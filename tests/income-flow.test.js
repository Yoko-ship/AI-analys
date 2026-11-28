import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {incomeFlow} from '../frontend/src/features/company/incomeFlow.js';

const reports = JSON.parse(readFileSync('tests/fixtures/financial_columns/uzmk_income_history.json', 'utf8'));

test('UZMK filed income diagrams retain material source discrepancies without correcting the amounts', () => {
  for (const [period, metric, amount, difference] of [
    ['2025', 'net_income', 284061318, 17962052],
    ['2026-09-30', 'gross_profit', 942389976, -640620667],
  ]) {
    const rows = reports.annual.rows;
    const before = structuredClone(rows);
    const flow = incomeFlow(rows, period);
    assert.ok(flow, period);
    assert.equal(flow.totals.find(line => line.id === metric).value, amount);
    assert.ok(flow.bridges.flat().some(line => line.id === 'difference' && line.value === difference));
    assert.equal(flow.issues.length, 1);
    assert.equal(flow.issues[0].severity, 'blocked');
    assert.match(flow.issues[0].source_url, /new-api.openinfo.uz/);
    assert.deepEqual(rows, before);
  }
  assert.deepEqual(incomeFlow(reports.annual.rows, '2024').issues, []);
});

test('an income diagram never promotes held, conflicting or untraceable amounts to reported figures', () => {
  for (const reason of ['UNDER_REVIEW', 'CONFLICTING_SOURCE_VALUES', 'AMOUNT_UNRESOLVED']) {
    const rows = structuredClone(reports.annual.rows);
    rows.find(row => row.metric_id === 'revenue').cells['2026-09-30'].reason = reason;
    assert.equal(incomeFlow(rows, '2026-09-30'), null, reason);
  }
  const rows = structuredClone(reports.annual.rows);
  delete rows.find(row => row.metric_id === 'revenue').cells['2026-09-30'].source_url;
  assert.equal(incomeFlow(rows, '2026-09-30'), null);
  assert.equal(incomeFlow(reports.quarter.rows, '2026-09-30'), null);
  assert.ok(incomeFlow(reports.quarter.rows, '2026-06-30'));
});
