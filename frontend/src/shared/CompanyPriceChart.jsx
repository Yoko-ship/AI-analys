import React from "react";
import { CHART_RANGES, QC_MAX, buildCompareAligned, chartRange, chartRangeCutoff, chartRangeSpan } from "./priceChartModel.jsx";
import { DOWN as LW_DOWN, DOWN_FILL as LW_DOWN_FILL, DOWN_FILL_FAINT as LW_DOWN_FILL_FAINT, UP as LW_UP, UP_FILL as LW_UP_FILL, UP_FILL_FAINT as LW_UP_FILL_FAINT, calendarMA, customFormat as lwCustomFormat, heikinAshi as lwHeikinAshi, ohlcBar as lwOhlcBar, ohlcOk as lwOhlcOk, percentFormat as lwPercentFormat, priceFormatFor as lwPriceFormatFor, syntheticSeries as lwSyntheticSeries, toTime as lwTime, uniqueByTime as lwUniqueByTime } from "../charts/lwCore.js";
import { PatternList, PatternMenuItems, applyPatternOverlay, patternKey, patternOverlay, usePatterns } from "./Patterns.jsx";
import { threshold as cfgThreshold } from "../lib/flags.js";
import { LineType as LwLineType } from "lightweight-charts";
import { compact as fmtCompact } from "../lib/format.js";
import { fmtRelVol, peerVolumeAt, relativeVolume } from "./volume.js";
import { signedFixed } from "./format.jsx";
import LwCanvas from "../charts/LwCanvas.jsx";
import { patternName } from "../lib/patterns.js";

function aggregateCompanyPricePoints(points, interval) {
  if (interval === "D") return points;
  const buckets = [];
  let current = null;
  for (const point of points) {
    const day = String(point.date || "").slice(0, 10);
    const date = new Date(`${day}T00:00:00Z`);
    if (!day || Number.isNaN(date.getTime())) continue;
    let key;
    if (interval === "W") {
      const monday = new Date(date.getTime() - ((date.getUTCDay() + 6) % 7) * 864e5);
      key = `W:${monday.toISOString().slice(0, 10)}`;
    } else {
      key = `M:${day.slice(0, 7)}`;
    }
    if (!current || current.key !== key) {
      current = {
        key,
        date: point.date,
        open: point.open > 0 ? point.open : point.close,
        high: point.high > 0 ? point.high : point.close,
        low: point.low > 0 ? point.low : point.close,
        close: point.close,
        volume: point.volume || 0,
        turnover: point.turnover || 0,
        change: point.change,
      };
      buckets.push(current);
    } else {
      current.date = point.date;
      current.high = Math.max(current.high, point.high > 0 ? point.high : point.close);
      current.low = Math.min(current.low, point.low > 0 ? point.low : point.close);
      current.close = point.close;
      current.volume += point.volume || 0;
      current.turnover += point.turnover || 0;
      current.change = point.change;
    }
  }
  return buckets.map(({ key, ...point }) => point);
}

function CompanyChartToolIcon({ kind }) {
  let content = null;
  if (kind === "pointer") content = (
    <>
      <rect x="4" y="3.5" width="11" height="15" rx="1.5" />
      <path d="M7 7h5M7 10h4M13 12l6 3-3 1.2 1.7 3-1.8 1-1.7-3-1.2 2z" />
    </>
  );
  if (kind === "candle") content = (
    <>
      <path d="M7 3v18M17 4v16" />
      <rect x="4.5" y="7" width="5" height="8" rx="1" />
      <rect x="14.5" y="9" width="5" height="7" rx="1" />
    </>
  );
  if (kind === "compare") content = (
    <>
      <path d="M3 17l5-5 4 3 5-7" />
      <circle cx="3" cy="17" r="1" fill="currentColor" stroke="none" />
      <circle cx="8" cy="12" r="1" fill="currentColor" stroke="none" />
      <path d="M19 13v7M15.5 16.5h7" />
    </>
  );
  if (kind === "draw") content = (
    <>
      <path d="M4 18L18 5" />
      <circle cx="4" cy="18" r="2" />
      <circle cx="18" cy="5" r="2" />
      <path d="M7 20h10" strokeDasharray="2 2" opacity=".65" />
    </>
  );
  if (kind === "patterns") content = (
    <>
      <path d="M3 17l4-8 4 6 4-10 6 12" />
      <path d="M3 13h18" strokeDasharray="2 2" opacity=".6" />
    </>
  );
  if (kind === "settings") content = (
    <>
      <path d="M3 7h18M3 17h18" />
      <circle cx="9" cy="7" r="2.2" fill="var(--panel)" />
      <circle cx="16" cy="17" r="2.2" fill="var(--panel)" />
    </>
  );
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {kind === "fx"
        ? <text x="3.5" y="17" fill="currentColor" stroke="none" fontSize="14" fontStyle="italic">ƒx</text>
        : content}
    </svg>
  );
}

const CPC_COMPARISON_TYPES = new Set(["line", "area", "baseline", "columns"]);

const CPC_SYNTHETIC_TYPES = new Set(["kagi", "point_figure", "renko"]);

