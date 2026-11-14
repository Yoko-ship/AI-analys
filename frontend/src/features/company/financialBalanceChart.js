const numeric = input => {
  if (typeof input !== 'number' && (typeof input !== 'string' || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(input.trim()))) return null;
  const value = Number(input);
  return Number.isFinite(value) ? value : null;
};
const valueOf = cell => ['valid', 'warn'].includes(cell?.quality) ? numeric(cell.value) : null;
const DISPLAY_SCALES = new Map([['UZS', 1], ['UZS_thousand', 1000]]);

function conversionFor(cell, unit, value, periodEnd) {
  const displayScale = DISPLAY_SCALES.get(unit);
  const sourceScale = numeric(cell.unit_scale);
  const fx = cell.fx;
  const foreign = cell.currency !== 'UZS';
  const end = Date.parse(periodEnd);
  const effective = Date.parse(fx?.effective_date);
  const fxAge = (end - effective) / 86400000;
  const verifiedFx = fx?.currency === cell.currency && fx?.as_of === periodEnd && fx?.basis === 'period_end_presentation' &&
    fxAge >= 0 && fxAge <= 7 && fx?.source_url === `https://cbu.uz/ru/arkhiv-kursov-valyut/json/all/${periodEnd}/`;
  const rate = foreign ? (verifiedFx ? numeric(fx.rate) : null) : 1;
  if (!displayScale || sourceScale == null || sourceScale <= 0 || rate == null || rate <= 0) return null;
  if (cell.raw_value == null) return sourceScale === displayScale && !foreign ? [sourceScale, 1] : null;
  const raw = numeric(cell.raw_value);
  if (raw == null) return null;
  const normalized = raw * sourceScale * rate / displayScale;
  if (!Number.isFinite(normalized) || Math.abs(normalized - value) > Number.EPSILON * 4 * Math.max(Math.abs(value), Math.abs(normalized))) return null;
  return foreign ? [sourceScale, rate, fx.effective_date, fx.source_url] : [sourceScale, 1];
}

// financial_columns/registry.py maps these official balance-sheet lines.
// F1 line 320 includes bank accounts. BANK_BS lines 1, 2 and 3 are separate.
// Bank net amounts replace their gross lines and allowances.
const ASSET_LINES = {
  F1: {ppe: '012', intangibles: '022', inventory: '140', receivables: '210', cash: '320'},
  BANK_BS: {cash: '1', central_bank_balances: '2', bank_balances: '3', trading_assets_net: '4г',
    investments_net: '5в', loans_leases_net: '7г', ppe: '10', interest_receivables: '11'},
};
const BALANCE_LINES = {
  F1: {total_assets: '400', noncurrent_assets: '130', current_assets: '390', total_liabilities: '770', total_equity: '480'},
  BANK_BS: {total_assets: '14', total_liabilities: '25', total_equity: '30'},
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
    if (mismatch && Math.abs(difference) > roundingError) reason = mismatch;
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
    const candidates = stocks.filter(row => row.metric_id === metric);
    const [row] = candidates;
    const cell = row?.cells?.[period];
    const value = valueOf(cell);
    const form = cell?.source_form || row?.source_form;
    const version = cell?.source_version || cell?.source_url;
    const url = cell?.source_url ?? row?.source_url ?? null;
    const code = cell?.source_code ?? row?.source_code;
    const expectedCode = BALANCE_LINES[form]?.[metric] ?? ASSET_LINES[form]?.[metric];
    const issuersMatch = [cell?.issuer_id, row?.issuer_id].every(id => id == null || String(id) === String(issuerId)) &&
      [cell?.ticker, row?.ticker].every(symbol => symbol == null || symbol === ticker);
    const cellScope = cell?.scope ?? row?.scope ?? scope;
    const cellStandard = cell?.standard ?? row?.standard ?? standard;
    const conversion = value != null && knownContext && issuersMatch && expectedCode && code === expectedCode &&
      cellScope === scope && cellStandard === standard && version &&
      cell?.period_end === periodEnd && cell?.currency && conversionFor(cell, row.unit, value, periodEnd);
    const source = conversion ? JSON.stringify([ticker, issuerId, form, version, url, cell.currency, ...conversion]) : null;
    const unitError = value != null && !DISPLAY_SCALES.has(row?.unit);
    const sourceError = candidates.length > 1 || (value != null && !unitError && !source);
    return {...row, metric_id: metric, value: sourceError || unitError ? null : value, source, sourceError, unitError,
      form};
  };
  const totalAssets = reading('total_assets');
  const sections = ['noncurrent_assets', 'current_assets'].map(reading);
  const components = Object.keys(ASSET_LINES[totalAssets.form] ?? {}).map(reading).filter(row => row.id);
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
