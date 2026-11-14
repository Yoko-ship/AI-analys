const valueOf = cell => cell?.value != null && cell.value !== '' &&
  ['valid', 'warn'].includes(cell.quality) && Number.isFinite(Number(cell.value)) ? Number(cell.value) : null;

// These are disjoint net asset categories. Gross amounts, allowances and
// nested statement lines must never become additional slices.
const ASSET_COMPONENTS = [
  ['ppe'], ['intangibles_goodwill', 'intangibles'], ['inventory'],
  ['trade_other_receivables', 'receivables', 'trade_receivables'], ['cash'],
  ['central_bank_balances'], ['bank_balances'], ['trading_assets_net'],
  ['investments_net'], ['loans_leases_net', 'loans_net'], ['interest_receivables'],
];

function composition(rows, total, unit) {
  const sum = rows.reduce((sum, row) => sum + row.value, 0);
  const roundingError = Number.EPSILON * Math.max(Math.abs(total || 0), Math.abs(sum)) * rows.length;
  let reason = null;
  if (total == null || rows.some(row => row.value == null)) reason = 'missing';
  else if (rows.some(row => row.unit !== unit)) reason = 'units';
  else if (total < 0 || rows.some(row => row.value < 0)) reason = 'negative';
  else if (total === 0) reason = 'zero';
  else if (sum - total > roundingError) reason = 'inconsistent';
  return {rows, total, unit, reason};
}

export function balanceComposition(rows, period) {
  const stocks = rows.filter(row => row.kind === 'stock');
  const find = metric => stocks.find(row => row.metric_id === metric);
  const reading = metric => {
    const row = find(metric);
    return {...row, metric_id: metric, unit: row?.unit || 'UZS_thousand', value: valueOf(row?.cells?.[period])};
  };
  const totalAssets = reading('total_assets');
  const sections = ['noncurrent_assets', 'current_assets'].map(reading);
  const components = ASSET_COMPONENTS.map(aliases => aliases.map(reading).find(row => row.value != null))
    .filter(row => row && find(row.metric_id)?.source_form === find('total_assets')?.source_form);
  const assetRows = sections.every(row => row.value != null) ? sections : components;
  const assets = composition(assetRows, totalAssets.value, totalAssets.unit);
  if (!assets.reason && !assetRows.length) assets.reason = 'missing';
  if (!assets.reason) {
    const difference = totalAssets.value - assetRows.reduce((sum, row) => sum + row.value, 0);
    const roundingError = Number.EPSILON * Math.abs(totalAssets.value) * assetRows.length;
    if (difference > roundingError) assets.rows = [...assetRows, {
      metric_id: 'other_assets_difference', value: difference, unit: assets.unit, derived: true,
    }];
  }
  const fundingRows = ['total_liabilities', 'total_equity'].map(reading);
  const fundingTotal = fundingRows.every(row => row.value != null) ?
    fundingRows.reduce((sum, row) => sum + row.value, 0) : null;
  return {assets, funding: composition(fundingRows, fundingTotal, fundingRows[0].unit)};
}
