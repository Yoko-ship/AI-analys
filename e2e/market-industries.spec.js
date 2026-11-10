import {test, expect} from '@playwright/test';
import {selectLanguage, toggleTheme} from './language-control.js';
import {openIndustryChooser, chooseIndustry} from './industry-control.js';

const tickers = ['IPTB', 'IPTBP', 'UZNF', 'DORI', 'CBSK', 'PLST', 'PLSTP', 'UZGF', 'UZGFP', 'ORGS', 'UVGT', 'MIQE', 'BNGP', 'BNGPP', 'NEW'];
const preferred = new Set(['IPTBP', 'PLSTP', 'UZGFP', 'BNGPP']);
async function openMarket(page, url = '/market') {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    sessionStorage.setItem('uz_sponsor_seen', '1');
    localStorage.setItem('uz_stock_analyzer_theme', 'light');
  });
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    let data = {ok: true};
    if (url.pathname === '/api/companies') data = {companies: tickers.map(ticker => ({ticker, company_name: `${ticker} issuer`, sector: 'other'}))};
    if (url.pathname === '/api/securities') data = {ok: true, securities: Object.fromEntries(tickers.map(ticker => [ticker, {
      ticker, type: 'stock', isin: `UZ-${ticker}`, sector: ['UZGF', 'UZGFP', 'PLST', 'PLSTP'].includes(ticker) ? 'mining' : ticker === 'DORI' ? 'manufacturing' : 'other',
      is_preferred: preferred.has(ticker),
    }]))};
    if (url.pathname === '/api/market/stocks') data = {stocks: tickers.map(ticker => ({ticker, name: `${ticker} issuer`, type: 'stock', isin: `UZ-${ticker}`,
      last_price: 110, close_price: 100, volume: 1e6, quantity: 100, trade_count: 2, last_trade_date: '2026-11-06'}))};
    if (url.pathname === '/api/auth/me') return route.fulfill({status: 401, json: {user: null}});
    if (url.pathname.startsWith('/api/price-history/')) data = {ok: true, points: [
      {date: '2026-11-04', close: 100}, {date: '2026-11-05', close: 105}, {date: '2026-11-06', close: 110},
    ]};
    return route.fulfill({json: data});
  });
  await page.goto(url);
  return errors;
}
const tiles = page => page.locator('.heatmap-tree-tile');

for (const width of [1440, 390]) test(`heatmap hover shows an industry quote card at ${width}px`, async ({page}, testInfo) => {
  await page.setViewportSize({width, height: 900});
  const errors = await openMarket(page, '/heatmap');
  await page.getByLabel('Площадь плитки').selectOption('equal');
  const tile = page.locator('.heatmap-tree-tile[data-ticker="IPTB"]');
  await tile.hover();
  const card = page.getByRole('dialog', {name: 'Обзор компании IPTB', exact: true});
  await expect(card).toBeVisible();
  await expect(card.locator('.heatmap-preview-industry')).toContainText('Банки');
  await expect(card.locator('.heatmap-preview-name')).toHaveText('IPTB issuer');
  await expect(card.locator('.heatmap-preview-price')).toContainText('110');
  await expect(card.locator('.heatmap-preview-change')).toContainText('+10');
  await expect(card.locator('[data-peer]')).toHaveCount(2);
  await expect(card.locator('[data-peer="IPTBP"]')).toBeVisible();
  await expect(card.locator('[data-peer="UZNF"]')).toHaveCount(0);
  await expect(card.locator('svg')).toHaveCount(2);
  await expect(page.locator('.heatmap-group-highlight')).toHaveAttribute('data-group', 'banks');
  await expect(tile).not.toHaveAttribute('title');
  await card.hover(); // Users can move into the card to read and scroll it.
  for (const theme of ['light', 'dark']) {
    await page.evaluate(theme => { document.body.dataset.theme = theme; document.documentElement.dataset.theme = theme; }, theme);
    const box = await card.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(8);
    expect(box.x + box.width).toBeLessThanOrEqual(width - 8);
    expect(box.y).toBeGreaterThanOrEqual(8);
    expect(box.y + box.height).toBeLessThanOrEqual(892);
    await page.screenshot({path: testInfo.outputPath(`heatmap-hover-${theme}.png`)});
  }
  await page.keyboard.press('Escape');
  await expect(card).toHaveCount(0);
  await expect(tile).toBeFocused();
  await tile.blur();
  await tile.focus();
  await expect(card).toBeVisible();
  await page.keyboard.press('ArrowDown');
  await expect(card.getByRole('button', {name: 'Закрыть обзор'})).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(card).toHaveCount(0);
  await page.locator('.heatmap-tree-tile[data-ticker="DORI"]').hover();
  const other = page.getByRole('dialog', {name: 'Обзор компании DORI', exact: true});
  await expect(other).toBeVisible();
  await expect(other.locator('[data-peer]')).toHaveCount(1);
  await page.mouse.move(0, 0);
  await expect(other).toHaveCount(0);
  await tile.click();
  await expect(page).toHaveURL(/\/company\/IPTB$/);
  expect(errors).toEqual([]);
});

