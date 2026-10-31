import { test, expect } from '@playwright/test';

const cases = [
  { width: 1440, theme: 'dark', language: 'ru', title: /За каждой\s*акцией —\s*компания\./ },
  { width: 1440, theme: 'light', language: 'ru', title: /За каждой\s*акцией —\s*компания\./ },
  { width: 320, theme: 'dark', language: 'ru', title: /За каждой\s*акцией —\s*компания\./ },
  { width: 390, theme: 'light', language: 'ru', title: /За каждой\s*акцией —\s*компания\./ },
  { width: 768, theme: 'light', language: 'ru', title: /За каждой\s*акцией —\s*компания\./ },
  { width: 1440, theme: 'light', language: 'en', title: /Behind every\s*share is\s*a company\./ },
  { width: 390, theme: 'dark', language: 'uz', title: /Har bir aksiya\s*ortida —\s*kompaniya\./ },
];

for (const { width, theme, language, title } of cases) {
  test(`glass landing at ${width}px, ${theme}, ${language}`, async ({ page }, testInfo) => {
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
    const artwork = landing.locator('.landing-hero-art img');
    await expect(artwork).toBeVisible();
    await expect.poll(() => artwork.evaluate(img => img.complete && img.naturalWidth > 600)).toBe(true);
    await expect(landing.locator('canvas')).toHaveCount(0);
    const primary = landing.locator('.lv-actions button');
    await expect(primary).toBeInViewport();
    const buttonBox = await primary.boundingBox();
    expect(buttonBox.height).toBeGreaterThanOrEqual(44);
    expect(buttonBox.x).toBeGreaterThanOrEqual(0);
    expect(buttonBox.x + buttonBox.width).toBeLessThanOrEqual(width);
    const headlineBox = await landing.locator('h1').boundingBox();
    expect(headlineBox.x + headlineBox.width).toBeLessThanOrEqual(width);
    await expect(page.locator('.topbar .brand-icon')).toBeVisible();
    await expect(page.locator('.topbar-brand')).toHaveAttribute('aria-label', /^UZStock/);
    if (width > 360) await expect(page.locator('.topbar .brand-title')).toBeVisible();
    const iconContrast = await page.locator('.theme-toggle strong').evaluate(el => {
      const luminance = color => color.match(/[\d.]+/g).slice(0, 3).map(Number).map(v => {
        const c = v / 255;
        return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      }).reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
      const a = luminance(getComputedStyle(el).color);
      const b = luminance(getComputedStyle(el.closest('.topbar')).backgroundColor);
      return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    });
    expect(iconContrast).toBeGreaterThanOrEqual(4.5);
    const artBox = await artwork.boundingBox();
    const calloutBox = await landing.locator('.landing-hero-company').boundingBox();
    const footerBox = await landing.locator('.landing-hero-footer').boundingBox();
    await expect(artwork).toHaveCSS('object-fit', 'contain');
    expect(artBox.y + artBox.height).toBeLessThanOrEqual(footerBox.y + 1);
    if (width <= 980) {
      expect(artBox.y).toBeGreaterThanOrEqual(buttonBox.y + buttonBox.height);
      const ratio = await artwork.evaluate(img => img.naturalWidth / img.naturalHeight);
      expect(Math.abs(artBox.width / artBox.height - ratio)).toBeLessThan(0.01);
      expect(calloutBox.y).toBeGreaterThanOrEqual(artBox.y + artBox.height);
    }
    await expect(landing.locator('.landing-hero-shade')).toHaveCount(0);
    expect(await landing.locator('.landing-hero-art').evaluate(el => getComputedStyle(el, '::after').backgroundImage)).toBe('none');
    await expect(landing.locator('.landing-hero-topics button')).toHaveCount(3);
    expect(await landing.locator('.lv-stage').evaluate(el => el.getAnimations({ subtree: true }).filter(a => a.playState === 'running').length)).toBe(0);
    expect((await landing.locator('.lv-stage').boundingBox()).height).toBeGreaterThan(400);
    await expect(landing.locator(':scope > *')).toHaveCount(1);
    await expect(landing.locator('.lv-table, .lv-tape-belt, .lv-movers, .lv-company-card, .lv-news-card, .lv-step, .lv-cta')).toHaveCount(0);
    await expect(page.locator('.app-footer')).toHaveCount(0);
    if (width >= 1180) expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('landing.png') });

    await landing.locator('.lv-actions button').click();
    await expect(page.locator('.view-market')).toBeVisible();
    await page.goBack();
    await landing.locator('.landing-hero-company').press('Enter');
    await expect(page).toHaveURL(/company\/UZTL/);

    expect(errors).toEqual([]);
  });
}

