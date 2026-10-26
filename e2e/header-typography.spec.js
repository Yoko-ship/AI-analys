import { test, expect } from '@playwright/test';

const cases = [
  { width: 1280, theme: 'dark', scale: 100 },
  { width: 1280, theme: 'light', scale: 100 },
  { width: 1920, theme: 'dark', scale: 100 },
  { width: 390, theme: 'dark', scale: 100 },
  { width: 390, theme: 'light', scale: 100 },
  { width: 1440, theme: 'dark', scale: 115 },
];

for (const { width, theme, scale } of cases) {
  test(`header typography survives Main–Market navigation at ${width}px, ${theme}, ${scale}%`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(({ theme, scale }) => {
      localStorage.setItem('uz_stock_analyzer_language', 'ru');
      localStorage.setItem('uz_stock_analyzer_theme', theme);
      localStorage.setItem('uz_text_scale', String(scale));
      localStorage.setItem('uz_track_internal', '1');
      sessionStorage.setItem('uz_sponsor_seen', '1');
    }, { theme, scale });
    await page.route('**/api/**', route => route.fulfill({ json: {} }));

    const header = page.locator('.topbar');
    const main = header.getByRole('button', { name: 'Главная', exact: true });
    const market = header.getByRole('button', { name: 'Рынок', exact: true });
    const showNavigation = async () => {
      const burger = header.getByRole('button', { name: 'Открыть меню', exact: true });
      if (await burger.isVisible()) {
        await burger.click();
        await expect(header.locator('.topbar-nav')).toHaveCSS('transform', 'matrix(1, 0, 0, 1, 0, 0)');
      }
      await expect(main).toBeVisible();
    };
    const typography = () => header.locator('.topbar-nav-btn').evaluateAll(buttons =>
      buttons.map(button => {
        const style = getComputedStyle(button);
        return { text: button.textContent, size: style.fontSize, family: style.fontFamily };
      }));
    const checkScale = async () => {
      await expect(page.locator('html')).toHaveCSS('zoom', String(scale / 100));
      await expect(header.locator('.topbar-textsize-now:visible')).toHaveText(`${scale}%`);
    };

    // Start on the screener to capture the existing shared responsive type.
    // The reported bug occurs when the same header enters the Purple skin.
    await page.goto('/market');
    await expect(page.locator('.view-market')).toBeVisible();
    await showNavigation();
    await checkScale();
    const shared = await typography();
    await main.click();
    await expect(page.locator('.view-main')).toBeVisible();
    await showNavigation();
    await checkScale();
    expect(await typography()).toEqual(shared);
    await page.screenshot({ path: testInfo.outputPath('main.png') });

    await market.click();
    await expect(page.locator('.view-market')).toBeVisible();
    await showNavigation();
    await checkScale();
    expect(await typography()).toEqual(shared);
    await page.screenshot({ path: testInfo.outputPath('market.png') });

    await page.goBack();
    await expect(page.locator('.view-main')).toBeVisible();
    await showNavigation();
    expect(await typography()).toEqual(shared);
    await page.reload();
    await expect(page.locator('.view-main')).toBeVisible();
    await showNavigation();
    await checkScale();
    expect(await typography()).toEqual(shared);
  });
}
