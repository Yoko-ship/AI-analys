import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const fixture = JSON.parse(readFileSync('e2e/fixtures/financial-columns.json', 'utf8'));
const original = JSON.parse(readFileSync('tests/fixtures/openinfo/iptb_2026q3_complete_rows.json', 'utf8'));

async function setup(page, { fail = false } = {}) {
  await page.addInitScript(() => {
    localStorage.setItem('uz_stock_analyzer_language', 'en');
    localStorage.setItem('uz_stock_analyzer_token', 'columns-admin');
  });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    const json = value => route.fulfill({ json: value });
    if (path === '/api/auth/me') return json({ user: { id: 1, is_admin: true } });
    if (path === '/api/catalog/companies') return json({ ok: true, total: 1, companies: [{ ticker: 'IPTB', company_name: 'Ipoteka bank', sector: 'finance' }] });
    if (path === '/api/catalog/index/IPTB') return json({ ok: true, company_name: 'Ipoteka bank', availability: { NSBU: { annual: [{ year: 2025 }], quarter: [{ year: 2026, quarter: 3 }] } } });
    if (path.endsWith('/financials/columns')) {
      if (fail) return route.fulfill({ status: 503, json: { detail: 'Source temporarily unavailable' } });
      const data = fixture[url.searchParams.get('freq') || 'annual'];
      if (url.searchParams.get('form') === 'MSFO') return json({ ...data, standard: 'MSFO', rows: [], ratios: [], source_forms: [], coverage: { complete: false, notes: 'missing', issues: ['NOTES_MISSING'] } });
      return json({ ...data, source_forms: [{ period_end: '2026-09-30', documents: [original] }] });
    }
    return json({ ok: true, companies: [], rows: [], items: [], series: {}, periods: [], rates: [], availability: {} });
  });
  await page.goto('/catalog?t=IPTB&f=PL');
}

test('source columns preserve units, periods and passports at desktop and mobile sizes', async ({ page }, testInfo) => {
  await setup(page);
  const terminal = page.getByTestId('financial-columns');
  await expect(terminal).toBeVisible();
  await terminal.getByRole('button', { name: '6M / 9M', exact: true }).click();
  await expect(terminal.locator('.fc-stats > div').filter({ hasText: 'Assets' })).toContainText('2026-09-30');
  const income = terminal.locator('tr[data-metric="interest_income"]').filter({ hasText: 'Итого' });
  await expect(income).toContainText('9,447,836,814');
  await expect(terminal.getByText('Amounts: thousands UZS', { exact: false })).toBeVisible();
  await income.getByRole('button').last().click();
  const passport = page.getByRole('dialog', { name: 'Source passport' });
  await expect(passport).toContainText('1л');
  await expect(passport).toContainText('separate');
  await expect(passport.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', /openinfo/);
  await passport.getByRole('button', { name: 'Close', exact: true }).click();
  await terminal.getByRole('button', { name: 'Chart', exact: true }).click();
  await expect(terminal.getByRole('img', { name: 'Financial history' })).toBeVisible();
  await terminal.getByRole('button', { name: 'Table', exact: true }).click();
  await terminal.getByRole('tab', { name: 'Original forms', exact: true }).click();
  await terminal.getByText('Complete original form', { exact: true }).click();
  await expect(terminal.getByRole('combobox', { name: 'Source document' })).toBeVisible();
  await expect(terminal.locator('.fc-documents')).toContainText('9447836814');
  await terminal.getByText('Complete original form', { exact: true }).click();
  await terminal.getByRole('searchbox').fill('1л');
  await expect(terminal.locator('tbody tr[data-metric]')).toHaveCount(1);
  await terminal.getByRole('button', { name: 'Reset', exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath('financial-columns-desktop.png'), fullPage: true, animations: 'disabled' });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(terminal.getByRole('button', { name: '6M / 9M', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('financial-columns-mobile.png'), fullPage: true, animations: 'disabled' });
});

test('changing standard clears source rows and gives an explicit missing-data state', async ({ page }) => {
  await setup(page);
  const terminal = page.getByTestId('financial-columns');
  await expect(terminal.locator('tr[data-metric="total_assets"]')).toBeVisible();
  await terminal.getByRole('button', { name: 'IFRS', exact: true }).click();
  await expect(terminal.locator('tr[data-metric="total_assets"]')).toHaveCount(0);
  await expect(terminal.getByText('No verified source rows in this accounting scope.')).toBeVisible();
  await expect(terminal.getByText('Notes are missing or have not been verified.')).toBeVisible();
  await terminal.getByRole('tab', { name: 'Data quality', exact: true }).click();
  await expect(terminal.locator('.fc-quality')).toContainText('Notes are missing or have not been verified.');
});

test('a failed financial source request can be retried without showing stale amounts', async ({ page }) => {
  await setup(page, { fail: true });
  const terminal = page.getByTestId('financial-columns');
  await expect(terminal.getByRole('alert')).toContainText('Could not load financial statements');
  await expect(terminal.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
  await expect(terminal.locator('tr[data-metric]')).toHaveCount(0);
});
