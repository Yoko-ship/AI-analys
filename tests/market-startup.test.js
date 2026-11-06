import {test} from 'node:test';
import assert from 'node:assert/strict';
import {runInNewContext} from 'node:vm';
import {marketDataNeeds} from '../frontend/src/lib/marketDataNeeds.js';
import {startMarketStartup, requestMarketData} from '../frontend/src/lib/marketStartup.js';

const stocks = '/api/market/stocks?type=stock';
function browser(pathname = '/market', fetcher = async () => new Response('{}')) {
  const requested = [], links = [];
  const scope = {location:{pathname}, performance:{now:() => 100},
    fetch:path => {requested.push(path); return fetcher(path);},
    document:{createElement:() => ({}), head:{appendChild:link => links.push(link)}},
  };
  return {scope, requested, links};
}

test('serialized startup starts public data and market modules on Russian and Uzbek market URLs', async () => {
  for (const path of ['/market', '/market/', '/uz/market', '/uz/market/']) {
    const {scope, requested, links} = browser(path);
    runInNewContext(`(${startMarketStartup.toString()})(window, ['/assets/MarketView-test.mjs'], ${marketDataNeeds.toString()});`, {window:scope});
    assert.deepEqual(requested, [stocks, '/api/companies', '/api/securities', '/api/market/trade-stats', '/api/instruments?view=board', '/api/market/changes']);
    assert.equal(links[0].rel, 'modulepreload');
    assert.equal(links[0].href, '/assets/MarketView-test.mjs');
    assert.equal(links[0].crossOrigin, '');
  }
});

test('other routes do not preload market data or code', () => {
  for (const path of ['/', '/uz', '/catalog', '/company/UZTL', '/bonds', '/marketplace']) {
    const {scope, requested, links} = browser(path);
    startMarketStartup(scope, ['/assets/MarketView-test.mjs'], marketDataNeeds);
    assert.deepEqual(requested, []);
    assert.deepEqual(links, []);
  }
});

test('a pending UZTL quote response is consumed once; refresh and later reads use the normal fetch', async () => {
  let release;
  const pending = new Promise(resolve => {release = resolve;});
  const {scope} = browser('/market', path => path === stocks ? pending : Promise.resolve(new Response('{}')));
  startMarketStartup(scope, [], marketDataNeeds);
  const normal = [];
  const fetcher = async path => {normal.push(path); return new Response('{"stocks":[]}');};
  const first = requestMarketData(stocks, fetcher, scope);
  assert.deepEqual(normal, []);
  release(new Response('{"stocks":[{"ticker":"UZTL","last_price":20980}]}'));
  assert.equal((await (await first).json()).stocks[0].last_price, 20980);
  await requestMarketData(stocks, fetcher, scope);
  await requestMarketData(stocks + '&refresh=true', fetcher, scope);
  assert.deepEqual(normal, [stocks, stocks + '&refresh=true']);
});

test('failed, expired and other-page startup responses fall back to the caller fetch', async () => {
  for (const kind of ['network', 'http', 'expired', 'navigation']) {
    const {scope} = browser('/market', async () => {
      if (kind === 'network') throw new Error('offline');
      return new Response('{}', {status:kind === 'http' ? 503 : 200});
    });
    startMarketStartup(scope, [], marketDataNeeds);
    if (kind === 'expired') scope.performance.now = () => 30_100;
    if (kind === 'navigation') scope.location.pathname = '/company/UZTL';
    const normal = [];
    const result = await requestMarketData(stocks, async path => {normal.push(path); return 'fresh';}, scope);
    assert.equal(result, 'fresh', kind);
    assert.deepEqual(normal, [stocks], kind);
  }
});


test('startup requests match visible history and financial columns without fetching hidden datasets', () => {
  for (const [columns, period, expected] of [
    [[], '1d', []],
    [['change1w'], '1d', ['/api/market/changes']],
    [['change1m'], '1d', ['/api/market/changes']],
    [['change'], '1m', ['/api/market/changes']],
    [['pe','pb','roe'], '1d', ['/api/market/multiples?view=board']],
    [['finRevenue','currentRatio','pe'], '1d', ['/api/market/financials','/api/market/ratios','/api/market/multiples?view=board']],
  ]) {
    const {scope, requested} = browser();
    scope.localStorage = {getItem:storageName => storageName === 'uz_market_cols_v3' ? JSON.stringify(columns) : period};
    startMarketStartup(scope, [], marketDataNeeds);
    assert.deepEqual(requested.slice(5), expected);
  }
  const {scope, requested} = browser();
  scope.localStorage = {getItem:() => '{invalid'};
  startMarketStartup(scope, [], marketDataNeeds);
  assert.deepEqual(requested.slice(5), ['/api/market/changes']);
  assert.equal(marketDataNeeds(['pe','change1w','currentRatio'], '1m', 'bond').multiples, false);
  assert.equal(marketDataNeeds(['pe','change1w','currentRatio'], '1m', 'bond').changes, true);
});
