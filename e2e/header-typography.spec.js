import { test, expect } from '@playwright/test';
import { expectPlainActiveNavigation } from './header-navigation.js';

const cases = [
  { width: 1280, theme: 'dark', scale: 100 },
  { width: 1280, theme: 'light', scale: 100 },
  { width: 1920, theme: 'dark', scale: 100 },
  { width: 390, theme: 'dark', scale: 100 },
  { width: 390, theme: 'light', scale: 100 },
  { width: 320, theme: 'light', scale: 100 },
  { width: 1440, theme: 'dark', scale: 115 },
];

test('the UZStock mark shows five colored candles with wicks', async ({ page }) => {
  await page.goto('/favicon.svg?v=candles-1');
  const candles = await page.locator('svg > g').evaluateAll(groups => groups.map(group => {
    const body = group.querySelector('rect');
    const wick = group.querySelector('line');
    const box = body.getBBox();
    const style = getComputedStyle(wick);
    const color = getComputedStyle(body).fill;
    return {
      color,
      center: box.x + box.width / 2,
      hasWick: style.stroke === color && parseFloat(style.strokeWidth) > 0
        && wick.x1.baseVal.value === box.x + box.width / 2
        && wick.x2.baseVal.value === wick.x1.baseVal.value
        && wick.y1.baseVal.value < box.y
        && wick.y2.baseVal.value > box.y + box.height,
    };
  }));
  const green = 'rgb(39, 233, 154)';
  const red = 'rgb(255, 83, 92)';
  expect(candles.map(candle => candle.color)).toEqual([green, green, red, green, green]);
  expect(candles.every(candle => candle.hasWick)).toBe(true);
  const centers = candles.map(candle => candle.center);
  expect(centers).toEqual([...centers].sort((a, b) => a - b));
});

test('fallback site icons retain the five candles down to 16px', async ({ page }) => {
  await page.goto('/');
  const links = page.locator('head link[rel="icon"], head link[rel="apple-touch-icon"]');
  expect(await links.evaluateAll(items => items.map(item => item.getAttribute('href')).sort())).toEqual([
    '/apple-touch-icon.png?v=candles-1', '/favicon-96x96.png?v=candles-1',
    '/favicon.ico?v=candles-1', '/favicon.svg?v=candles-1',
  ]);
  const icons = await page.evaluate(async () => {
    const pixels = async (blob, size) => {
      const url = URL.createObjectURL(blob);
      try {
        const image = new Image();
        image.src = url;
        await image.decode();
        const canvas = document.createElementNS('http://www.w3.org/1999/xhtml', 'canvas');
        canvas.width = canvas.height = size;
        const context = canvas.getContext('2d');
        context.drawImage(image, 0, 0, size, size);
        const colors = [[.16, .66], [.33, .54], [.50, .59], [.67, .49], [.84, .36]].map(([x, y]) => {
          const [red, green, blue] = context.getImageData(Math.floor(x * size), Math.floor(y * size), 1, 1).data;
          if (red > 200 && green < 125 && blue < 125) return 'red';
          if (green > 180 && red < 100 && blue < 190) return 'green';
          return 'other';
        });
        return { width: image.naturalWidth, height: image.naturalHeight, colors };
      } finally {
        URL.revokeObjectURL(url);
      }
    };
    const pngs = await Promise.all([['/favicon-96x96.png?v=candles-1', 96], ['/apple-touch-icon.png?v=candles-1', 180]]
      .map(async ([url, size]) => pixels(await (await fetch(url)).blob(), size)));
    const ico = new Uint8Array(await (await fetch('/favicon.ico?v=candles-1')).arrayBuffer());
    const directory = new DataView(ico.buffer);
    const count = directory.getUint16(4, true);
    const frames = await Promise.all(Array.from({ length: count }, async (_, index) => {
      const entry = 6 + index * 16;
      const size = ico[entry];
      const length = directory.getUint32(entry + 8, true);
      const offset = directory.getUint32(entry + 12, true);
      // Isolate each ICO frame so the browser decodes that resolution.
      const header = ico.slice(0, 22);
      header.set(ico.subarray(entry, entry + 16), 6);
      const frameDirectory = new DataView(header.buffer);
      frameDirectory.setUint16(4, 1, true);
      frameDirectory.setUint32(18, 22, true);
      return pixels(new Blob([header, ico.subarray(offset, offset + length)], { type: 'image/x-icon' }), size);
    }));
    return [...pngs, ...frames.sort((a, b) => a.width - b.width)];
  });
  const colors = ['green', 'green', 'red', 'green', 'green'];
  expect(icons).toEqual([96, 180, 16, 32, 48].map(size => ({ width: size, height: size, colors })));
});

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
      await expectPlainActiveNavigation(page, theme);
      await expect(page.locator('html')).toHaveCSS('zoom', '1');
      await expect(header.locator('.topbar-textsize, .topbar-nav-textsize')).toHaveCount(0);
      expect(await page.evaluate(() => localStorage.getItem('uz_text_scale'))).toBeNull();
    };

    // Start on the screener to capture the existing shared responsive type.
    // The reported bug occurs when the same header enters the Purple skin.
    await page.goto('/market');
    await expect(page.locator('.view-market')).toBeVisible();
    await header.screenshot({ path: testInfo.outputPath('header.png') });
    const brand = header.getByRole('link', { name: 'UZStock — Главная', exact: true });
    await expect(brand).toHaveAttribute('href', '/');
    const mark = brand.locator('.brand-icon');
    await expect(mark).toBeVisible();
    await expect(mark).toHaveAttribute('src', '/favicon.svg?v=candles-1');
    await expect(mark).toHaveAttribute('alt', '');
    await expect.poll(() => mark.evaluate(img => img.naturalWidth > 0)).toBe(true);
    expect((await brand.boundingBox()).height).toBeGreaterThanOrEqual(44);
    await expect(header).toHaveCSS('border-top-width', '0px');
    await expect(header).toHaveCSS('border-bottom-width', '0px');
    await brand.focus();
    await expect(brand).toBeFocused();
    await brand.press('Enter');
    await expect(page.locator('.view-main')).toBeVisible();
    await expect(brand.locator('.brand-icon')).toBeVisible();
    await expect(header).toHaveCSS('border-bottom-width', '0px');
    await page.locator('.lv-h1').click();
    await header.screenshot({ path: testInfo.outputPath('home-header.png') });
    const actions = await header.locator('.topbar-actions').boundingBox();
    expect(actions.x + actions.width).toBeLessThanOrEqual(width);
    await page.goBack();
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
