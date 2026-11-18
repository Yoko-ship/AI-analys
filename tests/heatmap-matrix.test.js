import {test} from 'node:test';
import assert from 'node:assert/strict';
import {capitalizationTier, matchesCapitalization, matrixLayout} from '../frontend/src/features/market/heatmapMatrix.js';

test('capitalization tiers partition strict trillion thresholds without guessing unknown values', () => {
  for (const [cap, tier] of [[1, 'under1'], [1e12, 'under1'], [1e12 + 1, '1to5'], [5e12, '1to5'],
    [5e12 + 1, '5to10'], [10e12, '5to10'], [10e12 + 1, '10to25'], [25e12, '10to25'], [25e12 + 1, 'over25'],
    [null, 'unknown'], [undefined, 'unknown'], [NaN, 'unknown'], [Infinity, 'unknown'], [0, 'unknown'], [-1, 'unknown']]) {
    assert.equal(capitalizationTier(cap), tier);
    assert.equal(matchesCapitalization({marketCap: cap}, 1e12), Number.isFinite(cap) && cap > 1e12);
    assert.equal(matchesCapitalization({marketCap: cap}, 0), true);
  }
});

test('matrix keeps each security once, equal sized and inside its industry and tier across viewport widths', () => {
  const rows = Array.from({length: 31}, (_, i) => ({ticker: `T${i}`, marketCap: i === 30 ? null : 2e12}));
  const sections = [{sector: 'finance', groups: [{id: 'banks', rows}]}];
  for (const width of [320, 1440, 2880]) {
    const layout = matrixLayout(sections, width);
    const stocks = layout.sectors.flatMap(s => s.stocks);
    assert.equal(stocks.length, rows.length);
    assert.equal(new Set(stocks.map(s => s.row.ticker)).size, rows.length);
    assert.equal(new Set(stocks.map(s => `${s.w}:${s.h}`)).size, 1);
    for (const stock of stocks) {
      const column = layout.columns.find(c => c.id === stock.tier);
      assert.ok(stock.x >= column.x && stock.x + stock.w <= column.x + column.w);
      assert.ok(stock.y >= 0 && stock.y + stock.h <= layout.height);
    }
  }
  assert.equal(matrixLayout([], 320).sectors.length, 0);
});
