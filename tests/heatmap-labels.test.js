import {test} from 'node:test';
import assert from 'node:assert/strict';
import {heatmapTileLabels} from '../frontend/src/features/market/tileLabels.js';

test('SANE ytd +82.66% fits alongside its ticker in a short, wide tile', () => {
  const layout = heatmapTileLabels(270, 24, 'SANE', '+82,66%');
  assert.equal(layout.flow, 'row');
  assert.equal(layout.showTicker, true);
  assert.equal(layout.showPercent, true);
  assert.ok(layout.percentSize >= 8);
});

test('KSCM ytd +58.82% fits in a narrow, tall tile without a logo', () => {
  const layout = heatmapTileLabels(44, 150, 'KSCM', '+58,82%');
  assert.equal(layout.flow, 'column');
  assert.equal(layout.showPercent, true);
  assert.ok(layout.percentSize >= 8);
  assert.ok(layout.percentSize * 7 * .62 <= 44 - 2 * (layout.padding + 1));
});

test('micro tiles gain labels when enlarged, while unreadable text stays hidden', () => {
  const small = heatmapTileLabels(12, 18, 'BECM', '+58,21%');
  assert.equal(small.showTicker, false);
  assert.equal(small.showPercent, false);
  const enlarged = heatmapTileLabels(96, 144, 'BECM', '+58,21%');
  assert.equal(enlarged.showTicker, true);
  assert.equal(enlarged.showPercent, true);
});

test('long changes and unavailable values fit using their actual formatted text', () => {
  const large = heatmapTileLabels(90, 60, 'UZPN', '+1 748,76%');
  assert.equal(large.showPercent, true);
  assert.ok(large.percentSize * 10 * .62 <= 90 - 2 * (large.padding + 1));
  assert.equal(heatmapTileLabels(44, 150, 'SANE', '—').showPercent, true);
});
