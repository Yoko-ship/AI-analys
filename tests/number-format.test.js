import test from "node:test";
import assert from "node:assert/strict";
import {
  safeNumber, formatCompactNumber, formatSignedPercent, formatRatio,
  formatMarketNumber, signedFixed,
} from "../frontend/src/lib/numberFormat.js";

test("numeric formatting distinguishes missing values from real zero", () => {
  for (const value of [null, undefined, "", "  ", NaN, Infinity, "invalid"]) {
    assert.equal(safeNumber(value), null);
    for (const format of [formatCompactNumber, formatSignedPercent, formatRatio, formatMarketNumber, signedFixed]) {
      assert.equal(format(value), "—", `${format.name}: ${String(value)}`);
    }
  }
  assert.equal(safeNumber(0), 0);
  assert.equal(safeNumber("0"), 0);
  assert.equal(safeNumber("12.5"), 12.5);
  assert.equal(formatSignedPercent(0), "0%");
  assert.equal(signedFixed(0), "0.00");
  assert.equal(formatMarketNumber(0, "en"), "0.00");
});

test("display precision, signs and locales are preserved", () => {
  assert.equal(formatSignedPercent(1.234), "+1.2%");
  assert.equal(formatSignedPercent(-0.0001), "0%");
  assert.equal(signedFixed(-0.0001), "0.00");
  assert.equal(signedFixed(1.235), "+1.24");
  assert.equal(formatCompactNumber(1234, "en"), "1.2K");
  assert.equal(formatRatio(1.2345, 2, "en"), "1.23");
  assert.equal(formatRatio(1.2345, 2, "ru"), "1,23");
  assert.equal(formatMarketNumber(12.5, "en"), "12.5");
});

test("a session change reads the same on the board and in the company header", async () => {
  // Audit of 12.10.2026: 90 headers read «-1699.00 (-5.16%)» — a point, no digit
  // groups — beside a board that writes «-1 699 · -5,16%».
  const { formatMarketChange } = await import("../frontend/src/lib/numberFormat.js");
  assert.equal(formatMarketChange(-1699, -5.16, "ru"), "-1 699 · -5,16%");
  assert.equal(formatMarketChange(9.99, 1.69, "ru"), "+9,99 · +1,69%");
  assert.equal(formatMarketChange(-1699, -5.16, "en"), "-1,699 · -5.16%");
  assert.equal(formatMarketChange(null, 1, "ru"), "—");
});

test("a percent change is written one way everywhere, and never as «−0%»", async () => {
  // ТЗ 12.10.2026, задачи 4–5: the card's side lists printed «-3.22%» with a point,
  // and a move that rounds to nothing printed «−0%» (URTS −0,02 сум, PLST 1Н).
  const { formatChangePercent, formatMarketChange } = await import("../frontend/src/lib/numberFormat.js");
  assert.equal(formatChangePercent(-3.22, "ru"), "-3,22%");
  assert.equal(formatChangePercent(1.694, "ru"), "+1,69%");
  assert.equal(formatChangePercent(-3.22, "en"), "-3.22%");
  assert.equal(formatChangePercent(-0.0001, "ru"), "0%");
  assert.equal(formatChangePercent(-0.004, "ru"), "0%");
  assert.equal(formatChangePercent(null, "ru"), "—");
  assert.equal(formatMarketChange(-0.02, -0.0021, "ru"), "-0,02 · 0%");
  assert.equal(formatMarketChange(-0.001, -0.0001, "ru"), "0,00 · 0%");
});

test('market number formatting reuses formatters without mixing locales or precision', async () => {
  const Native = Intl.NumberFormat;
  let constructions = 0;
  Intl.NumberFormat = new Proxy(Native, {construct(target, args) {
    constructions++; return Reflect.construct(target, args);
  }});
  try {
    // A fresh module makes this independent of formatters warmed by other tests.
    const model = await import('../frontend/src/lib/numberFormat.js?market-performance');
    for (const lang of ['ru', 'uz', 'en']) {
      for (const value of [20980, 12680, 0, 0.01, -0.02]) {
        for (const digits of [2, 4]) {
          for (const name of ['formatMarketNumber','formatRatio']) {
            const actual = name === 'formatRatio' ? model[name](value, digits, lang) : model[name](value, lang, digits);
            const expected = new Native(lang === 'en' ? 'en-US' : lang === 'uz' ? 'uz-Latn-UZ' : 'ru-RU', {
              ...(name === 'formatMarketNumber' ? {minimumFractionDigits:Math.abs(value) < 10 ? 2 : 0} : {}), maximumFractionDigits:digits,
            }).format(value);
            assert.equal(actual, expected);
          }
        }
      }
    }
    const warmed = constructions;
    for (let i=0; i<100; i++) {model.formatMarketNumber(20980,'ru'); model.formatRatio(1.69,2,'ru');}
    assert.equal(constructions, warmed);
  } finally {Intl.NumberFormat = Native;}
});
