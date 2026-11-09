import { test, expect } from '@playwright/test';
import { landingStocks, setupLanding } from './landing-fixtures.js';
import { selectLanguage } from './language-control.js';

const cases = [
  { width: 1440, theme: 'dark', language: 'ru', title: 'Большая картина. За каждой компанией.' },
  { width: 1440, theme: 'light', language: 'ru', title: 'Большая картина. За каждой компанией.' },
  { width: 320, theme: 'dark', language: 'ru', title: 'Большая картина. За каждой компанией.' },
  { width: 390, theme: 'light', language: 'ru', title: 'Большая картина. За каждой компанией.' },
  { width: 768, theme: 'light', language: 'ru', title: 'Большая картина. За каждой компанией.' },
  { width: 1440, theme: 'light', language: 'en', title: 'The bigger picture. Behind every company.' },
  { width: 390, theme: 'dark', language: 'uz', title: 'Katta manzara. Har bir kompaniya ortida.' },
];
for (const options of cases) {
  test(`illustrated homepage at ${options.width}px, ${options.theme}, ${options.language}`, async ({ page }, testInfo) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await setupLanding(page, options);
    await page.goto(options.language === 'uz' ? '/uz' : '/');
    const landing = page.locator('.landing-view');
    await expect(landing.getByRole('heading', { level: 1 })).toHaveText(options.title);
    await expect(page.locator('header.topbar')).toHaveCount(1);
    await expect(page.locator('.topbar .brand-icon')).toBeVisible();
    await expect(landing.locator('.landing-steps > *')).toHaveCount(4);
    await expect(landing.locator('.landing-sector-card')).toHaveCount(3);
    const artwork = landing.locator('.landing-hero-art img');
    await expect(artwork).toBeVisible();
    await expect.poll(() => artwork.evaluate(img => img.complete && img.naturalWidth >= 1536)).toBe(true);
    await expect(artwork).toHaveCSS('object-fit', 'contain');
    const primary = landing.locator('.landing-hero-primary');
    await expect(primary).toBeInViewport();
    expect((await primary.boundingBox()).height).toBeGreaterThanOrEqual(44);
    if (options.width <= 800) {
      const artBox = await artwork.boundingBox(), buttonBox = await primary.boundingBox();
      expect(artBox.y).toBeGreaterThanOrEqual(buttonBox.y + buttonBox.height);
    }
    await expect(landing.locator('.landing-market tbody tr')).toHaveCount(5);
    const companyLogo = landing.locator('.landing-market img[src="/logos/HMKB_MARK.png"]');
    await companyLogo.scrollIntoViewIfNeeded();
    await expect(companyLogo).toBeVisible();
    await expect(companyLogo).toHaveAttribute('src', '/logos/HMKB_MARK.png');
    await expect.poll(() => companyLogo.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
    await expect(companyLogo).toHaveCSS('object-fit', 'contain');
    expect(await landing.locator('.landing-table-wrap').evaluate(table => table.scrollWidth <= table.clientWidth)).toBe(true);
    await expect(landing.locator('.landing-market')).not.toContainText('BOND');
    await expect(landing.locator('.landing-news-row')).toHaveCount(1);
    const guide = landing.locator('.landing-about');
    await expect(guide.locator('.landing-company-example')).toBeVisible();
    await expect(guide.getByRole('heading', { level: 3 })).toHaveText('Хамкорбанк');
    await expect(guide.locator('.landing-example-price')).toContainText('118');
    await expect(guide.locator('time')).toHaveAttribute('datetime', '2026-11-06');
    expect(await guide.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await guide.screenshot({ path: testInfo.outputPath('company-guide.png') });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('homepage.png'), fullPage: true });
    await landing.locator('.landing-market').screenshot({ path: testInfo.outputPath('company-logos.png') });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath('viewport.png') });
    for (const selector of ['.landing-about .landing-primary', '.landing-hero-primary', '.landing-hero-secondary']) {
      await landing.locator(selector).click();
      await expect(page).toHaveURL(options.language === 'uz' ? /\/uz\/market$/ : /\/market$/);
      await expect(page.locator('.view-market')).toBeVisible();
      if (selector === '.landing-about .landing-primary') await page.screenshot({ path: testInfo.outputPath('discover-market.png') });
      await page.goBack();
      await expect(landing.getByRole('heading', { level: 1 })).toHaveText(options.title);
    }
    expect(errors).toEqual([]);
  });
}

