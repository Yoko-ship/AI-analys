import { sectorOf } from "../lib/sectors.js";

// ---------------------------------------------------------------------------
// The auditor's own screen used to live here as AuditAdminPage, authenticated by
// typing the machine X-Admin-Secret into a field. It is superseded by the admin
// panel (admin/AdminPanel.jsx, section «Аудит»), which authenticates as the
// signed-in administrator instead, so the shared secret no longer reaches the
// browser at all. /admin/audit still resolves; it now opens that section.
// ---------------------------------------------------------------------------



// The spans the chart offers.
//
// `months` is what /api/price-history is ASKED for — its smallest unit is a
// month — and `days`/`ytd` then narrow the loaded series on the client. Keeping
// both in one table is what stops the buttons and the fetch drifting apart.
//
// `hourly` marks the ranges the company chart draws from the exchange's own
// trade feed rolled up to hourly bars (/api/intraday). 1Д exists BECAUSE of
// that feed — every execution carries its moment, the collector banks them
// hourly (negotiated T1 deals excluded), and a day is ~7 bars, not the single
// candle it used to be. 1Н still mixes in daily closes for any day the bank
// does not cover — a security can sit out any number of sessions.
const CHART_RANGES = [
  { key: "1d", months: 1, days: 1, span: 0.05, hourly: true, label: ["1Д", "1K", "1D"] },
  { key: "1w", months: 1, days: 7, span: 0.25, hourly: true, label: ["1Н", "1H", "1W"] },
  { key: "1m", months: 1, span: 1, label: ["1М", "1O", "1M"] },
  { key: "3m", months: 3, span: 3, label: ["3М", "3O", "3M"] },
  { key: "6m", months: 6, span: 6, label: ["6М", "6O", "6M"] },
  { key: "ytd", ytd: true, label: ["YTD", "YTD", "YTD"] },
  { key: "1y", months: 12, span: 12, label: ["1Г", "1Y", "1Y"] },
  { key: "3y", months: 36, span: 36, label: ["3Г", "3Y", "3Y"] },
  { key: "5y", months: 60, span: 60, label: ["5Л", "5Y", "5Y"] },
  { key: "max", months: 240, span: 240, label: ["Макс", "Maks", "Max"] },
];

function chartRange(key) {
  return CHART_RANGES.find((r) => r.key === key) || CHART_RANGES.find((r) => r.key === "1y");
}

/** Months to ask the API for. YTD is a moving target — in January it is weeks. */
function chartRangeMonths(key) {
  const r = chartRange(key);
  if (r.ytd) return Math.min(60, new Date().getMonth() + 2);
  return r.months;
}

/** How much calendar the view actually shows, in months — drives bucket width. */
function chartRangeSpan(key) {
  const r = chartRange(key);
  return r.ytd ? new Date().getMonth() + 1 : r.span;
}

/**
 * The window the METRICS call should measure, as the endpoint understands it.
 *
 * The fetch is in months because that is openinfo's smallest unit, but two
 * buttons are not a whole number of months: «1Н» is seven days and YTD runs
 * from 1 January. Asking for months on those gave the rail a month's figures
 * under a week's label — twenty-one sessions and a range four times too wide.
 * The server takes `days` + a window name for exactly that reason.
 */
function chartRangeWindowQuery(key) {
  const r = chartRange(key);
  if (r.ytd) {
    const now = new Date();
    const jan1 = new Date(now.getFullYear(), 0, 1);
    return `&days=${Math.max(1, Math.round((now - jan1) / 86400000))}&window=ytd`;
  }
  return r.days ? `&days=${r.days}&window=${r.key}` : "";
}

/** The first date the view keeps, or null when the whole fetch is shown. */
function chartRangeCutoff(key, anchorValue = null) {
  const r = chartRange(key);
  const anchor = anchorValue ? new Date(anchorValue) : new Date();
  if (Number.isNaN(anchor.getTime())) return null;
  if (r.ytd) return `${anchor.getUTCFullYear()}-01-01`;
  if (r.days) {
    const d = new Date(anchor);
    d.setUTCDate(d.getUTCDate() - r.days);
    return d.toISOString().slice(0, 10);
  }
  return null;
}

/* ── Быстрое сравнение ──────────────────────────────────────────────────────
 * Peer lines on the price chart, as on the reference quote page: a strip of
 * cards under the chart, and one click puts that security's line beside this
 * one's.
 *
 * The lines are drawn as PERCENT from a shared start, never in сумы. On this
 * market KSCM closes near 111 000 and UZTL near 12 000 — a shared price axis
 * would flatten one of them onto the frame and compare nothing. Percent is also
 * what «сравнить» means here: which of the two moved more.
 */
