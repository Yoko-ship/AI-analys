import { test, expect } from "@playwright/test";

async function mockAdmin(page) {
  await page.addInitScript(() => {
    localStorage.setItem("uz_stock_analyzer_token", "admin-token");
    localStorage.setItem("uz_stock_analyzer_language", "en");
  });
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const send = (body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/auth/me") return send({ user: { id: 1, email: "admin@example.com", full_name: "Admin", is_admin: true } });
    if (path === "/api/admin/overview") return send({ ok: true, catalog: {}, audit: { open: {}, history: [], queue: [], latest: null }, news: {}, streams: [] });
    return send({ ok: true, items: [] });
  });
}

test("admin opens straight on the product tabs, with no second navigation", async ({ page }, testInfo) => {
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await mockAdmin(page);
  await page.goto("/admin");
  const tabs = page.locator(".admin-tabs");
  await expect(tabs.getByRole("button", { name: "Overview" })).toHaveAttribute("aria-current", "page");
  await expect(page.locator(".control-sidebar")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("admin-desktop.png"), fullPage: true });
  await tabs.getByRole("button", { name: "Audience" }).click();
  await expect(page).toHaveURL(/\/admin\/audience$/);
  await tabs.getByRole("button", { name: "System" }).click();
  await expect(page).toHaveURL(/\/admin\/companies$/);
  const subtabs = page.locator(".admin-subtabs");
  for (const gone of ["Data quality", "Data", "Audit", "Statements", "Rules", "Source"]) await expect(subtabs.getByRole("button", { name: gone, exact: true })).toHaveCount(0);
  await subtabs.getByRole("button", { name: "Collectors" }).click();
  await expect(page).toHaveURL(/\/admin\/streams$/);
  expect(failures).toEqual([]);
});

test("links to removed admin screens land on the overview", async ({ page }) => {
  await mockAdmin(page);
  for (const old of ["/admin/documents", "/admin/audit", "/admin/access", "/admin/product-overview", "/admin/findings", "/admin/quality", "/admin/intake", "/admin/rules", "/admin/source"]) {
    await page.goto(old);
    await expect(page).toHaveURL(/\/admin$/);
    await expect(page.locator(".admin-tabs").getByRole("button", { name: "Overview" })).toHaveAttribute("aria-current", "page");
  }
});

test("the panel fits a phone without sideways scrolling", async ({ page }, testInfo) => {
  await mockAdmin(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin/system");
  await expect(page).toHaveURL(/\/admin\/companies$/);
  await expect(page.locator(".admin-subtabs")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("admin-phone.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
