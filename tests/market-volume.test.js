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
