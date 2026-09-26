// format.js — the ONE place rounding and digit separators happen (ТЗ §10.7).
//
// The rule this module exists to enforce: prices and sums are carried through
// every calculation unrounded, and rounded only here, on the way to the screen.
// Rounding earlier is how a security priced at 0.01 sum came to show a 0 % move
// on 232 trades — two decimals applied before the division erased the change
// entirely.
//
// Nothing here computes. It formats what a calculation already decided.

import { safeNumber } from "./numbers.js";

const LOCALES = { ru: "ru-RU", uz: "ru-RU", en: "en-US" };

export function localeOf(lang) {
  return LOCALES[lang] || LOCALES.ru;
}

/** Final display/export rounding. Never feed this value back into calculations. */
export function roundedDisplayValue(value, digits = 0) {
  const n = safeNumber(value);
  if (n === null) return null;
  const scale = 10 ** digits;
  // eslint-disable-next-line no-restricted-properties -- This is the shared output boundary.
  return Math.round(n * scale) / scale + 0;
}

/** A number for display. `null` becomes an em-dash, never a zero. */
export function num(value, lang, digits = 2) {
  const n = safeNumber(value);
  if (n === null) return "—";
  return n.toLocaleString(localeOf(lang), {
    minimumFractionDigits: 0, maximumFractionDigits: digits,
  });
}

/**
 * A percentage, signed.
 *
 * The value must already be a percentage computed on unrounded inputs — this
 * function is the last step, not part of the arithmetic.
 */
export function pct(value, lang, digits = 2) {
  const n = safeNumber(value);
  if (n === null) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}%`;
}

/**
 * A price. Sub-unit prices keep four decimals.
 *
 * KASU trades at 0.01 sum: formatted to two decimals it reads "0,01" and every
 * move it makes rounds away. The extra digits are shown only where they carry
 * information, so ordinary prices stay readable.
 */
export function price(value, lang) {
  const n = safeNumber(value);
  if (n === null) return "—";
  const digits = Math.abs(n) < 1 ? 4 : 2;
  return n.toLocaleString(localeOf(lang), {
    minimumFractionDigits: digits > 2 ? digits : 0, maximumFractionDigits: digits,
  });
}

/** Large sums abbreviated for a cell: 1 234 567 -> "1,23 млн". */
export function compact(value, lang) {
  const n = safeNumber(value);
  if (n === null) return "—";
  const abs = Math.abs(n);
  const units = lang === "en"
    ? [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]]
    : [[1e12, " трлн"], [1e9, " млрд"], [1e6, " млн"], [1e3, " тыс."]];
  for (const [scale, suffix] of units) {
    if (abs >= scale) return `${(n / scale).toFixed(2).replace(".", lang === "en" ? "." : ",")}${suffix}`;
  }
  return num(n, lang, 2);
}

/** A metric envelope `{value, status}` — the value, or a dash that explains itself. */
export function metric(m, lang, formatter = num) {
  if (!m || m.value == null) return "—";
  return formatter(m.value, lang);
}
