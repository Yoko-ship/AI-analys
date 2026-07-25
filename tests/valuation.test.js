// Unit tests for the shared frontend helpers. Run with `npm run test:unit`
// (node's built-in test runner — no extra dependency).
//
// Two regressions pinned here:
//   * P/B was computed as `P/E x ROE` on the company page and as
//     `market cap / equity` in the market table. The identity is undefined for a
//     loss-maker, so every loss-making issuer showed a P/B on the board and a
//     blank on its own page.
//   * last_trade_date arrives as both DD.MM.YYYY and YYYY-MM-DD, and was compared
//     lexicographically — so "latest first" broke at every month boundary.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  finFieldPeriod,
  finPeriodCoverage,
  finRowPeriod,
  marketRowDay,
  normalizeMarketDay,
  valuationEquity,
  valuationRatios,
} from "../frontend/src/lib/valuation.js";

describe("valuationRatios", () => {
  it("computes both multiples from published figures", () => {
    const { pe, pb } = valuationRatios({
      marketCap: 1_000_000, netIncome: 100_000, equity: 500_000,
    });
    assert.equal(pe, 10);
    assert.equal(pb, 2);
  });

  it("returns a NEGATIVE P/E for a loss-maker rather than a blank", () => {
    // Screener convention: both figures ARE published, so a dash would lie.
    const { pe } = valuationRatios({ marketCap: 1_000_000, netIncome: -100_000 });
    assert.equal(pe, -10);
  });

  it("still returns P/B for a loss-maker — the divergence that was the bug", () => {
    // The old company-page formula (P/E x ROE) yielded null here while the market
    // table yielded 2. Both call this now, so both get 2.
    const { pe, pb } = valuationRatios({
      marketCap: 1_000_000, netIncome: -100_000, equity: 500_000, roePercent: -20,
    });
    assert.equal(pe, -10);
    assert.equal(pb, 2);
  });

  it("agrees whether equity is supplied directly or via the ROE identity", () => {
    // net income 100k at ROE 20% implies equity 500k.
    const direct = valuationRatios({ marketCap: 1_000_000, netIncome: 100_000, equity: 500_000 });
    const derived = valuationRatios({ marketCap: 1_000_000, netIncome: 100_000, roePercent: 20 });
    assert.equal(direct.pb, derived.pb);
  });

  it("prefers a published equity over the derived one", () => {
    const { pb } = valuationRatios({
      marketCap: 1_000_000, netIncome: 100_000, equity: 250_000, roePercent: 20,
    });
    assert.equal(pb, 4); // 1_000_000 / 250_000, not the 2 the identity would give
  });

  it("treats a missing or non-positive market cap as no data", () => {
    for (const marketCap of [null, undefined, 0, -5, NaN, "1000"]) {
      const { pe, pb } = valuationRatios({ marketCap, netIncome: 100_000, equity: 500_000 });
      assert.equal(pe, null, `pe for marketCap=${marketCap}`);
      assert.equal(pb, null, `pb for marketCap=${marketCap}`);
    }
  });

  it("never divides by a zero net income", () => {
    const { pe } = valuationRatios({ marketCap: 1_000_000, netIncome: 0, equity: 500_000 });
    assert.equal(pe, null);
  });

  it("refuses P/B on non-positive book value", () => {
    for (const equity of [0, -500_000]) {
      const { pb } = valuationRatios({ marketCap: 1_000_000, netIncome: 100_000, equity });
      assert.equal(pb, null, `pb for equity=${equity}`);
    }
  });

  it("returns no NaN for any missing input", () => {
    const { pe, pb } = valuationRatios({});
    assert.equal(pe, null);
    assert.equal(pb, null);
  });
});

describe("valuationEquity", () => {
  it("rejects the ROE identity when the signs disagree", () => {
    // A positive ROE with a negative net income is inconsistent source data;
    // dividing anyway produces negative "equity".
    assert.equal(valuationEquity({ netIncome: -100_000, roePercent: 12.36 }), null);
  });

  it("rejects a near-zero ROE where rounding dominates", () => {
    assert.equal(valuationEquity({ netIncome: 100_000, roePercent: 0.05 }), null);
  });

  it("accepts a negative ROE with a negative net income", () => {
    // Both negative -> positive equity, which is a real loss-making issuer.
    assert.equal(valuationEquity({ netIncome: -100_000, roePercent: -20 }), 500_000);
  });
});

describe("reporting-period labels", () => {
  it("labels annual and quarterly rows", () => {
    assert.equal(finRowPeriod({ year: 2024, quarter: 0 }), "2024");
    assert.equal(finRowPeriod({ year: 2026, quarter: 1 }), "2026 Q1");
    assert.equal(finRowPeriod(null), null);
    assert.equal(finRowPeriod({}), null);
  });

  it("falls back to the row's period when a field has none of its own", () => {
    const row = { year: 2026, quarter: 1 };
    assert.equal(finFieldPeriod(row, "revenue"), "2026 Q1");
  });

  it("shows a field's own period when it differs from the row's", () => {
    // The UZMK class of bug: a value from another filing under this row's label.
    const row = { year: 2026, quarter: 1, field_periods: { revenue: "2024" } };
    assert.equal(finFieldPeriod(row, "revenue"), "2024");
    assert.equal(finFieldPeriod(row, "net_income"), "2026 Q1");
  });

  it("formats a quarterly field period", () => {
    const row = { year: 2026, quarter: 1, field_periods: { cash: "2023Q2" } };
    assert.equal(finFieldPeriod(row, "cash"), "2023 Q2");
  });

  it("states the months a period covers so a quarter is not read as a year", () => {
    assert.equal(finPeriodCoverage("2024", "en"), "12 months");
    assert.equal(finPeriodCoverage("2026 Q1", "en"), "3 months, year to date");
    assert.equal(finPeriodCoverage("2026 Q3", "en"), "9 months, year to date");
    assert.equal(finPeriodCoverage("2026 Q1", "ru"), "3 мес., с начала года");
  });
});

describe("normalizeMarketDay", () => {
  it("normalizes both wire formats to one comparable key", () => {
    assert.equal(normalizeMarketDay("31.01.2026"), "20260131");
    assert.equal(normalizeMarketDay("2026-02-05"), "20260205");
    assert.equal(normalizeMarketDay("20260205"), "20260205");
  });

  it("orders correctly across a month boundary", () => {
    // Raw string compare put 31.01 above 05.02; normalized it does not.
    const jan31 = normalizeMarketDay("31.01.2026");
    const feb05 = normalizeMarketDay("2026-02-05");
    assert.ok(feb05 > jan31, "February must sort after January");
    assert.ok("31.01.2026" > "2026-02-05", "the raw compare really was wrong");
  });

  it("orders correctly across a year boundary", () => {
    assert.ok(normalizeMarketDay("05.01.2026") > normalizeMarketDay("31.12.2025"));
  });

  it("returns null for junk", () => {
    for (const s of ["", null, undefined, "not a date", "2026-2-5", "5.1.2026"]) {
      assert.equal(normalizeMarketDay(s), null, `for ${JSON.stringify(s)}`);
    }
  });
});

describe("marketRowDay", () => {
  it("prefers the day-stats date over the board date", () => {
    assert.equal(marketRowDay({ ts: { trade_date: "20260205" }, last_trade_date: "31.01.2026" }),
      "20260205");
  });

  it("falls back to the board date", () => {
    assert.equal(marketRowDay({ last_trade_date: "31.01.2026" }), "20260131");
  });

  it("is null when a security has never traded", () => {
    assert.equal(marketRowDay({}), null);
    assert.equal(marketRowDay(null), null);
  });
});
