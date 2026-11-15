import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {balanceComposition as compose} from '../frontend/src/features/company/financialBalanceChart.js';

const reports = JSON.parse(readFileSync('e2e/fixtures/hmkb-recent-reports.json', 'utf8'));
const period = '2026-09-30';
const fxEvidence = {currency: 'USD', as_of: period, effective_date: period, basis: 'period_end_presentation',
  source_url: `https://cbu.uz/ru/arkhiv-kursov-valyut/json/all/${period}/`};
const balanceComposition = (rows, key, end = key, context = {scope: 'separate', standard: 'NSBU'}) =>
  compose(rows, key, end, {ticker: 'HMKB', issuerId: '8', ...context});
const row = (metric_id, value, quality = 'valid', unit = 'UZS_thousand') => ({
  id: metric_id, metric_id, label: metric_id, kind: 'stock', source_form: 'F1', unit,
  source_code: {ppe: '012', inventory: '140', cash: '320', receivables: '210', total_assets: '400',
    noncurrent_assets: '130', current_assets: '390', total_liabilities: '770', total_equity: '480'}[metric_id],
  cells: {[period]: {value, quality, source_form: 'F1', source_version: 'report-1', period_end: period, scope: 'separate', currency: 'UZS', unit_scale: '1000',
    ...(unit === 'UZS' && {raw_value: Number(value) / 1000})}},
});

test('balances reject other issuers, conflicting filing URLs and misidentified totals', () => {
  const rows = [row('total_assets', 100), row('total_liabilities', 80), row('total_equity', 20)];
  for (const conflict of [{issuer_id: '9'}, {ticker: 'OTHER'}, {source_url: 'https://example.test/another'}, {source_code: '470'}]) {
    const inputs = structuredClone(rows);
    for (const input of inputs) input.cells[period].source_url = 'https://example.test/report';
    Object.assign(inputs[2].cells[period], conflict);
    assert.equal(balanceComposition(inputs, period).funding.reason, 'source');
  }
  const sections = [rows[0], row('noncurrent_assets', 60), row('current_assets', 40)];
  sections[1].source_code = '120';
  assert.equal(balanceComposition(sections, period).assets.reason, 'source');
});

