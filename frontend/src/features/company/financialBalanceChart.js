const valueOf = cell => cell?.value != null && cell.value !== '' &&
  ['valid', 'warn'].includes(cell.quality) && Number.isFinite(Number(cell.value)) ? Number(cell.value) : null;
const MONEY_UNITS = new Set(['UZS', 'UZS_thousand']);

// These are disjoint net asset categories. Gross amounts, allowances and
// nested statement lines must never become additional slices.
const ASSET_COMPONENTS = [
  ['ppe'], ['intangibles_goodwill', 'intangibles'], ['inventory'],
  ['trade_other_receivables', 'receivables', 'trade_receivables'], ['cash'],
  ['central_bank_balances'], ['bank_balances'], ['trading_assets_net'],
  ['investments_net'], ['loans_leases_net', 'loans_net'], ['interest_receivables'],
];

function composition(rows, {value: total, unit, source, ambiguous}, mismatch = null) {
  let reason = null;
  if (ambiguous || rows.some(row => row.ambiguous)) reason = 'source';
  else if (total == null || !rows.length || rows.some(row => row.value == null)) reason = 'missing';
  else if (!MONEY_UNITS.has(unit) || rows.some(row => row.unit !== unit)) reason = 'units';
  else if (!source || rows.some(row => row.source !== source)) reason = 'source';
  else if (total < 0 || rows.some(row => row.value < 0)) reason = 'negative';
  else {
    const sum = rows.reduce((subtotal, row) => subtotal + row.value, 0);
    const difference = sum - total;
    const roundingError = Number.EPSILON * Math.max(Math.abs(total), Math.abs(sum)) * rows.length;
    if (mismatch && Math.abs(difference) > roundingError) reason = mismatch;
    else if (total === 0) reason = 'zero';
    else if (difference > roundingError) reason = 'inconsistent';
  }
  return {rows, total: reason ? null : total, unit, reason};
}

export function balanceComposition(rows, period, periodEnd, {scope, standard} = {}) {
  const knownContext = ['separate', 'consolidated'].includes(scope) && ['NSBU', 'MSFO'].includes(standard);
  const stocks = rows.filter(row => row.kind === 'stock');
  const reading = metric => {
    const candidates = stocks.filter(row => row.metric_id === metric && row.cells?.[period]);
    const [row] = candidates;
    const cell = row?.cells?.[period];
    const form = cell?.source_form || row?.source_form;
    const version = cell?.source_version || cell?.source_url;
    const cellScope = cell?.scope ?? row?.scope ?? scope;
    const cellStandard = cell?.standard ?? row?.standard ?? standard;
    const hasSource = knownContext && cellScope === scope && cellStandard === standard && form && version &&
      cell.period_end === periodEnd && cell.currency && cell.unit_scale;
    const source = hasSource ? JSON.stringify([form, version, cell.currency, String(cell.unit_scale)]) : null;
    return {...row, metric_id: metric, value: valueOf(cell), source, ambiguous: candidates.length > 1};
  };
  const totalAssets = reading('total_assets');
  const sections = ['noncurrent_assets', 'current_assets'].map(reading);
  const components = ASSET_COMPONENTS.map(aliases => {
    const readings = aliases.map(reading);
    return readings.find(row => row.id);
  }).filter(Boolean);
  const hasSections = sections.every(row => row.id);
  const assetRows = hasSections ? sections : components;
  const assets = composition(assetRows, totalAssets, hasSections ? 'asset_sections' : null);
  if (!assets.reason) {
    const difference = totalAssets.value - assetRows.reduce((sum, row) => sum + row.value, 0);
    const roundingError = Number.EPSILON * Math.abs(totalAssets.value) * assetRows.length;
    if (difference > roundingError) assets.rows = [...assetRows, {
      metric_id: 'other_assets_difference', value: difference, unit: assets.unit, derived: true,
    }];
  }
  const fundingRows = ['total_liabilities', 'total_equity'].map(reading);
  return {assets, funding: composition(fundingRows, totalAssets, 'unreconciled')};
}
