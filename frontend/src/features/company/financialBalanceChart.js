import {conversionFor, DISPLAY_SCALES, valueOf} from './financialSourceAmount.js';

// financial_columns/registry.py maps these official balance-sheet lines.
// F1 line 320 includes bank accounts. BANK_BS lines 1, 2 and 3 are separate.
// Bank net amounts replace their gross lines and allowances.
// INSURANCE_BS line 140 includes 150 and 160; use that subtotal only once.
const ASSET_LINES = {
  F1: {ppe: '012', intangibles: '022', long_term_investments: '030', equipment_installation: '090',
    construction_in_progress: '100', long_term_receivables: '110', long_term_deferred_expenses: '120',
    inventory: '140', prepaid_expenses: '190', deferred_expenses: '200', receivables: '210', cash: '320',
    short_term_investments: '370', other_current_assets: '380'},
  BANK_BS: {cash: '1', central_bank_balances: '2', bank_balances: '3', trading_assets_net: '4г',
    investments_net: '5в', loans_leases_net: '7г', ppe: '10', interest_receivables: '11'},
  INSURANCE_BS: {ppe: '012', intangibles: '022', long_term_investments: '030', equipment_installation: '090',
    construction_in_progress: '100', long_term_receivables: '110', long_term_deferred_expenses: '120',
    materials: '140', prepaid_expenses: '170', deferred_expenses: '180', receivables: '190', cash: '410',
    short_term_investments: '460', other_current_assets: '470'},
};
const BALANCE_LINES = {
  F1: {total_assets: '400', noncurrent_assets: '130', current_assets: '390', total_liabilities: '770', total_equity: '480'},
  BANK_BS: {total_assets: '14', total_liabilities: '25', total_equity: '30'},
  INSURANCE_BS: {total_assets: '490', noncurrent_assets: '130', current_assets: '480',
    nonreserve_liabilities: '1190', insurance_reserves_net: '720', total_equity: '570'},
};
// Only top-level equity lines belong in these slices. Bank share classes and
// reserve subrows are already included in their parent capital/reserve lines.
const EQUITY_LINES = {
  F1: {share_capital: '410', share_premium: '420', reserve_capital: '430', treasury_shares: '440',
    retained_earnings: '450', target_receipts: '460', future_expense_reserves: '470'},
  BANK_BS: {share_capital: '26', share_premium: '27', reserve_capital: '28', retained_earnings: '29'},
  INSURANCE_BS: {share_capital: '500', share_premium: '510', reserve_capital: '520', treasury_shares: '530',
    retained_earnings: '540', target_receipts: '550', future_expense_reserves: '560'},
};
const RECONCILIATION_TOLERANCE_UZS = 1_000_000;

function compare(rows, comparator) {
  const sum = rows.reduce((subtotal, row) => subtotal + row.value, 0);
  const difference = sum - comparator.value;
  const roundingError = Number.EPSILON * Math.max(Math.abs(comparator.value), Math.abs(sum)) * rows.length;
  const tolerance = RECONCILIATION_TOLERANCE_UZS / DISPLAY_SCALES.get(comparator.unit) + roundingError;
  return {rows, comparator, sum, difference, tolerance};
}

function composition(rows, comparator, mismatch = null) {
  const {value: total, unit, source} = comparator;
  const inputs = [comparator, ...rows];
  const sources = new Set(inputs.map(row => row.source).filter(Boolean));
  const panel = (reason = null, {unavailable = [], comparison = null} = {}) => ({
    rows: reason === 'source' ? rows.map(row => ({...row, value: null, unit: null})) : rows,
    total: reason ? null : total, unit, reason, comparison, unavailable,
  });
  const sourceIssues = inputs.filter(row => row.sourceError || (sources.size > 1 && row.source && row.source !== source));
  if (sourceIssues.length) return panel('source', {unavailable: sourceIssues});
  const invalidUnits = inputs.filter(row => row.unitError);
  if (invalidUnits.length) return panel('units', {unavailable: invalidUnits});
  const missing = inputs.filter(row => row.value == null);
  if (missing.length || !rows.length) return panel('missing', {unavailable: missing});
  const differingUnits = rows.filter(row => row.unit !== unit);
  if (differingUnits.length) return panel('units', {unavailable: differingUnits});
  if (inputs.some(row => row.value < 0)) return panel('negative');

  const comparison = compare(rows, comparator);
  if (!Number.isFinite(comparison.sum)) return panel('overflow');
  if (mismatch && (Math.abs(comparison.difference) > comparison.tolerance || (total > 0 && comparison.sum === 0))) {
    return panel(mismatch, {comparison});
  }
  if (total === 0) return panel('zero');
  if (comparison.difference > comparison.tolerance) return panel('inconsistent', {comparison});
  return panel();
}

