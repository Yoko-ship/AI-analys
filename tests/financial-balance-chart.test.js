import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {balanceComposition as compose} from '../frontend/src/features/company/financialBalanceChart.js';
import {filedBalance} from './fixtures/financial_columns/nsbu-balance.js';

const reports = JSON.parse(readFileSync('e2e/fixtures/hmkb-recent-reports.json', 'utf8'));
const period = '2026-09-30';
const fxEvidence = {currency: 'USD', as_of: period, effective_date: period, basis: 'period_end_presentation',
  source_url: `https://cbu.uz/ru/arkhiv-kursov-valyut/json/all/${period}/`};
const balanceComposition = (rows, key, end = key, context = {scope: 'separate', standard: 'NSBU'}) =>
  compose(rows, key, end, {ticker: 'HMKB', issuerId: '8', ...context});
const row = (metric_id, value, quality = 'valid', unit = 'UZS_thousand') => ({
  id: metric_id, metric_id, label: metric_id, kind: 'stock', source_form: 'F1', unit,
  source_code: {ppe: '012', inventory: '140', cash: '320', receivables: '210', total_assets: '400',
    noncurrent_assets: '130', current_assets: '390', total_liabilities: '770', total_equity: '480',
    share_capital: '410', share_premium: '420', reserve_capital: '430', treasury_shares: '440',
    retained_earnings: '450', target_receipts: '460', future_expense_reserves: '470'}[metric_id],
  cells: {[period]: {value, quality, source_form: 'F1', source_version: 'report-1', period_end: period, scope: 'separate', currency: 'UZS', unit_scale: '1000',
    ...(unit === 'UZS' && {raw_value: Number(value) / 1000})}},
});

const equityAmounts = shareCapital => ({share_capital: shareCapital, share_premium: 0, reserve_capital: 0,
  treasury_shares: 0, retained_earnings: 0, target_receipts: 0, future_expense_reserves: 0});

test('UZMK 2024 balance charts tolerate the reported +0.35 assets and +0.01 equity differences', () => {
  const totalAssets = 12776733776.92;
  // Constructed rows reproduce the reported differences in thousands of UZS.
  const totalEquity = 6800000000;
  const amounts = {
    total_assets: totalAssets, noncurrent_assets: 10000000000, current_assets: 2776733777.27,
    total_liabilities: totalAssets - totalEquity, total_equity: totalEquity,
    ...equityAmounts(totalEquity + 0.01),
  };
  const rows = Object.entries(amounts).map(([metric, amount]) => {
    const entry = row(metric, amount);
    entry.cells = {2024: {...entry.cells[period], period_end: '2024-12-31'}};
    return entry;
  });
  const {assets, equity} = compose(rows, '2024', '2024-12-31', {
    ticker: 'UZMK', issuerId: 'fixture:UZMK', scope: 'separate', standard: 'NSBU',
  });
  assert.deepEqual([assets.reason, assets.total, equity.reason, equity.total], [null, totalAssets, null, totalEquity]);
  assert.equal(assets.rows.find(row => row.metric_id === 'current_assets').value, amounts.current_assets);
  assert.equal(equity.rows.find(row => row.metric_id === 'share_capital').value, amounts.share_capital);
});

for (const [unit, multiplier] of [['UZS_thousand', 1], ['UZS', 1000]]) {
  for (const sign of [-1, 1]) test(`balance reconciles inclusively at one million UZS (${unit}, sign ${sign})`, () => {
    for (const delta of [999.99, 1000, 1000.01]) {
      const difference = sign * delta;
      const amounts = {total_assets: 12776733776.92, noncurrent_assets: 10000000000, current_assets: 2776733776.92 + difference,
        total_liabilities: 5976733776.92 + difference, total_equity: 6800000000, ...equityAmounts(6800000000 + difference)};
      const rows = Object.entries(amounts).map(([metric, value]) => row(metric, value * multiplier, 'valid', unit));
      const {assets, funding, equity} = balanceComposition(rows, period);
      for (const [panel, filed, reason] of [[assets, amounts.total_assets, 'asset_sections'],
        [funding, amounts.total_assets, 'unreconciled'], [equity, amounts.total_equity, 'equity_unreconciled']]) {
        if (delta <= 1000) {
          assert.equal(panel.reason, null, `${reason}, ${difference}`);
          assert.equal(panel.total, filed * multiplier);
          assert.ok(!panel.rows.some(row => row.metric_id === 'unclassified_assets'));
        } else {
          assert.equal(panel.reason, reason);
          assert.equal(panel.total, null);
          assert.ok(Math.abs(panel.comparison.difference / multiplier - difference) < 0.00001);
        }
      }
    }
  });
}