for (const width of [1440, 390]) test(`market classifications filter table, map and totals at ${width}px`, async ({page}, testInfo) => {
  await page.setViewportSize({width, height: 1000});
  const errors = await openMarket(page);
  const select = page.locator('.market-industry-trigger');
  const menu = await openIndustryChooser(page);
  await expect(menu.locator('button[data-value="finance"]')).toContainText('Финансы и страхование');
  await expect(menu.locator('button[data-value="group:funds"]')).toContainText('Инвестиционные фонды');
  await chooseIndustry(page, 'group:banks');
  await expect(page.locator('.market-table tbody tr')).toHaveCount(2);
  await expect(page.locator('.market-table tbody')).toContainText('IPTBP');
  await expect(page.locator('.market-table tbody')).not.toContainText('UZNF');
  await page.locator('.market-view-toggle button[title="Карта рынка"]').click();
  await expect(tiles(page)).toHaveCount(2);
  await expect(select).toHaveAttribute('data-value', 'group:banks');
  await expect(page.locator('.market-stats-scope-chip')).toContainText('Банки');
  await expect(page.locator('.market-stat-card.is-turnover > strong')).toHaveText('2M');
  await chooseIndustry(page, 'finance');
  await expect(tiles(page)).toHaveCount(3);
  await expect(page.locator('.heatmap-tree-subgroup[data-group="banks"]')).toContainText('Банки');
  await expect(page.locator('.heatmap-tree-subgroup[data-group="funds"]')).toContainText('Инвестиционные фонды');
  await chooseIndustry(page, 'group:geophysics');
  await expect(tiles(page)).toHaveCount(2);
  await expect(tiles(page).first()).toHaveAttribute('data-sector', 'professional');
  await page.locator('.market-subtype-control').getByRole('button', {name: 'Привилегированные', exact: true}).click();
  await expect(tiles(page)).toHaveCount(1);
  await expect(tiles(page)).toHaveAttribute('data-ticker', 'UZGFP');
  await page.locator('.market-subtype-control').getByRole('button', {name: 'Все', exact: true}).click();
  await chooseIndustry(page, 'group:funds');
  await page.locator('.market-subtype-control').getByRole('button', {name: 'Привилегированные', exact: true}).click();
  await expect(tiles(page)).toHaveCount(0);
  await expect(select).toHaveAttribute('data-value', 'group:funds');
  await expect(page.locator('.heatmap-empty-state')).toContainText('Нет бумаг под выбранные фильтры');
  await page.locator('.heatmap-empty-state').getByRole('button', {name: 'Сбросить фильтры'}).click();
  await expect(tiles(page)).toHaveCount(tickers.length);
  await expect(select).toHaveAttribute('data-value', '');
  await page.getByLabel('Площадь плитки').selectOption('equal');
  for (const [ticker, sector, group] of [['DORI','trade','pharma-wholesale'], ['CBSK','trade','trading-complexes'], ['PLSTP','manufacturing','chemicals'], ['UZGF','professional','geophysics'], ['ORGS','construction','electrical-installation'], ['UVGT','manufacturing','rail-repair'], ['MIQE','mining','well-services'], ['NEW','other','']]) {
    const tile = page.locator(`.heatmap-tree-tile[data-ticker="${ticker}"]`);
    await expect(tile).toHaveAttribute('data-sector', sector);
    await expect(tile).toHaveAttribute('data-group', group);
  }
  for (const theme of ['light', 'dark']) {
    if (theme === 'dark') await toggleTheme(page);
    await openIndustryChooser(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const bounds = await menu.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(8);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width - 8);
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(1000 - 8);
    await page.screenshot({path: testInfo.outputPath(`industry-menu-${width}-${theme}.png`)});
    await page.keyboard.press('Escape');
    await expect(select).toBeFocused();
  }
  await openIndustryChooser(page);
  const search = menu.getByRole('searchbox');
  await expect(search).toBeFocused();
  await search.fill('гео');
  await expect(menu.locator('button[data-value="group:geophysics"]')).toBeVisible();
  await expect(menu.locator('button[data-value="group:banks"]')).toHaveCount(0);
  await search.fill('no-such-industry');
  await expect(menu.getByRole('status')).toHaveText('Ничего не найдено');
  await menu.getByRole('button', {name: 'Очистить поиск', exact: true}).click();
  await expect(search).toBeFocused();
  await expect(menu.locator('button[data-value="group:banks"]')).toBeVisible();
  await search.fill('Банки');
  await search.press('Tab'); // clear search
  await page.keyboard.press('Tab'); // all industries
  await page.keyboard.press('Tab'); // parent section
  await page.keyboard.press('Tab'); // subgroup
  await expect(menu.locator('button[data-value="group:banks"]')).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(select).toBeFocused();
  await expect(tiles(page)).toHaveCount(2);
  await openIndustryChooser(page);
  await expect(menu.locator('button[data-value="group:banks"]')).toHaveAttribute('aria-pressed', 'true');
  await page.keyboard.press('Escape');
  await selectLanguage(page, 'en');
  await chooseIndustry(page, 'group:pharma-wholesale');
  await expect(tiles(page)).toHaveCount(1);
  await expect(page.locator('.market-stats-scope-chip')).toContainText('Pharmaceutical wholesale');
  await selectLanguage(page, 'uz');
  await openIndustryChooser(page);
  await expect(menu.locator('button[data-value="group:banks"]')).toContainText('Banklar');
  expect(errors).toEqual([]);
});
