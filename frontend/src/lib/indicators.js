/**
 * Chart indicators for the advanced price chart.
 *
 * Everything here is pure and works on a CALENDAR-daily series, never on the
 * raw list of sessions — which is the one decision in this file that is not
 * textbook.
 *
 * ТЗ §6 already settles it for moving averages: an average is taken over a
 * calendar window, not over N observations, because most securities on this
 * market trade on a minority of days. "SMA(50)" read as fifty observations
 * spans ten weeks on UZTL and two and a half YEARS on a security that prints
 * twice a month — the same label drawing two different lines. The same trap
 * catches RSI, MACD and the stochastic, all of which count back N bars.
 *
 * So the sessions are forward-filled onto every calendar day first and the
 * standard formulas are applied to that. Forward-filling is not an invention:
 * it is what the exchange itself does with a close on a day with no executions,
 * and what the board shows. A stretch with no trading then reads as a stretch
 * with no momentum — RSI sits at 50, MACD converges on zero — which is the
 * honest answer, not a gap.
 *
 * Every function returns an array the same length as its input, `null` where
 * the window is not yet full. Nothing is back-filled or extrapolated.
 */

/** ISO day arithmetic without touching the local timezone. */
function dayNumber(iso) {
  const s = String(iso || "");
  const y = Number(s.slice(0, 4)), m = Number(s.slice(5, 7)), d = Number(s.slice(8, 10));
  if (!y || !m || !d) return null;
  return Math.floor(Date.UTC(y, m - 1, d) / 86400000);
}

function isoFromDayNumber(n) {
  return new Date(n * 86400000).toISOString().slice(0, 10);
}

/**
 * Forward-fill traded sessions onto every calendar day they span.
 *
 * `points` is ascending and carries at least { date, close }; high/low fall
 * back to the close, which is what a session without an intraday record has.
 * Returns parallel arrays plus `indexByDate`, so a value computed here can be
 * read back onto the sessions actually drawn without recomputing anything.
 */
export function calendarSeries(points) {
  const rows = (points || []).filter((p) => p && p.date && Number(p.close) > 0);
  if (rows.length < 2) return { days: [], close: [], high: [], low: [], indexByDate: new Map() };
  const first = dayNumber(rows[0].date);
  const last = dayNumber(rows[rows.length - 1].date);
  if (first == null || last == null || last < first) {
    return { days: [], close: [], high: [], low: [], indexByDate: new Map() };
  }
  const days = [], close = [], high = [], low = [], indexByDate = new Map();
  let cursor = 0;
  let held = null;
  for (let n = first; n <= last; n++) {
    while (cursor < rows.length && dayNumber(rows[cursor].date) <= n) {
      const r = rows[cursor];
      held = {
        close: Number(r.close),
        high: Number(r.high) > 0 ? Number(r.high) : Number(r.close),
        low: Number(r.low) > 0 ? Number(r.low) : Number(r.close),
      };
      cursor += 1;
    }
    if (!held) continue;
    const iso = isoFromDayNumber(n);
    indexByDate.set(iso, days.length);
    days.push(iso);
    close.push(held.close);
    high.push(held.high);
    low.push(held.low);
  }
  return { days, close, high, low, indexByDate };
}

/** Read a calendar-daily result back onto the dates a chart actually draws. */
export function alignToDates(daily, indexByDate, dates) {
  return (dates || []).map((d) => {
    const i = indexByDate.get(String(d));
    return i == null ? null : (daily[i] ?? null);
  });
}

/** Simple moving average over `n` calendar days. */
export function sma(values, n) {
  const out = new Array(values.length).fill(null);
  if (!(n > 0)) return out;
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= n) sum -= values[i - n];
    if (i >= n - 1) out[i] = sum / n;
  }
  return out;
}

/**
 * Exponential moving average, seeded with the first full simple average.
 * Seeding on the SMA rather than on the first observation keeps the first
 * drawn value from being a single day dressed up as an average.
 */
