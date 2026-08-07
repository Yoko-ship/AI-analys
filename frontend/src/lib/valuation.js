// Valuation multiples and reporting-period labels — ONE definition, used by
// every view that shows them.
//
// These lived twice in App.jsx and had drifted:
//   market table:  P/E = market cap / net income   P/B = market cap / equity
//   company page:  P/E = market cap / net income   P/B = P/E x ROE
// The P/B identity (ROE = net income / equity) is algebraically the same thing,
// but it is only defined when P/E and ROE are both positive — so every loss-maker
// showed a P/B on the market board and a blank on its own page. Same inputs, two
// answers, is the bug. Extracted here so there is one implementation and one test
// suite, and so neither copy can drift again.
//
// Units are the API's responsibility: it scales NSBU sums (stored in thousands of
// UZS) to full UZS at the response boundary, so every division below is
// like-for-like. Dividing a full-UZS market cap by thousands-UZS earnings is what
// understated P/E and P/B ~1000x once already.

/**
 * Book equity to divide a market cap by, or null when none is trustworthy.
 *
 * Prefers the published figure. Falls back to the source's own ROE identity
 * (equity = net income / ROE x 100) for the many issuers that publish ROE but no
 * equity line — guarded so it is only used where it is actually defined.
 */
export function valuationEquity({ equity, netIncome, roePercent }) {
  if (Number.isFinite(equity) && equity > 0) return equity;
  // Same sign required (a negative-equity issuer is not representable here), and
  // |ROE| >= 0.1% because below that the published 2-decimal rounding dominates
  // the estimate entirely.
  if (Number.isFinite(netIncome) && Number.isFinite(roePercent)
      && Math.abs(roePercent) >= 0.1 && netIncome / roePercent > 0) {
    const derived = (netIncome / roePercent) * 100;
    return derived > 0 ? derived : null;
  }
  return null;
}

/**
 * The earnings a multiple should divide by, and the period they cover.
 *
 * NSBU quarterly forms are cumulative from 1 January, so an issuer's latest
 * filing is three, six or nine months of profit depending only on when in the
 * year it filed — and issuers file on different calendars. Dividing a market cap
 * by that produces a P/E column where one row means "price per year of earnings"
 * and the next means "price per quarter", four times larger for no reason the
 * reader can see. The backend therefore carries the last complete fiscal year
 * alongside the latest period; prefer it, and fall back to the row's own figure
 * (already 12 months when the row IS an annual).
 *
 * Returns { netIncome, period, months } — `period` labels what was used so the
 * cell can say so, rather than leaving the reader to assume "latest".
 */
export function finEarnings(f) {
  const annual = f?.annual;
  if (annual && Number.isFinite(annual.net_income)) {
    return { netIncome: annual.net_income, period: finRowPeriod(annual), months: 12 };
  }
  return {
    netIncome: Number.isFinite(f?.net_income) ? f.net_income : null,
    period: finRowPeriod(f),
    months: finPeriodMonths(f),
  };
}

/**
 * { pe, pb } for one issuer. Either may be null, meaning "not computable from
 * published data" — never 0 and never NaN.
 *
 * P/E is returned NEGATIVE for a loss-maker: that is the screener convention, and
 * a blank would read as "not published" when both figures are in fact published.
 * P/B requires positive equity — with negative book value the ratio is
 * meaningless rather than negative.
 */
export function valuationRatios({ marketCap, netIncome, equity, roePercent }) {
  const mc = Number.isFinite(marketCap) && marketCap > 0 ? marketCap : null;
  if (mc === null) return { pe: null, pb: null };
  const pe = Number.isFinite(netIncome) && netIncome !== 0 ? mc / netIncome : null;
  const eq = valuationEquity({ equity, netIncome, roePercent });
  const pb = eq !== null ? mc / eq : null;
  return { pe, pb };
}

/** The reporting period a financials ROW is labelled with: "2024" or "2025 Q1". */
export function finRowPeriod(f) {
  if (!f || !f.year) return null;
  return f.quarter > 0 ? `${f.year} Q${f.quarter}` : String(f.year);
}

/**
 * The period a SINGLE field describes.
 *
 * Usually the row's own, but a few figures can only be sourced from a different
 * filing (a bank's revenue exists as an annual indicator and nowhere in the
 * quarterly NSBU form), and the backend records those in `field_periods`. Showing
 * them under the row's label is how a full-year revenue came to be presented as a
 * 3-month figure.
 */
export function finFieldPeriod(f, field) {
  const own = (f?.field_periods || {})[field];
  if (!own) return finRowPeriod(f);
  const m = String(own).match(/^(\d{4})Q([1-4])$/);
  return m ? `${m[1]} Q${m[2]}` : String(own);
}

/** Months of activity a financials ROW's P&L figures cover (12 for an annual). */
export function finPeriodMonths(f) {
  if (!f || !f.year) return null;
  if (Number.isFinite(f.period_months)) return f.period_months;
  return f.quarter > 0 ? f.quarter * 3 : 12;
}

/** Human coverage of a period, so a cumulative quarter is never read as a year. */
export function finPeriodCoverage(period, lang) {
  const m = String(period || "").match(/Q([1-4])$/);
  if (!m) return lang === "ru" ? "12 мес." : lang === "uz" ? "12 oy" : "12 months";
  const months = Number(m[1]) * 3;
  return lang === "ru" ? `${months} мес., с начала года`
    : lang === "uz" ? `${months} oy, yil boshidan`
    : `${months} months, year to date`;
}

