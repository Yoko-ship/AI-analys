// Shared pieces of the price charts drawn with TradingView Lightweight Charts:
// the time encoding, the theme, number formats, the synthetic chart types
// (Heikin Ashi, Renko, Kagi, point & figure) and two canvas primitives the
// library does not ship (a two-point trend line, point & figure glyphs).

export const UP = "#2fc584";
export const DOWN = "#ee6a60";
export const UP_FILL = "rgba(47,197,132,0.22)";
export const UP_FILL_FAINT = "rgba(47,197,132,0.02)";
export const DOWN_FILL = "rgba(238,106,96,0.22)";
export const DOWN_FILL_FAINT = "rgba(238,106,96,0.02)";

// Wall-clock Tashkent time stored as if it were UTC. Every formatter below
// reads it back with timeZone "UTC", so "2026-09-18T10:00" is 10:00 for a
// reader in any time zone — the exchange's hour, not the browser's.
export function toTime(d) {
  const [ymd, hm] = String(d).split("T");
  const [y, m, dd] = ymd.split("-").map(Number);
  const [h, mi] = (hm || "0:0").split(":").map(Number);
  return Date.UTC(y, m - 1, dd, h || 0, mi || 0) / 1000;
}

/**
 * One bar per moment, ascending. The feed can carry the same session twice;
 * the canvas refuses a repeated time, and the later row is the settled one.
 */
export function uniqueByTime(points) {
  const out = [];
  for (const p of points) {
    if (out.length && toTime(out.at(-1).date) === toTime(p.date)) out[out.length - 1] = p;
    else out.push(p);
  }
  return out;
}

/** Quote history arrives as "20260924"; everything else is ISO. */
export function isoDay(v) {
  const s = String(v || "").trim();
  return /^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : s.slice(0, 10);
}

export const hasHour = (d) => String(d || "").includes("T");

/** Nearest integer — an index or a box count, never a published figure. */
export const nearestInt = (v) => (v < 0 ? Math.ceil(v - 0.5) : Math.floor(v + 0.5));

export function readChartTheme() {
  const fallback = { text: "#111827", muted: "#667085", border: "rgba(15,23,42,0.10)", panel: "#ffffff", accent: "#6257d9" };
  if (typeof document === "undefined") return fallback;
  const cs = getComputedStyle(document.body);
  const v = (name, fb) => cs.getPropertyValue(name).trim() || fb;
  return {
    text: v("--text", fallback.text),
    muted: v("--muted", fallback.muted),
    border: v("--border", fallback.border),
    panel: v("--panel", fallback.panel),
    accent: v("--accent", fallback.accent),
  };
}

/** Enough decimals that a 0.005 step on a 2-сум share never prints twice. */
export function priceDecimals(price) {
  const p = Math.abs(price || 0);
  return p >= 1 ? 2 : p >= 0.01 ? 4 : 6;
}

/** Prices in the reader's locale: «93,95», «56 000», «0,0042». */
export function priceFormatFor(price, lang) {
  const locale = lang === "en" ? "en-US" : "ru-RU";
  return {
    type: "custom",
    minMove: 1 / 10 ** priceDecimals(price),
    formatter: (v) => Number(v).toLocaleString(locale, { maximumFractionDigits: priceDecimals(v) }),
  };
}

/** A percent move from the comparison's shared start: «+12,5%». */
export function percentFormat(lang) {
  const locale = lang === "en" ? "en-US" : "ru-RU";
  return {
    type: "custom",
    minMove: 0.01,
    formatter: (v) => `${v > 0 ? "+" : ""}${Number(v).toLocaleString(locale, { maximumFractionDigits: 1 })}%`,
  };
}

/** Any other figure, through the caller's formatter (оборот, ROE, …). */
export const customFormat = (formatter, minMove = 0.01) => ({ type: "custom", minMove, formatter });

export const ohlcOk = (p) => p.open > 0 && p.high > 0 && p.low > 0 && p.close > 0
  && p.low <= Math.min(p.open, p.close) && Math.max(p.open, p.close) <= p.high;