export function ema(values, n) {
  const out = new Array(values.length).fill(null);
  if (!(n > 0) || values.length < n) return out;
  const k = 2 / (n + 1);
  let sum = 0;
  for (let i = 0; i < n; i++) sum += values[i];
  let prev = sum / n;
  out[n - 1] = prev;
  for (let i = n; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** Population standard deviation over a rolling window — the Bollinger convention. */
function rollingStd(values, n, means) {
  const out = new Array(values.length).fill(null);
  for (let i = n - 1; i < values.length; i++) {
    const m = means[i];
    if (m == null) continue;
    let acc = 0;
    for (let j = i - n + 1; j <= i; j++) acc += (values[j] - m) ** 2;
    out[i] = Math.sqrt(acc / n);
  }
  return out;
}

/** Bollinger bands: an `n`-day average with a ±k·σ envelope. */
export function bollinger(values, n = 20, k = 2) {
  const mid = sma(values, n);
  const sd = rollingStd(values, n, mid);
  return {
    mid,
    upper: mid.map((m, i) => (m == null || sd[i] == null ? null : m + k * sd[i])),
    lower: mid.map((m, i) => (m == null || sd[i] == null ? null : m - k * sd[i])),
  };
}

/**
 * Relative strength index, Wilder's smoothing.
 *
 * A flat stretch — which is what a forward-filled quiet month looks like —
 * has neither gains nor losses, and Wilder's ratio then decays towards 50.
 * That is the reading it should give: no trading is not weakness.
 */
export function rsi(values, n = 14) {
  const out = new Array(values.length).fill(null);
  if (values.length <= n) return out;
  let gain = 0, loss = 0;
  for (let i = 1; i <= n; i++) {
    const d = values[i] - values[i - 1];
    if (d >= 0) gain += d; else loss -= d;
  }
  gain /= n; loss /= n;
  // A window with no losses at all is not "infinitely strong" — it is 100 by
  // definition, and dividing by zero would put a hole in the line instead.
  out[n] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  for (let i = n + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    gain = (gain * (n - 1) + (d > 0 ? d : 0)) / n;
    loss = (loss * (n - 1) + (d < 0 ? -d : 0)) / n;
    out[i] = loss === 0 ? (gain === 0 ? 50 : 100) : 100 - 100 / (1 + gain / loss);
  }
  return out;
}

/** MACD: the gap between two EMAs, its own average, and the difference. */
export function macd(values, fast = 12, slow = 26, signalN = 9) {
  const f = ema(values, fast);
  const s = ema(values, slow);
  const line = values.map((_, i) => (f[i] == null || s[i] == null ? null : f[i] - s[i]));
  // The signal is an EMA of the MACD line, which only exists from the slow
  // EMA onwards — feed it the defined tail and put the result back in place.
  const start = line.findIndex((v) => v != null);
  const signal = new Array(values.length).fill(null);
  if (start >= 0) {
    const tail = line.slice(start).map((v) => v ?? 0);
    ema(tail, signalN).forEach((v, i) => { signal[start + i] = v; });
  }
  return {
    line,
    signal,
    hist: line.map((v, i) => (v == null || signal[i] == null ? null : v - signal[i])),
  };
}

/** Stochastic oscillator: where the close sits inside its `n`-day range. */
export function stochastic(high, low, close, n = 14, d = 3) {
  const k = new Array(close.length).fill(null);
  for (let i = n - 1; i < close.length; i++) {
    let hi = -Infinity, lo = Infinity;
    for (let j = i - n + 1; j <= i; j++) {
      if (high[j] > hi) hi = high[j];
      if (low[j] < lo) lo = low[j];
    }
    // A range of zero is a price that did not move all window. Calling that
    // 0 % (bottom of the range) or 100 % (top) would both be a claim; 50 is
    // the only reading the data supports.
    k[i] = hi === lo ? 50 : ((close[i] - lo) / (hi - lo)) * 100;
  }
  const start = k.findIndex((v) => v != null);
  const dLine = new Array(close.length).fill(null);
  if (start >= 0) {
    sma(k.slice(start).map((v) => v ?? 0), d).forEach((v, i) => { dLine[start + i] = v; });
  }
  return { k, d: dLine };
}