function CompanyPriceChart({ history, loading, range, onRangeChange, adjustments, lang, quality, metricsWindows,
                             ticker, compare, compareLoading, compareTools, onExpand, intraday }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const [hover, setHover] = React.useState(null);
  const [maOn, setMaOn] = React.useState({ ma20: false, ma50: false });
  const [chartInterval, setChartInterval] = React.useState("D");
  const [chartType, setChartType] = React.useState("area");
  const [cursorOn, setCursorOn] = React.useState(true);
  const [toolMenu, setToolMenu] = React.useState(null);
  const [drawMode, setDrawMode] = React.useState(false);
  const [drawingPoints, setDrawingPoints] = React.useState([]);
  const [chartPrefs, setChartPrefs] = React.useState({ grid: true, fill: true, lastPrice: true, events: true, volume: false });
  const [visible, setVisible] = React.useState(null);
  const [resetToken, setResetToken] = React.useState(0);
  const [patternsOn, setPatternsOn] = React.useState({ chart: false, candle: false, cycle: false });
  const [sensitivity, setSensitivity] = React.useState("medium");
  const [selectedPattern, setSelectedPattern] = React.useState(null);
  const [focus, setFocus] = React.useState(null);
  // «Час» on a range longer than a week: every hourly bar the bank holds (60
  // days, from the day the collector first stored them). 1Д/1Н already get
  // their own hourly bars through `intraday`.
  const hourMode = chartInterval === "H" && !chartRange(range).hourly;
  const [longIntraday, setLongIntraday] = React.useState(null);
  React.useEffect(() => {
    if (!hourMode || !ticker) { setLongIntraday(null); return undefined; }
    let alive = true;
    fetch(`/api/intraday/${encodeURIComponent(ticker)}?days=60`)
      .then((r) => r.json())
      .then((d) => { if (alive) setLongIntraday(d.ok ? (d.points || []) : []); })
      .catch(() => { if (alive) setLongIntraday([]); });
    return () => { alive = false; };
  }, [hourMode, ticker]);
  React.useEffect(() => { setSelectedPattern(null); }, [ticker, sensitivity]);
  const toolStripRef = React.useRef(null);
  const selectedCompareKey = (compareTools?.selected || []).join(",");
  // 340…660px, 58 % of the window: shorter cannot show a candle body, taller
  // pushes «О компании» off the fold on a laptop.
  const [chartPx, setChartPx] = React.useState(() => (typeof window === "undefined" ? 420
    : Math.max(340, Math.min(660, window.innerHeight * 0.58))));
  React.useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onResize = () => setChartPx(Math.max(340, Math.min(660, window.innerHeight * 0.58)));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  React.useEffect(() => {
    setChartInterval("D");
    setToolMenu(null);
    setDrawMode(false);
    setDrawingPoints([]);
  }, [ticker, range]);
  React.useEffect(() => {
    setDrawingPoints([]);
    setDrawMode(false);
  }, [chartInterval, selectedCompareKey, chartType]);
  React.useEffect(() => {
    if (!toolMenu || typeof document === "undefined") return undefined;
    const closeOutside = (event) => {
      if (!toolStripRef.current?.contains(event.target)) setToolMenu(null);
    };
    const closeEscape = (event) => { if (event.key === "Escape") setToolMenu(null); };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeEscape);
    };
  }, [toolMenu]);

  // ── The series, by the same rules the SVG chart used ─────────────────────
  const model = React.useMemo(() => {
    // The feed returns newest-first — sort ascending so time reads left→right.
    const rawDaily = (history || []).map((h) => {
      if (Array.isArray(h)) return { date: h[0], open: null, high: null, low: null, close: Number(h[1]) || 0, volume: 0, turnover: Number(h[2]) || 0, change: null };
      return {
        date: h.date || h.trade_date,
        open: h.open != null ? Number(h.open) : null,
        high: h.high != null ? Number(h.high) : null,
        low: h.low != null ? Number(h.low) : null,
        close: Number(h.close ?? h.price ?? h.close_price ?? 0),
        volume: Number(h.volume ?? h.trading_volume ?? 0) || 0,
        // «Объём» on this site means MONEY — the landing board says «Объём
        // торгов · 4,57 млрд сум» — so the chart means the same thing by it.
        turnover: Number(h.value ?? h.trading_value ?? 0) || 0,
        change: h.change != null ? Number(h.change) : null,
      };
    }).filter((p) => p.close > 0 && p.date).sort((a, b) => String(a.date).localeCompare(String(b.date)));
    const daily = lwUniqueByTime(rawDaily);

    // The endpoint's smallest unit is a month, so 1Н and YTD ask for the
    // month(s) that contain them and are trimmed here.
    let cutoff = chartRangeCutoff(range);
    if (!cutoff && range !== "max") {
      const spanMonths = chartRangeSpan(range);
      if (spanMonths) {
        const d = new Date(daily.at(-1)?.date || Date.now());
        d.setUTCMonth(d.getUTCMonth() - spanMonths);
        cutoff = d.toISOString().slice(0, 10);
      }
    }
    // Peer compare stays on daily closes: the peers arrive as daily series.
    // On 1Д the peers are dropped instead — a session of hourly bars has no
    // dates a daily peer series could be sampled on.
    const peersOn = Boolean((compare || []).some((s) => s.points && s.points.length));
    const hourlyRange = Boolean(chartRange(range).hourly);
    const hourlyRaw = hourlyRange && (range === "1d" || !peersOn)
      ? (intraday || []).map((h) => ({
          date: h.date,
          open: h.open != null ? Number(h.open) : null,
          high: h.high != null ? Number(h.high) : null,
          low: h.low != null ? Number(h.low) : null,
          close: Number(h.close ?? 0),
          volume: Number(h.volume ?? 0) || 0,
          turnover: Number(h.value ?? 0) || 0,
          change: null,
        })).filter((p) => p.close > 0 && p.date)
          .sort((a, b) => String(a.date).localeCompare(String(b.date)))
      : [];
    const hourly = lwUniqueByTime(hourlyRaw);
    let windowed;
    if (range === "1d") {
      // The newest banked SESSION, not the last 24 hours: on a Sunday «1Д» is Friday.
      const lastDay = hourly.length ? String(hourly.at(-1).date).slice(0, 10) : null;
      windowed = lastDay ? hourly.filter((p) => String(p.date).startsWith(lastDay)) : [];
    } else if (hourly.length) {
      // 1Н: hourly bars where the bank has them, the settled daily close where
      // it does not. "2026-08-17" < "2026-08-17T10:00" as strings, so one sort holds.
      const covered = new Set(hourly.map((p) => String(p.date).slice(0, 10)));
      const merged = [...daily.filter((p) => !covered.has(String(p.date).slice(0, 10))), ...hourly]
        .sort((a, b) => String(a.date).localeCompare(String(b.date)));
      windowed = cutoff ? merged.filter((p) => String(p.date) >= cutoff) : merged;
    } else {
      windowed = cutoff ? daily.filter((p) => String(p.date) >= cutoff) : daily;
    }
    // Period buttons choose the first view; they do not discard the rest of
    // the daily archive, which stays reachable by dragging.
    const historyNavigation = !hourlyRange && daily.length >= 2;
    if (chartInterval === "H" && !hourlyRange) {
      const bars = lwUniqueByTime((longIntraday || []).map((h) => ({
        date: h.date,
        open: h.open != null ? Number(h.open) : null,
        high: h.high != null ? Number(h.high) : null,
        low: h.low != null ? Number(h.low) : null,
        close: Number(h.close ?? 0),
        volume: Number(h.volume ?? 0) || 0,
        turnover: Number(h.value ?? 0) || 0,
        change: null,
      })).filter((p) => p.close > 0 && p.date).sort((a, b) => String(a.date).localeCompare(String(b.date))));
      // The range's window, cut to where hourly bars exist at all.
      const from = String(windowed[0]?.date || "");
      const inRange = bars.filter((p) => String(p.date) >= from);
      return { daily, cutoff, hourlyRange, windowed, historyNavigation: bars.length > 0, hourBars: true,
               source: bars, rangeWindow: inRange.length ? inRange : bars };
    }
    const source = historyNavigation ? aggregateCompanyPricePoints(daily, chartInterval) : windowed;
    const rangeWindow = historyNavigation ? aggregateCompanyPricePoints(windowed, chartInterval) : windowed;
    return { daily, cutoff, hourlyRange, windowed, historyNavigation, source, rangeWindow };
  }, [history, intraday, range, compare, chartInterval, longIntraday]);

  const { daily, cutoff, windowed, historyNavigation } = model;
  const stepLine = quality ? quality.candles_enabled === false : false;
  const cmp = React.useMemo(() => (range === "1d" || model.hourBars ? null
    : buildCompareAligned(model.source, compare, model.rangeWindow[0]?.date)), [range, model, compare]);
  const cmpOn = Boolean(cmp && cmp.series.length);
  const effectiveChartType = cmpOn && !CPC_COMPARISON_TYPES.has(chartType) ? "line" : chartType;
  const synthetic = CPC_SYNTHETIC_TYPES.has(effectiveChartType);
  // A synthetic figure is built from the range's closes and has no calendar;
  // everything else draws the whole loaded archive and opens on the range.
  const points = synthetic ? model.rangeWindow : model.source;
  const baseVals = React.useMemo(() => (cmpOn ? cmp.basePct : points.map((p) => p.close)), [cmpOn, cmp, points]);

  // Patterns are read off daily sessions in сумы: not a percent comparison, a
  // weekly bucket, an hourly bar or a synthetic figure.
  const patternsWanted = patternsOn.chart || patternsOn.candle || patternsOn.cycle;
  const patternsAvailable = !synthetic && !cmpOn && chartInterval === "D" && !model.hourlyRange;
  const patternData = usePatterns(ticker, patternsWanted, sensitivity);
  const shownPatterns = React.useMemo(() => (patternsAvailable && patternData?.signals
    ? patternData.signals.filter((s) => (s.family === "chart" ? patternsOn.chart : patternsOn.candle)) : []),
  [patternsAvailable, patternData, patternsOn]);
  // Names on the chart up to about a year of sessions in view; wider, the
  // markers stay and the names live in the list and the tooltip.
  const patternLabels = Boolean(visible) && visible.to - visible.from <= 300;

  const MA_DAYS = {
    ma20: metricsWindows?.ma20 || cfgThreshold("moving_average.ma20_calendar_days", 28),
    ma50: metricsWindows?.ma50 || cfgThreshold("moving_average.ma50_calendar_days", 70),
  };
  const maSeries = React.useMemo(() => ({
    ma20: calendarMA(daily, MA_DAYS.ma20),
    ma50: calendarMA(daily, MA_DAYS.ma50),
  }), [daily, MA_DAYS.ma20, MA_DAYS.ma50]);
  const ma20Available = maSeries.ma20.some((v) => v != null);
  const ma50Available = maSeries.ma50.some((v) => v != null);

  // Splits and bonus issues inside the drawn span. The prices either side are
  // already in one unit (the server restated the older half), but the day the
  // share count changed is still named — otherwise a reader checking a 2024
  // close against uzse.uz finds a different number and no explanation.
  const eventMarks = React.useMemo(() => (synthetic ? [] : (adjustments || [])
    .map((a) => ({ ...a, i: points.findIndex((p) => String(p.date) >= String(a.ex_date)) }))
    .filter((a) => a.i > 0)), [adjustments, points, synthetic]);

  const up = baseVals.length >= 2
    ? baseVals.at(-1) >= (cmpOn ? 0 : (model.rangeWindow[0]?.close ?? baseVals[0]))
    : true;
  const color = up ? LW_UP : LW_DOWN;

  // ── The spec the canvas draws ────────────────────────────────────────────
  const spec = React.useMemo(() => {
    if (points.length < 1) return null;
    const times = points.map((p) => lwTime(p.date));
    const lastPriceOpts = { lastValueVisible: chartPrefs.lastPrice, priceLineVisible: chartPrefs.lastPrice };
    const priceFormat = cmpOn ? lwPercentFormat(lang) : lwPriceFormatFor(points.at(-1).close, lang);
    const series = [];
    const lineType = stepLine ? LwLineType.WithSteps : LwLineType.Simple;
    const valueData = points.map((p, i) => ({ time: times[i], value: baseVals[i] }));
    const trend = drawingPoints.map((d) => ({ time: d.time, value: d.value }));
    const markers = [];
    if (chartPrefs.events) {
      const bonus = lang === "en" || lang === "uz" ? "Bonus" : "Бонус";
      const split = lang === "en" || lang === "uz" ? "Split" : "Сплит";
      eventMarks.forEach((m) => markers.push({ time: times[m.i], position: "aboveBar", color: "#8b82f0", shape: "arrowDown",
        text: m.kind === "bonus" ? bonus : split }));
    }
    // ТЗ §6: on a step chart a move that stopped exactly at the ±20 % daily
    // limit is marked — a rule of the exchange, not a decision of the market.
    if (stepLine && !synthetic) {
      points.forEach((p, i) => {
        const prev = i > 0 ? points[i - 1].close : null;
        const move = prev ? ((p.close - prev) / prev) * 100 : null;
        if (move != null && Math.abs(Math.abs(move) - 20) < 0.5) {
          markers.push({ time: times[i], position: "inBar", color: "#fbbf24", shape: "square", size: 0.6 });
        }
      });
    }
    markers.sort((a, b) => a.time - b.time);
    let labels = null;

    if (synthetic) {
      const syn = lwSyntheticSeries(effectiveChartType, points);
      labels = syn.labels;
      series.push({
        key: "price", kind: syn.kind, data: syn.data,
        options: syn.kind === "line"
          ? { ...lastPriceOpts, lineType: LwLineType.WithSteps, lineWidth: 2, priceFormat }
          : effectiveChartType === "point_figure"
            ? { ...lastPriceOpts, priceFormat, upColor: "rgba(0,0,0,0)", downColor: "rgba(0,0,0,0)",
                borderVisible: false, wickVisible: false }
            : { ...lastPriceOpts, priceFormat, upColor: LW_UP_FILL, downColor: LW_DOWN_FILL,
                borderUpColor: LW_UP, borderDownColor: LW_DOWN, wickVisible: false },
        glyphs: syn.glyphs ? { columns: syn.glyphs, box: syn.box } : null,
      });
    } else if (["candle", "heikin_ashi", "bars"].includes(effectiveChartType)) {
      const src = effectiveChartType === "heikin_ashi" ? lwHeikinAshi(points) : points;
      series.push({
        key: "price", kind: effectiveChartType === "bars" ? "bar" : "candle",
        data: src.map((p, i) => lwOhlcBar(p, times[i])),
        options: effectiveChartType === "bars"
          ? { ...lastPriceOpts, priceFormat, upColor: LW_UP, downColor: LW_DOWN, thinBars: false }
          : { ...lastPriceOpts, priceFormat, upColor: LW_UP, downColor: LW_DOWN, borderVisible: false, wickUpColor: LW_UP, wickDownColor: LW_DOWN },
        markers, trend,
      });
    } else if (effectiveChartType === "columns") {
      series.push({
        key: "price", kind: "histogram",
        data: valueData.map((d, i) => ({ ...d, color: i && d.value < valueData[i - 1].value ? LW_DOWN : LW_UP })),
        options: { ...lastPriceOpts, priceFormat, base: cmpOn ? 0 : undefined },
        markers, trend,
      });
    } else if (effectiveChartType === "baseline") {
      series.push({
        key: "price", kind: "baseline", data: valueData,
        options: { ...lastPriceOpts, priceFormat, lineType, lineWidth: 2,
          baseValue: { type: "price", price: cmpOn ? 0 : (model.rangeWindow[0]?.close ?? baseVals[0]) },
          topLineColor: LW_UP, bottomLineColor: LW_DOWN,
          topFillColor1: LW_UP_FILL, topFillColor2: LW_UP_FILL_FAINT,
          bottomFillColor1: LW_DOWN_FILL_FAINT, bottomFillColor2: LW_DOWN_FILL },
        markers, trend,
      });
    } else if (effectiveChartType === "area" && !cmpOn && chartPrefs.fill) {
      series.push({
        key: "price", kind: "area", data: valueData,
        options: { ...lastPriceOpts, priceFormat, lineType, lineColor: color, lineWidth: 2,
          topColor: up ? LW_UP_FILL : LW_DOWN_FILL, bottomColor: up ? LW_UP_FILL_FAINT : LW_DOWN_FILL_FAINT,
          pointMarkersVisible: stepLine && points.length <= 260 },
        markers, trend,
      });
    } else {
      series.push({
        key: "price", kind: "line", data: valueData,
        options: { ...lastPriceOpts, priceFormat, lineType, color, lineWidth: 2,
          pointMarkersVisible: stepLine && points.length <= 260 },
        markers, trend,
      });
    }

    if (cmpOn) {
      cmp.series.forEach((s) => {
        series.push({
          key: `cmp:${s.ticker}`, kind: "line",
          data: s.pct.map((v, i) => (v == null ? { time: times[i] } : { time: times[i], value: v })),
          options: { color: s.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: chartPrefs.lastPrice,
            crosshairMarkerRadius: 3, priceFormat },
        });
      });
    }

    // ТЗ §6: moving averages on the RAW DAILY series over a calendar window,
    // read off at each drawn point's date (a weekly bucket carries its last day).
    if (!synthetic && !model.hourlyRange) {
      const byDate = new Map(daily.map((p, i) => [p.date, i]));
      [["ma20", "#f59e0b"], ["ma50", "#a855f7"]].forEach(([k, maColor]) => {
        if (!maOn[k]) return;
        const arr = maSeries[k];
        const data = points.map((p, i) => {
          const v = arr[byDate.get(p.date)];
          return v == null ? { time: times[i] } : { time: times[i], value: cmpOn ? (v / cmp.base0 - 1) * 100 : v };
        });
        if (!data.some((d) => d.value != null)) return;
        series.push({ key: k, kind: "line", data,
          options: { color: maColor, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false,
            crosshairMarkerVisible: false, priceFormat } });
      });
    }

    if (shownPatterns.length) {
      applyPatternOverlay(series, patternOverlay(shownPatterns, times, lang, patternLabels,
        shownPatterns.find((sig) => patternKey(sig) === selectedPattern) || null));
    }

    if (chartPrefs.volume && !cmpOn && !synthetic) {
      series.push({
        key: "volume", kind: "histogram",
        data: points.map((p, i) => ({ time: times[i], value: p.turnover || 0,
          color: i && p.close < points[i - 1].close ? "rgba(238,106,96,0.45)" : "rgba(47,197,132,0.45)" })),
        options: { priceScaleId: "vol", priceFormat: lwCustomFormat((v) => fmtCompact(v, lang), 1), lastValueVisible: false, priceLineVisible: false },
        scale: { scaleMargins: { top: 0.82, bottom: 0 } },
      });
    }
    return { series, main: "price", percent: cmpOn, hourly: model.hourlyRange || Boolean(model.hourBars), labels };
  }, [points, baseVals, cmpOn, cmp, effectiveChartType, synthetic, stepLine, chartPrefs, maOn, maSeries, daily,
      eventMarks, drawingPoints, color, up, model, lang, shownPatterns, patternLabels, selectedPattern]);

  // The range button's window is the first view; synthetic and hourly views
  // are the whole of what they drew. A comparison opens on its shared start.
  const initialView = React.useMemo(() => {
    if (synthetic || !historyNavigation || range === "max" || !points.length) return null;
    const first = cmpOn ? points[cmp.baseIdx]?.date : model.rangeWindow[0]?.date;
    return first ? { from: lwTime(first), to: lwTime(points.at(-1).date) } : null;
  }, [synthetic, historyNavigation, range, points, cmpOn, cmp, model.rangeWindow]);
  const viewKey = `${ticker}|${range}|${chartInterval}|${synthetic ? effectiveChartType : "t"}|${cmpOn ? cmp.baseIdx : "-"}`;

  const rangeBar = (
    <div className="company-chart-ranges">
      {CHART_RANGES.map((r) => (
        <button key={r.key} type="button"
          className={`range-btn ${range === r.key ? "active" : ""}`}
          onClick={() => onRangeChange(r.key)}>
          {r.label[lang === "uz" ? 1 : lang === "en" ? 2 : 0]}
        </button>
      ))}
    </div>
  );

  if (loading) return <div className="chart-loading muted">{t("Загрузка...", "Yuklanmoqda...", "Loading...")}</div>;

  // A week with no executions is a fact about the security, not a failure to
  // load anything — «история недоступна» would be a lie about a page that has
  // years of it.
  const emptyNote = (msg) => (
    <div className="company-chart-wrap">
      <div className="company-chart-toolbar">{rangeBar}</div>
      <div className="muted" style={{ padding: "48px 0", textAlign: "center", fontSize: 14 }}>{msg}</div>
    </div>
  );
  if (range === "1d" && windowed.length === 0) {
    return emptyNote(t("В последних сессиях сделок не было — часовой график недоступен",
      "So'nggi sessiyalarda bitim bo'lmagan — soatlik grafik mavjud emas",
      "No trades in the recent sessions — no hourly view to draw"));
  }
  if (cutoff && !model.hourlyRange && windowed.length < 2 && daily.length >= 2) {
    return emptyNote(chartRange(range).ytd
      ? t("С начала года сделок не было", "Yil boshidan bitim bo'lmagan", "No trades since the start of the year")
      : chartRange(range).days
        ? t("За выбранные дни сделок не было", "Tanlangan kunlarda bitim bo'lmagan", "No trades in the selected days")
        : t("За выбранный период сделок не было", "Tanlangan davrda bitim bo'lmagan", "No trades in the selected period"));
  }
  if (model.hourBars && !spec) {
    // Picking another period resets the interval to «День».
    return emptyNote(longIntraday === null
      ? t("Загрузка часовых баров…", "Soatlik barlar yuklanmoqda…", "Loading hourly bars…")
      : t("По этой бумаге часовых баров нет — сделок за последние 60 дней не было. Выберите другой период, чтобы вернуться к дневным свечам.",
          "Bu qog'oz bo'yicha soatlik barlar yo'q — so'nggi 60 kunda bitim bo'lmagan. Kunlik shamlarga qaytish uchun boshqa davrni tanlang.",
          "No hourly bars for this security — it has not traded in the last 60 days. Pick another period to return to daily bars."));
  }
  if ((daily.length < 2 && windowed.length === 0) || !spec) {
    return emptyNote(t("История цен недоступна", "Narxlar tarixi mavjud emas", "Price history unavailable"));
  }

  const dateLocale = lang === "en" ? "en-US" : "ru-RU";
  const isHourly = (d) => String(d || "").includes("T");
  const fmtDate = (d, withYear) => {
    if (!d) return "";
    if (isHourly(d)) return new Date(d).toLocaleString(dateLocale, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    return new Date(d).toLocaleDateString(dateLocale, withYear ? { year: "2-digit", month: "short", day: "numeric" } : { month: "short", day: "numeric" });
  };
  const fmtFull = (v) => (v == null ? "—" : Number(v).toLocaleString(dateLocale, { maximumFractionDigits: 2 }));
  const fmtPct = (v) => `${signedFixed(v, 1)}%`;

  const onChartClick = ({ index, pane }) => {
    if (!drawMode || pane !== 0 || synthetic) return;
    const next = { time: lwTime(points[index].date), value: baseVals[index], date: String(points[index].date) };
    setDrawingPoints((current) => (current.length >= 2 ? [next] : [...current, next]));
    if (drawingPoints.length === 1) setDrawMode(false);
  };

  // A synthetic figure's bar is a brick or a column, not a session: the
  // readout names the date that completed it and the level it stands at.
  const synthBar = synthetic && hover != null ? spec.series[0].data[hover.index] : null;
  const hp = !cursorOn || drawMode || hover == null ? null
    : synthetic
      ? (synthBar ? { date: spec.labels?.get(synthBar.time), close: synthBar.close ?? synthBar.value, change: null } : null)
      : points[hover.index];
  // Measured on the full loaded series, not the drawn window, so the first
  // points of a 1М chart still have their history behind them.
  const relVol = hp && !synthetic ? relativeVolume(daily, hp.date, hp.turnover) : null;
  const selectedCompare = new Set(compareTools?.selected || []);
  const hasDrawing = drawMode || drawingPoints.length > 0;
  const hasChartOverlays = hasDrawing || maOn.ma20 || maOn.ma50 || selectedCompare.size > 0 || patternsWanted;
  const clearAllOverlays = () => {
    setDrawingPoints([]);
    setDrawMode(false);
    setMaOn({ ma20: false, ma50: false });
    setPatternsOn({ chart: false, candle: false, cycle: false });
    setSelectedPattern(null);
    compareTools?.onClear?.();
    setToolMenu(null);
    setHover(null);
  };
  const kindLabel = (kind) => kind === "bonus"
    ? t("бонусная эмиссия", "bonus emissiya", "bonus issue")
    : t("дробление", "aksiyalarni maydalash", "split");
  const visFrom = visible ? points[visible.from]?.date : null;
  const visTo = visible ? points[visible.to]?.date : null;
  const ttRight = hover && hover.point.x > (hover.width || 800) * 0.62;

  return (
    <div className="company-chart-wrap">
      <div className="company-chart-toolbar">
        {rangeBar}
        <div className="company-chart-opts">
          <div className="cpc-tool-strip" ref={toolStripRef}>
            <div className="cpc-tool-slot">
              <button type="button" className={`cpc-tool-btn ${toolMenu === "interval" ? "active" : ""}`}
                data-testid="company-chart-interval" aria-haspopup="menu" aria-expanded={toolMenu === "interval"}
                aria-label={t(`Интервал: ${chartInterval}`, `Interval: ${chartInterval}`, `Interval: ${chartInterval}`)}
                title={t("Интервал свечей", "Grafik intervali", "Chart interval")}
                disabled={!historyNavigation}
                onClick={() => setToolMenu((m) => m === "interval" ? null : "interval")}>{chartInterval === "H" ? t("1ч", "1s", "1h") : chartInterval}</button>
              {toolMenu === "interval" && (
                <div className="cpc-tool-menu" role="menu">
                  {[["H", "Час", "Soat", "Hour"], ["D", "День", "Kun", "Day"], ["W", "Неделя", "Hafta", "Week"], ["M", "Месяц", "Oy", "Month"]].map(([key, ru, uz, en]) => (
                    <button key={key} type="button" role="menuitemradio" aria-checked={chartInterval === key}
                      className={chartInterval === key ? "active" : ""}
                      onClick={() => { setChartInterval(key); setToolMenu(null); }}>{t(ru, uz, en)} <span>{key}</span></button>
                  ))}
                </div>
              )}
            </div>

            <button type="button" className={`cpc-tool-btn ${cursorOn ? "active" : ""}`}
              data-testid="company-chart-cursor" aria-pressed={cursorOn}
              aria-label={t("Перекрестие и подсказки", "Kursor va ko'rsatmalar", "Crosshair and tooltips")}
              title={t("Перекрестие и подсказки", "Kursor va ko'rsatmalar", "Crosshair and tooltips")}
              onClick={() => { setCursorOn((on) => !on); setHover(null); setToolMenu(null); }}>
              <CompanyChartToolIcon kind="pointer" />
            </button>

            <div className="cpc-tool-slot">
              <button type="button" className={`cpc-tool-btn ${toolMenu === "type" ? "active" : ""}`}
                data-testid="company-chart-type" aria-haspopup="menu" aria-expanded={toolMenu === "type"}
                aria-label={t("Вид графика", "Grafik turi", "Chart type")}
                title={t("Вид графика", "Grafik turi", "Chart type")}
                onClick={() => setToolMenu((m) => m === "type" ? null : "type")}>
                <CompanyChartToolIcon kind="candle" />
              </button>
              {toolMenu === "type" && (
                <div className="cpc-tool-menu" role="menu">
                  {[
                    ["line", "Линия", "Chiziq", "Line"],
                    ["area", "Область", "Maydon", "Area"],
                    ["baseline", "Базовая линия", "Asosiy chiziq", "Baseline"],
                    ["candle", "Свечи", "Shamlar", "Candle"],
                    ["bars", "Бары", "Barlar", "Bars"],
                    ["columns", "Колонки", "Ustunlar", "Columns"],
                    ["kagi", "Каги", "Kagi", "Kagi"],
                    ["point_figure", "Крестики-нолики", "Nuqta va shakl", "Point and Figure"],
                    ["heikin_ashi", "Хейкин Аши", "Heikin Ashi", "Heikin Ashi"],
                    ["renko", "Ренко", "Renko", "Renko"],
                  ].map(([key, ru, uz, en]) => (
                    <button key={key} type="button" role="menuitemradio" aria-checked={chartType === key}
                      className={chartType === key ? "active" : ""}
                      onClick={() => { setChartType(key); setToolMenu(null); }}>{t(ru, uz, en)}</button>
                  ))}
                </div>
              )}
            </div>

            <div className="cpc-tool-slot">
              <button type="button" className={`cpc-tool-btn ${selectedCompare.size ? "has-value" : ""} ${toolMenu === "compare" ? "active" : ""}`}
                data-testid="company-chart-compare" aria-haspopup="menu" aria-expanded={toolMenu === "compare"}
                aria-label={t("Добавить бумагу для сравнения", "Taqqoslash uchun qog'oz qo'shish", "Add comparison")}
                title={t("Сравнить", "Taqqoslash", "Compare")}
                onClick={() => setToolMenu((m) => m === "compare" ? null : "compare")}>
                <CompanyChartToolIcon kind="compare" />
              </button>
              {toolMenu === "compare" && (
                <div className="cpc-tool-menu cpc-tool-menu-wide" role="menu">
                  <strong>{t("Сравнить с", "Taqqoslash", "Compare with")}</strong>
                  {(compareTools?.peers || []).length ? (compareTools.peers || []).map((peer) => {
                    const tk = String(peer.ticker || "").toUpperCase();
                    const active = selectedCompare.has(tk);
                    return (
                      <button key={tk} type="button" role="menuitemcheckbox" aria-checked={active}
                        className={active ? "active" : ""}
                        disabled={!active && selectedCompare.size >= QC_MAX}
                        onClick={() => compareTools?.onToggle?.(tk)}>
                        <span>{peer.name || tk}</span><b>{tk}</b>
                      </button>
                    );
                  }) : <span className="cpc-tool-empty">{t("Нет доступных бумаг", "Qog'ozlar mavjud emas", "No securities available")}</span>}
                </div>
              )}
            </div>

            <button type="button" className={`cpc-tool-btn ${drawMode || drawingPoints.length ? "active" : ""}`}
              data-testid="company-chart-draw" aria-pressed={drawMode}
              aria-label={t("Линия тренда", "Trend chizig'i", "Trend line")}
              title={t("Линия тренда", "Trend chizig'i", "Trend line")}
              disabled={synthetic}
              onClick={() => { setDrawMode((on) => !on); setToolMenu(null); setHover(null); }}>
              <CompanyChartToolIcon kind="draw" />
            </button>

            <div className="cpc-tool-slot">
              <button type="button" className={`cpc-tool-btn ${maOn.ma20 || maOn.ma50 ? "has-value" : ""} ${toolMenu === "indicators" ? "active" : ""}`}
                data-testid="company-chart-indicators" aria-haspopup="menu" aria-expanded={toolMenu === "indicators"}
                aria-label={t("Индикаторы", "Indikatorlar", "Indicators")}
                title={t("Индикаторы", "Indikatorlar", "Indicators")}
                onClick={() => setToolMenu((m) => m === "indicators" ? null : "indicators")}>
                <CompanyChartToolIcon kind="fx" />
              </button>
              {toolMenu === "indicators" && (
                <div className="cpc-tool-menu cpc-tool-menu-right" role="menu">
                  <button type="button" role="menuitemcheckbox" aria-checked={maOn.ma20} disabled={!ma20Available}
                    className={maOn.ma20 ? "active" : ""}
                    onClick={() => setMaOn((s) => ({ ...s, ma20: !s.ma20 }))}>MA20 <span>{MA_DAYS.ma20} {t("дн.", "kun", "days")}</span></button>
                  <button type="button" role="menuitemcheckbox" aria-checked={maOn.ma50} disabled={!ma50Available}
                    className={maOn.ma50 ? "active" : ""}
                    onClick={() => setMaOn((s) => ({ ...s, ma50: !s.ma50 }))}>MA50 <span>{MA_DAYS.ma50} {t("дн.", "kun", "days")}</span></button>
                </div>
              )}
            </div>

            <div className="cpc-tool-slot">
              <button type="button" className={`cpc-tool-btn ${patternsWanted ? "has-value" : ""} ${toolMenu === "patterns" ? "active" : ""}`}
                data-testid="company-chart-patterns" aria-haspopup="menu" aria-expanded={toolMenu === "patterns"}
                aria-label={t("Паттерны", "Patternlar", "Patterns")}
                title={t("Паттерны", "Patternlar", "Patterns")}
                onClick={() => setToolMenu((m) => m === "patterns" ? null : "patterns")}>
                <CompanyChartToolIcon kind="patterns" />
              </button>
              {toolMenu === "patterns" && (
                <div className="cpc-tool-menu cpc-tool-menu-right" role="menu">
                  <PatternMenuItems patternsOn={patternsOn} setPatternsOn={setPatternsOn} sensitivity={sensitivity}
                    setSensitivity={setSensitivity} available={patternsAvailable} lang={lang} variant="cpc" />
                </div>
              )}
            </div>

            <div className="cpc-tool-slot">
              <button type="button" className={`cpc-tool-btn ${toolMenu === "settings" ? "active" : ""}`}
                data-testid="company-chart-settings" aria-haspopup="menu" aria-expanded={toolMenu === "settings"}
                aria-label={t("Настройки графика", "Grafik sozlamalari", "Chart settings")}
                title={t("Настройки графика", "Grafik sozlamalari", "Chart settings")}
                onClick={() => setToolMenu((m) => m === "settings" ? null : "settings")}>
                <CompanyChartToolIcon kind="settings" />
              </button>
              {toolMenu === "settings" && (
                <div className="cpc-tool-menu cpc-tool-menu-right cpc-settings-menu">
                  {[["grid", "Сетка", "To'r", "Grid"], ["fill", "Заливка", "To'ldirish", "Area fill"],
                    ["lastPrice", "Последняя цена", "So'nggi narx", "Last price"], ["events", "События", "Voqealar", "Events"],
                    ["volume", "Объём", "Hajm", "Volume"]].map(([key, ru, uz, en]) => (
                    <label key={key}>
                      <input type="checkbox" checked={chartPrefs[key]}
                        onChange={(event) => setChartPrefs((prefs) => ({ ...prefs, [key]: event.target.checked }))} />
                      <span>{t(ru, uz, en)}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          </div>
          {onExpand && (
            <button type="button" className="chart-expand-btn" onClick={onExpand}
              title={t("Развернуть в расширенный график", "Kengaytirilgan grafikka", "Expand to the advanced chart")}
              aria-label={t("Развернуть в расширенный график", "Kengaytirilgan grafikka", "Expand to the advanced chart")}>
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {model.hourBars && (
        <p className="cpc-tier-note muted" data-testid="cpc-hourly-note">
          {longIntraday === null
            ? t("Загрузка часовых баров…", "Soatlik barlar yuklanmoqda…", "Loading hourly bars…")
            : model.source.length
              ? t(`Часовые бары — из ленты сделок биржи; хранятся с ${new Date(model.source[0].date.slice(0, 10)).toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "2-digit" })}, раньше почасовых данных нет.`,
                  `Soatlik barlar — birja bitimlar lentasidan; ${model.source[0].date.slice(0, 10)} dan saqlanadi.`,
                  `Hourly bars come from the exchange's trade feed, stored from ${model.source[0].date.slice(0, 10)}; nothing hourly exists before that.`)
              : t("По этой бумаге часовых баров нет — сделок за последние 60 дней не было.",
                  "Bu qog'oz bo'yicha soatlik barlar yo'q — so'nggi 60 kunda bitim bo'lmagan.",
                  "No hourly bars for this security — it has not traded in the last 60 days.")}
        </p>
      )}

      {stepLine && (
        <p className="cpc-tier-note muted">
          {t("Цена показана ступенями — между сделками она не менялась",
             "Narx pog'onalar bilan ko'rsatilgan — bitimlar orasida u o'zgarmagan",
             "The price is drawn as steps — between trades it did not move")}
          {quality?.reason ? ` — ${quality.reason}` : ""}
          {"."}
        </p>
      )}

      <div className="cpc-plot">
        <LwCanvas spec={spec} height={chartPx} lang={lang} grid={chartPrefs.grid} crosshair={cursorOn}
          pan={!drawMode} viewKey={viewKey} initialView={initialView} resetToken={resetToken} focus={focus}
          onHover={setHover}
          onClick={onChartClick}
          onRange={(r) => setVisible((cur) => (cur && cur.from === r.from && cur.to === r.to && cur.changed === r.changed ? cur : r))}
          className={`company-price-chart ${cursorOn ? "is-inspect" : ""} ${drawMode ? "is-drawing" : ""}`}
          data-chart-type={effectiveChartType} data-chart-interval={chartInterval}
          data-series={spec.series.map((s) => s.key).join(",")}
          data-trend-points={drawingPoints.length} data-grid={chartPrefs.grid ? "on" : "off"}
          data-visible-bars={visible ? visible.to - visible.from + 1 : spec.series[0].data.length}
          data-patterns={shownPatterns.length}
          aria-label={historyNavigation
            ? t("График истории цены. Ctrl и колесо меняют масштаб, перетаскивание показывает историю.",
                "Narx tarixi grafigi. Ctrl va g'ildirak masshtabni o'zgartiradi, sudrash tarixni ko'rsatadi.",
                "Price history chart. Ctrl and the wheel zoom; drag to browse history.")
            : undefined} />

        {hp && (
          <div className="cpc-tooltip" style={{
            // Follows the pointer down the chart, then stops short of either
            // end so the readout never hangs outside the panel that frames it.
            top: `${Math.max(8, Math.min(hover.point.y - 40, chartPx - 150))}px`,
            ...(ttRight ? { right: `calc(100% - ${hover.point.x - 12}px)` } : { left: `${hover.point.x + 14}px` }),
          }}>
            <div className="cpc-tt-date">{fmtDate(hp.date, true)}</div>
            <div className="cpc-tt-row"><span>{synthetic ? t("Уровень", "Daraja", "Level") : t("Закрытие", "Yopilish", "Close")}</span><b>{fmtFull(hp.close)}</b></div>
            {lwOhlcOk(hp) && !synthetic && (
              <>
                <div className="cpc-tt-row"><span>{t("Откр.", "Ochil.", "Open")}</span><b>{fmtFull(hp.open)}</b></div>
                <div className="cpc-tt-row"><span>{t("Макс.", "Maks.", "High")}</span><b>{fmtFull(hp.high)}</b></div>
                <div className="cpc-tt-row"><span>{t("Мин.", "Min.", "Low")}</span><b>{fmtFull(hp.low)}</b></div>
              </>
            )}
            {!synthetic && (
              <div className="cpc-tt-row"><span>{t("Объём", "Hajm", "Volume")}</span>
                <b>{hp.turnover ? `${fmtCompact(hp.turnover, lang)} ${t("сум", "so'm", "UZS")}` : "—"}</b>
              </div>
            )}
            {relVol != null && (
              <div className="cpc-tt-row"><span>{t("Объём к среднему", "O'rtacha hajmga", "Vol vs avg")}</span>
                <b>{fmtRelVol(relVol, lang)}</b>
              </div>
            )}
            {!synthetic && shownPatterns.filter((sig) => sig.signal_date === String(hp.date).slice(0, 10)).map((sig) => (
              <div className="cpc-tt-row" key={`ttp${sig.type}`}>
                <span style={{ color: sig.direction === "bullish" ? LW_UP : LW_DOWN }}>{sig.direction === "bullish" ? "↑" : "↓"} {patternName(sig.type, lang)}</span>
              </div>
            ))}
            {hp.change != null && !synthetic && (
              <div className="cpc-tt-row"><span>{t("Изм.", "O'zg.", "Chg")}</span>
                <b style={{ color: hp.change >= 0 ? LW_UP : LW_DOWN }}>{hp.change >= 0 ? "+" : ""}{fmtFull(hp.change)}</b>
              </div>
            )}
            {/* While comparing, the readout states what the lines do: the move
                since the shared start, per security, with the peer's close
                beside it so the percentage can be checked against a price. */}
            {cmpOn && (
              <div className="cpc-tt-cmp">
                <div className="cpc-tt-row">
                  <span style={{ color }}>{ticker || t("Эта бумага", "Bu qog'oz", "This security")}</span>
                  <b style={{ color }}>{fmtPct(baseVals[hover.index])}</b>
                </div>
                {cmp.series.map((s) => {
                  const pv = peerVolumeAt(s.volHist, String(hp.date).slice(0, 10));
                  return (
                    <React.Fragment key={`tt${s.ticker}`}>
                      <div className="cpc-tt-row">
                        <span style={{ color: s.color }}>{s.ticker}</span>
                        <b style={{ color: s.color }}>
                          {s.pct[hover.index] == null ? "—" : fmtPct(s.pct[hover.index])}
                          {s.closes[hover.index] != null && (
                            <span className="cpc-tt-cmp-price"> · {fmtFull(s.closes[hover.index])}</span>
                          )}
                        </b>
                      </div>
                      <div className="cpc-tt-row cpc-tt-volrow">
                        <span>{t("объём", "hajm", "vol")}</span>
                        <b>{pv
                          ? `${fmtCompact(pv.turnover, lang)}${pv.rel != null ? ` · ${fmtRelVol(pv.rel, lang)}` : ""}`
                          : "—"}</b>
                      </div>
                    </React.Fragment>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {hasChartOverlays && (
        <p className="cpc-draw-status" role="status">
          <span>{hasDrawing
            ? (drawMode
                ? (drawingPoints.length === 0
                    ? t("Линия тренда: выберите первую точку", "Trend chizig'i: birinchi nuqtani tanlang", "Trend line: choose the first point")
                    : t("Линия тренда: выберите вторую точку", "Trend chizig'i: ikkinchi nuqtani tanlang", "Trend line: choose the second point"))
                : t("Линия тренда добавлена", "Trend chizig'i qo'shildi", "Trend line added"))
            : t("На график добавлены элементы", "Grafikka elementlar qo'shildi", "Chart overlays added")}</span>
          {hasDrawing && (
            <button type="button" onClick={() => { setDrawingPoints([]); setDrawMode(false); }}>
              {t("Очистить", "Tozalash", "Clear")}
            </button>
          )}
          <button type="button" className="cpc-clear-all" data-testid="company-chart-clear-all"
            onClick={clearAllOverlays}>
            {t("Очистить всё", "Hammasini tozalash", "Clear all")}
          </button>
        </p>
      )}

      {historyNavigation && !synthetic && visFrom && (
        <p className="cpc-history-help" data-testid="company-visible-range" data-from={visFrom} data-to={visTo}>
          <span>
            {t("Ctrl + колесо: вверх — приблизить, вниз — отдалить; потяните график — перейти по истории.",
               "Ctrl + g'ildirak: yuqoriga — yaqinlashtirish, pastga — uzoqlashtirish; tarix uchun grafikni suring.",
               "Ctrl + wheel: up zooms in, down zooms out; drag the chart to browse history.")}
          </span>
          <span className="cpc-history-dates">{fmtDate(visFrom, true)} — {fmtDate(visTo, true)}</span>
          {visible?.changed && (
            <button type="button" className="cpc-history-reset" onClick={() => setResetToken((n) => n + 1)}>
              {t("Сбросить", "Tiklash", "Reset")}
            </button>
          )}
        </p>
      )}

      {patternsWanted && (patternsAvailable || patternsOn.cycle ? (
        <PatternList data={patternData} signals={shownPatterns} lang={lang} visibleFrom={visFrom} visibleTo={visTo}
          families={{ chart: patternsAvailable && patternsOn.chart, candle: patternsAvailable && patternsOn.candle,
                      cycle: patternsOn.cycle }}
          selectedKey={selectedPattern}
          onPick={(sig) => {
            setSelectedPattern(patternKey(sig));
            setFocus({ from: lwTime(sig.start_date) - 10 * 86400, to: lwTime(sig.exit_date || sig.signal_date) + 10 * 86400 });
          }} />
      ) : (
        <p className="pattern-note muted" data-testid="pattern-list">
          {t("Паттерны строятся по дневным свечам в сумах — без сравнения, недельных баров и синтетических видов.",
             "Patternlar kunlik shamlarda quriladi — taqqoslash, haftalik barlar va sintetik turlarsiz.",
             "Patterns are read off daily bars in сум — not while comparing, on weekly bars or synthetic types.")}
        </p>
      ))}

      {synthetic && (
        <p className="cpc-tier-note muted cpc-synthetic-note">
          {t("Расчётный вид по ценам закрытия выбранного периода; значения фигур синтетические и не являются ценами сделок.",
             "Tanlangan davr yopilish narxlari asosidagi hisobiy ko‘rinish; shakl qiymatlari sintetik va bitim narxlari emas.",
             "Calculated from the period's closes; figure values are synthetic and are not traded prices.")}
        </p>
      )}

      {/* Two facts about a comparison the chart cannot draw: the stored quote
          history begins in Aug 2025, so a peer can move the shared start — and
          a security with no stored session in the window has no line at all. */}
      {cmpOn && cmp.start && (
        <p className="cpc-tier-note muted">
          {t(`Сравнение считается с ${fmtDate(cmp.start, true)} — раньше сохранённых котировок нет; шкала показывает изменение в процентах от этого дня.`,
             `Taqqoslash ${fmtDate(cmp.start, true)} dan hisoblanadi — undan oldingi saqlangan kotirovkalar yo'q; shkala shu kundan foizdagi o'zgarishni ko'rsatadi.`,
             `The comparison starts on ${fmtDate(cmp.start, true)} — there are no stored quotes before it; the axis shows the percent move from that day.`)}
        </p>
      )}
      {cmp && cmp.dropped.length > 0 && !compareLoading && (
        <p className="cpc-tier-note muted">
          {t("Нет сохранённых котировок за этот период: ", "Bu davr uchun saqlangan kotirovkalar yo'q: ", "No stored quotes for this period: ")}
          {cmp.dropped.map((c) => c.ticker).join(", ")}
        </p>
      )}

      {chartPrefs.events && eventMarks.length > 0 && (
        <p className="cpc-adjust-note">
          {t("Цены до этих дат пересчитаны на текущую акцию",
             "Bu sanalargacha boʻlgan narxlar joriy aksiyaga qayta hisoblangan",
             "Prices before these dates are restated onto the current share")}
          {": "}
          {eventMarks.map((m, i) => (
            <React.Fragment key={m.ex_date}>
              {i > 0 && "; "}
              {fmtDate(m.ex_date, true)} — {kindLabel(m.kind)} ×{fmtFull(m.ratio)}
            </React.Fragment>
          ))}
          {t(". На бирже они котировались в прежних долях.",
             ". Birjada ular eski ulushlarda kotirovka qilingan.",
             ". The exchange quoted them in the old units.")}
        </p>
      )}
    </div>
  );
}

export { CompanyChartToolIcon, CompanyPriceChart, aggregateCompanyPricePoints };