/** A bar the candle series can draw: a day without a range becomes a flat tick. */
export function ohlcBar(p, time) {
  return ohlcOk(p)
    ? { time, open: p.open, high: p.high, low: p.low, close: p.close }
    : { time, open: p.close, high: p.close, low: p.close, close: p.close };
}

// ── Synthetic chart types ───────────────────────────────────────────────────
// Their values are constructions from closes, not traded prices; the pages
// that draw them say so under the chart.

export function heikinAshi(points) {
  let previous = null;
  return points.map((point) => {
    const source = ohlcOk(point) ? point : { ...point, open: point.close, high: point.close, low: point.close };
    const close = (source.open + source.high + source.low + source.close) / 4;
    const open = previous ? (previous.open + previous.close) / 2 : (source.open + source.close) / 2;
    const next = { ...source, open, close, high: Math.max(source.high, open, close), low: Math.min(source.low, open, close) };
    previous = next;
    return next;
  });
}

/** The box size: the median non-zero close-to-close move. */
export function movementBox(points) {
  const moves = points.slice(1).map((point, i) => Math.abs(point.close - points[i].close))
    .filter((value) => value > 0).sort((a, b) => a - b);
  if (moves.length) return moves[Math.floor(moves.length / 2)];
  const closes = points.map((point) => point.close).filter(Number.isFinite);
  return Math.max(0.01, (Math.max(...closes) - Math.min(...closes)) / 30 || closes[0] * 0.01 || 1);
}

export function renko(points) {
  if (!points.length) return { box: 1, bricks: [] };
  const box = movementBox(points);
  let level = points[0].close;
  const bricks = [];
  points.slice(1).forEach((point) => {
    while (Math.abs(point.close - level) >= box && bricks.length < 400) {
      const direction = point.close > level ? 1 : -1;
      const next = level + direction * box;
      bricks.push({ from: level, to: next, direction, date: point.date });
      level = next;
    }
  });
  return { box, bricks };
}

export function kagi(points) {
  if (!points.length) return { box: 1, turns: [] };
  const box = movementBox(points);
  const turns = [{ value: points[0].close, direction: 0, date: points[0].date }];
  let extreme = points[0].close, direction = 0;
  points.slice(1).forEach((point) => {
    const price = point.close;
    if (!direction && Math.abs(price - extreme) >= box) direction = price > extreme ? 1 : -1;
    if ((direction >= 0 && price >= extreme) || (direction <= 0 && price <= extreme)) {
      extreme = price;
      turns[turns.length - 1] = { value: price, direction, date: point.date };
    } else if (Math.abs(price - extreme) >= box) {
      turns.push({ value: price, direction: -direction, date: point.date });
      direction *= -1;
      extreme = price;
    }
  });
  return { box, turns };
}

export function pointFigure(points) {
  if (!points.length) return { box: 1, columns: [] };
  const box = movementBox(points);
  const columns = [];
  let anchor = points[0].close;
  points.slice(1).forEach((point) => {
    const boxes = Math.floor(Math.abs(point.close - anchor) / box);
    if (!boxes) return;
    const direction = point.close > anchor ? 1 : -1;
    const last = columns.at(-1);
    if (!last || last.direction === direction) {
      if (!last) columns.push({ direction, from: anchor, to: anchor + direction * boxes * box, date: point.date });
      else if ((direction > 0 && point.close > last.to) || (direction < 0 && point.close < last.to)) {
        last.to = anchor + direction * boxes * box;
        last.date = point.date;
      }
    } else if (boxes >= 3) {
      columns.push({ direction, from: anchor + direction * box, to: anchor + direction * boxes * box, date: point.date });
    }
    anchor = columns.at(-1)?.to ?? anchor;
  });
  return { box, columns: columns.slice(-120) };
}

// Synthetic figures have no calendar of their own: each brick or column is one
// step on an evenly spaced axis, labelled with the date that completed it.
const SYNTHETIC_T0 = Date.UTC(2000, 0, 3) / 1000;
export const syntheticTime = (i) => SYNTHETIC_T0 + i * 86400;

/**
 * A synthetic type as series data for the canvas: Renko and P&F as boxes on a
 * candle series, Kagi as a step line. `labels` maps each synthetic time back to
 * the real session date for the axis and the readout.
 */