test('HMKB balance pies use net loans once and published funding totals', () => {
  // OpenInfo bank report 1306, 2026-09-30, HMKB (issuer 8), separate NSBU, UZS thousands.
  // Registry BANK_BS lines 1 (cash), 2 (due from CBU), 3 (due from other banks),
  // 5в (net investments), 7г (net loans/leases), 10 (net PPE), 11 (accrued interest).
  // Lines 7а, 7б and 7в are gross loans, gross leases and the allowance within 7г.
  const filedAssets = [['cash', '1', 2256418896], ['central_bank_balances', '2', 1288812892],
    ['bank_balances', '3', 2259057543], ['investments_net', '5в', 352450377],
    ['loans_leases_net', '7г', 30908613408], ['ppe', '10', 1236365217], ['interest_receivables', '11', 458105227]];
  assert.equal(reports.issuer_id, '8');
  assert.equal(reports.scope, 'separate');
  assert.equal(reports.standard, 'NSBU');
  for (const [metric, code, value] of [...filedAssets, ['total_assets', '14', 44389278550],
    ['total_liabilities', '25', 36204146303], ['total_equity', '30', 8185132247]]) {
    const cell = reports.rows.find(row => row.metric_id === metric).cells[period];
    assert.deepEqual([cell.source_form, cell.source_code, cell.period_end, cell.currency, cell.unit_scale, Number(cell.value)],
      ['BANK_BS', code, period, 'UZS', '1000', value]);
    assert.match(cell.source_url, /report_id=1306(?:&|$)/);
  }
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

test('asset details replace section slices while section totals still reconcile', () => {
  const rows = [row('total_assets', '100'), row('noncurrent_assets', '60'), row('current_assets', '40'),
    row('ppe', '50'), row('inventory', '30'), row('cash', '10')];
  const {assets} = balanceComposition(rows, period);
  assert.equal(assets.reason, null);
  assert.deepEqual(assets.rows.map(row => row.metric_id), ['ppe', 'inventory', 'cash', 'unclassified_assets']);
  assert.equal(assets.rows.at(-1).value, 10);
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
    const {funding} = balanceComposition([assets, liabilities, other], period);
    assert.equal(funding.reason, 'source', key);
    assert.equal(funding.rows[1].value, null, key);
  }
  const duplicate = balanceComposition([assets, liabilities, equity, row('total_equity', '21')], period).funding;
  assert.equal(duplicate.reason, 'source');
  assert.equal(duplicate.rows[1].value, null);
  assert.equal(balanceComposition([assets, row('ppe', '20'), row('ppe', '21')], period).assets.reason, 'source');
});

test('duplicate detection applies only to observations for the selected period', () => {
  const older = row('total_equity', 15);
  older.cells = {'2025': {...older.cells[period], period_end: '2025-12-31'}};
  const current = [row('total_assets', 100), row('total_liabilities', 80), row('total_equity', 20)];
  const {funding} = balanceComposition([...current, older], period);
  assert.equal(funding.reason, null);
  assert.equal(funding.rows[1].value, 20);
});

test('UZAL 2025 Form 1 uses the filed section and funding totals', () => {
  const filing = JSON.parse(readFileSync('tests/fixtures/openinfo/uzal_2025_complete_rows.json', 'utf8'));
  // financial_columns/registry.py, F1: sections 130+390=400, funding 770+480=400.
  const readings = [
    ['noncurrent_assets', '130', 6572615509], ['current_assets', '390', 927967315],
    ['total_assets', '400', 7500582824], ['total_liabilities', '770', 6401242501.7],
    ['total_equity', '480', 1099340322.3],
  ];
  const form = filing.sheets.find(sheet => sheet.source_rows.some(({cells}) => cells[1] === '400' && cells[3] === 7500582824));
  const rows = readings.map(([metric, code, amount]) => {
    assert.ok(form.source_rows.some(({cells}) => cells[1] === code && cells[3] === amount), code);
    return {...row(metric, amount), source_code: code, ticker: 'UZAL', cells: {'2025': {
      ...row(metric, amount).cells[period], raw_value: amount, period_end: filing.reporting_date, source_url: filing.source_url, source_version: undefined,
    }}};
  });
  const {assets, funding} = compose(rows, '2025', '2025-12-31', {scope: 'separate', standard: 'NSBU', ticker: 'UZAL', issuerId: 'UZAL'});
  assert.equal(assets.total, 7500582824);
  assert.equal(funding.total, assets.total);
  assert.equal(assets.rows.length, 2);

  const assetMetrics = { '012': 'ppe', '022': 'intangibles', '030': 'long_term_investments',
    '090': 'equipment_installation', '100': 'construction_in_progress', '110': 'long_term_receivables',
    '120': 'long_term_deferred_expenses', '140': 'inventory', '190': 'prepaid_expenses',
    '200': 'deferred_expenses', '210': 'receivables', '320': 'cash',
    '370': 'short_term_investments', '380': 'other_current_assets'};
  const assetSource = form.source_rows.slice(0, form.source_rows.findIndex(({cells}) => cells[1] === '400'));
  const details = assetSource.filter(({cells}) => assetMetrics[cells[1]]).map(({cells}) => ({
    ...structuredClone(rows[0]), id: `F1:${cells[1]}`, metric_id: assetMetrics[cells[1]], source_code: cells[1],
    cells: {'2025': {...rows[0].cells['2025'], value: cells[3], raw_value: cells[3]}},
  }));
  const detailed = compose([...rows, ...details], '2025', '2025-12-31', {scope: 'separate', standard: 'NSBU', ticker: 'UZAL', issuerId: 'UZAL'}).assets;
  assert.equal(detailed.reason, null);
  assert.equal(detailed.rows.length, 14);
  assert.equal(detailed.rows.find(row => row.metric_id === 'long_term_investments').value, 511475.7);
  assert.ok(!detailed.rows.some(row => ['noncurrent_assets', 'current_assets', 'unclassified_assets'].includes(row.metric_id)));
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
  assert.ok(!assets.rows.some(row => row.metric_id === 'unclassified_assets'));
  const absent = balanceComposition([row('total_assets', '100'), row('ppe', '20'), {...row('cash', '60'), cells: {}}], period).assets;
  assert.equal(absent.reason, 'missing');
  assert.equal(absent.total, null);
  assert.ok(!absent.rows.some(row => row.metric_id === 'unclassified_assets'));
});

test('balance breakdown rejects blocked duplicates and unverified report context', () => {
  const assets = row('total_assets', '100');
  const equity = row('total_equity', '20');
  const rows = [assets, row('total_liabilities', '80'), equity];
  for (const conflict of [{scope: 'consolidated'}, {standard: 'MSFO'}]) {
    const funding = balanceComposition([assets, rows[1], {...equity, ...conflict}], period).funding;
    assert.equal(funding.reason, 'source');
    assert.equal(funding.rows[1].value, null);
  }
  assert.equal(balanceComposition([...rows, row('total_assets', '90', 'blocked')], period).funding.reason, 'source');
  assert.equal(balanceComposition([assets, row('ppe', '20'), row('ppe', '30', 'blocked')], period).assets.reason, 'source');
  for (const context of [{}, {scope:'unknown',standard:'NSBU'}, {scope:'separate',standard:'IFRS'}, {scope:'consolidated',standard:'NSBU'}]) {
    assert.equal(balanceComposition(rows, period, period, context).funding.reason, 'source');
  }
});

test('a bank balance without its filed net-loan line withholds the asset pie', () => {
  const rows = reports.rows.filter(row => row.metric_id !== 'loans_leases_net');
  const {assets, funding} = balanceComposition(rows, period);
  assert.equal(assets.reason, 'missing');
  assert.equal(assets.total, null);
  assert.equal(funding.reason, null);
});

test('decimal statement values do not create false reconciliation errors', () => {
  const {assets} = balanceComposition([row('total_assets', '0.3'), row('noncurrent_assets', '0.1'), row('current_assets', '0.2')], period);
  assert.equal(assets.reason, null);
  assert.equal(assets.rows.length, 2);
});

test('finite balance readings cannot produce an overflowing aggregate', () => {
  const total = row('total_assets', 1e308);
  const {assets, funding} = balanceComposition([total, row('total_liabilities', 1e308), row('total_equity', 1e308),
    row('noncurrent_assets', 1e308), row('current_assets', 1e308)], period);
  for (const panel of [assets, funding]) {
    assert.equal(panel.total, null);
    assert.ok(panel.reason);
  }
});

test('invalid source readings stay hidden alongside missing inputs or incompatible units', () => {
  const total = row('total_assets', '100');
  const stale = row('total_equity', '20');
  stale.cells[period].period_end = '2024-12-31';
  for (const liabilities of [[], [row('total_liabilities', '80', 'valid', 'UZS')]]) {
    assert.equal(balanceComposition([total, ...liabilities, stale], period).funding.rows[1].value, null);
  }
});

test('source currency and scale must substantiate the displayed amount', () => {
  const funding = metadata => balanceComposition([
    row('total_assets', '100'), row('total_liabilities', '80'), row('total_equity', '20'),
  ].map(row => ({...row, cells: {[period]: {...row.cells[period], ...metadata(Number(row.cells[period].value))}}})), period).funding;
  assert.equal(funding(() => ({currency: 'USD'})).reason, 'source');
  assert.equal(funding(value => ({unit_scale: '1', raw_value: value})).reason, 'source');
  assert.equal(funding(value => ({unit_scale: '1000000', raw_value: value / 1000})).reason, null);
  assert.equal(funding(value => ({currency: 'USD', raw_value: value / 10000,
    fx: {currency: 'USD', as_of: period, rate: 10000}})).reason, 'source');
  assert.equal(funding(value => ({currency: 'USD', raw_value: value / 10000,
    fx: {...fxEvidence, rate: 10000}})).reason, null);
  assert.equal(funding(value => ({currency: 'USD', raw_value: value / 10000,
    fx: {...fxEvidence, rate: 10000, source_url: 'https://example.test/rate'}})).reason, 'source');
});

test('matching totals cannot hide different FX rates or filing versions', () => {
  const converted = (metric, raw, rate) => {
    const reading = row(metric, raw * rate);
    Object.assign(reading.cells[period], {raw_value: raw, currency: 'USD', fx: {...fxEvidence, rate}});
    return reading;
  };
  const mixedRates = balanceComposition([
    converted('total_assets', 100, 10), converted('total_liabilities', 80, 9), converted('total_equity', 20, 14),
  ], period).funding;
  assert.equal(mixedRates.reason, 'source');
  assert.equal(mixedRates.total, null);
  assert.ok(mixedRates.rows.every(reading => reading.value == null));

  const total = row('total_assets', 100);
  const equity = row('total_equity', 20);
  equity.cells[period].source_version = 'another-filing';
  for (const liabilities of [[], [row('total_liabilities', 80, 'valid', 'UZS')]]) {
    const funding = balanceComposition([total, ...liabilities, equity], period).funding;
    assert.equal(funding.reason, 'source');
    assert.equal(funding.rows[1].value, null);
  }
});

test('asset components follow the selected source form and omit overlapping sublines', () => {
  const {assets} = balanceComposition([row('total_assets', 100), row('cash', 20), row('bank_balances', 15),
    row('receivables', 30), row('interest_receivables', 10)], period);
  assert.equal(assets.reason, null);
  assert.deepEqual(assets.rows.map(row => [row.metric_id, row.value]), [['receivables',30],['cash',20],['unclassified_assets',50]]);
  const incorrect = {...row('cash', 20), source_code: '340'};
  assert.equal(balanceComposition([row('total_assets', 100), incorrect], period).assets.reason, 'source');
});

test('blank and nonnumeric amounts do not become zero equity', () => {
  for (const invalid of [' ', true, []]) {
    const equity = row('total_equity', invalid);
    equity.cells[period].raw_value = invalid;
    const {funding} = balanceComposition([row('total_assets', 100), row('total_liabilities', 100), equity], period);
    assert.equal(funding.reason, 'missing');
    assert.equal(funding.rows[1].value, null);
  }
});