for (const ticker of ['UZAL', 'UZTL', 'KFSK']) test(`${ticker} equity composition uses the full filed capital section`, () => {
  const report = filedBalance(ticker);
  const {equity} = compose(report.chart_rows, '2025', '2025-12-31', {
    ticker, issuerId: report.issuer_id, scope: report.scope, standard: report.standard,
  });
  assert.equal(equity.reason, null);
  assert.equal(equity.total, report.rows.find(row => row.metric_id === 'total_equity').cells['2025'].value);
  assert.deepEqual(equity.rows.map(row => row.metric_id), [
    'share_capital', 'share_premium', 'reserve_capital', 'treasury_shares',
    'retained_earnings', 'target_receipts', 'future_expense_reserves',
  ]);
  assert.ok(Math.abs(equity.rows.reduce((sum, row) => sum + row.value, 0) - equity.total) < 0.000001);
});

test('equity composition validates source, units, complete rows and total independently of assets', () => {
  for (const [update, reason] of [
    [{value: null, raw_value: null, quality: 'missing'}, 'missing'],
    [{source_version: 'another-filing'}, 'source'],
    [{source_code: '580'}, 'source'],
    [{period_end: '2024-12-31'}, 'source'],
    [{value: -1, raw_value: -1}, 'negative'],
    [{value: 1, raw_value: 1}, 'equity_unreconciled'],
  ]) {
    const report = filedBalance('KFSK');
    Object.assign(report.rows.find(row => row.metric_id === 'retained_earnings').cells['2025'], update);
    const {equity, assets} = compose(report.rows, '2025', '2025-12-31', {
      ticker: 'KFSK', issuerId: report.issuer_id, scope: report.scope, standard: report.standard,
    });
    assert.equal(equity.reason, reason);
    assert.equal(equity.total, null);
    assert.equal(assets.reason, null);
  }
  for (const mutation of ['absent', 'duplicate', 'units', 'deduction', 'zero']) {
    const report = filedBalance('UZTL');
    const capital = report.rows.find(row => row.metric_id === 'share_capital');
    if (mutation === 'absent') report.rows.splice(report.rows.indexOf(capital), 1);
    if (mutation === 'duplicate') report.rows.push(structuredClone(capital));
    if (mutation === 'units') {
      capital.unit = 'UZS';
      capital.cells['2025'].value *= 1000;
    }
    if (mutation === 'deduction') {
      const treasury = report.rows.find(row => row.metric_id === 'treasury_shares').cells['2025'];
      const total = report.rows.find(row => row.metric_id === 'total_equity').cells['2025'];
      treasury.value = treasury.raw_value = 100;
      total.value = total.raw_value = total.value - 100;
    }
    if (mutation === 'zero') for (const row of report.rows) {
      if (Number(row.source_code) >= 410 && Number(row.source_code) <= 480)
        row.cells['2025'].value = row.cells['2025'].raw_value = 0;
    }
    const {equity} = compose(report.rows, '2025', '2025-12-31', {
      ticker: 'UZTL', issuerId: report.issuer_id, scope: report.scope, standard: report.standard,
    });
    assert.equal(equity.reason, {absent: 'missing', duplicate: 'source', units: 'units', deduction: 'deductions', zero: 'zero'}[mutation]);
    assert.equal(equity.total, null);
  }
});

test('bank equity uses top-level capital and reserves without double-counting subrows', () => {
  const bank = structuredClone(reports);
  const capital = bank.rows.find(row => row.metric_id === 'share_capital');
  const premium = structuredClone(capital);
  Object.assign(premium, {id: 'BANK_BS:27', metric_id: 'share_premium', source_code: '27'});
  // Reconcile this boundary fixture without pretending the absent source row was zero.
  const total = Number(bank.rows.find(row => row.metric_id === 'total_equity').cells[period].value);
  const subtotal = bank.rows.filter(row => ['share_capital', 'reserve_capital', 'retained_earnings'].includes(row.metric_id))
    .reduce((sum, row) => sum + Number(row.cells[period].value), 0);
  premium.cells = {[period]: {...capital.cells[period], source_code: '27', value: total - subtotal, raw_value: total - subtotal}};
  bank.rows.push(premium);
  const nested = structuredClone(capital);
  Object.assign(nested, {id: 'BANK_BS:26а', metric_id: 'ordinary_share_capital', source_code: '26а'});
  nested.cells[period].source_code = '26а';
  bank.rows.push(nested);
  const {equity} = balanceComposition(bank.rows, period);
  assert.equal(equity.reason, null);
  assert.equal(equity.total, total);
  assert.deepEqual(equity.rows.map(row => row.metric_id), ['share_capital', 'share_premium', 'reserve_capital', 'retained_earnings']);
  assert.equal(balanceComposition(reports.rows, period).equity.reason, 'missing');
});