test('hero topics work with the keyboard and open the featured company', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('uz_stock_analyzer_language', 'ru');
    localStorage.setItem('uz_track_internal', '1');
  });
  await page.route('**/api/**', route => route.fulfill({ json: { ok: true, stocks: [], items: [] } }));
  await page.goto('/');
  const topics = page.locator('.landing-hero-topics button');
  await expect(topics.first()).toHaveAttribute('aria-pressed', 'true');
  await topics.nth(1).focus();
  await page.keyboard.press('Enter');
  await expect(topics.nth(1)).toHaveAttribute('aria-pressed', 'true');
  await expect(topics.first()).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('.lv-h1')).toHaveText(/За цифрами —\s*целая история\./);
  await topics.nth(2).press('Space');
  await expect(page.locator('.lv-h1')).toHaveText(/У каждой\s*выплаты —\s*своя история\./);
  await expect(page.locator('.landing-hero-note')).toHaveCount(0);
  await page.locator('.landing-hero-company').click();
  await expect(page).toHaveURL(/\/company\/UZTL$/);
  await page.goBack();
  await page.locator('.lv-actions button').click();
  await expect(page).toHaveURL(/\/market$/);
});

test('hero motion settles and the page stays usable when artwork fails', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('uz_track_internal', '1'));
  await page.route('**/api/**', route => route.fulfill({ json: {} }));
  await page.goto('/');
  const stage = page.locator('.lv-stage');
  await expect(page.locator('.landing-hero-art img')).toBeVisible();
  await expect.poll(() => stage.evaluate(el => el.getAnimations({ subtree: true }).filter(a => a.playState === 'running').length)).toBe(0);
  await page.route('**/*landing-glass*.webp', route => route.abort());
  await page.reload();
  await expect(page.locator('.lv-h1')).toBeVisible();
  await expect(page.locator('.lv-actions button')).toBeVisible();
  await page.locator('.lv-actions button').click();
  await expect(page).toHaveURL(/\/market$/);
});


test.describe('full-detail artwork on high-density mobile screens', () => {
  test.use({ deviceScaleFactor: 2 });
  for (const [width, theme] of [[390, 'light'], [768, 'dark']]) {
    test(`preserves the full source image at ${width}px ${theme}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await page.addInitScript(theme => {
        localStorage.setItem('uz_stock_analyzer_theme', theme);
        localStorage.setItem('uz_track_internal', '1');
      }, theme);
      await page.route('**/api/**', route => route.fulfill({ json: {} }));
      await page.goto('/');
      const image = page.locator('.landing-hero-art img');
      await image.evaluate(img => img.decode());
      const sourceWidth = await image.evaluate(async img => {
        const bitmap = await createImageBitmap(await (await fetch(img.currentSrc)).blob());
        const width = bitmap.width;
        bitmap.close();
        return width;
      });
      // The supplied artwork is 1586px wide; phones must not get a reduced 960px copy.
      expect(sourceWidth).toBeGreaterThanOrEqual(1586);
      await expect(image).toHaveCSS('filter', 'none');
    });
  }
});
