import { roundedDisplayValue } from "../lib/format.js";
import { formatCompactNumber, formatRatio, safeNumber } from "./format.jsx";
import { marketRowDay, normalizeMarketDay, previousClose, tradeStatsApply } from "../lib/valuation.js";
import { avgSharePrice, avgTradeValue } from "../lib/marketVolume.js";

function profileMarketQuote(ticker, rows, securities) {
  const normalized = String(ticker || "").trim().toUpperCase();
  const row = (rows || []).find((item) => String(item?.ticker || "").trim().toUpperCase() === normalized) || {};
  const security = (securities || {})[normalized] || {};
  const price = safeNumber(row.last_price ?? row.price ?? security.last_price ?? security.price);
  const previous = safeNumber(row.previous_close ?? row.close_price ?? security.previous_close ?? security.close_price);
  const directChange = safeNumber(row.change_pct ?? row.change_percent ?? security.change_pct ?? security.change_percent);
  const change = directChange !== null
    ? directChange
    : price !== null && previous !== null && previous !== 0
      ? ((price - previous) / Math.abs(previous)) * 100
      : null;
  return { row, security, price, change };
}

function formatCompactVolume(value, lang) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  // On MAGNITUDE, with the sign re-attached. Comparing the raw number against
  // the thresholds meant every negative fell through to the plain branch, and a
  // loss printed as «-215 311 494 000» in a column of «376B» — twelve digits
  // wide, breaking the table it sat in. Turnover is never negative, which is
  // why this survived; a loss on the income statement is ordinary.
  const abs = Math.abs(num);
  const sign = num < 0 ? "-" : "";
  if (abs >= 1e9) return sign + formatRatio(abs / 1e9, 1, lang) + "B";
  if (abs >= 1e6) return sign + formatRatio(abs / 1e6, 1, lang) + "M";
  if (abs >= 1e3) return sign + formatRatio(abs / 1e3, 1, lang) + "K";
  return formatRatio(num, 0, lang);
}

function formatMarketTimestamp(value, language) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

// "1 сделок" is what a bare noun gives you in Russian. The board prints the
// trade count under the turnover on every row, so the wrong form is on screen
// seventy times at once. Uzbek takes no plural marker after a numeral, and
// English needs only the two forms.
function tradeCountLabel(n, language) {
  const abs = Math.abs(roundedDisplayValue(Number(n) || 0));
  if (language === "uz") return "savdo";
  if (language === "en") return abs === 1 ? "trade" : "trades";
  const mod10 = abs % 10;
  const mod100 = abs % 100;
  if (mod10 === 1 && mod100 !== 11) return "сделка";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "сделки";
  return "сделок";
}

// Same three Russian forms, for the sessions counted since a story was published.
function sessionCountLabel(n, language) {
  const abs = Math.abs(roundedDisplayValue(Number(n) || 0));
  if (language === "uz") return "sessiya";
  if (language === "en") return abs === 1 ? "session" : "sessions";
  const mod10 = abs % 10;
  const mod100 = abs % 100;
  if (mod10 === 1 && mod100 !== 11) return "сессия";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "сессии";
  return "сессий";
}

