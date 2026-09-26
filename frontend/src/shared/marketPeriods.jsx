

// The periods the board can measure a change over. `1d` is the session — it comes
// off the live board row, not the stored history, because that is the number the
// exchange itself publishes today; the rest are windows over the settled closes
// (/api/market/changes, MARKET_CHANGE_WINDOWS on the server side).
const CHANGE_PERIODS = [
  { code: "1d", label: ["За сессию", "Sessiya", "Session"], short: ["сессия", "sessiya", "session"] },
  { code: "1w", label: ["1Н", "1H", "1W"], short: ["нед.", "hafta", "wk"] },
  { code: "1m", label: ["1М", "1O", "1M"], short: ["мес.", "oy", "mo"] },
  { code: "3m", label: ["3М", "3O", "3M"], short: ["3 мес.", "3 oy", "3mo"] },
  { code: "6m", label: ["6М", "6O", "6M"], short: ["6 мес.", "6 oy", "6mo"] },
  { code: "1y", label: ["1Г", "1Y", "1Y"], short: ["год", "yil", "yr"] },
  { code: "ytd", label: ["С начала года", "Yil boshidan", "YTD"], short: ["с 1 янв.", "1-yanv.dan", "YTD"] },
];

const CHANGE_PERIOD_KEY = "uz_market_change_period";

const changePeriodLabel = (code, lang, field = "label") => {
  const found = CHANGE_PERIODS.find((p) => p.code === code) || CHANGE_PERIODS[0];
  const i = lang === "uz" ? 1 : lang === "en" ? 2 : 0;
  return found[field][i];
};

export { CHANGE_PERIODS, CHANGE_PERIOD_KEY, changePeriodLabel };