export function syntheticSeries(type, points) {
  const labels = new Map();
  if (type === "renko") {
    const { bricks } = renko(points);
    const data = bricks.map((b, i) => {
      const time = syntheticTime(i);
      labels.set(time, b.date);
      return { time, open: b.from, close: b.to, high: Math.max(b.from, b.to), low: Math.min(b.from, b.to) };
    });
    return { kind: "candle", data, labels };
  }
  if (type === "point_figure") {
    const { box, columns } = pointFigure(points);
    const data = columns.map((c, i) => {
      const time = syntheticTime(i);
      labels.set(time, c.date);
      return { time, open: c.from, close: c.to, high: Math.max(c.from, c.to), low: Math.min(c.from, c.to) };
    });
    const glyphs = columns.map((c, i) => ({ time: syntheticTime(i), direction: c.direction, from: c.from, to: c.to }));
    return { kind: "candle", data, labels, glyphs, box };
  }
  // Kagi: thick after a rise, thin after a fall is not something a line series
  // can vary per segment; colour carries the direction instead.
  const { turns } = kagi(points);
  const data = turns.map((turn, i) => {
    const time = syntheticTime(i);
    labels.set(time, turn.date);
    return { time, value: turn.value, color: i && turn.value < turns[i - 1].value ? DOWN : UP };
  });
  return { kind: "line", data, labels };
}

/** Mean close over a CALENDAR window of the raw daily series (ТЗ §6). */
export function calendarMA(daily, days, minObs = 3) {
  const out = new Array(daily.length).fill(null);
  let start = 0, sum = 0;
  for (let i = 0; i < daily.length; i++) {
    sum += daily[i].close;
    const cutoff = new Date(daily[i].date);
    cutoff.setDate(cutoff.getDate() - (days - 1));
    while (start < i && new Date(daily[start].date) < cutoff) {
      sum -= daily[start].close;
      start += 1;
    }
    const n = i - start + 1;
    out[i] = n >= minObs ? sum / n : null;
  }
  return out;
}

// ── Primitives ──────────────────────────────────────────────────────────────

/**
 * A trend line between two (time, price) points, with its handles. One point
 * shows just the handle, so the first click has a visible result.
 */
export class TrendLinePrimitive {
  constructor(points, color, handleFill) {
    this._points = points;
    this._color = color;
    this._handleFill = handleFill;
    this._chart = null;
    this._series = null;
  }

  attached({ chart, series }) { this._chart = chart; this._series = series; }

  detached() { this._chart = null; this._series = null; }

  paneViews() {
    return [{ zOrder: () => "top", renderer: () => ({ draw: (target) => this._draw(target) }) }];
  }

  _draw(target) {
    if (!this._chart || !this._series) return;
    const ts = this._chart.timeScale();
    const pts = this._points
      .map((p) => ({ x: ts.timeToCoordinate(p.time), y: this._series.priceToCoordinate(p.value) }))
      .filter((p) => p.x != null && p.y != null);
    if (!pts.length) return;
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      ctx.save();
      ctx.strokeStyle = this._color;
      ctx.lineWidth = 1.8;
      if (pts.length === 2) {
        ctx.setLineDash([5, 3]);
        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        ctx.lineTo(pts[1].x, pts[1].y);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      ctx.fillStyle = this._handleFill;
      ctx.lineWidth = 1.5;
      pts.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 3.4, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      });
      ctx.restore();
    });
  }
}

/**
 * Straight segments in chart coordinates — a pattern's neckline, a triangle's
 * edges, a flag's channel, a target level. ``segments``: [{ from: {time, value},
 * to: {time, value}, color, width, dash, label }]; a label is written just
 * above the segment's right end.
 */
export class SegmentsPrimitive {
  constructor(segments) {
    this._segments = segments;
    this._chart = null;
    this._series = null;
  }

  attached({ chart, series }) { this._chart = chart; this._series = series; }

  detached() { this._chart = null; this._series = null; }

  paneViews() {
    return [{ zOrder: () => "top", renderer: () => ({ draw: (target) => this._draw(target) }) }];
  }

