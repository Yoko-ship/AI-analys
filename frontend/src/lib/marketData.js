// Market rows have one preparation path, shared by every screen.
// Callers supply quote rows and the stored trade-statistics map; session
// alignment, negotiated deals, and close-to-close changes stay inside here.
import { normalizeMarketDay, previousClose, tradeStatsApply } from "./valuation.js";

function safeNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function marketChange(stock) {
  // last_price is null when no trade happened today; Number(null)=0 so we
  // must guard on the raw value, not the coerced number.
  if (stock?.last_price == null) return { value: null, percent: null };
  const last = safeNumber(stock.last_price);
  const close = safeNumber(stock.close_price);
  if (last === null || close === null || close === 0) {
    return { value: null, percent: null };
  }
  const value = last - close;
  return {
    value,
    percent: (value / Math.abs(close)) * 100,
  };
}

export function marketTone(percent) {
  if (percent === null || percent === undefined || !Number.isFinite(Number(percent))) return "neutral";
  if (Number(percent) > 0.05) return "good";
  if (Number(percent) < -0.05) return "danger";
  return "neutral";
}

function enrichMarketStock(stock) {
  const change = marketChange(stock);
  return {
    ...stock,
    lastPrice: safeNumber(stock?.last_price),
    closePrice: safeNumber(stock?.close_price),
    openPrice: safeNumber(stock?.open) || null,
    highPrice: safeNumber(stock?.high) || null,
    lowPrice: safeNumber(stock?.low) || null,
    stockVolume: safeNumber(stock?.volume),
    stockQuantity: safeNumber(stock?.quantity),
    stockTradeCount: safeNumber(stock?.trade_count),
    marketCap: safeNumber(stock?.market_cap) || null,
    nominal: safeNumber(stock?.nominal) || null,
    sharesOutstanding: safeNumber(stock?.shares_outstanding) || null,
    changeValue: change.value,
    changePercent: change.percent,
    // Did this security trade in the session the board is showing? The
    // exchange carries a close forward through sessions with no executions, so
    // last == prev proves nothing on its own — a security CAN trade and close
    // exactly flat, and that is a real 0 %. Only activity separates the two.
    tradedToday: (safeNumber(stock?.trade_count) || 0) > 0
      || (safeNumber(stock?.volume) || 0) > 0
      || (safeNumber(stock?.quantity) || 0) > 0,
    tone: marketTone(change.percent),
  };
}

