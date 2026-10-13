import { safeNumber } from "./numbers.js";

export { safeNumber };

function locale(language) {
  return language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
}

export function formatCompactNumber(value, language, digits = 1) {
  const number = safeNumber(value);
  if (number === null) return "—";
  return new Intl.NumberFormat(locale(language), {
    notation: Math.abs(number) >= 1000 ? "compact" : "standard",
    maximumFractionDigits: digits,
  }).format(number);
}

export function formatSignedPercent(value, digits = 1) {
  const number = safeNumber(value);
  if (number === null) return "—";
  const fixed = Number(number.toFixed(digits));
  return `${fixed > 0 ? "+" : ""}${fixed}%`;
}

export function formatRatio(value, digits = 2, language = "ru") {
  const number = safeNumber(value);
  if (number === null) return "—";
  return new Intl.NumberFormat(locale(language), { maximumFractionDigits: digits }).format(number);
}

export function formatMarketNumber(value, language, digits = 2) {
  const number = safeNumber(value);
  if (number === null) return "—";
  return new Intl.NumberFormat(locale(language), {
    minimumFractionDigits: Math.abs(number) < 10 ? 2 : 0,
    maximumFractionDigits: digits,
  }).format(number);
}

export function signedFixed(value, digits = 2) {
  const number = safeNumber(value);
  if (number === null) return "—";
  const rounded = Number(number.toFixed(digits)) + 0; // Normalize negative zero.
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(digits)}`;
}

/** A session move as the board writes it — «-1 699 · -5,16%» — so the company
 * header cannot print the same move in another notation. */
export function formatMarketChange(value, percent, language) {
  const v = safeNumber(value), p = safeNumber(percent);
  if (v === null || p === null) return "—";
  return `${v > 0 ? "+" : ""}${formatMarketNumber(v, language)} · ${p > 0 ? "+" : ""}${formatRatio(p, 2, language)}%`;
}
