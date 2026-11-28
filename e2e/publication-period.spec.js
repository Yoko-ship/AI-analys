import { test, expect } from '@playwright/test';

test('filings identify the publication-date period fallback', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    localStorage.setItem('uz_stock_analyzer_language', 'en');
    localStorage.setItem('uz_stock_analyzer_token', 'admin-token');
  });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/me') return route.fulfill({ json: { user: { id: 1, is_admin: true } } });
    if (path === '/api/catalog/companies') return route.fulfill({ json: { ok: true,
      companies: [{ ticker: 'SQBN', company_name: 'SQB', total_count: 1 }] } });
    if (path.startsWith('/api/catalog/index/')) return route.fulfill({ json: { ok: true,
      company_name: 'SQB', availability: { NSBU: { annual: [], quarter: [
        { year: 2022, quarter: 3, period_source: 'publication_date', published_at: '2022-09-14' },
      ] } } } });
    return route.fulfill({ json: { ok: true, items: [], rows: [], companies: [], periods: [], series: {},
      companies_synced: 1, total_reports: 1 } });
  });
  await page.goto('/catalog?f=CF&t=SQBN');
  const filing = page.locator('.catalog-report-select').filter({ hasText: '2022' });
  await expect(filing).toContainText('Q3');
  await expect(filing).toContainText('Based on publication date');
  await page.screenshot({ path: testInfo.outputPath('publication-period.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(filing).toContainText('Based on publication date');
  await filing.scrollIntoViewIfNeeded();
  await filing.evaluate(element => {
    for (let parent = element.parentElement; parent; parent = parent.parentElement) parent.scrollLeft = 0;
  });
  await expect(filing).toBeInViewport();
  await filing.screenshot({ path: testInfo.outputPath('publication-period-mobile.png') });
});