// How many peers can be on the chart at once — a palette limit, not a data one.
// The request carries any number of tickers and the store answers for all of
// them; what runs out is COLOUR. The chart already spends green and red on this
// security's own direction, amber on MA20 and violet on MA50, so a peer colour
// has to be told apart from four things before it is told apart from the other
// peers. Five hues survive that on both themes; a sixth would either repeat a
// hue or sit next to one, and two lines the reader cannot separate are worse
// than one line they cannot add.
// Gold, not #facc15: the brighter yellow reads on the dark theme and nearly
// vanishes on the light one, and a line only one of two readers can follow is
// not a fifth colour.
const QC_COLORS = ["#f472b6", "#22d3ee", "#3b82f6", "#94a3b8", "#eab308"];

const QC_MAX = QC_COLORS.length;

// Which securities the strip offers. Pure and module-level for the same reason
// watchRailLists is: the page fetches a stored series for exactly these
// tickers, and computing the list twice would let the fetch ask for one set
// while the strip drew another.
function quickComparePeers({ ticker, rows, securitiesMap, limit = 8 }) {
  const up = String(ticker || "").toUpperCase();
  const priced = (Array.isArray(rows) ? rows : []).filter(
    (r) => Number.isFinite(r.lastPrice) && r.lastPrice > 0
      && String(r.ticker || "").toUpperCase() !== up,
  );
  const byCap = (a, b) => (b.marketCap || 0) - (a.marketCap || 0);
  // The issuer's OTHER class first. It is the one comparison whose two lines
  // are supposed to agree, so the days they part are worth seeing.
  const sibling = up.endsWith("P") ? up.slice(0, -1) : `${up}P`;
  // sectorOf answers "other" for a ticker the catalog does not classify — a
  // bucket, not a sector. Offering its members as peers would put a fund next
  // to a cement plant and call them comparable; the market's largest names are
  // the honest fallback, because they are the ones a reader already knows.
  const mine = sectorOf(up, securitiesMap, null);
  const sameSector = (!mine || mine === "other") ? [] : priced
    .filter((r) => sectorOf(r.ticker, securitiesMap, null) === mine).sort(byCap);
  const ordered = [
    ...priced.filter((r) => String(r.ticker || "").toUpperCase() === sibling),
    ...sameSector,
    ...[...priced].sort(byCap),
  ];
  const out = [];
  for (const row of ordered) {
    const tk = String(row.ticker || "").toUpperCase();
    if (out.some((x) => String(x.ticker || "").toUpperCase() === tk)) continue;
    out.push(row);
    if (out.length >= limit) break;
  }
  return out;
}

// YYYYMMDD (the stored quote history) → YYYY-MM-DD (the price-history feed).
// ONE rule, here, because a series half in each form orders by its leading
// digits and draws a scrambled line — the same trap store_quote_history guards
// on the way in.
function compareIsoDay(v) {
  const s = String(v || "").trim();
  return /^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : s;
}

/**
 * Put the base window and its comparison series on ONE percent scale.
 *
 * The rule that matters: every line is rebased at the SAME session, and that
 * session is the first one all of them have. Rebasing each series at its own
 * first point would draw a peer at 0 % on a day the base already stood at
 * +40 %, and the two curves would be answering different questions.
 *
 * The stored quote history begins in Aug 2025, so on «3 года» or «Макс» the
 * shared start is later than the window — the chart says so underneath rather
 * than quietly showing less than the range button promises.
 *
 * Returns null when there is nothing to compare; `dropped` carries the peers
 * with no stored session inside the window, which is a fact about the security
 * and has to be stated, not swallowed.
 */
