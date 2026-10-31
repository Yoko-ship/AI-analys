// The Uzbek site has URLs of its own: /uz + the Russian path. The URL names the
// language on load, the address bar follows a language switch, and every in-app
// navigation keeps the reader's prefix (frontend/src/lib/languagePath.js).
import { test, expect } from "@playwright/test";
import { selectLanguage } from './language-control.js';

const UZ_TITLE = "UZStock — O‘zbekiston fond bozori";

async function open(page, path, { saved } = {}) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => sessionStorage.setItem("uz_sponsor_seen", "1"));
  if (saved) await page.addInitScript((lang) => localStorage.setItem("uz_stock_analyzer_language", lang), saved);
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/auth/me") return route.fulfill({ status: 401, json: { user: null } });
    return route.fulfill({ json: { ok: true, items: [] } });
  });
  await page.goto(path);
  return errors;
}

const savedLanguage = (page) => page.evaluate(() => localStorage.getItem("uz_stock_analyzer_language"));

test("a /uz URL opens in Uzbek and wins over the saved language", async ({ page }) => {
  const errors = await open(page, "/uz/market", { saved: "ru" });
  await expect(page.locator("html")).toHaveAttribute("lang", "uz");
  await expect(page).toHaveURL(/\/uz\/market$/);
  expect(await savedLanguage(page)).toBe("uz");
  const brand = page.getByRole('link', { name: /^UZStock/ });
  await expect(brand).toHaveAttribute('href', '/uz');
  await brand.click();
  await expect(page).toHaveURL(/\/uz$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'uz');
  expect(errors).toEqual([]);
});

test("a bare URL follows a saved Uzbek choice without a new history entry", async ({ page }) => {
  await open(page, "/market", { saved: "uz" });
  await expect(page).toHaveURL(/\/uz\/market$/);
  await expect(page.locator("html")).toHaveAttribute("lang", "uz");
  // Back leaves the site rather than landing on the bare /market it replaced.
  await page.goBack();
  await expect(page).not.toHaveURL(/\/market$/);
});

test("a bare URL stays bare in Russian and English", async ({ page }) => {
  await open(page, "/market", { saved: "en" });
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page).toHaveURL(/\/market$/);
  await expect(page).not.toHaveURL(/\/uz\//);
});

test("switching language rewrites the current URL, and navigation keeps the prefix", async ({ page }) => {
  await open(page, "/market");
  await expect(page.locator("html")).toHaveAttribute("lang", "ru");
  await selectLanguage(page, 'uz');
  await expect(page).toHaveURL(/\/uz\/market$/);
  await expect(page.locator("html")).toHaveAttribute("lang", "uz");

  await page.locator(".account-signin").click();
  await expect(page).toHaveURL(/\/uz\/login$/);
  await expect(page).toHaveTitle(UZ_TITLE);
  await page.goBack();
  await expect(page).toHaveURL(/\/uz\/market$/);

  await selectLanguage(page, 'ru');
  await expect(page).toHaveURL(/\/market$/);
  await expect(page).not.toHaveURL(/\/uz\//);
});

test("Back onto a page written before a switch shows it in the current language", async ({ page }) => {
  await open(page, "/market");
  await page.locator(".account-signin").click();
  await expect(page).toHaveURL(/\/login$/);
  await selectLanguage(page, 'uz');
  await expect(page).toHaveURL(/\/uz\/login$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/uz\/market$/);
  await expect(page.locator("html")).toHaveAttribute("lang", "uz");
});

test("/uz alone is the Uzbek home page", async ({ page }) => {
  await open(page, "/uz");
  await expect(page).toHaveURL(/\/uz$/);
  await expect(page.locator("html")).toHaveAttribute("lang", "uz");
});


for (const [width, theme] of [[1440, 'light'], [1440, 'dark'], [320, 'light'], [320, 'dark']]) {
  test(`language menu fits ${width}px in ${theme}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript((theme) => {
      localStorage.setItem('uz_stock_analyzer_theme', theme);
      localStorage.setItem('uz_track_internal', '1');
    }, theme);
    const errors = await open(page, '/');
    const trigger = page.getByRole('combobox', { name: 'Язык', exact: true });
    await expect(trigger).toHaveText('RU');
    const triggerBox = await trigger.boundingBox();
    expect(triggerBox.width).toBeGreaterThanOrEqual(44);
    expect(triggerBox.height).toBeGreaterThanOrEqual(44);
    await trigger.click();
    const menu = page.getByRole('listbox');
    await expect(menu).toBeVisible();
    await expect(page.getByRole('option')).toHaveText(['Русский', 'O‘zbekcha', 'English']);
    await expect(page.getByRole('option', {name:'Русский', exact:true})).toHaveAttribute('aria-selected', 'true');
    const menuBox = await menu.boundingBox();
    expect(menuBox.x).toBeGreaterThanOrEqual(4);
    expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(width - 4);
    expect(menuBox.y).toBeGreaterThanOrEqual(triggerBox.y + triggerBox.height);
    expect(menuBox.y + menuBox.height).toBeLessThanOrEqual(900);
    // Chromium can report a subpixel rounding error during the arrival transform.
    for (const option of await page.getByRole('option').all()) expect((await option.boundingBox()).height).toBeGreaterThanOrEqual(43.9);
    await expect(menu).toHaveCSS('background-color', theme === 'dark' ? 'rgb(21, 33, 55)' : 'rgb(245, 243, 239)');
    await page.screenshot({path:testInfo.outputPath('language-menu.png')});
    await page.screenshot({path:testInfo.outputPath('language-control.png'), clip: {
      x: Math.max(0, menuBox.x - 16), y: Math.max(0, triggerBox.y - 8),
      width: Math.min(width, menuBox.width + 32), height: menuBox.y + menuBox.height - triggerBox.y + 24,
    }});
    await page.getByRole('option', {name:'English',exact:true}).click();
    await expect(menu).toHaveCount(0);
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.locator('#languageSelect')).toHaveText('EN');
    await expect(page.locator('.lv-h1')).toContainText('Behind every');
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.locator('#languageSelect')).toHaveText('EN');
    expect(errors).toEqual([]);
  });
}

test('language menu supports keyboard selection, cancellation and outside dismissal', async ({ page }) => {
  await open(page, '/');
  const trigger = page.locator('#languageSelect');
  await trigger.focus();
  await page.keyboard.press('Space');
  await expect(page.getByRole('option', {name:'Русский',exact:true})).toBeFocused();
  await page.keyboard.press('ArrowDown');
  await expect(page.getByRole('option', {name:'O‘zbekcha',exact:true})).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(page.locator('html')).toHaveAttribute('lang','ru');
  await trigger.press('Enter');
  await page.keyboard.press('End');
  await expect(page.getByRole('option', {name:'English',exact:true})).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('html')).toHaveAttribute('lang','en');
  await expect(trigger).toBeFocused();
  await trigger.click();
  await page.mouse.click(20, 400);
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await expect(page.locator('html')).toHaveAttribute('lang','en');
});
