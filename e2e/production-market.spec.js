import { test, expect } from "@playwright/test";

// This spec talks to the real API: keep it out of the admin audience numbers
// (docs/prod-browser-testing.md).
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem("uz_track_internal", "1"); } catch (e) { /* ignore */ }
  });
});

test("public market loads its code and real stock rows", async ({ page }, testInfo) => {
  test.skip(!process.env.E2E_PRODUCTION_SMOKE, "Opt-in public-site verification");
  const failedScripts = [];
  const errors = [];
  page.on("requestfailed", request => {
    if (request.resourceType() === "script") failedScripts.push(request.url());
  });
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/market", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".market-table-wrap .market-ticker-btn").first()).toBeVisible({ timeout: 20000 });
  await expect(page.locator(".market-table-wrap .market-empty-cell")).toHaveCount(0);
  expect(failedScripts).toEqual([]);
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("production-market.png"), fullPage: true });
});
