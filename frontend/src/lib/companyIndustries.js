import registry from '../../../config/company_industries.json' with {type: 'json'};

export const industrySections = registry.sections;
export const industryGroups = registry.groups;
export const industrySource = registry.source;
const index = new Map();
for (const issuer of registry.issuers) {
  const sector = industryGroups[issuer.group].sector;
  const entry = {...issuer, issuer_id: issuer.id, sector, section: industrySections[sector].code};
  for (const ticker of issuer.tickers) index.set(ticker, entry);
}
for (const [alias, ticker] of Object.entries(registry.aliases)) index.set(alias, index.get(ticker));
export const industryOf = ticker => index.get(String(ticker || '').trim().toUpperCase()) || null;
export const industryLabel = (labels, language) => labels?.[language] || labels?.ru || '';

/** One issuer contains explicit share classes; price data stays at security level.
 * PDF members remain discoverable without a quote. New catalog members survive
 * under an unclassified subgroup, with no guess based on a ticker's suffix. */
export function buildIssuerTree({companies = [], securitiesMap = {}, query = '', sector = '', group = ''} = {}) {
  const known = new Map();
  for (const issuer of registry.issuers) {
    issuer.tickers.forEach((ticker, i) => known.set(ticker, {
      ticker, name: issuer.name, share_type: i ? 'preferred' : 'ordinary',
    }));
  }
  for (const company of companies) {
    const raw = String(company.ticker || '').toUpperCase();
    const ticker = registry.aliases[raw] || raw;
    if (ticker) known.set(ticker, {...known.get(ticker), ...company, ticker, name: company.company_name || company.name});
  }
  for (const [key, security] of Object.entries(securitiesMap)) {
    const ticker = registry.aliases[key.toUpperCase()] || key.toUpperCase();
    known.set(ticker, {...known.get(ticker), ...security, ticker});
  }
  const issuers = new Map();
  for (const security of known.values()) {
    if (security.type === 'bond' || security.security_type === 'bond') continue;
    const industry = industryOf(security.ticker);
    const id = industry?.issuer_id || security.ticker;
    if (!issuers.has(id)) issuers.set(id, {
      ...(industry || {id, sector: security.sector || 'other', group: 'unclassified', status: 'unclassified'}),
      name: industry?.name || security.name || id, securities: [],
    });
    issuers.get(id).securities.push(security);
  }
  const needle = query.trim().toLocaleLowerCase();
  const sections = new Map();
  for (const issuer of issuers.values()) {
    if (sector && issuer.sector !== sector || group && issuer.group !== group) continue;
    const aliases = Object.keys(registry.aliases).filter(alias => industryOf(alias)?.issuer_id === issuer.id);
    const search = [issuer.name, ...aliases, ...issuer.securities.flatMap(s => [s.ticker, s.name, s.company_name, s.isin])].join(' ').toLocaleLowerCase();
    if (needle && !search.includes(needle)) continue;
    if (!sections.has(issuer.sector)) sections.set(issuer.sector, new Map());
    const groups = sections.get(issuer.sector);
    if (!groups.has(issuer.group)) groups.set(issuer.group, []);
    groups.get(issuer.group).push(issuer);
  }
  const ordered = (keys, reference) => [...Object.keys(reference).filter(k => keys.includes(k)), ...keys.filter(k => !reference[k]).sort()];
  return ordered([...sections.keys()], industrySections).map(key => ({
    sector: key, ...industrySections[key],
    groups: ordered([...sections.get(key).keys()], industryGroups).map(id => ({
      id, ...industryGroups[id], issuers: sections.get(key).get(id),
    })),
  }));
}