for (const [ticker, total] of [['UZTL', 13530348888], ['KFSK', 642485365.03]]) {
  test(`${ticker} uses the shared balance chart with its own filed form and totals`, () => {
    const report = filedBalance(ticker);
    const {assets, funding} = compose(report.chart_rows, '2025', '2025-12-31', {
      ticker, issuerId: report.issuer_id, scope: report.scope, standard: report.standard,
    });
    for (const panel of [assets, funding]) {
      assert.equal(panel.reason, null);
      assert.equal(panel.total, total);
      assert.ok(Math.abs(panel.rows.reduce((sum, row) => sum + row.value, 0) - total) < 0.00001);
    }
    if (ticker === 'KFSK') {
      assert.deepEqual(funding.rows.map(row => [row.metric_id, row.value]), [
        ['nonreserve_liabilities', 126355416.5], ['insurance_reserves_net', 259436970.5], ['total_equity', 256692978.03],
      ]);
      assert.ok(assets.rows.some(row => row.metric_id === 'materials' && row.value === 447602.15));
      assert.ok(!assets.rows.some(row => ['work_in_progress', 'finished_goods', 'noncurrent_assets', 'current_assets'].includes(row.metric_id)));
    }
  });
}

test('insurance pies withhold missing, conflicting and unreconciled reserve readings', () => {
  for (const [update, reason] of [
    [{value: null, raw_value: null, quality: 'missing'}, 'missing'],
    [{value: -1, raw_value: -1}, 'negative'],
    [{source_code: '580'}, 'source'],
    [{source_version: 'another-filing'}, 'source'],
    [{value: 0, raw_value: 0}, 'unreconciled'],
  ]) {
    const report = filedBalance('KFSK');
    Object.assign(report.rows.find(row => row.metric_id === 'insurance_reserves_net').cells['2025'], update);
    const {funding} = compose(report.rows, '2025', '2025-12-31', {
      ticker: 'KFSK', issuerId: report.issuer_id, scope: 'separate', standard: 'NSBU',
    });
    assert.equal(funding.reason, reason);
    assert.equal(funding.total, null);
  }
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
  const rows = [row('total_assets', 10000), row('noncurrent_assets', 6000), row('current_assets', 4000),
    row('ppe', 5990), row('inventory', 3000), row('cash', 1000)];
  const {assets} = balanceComposition(rows, period);
  assert.equal(assets.reason, null);
  assert.deepEqual(assets.rows.map(row => row.metric_id), ['ppe', 'inventory', 'cash', 'unclassified_assets']);
  assert.equal(assets.rows.at(-1).value, 10);
  for (const [section, sum, difference] of [[8000, 12000, 2000], [4500, 8500, -1500]]) {
    rows[1].cells[period].value = section;
    const {assets} = balanceComposition(rows, period);
    assert.equal(assets.reason, 'asset_sections');
    const {rows: inputs, comparator, sum: calculated, difference: delta} = assets.comparison;
    assert.deepEqual(inputs.map(input => [input.metric_id, input.code, input.value]),
      [['noncurrent_assets', '130', section], ['current_assets', '390', 4000]]);
    assert.deepEqual([comparator.metric_id, comparator.code, comparator.value, comparator.unit, calculated, delta],
      ['total_assets', '400', 10000, 'UZS_thousand', sum, difference]);
  }
});

test('asset component and section overruns use the same inclusive tolerance', () => {
  const totalAndSections = [row('total_assets', 10000), row('noncurrent_assets', 6000), row('current_assets', 4000)];
  const atLimit = balanceComposition([...totalAndSections, row('ppe', 7000), row('inventory', 4000)], period).assets;
  assert.equal(atLimit.reason, null);
  assert.equal(atLimit.total, 10000);
  const sectionOverrun = balanceComposition([...totalAndSections, row('ppe', 7000.01), row('inventory', 2999.99)], period).assets;
  assert.equal(sectionOverrun.reason, 'asset_section_overrun');
});

