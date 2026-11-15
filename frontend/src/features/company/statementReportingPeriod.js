import {conversionFor, valueOf} from './financialSourceAmount.js';

const monthStart = (year, month) => [year, String(month).padStart(2, '0'), '01'].join('-');

function monthEnd(year, month) {
  return new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
}

function flowInterval(period) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(period.end)) return null;
  const [year, month] = period.end.split('-').map(Number);
  if (year < 100 || ![3, 6, 9, 12].includes(month) || period.end !== monthEnd(year, month)) return null;
  const yearStart = monthStart(year, 1);
  const yearToDate = [yearStart, period.end, 1];
  if (period.basis === 'annual') {
    return month === 12 ? {start: yearStart, direct: 'annual'} : null;
  }
  if (period.basis === 'ytd') return {start: yearStart, direct: 'ytd'};
  if (period.basis === 'quarter') {
    const terms = month === 3 ? [yearToDate] : [yearToDate, [yearStart, monthEnd(year, month - 3), -1]];
    return {start: monthStart(year, month - 2), direct: 'reported_quarter', terms};
  }
  if (period.basis === 'ttm') {
    if (month === 12) return {start: yearStart, terms: [yearToDate]};
    const previousStart = monthStart(year - 1, 1);
    return {start: monthStart(year - 1, month + 1), terms: [
      yearToDate, [previousStart, monthEnd(year - 1, 12), 1], [previousStart, monthEnd(year - 1, month), -1],
    ]};
  }
  return null;
}

export function statementAmountReason(cell, row, period, amount, matchesSource) {
  if (cell.period_end !== period.end) return 'SOURCE_REPORTING_DIMENSIONS_MISMATCH';
  if (row.kind === 'stock') {
    if (cell.period_start != null && cell.period_start !== period.end) return 'SOURCE_REPORTING_DIMENSIONS_MISMATCH';
    return conversionFor(cell, row.unit, amount, period.end) ? null : 'UNIT_UNRESOLVED';
  }

  const interval = flowInterval(period);
  if (!interval || cell.period_start !== interval.start) return 'PERIOD_COVERAGE_MISSING';
  if (interval.direct && (cell.basis == null || cell.basis === interval.direct)) {
    return conversionFor(cell, row.unit, amount, period.end) ? null : 'UNIT_UNRESOLVED';
  }
  if (cell.basis !== period.basis || !interval.terms || !Array.isArray(cell.components) ||
      cell.components.length !== interval.terms.length) {
    return 'PERIOD_COVERAGE_MISSING';
  }

  let total = 0;
  let magnitude = 0;
  for (const [start, end, coefficient] of interval.terms) {
    const components = cell.components.filter(item => item?.period_start === start && item.period_end === end);
    const [component] = components;
    if (components.length !== 1 || component.coefficient !== coefficient || !matchesSource(component)) {
      return 'PERIOD_COVERAGE_MISSING';
    }
    const value = valueOf(component);
    if (value == null || !conversionFor(component, row.unit, value, end)) return 'UNIT_UNRESOLVED';
    total += value * coefficient;
    magnitude = Math.max(magnitude, Math.abs(value));
  }
  const tolerance = Number.EPSILON * 4 * Math.max(magnitude, Math.abs(total), Math.abs(amount));
  return Number.isFinite(total) && Math.abs(total - amount) <= tolerance ? null : 'CONFLICTING_SOURCE_VALUES';
}
