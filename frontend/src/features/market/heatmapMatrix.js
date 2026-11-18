// Strict thresholds in UZS, shared by the filter and matrix columns. Missing
// capitalization is never treated as a small company or inferred from turnover.
export const CAPITALIZATION_STEPS = [0, 1e12, 5e12, 10e12, 25e12];
export const CAPITALIZATION_TIERS = [
  {id: 'under1', label: '≤ 1'}, {id: '1to5', label: '> 1–5'},
  {id: '5to10', label: '> 5–10'}, {id: '10to25', label: '> 10–25'},
  {id: 'over25', label: '> 25'}, {id: 'unknown', label: null},
];

export function capitalizationTier(value) {
  if (!Number.isFinite(value) || value <= 0) return 'unknown';
  const index = CAPITALIZATION_STEPS.slice(1).findIndex(limit => value <= limit);
  return CAPITALIZATION_TIERS[index < 0 ? 4 : index].id;
}

export function matchesCapitalization(row, minimum) {
  return !minimum || (Number.isFinite(row.marketCap) && row.marketCap > minimum);
}

// Industry rows share fixed tier columns. Each cell wraps equal tiles; a busy
// industry grows vertically rather than shrinking its tickers into unreadable dots.
export function matrixLayout(sections, availableWidth, zoom = 1) {
  const tiers = CAPITALIZATION_TIERS.filter(tier => tier.id !== 'unknown'
    || sections.some(section => section.groups.some(group => group.rows.some(row => capitalizationTier(row.marketCap) === 'unknown'))));
  const labelWidth = 190 * zoom, header = 34 * zoom, padding = 6 * zoom;
  const minWidth = labelWidth + tiers.length * 166 * zoom;
  const width = Math.max(availableWidth || 0, minWidth);
  const columnWidth = (width - labelWidth) / tiers.length;
  const tileWidth = 72 * zoom, tileHeight = 26 * zoom, gap = 4 * zoom;
  const perLine = Math.max(1, Math.floor((columnWidth - padding * 2 + gap) / (tileWidth + gap)));
  const columns = tiers.map((tier, index) => ({...tier, x: labelWidth + index * columnWidth, w: columnWidth}));
  let y = header;
  const sectors = sections.map(section => {
    const sectorY = y;
    y += 26 * zoom;
    const groups = section.groups.map(group => {
      const buckets = columns.map(column => ({...column, rows: group.rows.filter(row => capitalizationTier(row.marketCap) === column.id)}));
      const lines = Math.max(1, ...buckets.map(bucket => Math.ceil(bucket.rows.length / perLine)));
      const h = Math.max(58 * zoom, padding * 2 + lines * (tileHeight + gap) - gap);
      const stocks = buckets.flatMap(bucket => [...bucket.rows].sort((a, b) => a.ticker.localeCompare(b.ticker)).map((row, index) => ({
        row, tier: bucket.id, x: bucket.x + padding + index % perLine * (tileWidth + gap),
        y: y + padding + Math.floor(index / perLine) * (tileHeight + gap), w: tileWidth, h: tileHeight,
      })));
      const result = {...group, x: labelWidth, y, w: width - labelWidth, h, labelHeight: h, stocks};
      y += h;
      return result;
    });
    return {...section, x: 0, y: sectorY, w: width, h: y - sectorY, showHeader: true,
      headerHeight: 26 * zoom, groups, stocks: groups.flatMap(group => group.stocks)};
  });
  return {columns, sectors, width, minWidth, height: y + 2, labelWidth, header};
}
