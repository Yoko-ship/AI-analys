import { test, expect } from '@playwright/test';

const palette = {
  dark: { background: 'rgb(11, 13, 18)', header: 'rgb(14, 16, 22)', accent: '#8b7cff', hero: 'rgb(10, 17, 32)', masthead: 'rgb(10, 17, 32)', ink: 'rgb(240, 244, 255)', blend: 'normal' },
  light: { background: 'rgb(232, 230, 225)', header: 'rgb(241, 239, 234)', accent: '#6257d9', hero: 'rgb(232, 230, 225)', masthead: 'rgb(241, 239, 234)', ink: 'rgb(24, 33, 55)', blend: 'multiply' },
};

async function setup(page, width, theme = 'dark') {
  await page.setViewportSize({ width, height: 900 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(theme => {
    localStorage.setItem('uz_stock_analyzer_language', 'ru');
    if (!localStorage.getItem('uz_stock_analyzer_theme')) localStorage.setItem('uz_stock_analyzer_theme', theme);
    localStorage.setItem('uz_track_internal', '1');
    sessionStorage.setItem('uz_sponsor_seen', '1');
  }, theme);
  await page.route('**/api/**', route => route.fulfill({ json: {} }));
}

for (const width of [2560, 1440, 390]) {
  for (const theme of ['dark', 'light']) {
    test(`glass hero follows the ${theme} theme and preserves the workspace at ${width}px`, async ({ page }, testInfo) => {
      await setup(page, width, theme);
      const original = palette[theme];
      const checkLanding = async expected => {
        await expect(page.locator('.landing-view')).toBeVisible();
        await expect(page.locator('body')).toHaveCSS('background-color', expected.background);
        await expect(page.locator('.landing-view')).toHaveCSS('background-color', expected.background);
        await expect(page.locator('.topbar')).toHaveCSS('background-color', expected.masthead);
        await expect(page.locator('.landing-hero')).toHaveCSS('background-color', expected.hero);
        await expect(page.locator('.lv-h1')).toHaveCSS('color', expected.ink);
        await expect(page.locator('.topbar .brand-title')).toHaveCSS('color', expected.ink);
        await expect(page.locator('.landing-hero-art img')).toHaveCSS('mix-blend-mode', expected.blend);
        await expect(page.locator('.landing-hero-art img')).toHaveCSS('filter', 'none');
        // Lower glare must preserve readable text and the primary action.
        const contrasts = await page.locator('.landing-hero').evaluate(hero => {
          const luminance = color => color.match(/[\d.]+/g).slice(0, 3).map(Number)
            .map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
            .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
          return ['.lv-h1', '.landing-hero-description', '.landing-hero-topics button', '.landing-hero-primary'].map(selector => {
            const el = hero.querySelector(selector), style = getComputedStyle(el);
            const a = luminance(style.color), b = luminance(selector.endsWith('primary') ? style.backgroundColor : getComputedStyle(hero).backgroundColor);
            return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
          });
        });
        for (const contrast of contrasts) expect(contrast).toBeGreaterThanOrEqual(4.5);
        expect(await page.locator('.landing-view').evaluate(el => getComputedStyle(el).getPropertyValue('--accent').trim())).toBe(expected.accent);
      };
      await page.goto('/');
      await checkLanding(original);
      await page.screenshot({ path: testInfo.outputPath('landing.png') });
      await page.goto('/market');
      await expect(page.locator('.view-market')).toBeVisible();
      await expect(page.locator('body')).toHaveCSS('background-color', original.background);
      await expect(page.locator('.topbar')).toHaveCSS('background-color', original.header);
      await page.goBack();
      await checkLanding(original);
      await page.reload();
      await checkLanding(original);
      const originalArtwork = await page.locator('.landing-hero-art img').evaluate(img => img.currentSrc);
      await page.locator('.theme-toggle').click();
      await checkLanding(palette[theme === 'dark' ? 'light' : 'dark']);
      await expect.poll(() => page.locator('.landing-hero-art img').evaluate(img => img.currentSrc)).not.toBe(originalArtwork);
      const switchedArtwork = await page.locator('.landing-hero-art img').evaluate(img => img.currentSrc);
      await page.reload();
      await checkLanding(palette[theme === 'dark' ? 'light' : 'dark']);
      await expect.poll(() => page.locator('.landing-hero-art img').evaluate(img => img.currentSrc)).toBe(switchedArtwork);
      if (width < 1180) {
        await page.locator('.topbar-burger').click();
        await expect(page.locator('.topbar-nav')).toBeVisible();
        await page.keyboard.press('Escape');
        await expect(page.locator('.topbar-burger')).toHaveAttribute('aria-expanded', 'false');
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
  }

  test(`shared header omits the information strip and global search at ${width}px`, async ({ page }) => {
    await setup(page, width);
    for (const path of ['/', '/market', '/news']) {
      await page.goto(path);
      await expect(page.locator('header.topbar')).toBeVisible();
      await expect(page.getByTestId('market-source-strip')).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Поиск по сайту', exact: true })).toHaveCount(0);
      await page.keyboard.press('ControlOrMeta+k');
      await expect(page.locator('.global-search-dialog')).toHaveCount(0);
    }
  });
}
