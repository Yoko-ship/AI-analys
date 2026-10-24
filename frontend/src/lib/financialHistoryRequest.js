// The legacy history API accepts a perimeter only for IFRS.
export function financialsUrl(ticker, standard, scope, quarterly = false) {
  const params = new URLSearchParams({ form: standard });
  if (quarterly) params.set('freq', 'quarterly');
  if (standard === 'MSFO' && scope) params.set('scope', scope);
  return `/api/company/${encodeURIComponent(ticker)}/financials?${params}`;
}
