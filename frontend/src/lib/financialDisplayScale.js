// The history API stores full currency amounts. Scale only the display copy;
// source passports, per-share values, percentages and coefficients stay intact.
export function financialDisplaySeries(series) {
  return Object.fromEntries(Object.entries(series || {}).map(([field, row]) => [field,
    row.money && row.unit === 'UZS' ? {
      ...row, unit: 'UZS_thousand',
      values: Object.fromEntries(Object.entries(row.values || {}).map(([period, value]) =>
        [period, Number.isFinite(value) ? value / 1000 : null])),
    } : row,
  ]));
}
