import { test, expect } from "@playwright/test";
import { controlFixture } from "./admin-control-fixture.js";

async function setup(page, role = "analyst") {
  const fixture = controlFixture(role);
  await page.addInitScript(() => {
    localStorage.setItem("uz_stock_analyzer_token", "qa-fixture-token");
    localStorage.setItem("uz_stock_analyzer_language", "en");
    localStorage.setItem("uz_stock_analyzer_theme", "light");
  });
  await page.route("**/api/**", route => {
    const req = route.request();
    const result = fixture.respond(req.url(), req.method(), req.postData() ? JSON.parse(req.postData()) : {});
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(result) });
  });
  return fixture;
}

test("admin opens on product analytics and the sidebar keeps only management", async ({ page }, testInfo) => {
  const failures = [];
  page.on("pageerror", error => failures.push(error.message));
  await setup(page);
  await page.setViewportSize({ width: 1600, height: 1050 });
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Product analytics", exact: true })).toBeVisible();
  const sidebar = page.locator(".control-sidebar");
  for (const name of ["Operations", "Catalog", "Documents", "Formulas", "Publications"]) await expect(sidebar.getByText(name, { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Global search", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("overview-desktop.png"), fullPage: true });
  await sidebar.getByRole("button", { name: "Audit trail", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/audit$/);
  await expect(page.getByRole("heading", { name: "Audit trail", exact: true })).toBeVisible();
  expect(failures).toEqual([]);
});

test("audit trail filters persist in the URL and empty results explain themselves", async ({ page }) => {
  const fixture = await setup(page);
  await page.goto("/admin/audit");
  await expect(page.getByText("Onboard a reviewer", { exact: true })).toBeVisible();
  await page.getByLabel("Search", { exact: true }).fill("MISSING");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/q=MISSING/);
  expect(fixture.calls.some(call => call.query.q === "MISSING")).toBe(true);
  await expect(page.getByRole("heading", { name: "No records in this view" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "No records in this view" })).toBeVisible();
});

test("viewer cannot assign roles", async ({ page }) => {
  await setup(page, "viewer");
  await page.goto("/admin/access");
  await expect(page.getByRole("button", { name: "Assign role", exact: true })).toHaveCount(0);
});

test("phone navigation remains accessible in dark theme", async ({ page }, testInfo) => {
  await setup(page, "viewer");
  await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_theme", "dark"));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin");
  await page.getByLabel("Section", { exact: true }).selectOption("audit");
  await expect(page.getByRole("heading", { name: "Audit trail", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("phone-dark.png"), fullPage: true });
});

test("server errors are visible and retry restores the registry", async ({ page }) => {
  await setup(page);
  let fail = true;
  await page.route("**/api/admin/control/audit?*", async route => {
    if (!fail) return route.fallback();
    fail = false;
    return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "SOURCE_UNAVAILABLE", message: "Source temporarily unavailable" } }) });
  });
  await page.goto("/admin/audit");
  await expect(page.getByRole("alert")).toContainText("SOURCE_UNAVAILABLE");
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByText("Onboard a reviewer", { exact: true })).toBeVisible();
});
