import { test, expect } from '@playwright/test';

const cases = [
  { width: 1440, theme: 'dark', language: 'ru', title: /Открытый\s*рынок/ },
  { width: 1440, theme: 'light', language: 'ru', title: /Открытый\s*рынок/ },
  { width: 320, theme: 'dark', language: 'ru', title: /Открытый\s*рынок/ },
  { width: 390, theme: 'light', language: 'ru', title: /Открытый\s*рынок/ },
  { width: 1440, theme: 'light', language: 'en', title: /The open\s*market/ },
  { width: 1440, theme: 'dark', language: 'uz', title: /Ochiq\s*bozor/ },
];

for (const { width, theme, language, title } of cases) {
  test(`original landing at ${width}px, ${theme}, ${language}`, async ({ page }, testInfo) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.addInitScript(({ theme, language }) => {
      localStorage.setItem('uz_stock_analyzer_theme', theme);
      localStorage.setItem('uz_stock_analyzer_language', language);
      localStorage.setItem('uz_track_internal', '1');
      sessionStorage.setItem('uz_sponsor_seen', '1');
    }, { theme, language });
    const stocks = ['UZTL', 'HMKB', 'AGBA', 'KVTS'].map((ticker, i) => ({
      ticker, name: `${ticker} issuer`, type: 'stock', last_price: 100 + i,
      close_price: 90, volume: 1000000, quantity: 1000, last_trade_date: '2026-10-26',
    }));
    await page.route('**/api/**', route => {
      const path = new URL(route.request().url()).pathname;
      const payload = path === '/api/market/stocks' ? { stocks }
        : path === '/api/companies' ? { companies: stocks.map(s => ({ ...s, company_name: s.name })) }
        : path === '/api/securities' ? { securities: Object.fromEntries(stocks.map(s => [s.ticker, s])) }
        : path === '/api/news/feed' ? { items: [{ id: 6570, title: 'UZStock market update', published_at: '2026-10-26', source: 'OpenInfo' }] }
        : { items: [], stats: {}, series: {}, changes: {} };
      return route.fulfill({ json: { ok: true, ...payload } });
    });
    await page.goto(language === 'uz' ? '/uz' : '/');
    const landing = page.locator('.landing-view');
    await expect(landing.getByRole('heading', { level: 1 })).toHaveText(title);
    const sky = landing.locator('canvas');
    await expect(sky).toBeVisible();
    await expect.poll(() => sky.evaluate(canvas => {
      const { width, height } = canvas;
      return width > 0 && height > 0 && canvas.getContext('2d').getImageData(0, 0, 1, 1).data[3] > 0;
    })).toBe(true);
    expect((await landing.locator('.lv-stage').boundingBox()).height).toBeGreaterThan(400);
    await expect(landing.locator('.lv-table tbody tr')).toHaveCount(4);
    await expect(landing.locator('.lv-company-card')).toContainText('UZTL');
    await expect(landing.locator('.lv-news-card')).toContainText('UZStock market update');
    await expect(landing.locator('.lv-step')).toHaveCount(3);
    await expect(landing.locator('.lv-cta')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('landing.png'), fullPage: true });

    await landing.locator('.lv-actions button').click();
    await expect(page.locator('.view-market')).toBeVisible();
    await page.goBack();
    await landing.locator('.lv-company-card').press('Enter');
    await expect(page).toHaveURL(/company\/UZTL/);
    await page.goBack();
    await landing.locator('.lv-news-card').click();
    await expect(page).toHaveURL(/news\/6570/);
    expect(errors).toEqual([]);
  });
}
