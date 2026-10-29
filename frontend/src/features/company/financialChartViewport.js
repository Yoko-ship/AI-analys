export function chartWindow(columns, offset, count) {
  const skip=Math.min(Math.max(0, offset), Math.max(0, columns.length-count));
  const end=columns.length-skip;
  return columns.slice(Math.max(0,end-count),end);
}

export function defaultChartMetrics(rows) {
  const priority=['net_profit','net_income','revenue','interest_income','interest_expense',
    'net_interest_after_ecl','total_assets','total_equity','total_liabilities'];
  const ranked=[...priority.flatMap(metric=>rows.filter(row=>row.metric_id===metric)),...rows];
  const ids=new Set(ranked.filter((row,i)=>ranked.findIndex(item=>item.id===row.id)===i).slice(0,3).map(row=>row.id));
  return rows.filter(row=>ids.has(row.id));
}

// Round axis boundaries, never the source observations. Include zero so bars
// retain honest proportions; only observations in the visible window belong here.
export function chartScale(values) {
  const finite=values.filter(Number.isFinite);
  const low=Math.min(0,...finite),high=Math.max(0,...finite);
  const span=high-low || 1,rawStep=span/5;
  const power=10**Math.floor(Math.log10(rawStep));
  const step=([1,2,2.5,5,10].find(n=>n*power>=rawStep)||10)*power;
  const min=Math.floor(low/step)*step,max=Math.ceil((high===low?high+1:high)/step)*step;
  const ticks=Array.from({length:Math.floor((max-min)/step+.5)+1},(_,i)=>Number((min+i*step).toPrecision(12)));
  return {min,max,ticks};
}