function buildCompareSeries(windowed, compare) {
  const wanted = Array.isArray(compare) ? compare : [];
  if (!windowed.length || !wanted.length) return null;
  const from = String(windowed[0].date);
  const prepared = [];
  const dropped = [];
  for (const c of wanted) {
    const norm = (Array.isArray(c.points) ? c.points : [])
      .map((p) => (Array.isArray(p)
        ? [compareIsoDay(p[0]), Number(p[1]), Number(p[2]) || 0]
        : [compareIsoDay(p.date || p.trade_date), Number(p.close ?? p.close_price),
           Number(p.value ?? p.turnover ?? 0) || 0]))
      .filter(([d, v]) => d && Number.isFinite(v) && v > 0)
      .sort((a, b) => a[0].localeCompare(b[0]));
    // The volume history keeps its FULL depth, not the drawn window's: a
    // «к среднему» read near the window's left edge averages the sessions
    // BEFORE the window, exactly as the base security's does.
    const volHist = norm.map(([d, , tv]) => ({ date: d, turnover: tv }));
    const pts = norm.filter(([d]) => d >= from);
    if (pts.length < 2) dropped.push(c);
    else prepared.push({ ...c, pts, volHist });
  }
  if (!prepared.length) return { points: windowed, series: [], dropped, start: null };

  const start = prepared.reduce((m, c) => (c.pts[0][0] > m ? c.pts[0][0] : m), from);
  const points = windowed.filter((p) => String(p.date) >= start);
  // A shared span of one session is not a comparison. Say the peers could not
  // be drawn rather than trim the base chart to a dot.
  if (points.length < 2) {
    return { points: windowed, series: [], dropped: [...dropped, ...prepared], start: null };
  }
  const base0 = points[0].close;
  const basePct = points.map((p) => (p.close / base0 - 1) * 100);

  const series = [];
  for (const c of prepared) {
    // Carried forward, not interpolated: two securities here do not trade on
    // the same days, and a peer's price on a session it sat out is the last one
    // it printed — which is what the exchange itself carries forward.
    let j = 0;
    let last = null;
    const closes = points.map((p) => {
      const d = String(p.date);
      while (j < c.pts.length && c.pts[j][0] <= d) { last = c.pts[j][1]; j += 1; }
      return last;
    });
    const first = closes[0];
    if (!Number.isFinite(first) || first <= 0) { dropped.push(c); continue; }
    series.push({ ...c, closes, pct: closes.map((v) => (v == null ? null : (v / first - 1) * 100)) });
  }
  return { points, basePct, base0, series, dropped, start: start > from ? start : null };
}

/**
 * Peers on one percent scale with the security, over the WHOLE series the
 * chart holds (so dragging back through history keeps the peers on screen).
 *
 * Every line is rebased at the SAME session — the first one inside the range
 * window that all of them have — exactly as buildCompareSeries does for the
 * window alone. Peer closes are carried forward, not interpolated: a price on a
 * session a security sat out is the last one it printed, which is what the
 * exchange itself carries.
 */
function buildCompareAligned(source, compare, windowStart) {
  const wanted = Array.isArray(compare) ? compare : [];
  if (!source.length || !wanted.length) return null;
  const from = String(windowStart || source[0].date);
  const prepared = [];
  const dropped = [];
  for (const c of wanted) {
    const norm = (Array.isArray(c.points) ? c.points : [])
      .map((p) => (Array.isArray(p)
        ? [compareIsoDay(p[0]), Number(p[1]), Number(p[2]) || 0]
        : [compareIsoDay(p.date || p.trade_date), Number(p.close ?? p.close_price),
           Number(p.value ?? p.turnover ?? 0) || 0]))
      .filter(([d, v]) => d && Number.isFinite(v) && v > 0)
      .sort((a, b) => a[0].localeCompare(b[0]));
    const volHist = norm.map(([d, , tv]) => ({ date: d, turnover: tv }));
    if (norm.filter(([d]) => d >= from).length < 2) dropped.push(c);
    else prepared.push({ ...c, pts: norm, volHist });
  }
  if (!prepared.length) return { series: [], dropped, start: null, baseIdx: -1 };
  const start = prepared.reduce((m, c) => {
    const first = c.pts.find(([d]) => d >= from)?.[0] || from;
    return first > m ? first : m;
  }, from);
  const baseIdx = source.findIndex((p) => String(p.date).slice(0, 10) >= start);
  if (baseIdx < 0 || source.length - baseIdx < 2) {
    return { series: [], dropped: [...dropped, ...prepared], start: null, baseIdx: -1 };
  }
  const base0 = source[baseIdx].close;
  const basePct = source.map((p) => (p.close / base0 - 1) * 100);
  const series = [];
  for (const c of prepared) {
    let j = 0;
    let last = null;
    const closes = source.map((p) => {
      const d = String(p.date).slice(0, 10);
      while (j < c.pts.length && c.pts[j][0] <= d) { last = c.pts[j][1]; j += 1; }
      return last;
    });
    const first = closes[baseIdx];
    if (!Number.isFinite(first) || first <= 0) { dropped.push(c); continue; }
    series.push({ ...c, closes, pct: closes.map((v) => (v == null ? null : (v / first - 1) * 100)) });
  }
  return { basePct, base0, series, dropped, start: start > from ? start : null, baseIdx };
}

export { CHART_RANGES, QC_COLORS, QC_MAX, buildCompareAligned, chartRange, chartRangeCutoff, chartRangeMonths, chartRangeSpan, chartRangeWindowQuery, quickComparePeers };