// Tooltip behind the "Обновлено" badge: the trading session the numbers belong
// to, and the exchange mirror's own stamp — the two facts the headline number
// deliberately leaves out.
function marketStampTitle(meta, language) {
  const lines = [];
  const session = meta?.trade_date;
  if (session) {
    // `catalog_trade_stats.trade_date` is compacted YYYYMMDD in production
    // (that is the form the day-vs-day comparisons use), while older rows and
    // the listings registry carry ISO. Accept both rather than printing
    // "20260731" at a reader.
    const raw = String(session);
    const iso = /^\d{8}$/.test(raw) ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6)}` : raw;
    const d = new Date(`${iso}T00:00:00`);
    const shown = Number.isNaN(d.getTime())
      ? raw
      : new Intl.DateTimeFormat(language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU",
          { day: "2-digit", month: "short", year: "numeric" }).format(d);
    lines.push(`${language === "en" ? "Trading session" : language === "uz" ? "Savdo sessiyasi" : "Торговая сессия"}: ${shown}`);
  }
  if (meta?.updated_at) {
    lines.push(`${language === "en" ? "Exchange feed" : language === "uz" ? "Birja lentasi" : "Биржевая лента"}: ${formatMarketTimestamp(meta.updated_at, language)}`);
  }
  return lines.join("\n") || undefined;
}







// The newest session any stored day-statistic describes.


// Reconcile ONE enriched board row against the stored per-trade day statistics.
//
// Per-trade stats (UZSE) are the complete, correct daily totals — the plain
// /stocks snapshot can be stale. When present, override turnover/qty/trades with
// them and expose the average trade price. The change stays close-to-close (the
// exchange's official convention — UZSE's daily bulletin computes O'zgarish from
// the closing price, not the day's average; and a backfilled older day's average
// vs the current close would fabricate a bogus "today's move" for an untraded
// security).
//
// Module-level because the market board and the company page's key-stats rail
// must describe the SAME session for the same security. The company header used
// to derive its move as a bare `last_price - close_price`, which is the exact
// two-days-in-one-day defect `previousClose` exists to prevent — so a security
// the board showed flat could lead the company page at +20 %.


// Price to show in the quote column. UZSE sometimes reports last_price=null even
// for a security that traded today (e.g. UZAS: null price but real turnover), and
// Number(null)===0 would render a misleading "0,00". So: use the last trade price
// when present; otherwise, only if the security actually traded, fall back to the
// average trade price (turnover/shares) or the close; else null → em-dash.
function marketDisplayPrice(row) {
  if (row?.last_price != null && Number.isFinite(row.lastPrice)) return row.lastPrice;
  // A security can trade with its data only in the trade-stats feed (avgPrice),
  // while the /stocks feed reports null volume (e.g. MIQE). Treat a real trade
  // average as proof it traded so we show the price instead of an em-dash.
  const traded = row?.stockTradeCount > 0 || row?.stockVolume > 0 || row?.stockQuantity > 0
    || (Number.isFinite(row?.avgPrice) && row.avgPrice > 0);
  if (traded) {
    const avg = Number.isFinite(row?.avgPrice) && row.avgPrice > 0 ? row.avgPrice : avgSharePrice(row);
    if (Number.isFinite(avg) && avg > 0) return avg;
  }
  // Last known price: fall back to the close price (the UI already marks these
  // rows "закр." / "нет сделки") even when the security did not trade today, so
  // illiquid names show a real price instead of an em-dash.
  return Number.isFinite(row?.closePrice) && row.closePrice > 0 ? row.closePrice : null;
}

// Financial indicator cell: compact sums (e.g. "1,2 млрд"), em-dash when absent.
function finValue(v, lang) {
  return Number.isFinite(v) ? formatCompactNumber(v, lang) : "—";
}

// One comparison for one sort key. Returns 0 on a tie so the next key in the
// chain can decide — which is the whole reason multi-key sorting works at all.
function compareSortValues(av, bv, dir) {
  const sign = dir === "asc" ? 1 : -1;
  if (typeof av === "string" || typeof bv === "string") {
    return sign * String(av).localeCompare(String(bv));
  }
  // Empty values (no trade / missing) always sink to the bottom, regardless of direction.
  const aEmpty = av === null || av === undefined || Number.isNaN(av);
  const bEmpty = bv === null || bv === undefined || Number.isNaN(bv);
  if (aEmpty && bEmpty) return 0;
  if (aEmpty) return 1;
  if (bEmpty) return -1;
  return sign * (av - bv);
}

function buildMarketStats(rows, { windowed = false } = {}) {
  // Movers, counters and the day's turnover follow the exchange's daily
  // bulletin: only securities that traded on the LATEST session count.
  // Backfilled last-day stats (an untraded security showing its own last
  // trading day) must not surface as "today's" gainers/losers/volume.
  //
  // Over a WINDOW there is no such session to filter to, and filtering to one
  // would be the bug: a security that has not traded this morning still moved
  // over the month, and ranking the month by who happened to trade today is
  // the answer to a different question. The rows arrive already restated for
  // the period (MarketView's `asPeriod`), so every sum below is the period's.
  const boardDay = windowed
    ? null
    : rows.reduce((m, r) => { const d = marketRowDay(r); return d && (!m || d > m) ? d : m; }, null);
  const todays = boardDay ? rows.filter((r) => marketRowDay(r) === boardDay) : rows;
  // Everything on the latest session's date traded (the feed's null-price
  // quirk must not undercount securities whose executions we hold).
  const traded = todays.length;
  const advancers = todays.filter((row) => row.changePercent !== null && row.changePercent > 0.05).length;
  const decliners = todays.filter((row) => row.changePercent !== null && row.changePercent < -0.05).length;
  const unchanged = todays.filter((row) => Number.isFinite(row.changePercent) && row.changePercent >= -0.05 && row.changePercent <= 0.05).length;
  const withChange = todays.filter((row) => Number.isFinite(row.changePercent));
  const topGrowth = withChange.reduce((best, row) => (!best || row.changePercent > best.changePercent ? row : best), null);
  const topDrop = withChange.reduce((worst, row) => (!worst || row.changePercent < worst.changePercent ? row : worst), null);
  const topGainers = withChange.filter((r) => r.changePercent > 0).sort((a, b) => b.changePercent - a.changePercent).slice(0, 5);
  const topLosers = withChange.filter((r) => r.changePercent < 0).sort((a, b) => a.changePercent - b.changePercent).slice(0, 5);
  // Ликвидность = the session's turnover in MONEY. `stockVolume` is the day
  // statistics' `total_value` — the sum the security changed hands FOR, which
  // is what «Объём» means in the column, in the turnover card and on the charts.
  // Positive and finite only: a row whose stored day did not match its own
  // session keeps no turnover at all (applyTradeStats refuses to paste another
  // week's figure onto it), and that absence must not sort as a zero that
  // claims the security traded for nothing.
  const topVolume = todays.filter((r) => Number.isFinite(r.stockVolume) && r.stockVolume > 0)
    .sort((a, b) => b.stockVolume - a.stockVolume).slice(0, 5);
  const totalVolume = todays.reduce((s, r) => s + (Number.isFinite(r.stockVolume) ? r.stockVolume : 0), 0);
  const totalTrades = todays.reduce((s, r) => s + (Number.isFinite(r.stockTradeCount) ? r.stockTradeCount : 0), 0);
  const totalMarketCap = rows.reduce((s, r) => s + (Number.isFinite(r.marketCap) && r.marketCap > 0 ? r.marketCap : 0), 0);
  return { boardDay, traded, advancers, decliners, unchanged, topGrowth, topDrop, topGainers, topLosers, topVolume, totalVolume, totalTrades, totalMarketCap };
}

export { avgSharePrice, avgTradeValue, buildMarketStats, compareSortValues, finValue, formatCompactVolume, formatMarketTimestamp, marketDisplayPrice, marketStampTitle, profileMarketQuote, sessionCountLabel, tradeCountLabel };
