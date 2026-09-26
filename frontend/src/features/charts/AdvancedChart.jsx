import { prepareMarketRows } from "../../lib/marketData.js";
import React from "react";
import { CHART_RANGES, QC_COLORS, QC_MAX, buildCompareAligned, chartRange, chartRangeCutoff, chartRangeMonths, chartRangeSpan, quickComparePeers } from "../../shared/priceChartModel.jsx";
import { DOWN as LW_DOWN, DOWN_FILL as LW_DOWN_FILL, DOWN_FILL_FAINT as LW_DOWN_FILL_FAINT, UP as LW_UP, UP_FILL as LW_UP_FILL, UP_FILL_FAINT as LW_UP_FILL_FAINT, customFormat as lwCustomFormat, heikinAshi as lwHeikinAshi, ohlcBar as lwOhlcBar, ohlcOk as lwOhlcOk, percentFormat as lwPercentFormat, priceFormatFor as lwPriceFormatFor, syntheticSeries as lwSyntheticSeries, toTime as lwTime, uniqueByTime as lwUniqueByTime } from "../../charts/lwCore.js";
import { CompanyChartToolIcon, aggregateCompanyPricePoints } from "../../shared/CompanyPriceChart.jsx";
import { AC_COMPARISON_TYPES, AC_FIN_COLORS, AC_FIN_FIELDS, AC_FIN_MAX, AC_INDICATORS, AC_OHLC_TYPES, AC_SYNTHETIC_TYPES, AC_TYPES, AC_TYPE_ICONS, acFinIsRate, acFinancialAtDates } from "../../shared/advancedChartModel.jsx";
import { PatternList, PatternMenuItems, applyPatternOverlay, patternKey, patternOverlay, usePatterns } from "../../shared/Patterns.jsx";
import { alignToDates as indAlign, bollinger as indBollinger, calendarSeries as indCalendar, ema as indEma, macd as indMacd, rsi as indRsi, sma as indSma, stochastic as indStochastic } from "../../lib/indicators.js";

import { fmtRelVol, peerVolumeAt, relativeVolume } from "../../shared/volume.js";
import { signedFixed } from "../../shared/format.jsx";
import { LineType as LwLineType } from "lightweight-charts";
import { compact as fmtCompact } from "../../lib/format.js";
import { finLabel } from "../../shared/financialLabels.jsx";
import { CompanyLogo } from "../../shared/CompanyLogo.jsx";
import { formatMarketNumber } from "../../shared/format.jsx";
import { AdvancedChartRail, AdvancedCompareBar } from "./CompareRail.jsx";
import LwCanvas from "../../charts/LwCanvas.jsx";
import { patternName } from "../../lib/patterns.js";
import { TechnicalBacktestCard } from "./TechnicalBacktest.jsx";

