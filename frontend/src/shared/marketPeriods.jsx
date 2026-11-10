

// The periods the board can measure a change over. `1d` is the session — it comes
// off the live board row, not the stored history, because that is the number the
// exchange itself publishes today; the rest are windows over the settled closes
// (/api/market/changes, MARKET_CHANGE_WINDOWS on the server side).
const CHANGE_PERIODS = [
  { code: "1d", label: ["За сессию", "Sessiya", "Session"], short: ["сессия", "sessiya", "session"], performance: ["За сессию", "Sessiyadagi o‘zgarish", "1-Day Performance"] },
  { code: "1w", label: ["1Н", "1H", "1W"], short: ["нед.", "hafta", "wk"], performance: ["За неделю", "1 haftalik o‘zgarish", "1-Week Performance"] },
  { code: "1m", label: ["1М", "1O", "1M"], short: ["мес.", "oy", "mo"], performance: ["За месяц", "1 oylik o‘zgarish", "1-Month Performance"] },
  { code: "3m", label: ["3М", "3O", "3M"], short: ["3 мес.", "3 oy", "3mo"], performance: ["За 3 месяца", "3 oylik o‘zgarish", "3-Month Performance"] },
  { code: "6m", label: ["6М", "6O", "6M"], short: ["6 мес.", "6 oy", "6mo"], performance: ["За 6 месяцев", "6 oylik o‘zgarish", "6-Month Performance"] },
  { code: "1y", label: ["1Г", "1Y", "1Y"], short: ["год", "yil", "yr"], performance: ["За год", "1 yillik o‘zgarish", "1-Year Performance"] },
  { code: "ytd", label: ["С начала года", "Yil boshidan", "YTD"], short: ["с 1 янв.", "1-yanv.dan", "YTD"], performance: ["С начала года", "Yil boshidan o‘zgarish", "Year-to-Date Performance"] },
];

const CHANGE_PERIOD_KEY = "uz_market_change_period";

const changePeriodLabel = (code, lang, field = "label") => {
  const found = CHANGE_PERIODS.find((p) => p.code === code) || CHANGE_PERIODS[0];
  const i = lang === "uz" ? 1 : lang === "en" ? 2 : 0;
  return found[field][i];
};

export { CHANGE_PERIODS, CHANGE_PERIOD_KEY, changePeriodLabel };