test('asset components cannot exceed their own filed subtotals', () => {
  for (const [noncurrent, current] of [[8000,2000], [4000,6000], [10000,0]]) {
    const rows = [row('total_assets', 10000), row('noncurrent_assets', 6000), row('current_assets', 4000),
      row('ppe', noncurrent), row('inventory', current)];
    const {assets} = balanceComposition(rows, period);
    assert.equal(assets.reason, 'asset_section_overrun');
    assert.equal(assets.total, null);
    const {rows: inputs, comparator, sum, difference} = assets.comparison;
    const currentSection = current > 4000;
    assert.deepEqual(inputs.map(row => row.metric_id), [currentSection ? 'inventory' : 'ppe']);
    assert.equal(comparator.metric_id, currentSection ? 'current_assets' : 'noncurrent_assets');
    assert.equal(sum, currentSection ? current : noncurrent);
    assert.equal(difference, sum - (currentSection ? 4000 : 6000));
  }
  const insurance = filedBalance('KFSK');
  // Preserve the grand total while moving current assets into noncurrent assets.
  for (const [metric, delta] of [['ppe', 2000], ['cash', -2000]]) {
    const cell = insurance.rows.find(row => row.metric_id === metric).cells['2025'];
    cell.value += delta;
    cell.raw_value += delta;
  }
  const {assets} = compose(insurance.rows, '2025', '2025-12-31', {
    ticker: 'KFSK', issuerId: insurance.issuer_id, scope: insurance.scope, standard: insurance.standard,
  });
  assert.equal(assets.reason, 'asset_section_overrun');
  assert.equal(assets.total, null);
  assert.equal(assets.comparison.comparator.code, '130');
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

test('the tolerance cannot turn an all-zero funding or equity breakdown into a pie', () => {
  const {funding} = balanceComposition([row('total_assets', 100), row('total_liabilities', 0), row('total_equity', 0)], period);
  const {equity} = balanceComposition([row('total_equity', 100),
    ...Object.keys(equityAmounts(0)).map(metric => row(metric, 0))], period);
  for (const panel of [funding, equity]) {
    assert.ok(panel.reason);
    assert.equal(panel.total, null);
  }
});

test('funding needs a published assets total and reconciles in the same known unit', () => {
  const liabilities = row('total_liabilities', 8000);
  const equity = row('total_equity', 3000);
  for (const [rows, reason, difference] of [
    [[liabilities, equity], 'missing'],
    [[row('total_assets', 9500), liabilities, equity], 'unreconciled', 1500],
    [[row('total_assets', 12500), liabilities, equity], 'unreconciled', -1500],
    [[row('total_assets', 11000), liabilities, {...equity, unit: undefined}], 'units'],
    [[row('total_assets', 11000, 'valid', 'shares'), {...liabilities, unit: 'shares'}, {...equity, unit: 'shares'}], 'units'],
  ]) {
    const {funding} = balanceComposition(rows, period);
    assert.equal(funding.reason, reason);
    assert.equal(funding.total, null);
    if (difference === undefined) {
      assert.equal(funding.comparison, null);
      assert.ok(funding.unavailable.some(input => input.metric_id === (reason === 'missing' ? 'total_assets' : 'total_equity')));
    } else {
      const {rows: inputs, comparator, sum, difference: delta} = funding.comparison;
      assert.deepEqual(inputs.map(input => [input.form, input.code, input.value]), [['F1', '770', 8000], ['F1', '480', 3000]]);
      assert.deepEqual([comparator.form, comparator.code, comparator.value, sum, delta], ['F1', '400', 11000 - difference, 11000, difference]);
    }
  }
  assert.equal(balanceComposition([row('total_assets', '100'), {...row('ppe', '20'), unit: undefined}], period).assets.reason, 'units');
});

test('asset pies require a published total and reject invalid components without inventing totals', () => {
  assert.equal(balanceComposition([row('ppe', '20')], period).assets.reason, 'missing');
  assert.equal(balanceComposition([row('total_assets', '100'), row('ppe', '-1')], period).assets.reason, 'negative');
  const overrun = balanceComposition([row('total_assets', 10000), row('ppe', 11000.01)], period).assets;
  assert.equal(overrun.reason, 'inconsistent');
  assert.ok(Math.abs(overrun.comparison.difference - 1000.01) < 0.00000001);
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
