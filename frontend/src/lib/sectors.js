import {industryOf} from './companyIndustries.js';
// One display classification for filters, maps and company surfaces. Reviewed
// issuer membership wins over stale catalog sectors. For new/unreviewed tickers,
// the securities catalog wins over the companies list (which can default to
// "other"). Legacy sector keys remain available for unclassified listings.

export const SECTOR_ORDER = [
  "finance",
  "funds",
  "energy",
  "manufacturing",
  "mining",
  "construction",
  "telecom",
  "transport",
  "logistics",
  "trade",
  "professional",
  "other",
];

const KNOWN_SECTORS = new Set(SECTOR_ORDER);

/** The reviewed parent section, then catalog / company fallback, then "other". Never undefined: every instrument files somewhere. */
export function sectorOf(ticker, securitiesMap, companyMap) {
  const key = String(ticker || "").toUpperCase();
  return industryOf(key)?.sector || securitiesMap?.[key]?.sector || companyMap?.[key]?.sector || "other";
}

/** Sectors in display order. Known ones keep the designed order; anything the
 *  catalog grows later is appended, never dropped — filtering by SECTOR_ORDER
 *  alone would have deleted its tiles instead of showing them. */
export function orderSectors(sectors) {
  const present = new Set(sectors);
  return [
    ...SECTOR_ORDER.filter((s) => present.has(s)),
    ...[...present].filter((s) => !KNOWN_SECTORS.has(s)).sort(),
  ];
}
