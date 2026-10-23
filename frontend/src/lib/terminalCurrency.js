export function periodEnd(period) {
  const match = /^(\d{4})(?:Q([1-4]))?$/.exec(String(period));
  if (!match) return null;
  return `${match[1]}-${({1:'03-31',2:'06-30',3:'09-30',4:'12-31'})[match[2] || 4]}`;
}
export function convertSeries(series, rates, currency) {
  if (currency !== 'USD') return series;
  return Object.fromEntries(Object.entries(series || {}).map(([key,row])=>[key,!row.money ? row : {
    ...row, unit:'USD', values:Object.fromEntries(Object.entries(row.values || {}).map(([period,value])=>{
      const rate=rates[period]?.per_unit;
      return [period,value != null && Number.isFinite(value) && Number.isFinite(rate) && rate > 0 ? value/rate : null];
    }))
  }]));
}