export function balanceComposition(rows, period, periodEnd, {scope, standard, ticker, issuerId} = {}) {
  const knownContext = ticker && issuerId && ['separate', 'consolidated'].includes(scope) && standard === 'NSBU';
  const stocks = rows.filter(row => row.kind === 'stock');
  const reading = metric => {
    const matchingRows = stocks.filter(row => row.metric_id === metric);
    const candidates = matchingRows.filter(row => Object.hasOwn(row.cells ?? {}, period));
    const row = candidates[0] ?? matchingRows[0];
    const cell = row?.cells?.[period];
    const value = valueOf(cell);
    const form = cell?.source_form || row?.source_form;
    const version = cell?.source_version || cell?.source_url;
    const url = cell?.source_url ?? row?.source_url ?? null;
    const code = cell?.source_code ?? row?.source_code;
    const expectedCode = BALANCE_LINES[form]?.[metric] ?? ASSET_LINES[form]?.[metric] ?? EQUITY_LINES[form]?.[metric];
    const issuersMatch = [cell?.issuer_id, row?.issuer_id].every(id => id == null || String(id) === String(issuerId)) &&
      [cell?.ticker, row?.ticker].every(symbol => symbol == null || symbol === ticker);
    const dimensionsMatch = [cell?.scope, row?.scope].every(value => value == null || value === scope) &&
      [cell?.standard, row?.standard].every(value => value == null || value === standard) &&
      [cell?.source_form, row?.source_form].every(value => value == null || value === form) &&
      [cell?.source_code, row?.source_code].every(value => value == null || value === code);
    const conversion = value != null && knownContext && issuersMatch && dimensionsMatch && expectedCode && code === expectedCode && version &&
      cell?.period_end === periodEnd && cell?.currency && conversionFor(cell, row.unit, value, periodEnd);
    const source = conversion ? JSON.stringify([ticker, issuerId, form, version, url, cell.currency, ...conversion]) : null;
    const unitError = value != null && !DISPLAY_SCALES.has(row?.unit);
    const sourceError = candidates.length > 1 || (value != null && !unitError && !source);
    return {...row, metric_id: metric, value: sourceError || unitError ? null : value, source, sourceError, unitError,
      form, code};
  };
  const totalAssets = reading('total_assets');
  const sections = ['noncurrent_assets', 'current_assets'].map(reading);
  const components = Object.keys(ASSET_LINES[totalAssets.form] ?? {}).map(reading)
    .filter(row => row.id || (totalAssets.form === 'BANK_BS' && row.metric_id === 'loans_leases_net'));
  const hasSections = sections.every(row => row.id);
  // Sections validate the balance, but their nested details form the slices.
  // Never add a subtotal and its children to the same pie.
  const sectionCheck = hasSections ? composition(sections, totalAssets, 'asset_sections') : null;
  const assetRows = components.length ? components : sections.filter(row => row.id);
  const assets = sectionCheck?.reason ? sectionCheck : composition(assetRows, totalAssets);
  if (!assets.reason && hasSections && components.length) {
    const boundary = BALANCE_LINES[totalAssets.form].noncurrent_assets;
    const noncurrent = components.filter(row => ASSET_LINES[totalAssets.form][row.metric_id] < boundary);
    const current = components.filter(row => ASSET_LINES[totalAssets.form][row.metric_id] > boundary);
    for (const [index, items] of [noncurrent, current].entries()) {
      const calculation = compare(items, sections[index]);
      if (calculation.difference > calculation.tolerance) {
        assets.reason = 'asset_section_overrun';
        assets.total = null;
        assets.comparison = calculation;
        break;
      }
    }
  }
  // A shortfall between two filed sections is already covered by reconciliation.
  if (!assets.reason && (!hasSections || components.length)) {
    const difference = totalAssets.value - assetRows.reduce((sum, row) => sum + row.value, 0);
    const roundingError = Number.EPSILON * Math.abs(totalAssets.value) * assetRows.length;
    if (difference > roundingError) assets.rows = [...assetRows, {
      metric_id: 'unclassified_assets', value: difference, unit: assets.unit, derived: true,
    }];
  }
  // Insurer liabilities exclude reserves. Add the filed net reserve subtotal,
  // never the overlapping gross reserve or reinsurer-share lines.
  const fundingRows = (totalAssets.form === 'INSURANCE_BS'
    ? ['nonreserve_liabilities', 'insurance_reserves_net', 'total_equity']
    : ['total_liabilities', 'total_equity']).map(reading);
  const totalEquity = reading('total_equity');
  const equityRows = Object.keys(EQUITY_LINES[totalEquity.form] ?? {}).map(reading);
  const equity = composition(equityRows, totalEquity, 'equity_unreconciled');
  // A positive filed treasury-share balance is a deduction, not a positive
  // ownership slice. Preserve the filed amount in the list and withhold the pie.
  if ([null, 'equity_unreconciled'].includes(equity.reason) &&
    equityRows.some(row => row.metric_id === 'treasury_shares' && row.value > 0)) {
    equity.reason = 'deductions';
    equity.total = null;
    equity.comparison = null;
  }
  return {assets, funding: composition(fundingRows, totalAssets, 'unreconciled'), equity};
}
