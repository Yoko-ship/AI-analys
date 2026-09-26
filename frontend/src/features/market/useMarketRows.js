import React from "react";
import { marketDisplayPrice } from "../../shared/marketModel.jsx";
import { prepareMarketRows } from "../../lib/marketData.js";
import { orderSectors, sectorOf } from "../../lib/sectors.js";
export function useMarketRows({
  changes,
  securitiesMap,
  companies,
  suppliedFinancials,
  financials,
  onDemandFinancials,
  tradeStats,
  rows,
  segment,
  changePeriod,
  type,
  instruments,
  inactiveOnly,
  query,
  lang,
  marketSector,
  ratios,
  multiples,
  multiplesStatus
}) {
  const changeOver = (ticker, code) => {
    if (code === "1d") return null;
    const hit = (changes[String(ticker || "").toUpperCase()] || {})[code];
    return hit && Number.isFinite(hit.pct) ? hit : null;
  };
  const turnoverOver = (ticker, code) => {
    if (code === "1d") return null;
    const hit = ((changes[String(ticker || "").toUpperCase()] || {}).turnover || {})[code];
    return hit && Number.isFinite(hit.value) ? hit : null;
  };
  const statsOver = (ticker, code) => {
    if (code === "1d") return null;
    const hit = ((changes[String(ticker || "").toUpperCase()] || {}).stats || {})[code];
    return hit || null;
  };
  const parOf = row => {
    const par = Number(row?.nominal);
    return Number.isFinite(par) && par > 0 ? par : null;
  };
  const priceToPar = row => {
    const par = parOf(row);
    const price = marketDisplayPrice(row);
    return par && Number.isFinite(price) && price > 0 ? price / par : null;
  };
  const smap = securitiesMap || {};
  const companyMap = React.useMemo(() => {
    const by = {};
    (companies || []).forEach(c => {
      if (c?.ticker) by[c.ticker] = c;
    });
    return by;
  }, [companies]);
  const fmap = suppliedFinancials ? financials : onDemandFinancials;
  const finOf = ticker => {
    const t = String(ticker || "").toUpperCase();
    return fmap[t] || fmap[t.endsWith("P") ? t.slice(0, -1) : `${t}P`] || null;
  };
  const tmap = tradeStats || {};
  const preparedEnriched = prepareMarketRows(rows, tradeStats);
  const negotiated = r => Number.isFinite(r?.nego?.value) && r.nego.value > 0;
  const asNegotiated = r => ({
    ...r,
    stockVolume: r.nego.value,
    stockQuantity: r.nego.qty,
    stockTradeCount: r.nego.count,
    // Cleared so «Ср. цена акции» derives from the NEGOTIATED turnover and
    // quantity (avgSharePrice) instead of serving the auction's VWAP under a
    // negotiated row. Same for the session VWAP column.
    avgPrice: undefined,
    vwap: null,
    // The date column must name the day the DEAL was struck. A negotiated deal is
    // not a session and is routinely weeks old — the ones on this market in
    // August 2026 were dated 02.07, 10.07, 07.08 and 13.08 — so showing the
    // auction's last-trade date beside a negotiated turnover would date the deal
    // to a session it had nothing to do with.
    last_trade_date: r.nego.date || r.last_trade_date
  });
  const negotiatedCount = preparedEnriched.filter(negotiated).length;
  const negotiatedAnywhere = Object.values(tmap).filter(s => Number.isFinite(s?.block_value) && s.block_value > 0).length;
  const preparedAllSession = segment === "nego" ? preparedEnriched.filter(negotiated).map(asNegotiated) : preparedEnriched;
  const windowed = changePeriod !== "1d" && segment !== "nego";
  const orNull = v => Number.isFinite(v) ? v : null;
  const asPeriod = r => {
    const hit = changeOver(r.ticker, changePeriod);
    const st = statsOver(r.ticker, changePeriod);
    return {
      ...r,
      changePercent: hit ? hit.pct : null,
      // Dropped, not converted: a window has no single сум figure — it spans
      // many sessions — and carrying the session's would put this morning's
      // сумы beside half a year's percent.
      changeValue: null,
      periodPct: hit ? hit.pct : null,
      stockVolume: orNull(st?.value),
      periodVolume: orNull(st?.value),
      stockQuantity: orNull(st?.qty),
      stockTradeCount: orNull(st?.trades),
      // The window's volume-weighted price. Cleared rather than left as the
      // session's, so «Ср. цена акции» can never quote one morning under a year.
      avgPrice: Number.isFinite(st?.vwap) ? st.vwap : undefined,
      vwap: orNull(st?.vwap),
      // `undefined`, not null: the session renderers fall back to the last price
      // when these are exactly null, and a window with no stored open must show
      // a dash rather than today's quote.
      openPrice: Number.isFinite(st?.open) ? st.open : undefined,
      highPrice: Number.isFinite(st?.high) ? st.high : undefined,
      lowPrice: Number.isFinite(st?.low) ? st.low : undefined,
      ts: st && Number.isFinite(st.largest_value) ? {
        ...(r.ts || {}),
        largest_value: st.largest_value,
        largest_qty: orNull(st.largest_qty),
        largest_pct_value: orNull(st.largest_pct)
      } : r.ts ? {
        ...r.ts,
        largest_value: null,
        largest_qty: null,
        largest_pct_value: null
      } : r.ts,
      periodFrom: st?.from || hit?.from || null,
      periodTo: st?.to || null,
      periodSessions: orNull(st?.sessions),
      periodApprox: st?.approx === true,
      // How many of the window's sessions could say how many deals they held.
      // Absent when all of them could; a number here means the deal count and
      // the largest deal are floors over that many sessions, not the whole.
      periodDetailSessions: orNull(st?.detail_sessions)
    };
  };
  const preparedAll = windowed ? preparedAllSession.map(asPeriod) : preparedAllSession;
  const isPreferredSec = r => smap[r.ticker]?.is_preferred === true || smap[r.ticker]?.share_type === "preferred" || r.share_type === "preferred";
  const byClass = type === "preferred" ? preparedAll.filter(isPreferredSec) : type === "ordinary" ? preparedAll.filter(r => !isPreferredSec(r)) : preparedAll;
  const isDormant = r => {
    const item = instruments[String(r.ticker || "").toUpperCase()];
    return item ? item.is_active === false : r.inactive === true;
  };
  const dormantCount = byClass.filter(isDormant).length;
  const prepared = byClass.filter(r => isDormant(r) === inactiveOnly);
  const mapRows = byClass.filter(r => !isDormant(r));
  const periodMapRows = mapRows;
  const search = String(query || "").trim().toLowerCase();
  const rowSector = r => sectorOf(r.ticker, smap, companyMap);
  const presentSectors = orderSectors([...new Set(prepared.map(rowSector))]);
  const sectorWord = lang === "en" ? "Sector" : lang === "uz" ? "Soha" : "Отрасль";
  const activeSector = presentSectors.includes(marketSector) ? marketSector : null;
  const sectorMapRows = activeSector ? periodMapRows.filter(r => rowSector(r) === activeSector) : periodMapRows;
  const ratioOf = ticker => ratios[ticker] || ratios[String(ticker || "").toUpperCase()] || null;
  const mktCapOf = r => Number.isFinite(r.marketCap) ? r.marketCap : null;
  const multiplesOf = r => multiples[String(r.ticker || "").toUpperCase()] || null;
  const unavailableMultiple = () => ({
    value: null,
    status: multiplesStatus === "loading" ? "loading" : "unavailable"
  });
  const multipleOf = (r, field) => multiplesOf(r)?.[field] || unavailableMultiple();
  const valuationOf = r => {
    const server = multiplesOf(r);
    return {
      pe: server?.pe || unavailableMultiple(),
      pb: server?.pb || unavailableMultiple(),
      server: Boolean(server)
    };
  };
  const peOf = r => {
    const m = valuationOf(r).pe;
    return m?.status === "out_of_range" ? null : m?.value ?? null;
  };
  const annualisedFin = (r, field) => {
    const fin = finOf(r.ticker);
    const value = fin?.[field];
    if (!Number.isFinite(value)) return null;
    const months = Number.isFinite(fin?.period_months) ? fin.period_months : fin?.quarter > 0 ? fin.quarter * 3 : fin?.year ? 12 : null;
    if (!months || months <= 0) return null;
    return value * 12 / months;
  };
  const pbOf = r => {
    const m = valuationOf(r).pb;
    return m?.status === "out_of_range" ? null : m?.value ?? null;
  };
  return {
    changeOver,
    parOf,
    priceToPar,
    smap,
    finOf,
    negotiatedCount,
    negotiatedAnywhere,
    windowed,
    byClass,
    isDormant,
    dormantCount,
    prepared,
    search,
    rowSector,
    presentSectors,
    sectorWord,
    activeSector,
    sectorMapRows,
    ratioOf,
    mktCapOf,
    multipleOf,
    multiplesOf,
    valuationOf,
    peOf,
    annualisedFin,
    pbOf
  };
}
