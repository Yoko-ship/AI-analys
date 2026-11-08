import { test, expect } from '@playwright/test';

test.beforeEach(async ({}, testInfo) => {
  test.skip(!testInfo.config.metadata.landingServer, 'Use playwright.landing.config.js for the real server HTML.');
});

const cases = [
  { width: 1440, theme: 'light', language: 'ru', path: '/', title: /Большая картина\.\s*За каждой компанией\./ },
  { width: 1440, theme: 'dark', language: 'en', path: '/', title: /The bigger picture\.\s*Behind every company\./ },
  { width: 390, theme: 'light', language: 'ru', path: '/uz', title: /Katta manzara\.\s*Har bir kompaniya ortida\./ },
  { width: 390, theme: 'dark', language: 'uz', path: '/', title: /Katta manzara\.\s*Har bir kompaniya ortida\./ },
  { width: 1440, theme: null, language: 'ru', path: '/', title: /Большая картина\.\s*За каждой компанией\./ },
];

for (const sample of cases) {
  test(`initial landing matches React at ${sample.width}px ${sample.theme || 'default'} ${sample.language} ${sample.path}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: sample.width, height: 900 });
    await page.addInitScript(({ theme, language }) => {
      if (theme) localStorage.setItem('uz_stock_analyzer_theme', theme);
      localStorage.setItem('uz_stock_analyzer_language', language);
      localStorage.setItem('uz_track_internal', '1');
    }, sample);
    const artworkRequests = [];
    page.on('request', request => {
      if (/tashkent-economy.*webp/.test(request.url())) artworkRequests.push(request.url());
    });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    // Hold scripts through CDP: page.route disables the browser cache and
    // would artificially download an image twice when React replaces its node.
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Fetch.enable', { patterns: [{ urlPattern: '*/assets/*.mjs', resourceType: 'Script' }] });
    const held = [];
    let blocked = true;
    cdp.on('Fetch.requestPaused', ({ requestId }) => {
      if (blocked) held.push(requestId);
      else void cdp.send('Fetch.continueRequest', { requestId });
    });
    const release = async () => {
      blocked = false;
      await Promise.all(held.splice(0).map(requestId => cdp.send('Fetch.continueRequest', { requestId })));
    };
    try {
      const response = await page.goto(sample.path, { waitUntil: 'commit' });
      expect(response.status()).toBe(200);
      // The real SEO content must remain available, but never fill the first screen.
      await expect(page.locator('.landing-static .lv-h1')).toHaveText(sample.title);
      await expect(page.locator('.seo-snapshot')).toBeHidden();
      const hero = page.locator('.landing-hero');
      const heading = page.locator('.lv-h1');
      const image = hero.locator('img');
      await expect.poll(() => image.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
      // Isolate the app handoff from the independent webfont download.
      await page.evaluate(() => document.fonts.ready);
      await expect(page.locator('html')).toHaveAttribute('data-theme', sample.theme || 'dark');
      const before = { box: await heading.boundingBox(), background: await hero.evaluate(el => getComputedStyle(el).backgroundColor), src: await image.getAttribute('src') };
      const stableElements = ['.landing-hero-primary', '.landing-hero-art', '.landing-hero-description', '.topbar'];
      const boxes = await Promise.all(stableElements.map(selector => page.locator(selector).boundingBox()));
      await page.screenshot({ path: testInfo.outputPath('before-javascript.png') });
      await release();
      await expect(page.locator('.landing-static')).toHaveCount(0);
      await expect(heading).toHaveText(sample.title);
      await expect(hero).toHaveCSS('background-color', before.background);
      await expect(image).toHaveAttribute('src', before.src);
      await expect(heading).toHaveCSS('opacity', '1');
      const after = await heading.boundingBox();
      for (const dimension of ['x', 'y', 'width', 'height']) expect(Math.abs(after[dimension] - before.box[dimension]), dimension).toBeLessThan(1);
      for (const [index, selector] of stableElements.entries()) {
        const box = await page.locator(selector).boundingBox();
        for (const dimension of ['x', 'y', 'width', 'height']) expect(Math.abs(box[dimension] - boxes[index][dimension]), `${selector} ${dimension}`).toBeLessThan(1);
      }
      expect(new Set(artworkRequests).size).toBe(1);
      await expect.poll(() => image.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
      const downloads = await page.evaluate(() => performance.getEntriesByType('resource')
        .filter(entry => /tashkent-economy.*webp/.test(entry.name) && entry.transferSize > 0));
      expect(downloads).toHaveLength(1);
      await page.screenshot({ path: testInfo.outputPath('after-javascript.png') });
      await page.locator('.landing-hero-primary').click();
      await expect(page).toHaveURL(/\/market$/);
      expect(errors).toEqual([]);
    } finally { await release(); }
  });
}

test.describe('landing without JavaScript', () => {
  test.use({ javaScriptEnabled: false });
  for (const path of ['/', '/uz']) {
    test(`${path} has a designed hero, working market link and readable SEO data`, async ({ page }) => {
      if (path === '/uz') await page.setViewportSize({ width: 390, height: 900 });
      await page.goto(path);
      await expect(page.locator('.landing-static .lv-h1')).toBeVisible();
      const image = page.locator('.landing-hero-art img');
      await expect.poll(() => image.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
      await expect(page.locator('.seo-snapshot')).toBeHidden();
      if (path === '/uz') {
        await page.locator('.landing-static-menu summary').click();
        await expect(page.locator('.landing-static-menu nav')).toBeVisible();
        await page.locator('.landing-static-menu summary').click();
      }
      await page.locator('.landing-snapshot summary').click();
      await expect(page.locator('.seo-snapshot')).toBeVisible();
      await expect(page.locator('.seo-snapshot a', { hasText: 'Uztelecom' })).toHaveAttribute('href', `${path === '/uz' ? '/uz' : ''}/company/UZTL`);
      await page.locator('.landing-hero-primary').click();
      await expect(page).toHaveURL(/\/market$/);
    });
  }
});
