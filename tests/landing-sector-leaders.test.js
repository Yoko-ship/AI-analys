import assert from 'node:assert/strict';
import { test } from 'node:test';
import { selectSectorLeaders } from '../frontend/src/features/landing/sectorLeaders.js';

const sectors = ['finance', 'manufacturing', 'telecom'];
const stock = (ticker, volume, extra = {}) => ({ ticker, type: 'stock', last_trade_date: '2026-11-06', volume, ...extra });
const market = (marketRows, extra = {}) => ({
  marketRows,
  securitiesMap: { HMKB: { sector: 'finance' }, URTS: { sector: 'finance' }, GRBK: { sector: 'finance' },
    DRBK: { sector: 'finance' }, UZMK: { sector: 'manufacturing' }, BIOK: { sector: 'manufacturing' },
    UZTL: { sector: 'telecom' }, UZTLP: { sector: 'telecom' } },
  ...extra,
});
const tickers = data => selectSectorLeaders(data, sectors).map(row => row.ticker);

test('selects one turnover leader per sector from the 6 November market data', () => {
  const rows = [stock('HMKB', 658856138.48), stock('URTS', 372249911.22), stock('UZMK', 143424137.79),
    stock('BIOK', 69267516.21), stock('UZTL', 273964339.62), stock('UZTLP', 23745555.44)];
  assert.deepEqual(tickers(market(rows)), ['HMKB', 'UZMK', 'UZTL']);
  assert.deepEqual(tickers(market([...rows].reverse())), ['HMKB', 'UZMK', 'UZTL']);
});

test('does not promote historic turnover, undated quotes, bonds or missing activity', () => {
  const rows = [stock('HMKB', 100), stock('DRBK', 1e12, { last_trade_date: '2019-10-31' }),
    stock('GRBK', 1e11, { last_trade_date: null }), stock('UZMK', 0), stock('BIOK', Infinity),
    stock('UZTL', null), stock('UZTLP', -1), stock('BOND', 1e12, { type: 'bond', last_trade_date: '2026-11-09' })];
  assert.deepEqual(tickers(market(rows, { companies: [{ ticker: 'BOND', sector: 'finance' }] })), ['HMKB']);
  assert.deepEqual(tickers({}), []);
});

test('uses the common latest session and leaves inactive sectors without a pick', () => {
  const data = market([stock('HMKB', 100), stock('UZTL', 200, { last_trade_date: '2026-11-05' })]);
  assert.deepEqual(tickers(data), ['HMKB']);
  assert.deepEqual(tickers({ ...data, marketMeta: { trade_date: '20261109' } }), []);
});

test('breaks equal turnover by trade count, then ticker, independent of input order', () => {
  const rows = [stock('HMKB', 100, { trade_count: 2 }), stock('GRBK', 100, { trade_count: 4 }), stock('URTS', 100, { trade_count: 4 })];
  assert.deepEqual(tickers(market(rows)), ['GRBK']);
  assert.deepEqual(tickers(market([...rows].reverse())), ['GRBK']);
});

test('follows the catalog sector and falls back to company metadata when absent', () => {
  const data = market([stock('HMKB', 100), stock('UZMK', 200)], {
    securitiesMap: { HMKB: { sector: 'finance' } },
    companies: [{ ticker: 'HMKB', sector: 'other' }, { ticker: 'UZMK', sector: 'manufacturing' }],
  });
  assert.deepEqual(tickers(data), ['HMKB', 'UZMK']);
});

test('recomputes the winner from reconciled session totals as statistics arrive', () => {
  const data = market([stock('HMKB', 100), stock('GRBK', 50, { isin: 'UZ7037610001' })]);
  assert.deepEqual(tickers(data), ['HMKB']);
  const leaders = selectSectorLeaders({ ...data, marketTradeStats: {
    UZ7037610001: { trade_date: '20261106', total_value: 200, total_qty: 2, trade_count: 1 },
  } }, sectors);
  assert.deepEqual(leaders.map(row => row.ticker), ['GRBK']);
  assert.equal(leaders[0].turnover, 200);
  assert.equal(leaders[0].tradeDate, '20261106');
});

test('a later negotiated-only deal cannot relabel historic auction turnover as current', () => {
  const data = market([stock('HMKB', 100), stock('DRBK', 1e12, { isin: 'UZ7051550005', last_trade_date: '2019-10-31' })], {
    marketTradeStats: { UZ7051550005: { trade_date: '20261106', total_value: 0, total_qty: 0, trade_count: 0, block_value: 1e13 } },
  });
  assert.deepEqual(tickers(data), ['HMKB']);
});
