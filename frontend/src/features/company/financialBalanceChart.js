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

function composition(rows, {value: total, unit, source, sourceError, unitError}, mismatch = null) {
  let reason = null;
  const sources = new Set([source, ...rows.map(row => row.source)].filter(Boolean));
  if (sourceError || rows.some(row => row.sourceError) || sources.size > 1) reason = 'source';
  else if (unitError || rows.some(row => row.unitError)) reason = 'units';
  else if (total == null || !rows.length || rows.some(row => row.value == null)) reason = 'missing';
  else if (rows.some(row => row.unit !== unit)) reason = 'units';
  else if (total < 0 || rows.some(row => row.value < 0)) reason = 'negative';
  else {
    const sum = rows.reduce((subtotal, row) => subtotal + row.value, 0);
    const difference = sum - total;
    const roundingError = Number.EPSILON * Math.max(Math.abs(total), Math.abs(sum)) * rows.length;
    if (!Number.isFinite(sum)) reason = 'overflow';
    else if (mismatch && Math.abs(difference) > roundingError) reason = mismatch;
    else if (total === 0) reason = 'zero';
    else if (difference > roundingError) reason = 'inconsistent';
  }
  const readings = reason === 'source' ? rows.map(row => ({...row, value: null, unit: null})) : rows;
  return {rows: readings, total: reason ? null : total, unit, reason};
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
    const expectedCode = BALANCE_LINES[form]?.[metric] ?? ASSET_LINES[form]?.[metric];
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
      form};
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
    const exceedsSection = [noncurrent, current].some((items, i) => {
      const sum = items.reduce((subtotal, item) => subtotal + item.value, 0);
      const cap = sections[i].value;
      const roundingError = Number.EPSILON * Math.max(sum, cap) * items.length;
      return sum - cap > roundingError;
    });
    if (exceedsSection) {
      assets.reason = 'asset_sections';
      assets.total = null;
    }
  }
  if (!assets.reason) {
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
  return {assets, funding: composition(fundingRows, totalAssets, 'unreconciled')};
}
