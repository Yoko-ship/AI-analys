import { test, expect } from '@playwright/test';
import { selectLanguage, toggleTheme } from './language-control.js';

const stocks = ['IPTB', 'IPTBP', 'DORI', 'PLST', 'PLSTP', 'UZGF', 'UZGFP', 'ORGS', 'CBSK', 'METQ', 'NEW'];
async function openDirectory(page) {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(() => sessionStorage.setItem('uz_sponsor_seen', '1'));
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    let data = { ok: true };
    if (url.pathname === '/api/companies') data = { companies: stocks.map(ticker => ({ticker, company_name: `${ticker} issuer`, sector: 'other'})) };
    if (url.pathname === '/api/securities') data = { ok: true, securities: Object.fromEntries([...stocks, 'BOND1'].map(ticker => [ticker, {
      ticker, type: ticker === 'BOND1' ? 'bond' : 'stock', sector: 'other', isin: `UZ-${ticker}`,
      is_preferred: ticker === 'IPTBP' || ticker === 'PLSTP',
    }])) };
    if (url.pathname === '/api/market/stocks') data = { stocks: stocks.map(ticker => ({ticker, type: 'stock', last_price: ticker === 'IPTBP' ? 9 : 3, close_price: 3, volume: 500, quantity: 5, trade_count: 1})) };
    if (url.pathname === '/api/auth/me') return route.fulfill({status: 401, json: {user: null}});
    return route.fulfill({json: data});
  });
  await page.goto('/issuers');
  return errors;
}

test('directory groups issuer share classes and filters by section, subgroup and ISIN', async ({page}) => {
  const errors = await openDirectory(page);
  const bank = page.locator('[data-issuer="IPTB"]');
  await expect(page.locator('[data-sector="finance"] [data-group="banks"]')).toContainText('Ipoteka-bank');
  await expect(bank.getByRole('button', {name: 'IPTB', exact: true})).toBeVisible();
  await expect(bank.getByRole('button', {name: 'IPTBP', exact: true})).toBeVisible();
  await expect(bank.locator('[data-ticker="IPTBP"]')).toContainText('9');
  await page.getByLabel('Поиск эмитентов').fill('UZ-IPTBP');
  await expect(page.locator('[data-issuer]')).toHaveCount(1);
  await expect(bank.getByRole('button', {name: 'IPTB', exact: true})).toBeVisible();
  await page.getByLabel('Поиск эмитентов').fill('');
  await page.getByLabel('Отрасль', {exact: true}).selectOption('construction');
  await expect(page.locator('[data-issuer="METQ"]')).toBeVisible();
  await expect(page.locator('[data-issuer="ORGS"]')).toContainText('Расхождение источников');
  await page.getByLabel('Подотрасль', {exact: true}).selectOption('electrical-networks');
  await expect(page.locator('[data-issuer="ORGS"]')).toHaveCount(0);
  await page.getByLabel('Отрасль', {exact: true}).selectOption('trade');
  await expect(page.getByLabel('Подотрасль', {exact: true})).toHaveValue('');
  await expect(page.locator('[data-issuer="DORI"]')).toBeVisible();
  await expect(page.locator('[data-issuer="CBSK"]')).toContainText('Требует проверки');
  await page.getByLabel('Поиск эмитентов').fill('not-an-issuer');
  await expect(page.getByText('Совпадений нет.', {exact: true})).toBeVisible();
  await page.getByLabel('Поиск эмитентов').fill('DORI');
  await page.getByRole('button', {name: 'DORI', exact: true}).click();
  await expect(page).toHaveURL(/\/company\/DORI$/);
  expect(errors).toEqual([]);
});

for (const width of [1280, 390]) test(`industry hierarchy is readable in both themes at ${width}px`, async ({page}, testInfo) => {
  await page.setViewportSize({width, height: 900});
  const errors = await openDirectory(page);
  await page.getByLabel('Поиск эмитентов').fill('UZGF');
  await expect(page.locator('[data-sector="professional"]')).toBeVisible();
  await page.locator('[data-issuer="UZGF"] summary').click();
  await expect(page.getByRole('link', {name: 'UZSE · 71120'})).toBeVisible();
  for (const theme of ['initial', 'alternate']) {
    if (theme === 'alternate') await toggleTheme(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path: testInfo.outputPath(`industry-${theme}.png`), fullPage: true});
  }
  await selectLanguage(page, 'en');
  await expect(page.getByLabel('Subgroup', {exact: true})).toBeVisible();
  await page.getByLabel('Search issuers').fill('NEW');
  await expect(page.locator('[data-issuer="NEW"]')).toBeVisible();
  await expect(page.locator('[data-issuer="BOND1"]')).toHaveCount(0);
  await selectLanguage(page, 'uz');
  await expect(page.getByLabel('Quyi tarmoq', {exact: true})).toBeVisible();
  expect(errors).toEqual([]);
});
