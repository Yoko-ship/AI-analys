// Requires the Python app serving the current frontend build, since Vite's
// preview server does not render SEO metadata. Set E2E_BASE_URL to that app.
import { test, expect } from "@playwright/test";

test.skip(!process.env.E2E_BASE_URL, "Set E2E_BASE_URL to the Python app serving the current build.");

for (const [path, language, heading] of [
  ["/feedback", "ru", "Обратная связь"],
  ["/uz/feedback", "uz", "Fikr-mulohaza"],
]) {
  test(`${path} keeps its own search metadata after the app renders`, async ({ page }) => {
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(() => {
      localStorage.setItem("uz_track_internal", "1");
      sessionStorage.setItem("uz_sponsor_seen", "1");
    });
    await page.route("**/api/**", route => {
      if (new URL(route.request().url()).pathname === "/api/auth/me") {
        return route.fulfill({ status: 401, json: { user: null } });
      }
      return route.fulfill({ json: { ok: true, items: [] } });
    });
    const response = await page.goto(`${path}?source=footer`);
    expect(response.status()).toBe(200);
    await expect(page.locator(".feedback-page h1")).toHaveText(heading);
    await expect(page).toHaveTitle(`${heading} | UZStock`);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", `https://uzstock.uz${path}`);
    await expect(page.locator('link[hreflang="ru"]')).toHaveAttribute("href", "https://uzstock.uz/feedback");
    await expect(page.locator('link[hreflang="uz"]')).toHaveAttribute("href", "https://uzstock.uz/uz/feedback");
    await expect(page.locator("html")).toHaveAttribute("lang", language);
    expect(errors).toEqual([]);
  });
}
