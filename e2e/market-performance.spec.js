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
