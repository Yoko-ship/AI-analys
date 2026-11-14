import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {balanceComposition as compose} from '../frontend/src/features/company/financialBalanceChart.js';

const reports = JSON.parse(readFileSync('e2e/fixtures/hmkb-recent-reports.json', 'utf8'));
const period = '2026-09-30';
const balanceComposition = (rows, key, end = key, context = {scope: 'separate', standard: 'NSBU'}) => compose(rows, key, end, context);
const row = (metric_id, value, quality = 'valid', unit = 'UZS_thousand') => ({
  id: metric_id, metric_id, label: metric_id, kind: 'stock', source_form: 'F1', unit,
  cells: {[period]: {value, quality, source_form: 'F1', source_version: 'report-1', period_end: period, scope: 'separate', currency: 'UZS', unit_scale: '1000'}},
});

test('HMKB balance pies use net loans once and published funding totals', () => {
  const {assets, funding} = balanceComposition(reports.rows, period);
  assert.equal(assets.reason, null);
  assert.equal(assets.total, 44389278550);
  assert.ok(assets.rows.some(row => row.metric_id === 'loans_leases_net' && row.value === 30908613408));
  assert.ok(!assets.rows.some(row => ['loans_gross', 'leases_gross', 'loan_lease_allowance', 'total_assets'].includes(row.metric_id)));
  assert.equal(assets.rows.reduce((sum, row) => sum + row.value, 0), assets.total);
  assert.equal(funding.reason, null);
  assert.deepEqual(funding.rows.map(row => row.value), [36204146303, 8185132247]);
  assert.equal(funding.total, 44389278550);
});

test('asset sections take precedence over their nested detail rows', () => {
  const rows = [row('total_assets', '100'), row('noncurrent_assets', '60'), row('current_assets', '40'),
    row('ppe', '50'), row('inventory', '30'), row('cash', '10')];
  const {assets} = balanceComposition(rows, period);
  assert.equal(assets.reason, null);
  assert.deepEqual(assets.rows.map(row => row.metric_id), ['noncurrent_assets', 'current_assets']);
  rows[1].cells[period].value = '80';
  assert.equal(balanceComposition(rows, period).assets.reason, 'asset_sections');
  rows[1].cells[period].value = '50';
  assert.equal(balanceComposition(rows, period).assets.reason, 'asset_sections');
});

test('balance pies reject duplicate readings and conflicting source contexts', () => {
  const assets = row('total_assets', '100');
  const liabilities = row('total_liabilities', '80');
  const equity = row('total_equity', '20');
  for (const [key, value] of Object.entries({source_form: 'F2', source_version: 'other', period_end: '2025-12-31', scope: 'consolidated', currency: 'USD', unit_scale: '1'})) {
    const other = {...equity, cells: {[period]: {...equity.cells[period], [key]: value}}};
    assert.equal(balanceComposition([assets, liabilities, other], period).funding.reason, 'source', key);
  }
  assert.equal(balanceComposition([assets, liabilities, equity, row('total_equity', '21')], period).funding.reason, 'source');
  assert.equal(balanceComposition([assets, row('ppe', '20'), row('ppe', '21')], period).assets.reason, 'source');
});

test('unavailable, negative and incompatible funding values keep their reported readings without pie slices', () => {
  for (const [value, quality, unit, reason] of [
    [null, 'missing', 'UZS_thousand', 'missing'],
    ['20', 'blocked', 'UZS_thousand', 'missing'],
    ['-20', 'warn', 'UZS_thousand', 'negative'],
    ['20', 'valid', 'UZS', 'units'],
  ]) {
    const {funding} = balanceComposition([row('total_assets', '80'), row('total_liabilities', '80'), row('total_equity', value, quality, unit)], period);
    assert.equal(funding.reason, reason);
    assert.equal(funding.total, null);
    assert.equal(funding.rows[1].value, quality === 'blocked' ? null : value == null ? null : Number(value));
  }
  const {funding} = balanceComposition([row('total_assets', '80'), row('total_liabilities', '80'), row('total_equity', '0')], period);
  assert.equal(funding.reason, null);
  assert.equal(funding.rows[1].value, 0);
  assert.equal(balanceComposition([row('total_assets', '0'), row('total_liabilities', '0'), row('total_equity', '0')], period).funding.reason, 'zero');
});

test('funding needs a published assets total and reconciles in the same known unit', () => {
  const liabilities = row('total_liabilities', '80');
  const equity = row('total_equity', '30');
  for (const [rows, reason] of [
    [[liabilities, equity], 'missing'],
    [[row('total_assets', '100'), liabilities, equity], 'unreconciled'],
    [[row('total_assets', '120'), liabilities, equity], 'unreconciled'],
    [[row('total_assets', '110'), liabilities, {...equity, unit: undefined}], 'units'],
    [[row('total_assets', '110', 'valid', 'shares'), {...liabilities, unit: 'shares'}, {...equity, unit: 'shares'}], 'units'],
  ]) {
    const {funding} = balanceComposition(rows, period);
    assert.equal(funding.reason, reason);
    assert.equal(funding.total, null);
  }
  assert.equal(balanceComposition([row('total_assets', '100'), {...row('ppe', '20'), unit: undefined}], period).assets.reason, 'units');
});

test('asset pies require a published total and reject invalid components without inventing totals', () => {
  assert.equal(balanceComposition([row('ppe', '20')], period).assets.reason, 'missing');
  assert.equal(balanceComposition([row('total_assets', '100'), row('ppe', '-1')], period).assets.reason, 'negative');
  assert.equal(balanceComposition([row('total_assets', '100'), row('ppe', '101')], period).assets.reason, 'inconsistent');
  const {assets} = balanceComposition([row('total_assets', '100'), row('ppe', '20'), row('cash', '60', 'blocked')], period);
  assert.equal(assets.reason, 'missing');
  assert.equal(assets.total, null);
  assert.ok(!assets.rows.some(row => row.metric_id === 'other_assets_difference'));
  const absent = balanceComposition([row('total_assets', '100'), row('ppe', '20'), {...row('cash', '60'), cells: {}}], period).assets;
  assert.equal(absent.reason, 'missing');
  assert.equal(absent.total, null);
  assert.ok(!absent.rows.some(row => row.metric_id === 'other_assets_difference'));
});

test('balance breakdown rejects blocked duplicates and unverified report context', () => {
  const assets = row('total_assets', '100');
  const equity = row('total_equity', '20');
  const rows = [assets, row('total_liabilities', '80'), equity];
  assert.equal(balanceComposition([...rows, row('total_assets', '90', 'blocked')], period).funding.reason, 'source');
  assert.equal(balanceComposition([assets, row('ppe', '20'), row('ppe', '30', 'blocked')], period).assets.reason, 'source');
  for (const context of [{}, {scope:'unknown',standard:'NSBU'}, {scope:'separate',standard:'IFRS'}, {scope:'consolidated',standard:'NSBU'}]) {
    assert.equal(balanceComposition(rows, period, period, context).funding.reason, 'source');
  }
});

test('decimal statement values do not create false reconciliation errors', () => {
  const {assets} = balanceComposition([row('total_assets', '0.3'), row('noncurrent_assets', '0.1'), row('current_assets', '0.2')], period);
  assert.equal(assets.reason, null);
  assert.equal(assets.rows.length, 2);
});
