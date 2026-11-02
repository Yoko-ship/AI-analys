import { test, expect } from '@playwright/test';

const companies = [
  { ticker: 'SQBN', company_name: 'Узпромстройбанк', sector: 'finance' },
  { ticker: 'UZTL', tickers: ['UZTL', 'UZTLP'], company_name: 'O‘zbektelekom aksiyadorlik kompaniyasi', sector: 'telecom' },
];
const locales = {
  ru: { hint: 'Название компании или тикер', label: 'Поиск компании', open: 'Открыть', help: 'Справка терминала' },
  uz: { hint: 'Kompaniya nomi yoki tiker', label: 'Kompaniya qidiruvi', open: 'Ochish', help: 'Terminal yordami' },
  en: { hint: 'Company name or ticker', label: 'Company search', open: 'Open', help: 'Terminal help' },
};

async function setup(page, { lang = 'ru', theme = 'light', width = 1440 } = {}) {
  await page.setViewportSize({ width, height: 900 });
  await page.addInitScript(({ lang, theme }) => {
    localStorage.setItem('uz_stock_analyzer_token', 'admin-token');
    localStorage.setItem('uz_stock_analyzer_language', lang);
    localStorage.setItem('uz_stock_analyzer_theme', theme);
    localStorage.setItem('uz_track_internal', '1');
  }, { lang, theme });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    const json = body => route.fulfill({ json: body });
    if (path === '/api/auth/me') return json({ user: { id: 1, is_admin: true, email: 'admin@example.test' } });
    if (path === '/api/catalog/companies') return json({ ok: true, companies });
    if (path.startsWith('/api/catalog/index/')) return json({ ok: true, availability: { NSBU: { annual: [], quarter: [] } } });
    return json({ ok: true, items: [], rows: [], periods: [], series: {}, companies_synced: 2, total_reports: 0 });
  });
  await page.goto(`${lang === 'uz' ? '/uz' : ''}/catalog?t=SQBN&f=SUM`);
}

for (const [lang, copy] of Object.entries(locales)) {
  for (const [theme, width] of [['light', 1440], ['dark', 390]]) {
    test(`company search is clear and opens named results in ${lang}, ${theme}, ${width}px`, async ({ page }, testInfo) => {
      await setup(page, { lang, theme, width });
      const search = page.getByRole('combobox', { name: copy.label, exact: true });
      await expect(page.locator('.catalog-layout .catalog-search-field input')).toHaveCount(1);
      await expect(page.locator('.catalog-sidebar input[type="search"]')).toHaveCount(0);
      await expect(search).toHaveAttribute('placeholder', copy.hint);
      const form = page.getByRole('search', { name: copy.label });
      await expect(form.getByRole('button', { name: copy.open, exact: true })).toBeVisible();
      expect(await search.evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(14);
      // Browser transforms can produce a fractional-pixel rounding remainder.
      expect((await form.locator('.terminal-command-field').boundingBox()).height).toBeGreaterThanOrEqual(43.99);
      expect((await form.getByRole('button', { name: copy.open, exact: true }).boundingBox()).height).toBeGreaterThanOrEqual(43.99);
      await search.fill('O‘zbektelekom aksiyadorlik');
      await expect(page.locator('.catalog-company-item')).toHaveCount(1);
      await expect(page.locator('.catalog-company-item')).toContainText('UZTL');
      const result = page.getByRole('option', { name: /UZTL.*O‘zbektelekom/ });
      await expect(result).toBeVisible();
      await expect(result).toBeInViewport();
      await result.click();
      await expect(page).toHaveURL(/t=UZTL/);
      await expect(search).toHaveValue('');
      await expect(page.locator('.catalog-company-item')).toHaveCount(2);
      await expect(search).toHaveAttribute('aria-expanded', 'false');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      await page.locator('.catalog-layout').screenshot({ path: testInfo.outputPath('single-company-search.png') });
      await page.locator('.terminal-market-nav').getByRole('button', { name: /^HELP/ }).click();
      const help = page.getByRole('dialog', { name: copy.help });
      await expect(help).toBeVisible();
      await expect(help).toContainText('SQBN PL');
      await page.keyboard.press('Escape');
      await expect(help).toHaveCount(0);
    });
  }
}

test('company search supports Enter, keyboard suggestions, and existing commands', async ({ page }) => {
  await setup(page);
  const search = page.getByRole('combobox', { name: locales.ru.label });
  await search.fill(companies[1].company_name);
  await expect(page.getByRole('option', { name: /UZTL.*O‘zbektelekom/ })).toBeVisible();
  await search.press('Escape');
  await expect(search).toHaveValue(companies[1].company_name);
  await search.press('Enter');
  await expect(page).toHaveURL(/t=UZTL/);
  await search.fill('Узпром');
  await search.press('ArrowDown');
  await search.press('Enter');
  await expect(page).toHaveURL(/t=SQBN/);
  await expect(search).toHaveValue('');
  await search.fill('UZTL BS');
  await expect(page.locator('.catalog-company-item')).toHaveCount(1);
  await expect(page.locator('.catalog-company-item')).toContainText('UZTL');
  await search.press('Enter');
  await expect(page).toHaveURL(/t=UZTL&f=BS/);
  await search.fill('SQBX PL');
  await search.press('Enter');
  await expect(page.getByRole('status')).toContainText('SQBX');
  await expect(page).toHaveURL(/t=UZTL&f=BS/);
  await search.fill('SQBN B');
  await search.press('Tab');
  await expect(search).toHaveValue('SQBN BS ');
  await search.press('Enter');
  await expect(page).toHaveURL(/t=SQBN&f=BS/);
});

test('the single search filters aliases, clears results, and receives catalog shortcuts', async ({page}) => {
  await setup(page);
  const search = page.getByRole('combobox', {name: locales.ru.label});
  const list = page.locator('.catalog-company-list');
  await search.fill('  o‘zbektelekom   aksiyadorlik  ');
  await expect(list.locator('.catalog-company-item')).toHaveCount(1);
  await expect(list).toContainText('UZTL');
  await search.fill('UZTLP');
  await expect(list.locator('.catalog-company-item')).toHaveCount(1);
  await search.press('Enter');
  await expect(page).toHaveURL(/t=UZTL/);
  await expect(search).toHaveValue('');
  await expect(list.locator('.catalog-company-item')).toHaveCount(2);
  await search.fill('missing-issuer');
  await expect(list.locator('.catalog-company-item')).toHaveCount(0);
  await search.fill('');
  await expect(list.locator('.catalog-company-item')).toHaveCount(2);
  await search.blur();
  await page.keyboard.press('/');
  await expect(search).toBeFocused();
  await page.locator('.terminal-market-nav').getByRole('button', {name: /^EQS/}).click();
  await expect(page.locator('.catalog-sidebar')).toHaveCount(0);
  await page.locator('.terminal-market-nav').getByRole('button', {name: /^CAT/}).click();
  await expect(search).toBeFocused();
  await expect(page.locator('.catalog-sidebar')).toBeVisible();
  await expect(page.locator('.catalog-layout .catalog-search-field input')).toHaveCount(1);
});
