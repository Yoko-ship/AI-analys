// Prefer source-provided short names. Quotation marks delimit an issuer's name
// in Uzbek legal names; apostrophes within words are never delimiters.
export function issuerDisplayName(issuer, ticker = '') {
  const short = issuer.short_name || issuer.shortName;
  if (short?.trim()) return short.trim();
  const name = issuer.name || issuer.company_name || ticker;
  const quoted = name.match(/["“«]([^"”»]+)["”»]/u);
  return quoted?.[1].trim() || name;
}
