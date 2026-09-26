import { changePeriodLabel } from "../../shared/marketPeriods.jsx";
import { mt } from "../../shared/marketCopy.jsx";
export function marketColumns({
  lang,
  changePeriod
}) {
  const COL_GROUPS = [{
    key: "overview",
    title: mt(lang, "grpOverview"),
    cols: [
    // «Изм.» follows the period selector; these two never do. A reader who is
    // comparing the week against the month needs both on screen at once, and a
    // column whose meaning depends on a control elsewhere cannot be that.
    ["change", `${mt(lang, "change")} (${changePeriodLabel(changePeriod, lang, "short")})`], ["change1w", `${mt(lang, "change")} 1${lang === "en" ? "W" : lang === "uz" ? "H" : "Н"}`], ["change1m", `${mt(lang, "change")} 1${lang === "en" ? "M" : lang === "uz" ? "O" : "М"}`],
    // «Номинальная стоимость» and what the market pays for it. The par is a
    // registry fact about the security; the ratio beside it is the reading a
    // par is FOR — a share trading at eighteen times its par and one trading
    // below it are two different propositions.
    ["nominal", mt(lang, "nominalCol")], ["priceToPar", mt(lang, "nominalToPrice")], ["open", mt(lang, "open")], ["high", mt(lang, "high")], ["low", mt(lang, "low")], ["date", mt(lang, "date")], ["source", mt(lang, "source")]]
  }, {
    key: "volumes",
    title: mt(lang, "grpVolumes"),
    cols: [["volume", mt(lang, "volumeCol")], ["volQty", mt(lang, "volQty")], ["avgShare", mt(lang, "avgSharePrice")], ["avgTrade", mt(lang, "avgTradePrice")], ["bigTrade", mt(lang, "bigTrade")], ["volShare", mt(lang, "volShare")]]
  }, {
    key: "financials",
    title: mt(lang, "grpFinancials"),
    cols: [["finRevenue", mt(lang, "finRevenue")], ["finGross", mt(lang, "finGross")], ["finCash", mt(lang, "finCash")], ["finLiab", mt(lang, "finLiab")], ["finNet", mt(lang, "finNet")], ["finOperating", mt(lang, "finOperating")]]
  },
  // Долг/Капитал удалён по ТЗ мультипликаторов (лист 06): 47 из 99 значений
  // не воспроизводились, единицы были смешаны. Его роль делят P/S
  // (нефинансовый сектор) и Капитал/Активы (в первую очередь банки).
  {
    key: "multiples",
    title: mt(lang, "grpMultiples"),
    cols: [["mktCap", mt(lang, "mktCap")], ["pe", "P/E"], ["pb", "P/B"], ["ps", "P/S"], ["roe", "ROE"], ["roa", "ROA"], ["netMargin", mt(lang, "netMargin")], ["eqAssets", mt(lang, "equityAssets")]]
  },
  // The ratio rows of the company page's «Коэффициенты» card, on the board —
  // the same numbers from the same indicator filings, so a reader who
  // compares two issuers does not have to open two pages to do it. Published
  // as the issuer published them (Долг/Активы in percent, the rest bare
  // coefficients), with the year each one belongs to under the figure.
  {
    key: "coefficients",
    title: mt(lang, "grpRatios"),
    cols: [["currentRatio", mt(lang, "currentRatio")], ["quickRatio", mt(lang, "quickRatio")], ["debtAssets", mt(lang, "debtAssets")], ["assetTurnover", mt(lang, "assetTurnover")], ["roce", "ROCE"]]
  }];
  const MARKET_COLS = COL_GROUPS.flatMap(g => g.cols);
  const CORE_COLS = [["ticker", mt(lang, "ticker")], ["company", mt(lang, "company")], ["last", mt(lang, "last")]];
  const SORT_LABEL_OF = Object.fromEntries([...CORE_COLS, ...MARKET_COLS]);
  return {
    COL_GROUPS,
    MARKET_COLS,
    CORE_COLS,
    SORT_LABEL_OF
  };
}