/**
 * The short suffix printed next to the period under a figure.
 *
 * Only flow (P&L) figures get one: a cumulative Q2 revenue is six months of
 * trading and has to say so, or the column silently compares half a year against
 * a peer's full one. Balance-sheet lines are a position on the closing date —
 * there is no length to state, and adding one would imply an accumulation that
 * does not exist.
 */
const FIN_BALANCE_FIELDS = new Set(["cash", "total_liabilities"]);

export function finFieldCoverage(period, field, lang) {
  if (FIN_BALANCE_FIELDS.has(field)) return null;
  const m = String(period || "").match(/Q([1-4])$/);
  if (!m) return null;                       // an annual is the unit; no suffix needed
  const months = Number(m[1]) * 3;
  return lang === "ru" ? `${months} мес.` : lang === "uz" ? `${months} oy` : `${months}m`;
}

/**
 * Normalize a trade day to YYYYMMDD, or null.
 *
 * The live feed writes DD.MM.YYYY, the listings registry YYYY-MM-DD, the day
 * stats YYYYMMDD. Comparing those raw strings ordered by their leading digits, so
 * "31.01.2026" sorted above "05.02.2026" and every "latest first" ordering broke
 * at month boundaries.
 */
export function normalizeMarketDay(s) {
  const str = String(s || "");
  const m = str.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  if (m) return `${m[3]}${m[2]}${m[1]}`;
  const d = str.replace(/-/g, "");
  return /^\d{8}$/.test(d) ? d : null;
}

/** The day a market row's statistics describe, from whichever field carries it. */
export function marketRowDay(r) {
  return normalizeMarketDay(r?.ts?.trade_date) || normalizeMarketDay(r?.last_trade_date);
}

/**
 * Do the stored day statistics describe the same session as the market row?
 *
 * The stats are a nightly snapshot; a push that never lands leaves a security on
 * an older session while the live feed has already moved on. Pasting that older
 * day's turnover next to the newer quote produces a volume that belongs to no
 * session at all — NGQS showed 16.07's 251 246 UZS / 6 trades beside its 24.07
 * price of 23 900 (that session was 287 900 / 4). Stats for the row's own day
 * apply; newer ones apply too (the feed lags for thin names); older ones do not.
 *
 * An unknown day on either side keeps the stats: the feed reports
 * last_trade_date=null for securities that did trade, and dropping their
 * turnover would trade a wrong number for a missing one.
 */
export function tradeStatsApply(lastTradeDate, statsTradeDate) {
  const rowDay = normalizeMarketDay(lastTradeDate);
  const tsDay = normalizeMarketDay(statsTradeDate);
  if (!rowDay || !tsDay) return true;
  return tsDay >= rowDay;
}

/**
 * The close that `sessionDay`'s move is measured against.
 *
 * A row carries TWO dated closes: the close of the last session it traded in
 * (`lastPrice` @ `lastTradeDate`) and that session's own previous close
 * (`closePrice` @ `closeDate`). While both describe the same session as the day
 * stats, `closePrice` is the previous close and there is nothing to decide. It
 * is when the quote layer falls behind the execution feed that the two split —
 * and then reaching for `closePrice` reaches one session too far back.
 *
 * UQEQ found this. It traded a single share at 37 200 on 07.08, unchanged from
 * its 06.08 close of 37 200 — a flat 0 %, which is what the exchange published.
 * The board led its top-gainers panel with **+20 %**, because the quote pass had
 * last run before 06.08's trade and the row still paired 06.08's close with
 * 05.08's 31 000. Struck against that, one day's move became two.
 *
 * So: the newest close dated strictly BEFORE the session. The exchange carries a
 * close forward through sessions with no trades, so the last session a security
 * traded in is the one the exchange itself measures from, whatever sat between.
 *
 * Returns `{ price, date }` — the date comes back because a row that restates
 * its previous close must restate the day that close belongs to; the "закр."
 * line under the trade date prints it, and a price from one session over
 * another session's date is the same class of error this function exists to fix.
 *
 * Returns null when every close it can date falls on or after the session — a
 * close from the session itself is not a previous close, and a move invented
 * from one is worse than the em-dash the caller renders instead. An UNDATED
 * close is the last resort rather than a refusal: the feed leaves the field
 * empty for securities that did trade, and those rows were readable before.
 */
export function previousClose({ lastPrice, lastTradeDate, closePrice, closeDate } = {}, sessionDay) {
  const session = normalizeMarketDay(sessionDay);
  const priced = (px) => Number.isFinite(px) && px > 0;
  const dated = [{ date: lastTradeDate, price: lastPrice },
                 { date: closeDate, price: closePrice }]
    .map((c) => ({ ...c, day: normalizeMarketDay(c.date) }))
    .filter((c) => c.day && priced(c.price) && (!session || c.day < session))
    .sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : 0));
  if (dated.length) return { price: dated[0].price, date: dated[0].date };
  if (!normalizeMarketDay(closeDate) && priced(closePrice)) return { price: closePrice, date: null };
  return null;
}
