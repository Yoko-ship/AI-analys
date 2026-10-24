import test from 'node:test';
import assert from 'node:assert/strict';
import { financialDisplaySeries } from '../frontend/src/lib/financialDisplayScale.js';

test('UZTL monetary history displays billions without changing ratios, source data or per-share values', () => {
  const source = {
    net_revenue: { money: true, unit: 'UZS', values: { 2025: 10512797471000, 2024: 8964716518000 } },
    net_profit: { money: true, unit: 'UZS', values: { 2025: 590906080000, 2024: null, 2023: 0 } },
    operating_expenses: { money: true, unit: 'UZS', values: { 2025: -2591539560000 } },
    roa: { money: false, unit: '%', values: { 2025: 4.37 } },
    debt_to_equity: { money: false, values: { 2025: 3.4644 } },
    eps: { money: true, unit: 'UZS_per_share', values: { 2025: 20.5 } },
  };
  const original = structuredClone(source);
  const shown = financialDisplaySeries(source);
  assert.equal(shown.net_revenue.values[2025], 10512.797471);
  assert.equal(shown.net_profit.values[2025], 590.90608);
  assert.equal(shown.operating_expenses.values[2025], -2591.53956);
  assert.equal(shown.net_profit.values[2024], null);
  assert.equal(shown.net_profit.values[2023], 0);
  assert.equal(shown.net_profit.unit, 'UZS_billion');
  for (const key of ['roa', 'debt_to_equity', 'eps']) assert.deepEqual(shown[key], source[key]);
  assert.deepEqual(source, original);
  assert.deepEqual(financialDisplaySeries(shown), shown); // Already scaled values stay scaled once.
  assert.deepEqual(financialDisplaySeries({ revenue: { money: true, unit: 'USD', values: { 2025: 5000 } } }),
    { revenue: { money: true, unit: 'USD', values: { 2025: 5000 } } });
});
