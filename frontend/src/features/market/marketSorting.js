import { avgSharePrice, avgTradeValue, compareSortValues, marketDisplayPrice } from "../../shared/marketModel.jsx";
import { marketRowDay } from "../../lib/valuation.js";
export function sortMarketRows({
  changePeriod,
  changeOver,
  parOf,
  priceToPar,
  annualisedFin,
  finOf,
  mktCapOf,
  peOf,
  pbOf,
  multipleOf,
  ratioOf,
  prepared,
  favOnly,
  hasFav,
  activeSector,
  rowSector,
  search,
  sortKeys
}) {
  const sortAccessors = {
    ticker: r => r.ticker || "",
    company: r => r.name || "",
    last: r => marketDisplayPrice(r),
    // The selected period's change, so the order follows what the column shows.
    change: r => changePeriod === "1d" ? r.changePercent : changeOver(r.ticker, changePeriod)?.pct ?? null,
    change1w: r => changeOver(r.ticker, "1w")?.pct ?? null,
    change1m: r => changeOver(r.ticker, "1m")?.pct ?? null,
    nominal: r => parOf(r),
    priceToPar: r => priceToPar(r),
    open: r => r.openPrice,
    high: r => r.highPrice,
    low: r => r.lowPrice,
    volume: r => r.stockVolume,
    volQty: r => r.stockQuantity,
    avgShare: r => Number.isFinite(r.avgPrice) ? r.avgPrice : avgSharePrice(r),
    avgTrade: r => avgTradeValue(r),
    bigTrade: r => r.ts?.largest_value,
    volShare: r => r.stockVolume,
    // ТЗ §7: a column that mixes reporting periods may not be ordered by its
    // raw values. The cached rows span twelve different (year, months)
    // combinations, so a full year always outranked a peer's four quarters for
    // no reason the reader could see. The CELL keeps its own period and label;
    // only the SORT runs on the twelve-month normalisation. Balance-sheet lines
    // are a position on a date and are never scaled.
    finRevenue: r => annualisedFin(r, "revenue"),
    finGross: r => annualisedFin(r, "gross_profit"),
    finCash: r => finOf(r.ticker)?.cash,
    finLiab: r => finOf(r.ticker)?.total_liabilities,
    finNet: r => annualisedFin(r, "net_income"),
    finOperating: r => annualisedFin(r, "operating_income"),
    mktCap: r => mktCapOf(r),
    pe: r => peOf(r),
    pb: r => pbOf(r),
    // Sort on what is RENDERED — the server envelope — not on the raw
    // indicator feed. Sorting on the feed while rendering the envelope put a
    // withheld value's ghost in the ordering (ТЗ мультипликаторов, лист 05:
    // «сортировка по марже выдаёт бессмысленный порядок»).
    ps: r => multipleOf(r, "ps").value,
    roe: r => multipleOf(r, "roe").value,
    roa: r => multipleOf(r, "roa").value,
    netMargin: r => multipleOf(r, "net_margin").value,
    eqAssets: r => multipleOf(r, "equity_assets").value,
    // The published coefficients sort on what they show. Unlike the financials
    // columns there is nothing to annualise: a liquidity ratio is a position on
    // a date, and a turnover is already a full year's revenue over assets.
    currentRatio: r => ratioOf(r.ticker)?.current_ratio,
    quickRatio: r => ratioOf(r.ticker)?.quick_ratio,
    debtAssets: r => ratioOf(r.ticker)?.debt_ratio,
    assetTurnover: r => ratioOf(r.ticker)?.total_asset_turnover,
    roce: r => ratioOf(r.ticker)?.return_to_capital_employed,
    // Normalized to YYYYMMDD so the comparison is chronological. The raw field is
    // a mix of DD.MM.YYYY (live feed) and YYYY-MM-DD (listings registry), and
    // comparing those as strings ordered by the leading digits — "31.01.2026"
    // sorted above "05.02.2026", so "latest first" broke at every month boundary.
    date: r => marketRowDay(r) || "",
    source: r => r.url || ""
  };
  const visibleRows = prepared.filter(row => {
    if (favOnly && !hasFav(row.ticker)) return false;
    if (activeSector && rowSector(row) !== activeSector) return false;
    if (!search) return true;
    return `${row.ticker || ""} ${row.name || ""} ${row.isin || ""}`.toLowerCase().includes(search);
  }).sort((a, b) => {
    if (!sortKeys.length) {
      // Same normalization as the `date` accessor — the default "most recently
      // traded first" order was wrong across month boundaries for exactly the
      // same reason (mixed DD.MM.YYYY / YYYY-MM-DD compared lexicographically).
      const aDate = marketRowDay(a) || "";
      const bDate = marketRowDay(b) || "";
      if (aDate !== bDate) return bDate.localeCompare(aDate);
      return Math.abs(b.changePercent ?? -Infinity) - Math.abs(a.changePercent ?? -Infinity);
    }
    // Each key decides only the rows the keys before it tied on.
    for (const {
      key,
      dir
    } of sortKeys) {
      const acc = sortAccessors[key];
      if (!acc) continue;
      const c = compareSortValues(acc(a), acc(b), dir);
      if (c) return c;
    }
    return 0;
  });
  return {
    visibleRows
  };
}
