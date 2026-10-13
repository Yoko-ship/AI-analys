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