test('unavailable company logos keep a readable fallback and company navigation', async ({ page }) => {
  await setupLanding(page);
  await page.route('**/logos/UZTL_MARK.svg', route => route.fulfill({ status: 404, body: '' }));
  await page.goto('/');
  const market = page.locator('.landing-market');
  const failedLogoCompany = market.locator('tbody tr').filter({ hasText: 'UZTL' });
  await failedLogoCompany.scrollIntoViewIfNeeded();
  await expect(failedLogoCompany.locator('.chip-logo-fallback')).toHaveText('UZ');
  await expect(failedLogoCompany.locator('img')).toHaveCount(0);
  await expect(market.locator('tbody tr').filter({ hasText: 'MIQE' }).locator('.chip-logo-fallback')).toHaveText('MI');
  await market.locator('.landing-company').filter({ hasText: 'UZTL' }).click();
  await expect(page).toHaveURL(/\/company\/UZTL$/);
});

test('compact wordmarks use their emblem and stay legible on dark rows', async ({ page }) => {
  await setupLanding(page);
  const security = { ticker: 'URTS', name: 'UzEx', type: 'stock', last_price: 12940, logo_url: '/logos/URTS.svg' };
  await page.route('**/api/market/stocks?*', route => route.fulfill({ json: { ok: true, stocks: [security] } }));
  await page.route('**/api/securities', route => route.fulfill({ json: { ok: true, securities: { URTS: security } } }));
  await page.goto('/');
  const logo = page.locator('.landing-market').locator('tbody tr').filter({ hasText: 'URTS' }).locator('img');
  await logo.scrollIntoViewIfNeeded();
  await expect.poll(() => logo.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  await expect(logo).toHaveCSS('object-fit', 'cover');
  await expect(logo).toHaveCSS('object-position', '0% 50%');
  await expect(logo).toHaveCSS('background-color', 'rgb(255, 255, 255)');
});

test('sector cards and search use real quotes and open the selected company', async ({ page }) => {
  await setupLanding(page);
  await page.goto('/');
  const market = page.locator('.landing-market');
  await expect(market.locator('tr').filter({ hasText: 'MIQE' })).toContainText('2 401');
  await page.locator('.landing-sector-card').filter({ hasText: 'Финансы' }).click();
  await expect(market.locator('tbody tr')).toHaveCount(2);
  await market.getByLabel('Поиск компании или тикера').fill('grbk');
  await expect(market.locator('tbody tr')).toHaveCount(1);
  await expect(market.locator('tbody tr')).toContainText('4 315');
  await market.getByLabel('Поиск компании или тикера').fill('нет-компании');
  await expect(market.getByRole('status')).toContainText('Компании не найдены');
  await market.getByRole('button', { name: 'Сбросить фильтры' }).click();
  await expect(market.locator('tbody tr')).toHaveCount(5);
  await market.locator('.landing-company').filter({ hasText: 'GRBK' }).click();
  await expect(page).toHaveURL(/\/company\/GRBK$/);
});

test('shared language control translates the whole homepage and preserves navigation', async ({ page }) => {
  await setupLanding(page);
  await page.goto('/');
  await selectLanguage(page, 'en');
  await expect(page.locator('.lv-h1')).toHaveText('The bigger picture. Behind every company.');
  await expect(page.locator('.landing-sector-card').first()).toContainText('Finance');
  await expect(page.locator('.landing-news-row')).toContainText('Companies publish annual results');
  await selectLanguage(page, 'uz');
  await expect(page).toHaveURL(/\/uz\/?$/);
  await expect(page.locator('.lv-h1')).toHaveText('Katta manzara. Har bir kompaniya ortida.');
  await page.reload();
  await expect(page.locator('.landing-sector-card').first()).toContainText('Moliya');
  await page.locator('.landing-hero-secondary').click();
  await expect(page).toHaveURL(/\/uz\/market$/);
});

test('news list and event shortcut open the actual article and calendar', async ({ page }) => {
  await setupLanding(page);
  await page.goto('/');
  await page.locator('.landing-news-row').click();
  await expect(page).toHaveURL(/\/news\/6570$/);
  await page.goBack();
  await page.locator('.landing-steps').getByRole('button', { name: /Следите за событиями/ }).click();
  await expect(page).toHaveURL(/\/news\?tab=calendar$/);
});

test('failed data has a retry and never fabricates quotes or news', async ({ page }) => {
  await setupLanding(page);
  await page.route('**/api/market/stocks?*', route => route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } }));
  await page.route('**/api/news/feed?*', route => route.fulfill({ status: 503, json: { ok: false } }));
  await page.goto('/');
  await expect(page.locator('.landing-market tbody tr')).toHaveCount(0);
  await expect(page.locator('.landing-ticker-links button')).toHaveCount(0);
  await expect(page.locator('.landing-company-example')).toHaveCount(0);
  await expect(page.locator('.landing-market').getByRole('alert')).toContainText('Не удалось загрузить котировки');
  await expect(page.locator('.landing-news').getByRole('alert')).toContainText('Не удалось загрузить новости');
  await page.unroute('**/api/market/stocks?*');
  await page.unroute('**/api/news/feed?*');
  await page.locator('.landing-market').getByRole('button', { name: 'Повторить' }).click();
  await page.locator('.landing-news').getByRole('button', { name: 'Повторить' }).click();
  await expect(page.locator('.landing-market tbody tr')).toHaveCount(5);
  await expect(page.locator('.landing-ticker-links button')).toHaveText(['HMKB', 'UZMT', 'UZTL']);
  await expect(page.locator('.landing-company-example')).toContainText('HMKB');
  await expect(page.locator('.landing-news-row')).toHaveCount(1);
});

