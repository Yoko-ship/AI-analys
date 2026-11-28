import {test, expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {openBoard, row} from './helpers/market-board.js';

const securities = JSON.parse(readFileSync('tests/fixtures/uztl_share_classes.json', 'utf8')).securities;
const stocks = Object.entries(securities).map(([ticker, security]) => ({
  ...row(ticker, ticker === 'UZTL' ? 20980 : 12680, 12000, 1000000), ...security,
  name:'Uzbektelecom', last_trade_date:'2026-10-28',
}));
const body = page => page.locator('.market-table-wrap tbody');
const tickers = page => body(page).locator('.market-ticker-btn');
const frames = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

// Actual November 26/27 closes from OpenInfo, matched by share-class ISIN.
const screenshotStocks = [
  {...row('UZMK', 8597, 8565, 28722391.55), isin:'UZ7021720006', last_trade_date:'2026-11-26'},
  {...row('UZML', 35900, 36000, 35900), isin:'UZ7055630006', last_trade_date:'2026-11-26'},
];
const collectedStocks = [
  {...screenshotStocks[0], last_price:8700, close_price:8597, last_trade_date:'2026-11-27'},
  screenshotStocks[1],
];
const companyRow = (page, ticker) => body(page).locator('tr').filter({has:page.getByText(ticker,{exact:true})});

for (const width of [1280,390]) test(`returning to an open market tab loads collected prices without changing quiet-stock dates at ${width}px`, async ({page}, info) => {
  await page.setViewportSize({width,height:950});
  await page.clock.install();
  const errors = await openBoard(page, ['date'], null, null, screenshotStocks);
  await expect(companyRow(page,'UZMK')).toContainText(/8\s*597/);
  let reads=0;
  await page.route('**/api/market/stocks?*', route => {
    reads++;
    expect(new URL(route.request().url()).searchParams.has('refresh')).toBe(false);
    return route.fulfill({json:{stocks:collectedStocks,count:2}});
  });
  await page.clock.fastForward(16_000);
  await page.evaluate(() => {
    window.dispatchEvent(new Event('focus'));
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(companyRow(page,'UZMK')).toContainText(/8\s*700/);
  await expect(companyRow(page,'UZMK')).toContainText('2026-11-27');
  await expect(companyRow(page,'UZML')).toContainText('2026-11-26');
  await expect(companyRow(page,'UZML')).toContainText(/35\s*900/);
  expect(reads).toBe(1);
  expect(errors).toEqual([]);
  await page.screenshot({path:info.outputPath('fresh-market.png'),fullPage:true});
});

test('visible market polling retries an unavailable read while preserving quotes and filters', async ({page}) => {
  await page.clock.install();
  const errors = await openBoard(page, ['date'], null, null, screenshotStocks);
  await page.locator('.market-hero-search input').fill('UZMK');
  let reads=0, unavailable=true;
  await page.route('**/api/market/stocks?*', route => {
    reads++;
    return route.fulfill({status:unavailable?503:200,json:unavailable?{detail:'Temporary outage'}:{stocks:collectedStocks,count:2}});
  });
  await page.evaluate(() => Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'}));
  await page.clock.fastForward(60_000);
  expect(reads).toBe(0);
  await page.evaluate(() => Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'}));
  await page.clock.fastForward(60_000);
  await expect.poll(()=>reads).toBe(1);
  await expect(companyRow(page,'UZMK')).toContainText(/8\s*597/);
  await expect(page.getByText('Temporary outage',{exact:true})).toHaveCount(0);
  unavailable=false;
  await page.clock.fastForward(60_000);
  await expect(companyRow(page,'UZMK')).toContainText(/8\s*700/);
  await expect(page.locator('.market-hero-search input')).toHaveValue('UZMK');
  await expect(tickers(page)).toHaveText(['UZMK']);
  expect(reads).toBe(2);
  expect(errors).toEqual([]);
});

test('search and column controls leave unchanged UZTL price cells alone', async ({page}) => {
  await page.addInitScript(() => {
    window.priceFormats = 0;
    Intl.NumberFormat = new Proxy(Intl.NumberFormat, {construct(target, args) {
      const formatter = Reflect.construct(target, args);
      return new Proxy(formatter, {get(target, key) {
        if (key === 'format') return value => {
          if (value === 20980 || value === 12680) window.priceFormats++;
          return formatter.format(value);
        };
        return Reflect.get(target, key, target);
      }});
    }});
  });
  await openBoard(page, ['volume', 'date'], null, null, stocks);
  await frames(page);
  const before = await page.evaluate(() => window.priceFormats);
  expect(before).toBeGreaterThan(0);
  await page.locator('.market-cols-btn').click();
  await page.locator('.market-cols-search input').pressSequentially('Объём');
  await expect(page.getByRole('checkbox', {name:/^Объём/}).first()).toBeVisible();
  await page.keyboard.press('Escape');
  await page.locator('.market-hero-search input').pressSequentially('UZ');
  await expect(tickers(page)).toHaveCount(2);
  await page.locator('.market-table-wrap th[data-sort-key="last"]').click();
  await expect(tickers(page)).toHaveText(['UZTL','UZTLP']);
  await page.locator('.market-table-wrap th[data-sort-key="last"]').click();
  await expect(tickers(page)).toHaveText(['UZTLP','UZTL']);
  await frames(page);
  expect(await page.evaluate(() => window.priceFormats)).toBe(before);
  // Filtering still changes the result, and a retained row still opens its issuer.
  await page.locator('.market-hero-search input').fill('UZTLP');
  await expect(tickers(page)).toHaveText(['UZTLP']);
  await tickers(page).click();
  await expect(page).toHaveURL(/company\/UZTLP/);
});

test('ordinary and preferred filters reuse stock data while explicit refresh updates prices', async ({page}) => {
  const requests = [];
  page.on('request', r => {if (/\/api\/(market\/|instruments)/.test(r.url())) requests.push(new URL(r.url()).pathname + new URL(r.url()).search);});
  await openBoard(page, ['volume','date'], null, null, stocks, {admin:true});
  await expect(tickers(page)).toHaveCount(2);
  await expect(page.locator('.market-hero-actions .ghost-btn')).toBeEnabled();
  await frames(page);
  const before = requests.length;
  for (const [name, expected] of [['Обыкновенные',['UZTL']],['Привилегированные',['UZTLP']],['Все',['UZTL','UZTLP']]]) {
    await page.locator('.market-subtype-control').getByRole('button', {name, exact:true}).click();
    await expect(tickers(page)).toHaveText(expected);
  }
  await frames(page);
  expect(requests.slice(before)).toEqual([]);
  await page.route('**/api/market/stocks?*', route => route.fulfill({json:{stocks:stocks.map(stock => ({...stock,last_price:stock.last_price+100})),count:2}}));
  const refreshed = page.waitForRequest('**/api/market/stocks?type=stock&refresh=true');
  await page.locator('.market-hero-actions .ghost-btn').click();
  await refreshed;
  await expect(body(page).locator('tr').filter({has:page.getByText('UZTL',{exact:true})})).toContainText(/21\s*080/);
  await expect(body(page).locator('tr').filter({has:page.getByText('UZTLP',{exact:true})})).toContainText(/12\s*780/);
});
