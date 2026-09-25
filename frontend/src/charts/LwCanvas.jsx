// TradingView Lightweight Charts™
// Copyright (c) 2025 TradingView, Inc. https://www.tradingview.com/
// Licensed under the Apache License 2.0. The licence asks for a link to
// tradingview.com on the page that shows the chart: it is the credit line this
// component renders under every chart, in place of the logo drawn on the plot.
import React from "react";
import {
  createChart, createSeriesMarkers, createTextWatermark, AreaSeries, LineSeries, BaselineSeries, CandlestickSeries,
  BarSeries, HistogramSeries, CrosshairMode, ColorType, TickMarkType,
} from "lightweight-charts";
import {
  readChartTheme, nearestInt, TrendLinePrimitive, PointFigurePrimitive, SegmentsPrimitive, BoxesPrimitive,
} from "./lwCore.js";

const KINDS = {
  line: LineSeries, area: AreaSeries, baseline: BaselineSeries,
  candle: CandlestickSeries, bar: BarSeries, histogram: HistogramSeries,
};

// Fewer bars than this and a zoomed view stops being a chart.
const MIN_VISIBLE_BARS = 12;

/**
 * One Lightweight Charts canvas, driven by a declarative spec.
 *
 * Number formats belong to the series (options.priceFormat), so an RSI pane
 * and a price pane on one canvas each read in their own unit.
 *
 * spec = {
 *   series: [{ key, kind, pane, data, options, markers, trend, glyphs, segments, boxes, lines, scale }],
 *   main: key of the series the crosshair, clicks and the visible range read,
 *   panes: [{ height, title }] for panes 1…n (pane 0 takes the rest),
 *   hourly: the axis carries hours,
 *   labels: Map(time → date) for synthetic types with no calendar of their own,
 * }
 *
 * The series are rebuilt whenever the spec changes; the visible range survives
 * that unless `viewKey` changed, in which case `initialView` ({ from, to } in
 * chart time, or null to fit everything) is applied. Bumping `resetToken`
 * re-applies it. `focus` ({ from, to, token } in chart time) moves the view to
 * a span — a pattern picked from a list — without resetting anything else.
 *
 * Scroll-wheel over the chart scrolls the PAGE — this sits in the middle of a
 * long company page — and Ctrl + wheel zooms, as the charts here always have.
 */