function AdvancedChart({ ticker, securitiesMap, marketRows, tradeStats, lang, favorites,
                         onToggleFavorite, signedIn, hasProAccess = false, apiFetch = fetch,
                         onUpgrade, onBack, onOpenCompany, onOpenChart, initial }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const up = String(ticker || "").toUpperCase();

  // ── State the URL carries, so an advanced chart can be linked to ──────────
  const [range, setRange] = React.useState(initial?.range || "1y");
  const [span, setSpan] = React.useState({ from: initial?.from || "", to: initial?.to || "" });
  const [type, setType] = React.useState(initial?.type || "line");
  // The bar each point stands for: a session, or a week / month rolled up
  // from the sessions (last close, high/low envelope, summed turnover).
  const [barInterval, setBarInterval] = React.useState(["H", "W", "M"].includes(initial?.interval) ? initial.interval : "D");
  const [indicators, setIndicators] = React.useState(() => new Set(initial?.indicators || []));
  const [finFields, setFinFields] = React.useState(initial?.fin || []);
  const [compareTickers, setCompareTickers] = React.useState(initial?.compare || []);
  const [menu, setMenu] = React.useState(null);            // "ind" | "fin" | "cmp" | null
  const [cursorOn, setCursorOn] = React.useState(true);
  const [drawMode, setDrawMode] = React.useState(false);
  const [drawPoints, setDrawPoints] = React.useState([]);
  const [isFullscreen, setIsFullscreen] = React.useState(false);
  const chartShellRef = React.useRef(null);
  const [railOpen, setRailOpen] = React.useState(() => (typeof window === "undefined"
    ? true
    : !window.matchMedia("(max-width: 900px)").matches));

  React.useEffect(() => {
    if (!menu || typeof document === "undefined") return undefined;
    const closeMenu = (event) => {
      if (event.key === "Escape") setMenu(null);
    };
    document.addEventListener("keydown", closeMenu);
    return () => document.removeEventListener("keydown", closeMenu);
  }, [menu]);

  // Full-screen here means the chart workspace fills the browser viewport,
  // while keeping every period, indicator and comparison control reachable.
  // Lock the page underneath it and make Escape behave like a native dialog.
  React.useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const onFullscreenChange = () => setIsFullscreen(document.fullscreenElement === chartShellRef.current);
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);

  React.useEffect(() => {
    if (!isFullscreen || typeof document === "undefined") return undefined;
    const previousOverflow = document.body.style.overflow;
    const onKeyDown = (event) => {
      if (event.key !== "Escape") return;
      // Browsers leave native full screen on Esc themselves; one that did not
      // (a headless or embedded one) would keep the chart in the top layer,
      // over the whole page, after the workspace had already restored.
      if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
      setIsFullscreen(false);
    };
    document.body.style.overflow = "hidden";
    document.body.classList.add("advanced-chart-fullscreen");
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.body.classList.remove("advanced-chart-fullscreen");
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isFullscreen]);

  const toggleFullscreen = async () => {
    const node = chartShellRef.current;
    if (!node || typeof document === "undefined") return;
    try {
      if (document.fullscreenElement === node) await document.exitFullscreen();
      else if (node.requestFullscreen) await node.requestFullscreen();
      else setIsFullscreen((value) => !value);
    } catch {
      setIsFullscreen((value) => !value);
    }
  };

  const [history, setHistory] = React.useState(null);
  const [adjustments, setAdjustments] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [failed, setFailed] = React.useState(false);
  const [retry, setRetry] = React.useState(0);
  const [quality, setQuality] = React.useState(null);
  const [sec, setSec] = React.useState((securitiesMap || {})[up] || {});
  const [fin, setFin] = React.useState(null);
  const [cmpSeries, setCmpSeries] = React.useState({});
  const [cmpLoading, setCmpLoading] = React.useState(false);

  const custom = Boolean(span.from && span.to);
  // How much history to ask for. A custom span asks back to its own start; the
  // buttons ask for what they show. Either way the fetch is a MONTH count,
  // which is the only unit /api/price-history understands. Every chart type
  // keeps the archive behind the selected window so dragging can browse older
  // sessions instead of stopping at an artificial fetch edge.
  const months = React.useMemo(() => {
    if (!custom) return 360;
    if (!custom) return chartRangeMonths(range);
    const d = new Date(span.from);
    const now = new Date();
    if (Number.isNaN(d.getTime())) return chartRangeMonths(range);
    return Math.max(1, Math.min(360,
      (now.getFullYear() - d.getFullYear()) * 12 + (now.getMonth() - d.getMonth()) + 2));
  }, [custom, span.from, range, type]);

  React.useEffect(() => {
    if (!up) return undefined;
    let alive = true;
    setLoading(true);
    setFailed(false);
    fetch(`/api/price-history/${encodeURIComponent(up)}?months=${months}`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return;
        if (d.ok) { setHistory(d.points || []); setAdjustments(d.adjustments || []); }
        else setFailed(true);
      })
      .catch(() => { if (alive) setFailed(true); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [up, months, retry]);

  // 1Д and 1Н draw the same hourly bars as the company chart (/api/intraday),
  // so both surfaces show the same thing for the same button.
  const hourlyRange = !custom && Boolean(chartRange(range).hourly);
  // «Час» on a longer range: every hourly bar the bank holds (it keeps 60
  // days, and starts the day the collector first stored them), opened on the
  // range the button asked for.
  const hourBars = !custom && !hourlyRange && barInterval === "H";
  const [intraday, setIntraday] = React.useState(null);
  React.useEffect(() => {
    if (!up || !(hourlyRange || hourBars)) return undefined;
    let alive = true;
    setIntraday(null);
    fetch(`/api/intraday/${encodeURIComponent(up)}?days=${hourBars ? 60 : 8}`)
      .then((r) => r.json())
      .then((d) => { if (alive) setIntraday(d.ok ? (d.points || []) : []); })
      .catch(() => { if (alive) setIntraday([]); });
    return () => { alive = false; };
  }, [up, hourlyRange, hourBars]);
  const busy = loading || ((hourlyRange || hourBars) && intraday === null);

  // Only `quality` is read here: whether this security trades often enough for
  // a candle to describe a day rather than invent one (ТЗ §6). The rest of the
  // metrics envelope belongs to the company page.
  React.useEffect(() => {
    if (!up) return undefined;
    let alive = true;
    fetch(`/api/company/${encodeURIComponent(up)}/metrics?months=${months}`)
      .then((r) => r.json())
      .then((d) => { if (alive) setQuality(d.ok ? d.quality : null); })
      .catch(() => { if (alive) setQuality(null); });
    return () => { alive = false; };
  }, [up, months]);

  React.useEffect(() => {
    if (!up) return undefined;
    let alive = true;
    fetch(`/api/securities/${encodeURIComponent(up)}/info?language=${lang}`)
      .then((r) => r.json())
      .then((d) => { if (alive && d.ok) setSec({ ...(d.security || {}) }); })
      .catch(() => {});
    return () => { alive = false; };
  }, [up, lang]);

  // The fact store, fetched once a fundamental is actually asked for — most
  // visits never open that menu.
  React.useEffect(() => {
    if (!up || !finFields.length || fin !== null) return undefined;
    let alive = true;
    fetch(`/api/company/${encodeURIComponent(up)}/financials`)
      .then((r) => r.json())
      .then((d) => { if (alive) setFin(d.ok ? d : { periods: [], series: {} }); })
      .catch(() => { if (alive) setFin({ periods: [], series: {} }); });
    return () => { alive = false; };
  }, [up, finFields.length, fin]);
  React.useEffect(() => { setFin(null); }, [up]);

  const cmpKey = [...compareTickers].sort().join(",");
  React.useEffect(() => {
    if (!cmpKey) { setCmpLoading(false); return undefined; }
    let alive = true;
    setCmpLoading(true);
    fetch(`/api/quotes/series?tickers=${encodeURIComponent(cmpKey)}&days=3650`)
      .then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setCmpSeries((s) => ({ ...s, ...(d.series || {}) })); })
      .catch(() => {})
      .finally(() => { if (alive) setCmpLoading(false); });
    return () => { alive = false; };
  }, [cmpKey]);

  // ── The URL mirrors the toolbar, so this view can be sent to somebody ─────
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const p = new URLSearchParams();
    if (custom) { p.set("from", span.from); p.set("to", span.to); } else if (range !== "1y") p.set("range", range);
    if (type !== "line") p.set("type", type);
    if (barInterval !== "D") p.set("iv", barInterval);
    if (indicators.size) p.set("ind", [...indicators].join(","));
    if (finFields.length) p.set("fin", finFields.join(","));
    if (compareTickers.length) p.set("cmp", compareTickers.join(","));
    const q = p.toString();
    window.history.replaceState(null, "", `/chart/${encodeURIComponent(up)}${q ? `?${q}` : ""}`);
  }, [up, range, span, type, barInterval, indicators, finFields, compareTickers, custom]);

  // ── Data preparation ─────────────────────────────────────────────────────
  const daily = React.useMemo(() => (history || []).map((h) => (Array.isArray(h)
    ? { date: h[0], close: Number(h[1]) || 0, volume: 0, turnover: Number(h[2]) || 0 }
    : {
        date: h.date || h.trade_date,
        open: h.open != null ? Number(h.open) : null,
        high: h.high != null ? Number(h.high) : null,
        low: h.low != null ? Number(h.low) : null,
        close: Number(h.close ?? h.price ?? h.close_price ?? 0),
        volume: Number(h.volume ?? h.trading_volume ?? 0) || 0,
        // Money, not a security count — see the note on the company chart's
        // normalizer. The pane, its scale label and the readout all use it.
        turnover: Number(h.value ?? h.trading_value ?? 0) || 0,
        change: h.change != null ? Number(h.change) : null,
      }))
    .filter((p) => p.close > 0 && p.date)
    .sort((a, b) => String(a.date).localeCompare(String(b.date))), [history]);

  const hourlyBars = React.useMemo(() => (intraday || []).map((h) => ({
    date: h.date,
    open: h.open != null ? Number(h.open) : null,
    high: h.high != null ? Number(h.high) : null,
    low: h.low != null ? Number(h.low) : null,
    close: Number(h.close ?? 0),
    volume: Number(h.volume ?? 0) || 0,
    turnover: Number(h.value ?? 0) || 0,
    change: null,
  })).filter((p) => p.close > 0 && p.date)
    .sort((a, b) => String(a.date).localeCompare(String(b.date))), [intraday]);
  // Peers arrive as daily series, so 1Н with a comparison stays on daily
  // closes; 1Д has no dates a peer could be sampled on and drops them.
  const peersWanted = compareTickers.length > 0;
  const sessionRange = hourlyRange && range === "1d";

  const windowed = React.useMemo(() => {
    if (custom) return daily.filter((p) => String(p.date) >= span.from && String(p.date) <= span.to);
    if (sessionRange) {
      // The newest banked session, not the last 24 hours: on a Sunday 1Д is Friday.
      const lastDay = hourlyBars.length ? String(hourlyBars.at(-1).date).slice(0, 10) : null;
      return lastDay ? hourlyBars.filter((p) => String(p.date).startsWith(lastDay)) : [];
    }
    let cutoff = chartRangeCutoff(range, daily.at(-1)?.date);
    // Normally the API request itself enforces month-based presets. Candle
    // mode deliberately fetches farther back for panning, so reproduce that
    // preset boundary here before opening the interactive viewport.
    if (!cutoff && range !== "max") {
      const spanMonths = chartRangeSpan(range);
      if (spanMonths) {
        const d = new Date(daily.at(-1)?.date || Date.now());
        d.setUTCMonth(d.getUTCMonth() - spanMonths);
        cutoff = d.toISOString().slice(0, 10);
      }
    }
    if (hourlyRange && hourlyBars.length && !peersWanted) {
      // Hourly bars where the bank has them, the settled daily close where it
      // does not. "2026-08-17" < "2026-08-17T10:00" as strings, so one sort holds.
      const covered = new Set(hourlyBars.map((p) => String(p.date).slice(0, 10)));
      const merged = [...daily.filter((p) => !covered.has(String(p.date).slice(0, 10))), ...hourlyBars]
        .sort((a, b) => String(a.date).localeCompare(String(b.date)));
      return cutoff ? merged.filter((p) => String(p.date) >= cutoff) : merged;
    }
    return cutoff ? daily.filter((p) => String(p.date) >= cutoff) : daily;
  }, [daily, custom, span.from, span.to, range, hourlyRange, sessionRange, hourlyBars, peersWanted]);

  // A preset defines the view we open with, not a wall around the data: the
  // whole fetched archive stays on the canvas, so a zoomed view can be dragged
  // into earlier history. A custom range remains a hard boundary because the
  // dates were an explicit request rather than a convenient zoom preset.
  const candlesAllowed = quality ? quality.candles_enabled !== false : true;
  const historyNavigation = !custom && !hourlyRange;
  const cmpLines = React.useMemo(() => compareTickers.map((tk, i) => ({
    ticker: tk,
    color: QC_COLORS[i % QC_COLORS.length],
    points: cmpSeries[tk] || null,
  })), [compareTickers, cmpSeries]);
  // A comparison is aligned session by session, so it stays daily; the hourly
  // ranges already have their own bar.
  const peersLoaded = !sessionRange && cmpLines.some((c) => c.points && c.points.length);
  const effInterval = peersLoaded || hourlyRange ? "D" : barInterval;
  const source = React.useMemo(() => {
    if (effInterval === "H") return lwUniqueByTime(hourlyBars);
    return lwUniqueByTime(historyNavigation
      ? aggregateCompanyPricePoints(daily, effInterval)
      : aggregateCompanyPricePoints(windowed, effInterval));
  }, [historyNavigation, daily, windowed, effInterval, hourlyBars]);
  const rangeWindow = React.useMemo(() => {
    if (effInterval === "H") {
      // The range's window, cut to where hourly bars exist at all.
      const from = String(windowed[0]?.date || "");
      const inRange = source.filter((p) => String(p.date) >= from);
      return inRange.length ? inRange : source;
    }
    return historyNavigation ? aggregateCompanyPricePoints(windowed, effInterval) : source;
  }, [historyNavigation, windowed, effInterval, source]);
  const cmp = React.useMemo(() => (sessionRange || effInterval === "H" ? null
    : buildCompareAligned(source, cmpLines, rangeWindow[0]?.date)), [sessionRange, effInterval, source, cmpLines, rangeWindow]);
  const cmpOn = Boolean(cmp && cmp.series.length);
  const hasHourly = source.some((p) => String(p.date).includes("T"));

  // A comparison is a percent question, so the price pane answers in percent —
  // and a candle has no meaning on a rebased axis. The type control says so
  // rather than silently drawing something else.
  const effType = cmpOn && !AC_COMPARISON_TYPES.has(type) ? "line" : type;
  // ТЗ §6: candles are only drawn where a day HAS a body worth drawing.
  const stepLine = quality ? quality.candles_enabled === false : false;
  const drawType = (AC_OHLC_TYPES.has(effType) && !candlesAllowed) ? "line" : effType;
  const synthetic = ["kagi", "point_figure", "renko"].includes(drawType);
  // A synthetic figure is built from the period's closes and has no calendar.
  const points = synthetic ? rangeWindow : source;
  const n = points.length;
  const dates = React.useMemo(() => points.map((p) => String(p.date)), [points]);
  const baseVals = React.useMemo(() => (cmpOn ? cmp.basePct : points.map((p) => p.close)), [cmpOn, cmp, points]);
  const toScale = React.useCallback((price) => (cmpOn ? (price / cmp.base0 - 1) * 100 : price), [cmpOn, cmp]);

  const [visible, setVisible] = React.useState(null);
  const [resetToken, setResetToken] = React.useState(0);
  const [focus, setFocus] = React.useState(null);

  // Patterns: daily sessions in сумы only, as on the company chart.
  const [patternsOn, setPatternsOn] = React.useState({ chart: false, candle: false, cycle: false });
  const [sensitivity, setSensitivity] = React.useState("medium");
  const [selectedPattern, setSelectedPattern] = React.useState(null);
  React.useEffect(() => { setSelectedPattern(null); }, [up, sensitivity]);
  const patternsWanted = patternsOn.chart || patternsOn.candle || patternsOn.cycle;
  const patternsAvailable = !synthetic && !cmpOn && effInterval === "D" && !hourlyRange;
  const patternData = usePatterns(up, patternsWanted, sensitivity);
  const shownPatterns = React.useMemo(() => (patternsAvailable && patternData?.signals
    ? patternData.signals.filter((s) => (s.family === "chart" ? patternsOn.chart : patternsOn.candle)) : []),
  [patternsAvailable, patternData, patternsOn]);
  const patternLabels = Boolean(visible) && visible.to - visible.from <= 300;
  React.useEffect(() => { setDrawPoints([]); }, [up, range, span.from, span.to, type, effInterval, cmpKey]);

  // Indicators run on the WHOLE fetched series, not on the visible window: a
  // 200-day average at the left edge of a one-month view is a real average of
  // the two hundred days before it, not a truncated one.
  const cal = React.useMemo(() => indCalendar(daily), [daily]);

  const ind = React.useMemo(() => {
    if (!cal.days.length) return {};
    const out = {};
    const put = (key, daily2) => { out[key] = indAlign(daily2, cal.indexByDate, dates); };
    if (indicators.has("sma50")) put("sma50", indSma(cal.close, 50));
    if (indicators.has("sma200")) put("sma200", indSma(cal.close, 200));
    if (indicators.has("ema50")) put("ema50", indEma(cal.close, 50));
    if (indicators.has("ema200")) put("ema200", indEma(cal.close, 200));
    if (indicators.has("bb")) {
      const b = indBollinger(cal.close, 20, 2);
      out.bb = {
        mid: indAlign(b.mid, cal.indexByDate, dates),
        upper: indAlign(b.upper, cal.indexByDate, dates),
        lower: indAlign(b.lower, cal.indexByDate, dates),
      };
    }
    if (indicators.has("rsi")) put("rsi", indRsi(cal.close, 14));
    if (indicators.has("macd")) {
      const m = indMacd(cal.close, 12, 26, 9);
      out.macd = {
        line: indAlign(m.line, cal.indexByDate, dates),
        signal: indAlign(m.signal, cal.indexByDate, dates),
        hist: indAlign(m.hist, cal.indexByDate, dates),
      };
    }
    if (indicators.has("stoch")) {
      const s = indStochastic(cal.high, cal.low, cal.close, 14, 3);
      out.stoch = {
        k: indAlign(s.k, cal.indexByDate, dates),
        d: indAlign(s.d, cal.indexByDate, dates),
      };
    }
    return out;
  }, [cal, indicators, dates]);

  const finPanes = React.useMemo(() => finFields.map((field, i) => {
    const series = fin?.series?.[field];
    return {
      field,
      color: AC_FIN_COLORS[i % AC_FIN_COLORS.length],
      unit: series?.unit || (acFinIsRate(field) ? "%" : null),
      values: series ? acFinancialAtDates(series.values || {}, dates) : dates.map(() => null),
      empty: !series,
    };
  }), [finFields, fin, dates]);

  const toggleIndicator = (key) => setIndicators((cur) => {
    const next = new Set(cur);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  const toggleFin = (field) => setFinFields((cur) => (cur.includes(field)
    ? cur.filter((f) => f !== field)
    : cur.length >= AC_FIN_MAX ? cur : [...cur, field]));
  const toggleCompare = (tk) => {
    const k = String(tk || "").toUpperCase();
    setCompareTickers((cur) => (cur.includes(k) ? cur.filter((x) => x !== k)
      : cur.length >= QC_MAX ? cur : [...cur, k]));
  };

  /**
   * Open another security's chart from the rail.
   *
   * The VIEW carries over — period, chart type, indicators, the fundamentals
   * on show are all questions about how to look, and a reader who set them up
   * wants to keep looking that way. The COMPARISON does not: a peer set is
   * chosen against one security, so carrying it over compares the new security
   * against the old one's neighbours — and opening a security that was itself
   * on the chart would compare it with itself, a flat line at 0 %.
   */
  const openPeerChart = (tk) => {
    if (!onOpenChart) return;
    onOpenChart(tk, {
      range,
      from: span.from,
      to: span.to,
      type,
      interval: barInterval,
      indicators: [...indicators],
      fin: finFields,
      compare: [],
    });
  };

  const preparedRows = React.useMemo(() => {
    return prepareMarketRows(marketRows, tradeStats);
  }, [marketRows, tradeStats]);
  const marketRow = preparedRows.find((r) => String(r.ticker || "").toUpperCase() === up) || null;
  const peers = React.useMemo(
    () => quickComparePeers({ ticker: up, rows: preparedRows, securitiesMap, limit: 24 }),
    [up, preparedRows, securitiesMap],
  );

  const dateLocale = lang === "en" ? "en-US" : "ru-RU";
  // An hourly bar's date carries its hour ("2026-08-17T14:00") and is labelled with it.
  const isHourly = (d) => String(d || "").includes("T");
  const fmtDate = (d, withYear) => (!d ? ""
    : isHourly(d)
      ? new Date(d).toLocaleString(dateLocale, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
      : new Date(d).toLocaleDateString(dateLocale, withYear
        ? { year: "2-digit", month: "short", day: "numeric" }
        : { month: "short", day: "numeric" }));
  const fmtFull = (v) => (v == null || !Number.isFinite(v) ? "—"
    : Number(v).toLocaleString(dateLocale, { maximumFractionDigits: 2 }));
  const fmtPctVal = (v) => (v == null || !Number.isFinite(v) ? "—" : `${signedFixed(v, 1)}%`);
  const abbrev = (v) => (v == null ? "—" : Math.abs(v) >= 1e9 ? `${(v / 1e9).toFixed(2)}B`
    : Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(2)}M`
    : Math.abs(v) >= 1e3 ? `${(v / 1e3).toFixed(1)}K` : `${v.toFixed(0)}`);

  const lastPrice = marketRow?.lastPrice ?? sec.last_price ?? (points.length ? points[points.length - 1].close : null);
  const dayChange = marketRow && Number.isFinite(marketRow.changePercent)
    ? { v: marketRow.changeValue, p: marketRow.changePercent } : null;
  // What the VIEW did, which is not what the day did — the reference states
  // both, and on a range button they are different questions.
  const changeBase = visible && !synthetic ? points.slice(visible.from, visible.to + 1) : rangeWindow;
  const windowChange = changeBase.length >= 2 && changeBase[0].close > 0
    ? ((changeBase[changeBase.length - 1].close / changeBase[0].close) - 1) * 100 : null;

  const rangeBar = (
    <div className="ac-ranges">
      {CHART_RANGES.map((r) => (
        <button key={r.key} type="button"
          className={`ac-range-btn ${!custom && range === r.key ? "active" : ""}`}
          onClick={() => { setSpan({ from: "", to: "" }); setRange(r.key); }}>
          {r.label[lang === "uz" ? 1 : lang === "en" ? 2 : 0]}
        </button>
      ))}
      <button type="button" className={`ac-range-btn ac-range-custom ${custom ? "active" : ""}`}
        onClick={() => setMenu(menu === "span" ? null : "span")}
        title={t("Свой период", "O'z davri", "Custom range")}>
        {custom ? `${fmtDate(span.from, true)} — ${fmtDate(span.to, true)}` : t("Период…", "Davr…", "Range…")}
      </button>
    </div>
  );

  const menuPanel = (key, children) => (menu === key
    ? <div className="ac-menu" onMouseLeave={() => setMenu(null)}>{children}</div> : null);

  // ── The canvas ───────────────────────────────────────────────────────────
  const GAP = 12;
  // Volume needs enough of its own pane to be readable.
  const VOL_H = 130;
  const SUB_H = 92;
  const subPanes = React.useMemo(() => [
    ...(indicators.has("rsi") ? [{ key: "rsi" }] : []),
    ...(indicators.has("macd") ? [{ key: "macd" }] : []),
    ...(indicators.has("stoch") ? [{ key: "stoch" }] : []),
    ...finPanes.map((f) => ({ key: `fin:${f.field}`, fin: f })),
  ], [indicators, finPanes]);
  const [viewH, setViewH] = React.useState(() => (typeof window === "undefined" ? 900 : window.innerHeight));
  React.useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onResize = () => setViewH(window.innerHeight);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  // The panel GROWS with what is on it. A fixed height would take an
  // oscillator's ninety pixels out of the price pane, which is the one pane
  // that was the reason to open this page.
  const plotH = Math.max(420, Math.floor(viewH * 0.62)) + subPanes.length * (SUB_H + GAP);

  const isUp = n >= 2 && baseVals[n - 1] >= (cmpOn ? 0 : (rangeWindow[0]?.close ?? baseVals[0]));
  const priceColor = cmpOn ? LW_UP : isUp ? LW_UP : LW_DOWN;

  const spec = React.useMemo(() => {
    if (n < 2) return null;
    const tt = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
    const times = points.map((p) => lwTime(p.date));
    const priceFormat = cmpOn ? lwPercentFormat(lang) : lwPriceFormatFor(points.at(-1).close, lang);
    const lineType = stepLine ? LwLineType.WithSteps : LwLineType.Simple;
    const valueData = points.map((p, i) => ({ time: times[i], value: baseVals[i] }));
    const baseLevel = cmpOn ? 0 : (rangeWindow[0]?.close ?? baseVals[0]);
    const series = [];
    const markers = synthetic ? [] : adjustments
      .map((a) => ({ i: points.findIndex((p) => String(p.date) >= String(a.ex_date)), kind: a.kind }))
      .filter((a) => a.i > 0)
      .map((a) => ({ time: times[a.i], position: "aboveBar", color: "#8b82f0", shape: "arrowDown",
        text: a.kind === "bonus" ? (lang === "ru" ? "Бонус" : "Bonus") : (lang === "ru" ? "Сплит" : "Split") }));
    const trend = drawPoints.map((d) => ({ time: d.time, value: d.value }));
    let labels = null;

    if (synthetic) {
      const syn = lwSyntheticSeries(drawType, points);
      labels = syn.labels;
      series.push({
        key: "price", kind: syn.kind, data: syn.data,
        options: syn.kind === "line"
          ? { lineType: LwLineType.WithSteps, lineWidth: 2, priceFormat }
          : drawType === "point_figure"
            ? { priceFormat, upColor: "rgba(0,0,0,0)", downColor: "rgba(0,0,0,0)", borderVisible: false, wickVisible: false }
            : { priceFormat, upColor: LW_UP_FILL, downColor: LW_DOWN_FILL, borderUpColor: LW_UP, borderDownColor: LW_DOWN, wickVisible: false },
        glyphs: syn.glyphs ? { columns: syn.glyphs, box: syn.box } : null,
      });
    } else if (["candle", "heikin_ashi", "bars"].includes(drawType)) {
      const src = drawType === "heikin_ashi" ? lwHeikinAshi(points) : points;
      series.push({
        key: "price", kind: drawType === "bars" ? "bar" : "candle",
        data: src.map((p, i) => lwOhlcBar(p, times[i])),
        options: drawType === "bars"
          ? { priceFormat, upColor: LW_UP, downColor: LW_DOWN, thinBars: false }
          : { priceFormat, upColor: LW_UP, downColor: LW_DOWN, borderVisible: false, wickUpColor: LW_UP, wickDownColor: LW_DOWN },
        markers, trend,
      });
    } else if (drawType === "columns") {
      series.push({
        key: "price", kind: "histogram",
        data: valueData.map((d, i) => ({ ...d, color: i && d.value < valueData[i - 1].value ? LW_DOWN : LW_UP })),
        options: { priceFormat }, markers, trend,
      });
    } else if (drawType === "baseline") {
      series.push({
        key: "price", kind: "baseline", data: valueData,
        options: { priceFormat, lineType, lineWidth: 2, baseValue: { type: "price", price: baseLevel },
          topLineColor: LW_UP, bottomLineColor: LW_DOWN,
          topFillColor1: LW_UP_FILL, topFillColor2: LW_UP_FILL_FAINT,
          bottomFillColor1: LW_DOWN_FILL_FAINT, bottomFillColor2: LW_DOWN_FILL },
        markers, trend,
      });
    } else if (drawType === "area" && !cmpOn) {
      series.push({
        key: "price", kind: "area", data: valueData,
        options: { priceFormat, lineType, lineColor: priceColor, lineWidth: 2,
          topColor: isUp ? LW_UP_FILL : LW_DOWN_FILL, bottomColor: isUp ? LW_UP_FILL_FAINT : LW_DOWN_FILL_FAINT },
        markers, trend,
      });
    } else {
      series.push({
        key: "price", kind: "line", data: valueData,
        options: { priceFormat, lineType, color: priceColor, lineWidth: 2 }, markers, trend,
      });
    }

    if (!synthetic) {
      const overlay = (key, values, color, extra = {}) => series.push({
        key, kind: "line",
        data: values.map((v, i) => (v == null ? { time: times[i] } : { time: times[i], value: toScale(v) })),
        options: { color, lineWidth: 1.4, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false, priceFormat, ...extra },
      });
      if (ind.bb) {
        overlay("bb:upper", ind.bb.upper, "rgba(20,184,166,0.75)", { lineWidth: 1 });
        overlay("bb:lower", ind.bb.lower, "rgba(20,184,166,0.75)", { lineWidth: 1 });
        overlay("bb:mid", ind.bb.mid, "rgba(20,184,166,0.5)", { lineWidth: 1, lineStyle: 2 });
      }
      ["sma50", "sma200", "ema50", "ema200"].forEach((k) => {
        if (ind[k]) overlay(k, ind[k], AC_INDICATORS.find((d) => d.key === k).color);
      });
      if (cmpOn) {
        cmp.series.forEach((s) => series.push({
          key: `cmp:${s.ticker}`, kind: "line",
          data: s.pct.map((v, i) => (v == null ? { time: times[i] } : { time: times[i], value: v })),
          options: { color: s.color, lineWidth: 1.6, priceLineVisible: false, lastValueVisible: true, priceFormat },
        }));
      }

      // Volume. Not decoration: on this market a move worth 40 000 сум and a
      // move worth 400 млн are different events, and the price line cannot
      // tell them apart. Money rather than share count, so a 2 сум share and a
      // 23 000 сум one are on the same scale. A fourth-root display keeps small
      // sessions readable beside rare block trades (the readout keeps the exact
      // turnover); a session with no published volume keeps a neutral stub, so
      // a gap reads as «no trades», not as a rendering bug.
      const volumeValues = points.map((p) => p.turnover || 0).filter((v) => v > 0).sort((a, b) => a - b);
      const volumeScale = volumeValues.length
        ? Math.max(1, volumeValues[Math.min(volumeValues.length - 1, Math.floor((volumeValues.length - 1) * 0.95))])
        : 1;
      series.push({
        key: "volume", kind: "histogram", pane: 1,
        data: points.map((p, i) => {
          const v = p.turnover || 0;
          if (!v) return { time: times[i], value: 8, color: "rgba(127,127,127,0.35)" };
          const upDay = i > 0 ? p.close >= points[i - 1].close : true;
          return { time: times[i], value: Math.max(20, Math.pow(Math.min(1, v / volumeScale), 0.25) * 100),
            color: upDay ? "rgba(47,197,132,0.9)" : "rgba(238,106,96,0.9)" };
        }),
        options: { priceLineVisible: false, lastValueVisible: false, priceFormat: lwCustomFormat(() => "") },
        // The axis stays (it prints nothing): hiding a pane's only price axis
        // trips the library's layout pass on a fresh canvas.
        scale: { scaleMargins: { top: 0.12, bottom: 0 } },
      });
    }

    if (shownPatterns.length) {
      applyPatternOverlay(series, patternOverlay(shownPatterns, times, lang, patternLabels,
        shownPatterns.find((sig) => patternKey(sig) === selectedPattern) || null));
    }

    const panes = synthetic ? [] : [{
      height: VOL_H,
      title: `${tt("Объём", "Hajm", "Volume")} · ${fmtCompact(Math.max(1, ...points.map((p) => p.turnover || 0)), lang)} ${tt("сум", "so'm", "UZS")}`,
    }];
    if (!synthetic) {
      subPanes.forEach((pane, pi) => {
        const paneIndex = 2 + pi;
        const line = (key, values, color, extra = {}) => series.push({
          key, kind: "line", pane: paneIndex,
          data: values.map((v, i) => (v == null ? { time: times[i] } : { time: times[i], value: v })),
          options: { color, lineWidth: 1.4, priceLineVisible: false, lastValueVisible: false, ...extra },
        });
        const fixed = (lo, hi) => ({ autoscaleInfoProvider: () => ({ priceRange: { minValue: lo, maxValue: hi } }) });
        if (pane.key === "rsi") {
          line("rsi", ind.rsi || [], "#22d3ee", fixed(0, 100));
          series.at(-1).lines = [{ price: 30 }, { price: 70 }];
          panes.push({ height: SUB_H, title: "RSI 14" });
        } else if (pane.key === "stoch") {
          line("stoch:k", ind.stoch?.k || [], "#a3e635", fixed(0, 100));
          series.at(-1).lines = [{ price: 20 }, { price: 80 }];
          line("stoch:d", ind.stoch?.d || [], "#fb923c", { ...fixed(0, 100), lineStyle: 2, lineWidth: 1.2 });
          panes.push({ height: SUB_H, title: "Stoch 14/3" });
        } else if (pane.key === "macd") {
          series.push({
            key: "macd:hist", kind: "histogram", pane: paneIndex,
            data: (ind.macd?.hist || []).map((v, i) => (v == null ? { time: times[i] }
              : { time: times[i], value: v, color: v >= 0 ? "rgba(47,197,132,0.45)" : "rgba(238,106,96,0.45)" })),
            options: { priceLineVisible: false, lastValueVisible: false },
            lines: [{ price: 0 }],
          });
          line("macd:line", ind.macd?.line || [], "#f472b6");
          line("macd:signal", ind.macd?.signal || [], "#facc15", { lineWidth: 1.2 });
          panes.push({ height: SUB_H, title: "MACD 12/26/9" });
        } else {
          const f = pane.fin;
          const has = f.values.some((v) => v != null);
          // A step, because an annual figure does not drift through its year —
          // it lands when the filing does.
          line(`fin:${f.field}`, f.values, f.color, {
            lineType: LwLineType.WithSteps, lineWidth: 1.5,
            priceFormat: lwCustomFormat((v) => `${abbrev(v)}${f.unit ? ` ${f.unit}` : ""}`),
          });
          if (!has) series.at(-1).data = [{ time: times[0], value: 0 }, { time: times.at(-1), value: 0 }];
          if (!has) series.at(-1).options.color = "rgba(0,0,0,0)";
          panes.push({ height: SUB_H, color: f.color,
            title: has ? `${finLabel(f.field, lang)}${f.unit ? `, ${f.unit}` : ""}`
              : `${finLabel(f.field, lang)} — ${tt("нет отчётности за этот период", "bu davr uchun hisobot yo'q", "no filing covers this period")}` });
        }
      });
    }
    return { series, main: "price", panes, hourly: hasHourly, labels };
  }, [n, points, baseVals, cmpOn, cmp, drawType, synthetic, stepLine, priceColor, isUp, rangeWindow, adjustments,
      drawPoints, ind, toScale, subPanes, finPanes, hasHourly, lang, shownPatterns, patternLabels, selectedPattern]);

  const initialView = React.useMemo(() => {
    if (synthetic || !historyNavigation || range === "max" || n < 2) return null;
    const first = cmpOn ? points[cmp.baseIdx]?.date : rangeWindow[0]?.date;
    return first ? { from: lwTime(first), to: lwTime(points.at(-1).date) } : null;
  }, [synthetic, historyNavigation, range, n, cmpOn, cmp, points, rangeWindow]);
  const viewKey = `${up}|${range}|${span.from}|${span.to}|${effInterval}|${synthetic ? drawType : "t"}|${cmpOn ? cmp.baseIdx : "-"}`;

  const [hover, setHover] = React.useState(null);
  const onChartClick = ({ index, pane }) => {
    if (!drawMode || pane !== 0 || synthetic) return;
    const next = { time: lwTime(points[index].date), value: baseVals[index] };
    setDrawPoints((current) => (current.length >= 2 ? [next] : [...current, next]));
  };
  const synthBar = synthetic && hover && spec ? spec.series[0].data[hover.index] : null;
  const hIdx = hover && !synthetic ? hover.index : null;
  const hp = !cursorOn || drawMode || !hover ? null
    : synthetic
      ? (synthBar ? { date: spec.labels?.get(synthBar.time), close: synthBar.close ?? synthBar.value } : null)
      : points[hover.index] || null;
  const relVol = hp && !synthetic && effInterval === "D" && !isHourly(hp.date) ? relativeVolume(daily, hp.date, hp.turnover) : null;
  const visFrom = visible && !synthetic ? points[visible.from]?.date : null;
  const visTo = visible && !synthetic ? points[visible.to]?.date : null;

  const legendChips = [
    ...(cmpOn ? cmp.series.map((s) => ({ key: `c:${s.ticker}`, color: s.color, text: s.ticker, off: () => toggleCompare(s.ticker) })) : []),
    ...AC_INDICATORS.filter((d) => indicators.has(d.key)).map((d) => ({
      key: `i:${d.key}`, color: d.color, off: () => toggleIndicator(d.key),
      text: d.label[lang === "uz" ? 1 : lang === "en" ? 2 : 0],
    })),
    ...finPanes.map((f) => ({
      key: `f:${f.field}`, color: f.color, off: () => toggleFin(f.field),
      text: finLabel(f.field, lang),
    })),
    ...(patternsWanted ? [{ key: "patterns", color: "var(--accent)", text: t("Паттерны", "Patternlar", "Patterns"),
      off: () => { setPatternsOn({ chart: false, candle: false, cycle: false }); setSelectedPattern(null); } }] : []),
  ];

  const emptyState = !busy && n < 2;

  return (
    <div ref={chartShellRef} className={`advanced-chart ${railOpen ? "rail-open" : ""} ${isFullscreen ? "is-fullscreen" : ""}`}>
      <div className="ac-head">
        <button className="ac-back" type="button" onClick={onBack}>
          ← {t("Назад", "Orqaga", "Back")}
        </button>
        <CompanyLogo logo={sec.company_logo_url || sec.logo_url || (securitiesMap || {})[up]?.logo_url}
          name={sec.company_name || sec.name || up} ticker={up} />
        <div className="ac-title">
          <h1>{sec.company_name || sec.name || up}</h1>
          <div className="ac-meta">
            <span className="ac-tk">{up}</span>
            {sec.isin && <span className="muted">{sec.isin}</span>}
            <span className="muted">{t("Расчётные цены закрытия · UZSE", "Hisob-kitob yopilish narxlari · UZSE", "Settled closing prices · UZSE")}</span>
          </div>
        </div>
        <div className="ac-quote">
          <span className="ac-price">{lastPrice != null ? formatMarketNumber(lastPrice, lang) : "—"}</span>
          {dayChange && (
            <span className={`ac-change ${dayChange.p >= 0 ? "pos" : "neg"}`}>
              {dayChange.v >= 0 ? "+" : ""}{fmtFull(dayChange.v)} ({signedFixed(dayChange.p)}%)
            </span>
          )}
          {windowChange != null && (
            <span className={`ac-window-change ${windowChange >= 0 ? "pos" : "neg"}`}>
              {t("за период", "davr uchun", "over the period")} {fmtPctVal(windowChange)}
            </span>
          )}
        </div>
        <button className="ac-open-company" type="button" onClick={() => onOpenCompany && onOpenCompany(up)}>
          {t("Страница компании →", "Kompaniya sahifasi →", "Company page →")}
        </button>
      </div>

      <div className="ac-toolbar">
        {rangeBar}
        <div className="cpc-tool-strip ac-company-tools" data-testid="advanced-chart-tool-strip">
          <div className="cpc-tool-slot">
            <button type="button" className={`cpc-tool-btn ${menu === "interval" ? "active" : ""}`}
              data-testid="advanced-chart-interval" aria-haspopup="menu" aria-expanded={menu === "interval"}
              aria-label={t(`Интервал: ${effInterval}`, `Interval: ${effInterval}`, `Interval: ${effInterval}`)}
              title={hourlyRange
                ? t("На 1Д и 1Н — часовые бары", "1K va 1H da — soatlik barlar", "1D and 1W use hourly bars")
                : cmpOn
                  ? t("При сравнении — только дневной интервал", "Taqqoslashda faqat kunlik interval", "Comparison is daily only")
                  : t("Интервал", "Interval", "Interval")}
              disabled={cmpOn || hourlyRange}
              onClick={() => setMenu(menu === "interval" ? null : "interval")}>{hasHourly ? t("1ч", "1s", "1h") : effInterval}</button>
            {menuPanel("interval", [["H", "Час", "Soat", "Hour"], ["D", "День", "Kun", "Day"], ["W", "Неделя", "Hafta", "Week"], ["M", "Месяц", "Oy", "Month"]].map(([key, ru, uz, en]) => (
              <button key={key} type="button" className={`ac-menu-item ${barInterval === key ? "on" : ""}`}
                onClick={() => { setBarInterval(key); setMenu(null); }}>{t(ru, uz, en)} <span>{key}</span></button>
            )))}
          </div>
          <button type="button" className={`cpc-tool-btn ${cursorOn ? "active" : ""}`}
            aria-pressed={cursorOn} aria-label={t("Перекрестие и подсказки", "Kursor va ko'rsatmalar", "Crosshair and tooltips")}
            onClick={() => { setCursorOn((value) => !value); setHover(null); }}>
            <CompanyChartToolIcon kind="pointer" />
          </button>
          <div className="cpc-tool-slot">
            <button type="button" className={`cpc-tool-btn ${menu === "type" ? "active" : ""}`}
              aria-haspopup="menu" aria-expanded={menu === "type"} aria-label={t("Вид графика", "Grafik turi", "Chart type")}
              onClick={() => setMenu(menu === "type" ? null : "type")}>
              <CompanyChartToolIcon kind="candle" />
            </button>
            {menuPanel("type", AC_TYPES.map((tp) => {
              const name = tp.label[lang === "uz" ? 1 : lang === "en" ? 2 : 0];
              return <button key={tp.key} type="button" className={`ac-menu-item ${effType === tp.key ? "on" : ""}`}
                disabled={(cmpOn && !AC_COMPARISON_TYPES.has(tp.key)) || (AC_OHLC_TYPES.has(tp.key) && !candlesAllowed)}
                onClick={() => { setType(tp.key); setMenu(null); }}>{name}</button>;
            }))}
          </div>
          <div className="cpc-tool-slot">
            <button type="button" className={`cpc-tool-btn ${compareTickers.length ? "has-value" : ""} ${menu === "cmp" ? "active" : ""}`}
              aria-haspopup="menu" aria-expanded={menu === "cmp"} aria-label={t("Сравнить", "Taqqoslash", "Compare")}
              onClick={() => setMenu(menu === "cmp" ? null : "cmp")}>
              <CompanyChartToolIcon kind="compare" />
            </button>
            {menuPanel("cmp", peers.slice(0, 30).map((peer) => {
              const tk = String(peer.ticker || "").toUpperCase();
              return <button key={tk} type="button" className={`ac-menu-item ${compareTickers.includes(tk) ? "on" : ""}`}
                disabled={!compareTickers.includes(tk) && compareTickers.length >= QC_MAX}
                onClick={() => toggleCompare(tk)}>{peer.name || tk} <b className="ac-menu-tk">{tk}</b></button>;
            }))}
          </div>
          <button type="button" className={`cpc-tool-btn ${drawMode || drawPoints.length ? "active" : ""}`}
            aria-pressed={drawMode} aria-label={t("Линия тренда", "Trend chizig'i", "Trend line")}
            onClick={() => { setMenu(null); setDrawMode((value) => !value); setHover(null); }}>
            <CompanyChartToolIcon kind="draw" />
          </button>
          <button type="button" className={`cpc-tool-btn ${indicators.size ? "has-value" : ""} ${menu === "ind" ? "active" : ""}`}
            aria-label={t("Индикаторы", "Indikatorlar", "Indicators")} onClick={() => setMenu(menu === "ind" ? null : "ind")}>
            <CompanyChartToolIcon kind="fx" />
          </button>
          <button type="button" className={`cpc-tool-btn ${finFields.length ? "has-value" : ""} ${menu === "fin" ? "active" : ""}`}
            aria-label={t("Настройки и финансовые слои", "Sozlamalar va moliyaviy qatlamlar", "Settings and financial overlays")}
            onClick={() => setMenu(menu === "fin" ? null : "fin")}>
            <CompanyChartToolIcon kind="settings" />
          </button>
        </div>
        <div className="ac-toolbar-group ac-types" role="group"
          aria-label={t("Вид графика", "Grafik turi", "Chart type")}>
          {AC_TYPES.filter((tp) => ["line", "candle", "area", "baseline"].includes(tp.key)).map((tp) => {
            const name = tp.label[lang === "uz" ? 1 : lang === "en" ? 2 : 0];
            // A disabled button still has to say WHY, and the reason differs:
            // one is a fact about the security, the other about the axis.
            const why = !AC_OHLC_TYPES.has(tp.key) ? null
              : !candlesAllowed
                ? t("Слишком мало сделок — день не имеет тела",
                    "Bitimlar juda kam — kunning tanasi yo'q",
                    "Too few trades — the day has no body")
                : cmpOn
                  ? t("В сравнении шкала процентная — у свечи нет тела",
                      "Taqqoslashda shkala foizli — shamning tanasi yo'q",
                      "The scale is percent while comparing — a candle has no body")
                  : null;
            return (
              <button key={tp.key} type="button"
                className={`ac-type-btn ${effType === tp.key ? "active" : ""}`}
                disabled={(cmpOn && !AC_COMPARISON_TYPES.has(tp.key)) || (AC_OHLC_TYPES.has(tp.key) && !candlesAllowed)}
                aria-pressed={effType === tp.key}
                aria-label={name}
                title={why ? `${name} — ${why}` : name}
                onClick={() => setType(tp.key)}>
                <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor"
                  strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  {AC_TYPE_ICONS[tp.key]}
                </svg>
              </button>
            );
          })}
        </div>
        <div className="ac-toolbar-group ac-menus">
          <div className="ac-menu-wrap">
            <button type="button" className={`ac-menu-btn ${indicators.size ? "on" : ""}`}
              onClick={() => setMenu(menu === "ind" ? null : "ind")}>
              {t("Индикаторы", "Indikatorlar", "Indicators")}{indicators.size ? ` · ${indicators.size}` : ""}
            </button>
            {menuPanel("ind", AC_INDICATORS.map((d) => (
              <button key={d.key} type="button"
                className={`ac-menu-item ${indicators.has(d.key) ? "on" : ""}`}
                onClick={() => toggleIndicator(d.key)}>
                <span className="ac-menu-dot" style={{ background: d.color }} />
                {d.label[lang === "uz" ? 1 : lang === "en" ? 2 : 0]}
              </button>
            )))}
          </div>
          <div className="ac-menu-wrap">
            <button type="button" className={`ac-menu-btn ${patternsWanted ? "on" : ""}`} data-testid="ac-patterns"
              onClick={() => setMenu(menu === "pat" ? null : "pat")}>
              {t("Паттерны", "Patternlar", "Patterns")}{patternsWanted && patternData?.signals ? ` · ${shownPatterns.length}` : ""}
            </button>
            {menuPanel("pat", (
              <PatternMenuItems patternsOn={patternsOn} setPatternsOn={setPatternsOn} sensitivity={sensitivity}
                setSensitivity={setSensitivity} available={patternsAvailable} lang={lang} variant="ac" />
            ))}
          </div>
          <div className="ac-menu-wrap">
            <button type="button" className={`ac-menu-btn ${finFields.length ? "on" : ""}`}
              onClick={() => setMenu(menu === "fin" ? null : "fin")}>
              {t("Финансы", "Moliya", "Financials")}{finFields.length ? ` · ${finFields.length}` : ""}
            </button>
            {menuPanel("fin", (
              <div className="ac-menu-scroll">
                {AC_FIN_FIELDS.map((f) => (
                  <button key={f} type="button"
                    className={`ac-menu-item ${finFields.includes(f) ? "on" : ""}`}
                    disabled={!finFields.includes(f) && finFields.length >= AC_FIN_MAX}
                    onClick={() => toggleFin(f)}>
                    {finLabel(f, lang)}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
        <button type="button" className="ac-fullscreen-btn"
          aria-pressed={isFullscreen}
          aria-label={isFullscreen
            ? t("Выйти из полноэкранного режима", "To'liq ekrandan chiqish", "Exit full screen")
            : t("Развернуть график на весь экран", "Grafikni to'liq ekranga yoyish", "Expand chart to full screen")}
          title={isFullscreen
            ? t("Выйти из полноэкранного режима (Esc)", "To'liq ekrandan chiqish (Esc)", "Exit full screen (Esc)")
            : t("На весь экран", "To'liq ekran", "Full screen")}
          onClick={toggleFullscreen}>
          <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor"
            strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {isFullscreen ? (
              <path d="M9 4v5H4 M15 4v5h5 M9 20v-5H4 M15 20v-5h5" />
            ) : (
              <path d="M8 3H3v5 M16 3h5v5 M8 21H3v-5 M21 16v5h-5" />
            )}
          </svg>
          <span className="ac-fullscreen-label">
            {isFullscreen ? t("Свернуть", "Kichraytirish", "Restore") : t("На весь экран", "To'liq ekran", "Full screen")}
          </span>
        </button>
        {menu === "span" && (
          <div className="ac-menu ac-span-menu">
            <label>{t("С", "Dan", "From")}
              <input type="date" value={span.from}
                onChange={(e) => setSpan((s) => ({ ...s, from: e.target.value }))} />
            </label>
            <label>{t("По", "Gacha", "To")}
              <input type="date" value={span.to}
                onChange={(e) => setSpan((s) => ({ ...s, to: e.target.value }))} />
            </label>
            <button type="button" className="ac-menu-clear"
              onClick={() => { setSpan({ from: "", to: "" }); setMenu(null); }}>
              {t("Сбросить", "Tozalash", "Clear")}
            </button>
          </div>
        )}
      </div>

      <AdvancedCompareBar peers={peers} allRows={preparedRows} securitiesMap={securitiesMap}
        selected={compareTickers} colors={QC_COLORS} onToggle={toggleCompare}
        lang={lang} max={QC_MAX} />

      <div className="ac-body">
        <div className="ac-rail-wrap">
          <AdvancedChartRail rows={preparedRows} securitiesMap={securitiesMap} ticker={up}
            favorites={favorites} onToggleFavorite={onToggleFavorite} lang={lang} signedIn={signedIn}
            onOpen={openPeerChart} />
        </div>
        <button type="button" className="ac-rail-toggle" onClick={() => setRailOpen((v) => !v)}
          aria-label={railOpen ? t("Скрыть список", "Ro'yxatni yashirish", "Hide the list")
                               : t("Показать список", "Ro'yxatni ko'rsatish", "Show the list")}>
          {railOpen ? "‹" : "›"}
        </button>

        <div className="ac-plot" style={{ height: plotH }}>
          {busy && <div className="ac-state muted">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</div>}
          {failed && (
            <div className="ac-state">
              <p>{t("Не удалось загрузить историю цен.", "Narxlar tarixini yuklab bo'lmadi.", "Failed to load the price history.")}</p>
              <button className="primary-btn" type="button" onClick={() => setRetry((v) => v + 1)}>
                {t("Повторить", "Qayta urinish", "Retry")}
              </button>
            </div>
          )}
          {emptyState && !failed && (
            <div className="ac-state muted">
              {custom
                ? t("За выбранный период сделок не было", "Tanlangan davrda bitim bo'lmagan", "No trades in the selected period")
                : sessionRange
                  ? (n === 0
                    ? t("В последних сессиях сделок не было — часовой график недоступен",
                        "So'nggi sessiyalarda bitim bo'lmagan — soatlik grafik mavjud emas",
                        "No trades in the recent sessions — no hourly view to draw")
                    : t("В последней сессии сделки были только в одном часе — линию не построить",
                        "Oxirgi sessiyada bitimlar faqat bir soatda bo'lgan — chiziq chizib bo'lmaydi",
                        "The last session traded in a single hour — too little for a line"))
                  : t("История цен недоступна", "Narxlar tarixi mavjud emas", "Price history unavailable")}
            </div>
          )}

          {!busy && !failed && n >= 2 && spec && (
            <>
              {legendChips.length > 0 && (
                <div className="ac-legend">
                  {legendChips.map((c) => (
                    <button key={c.key} type="button" className="ac-legend-chip"
                      style={{ "--ac-color": c.color }} onClick={c.off}>
                      <span className="ac-legend-dot" />{c.text}<span className="ac-legend-x">✕</span>
                    </button>
                  ))}
                </div>
              )}

              {/* 22px under the canvas for the TradingView credit: the plot box
                  clips at its own height. */}
              <LwCanvas spec={spec} height={plotH - 22} lang={lang} crosshair={cursorOn} pan={!drawMode}
                viewKey={viewKey} initialView={initialView} resetToken={resetToken} focus={focus}
                onHover={setHover} onClick={onChartClick}
                onRange={(r) => setVisible((cur) => (cur && cur.from === r.from && cur.to === r.to && cur.changed === r.changed ? cur : r))}
                className={`ac-canvas ${drawMode ? "is-drawing" : ""}`}
                data-chart-type={drawType} data-chart-interval={effInterval}
                data-series={spec.series.map((s) => s.key).join(",")}
                data-panes={1 + spec.panes.length} data-trend-points={drawPoints.length}
                data-visible-bars={visible ? visible.to - visible.from + 1 : spec.series[0].data.length}
                data-patterns={shownPatterns.length}
                aria-label={t("График. Ctrl и колесо меняют масштаб, перетаскивание показывает историю.",
                  "Grafik. Ctrl va g'ildirak masshtabni o'zgartiradi, sudrash tarixni ko'rsatadi.",
                  "Chart. Ctrl and the wheel zoom; drag to browse history.")} />

              {hp && (
                <div className="ac-tooltip" style={{
                  left: Math.min(Math.max(12, hover.point.x + 16), Math.max(12, (hover.width || 900) - 210)),
                  top: Math.min(Math.max(8, hover.point.y - 30), Math.max(8, plotH - 200)),
                }}>
                  <div className="ac-tt-date">{fmtDate(hp.date, true)}</div>
                  {!synthetic && lwOhlcOk(hp) && (
                    <>
                      <div className="ac-tt-row"><span>{t("Откр.", "Ochil.", "Open")}</span><b>{fmtFull(hp.open)}</b></div>
                      <div className="ac-tt-row"><span>{t("Макс.", "Maks.", "High")}</span><b>{fmtFull(hp.high)}</b></div>
                      <div className="ac-tt-row"><span>{t("Мин.", "Min.", "Low")}</span><b>{fmtFull(hp.low)}</b></div>
                    </>
                  )}
                  <div className="ac-tt-row"><span>{synthetic ? t("Уровень", "Daraja", "Level") : t("Закрытие", "Yopilish", "Close")}</span><b>{fmtFull(hp.close)}</b></div>
                  {!synthetic && (
                    <div className="ac-tt-row"><span>{t("Объём", "Hajm", "Volume")}</span>
                      <b>{hp.turnover ? `${fmtCompact(hp.turnover, lang)} ${t("сум", "so'm", "UZS")}` : "—"}</b>
                    </div>
                  )}
                  {relVol != null && (
                    <div className="ac-tt-row"><span>{t("Объём к среднему", "O'rtacha hajmga", "Vol vs avg")}</span>
                      <b>{fmtRelVol(relVol, lang)}</b>
                    </div>
                  )}
                  {!synthetic && shownPatterns.filter((sig) => sig.signal_date === String(hp.date).slice(0, 10)).map((sig) => (
                    <div className="ac-tt-row" key={`ttp${sig.type}`}>
                      <span style={{ color: sig.direction === "bullish" ? LW_UP : LW_DOWN }}>
                        {sig.direction === "bullish" ? "↑" : "↓"} {patternName(sig.type, lang)}
                      </span>
                    </div>
                  ))}
                  {cmpOn && hIdx != null && (
                    <div className="ac-tt-block">
                      <div className="ac-tt-row"><span style={{ color: priceColor }}>{up}</span>
                        <b style={{ color: priceColor }}>{fmtPctVal(baseVals[hIdx])}</b></div>
                      {cmp.series.map((s) => {
                        const pv = peerVolumeAt(s.volHist, String(hp.date).slice(0, 10));
                        return (
                          <React.Fragment key={`tt${s.ticker}`}>
                            <div className="ac-tt-row">
                              <span style={{ color: s.color }}>{s.ticker}</span>
                              <b style={{ color: s.color }}>{fmtPctVal(s.pct[hIdx])}</b>
                            </div>
                            <div className="ac-tt-row ac-tt-volrow">
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
                  {hIdx != null && (indicators.size > 0 || finPanes.length > 0) && (
                    <div className="ac-tt-block">
                      {AC_INDICATORS.filter((d) => indicators.has(d.key)).map((d) => {
                        const v = d.key === "bb" ? ind.bb?.mid?.[hIdx]
                          : d.key === "macd" ? ind.macd?.line?.[hIdx]
                          : d.key === "stoch" ? ind.stoch?.k?.[hIdx]
                          : ind[d.key]?.[hIdx];
                        return (
                          <div className="ac-tt-row" key={`tti${d.key}`}>
                            <span style={{ color: d.color }}>{d.label[lang === "uz" ? 1 : lang === "en" ? 2 : 0]}</span>
                            <b>{fmtFull(v)}</b>
                          </div>
                        );
                      })}
                      {finPanes.map((f) => (
                        <div className="ac-tt-row" key={`ttf${f.field}`}>
                          <span style={{ color: f.color }}>{finLabel(f.field, lang)}</span>
                          <b>{f.values[hIdx] == null ? "—"
                            : `${abbrev(f.values[hIdx])}${f.unit ? ` ${f.unit}` : ""}`}</b>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <div className="ac-notes">
        {effInterval === "H" && !busy && (
          <p className="muted" data-testid="ac-hourly-note">
            {source.length
              ? t(`Часовые бары — из ленты сделок биржи; хранятся с ${fmtDate(String(source[0].date).slice(0, 10), true)}, раньше почасовых данных нет.`,
                  `Soatlik barlar — birja bitimlar lentasidan; ${fmtDate(String(source[0].date).slice(0, 10), true)} dan saqlanadi.`,
                  `Hourly bars come from the exchange's trade feed, stored from ${fmtDate(String(source[0].date).slice(0, 10), true)}; nothing hourly exists before that.`)
              : t("По этой бумаге часовых баров нет — сделок за последние 60 дней не было.",
                  "Bu qog'oz bo'yicha soatlik barlar yo'q — so'nggi 60 kunda bitim bo'lmagan.",
                  "No hourly bars for this security — it has not traded in the last 60 days.")}
          </p>
        )}
        {patternsWanted && (patternsAvailable || patternsOn.cycle ? (
          <PatternList data={patternData} signals={shownPatterns} lang={lang} visibleFrom={visFrom} visibleTo={visTo}
            limit={12} selectedKey={selectedPattern}
            families={{ chart: patternsAvailable && patternsOn.chart, candle: patternsAvailable && patternsOn.candle,
                        cycle: patternsOn.cycle }}
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
        {visFrom && (
          <p className="ac-history-help" data-testid="ac-visible-range" data-from={visFrom} data-to={visTo}>
            <span>
              {t("Ctrl + колесо: вверх — приблизить, вниз — отдалить; потяните график — перейти по истории.",
                 "Ctrl + g'ildirak: yuqoriga — yaqinlashtirish, pastga — uzoqlashtirish; tarix uchun grafikni suring.",
                 "Ctrl + wheel: up zooms in, down zooms out; drag the chart to browse history.")}
            </span>
            <span className="ac-history-dates">{fmtDate(visFrom, true)} — {fmtDate(visTo, true)}</span>
            {visible?.changed && (
              <button type="button" className="ac-history-reset" onClick={() => setResetToken((v) => v + 1)}>
                {t("Сбросить", "Tiklash", "Reset")}
              </button>
            )}
          </p>
        )}
        {stepLine && (
          <p className="muted">
            {t("Цена показана ступенями — между сделками она не менялась.",
               "Narx pog'onalar bilan — bitimlar orasida u o'zgarmagan.",
               "The price is drawn as steps — between trades it did not move.")}
            {quality?.reason ? ` ${quality.reason}` : ""}
          </p>
        )}
        {AC_SYNTHETIC_TYPES.has(drawType) && (
          <p className="muted ac-synthetic-note">
            {t("Расчётный вид по дневным данным; значения фигур синтетические и не являются ценами сделок.",
               "Kunlik ma’lumotlar asosidagi hisobiy ko‘rinish; shakl qiymatlari sintetik va bitim narxlari emas.",
               "Calculated from daily data; figure values are synthetic and are not traded prices.")}
          </p>
        )}
        {cmpOn && cmp.start && (
          <p className="muted">
            {t(`Сравнение считается с ${fmtDate(cmp.start, true)} — раньше сохранённых котировок нет.`,
               `Taqqoslash ${fmtDate(cmp.start, true)} dan — undan oldingi kotirovkalar yo'q.`,
               `The comparison starts on ${fmtDate(cmp.start, true)} — there are no stored quotes before it.`)}
          </p>
        )}
        {cmp && cmp.dropped.length > 0 && !cmpLoading && (
          <p className="muted">
            {t("Нет сохранённых котировок за этот период: ", "Bu davr uchun kotirovkalar yo'q: ", "No stored quotes for this period: ")}
            {cmp.dropped.map((c) => c.ticker).join(", ")}
          </p>
        )}
        {adjustments.length > 0 && (
          <p className="muted">
            {t("Стрелками отмечены дробления и бонусные эмиссии; цены до них пересчитаны на текущую акцию.",
               "Strelkalar bilan maydalash va bonus emissiyalar belgilangan; ulardan oldingi narxlar qayta hisoblangan.",
               "The arrows mark splits and bonus issues; prices before them are restated onto the current share.")}
          </p>
        )}
        {finFields.length > 0 && (
          <p className="muted">
            {t("Годовой показатель нанесён на 31 декабря своего периода и держится до следующего отчёта — раньше его не существовало.",
               "Yillik ko'rsatkich o'z davrining 31 dekabriga qo'yilgan va keyingi hisobotgacha saqlanadi.",
               "An annual figure is placed on 31 December of its period and held until the next filing — before that it did not exist.")}
          </p>
        )}
      </div>
      <TechnicalBacktestCard ticker={ticker} lang={lang} apiFetch={apiFetch} signedIn={signedIn}
        hasProAccess={hasProAccess} onUpgrade={onUpgrade} />
    </div>
  );
}

export { AdvancedChart };