  _draw(target) {
    if (!this._chart || !this._series) return;
    const ts = this._chart.timeScale();
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      ctx.save();
      this._segments.forEach((seg) => {
        const x1 = ts.timeToCoordinate(seg.from.time), x2 = ts.timeToCoordinate(seg.to.time);
        const y1 = this._series.priceToCoordinate(seg.from.value), y2 = this._series.priceToCoordinate(seg.to.value);
        if (x1 == null || x2 == null || y1 == null || y2 == null) return;
        ctx.strokeStyle = seg.color;
        ctx.lineWidth = seg.width || 1.5;
        ctx.setLineDash(seg.dash || []);
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        if (seg.label) {
          ctx.setLineDash([]);
          ctx.font = "600 11px system-ui, -apple-system, sans-serif";
          ctx.fillStyle = seg.color;
          ctx.textAlign = "right";
          ctx.textBaseline = "bottom";
          ctx.fillText(seg.label, Math.max(x1, x2) - 2, Math.min(y1, y2) - 3);
        }
      });
      ctx.restore();
    });
  }
}

/**
 * Shaded rectangles behind the price — the extent of each figure, from its
 * first session to the one that completed it. ``boxes``: [{ from, to (chart
 * time), high, low, fill }].
 */
export class BoxesPrimitive {
  constructor(boxes) {
    this._boxes = boxes;
    this._chart = null;
    this._series = null;
  }

  attached({ chart, series }) { this._chart = chart; this._series = series; }

  detached() { this._chart = null; this._series = null; }

  paneViews() {
    return [{ zOrder: () => "bottom", renderer: () => ({ draw: (target) => this._draw(target) }) }];
  }

  _draw(target) {
    if (!this._chart || !this._series) return;
    const ts = this._chart.timeScale();
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      this._boxes.forEach((b) => {
        const x1 = ts.timeToCoordinate(b.from), x2 = ts.timeToCoordinate(b.to);
        const y1 = this._series.priceToCoordinate(b.high), y2 = this._series.priceToCoordinate(b.low);
        if (x1 == null || x2 == null || y1 == null || y2 == null) return;
        ctx.fillStyle = b.fill;
        ctx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1) || 1, Math.abs(y2 - y1) || 1);
      });
    });
  }
}

/** Point & figure: an X per box in a rising column, an O in a falling one. */
export class PointFigurePrimitive {
  constructor(columns, box) {
    this._columns = columns;
    this._box = box;
    this._chart = null;
    this._series = null;
  }

  attached({ chart, series }) { this._chart = chart; this._series = series; }

  detached() { this._chart = null; this._series = null; }

  paneViews() {
    return [{ zOrder: () => "top", renderer: () => ({ draw: (target) => this._draw(target) }) }];
  }

  _draw(target) {
    if (!this._chart || !this._series || !(this._box > 0)) return;
    const ts = this._chart.timeScale();
    const spacing = ts.options().barSpacing || 6;
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      ctx.save();
      ctx.lineWidth = 1.4;
      this._columns.forEach((c) => {
        const x = ts.timeToCoordinate(c.time);
        if (x == null) return;
        const lo = Math.min(c.from, c.to), hi = Math.max(c.from, c.to);
        const steps = Math.min(80, nearestInt((hi - lo) / this._box) + 1);
        const yA = this._series.priceToCoordinate(lo);
        const yB = this._series.priceToCoordinate(lo + this._box);
        const boxPx = yA != null && yB != null ? Math.abs(yA - yB) : spacing;
        const r = Math.max(2, Math.min(spacing * 0.38, boxPx * 0.42, 8));
        ctx.strokeStyle = c.direction > 0 ? UP : DOWN;
        for (let k = 0; k < steps; k++) {
          const y = this._series.priceToCoordinate(lo + k * this._box);
          if (y == null) continue;
          ctx.beginPath();
          if (c.direction > 0) {
            ctx.moveTo(x - r, y - r); ctx.lineTo(x + r, y + r);
            ctx.moveTo(x + r, y - r); ctx.lineTo(x - r, y + r);
          } else {
            ctx.arc(x, y, r, 0, Math.PI * 2);
          }
          ctx.stroke();
        }
      });
      ctx.restore();
    });
  }
}
