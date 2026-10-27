import { test, expect } from "@playwright/test";

// Uses e2e.seo_failure_app, not Vite preview or production.
test.skip(!process.env.E2E_SEO_FAILURE_APP, "Run against the local SEO failure app.");

for (const prefix of ["", "/uz"]) {
  test(`${prefix || "Russian"} bond timeout is retryable and the app still renders`, async ({ page }) => {
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(() => {
      localStorage.setItem("uz_track_internal", "1");
      sessionStorage.setItem("uz_sponsor_seen", "1");
    });
    await page.route("**/api/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/auth/me") return route.fulfill({ status: 401, json: { user: null } });
      if (path === "/api/bonds/IQMK9B10") return route.fulfill({ json: {
        ok: true, ticker: "IQMK9B10", issuer: "O‘zIQMK", reference: {}, coupons: [], schedule_flows: [],
      } });
      return route.fulfill({ json: { ok: true, items: [], stocks: [], companies: [] } });
    });
    const response = await page.goto(`${prefix}/bond/IQMK9B10`);
    expect(response.status()).toBe(503);
    expect(response.headers()["retry-after"]).toBe("60");
    expect(response.headers()["cache-control"]).toBe("no-store");
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", `https://uzstock.uz${prefix}/bond/IQMK9B10`);
    await expect(page.locator('meta[name="robots"][content*="noindex"]')).toHaveCount(0);
    // React replaces the server snapshot even on an HTTP 503 document.
    await expect(page.locator(".seo-snapshot")).toHaveCount(0);
    await expect(page.locator("#root")).toContainText("IQMK9B10");
    expect(errors).toEqual([]);
  });
}
