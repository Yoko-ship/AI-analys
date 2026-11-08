import {industryGroups, industryOf, industrySections} from './companyIndustries.js';
import {orderSectors, sectorOf} from './sectors.js';

// The table selector and the treemap consume the same hierarchy. Only securities
// on the board are included; new listings retain their catalog sector.
export function groupMarketIndustries(rows, securitiesMap, companyMap) {
  const sections = new Map();
  for (const row of rows) {
    const sector = sectorOf(row.ticker, securitiesMap, companyMap);
    const group = industryOf(row.ticker)?.group || '';
    if (!sections.has(sector)) sections.set(sector, new Map());
    const groups = sections.get(sector);
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(row);
  }
  const sectorOrder = [...Object.keys(industrySections), ...orderSectors(sections.keys())];
  return [...new Set(sectorOrder)].filter(sector => sections.has(sector)).map(sector => {
    const groups = sections.get(sector);
    return {sector, groups: [...Object.keys(industryGroups), ''].filter(id => groups.has(id))
      .map(id => ({id, rows: groups.get(id)}))};
  });
}

export function matchesMarketIndustry(ticker, selection, securitiesMap, companyMap) {
  if (!selection) return true;
  return selection.startsWith('group:')
    ? industryOf(ticker)?.group === selection.slice(6)
    : sectorOf(ticker, securitiesMap, companyMap) === selection;
}
