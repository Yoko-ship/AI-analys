import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { prepareMarketRows } from "../frontend/src/lib/marketData.js";

const quote = (overrides = {}) => ({
  isin: "UZ0001", ticker: "TEST", last_price: 120, close_price: 100,
  last_trade_date: "2026-08-14", close_date: "2026-08-13",
  volume: 240, quantity: 2, trade_count: 1, ...overrides,
});
const trades = (overrides = {}) => ({
  trade_date: "20260814", total_value: 1234, total_qty: 10,
  trade_count: 3, avg_price: 123.4, vwap: 123.4, ...overrides,
});

describe("market data shared by the board, company, chart and landing", () => {
  it("preserves quote changes while using matching session totals", () => {
    const [row] = prepareMarketRows([quote()], { UZ0001: trades() });
    assert.equal(row.lastPrice, 120);
    assert.equal(row.changePercent, 20);
    assert.equal(row.stockVolume, 1234);
    assert.equal(row.stockQuantity, 10);
    assert.equal(row.stockTradeCount, 3);
    assert.equal(row.vwap, 123.4);
    assert.equal(row.tone, "good");
  });

  it("uses the newest previous close rather than publishing a two-session move", () => {
    const [row] = prepareMarketRows([quote({ last_price: 37200, close_price: 31000,
      last_trade_date: "2026-08-06", close_date: "2026-08-05" })], {
      UZ0001: trades({ close_price: 37200, open_price: 37200, high_price: 37200, low_price: 37200 }),
    });
    assert.equal(row.changePercent, 0);
    assert.equal(row.closePrice, 37200);
    assert.equal(row.close_price, 37200);
    assert.equal(row.last_trade_date, "2026-08-14");
    assert.equal(row.tone, "neutral");
  });

  it("keeps an older negotiated deal visible without contaminating newer auction totals", () => {
    const [row] = prepareMarketRows([quote()], { UZ0001: trades({
      trade_date: "20260807", block_value: 50000, block_qty: 1000, block_count: 1,
    }) });
    assert.equal(row.stockVolume, 240);
    assert.equal(row.stockTradeCount, 1);
    assert.equal(row.ts, undefined);
    assert.deepEqual(row.nego, { value: 50000, qty: 1000, count: 1, date: "20260807" });
  });

  it("does not turn a negotiated-only day into a new auction session", () => {
    const [row] = prepareMarketRows([quote({ last_trade_date: "2026-08-13" })], {
      UZ0001: trades({ total_value: 0, total_qty: 0, trade_count: 0,
        close_price: 55, block_value: 55000, block_qty: 1000, block_count: 1 }),
    });
    assert.equal(row.lastPrice, 120);
    assert.equal(row.last_trade_date, "2026-08-13");
    assert.equal(row.stockVolume, 240);
    assert.equal(row.nego.value, 55000);
  });

  it("does not publish a stale quote change when newer trades have no usable price", () => {
    const [row] = prepareMarketRows([quote({ last_trade_date: "2026-08-13" })], {
      UZ0001: trades({ avg_price: null, vwap: null, close_price: null }),
    });
    assert.equal(row.changeValue, null);
    assert.equal(row.changePercent, null);
    assert.equal(row.stockVolume, 1234);
    assert.equal(row.tone, "neutral");
  });

  it("uses the board-wide latest session and accepts lowercase ISINs", () => {
    const [row] = prepareMarketRows([quote({ isin: "uz0001", last_trade_date: "2026-08-12" })], {
      UZ0001: trades({ trade_date: "20260813", close_price: 160 }),
      UZ0002: trades(),
    });
    assert.equal(row.stockVolume, 1234);
    assert.equal(row.lastPrice, 120, "an older statistic must not restate the latest session price");
  });

  it("handles missing statistics and empty inputs", () => {
    assert.deepEqual(prepareMarketRows(undefined), []);
    assert.deepEqual(prepareMarketRows(null, null), []);
    const [row] = prepareMarketRows([quote({ last_price: null })]);
    assert.equal(row.changeValue, null);
    assert.equal(row.changePercent, null);
    assert.equal(row.stockVolume, 240);
  });

  it("leaves source snapshots unchanged so all callers can safely share them", () => {
    const source = Object.freeze(quote());
    const stats = Object.freeze(trades());
    const rows = Object.freeze([source]);
    const map = Object.freeze({ UZ0001: stats });
    const first = prepareMarketRows(rows, map);
    const second = prepareMarketRows(rows, map);
    assert.deepEqual(first, second);
    assert.notEqual(first[0], source);
    assert.equal(source.volume, 240);
    assert.equal(source.ts, undefined);
  });
});
