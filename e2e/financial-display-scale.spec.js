import { test, expect } from '@playwright/test';

test('UZTL financial tables and charts use thousands while source passports keep original amounts', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    localStorage.setItem('uz_stock_analyzer_language', 'en');
    sessionStorage.setItem('uz_sponsor_seen', '1');
  });
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    let data = { ok: true, items: [], companies: [], securities: {} };
    if (url.pathname === '/api/company/UZTL/financials') data = {
      ok: true, periods: ['2025', '2024'], series: {
        net_revenue: { money: true, unit: 'UZS', values: { 2024: 8964716518000, 2025: 10512797471000 } },
        net_profit: { money: true, unit: 'UZS', values: { 2024: 41629721000, 2025: 590906080000 } },
        net_margin: { money: false, unit: '%', values: { 2024: 0.46, 2025: 5.62 } },
      },
    };
    if (url.pathname.endsWith('/financials/passport')) data = { ok: true, status: 'SOURCED', source: {
      normalized_value: 590906080000, raw_value: 590906080, unit_scale: 1000, currency: 'UZS', period_year: 2025,
    } };
    return route.fulfill({ json: data });
  });
  await page.goto('/company/UZTL?tab=financials');
  await page.getByRole('button', { name: 'Table', exact: true }).click();
  const view = page.locator('.company-financials');
  await expect(view.getByRole('button', { name: '10,512,797,471', exact: true })).toBeVisible();
  await expect(view.getByRole('button', { name: '590,906,080', exact: true })).toBeVisible();
  await expect(view.locator('.fin-note')).toContainText('thousands of UZS');
  await expect(view.locator('.fin-table thead th').first()).toContainText('thousands UZS');
  await expect(view.locator('.fin-table')).toContainText('5.62%');
  await expect(view.locator('.fin-table')).toContainText('+17.27%');
  await view.getByRole('button', { name: '590,906,080', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('590906080000');
  await expect(page.getByRole('dialog')).toContainText('×1000');
  await page.getByRole('button', { name: 'Close source passport' }).click();
  await page.screenshot({ path: testInfo.outputPath('uztl-thousands.png'), fullPage: true });
  await view.getByRole('button', { name: 'Bars', exact: true }).click();
  await expect(view.locator('svg')).toBeVisible();
  await expect(view.locator('.fin-note')).toContainText('thousands of UZS');
  await page.setViewportSize({ width: 390, height: 844 });
  await view.getByRole('button', { name: 'Table', exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('uztl-thousands-mobile.png'), fullPage: true });
});
