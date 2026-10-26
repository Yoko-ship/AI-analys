import { test, expect } from '@playwright/test';

const palette = {
  dark: { background: 'rgb(11, 13, 18)', header: 'rgb(14, 16, 22)', accent: '#8b7cff', workspace: 'rgb(21, 18, 34)' },
  light: { background: 'rgb(245, 247, 251)', header: 'rgb(245, 247, 251)', accent: '#6257d9', workspace: 'rgb(247, 247, 251)' },
};

async function setup(page, width, theme = 'dark') {
  await page.setViewportSize({ width, height: 900 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(theme => {
    localStorage.setItem('uz_stock_analyzer_language', 'ru');
    localStorage.setItem('uz_stock_analyzer_theme', theme);
    localStorage.setItem('uz_track_internal', '1');
    sessionStorage.setItem('uz_sponsor_seen', '1');
  }, theme);
  await page.route('**/api/**', route => route.fulfill({ json: {} }));
}

for (const width of [1440, 390]) {
  for (const theme of ['dark', 'light']) {
    test(`landing restores its original ${theme} colors at ${width}px`, async ({ page }, testInfo) => {
      await setup(page, width, theme);
      const original = palette[theme];
      const checkLanding = async expected => {
        await expect(page.locator('.landing-view')).toBeVisible();
        await expect(page.locator('body')).toHaveCSS('background-color', expected.background);
        await expect(page.locator('.landing-view')).toHaveCSS('background-color', expected.background);
        await expect(page.locator('.topbar')).toHaveCSS('background-color', expected.header);
        expect(await page.locator('.landing-view').evaluate(el => getComputedStyle(el).getPropertyValue('--accent').trim())).toBe(expected.accent);
      };
      await page.goto('/');
      await checkLanding(original);
      await page.screenshot({ path: testInfo.outputPath('landing.png') });
      await page.goto('/market');
      await expect(page.locator('.view-market')).toBeVisible();
      await expect(page.locator('body')).toHaveCSS('background-color', original.workspace);
      await page.goBack();
      await checkLanding(original);
      await page.reload();
      await checkLanding(original);
      await page.locator('.theme-toggle').click();
      await checkLanding(palette[theme === 'dark' ? 'light' : 'dark']);
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
