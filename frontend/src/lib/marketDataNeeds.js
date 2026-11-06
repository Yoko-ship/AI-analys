// Shared by the table and its HTML startup script. Keep this function
// self-contained so the build can serialize the same rules before React loads.
export function marketDataNeeds(columns, period = '1d', type = 'stock') {
  const visible = Array.isArray(columns) ? columns : [
    'change', 'change1w', 'change1m', 'nominal', 'open', 'high', 'low', 'volume', 'date', 'source',
  ];
  const has = keys => keys.some(key => visible.includes(key));
  const equity = type !== 'bond';
  return {
    columns: visible,
    changes: period !== '1d' || (equity && has(['change1w', 'change1m'])),
    financials: equity && has(['finRevenue', 'finGross', 'finCash', 'finLiab', 'finNet', 'finOperating']),
    ratios: equity && has(['currentRatio', 'quickRatio', 'debtAssets', 'assetTurnover', 'roce']),
    multiples: equity && has(['pe', 'pb', 'ps', 'roe', 'roa', 'netMargin', 'eqAssets']),
  };
}
