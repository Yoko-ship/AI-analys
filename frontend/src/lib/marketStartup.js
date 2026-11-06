// Serialized into the built HTML by build/market.js. Keep this function
// self-contained: it runs before React or any application module downloads.
export function startMarketStartup(browser, modules, dataNeeds) {
  if (!/^\/(uz\/)?market\/?$/.test(browser.location.pathname)) return;
  const paths = [
    '/api/market/stocks?type=stock', '/api/companies', '/api/securities',
    '/api/market/trade-stats', '/api/instruments?view=board',
  ];
  let columns, period;
  try {
    columns = JSON.parse(browser.localStorage?.getItem('uz_market_cols_v3') || 'null');
    period = browser.localStorage?.getItem('uz_market_change_period') || '1d';
  } catch { /* Storage may be blocked; use the same defaults as the table. */ }
  const needs = dataNeeds(columns, period);
  if (needs.changes) paths.push('/api/market/changes');
  if (needs.financials) paths.push('/api/market/financials');
  if (needs.ratios) paths.push('/api/market/ratios');
  if (needs.multiples) paths.push('/api/market/multiples?view=board');
  const requests = new Map();
  browser.__uzMarketStartup = {
    pathname: browser.location.pathname, at: browser.performance.now(), requests,
  };
  for (const path of paths) {
    // These endpoints are public and return the same data for every account.
    // Handle failures immediately; the app will retry through its normal fetch.
    requests.set(path, browser.fetch(path).then(response => response.ok ? response : null).catch(() => null));
  }
  for (const href of modules) {
    const link = browser.document.createElement('link');
    link.rel = 'modulepreload';
    link.href = href;
    link.crossOrigin = '';
    browser.document.head.appendChild(link);
  }
}

export async function requestMarketData(path, fetcher = fetch, browser = globalThis) {
  const startup = browser.__uzMarketStartup;
  const pending = startup?.requests.get(path);
  if (pending) {
    // One use only. Returning to the page and explicit refresh always follow
    // normal freshness rules; an old document cannot seed a new market visit.
    startup.requests.delete(path);
    const age = browser.performance.now() - startup.at;
    if (startup.pathname === browser.location.pathname && age >= 0 && age < 30_000) {
      const response = await pending;
      if (response) return response;
    }
  }
  return fetcher(path);
}
