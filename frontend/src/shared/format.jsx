import { t } from "./i18n.jsx";

function safeNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function formatDateLabel(value, language) {
  if (!value) return t(language, "analysis.noData");
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return t(language, "analysis.noData");
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.DateTimeFormat(locale, { day: "2-digit", month: "long", year: "numeric" }).format(date);
}

function formatCompactNumber(value, language, digits = 1) {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.NumberFormat(locale, {
    notation: Math.abs(num) >= 1000 ? "compact" : "standard",
    maximumFractionDigits: digits,
  }).format(num);
}

function formatSignedPercent(value, digits = 1) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const fixed = Number(num.toFixed(digits));
  return `${fixed > 0 ? "+" : ""}${fixed}%`;
}

function formatRatio(value, digits = 2, language = "ru") {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(num);
}

function formatMarketNumber(value, language, digits = 2) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: Math.abs(num) < 10 ? 2 : 0,
    maximumFractionDigits: digits,
  }).format(num);
}

function formatCatalogDate(value, language) {
  if (!value) return "—";
  const text = String(value).trim();
  const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(text) ? `${text}T12:00:00` : text);
  if (Number.isNaN(date.getTime())) return text;
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric" }).format(date);
}

export { formatCatalogDate, formatCompactNumber, formatDateLabel, formatMarketNumber, formatRatio, formatSignedPercent, safeNumber };

export function signedFixed(v, dp = 2) {
  const r = Number(Number(v).toFixed(dp)) + 0; // +0 folds -0 into 0
  return `${r > 0 ? "+" : ""}${r.toFixed(dp)}`;
}
