// A minimum 1% price span keeps a few-som move from filling the whole chart.
// Price axes still show the actual bounds; this is not a zero-based volume chart.
export function historyScale(values) {
  const valid = values.filter(Number.isFinite);
  if (!valid.length) return {min: 0, max: 1, ticks: [0, 0.5, 1]};
  const low = Math.min(...valid), high = Math.max(...valid);
  const center = (low + high) / 2;
  const span = Math.max((high - low) * 1.3, Math.abs(center) * 0.01, 0.01);
  const rough = span / 4, power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].find(n => n * power >= rough) * power;
  const min = Math.floor((center - span / 2) / step) * step;
  const max = Math.ceil((center + span / 2) / step) * step;
  const ticks = Array.from({length: Math.floor((max - min) / step + 0.5) + 1}, (_, i) => min + i * step);
  return {min, max, ticks};
}

export function historySegments(points) {
  const segments = [];
  let current = [];
  points.forEach((point, index) => {
    if (Number.isFinite(point.value)) current.push({...point, index});
    else if (current.length) { segments.push(current); current = []; }
  });
  if (current.length) segments.push(current);
  return segments;
}

// Keep every calendar day on the shared company-chart time scale. Separate
// visible series are essential: whitespace in a single line can bridge gaps.
export function historySeries(points, options = {}) {
  const datum = point => ({time: Date.parse(`${point.date}T00:00:00Z`) / 1000,
    ...(Number.isFinite(point.value) ? {value: point.value} : {})});
  const base = {color:'#8066f7', lineWidth:2, lastValueVisible:false, priceLineVisible:false, ...options};
  return [
    {key:'history', kind:'line', data:points.map(datum),
      options:{...base, lineVisible:false, crosshairMarkerVisible:false}},
    ...historySegments(points).map((segment,i)=>({key:`history-${i}`, kind:'line', data:segment.map(datum),
      options:{...base, pointMarkersVisible:segment.length===1, pointMarkersRadius:3}})),
  ];
}

export function mergeHistoryPoints(existing, incoming) {
  const days = new Map(existing.map(point=>[point.date,point]));
  for (const point of incoming) {
    if (Number.isFinite(point.value) || !Number.isFinite(days.get(point.date)?.value)) days.set(point.date,point);
  }
  return [...days.values()].sort((a,b)=>a.date.localeCompare(b.date));
}
