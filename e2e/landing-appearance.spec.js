import { toggleTheme } from './language-control.js';
import { test, expect } from '@playwright/test';
import { setupLanding } from './landing-fixtures.js';

const palette = {
  dark: { background: 'rgb(11, 13, 18)', header: 'rgb(14, 16, 22)', accent: '#8b7cff', hero: 'rgb(17, 20, 27)', masthead: 'rgb(10, 17, 32)', ink: 'rgb(243, 245, 251)', brand: 'rgb(240, 244, 255)', blend: 'normal' },
  light: { background: 'rgb(232, 230, 225)', header: 'rgb(241, 239, 234)', accent: '#6257d9', hero: 'rgb(245, 243, 239)', masthead: 'rgb(241, 239, 234)', ink: 'rgb(24, 33, 55)', brand: 'rgb(24, 33, 55)', blend: 'normal' },
};

const listNews = [
  { id: 6570, source: 'The Times of Central Asia — Uzbekistan', title: 'Узбекистан планирует увеличить годовую добычу урана до 15 000 тонн к 2030 году с прогнозируемых 7 500 тонн. Рост производства может поддержать инвестиции и активность в горнодобывающем секторе.' },
  { id: 6571, source: 'UzDaily.uz', title: '«Узбекнефтегаз» обсудил с Axens, Technip и CPECC модернизацию Бухарского НПЗ' },
  { id: 6572, source: 'UzA — National News Agency (English)', title: 'TBC Uzbekistan опубликовала консолидированные результаты по МСФО за третий квартал 2026 года. Компания сообщила о росте клиентской базы бизнес-клиентов и цифровой экосистемы.' },
].map(item => ({ ...item, title_ru: item.title, lang: 'ru', published_at: '2026-11-06T10:00:00Z' }));

for (const width of [1440, 390]) for (const theme of ['light', 'dark']) {
  test(`news reads as a compact list at ${width}px in ${theme}`, async ({ page }, testInfo) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await setupLanding(page, { width, theme });
    await page.route('**/api/news/feed?*', route => route.fulfill({ json: { ok: true, items: listNews } }));
    await page.goto('/');
    const section = page.getByRole('region', { name: 'За цифрами — события' });
    const rows = section.getByRole('listitem');
    await expect(rows).toHaveCount(3);
    const listBox = await section.getByRole('list').boundingBox();
    let previousBottom = null;
    for (const [index, row] of (await rows.all()).entries()) {
      const box = await row.boundingBox();
      expect(Math.abs(box.x - listBox.x)).toBeLessThan(1);
      expect(box.width).toBeGreaterThanOrEqual(listBox.width - 2);
      if (previousBottom !== null) expect(box.y).toBeGreaterThanOrEqual(previousBottom - 1);
      previousBottom = box.y + box.height;
      expect(box.height).toBeLessThan(width > 760 ? 150 : 360);
      await expect(row.getByRole('heading')).toHaveText(listNews[index].title);
      await expect(row.getByText(listNews[index].source, { exact: true })).toBeVisible();
      await expect(row.locator('time')).toHaveAttribute('datetime', listNews[index].published_at);
      await expect(row.getByRole('link')).toHaveAttribute('href', `/news/${listNews[index].id}`);
    }
    expect(await section.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await section.scrollIntoViewIfNeeded();
    await section.screenshot({ path: testInfo.outputPath('news-list.png'), animations: 'disabled' });
    const first = rows.first().getByRole('link');
    await first.focus();
    await page.keyboard.press('Tab');
    await expect(rows.nth(1).getByRole('link')).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/news\/6571$/);
    expect(errors).toEqual([]);
  });
}

for (const theme of ['light', 'dark']) {
  for (const width of [1440, 390]) {
    test(`market search has a restrained accessible focus at ${width}px in ${theme}`, async ({ page }, testInfo) => {
      await setupLanding(page, { theme, width });
      await page.goto('/');
      const search = page.getByRole('searchbox', { name: 'Поиск компании или тикера' });
      await search.scrollIntoViewIfNeeded();
      const resting = await search.boundingBox();
      const radius = await search.evaluate(input => getComputedStyle(input).borderRadius);
      await search.click();
      await expect(search).toBeFocused();
      await expect(search).toHaveCSS('outline-offset', '-2px');
      await expect(search).toHaveCSS('outline-width', '2px');
      await expect(search).toHaveCSS('outline-style', 'solid');
      await expect(search).toHaveCSS('box-shadow', 'none');
      await expect(search).toHaveCSS('border-radius', radius);
      const clicked = await search.boundingBox();
      expect(clicked.width).toBe(resting.width);
      expect(clicked.height).toBe(resting.height);
      const contrast = await search.evaluate(input => {
        const luminance = color => color.match(/[\d.]+/g).slice(0, 3).map(Number)
          .map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
          .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
        const style = getComputedStyle(input);
        const a = luminance(style.outlineColor), b = luminance(style.backgroundColor);
        return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
      });
      expect(contrast).toBeGreaterThanOrEqual(3);
      await page.screenshot({ path: testInfo.outputPath('search-focus.png'), clip: { x: clicked.x - 8, y: clicked.y - 8, width: clicked.width + 16, height: clicked.height + 16 } });
      await page.keyboard.press('Shift+Tab');
      const lastFilter = page.locator('.landing-filters button').last();
      await expect(lastFilter).toBeFocused();
      await expect(lastFilter).toHaveCSS('outline-style', 'solid');
      await page.keyboard.press('Tab');
      await expect(search).toBeFocused();
      await expect(search).toHaveCSS('outline-width', '2px');
      await expect(search).toHaveCSS('outline-offset', '-2px');
      await search.fill('GRBK');
      await expect(page.locator('.landing-market tbody tr')).toHaveCount(1);
      await expect(page.locator('.landing-market tbody tr')).toContainText('GRBK');
    });
  }
}

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
    test(`illustrated hero follows the ${theme} theme and preserves the workspace at ${width}px`, async ({ page }, testInfo) => {
      await setup(page, width, theme);
      const original = palette[theme];
      const checkLanding = async expected => {
        await expect(page.locator('.landing-view')).toBeVisible();
        await expect(page.locator('body')).toHaveCSS('background-color', expected.background);
        await expect(page.locator('.landing-view')).toHaveCSS('background-color', expected.background);
        await expect(page.locator('.topbar')).toHaveCSS('background-color', expected.masthead);
        await expect(page.locator('.landing-hero')).toHaveCSS('background-color', expected.hero);
        await expect(page.locator('.lv-h1')).toHaveCSS('color', expected.ink);
        await expect(page.locator('.topbar .brand-title')).toHaveCSS('color', expected.brand);
        await expect(page.locator('.landing-hero-art img')).toHaveCSS('mix-blend-mode', expected.blend);
        await expect(page.locator('.landing-hero-art img')).toHaveCSS('filter', 'none');
        // Lower glare must preserve readable text and the primary action.
        const contrasts = await page.locator('.landing-hero').evaluate(hero => {
          const luminance = color => color.match(/[\d.]+/g).slice(0, 3).map(Number)
            .map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
            .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
          return ['.lv-h1', '.landing-hero-description', '.landing-hero-primary'].map(selector => {
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
      await toggleTheme(page);
      await checkLanding(palette[theme === 'dark' ? 'light' : 'dark']);
      await expect.poll(() => page.locator('.landing-hero-art img').evaluate(img => img.currentSrc)).toBe(originalArtwork);
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
