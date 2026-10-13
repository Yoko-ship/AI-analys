import test from "node:test";
import assert from "node:assert/strict";
import { marketVolumeMetrics, marketVolumeShare } from "../frontend/src/lib/marketVolume.js";

test("map and table volume metrics use the prepared period and current market total", () => {
  const row = { stockVolume: 1000000, stockQuantity: 1000, stockTradeCount: 4,
    avgPrice: 1001, last_trade_date: "2026-09-25", ts: { largest_value: 700000 } };
  assert.deepEqual(marketVolumeMetrics(row, { boardDay: "20260925", totalVolume: 4000000 }), {
    volume: 1000000, volQty: 1000, avgShare: 1001, avgTrade: 250000, bigTrade: 700000, volShare: 25,
  });
  assert.equal(marketVolumeShare(row, { boardDay: "20260926", totalVolume: 4000000 }), 0);
  assert.equal(marketVolumeShare(row, { boardDay: null, totalVolume: 10000000 }), 10);
});

test("missing activity is not converted to zero or divided by missing counts", () => {
  assert.deepEqual(marketVolumeMetrics({}, {}), {
    volume: null, volQty: null, avgShare: null, avgTrade: null, bigTrade: null, volShare: null,
  });
  const metrics = marketVolumeMetrics({ stockVolume: 0, stockQuantity: 0, stockTradeCount: 0 }, { totalVolume: 100 });
  assert.equal(metrics.volume, 0);
  assert.equal(metrics.volShare, 0);
  assert.equal(metrics.avgShare, null);
  assert.equal(metrics.avgTrade, null);
});

test("average price and trade value work for bond and equity quantities without rounding inputs", () => {
  const metrics = marketVolumeMetrics({ stockVolume: 1000.05, stockQuantity: 3, stockTradeCount: 2 }, {});
  assert.equal(metrics.avgShare, 1000.05 / 3);
  assert.equal(metrics.avgTrade, 500.025);
});

test("a period's average deal is the server's, measured over the sessions that counted deals", async () => {
  // BNGPP over a month on 12.10.2026: 135 578 469 сум in 20 sessions, but deals were
  // counted in only 19 of them (276). The whole month's сумы over 19 sessions' deals
  // printed 491 226; the average over the sessions that counted is 453 719. 291
  // cells across 1М–YTD were overstated this way.
  const { avgTradeValue } = await import("../frontend/src/lib/marketVolume.js");
  const row = { stockVolume: 135578469, stockTradeCount: 276, avgTrade: 453719 };
  assert.equal(avgTradeValue(row), 453719);
  assert.equal(marketVolumeMetrics(row, {}).avgTrade, 453719);
  // A session, where every deal is counted, still divides.
  assert.equal(avgTradeValue({ stockVolume: 1000000, stockTradeCount: 4 }), 250000);
});
