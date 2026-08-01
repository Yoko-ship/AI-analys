// The formatting layer (ТЗ §10.7): rounding happens here and nowhere earlier.
import { strict as assert } from "node:assert";
import { describe, it } from "node:test";
import { compact, metric, num, pct, price } from "../frontend/src/lib/format.js";
import { config, isEnabled, resetForTests, threshold, loadConfig } from "../frontend/src/lib/flags.js";

describe("format", () => {
  it("renders an absent value as a dash, never as zero", () => {
    for (const fn of [num, pct, price, compact]) {
      assert.equal(fn(null, "ru"), "—");
      assert.equal(fn(undefined, "ru"), "—");
      assert.equal(fn(NaN, "ru"), "—");
    }
  });

  it("keeps four decimals for a sub-unit price", () => {
    // KASU trades at 0.01 sum; two decimals hide every move it makes.
    assert.match(price(0.0125, "en"), /0\.0125/);
    assert.match(price(1234.5, "en"), /1,234\.5/);
  });

  it("signs a percentage", () => {
    assert.equal(pct(12.345, "en"), "+12.35%");
    assert.equal(pct(-3, "en"), "-3.00%");
    assert.equal(pct(0, "en"), "0.00%");
  });

  it("abbreviates large sums", () => {
    assert.match(compact(1_234_567_890, "en"), /1\.23B/);
    assert.match(compact(29_088_000_000_000, "ru"), /трлн/);
  });

  it("renders a metric envelope, dash when the server withheld the value", () => {
    assert.equal(metric({ value: null, status: "loss_making" }, "en"), "—");
    assert.match(metric({ value: 8.4, status: "ok" }, "en"), /8\.4/);
  });
});

describe("flags", () => {
  it("falls back to the configured defaults when the server cannot answer", async () => {
    resetForTests();
    await loadConfig(async () => { throw new Error("offline"); });
    assert.equal(isEnabled("metrics_v2"), true);
    // The defaults must match config/thresholds.json, or the label would claim
    // a window the server did not apply.
    assert.equal(threshold("moving_average.ma20_calendar_days"), 28);
    assert.equal(threshold("volatility.window_days"), 30);
    assert.deepEqual(threshold("multiples.pe_range"), [0.5, 200]);
  });

  it("prefers the server's values", async () => {
    resetForTests();
    await loadConfig(async () => ({
      ok: true,
      json: async () => ({ ok: true, flags: { map_v2: false },
        thresholds: { moving_average: { ma20_calendar_days: 35 } } }),
    }));
    assert.equal(isEnabled("map_v2"), false);
    assert.equal(threshold("moving_average.ma20_calendar_days"), 35);
  });

  it("returns the fallback for an unknown path", () => {
    assert.equal(threshold("nope.nothing", "fallback"), "fallback");
    assert.ok(config().thresholds);
  });
});
