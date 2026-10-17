/**
 * terminalCommands.js — the catalog terminal's command language.
 *
 * One line, Bloomberg-style: a ticker, a function code and, optionally, a
 * standard, in any order (ТЗ «терминал каталога», «Навигация»):
 *
 *   SQBN FA        → SQBN, financials (FA is Bloomberg's alias of PL)
 *   AGBA MSFO PL   → AGBA, P&L on IFRS
 *   EQS            → the market screener, no ticker needed
 *
 * The registry here is the single source for the parser, the suggestions,
 * HELP and the number keys, so none of them can drift from the others.
 * Pure functions only: no React, no fetch.
 */

export const ISSUER_FUNCTIONS = [
  { code: "SUM", ru: "Обзор", uz: "Umumiy", en: "Summary" },
  { code: "PL", ru: "Прибыль и убыток", uz: "Foyda va zarar", en: "Profit and loss" },
  { code: "BS", ru: "Баланс", uz: "Balans", en: "Balance sheet" },
  { code: "RAT", ru: "Коэффициенты", uz: "Koeffitsientlar", en: "Ratios" },
  { code: "FV", ru: "Оценка", uz: "Baholash", en: "Fair value" },
  { code: "RV", ru: "Аналоги", uz: "Analoglar", en: "Peers" },
  { code: "DVD", ru: "Дивиденды", uz: "Dividendlar", en: "Dividends" },
  { code: "CF", ru: "Отчёты", uz: "Hisobotlar", en: "Filings" },
  { code: "CN", ru: "Новости", uz: "Yangiliklar", en: "News" },
  { code: "DQ", ru: "Качество данных", uz: "Ma'lumotlar sifati", en: "Data quality" },
  { code: "REC", ru: "Сверка НСБУ ↔ МСФО", uz: "BHMS ↔ MHXS solishtirish", en: "NSBU ↔ IFRS reconciliation" },
];

export const MARKET_FUNCTIONS = [
  { code: "CAT", ru: "Каталог", uz: "Katalog", en: "Catalog" },
  { code: "EQS", ru: "Скринер", uz: "Skriner", en: "Screener" },
  { code: "MON", ru: "Монитор", uz: "Monitor", en: "Monitor" },
  { code: "PNL", ru: "Панели", uz: "Panellar", en: "Panels" },
  { code: "LAST", ru: "Последние экраны", uz: "Oxirgi ekranlar", en: "Recent screens" },
  { code: "HELP", ru: "Справка", uz: "Yordam", en: "Help" },
  { code: "ADM", ru: "Админка", uz: "Admin", en: "Admin" },
];

// Keys 1–9 and 0 open the first ten issuer functions, in registry order.
export const TAB_KEYS = ISSUER_FUNCTIONS.slice(0, 10).map((fn, i) => ({ key: i === 9 ? "0" : String(i + 1), code: fn.code }));

const ALIASES = { DES: "SUM", FA: "PL", GO: "" };
const STANDARDS = { NSBU: "NSBU", "НСБУ": "NSBU", MSFO: "MSFO", IFRS: "MSFO", "МСФО": "MSFO" };

const ISSUER_CODES = new Set(ISSUER_FUNCTIONS.map((f) => f.code));
const MARKET_CODES = new Set(MARKET_FUNCTIONS.map((f) => f.code));

export function functionLabel(code, lang = "ru") {
  const fn = [...ISSUER_FUNCTIONS, ...MARKET_FUNCTIONS].find((f) => f.code === code);
  return fn ? (fn[lang] || fn.ru) : code;
}

export function isIssuerFunction(code) {
  return ISSUER_CODES.has(code);
}

/**
 * Index the catalog's issuers by every ticker they carry: an entry stands for
 * all its share classes and bond series, and any of them should open it.
 */
export function tickerIndex(companies) {
  const index = new Map();
  for (const company of companies || []) {
    const main = String(company.ticker || "").toUpperCase();
    if (!main) continue;
    for (const t of [main, ...(company.tickers || []).map((x) => String(x).toUpperCase())]) {
      if (!index.has(t)) index.set(t, main);
    }
  }
  return index;
}

/**
 * Parse one command line.
 * Returns { ticker, func, market, form, unknown } where `ticker` is the
 * issuer's catalog ticker, `func` an issuer function, `market` a market
 * function, and `unknown` the words that matched nothing.
 */
export function parseCommand(text, index) {
  const result = { ticker: null, func: null, market: null, form: null, unknown: [] };
  const words = String(text || "").trim().toUpperCase().split(/\s+/).filter(Boolean);
  for (const raw of words) {
    const word = Object.prototype.hasOwnProperty.call(ALIASES, raw) ? ALIASES[raw] : raw;
    if (!word) continue;
    if (STANDARDS[word]) result.form = STANDARDS[word];
    else if (ISSUER_CODES.has(word)) result.func = word;
    else if (MARKET_CODES.has(word)) result.market = word;
    else if (index?.has(word)) result.ticker = index.get(word);
    else result.unknown.push(raw);
  }
  return result;
}

/** True when the line asked for nothing the terminal can do. */
export function isEmptyCommand(parsed) {
  return !parsed.ticker && !parsed.func && !parsed.market && !parsed.form;
}

/**
 * Suggestions for the word being typed. A completed suggestion replaces that
 * last word, so choosing one never discards what was typed before it.
 */
export function suggestCommands(text, companies, lang = "ru", limit = 12) {
  const raw = String(text || "");
  const words = raw.trim().split(/\s+/).filter(Boolean);
  const endsWithSpace = /\s$/.test(raw);
  const prefix = endsWithSpace ? "" : (words[words.length - 1] || "");
  const head = endsWithSpace ? words : words.slice(0, -1);
  const index = tickerIndex(companies);
  const hasTicker = head.some((w) => index.has(w.toUpperCase()));
  const up = prefix.toUpperCase();
  const low = prefix.toLowerCase();
  const join = (word) => [...head, word].join(" ") + " ";
  const out = [];

  const fnMatches = (list) => list
    .filter((fn) => !up || fn.code.startsWith(up) || (fn[lang] || fn.ru).toLowerCase().includes(low))
    .map((fn) => ({ value: join(fn.code), code: fn.code, label: fn[lang] || fn.ru, kind: "function" }));

  if (hasTicker) {
    out.push(...fnMatches(ISSUER_FUNCTIONS));
  } else if (up) {
    for (const company of companies || []) {
      const tickers = [company.ticker, ...(company.tickers || [])].map((t) => String(t || "").toUpperCase());
      const hit = tickers.find((t) => t.startsWith(up))
        || ((company.company_name || "").toLowerCase().includes(low) ? String(company.ticker).toUpperCase() : null);
      if (hit) out.push({ value: join(hit), code: hit, label: company.company_name || hit, kind: "ticker" });
    }
    out.sort((a, b) => Number(!a.code.startsWith(up)) - Number(!b.code.startsWith(up)) || a.code.localeCompare(b.code));
    out.push(...fnMatches(MARKET_FUNCTIONS));
  } else {
    out.push(...fnMatches(MARKET_FUNCTIONS));
  }
  return out.slice(0, limit);
}

/** The canonical text of a screen, as LAST lists it and the URL keeps it. */
export function commandText({ ticker, func, market, form }) {
  if (market) return market;
  return [ticker, form && form !== "NSBU" ? form : null, func].filter(Boolean).join(" ");
}