test('the company guide uses the current market example and opens its company page', async ({ page }) => {
  await setupLanding(page);
  const stocks = landingStocks.map(row => row.ticker === 'GRBK' ? { ...row, volume: 1200000 } : row);
  await page.route('**/api/market/stocks?*', route => route.fulfill({ json: { ok: true, stocks } }));
  await page.goto('/');
  const guide = page.locator('.landing-about');
  await expect(guide.getByRole('heading', { level: 3 })).toHaveText('Гарант банк');
  await expect(guide.locator('.landing-example-price')).toContainText('4 315');
  await expect(guide.locator('.landing-example-turnover')).toContainText('1,20 млн');
  await guide.locator('.landing-example-open').click();
  await expect(page).toHaveURL(/\/company\/GRBK$/);
});

test('sector shortcuts update with turnover leaders and open the selected company', async ({ page }, testInfo) => {
  await setupLanding(page);
  let stocks = landingStocks.map(row => row.ticker === 'GRBK' ? { ...row, volume: 1200000 } : row);
  await page.route('**/api/market/stocks?*', route => route.fulfill({ json: { ok: true, stocks } }));
  await page.goto('/');
  const shortcuts = page.locator('.landing-ticker-links');
  await expect(shortcuts.getByRole('button')).toHaveText(['GRBK', 'UZMT', 'UZTL']);
  await expect(page.locator('.landing-ticker-note')).toHaveText('Лидеры отраслей по обороту');
  await expect(shortcuts.getByRole('button', { name: 'GRBK', exact: true })).toHaveAttribute('title', /Финансы.*06\.11\.2026/);
  await page.locator('.landing-sector-intro').screenshot({ path: testInfo.outputPath('dynamic-shortcuts.png') });
  await shortcuts.getByRole('button', { name: 'GRBK', exact: true }).click();
  await expect(page).toHaveURL(/\/company\/GRBK$/);
  stocks = landingStocks.map(row => row.ticker === 'UZTL' ? { ...row, last_trade_date: '2026-11-05' } : row);
  await page.goBack();
  await expect(shortcuts.getByRole('button')).toHaveText(['HMKB', 'UZMT']);
  await page.reload();
  await expect(shortcuts.getByRole('button')).toHaveText(['HMKB', 'UZMT']);
  await expect(page.locator('.landing-sector-card')).toHaveCount(3);
});

test('homepage remains usable if artwork fails', async ({ page }) => {
  await setupLanding(page);
  await page.route('**/*tashkent-economy*.webp', route => route.abort());
  await page.goto('/');
  await expect(page.locator('.lv-h1')).toBeVisible();
  await page.locator('.landing-hero-secondary').click();
  await expect(page).toHaveURL(/\/market$/);
});

test('the quote preview puts recent sessions before large historic trades', async ({ page }) => {
  await setupLanding(page);
  await page.route('**/api/market/stocks?*', route => route.fulfill({ json: { ok: true, stocks: [
    ...landingStocks,
    { ticker: 'DRBK', name: 'Davr-bank', type: 'stock', last_price: 5000, close_price: 5000, volume: 100000000000, quantity: 10000, last_trade_date: '2019-10-31' },
  ] } }));
  await page.goto('/');
  const market = page.locator('.landing-market');
  await expect(market.locator('tbody tr').first()).toContainText('HMKB');
  await market.getByLabel('Поиск компании или тикера').fill('DRBK');
  await expect(market.locator('tbody tr')).toHaveCount(1);
  await expect(market.locator('tbody tr')).toContainText('31.10.2019');
});
