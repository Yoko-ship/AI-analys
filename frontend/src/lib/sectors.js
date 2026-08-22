// sectors.js — which sector a ticker files under, decided in one place.
//
// The Рынок filter bar and the heat map used to answer that question from
// different maps. The bar read the securities catalog (`/api/securities`); the
// map asked `/api/companies` first and only fell back to the catalog. That
// endpoint answers a ticker it has never heard of with the string "other"
// rather than leaving the field blank, so its default always won the `||` and
// the catalog's real answer was never reached:
//
//   UZNF, UZNFP   Фонды in the table        → Прочее on the map
//   UTGA          Логистика in the table    → Прочее on the map
//   UTGAP         Логистика in the table    → Транспорт on the map
//   UTHK          Прочее in the table       → Производство on the map
//
// The precedence below (catalog first, companies only as a fallback for a
// ticker the catalog has not reached) is the same one `instruments.build_catalog`
// documents on the server, so all three now agree.

// Display order for the heat map's sector blocks. Every sector the catalog can
// produce has to be listed here: one that was missing got folded into "other",
// which is how Торговля (CBSK) and Услуги (BTRL, TGPG) had a chip of their own
// in the table and no block of their own on the map.
export const SECTOR_ORDER = [
  "finance",
  "funds",
  "energy",
  "manufacturing",
  "mining",
  "telecom",
  "transport",
  "logistics",
  "trade",
  "professional",
  "other",
];

const KNOWN_SECTORS = new Set(SECTOR_ORDER);

/** The sector a ticker belongs to — the catalog's answer, then the companies
 *  list, then "other". Never undefined: every instrument files somewhere. */
export function sectorOf(ticker, securitiesMap, companyMap) {
  const key = String(ticker || "").toUpperCase();
  return securitiesMap?.[key]?.sector || companyMap?.[key]?.sector || "other";
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