// The newest session any stored day-statistic describes.
function latestTradeStatsDay(tmap) {
  return Object.values(tmap || {}).reduce((m, t) => {
    const d = String(t?.trade_date || "");
    return /^\d{8}$/.test(d) && (!m || d > m) ? d : m;
  }, null);
}

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
function applyTradeStats(r, tmap, latestTsDay) {
  const t = (tmap || {})[r.isin] || (tmap || {})[(r.isin || "").toUpperCase()];
  if (!t) return r;
  const rowDay = normalizeMarketDay(r.last_trade_date);
  const tsDay = normalizeMarketDay(t.trade_date);
  // A NEGOTIATED deal is dated, not current, and it belongs to the row whatever
  // the session guard below decides: the deals on this market in August 2026 were
  // struck on 02.07, 10.07, 07.08 and 13.08, all older than their securities' last
  // auction session, so the guard would have hidden every one of them from the
  // NEGO board. Carried on its own key so it can never be mistaken for session
  // turnover — which is the whole point of keeping the two boards apart.
  if (Number.isFinite(t.block_value) && t.block_value > 0) {
    r = {
      ...r,
      nego: {
        value: t.block_value,
        qty: Number.isFinite(t.block_qty) ? t.block_qty : null,
        count: Number.isFinite(t.block_count) ? t.block_count : null,
        date: tsDay || null,
      },
    };
  }
  // The day stats and the feed row must describe the SAME session — a stored
  // day older than the row's own last trade is a snapshot the nightly push
  // never refreshed, and its turnover belongs to no quote on the page. Fall
  // back to the feed's own figures for the row's day; an em-dash where the
  // feed has none is honest, a number from another week is not.
  if (!tradeStatsApply(r.last_trade_date, t.trade_date)) return r;
  const out = { ...r, ts: t };
  // A day whose only executions were negotiated deals is NOT a session: the
  // bulletin says nothing traded, so its zeros must not replace the row's own
  // last real session, and its price must not become the row's close. The
  // deal stays reachable through `ts.block_value` for its own line on the card.
  if (!(t.trade_count > 0) && !(t.total_qty > 0)) return out;
  if (Number.isFinite(t.total_value)) out.stockVolume = t.total_value;
  if (Number.isFinite(t.total_qty)) out.stockQuantity = t.total_qty;
  if (Number.isFinite(t.trade_count)) out.stockTradeCount = t.trade_count;
  if (Number.isFinite(t.avg_price)) out.avgPrice = t.avg_price;
  if (Number.isFinite(t.vwap)) out.vwap = t.vwap;
  // The feed lags for thin names — SANE still carried its 13.07 trade
  // while today's executions existed (and sometimes last_price is null
  // outright) — so the official move vanished from the board. When the
  // day stats are the latest session AND newer than the feed row, the
  // session's own OHLC is authoritative: price/date/OHLC come from it and
  // the change is close-to-close (session close vs the feed's stale
  // close, which IS the previous close — matching the daily bulletin).
  const tsIsNewer = tsDay && tsDay === latestTsDay &&
    (r.lastPrice === null || !rowDay || rowDay < tsDay);
  if (tsIsNewer) {
    const px = Number.isFinite(t.close_price) ? t.close_price
      : Number.isFinite(t.vwap) ? t.vwap : t.avg_price;
    if (Number.isFinite(px)) {
      out.lastPrice = px;
      if (Number.isFinite(t.open_price)) out.openPrice = t.open_price;
      if (Number.isFinite(t.high_price)) out.highPrice = t.high_price;
      if (Number.isFinite(t.low_price)) out.lowPrice = t.low_price;
      if (/^\d{8}$/.test(String(t.trade_date))) {
        const d = String(t.trade_date);
        out.last_trade_date = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}`;
      }
      // Against the newest close the exchange published BEFORE this session —
      // not against whatever `close_price` the row is carrying. Once the quote
      // pass falls two sessions behind, that field is the PREVIOUS session's
      // previous close, and the difference is two days' move wearing one day's
      // date: UQEQ's single unchanged 37 200 trade led the top-gainers panel at
      // +20 % because it was struck against 05.08's 31 000. See previousClose.
      const prev = previousClose({
        lastPrice: r.lastPrice, lastTradeDate: r.last_trade_date,
        closePrice: r.closePrice, closeDate: r.close_date,
      }, t.trade_date);
      if (prev) {
        // The row now states this session, so it must state this session's
        // previous close too — the "закр." line under the trade date reads it.
        out.closePrice = prev.price;
        out.close_price = prev.price;
        out.close_date = prev.date ?? null;
        out.changeValue = px - prev.price;
        out.changePercent = ((px - prev.price) / Math.abs(prev.price)) * 100;
      } else {
        // Nothing datable to measure from. An em-dash is the honest cell.
        out.changeValue = null;
        out.changePercent = null;
      }
      out.tone = marketTone(out.changePercent);
    } else if (rowDay && rowDay < tsDay) {
      // The stats put this row in a session the quote layer has not reached,
      // and carry no price to restate it with. Whatever change the quote holds
      // belongs to the older session — leaving it in place is how a stale move
      // gets published under today's date, which is the whole defect above.
      out.changeValue = null;
      out.changePercent = null;
      out.tone = marketTone(null);
    }
  }
  return out;
}

/** Prepare independent display rows without changing the source snapshots. */
export function prepareMarketRows(rows, tradeStats = {}) {
  const stats = tradeStats || {};
  const latestDay = latestTradeStatsDay(stats);
  return (Array.isArray(rows) ? rows : [])
    .map(enrichMarketStock)
    .map((row) => applyTradeStats(row, stats, latestDay));
}