export default function LwCanvas({
  spec, height, lang, grid = true, crosshair = true, pan = true, viewKey, initialView = null,
  resetToken = 0, focus = null, onHover, onClick, onRange, className = "", style, ...rest
}) {
  const boxRef = React.useRef(null);
  const chartRef = React.useRef(null);
  const liveRef = React.useRef({ series: new Map(), detach: [] });
  const cbRef = React.useRef({});
  const specRef = React.useRef(spec);
  const initialViewRef = React.useRef(initialView);
  const viewKeyRef = React.useRef(undefined);
  // The view as it stood when the previous series were taken down.
  const lastRangeRef = React.useRef(null);
  const [themeTick, setThemeTick] = React.useState(0);
  const locale = lang === "en" ? "en-US" : "ru-RU";

  cbRef.current = { onHover, onClick, onRange };
  specRef.current = spec;
  initialViewRef.current = initialView;

  // The visible data span, reported as indices into the main series' data.
  const reportRange = React.useCallback(() => {
    const chart = chartRef.current;
    const s = specRef.current;
    const main = s?.series.find((x) => x.key === s.main);
    const lr = chart?.timeScale().getVisibleLogicalRange();
    if (!chart || !main || !lr || !main.data.length) return;
    const last = main.data.length - 1;
    // A bar is in view when its centre is: logical i spans i − ½ … i + ½.
    const from = Math.max(0, Math.min(last, Math.ceil(lr.from - 0.5)));
    const to = Math.max(0, Math.min(last, Math.floor(lr.to + 0.5)));
    // "Changed" means the reader moved away from the view the chart opened on:
    // the bars that view shows, not whatever range an interim frame reported.
    const view = initialViewRef.current;
    let expFrom = 0;
    if (view) {
      const i = main.data.findIndex((d) => d.time >= view.from);
      expFrom = i < 0 ? 0 : i;
    }
    const changed = Math.abs(from - expFrom) > 1 || Math.abs(to - last) > 1;
    cbRef.current.onRange?.({ from, to, changed });
  }, []);

  const applyInitialView = React.useCallback(() => {
    const apply = () => {
      const chart = chartRef.current;
      if (!chart) return;
      const ts = chart.timeScale();
      const view = initialViewRef.current;
      try {
        if (view) ts.setVisibleRange(view); else ts.fitContent();
      } catch {
        ts.fitContent();
      }
    };
    apply();
    // On a fresh canvas the width arrives a frame later (autoSize observes the
    // box), and a range set against a zero-width scale lands on the wrong bars.
    if (typeof requestAnimationFrame !== "undefined") {
      requestAnimationFrame(() => requestAnimationFrame(apply));
    }
  }, []);

  // One chart for the component's life.
  React.useEffect(() => {
    const el = boxRef.current;
    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, fontFamily: "inherit", fontSize: 11,
        attributionLogo: false,
        panes: { separatorColor: "rgba(127,127,127,0.18)", enableResize: false } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
      // «Макс» is ten years of sessions — it has to fit the width, not stop at
      // the library's half-pixel default spacing.
      timeScale: { borderVisible: false, rightOffset: 3, lockVisibleTimeRangeOnResize: true, minBarSpacing: 0.05 },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true },
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
    });
    chartRef.current = chart;

    const onWheel = (event) => {
      if (!event.ctrlKey || event.deltaY === 0) return;
      event.preventDefault();
      event.stopPropagation();
      const ts = chart.timeScale();
      const lr = ts.getVisibleLogicalRange();
      if (!lr) return;
      const rect = el.getBoundingClientRect();
      const anchor = ts.coordinateToLogical(event.clientX - rect.left) ?? (lr.from + lr.to) / 2;
      const f = event.deltaY < 0 ? 0.8 : 1.25;
      const from = anchor - (anchor - lr.from) * f;
      const to = anchor + (lr.to - anchor) * f;
      if (to - from < MIN_VISIBLE_BARS && f < 1) return;
      ts.setVisibleLogicalRange({ from, to });
    };
    el.addEventListener("wheel", onWheel, { passive: false });

    const onMove = (param) => {
      const s = specRef.current;
      if (!param.point || param.logical == null || param.point.x < 0) { cbRef.current.onHover?.(null); return; }
      const values = {};
      (liveRef.current.series || new Map()).forEach((api, key) => {
        const d = param.seriesData.get(api);
        if (d) values[key] = d.value ?? d.close;
      });
      const main = s?.series.find((x) => x.key === s.main);
      const index = nearestInt(param.logical);
      if (!main || index < 0 || index >= main.data.length) { cbRef.current.onHover?.(null); return; }
      cbRef.current.onHover?.({ index, time: main.data[index].time, point: param.point, pane: param.paneIndex ?? 0,
        width: el.clientWidth, height: el.clientHeight, values });
    };
    // Clicks are read off the element, not chart.subscribeClick: the library
    // drops a second click that lands within 500 ms of the first unless it is
    // on the same spot (it waits for a double-click), and a trend line's
    // second point is exactly that click.
    let down = null;
    const onPointerDown = (e) => {
      if (!e.isPrimary || (e.pointerType === "mouse" && e.button !== 0)) return;
      down = { x: e.clientX, y: e.clientY };
    };
    const onPointerUp = (e) => {
      if (!down || !e.isPrimary) return;
      const moved = Math.abs(e.clientX - down.x) + Math.abs(e.clientY - down.y);
      down = null;
      if (moved > 4) return;
      const s = specRef.current;
      const main = s?.series.find((x) => x.key === s.main);
      if (!main) return;
      const rect = el.getBoundingClientRect();
      const x = e.clientX - rect.left, y = e.clientY - rect.top;
      const logical = chart.timeScale().coordinateToLogical(x);
      if (logical == null) return;
      let top = 0, pane = -1;
      chart.panes().forEach((p, i) => {
        const h = p.getHeight();
        if (pane < 0 && y >= top && y < top + h) pane = i;
        top += h + 1;
      });
      const index = nearestInt(logical);
      if (pane < 0 || index < 0 || index >= main.data.length) return;
      cbRef.current.onClick?.({ index, time: main.data[index].time, point: { x, y }, pane });
    };
    el.addEventListener("pointerdown", onPointerDown);
    el.addEventListener("pointerup", onPointerUp);
    chart.subscribeCrosshairMove(onMove);
    chart.timeScale().subscribeVisibleLogicalRangeChange(reportRange);

    const mo = new MutationObserver(() => setThemeTick((n) => n + 1));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    mo.observe(document.body, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      mo.disconnect();
      el.removeEventListener("wheel", onWheel);
      chart.unsubscribeCrosshairMove(onMove);
      el.removeEventListener("pointerdown", onPointerDown);
      el.removeEventListener("pointerup", onPointerUp);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(reportRange);
      chart.remove();
      chartRef.current = null;
      liveRef.current = { series: new Map(), detach: [] };
    };
  }, [reportRange]);

  // Look and feel: theme, grid, crosshair, the axis language.
  React.useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const th = readChartTheme();
    const labels = spec?.labels || null;
    const dateOf = (time) => {
      if (labels?.has(time)) return new Date(`${String(labels.get(time)).slice(0, 10)}T00:00:00Z`);
      return new Date(time * 1000);
    };
    chart.applyOptions({
      layout: { textColor: th.muted },
      grid: { vertLines: { visible: false }, horzLines: { visible: grid, color: th.border, style: 2 } },
      crosshair: {
        mode: crosshair ? CrosshairMode.Normal : CrosshairMode.Hidden,
        vertLine: { color: th.muted, labelBackgroundColor: th.text },
        horzLine: { color: th.muted, labelBackgroundColor: th.text },
      },
      localization: {
        locale,
        timeFormatter: (time) => {
          const d = dateOf(time);
          const withHour = !labels && (d.getUTCHours() || d.getUTCMinutes());
          return d.toLocaleString(locale, { timeZone: "UTC", year: "numeric", month: "short", day: "numeric",
            ...(withHour ? { hour: "2-digit", minute: "2-digit" } : {}) });
        },
      },
      timeScale: {
        timeVisible: Boolean(spec?.hourly),
        tickMarkFormatter: (time, type) => {
          const d = dateOf(time);
          const o = { timeZone: "UTC" };
          if (labels) return d.toLocaleDateString(locale, { ...o, day: "numeric", month: "short" });
          if (type === TickMarkType.Year) return d.toLocaleDateString(locale, { ...o, year: "numeric" });
          if (type === TickMarkType.Month) return d.toLocaleDateString(locale, { ...o, month: "short" });
          if (type === TickMarkType.DayOfMonth) return d.toLocaleDateString(locale, { ...o, day: "numeric", month: "short" });
          return d.toLocaleTimeString(locale, { ...o, hour: "2-digit", minute: "2-digit" });
        },
      },
      handleScroll: { pressedMouseMove: pan, horzTouchDrag: pan },
    });
  }, [grid, crosshair, pan, locale, spec?.hourly, spec?.labels, themeTick]);

  // The series themselves.
  React.useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !spec) return undefined;
    const ts = chart.timeScale();
    const sameView = viewKeyRef.current === viewKey;
    const keep = sameView ? lastRangeRef.current : null;
    const th = readChartTheme();

    const live = { series: new Map(), detach: [] };
    spec.series.forEach((item) => {
      if (!item.data?.length) return;
      const api = chart.addSeries(KINDS[item.kind], item.options || {}, item.pane || 0);
      api.setData(item.data);
      live.series.set(item.key, api);
      if (item.markers?.length) {
        const m = createSeriesMarkers(api, item.markers);
        live.detach.push(() => m.detach());
      }
      if (item.trend?.length) {
        const p = new TrendLinePrimitive(item.trend, th.accent, th.panel);
        api.attachPrimitive(p);
        live.detach.push(() => api.detachPrimitive(p));
      }
      if (item.boxes?.length) {
        const p = new BoxesPrimitive(item.boxes);
        api.attachPrimitive(p);
        live.detach.push(() => api.detachPrimitive(p));
      }
      if (item.segments?.length) {
        const p = new SegmentsPrimitive(item.segments);
        api.attachPrimitive(p);
        live.detach.push(() => api.detachPrimitive(p));
      }
      if (item.glyphs?.columns?.length) {
        const p = new PointFigurePrimitive(item.glyphs.columns, item.glyphs.box);
        api.attachPrimitive(p);
        live.detach.push(() => api.detachPrimitive(p));
      }
      (item.lines || []).forEach((line) => {
        const pl = api.createPriceLine({ lineWidth: 1, lineStyle: 2, axisLabelVisible: false, color: th.muted, ...line });
        live.detach.push(() => api.removePriceLine(pl));
      });
      if (item.scale) chart.priceScale(item.options?.priceScaleId || "right", item.pane || 0).applyOptions(item.scale);
    });
    // A pane has no heading of its own; its name sits in its top-left corner.
    chart.panes().forEach((pane, i) => {
      const title = i > 0 ? spec.panes?.[i - 1]?.title : null;
      if (!title) return;
      const wm = createTextWatermark(pane, { horzAlign: "left", vertAlign: "top",
        lines: [{ text: title, color: spec.panes[i - 1].color || th.muted, fontSize: 11 }] });
      live.detach.push(() => wm.detach());
    });
    liveRef.current = live;

    // Sub-panes get their pixel height; the price pane takes what is left.
    const panes = chart.panes();
    const fixed = (spec.panes || []).reduce((sum, p) => sum + (p.height || 0), 0);
    const total = height || boxRef.current?.clientHeight || 400;
    panes.forEach((pane, i) => {
      const h = i === 0 ? Math.max(120, total - fixed) : spec.panes?.[i - 1]?.height;
      if (h) pane.setStretchFactor(h);
    });

    if (keep) {
      ts.setVisibleLogicalRange(keep);
    } else {
      viewKeyRef.current = viewKey;
      applyInitialView();
    }
    reportRange();

    return () => {
      if (chartRef.current !== chart) return;
      // Read BEFORE the series go: an empty chart has no visible range, and the
      // next pass would fall back to the opening view — zoom lost on every
      // indicator toggle or window resize.
      lastRangeRef.current = ts.getVisibleLogicalRange();
      live.detach.forEach((fn) => { try { fn(); } catch { /* already gone with its series */ } });
      live.series.forEach((api) => chart.removeSeries(api));
    };
  }, [spec, viewKey, height, applyInitialView, reportRange]);

  React.useEffect(() => {
    if (resetToken) applyInitialView();
  }, [resetToken, applyInitialView]);

  React.useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !focus) return;
    try { chart.timeScale().setVisibleRange({ from: focus.from, to: focus.to }); } catch { /* outside the data */ }
  }, [focus]);

  return (
    <>
      <div className={`lw-canvas ${className}`} style={{ position: "relative", height, ...style }} {...rest}>
        <div ref={boxRef} className="lw-canvas-surface" style={{ position: "absolute", inset: 0 }} />
      </div>
      <a className="lw-credit" href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">
        {lang === "en" ? "Charts by TradingView" : lang === "uz" ? "Grafiklar: TradingView" : "Графики: TradingView"}
      </a>
    </>
  );
}
