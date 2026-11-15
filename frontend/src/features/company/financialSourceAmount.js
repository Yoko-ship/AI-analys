const numeric = input => {
  if (typeof input !== 'number' && (typeof input !== 'string' || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(input.trim()))) return null;
  const value = Number(input);
  return Number.isFinite(value) ? value : null;
};
export const valueOf = cell => ['valid', 'warn'].includes(cell?.quality) ? numeric(cell.value) : null;
export const DISPLAY_SCALES = new Map([['UZS', 1], ['UZS_thousand', 1000]]);

function filedAmount({raw_value: raw, source_form: form, standard}) {
  if (!Array.isArray(raw)) return numeric(raw);
  // The NSBU parser retains the separate income and expense cells for these forms.
  if (standard !== 'NSBU' || !['F2', 'INSURANCE_PL'].includes(form) || raw.length !== 2) return null;
  const crossed = raw.map(item => typeof item === 'string' && /^[xх]$/i.test(item.trim()));
  if (crossed.every(Boolean)) return null;
  const [income, expense] = raw.map((item, index) => crossed[index] ? 0 : numeric(item));
  return income == null || expense == null ? null : income - expense;
}

export function conversionFor(cell, unit, value, periodEnd) {
  const displayScale = unit === 'UZS_per_share' || unit === 'shares' ? 1 : DISPLAY_SCALES.get(unit);
  const sourceScale = numeric(cell.unit_scale);
  const fx = cell.fx;
  if (!cell.currency || (unit === 'shares') !== (cell.currency === 'shares')) return null;
  const foreign = !['UZS', 'shares'].includes(cell.currency);
  const end = Date.parse(periodEnd);
  const effective = Date.parse(fx?.effective_date);
  const fxAge = (end - effective) / 86400000;
  const verifiedFx = fx?.currency === cell.currency && fx?.as_of === periodEnd && fx?.basis === 'period_end_presentation' &&
    fxAge >= 0 && fxAge <= 7 && fx?.source_url === `https://cbu.uz/ru/arkhiv-kursov-valyut/json/all/${periodEnd}/`;
  const rate = foreign ? (verifiedFx ? numeric(fx.rate) : null) : 1;
  if (!displayScale || sourceScale == null || sourceScale <= 0 || rate == null || rate <= 0) return null;
  if (cell.raw_value == null) return sourceScale === displayScale && !foreign ? [sourceScale, 1] : null;
  const raw = filedAmount(cell);
  if (raw == null) return null;
  const normalized = raw * sourceScale * rate / displayScale;
  if (!Number.isFinite(normalized) || Math.abs(normalized - value) > Number.EPSILON * 4 * Math.max(Math.abs(value), Math.abs(normalized))) return null;
  return foreign ? [sourceScale, rate, fx.effective_date, fx.source_url] : [sourceScale, 1];
}
