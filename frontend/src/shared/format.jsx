import { t } from "./i18n.jsx";

export { safeNumber, formatCompactNumber, formatSignedPercent, formatRatio,
  formatMarketNumber, signedFixed } from "../lib/numberFormat.js";

function formatDateLabel(value, language) {
  if (!value) return t(language, "analysis.noData");
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return t(language, "analysis.noData");
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.DateTimeFormat(locale, { day: "2-digit", month: "long", year: "numeric" }).format(date);
}

function formatRelativeTime(value, language) {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "—";
  const seconds = Number(((date.getTime() - Date.now()) / 1000).toFixed(0));
  const absolute = Math.abs(seconds);
  const locale = language === "en" ? "en" : language === "uz" ? "uz" : "ru";
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (absolute < 60) return formatter.format(seconds, "second");
  if (absolute < 3600) return formatter.format(Number((seconds / 60).toFixed(0)), "minute");
  if (absolute < 86400) return formatter.format(Number((seconds / 3600).toFixed(0)), "hour");
  if (absolute < 604800) return formatter.format(Number((seconds / 86400).toFixed(0)), "day");
  return formatDateLabel(value, language);
}

function formatCatalogDate(value, language) {
  if (!value) return "—";
  const text = String(value).trim();
  const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(text) ? `${text}T12:00:00` : text);
  if (Number.isNaN(date.getTime())) return text;
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric" }).format(date);
}

export { formatCatalogDate, formatDateLabel, formatRelativeTime };
