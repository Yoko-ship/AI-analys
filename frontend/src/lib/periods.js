// The periods the site measures, and the one rule every surface applies to them.
//
// This is the browser's copy of formulas.PERIOD_SPANS / formulas.period_cutoff on
// the server — the definition the board's change columns, the card's «За период»
// block and the absolute returns already share. The chart cut its preset windows
// with its own arithmetic (setUTCMonth, which turns 31.05 less three months into
// 03.03 rather than 28.02), kept the session ON the cutoff inside the window, and
// measured «за период» from the first close INSIDE it — so on a period that began
// on a weekend the chart's 3М started a session after the board's and printed a
// different percent (audit of 12.10.2026: ALSMP 3М 191,57 % against 143,53 %).
//
// The rule, stated once:
//   * a period's CUTOFF is the day it starts after: the same calendar day N months
//     back (clamped to the month's last day), N days back, or 31 December for YTD;
//   * its BASE is the last close at or before the cutoff;
//   * its WINDOW is every session strictly after the cutoff, through the anchor.
//
// The anchor is the market's latest session (the price-history response's
// `as_of`), the day the board's periods end on — not the reader's clock.

const PERIOD_SPANS = {
  "1d": { days: 1 },
  "1w": { days: 7 },
  "1m": { months: 1 },
  "3m": { months: 3 },
  "6m": { months: 6 },
  "1y": { months: 12 },
  "3y": { months: 36 },
  "5y": { months: 60 },
  ytd: { ytd: true },
};

// The codes the metrics endpoint resolves itself (formulas.PERIOD_SPANS).
const SERVER_PERIODS = new Set(["1w", "1m", "3m", "6m", "1y", "3y", "5y", "ytd"]);

const pad = (n) => String(n).padStart(2, "0");

/** «2026-10-12», «20261012», a Date or «2026-10-12T14:00» → «2026-10-12»; else null. */
function isoDay(value) {
  if (value == null || value === "") return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString().slice(0, 10);
  }
  const s = String(value).trim();
  if (/^\d{8}$/.test(s)) return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : null;
}

/** The same calendar day `months` earlier; a day the month lacks becomes its last day. */
function monthsBefore(day, months) {
  const iso = isoDay(day);
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  const total = y * 12 + (m - 1) - months;
  const year = Math.floor(total / 12);
  const month = total - year * 12 + 1;
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${year}-${pad(month)}-${pad(Math.min(d, last))}`;
}

function daysBefore(day, days) {
  const iso = isoDay(day);
  if (!iso) return null;
  const t = new Date(`${iso}T00:00:00Z`);
  t.setUTCDate(t.getUTCDate() - days);
  return t.toISOString().slice(0, 10);
}

/** The day a period starts AFTER (its base is the last close on or before it), or null. */
function periodCutoff(code, anchor) {
  const span = PERIOD_SPANS[code];
  const iso = isoDay(anchor);
  if (!span || !iso) return null;
  if (span.ytd) return `${Number(iso.slice(0, 4)) - 1}-12-31`;
  if (span.months) return monthsBefore(iso, span.months);
  return daysBefore(iso, span.days);
}

/**
 * The metrics query for a period: by NAME where the server knows it, so the server
 * measures it with the board's definition and anchor; a day count only for a span
 * it has no name for («1Д»).
 */
function periodQuery(code, days = null) {
  if (SERVER_PERIODS.has(code)) return `&window=${code}`;
  return days ? `&days=${days}&window=${code}` : "";
}

/** The points of a period: strictly after the cutoff (compared by day), through `asOf`. */
function inPeriod(points, cutoff, asOf = null) {
  const end = isoDay(asOf);
  return (points || []).filter((p) => {
    const day = isoDay(p?.date);
    return day && (!cutoff || day > cutoff) && (!end || day <= end);
  });
}

/**
 * What a span of the chart did: the last close in it against the last close BEFORE
 * it — the same base the board measures a period from. `null` when nothing precedes
 * the span: a series that begins inside a period has not moved over it, it was not
 * there. `fromFirst` is for the one span whose start IS the beginning (the whole
 * history), which is then measured from its first close.
 */
function spanChange(daily, firstDate, lastDate, { fromFirst = false } = {}) {
  const from = isoDay(firstDate);
  const to = isoDay(lastDate);
  if (!from || !to || !Array.isArray(daily) || !daily.length) return null;
  let base = null;
  let last = null;
  let first = null;
  for (const p of daily) {
    const day = isoDay(p?.date);
    const close = Number(p?.close);
    if (!day || !Number.isFinite(close) || close <= 0) continue;
    if (day < from) base = p;
    else if (day <= to) {
      if (!first) first = p;
      last = p;
    }
  }
  if (!base && fromFirst) base = first;
  if (!base || !last || base === last) return null;
  return {
    pct: (Number(last.close) / Number(base.close) - 1) * 100,
    base: Number(base.close),
    baseDate: isoDay(base.date),
    lastDate: isoDay(last.date),
  };
}

export { PERIOD_SPANS, SERVER_PERIODS, inPeriod, isoDay, monthsBefore, periodCutoff, periodQuery, spanChange };
