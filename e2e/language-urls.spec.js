// The Uzbek site has URLs of its own: /uz + the Russian path. The URL names the
// language on load, the address bar follows a language switch, and every in-app
// navigation keeps the reader's prefix (frontend/src/lib/languagePath.js).
import { test, expect } from "@playwright/test";

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
  await page.locator("#languageSelect").selectOption("uz");
  await expect(page).toHaveURL(/\/uz\/market$/);
  await expect(page.locator("html")).toHaveAttribute("lang", "uz");

  await page.locator(".account-signin").click();
  await expect(page).toHaveURL(/\/uz\/login$/);
  await expect(page).toHaveTitle(UZ_TITLE);
  await page.goBack();
  await expect(page).toHaveURL(/\/uz\/market$/);

  await page.locator("#languageSelect").selectOption("ru");
  await expect(page).toHaveURL(/\/market$/);
  await expect(page).not.toHaveURL(/\/uz\//);
});

test("Back onto a page written before a switch shows it in the current language", async ({ page }) => {
  await open(page, "/market");
  await page.locator(".account-signin").click();
  await expect(page).toHaveURL(/\/login$/);
  await page.locator("#languageSelect").selectOption("uz");
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
