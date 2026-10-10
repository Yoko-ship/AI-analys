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

test("admin opens on product analytics without the operations section", async ({ page }, testInfo) => {
  const failures = [];
  page.on("pageerror", error => failures.push(error.message));
  await setup(page);
  await page.setViewportSize({ width: 1600, height: 1050 });
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Product analytics", exact: true })).toBeVisible();
  const sidebar = page.locator(".control-sidebar");
  for (const name of ["Operations", "Incidents", "Jobs", "Data quality"]) await expect(sidebar.getByText(name, { exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("overview-desktop.png"), fullPage: true });
  await sidebar.getByRole("button", { name: "Documents", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/documents$/);
  await expect(page.getByRole("heading", { name: "Documents", exact: true })).toBeVisible();
  expect(failures).toEqual([]);
});

test("filters persist in the URL and document deep link opens a safe cell grid", async ({ page }, testInfo) => {
  const fixture = await setup(page);
  await page.goto("/admin/documents");
  await page.getByLabel("Issuer", { exact: true }).fill("UZNF");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/ticker=UZNF/);
  await expect(page.getByRole("button", { name: "HMKB", exact: true })).toHaveCount(0);
  expect(fixture.calls.some(call => call.query.ticker === "UZNF")).toBe(true);
  await page.getByRole("button", { name: "UZNF", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "B2 123456" }).click();
  await expect(page).toHaveURL(/cell=B2/);
  await expect(page.getByText("Balance!B2", { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("document-source.png"), fullPage: true });
  await page.reload();
  await expect(page.getByText("Balance!B2", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await expect(page).toHaveURL(/ticker=UZNF/);
});

test("document reprocess is recorded without leaving the page", async ({ page }) => {
  const fixture = await setup(page);
  await page.goto("/admin/documents?object=doc-fixture");
  await page.getByRole("button", { name: "Reprocess", exact: true }).click();
  const confirm = page.getByRole("dialog", { name: "Review this action" });
  await confirm.getByLabel("Reason", { exact: true }).fill("Verify the classified half-year period");
  await confirm.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.locator(".control-notice")).toContainText("recorded in the audit trail");
  await expect(page).toHaveURL(/\/admin\/documents/);
  const submitted = fixture.calls.find(call => call.method === "POST");
  expect(submitted.body.reason).toContain("half-year");
});

test("viewer cannot see mutation controls and empty results explain themselves", async ({ page }) => {
  await setup(page, "viewer");
  await page.goto("/admin/documents?object=doc-fixture");
  await expect(page.getByRole("button", { name: "Reprocess", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sync catalog", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByLabel("Issuer", { exact: true }).fill("MISSING");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByRole("heading", { name: "No records in this view" })).toBeVisible();
});

test("sidebar keeps only catalog and management, and a tablet viewport does not overflow", async ({ page }, testInfo) => {
  await setup(page);
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.goto("/admin/documents");
  const sections = page.getByLabel("Section", { exact: true });
  for (const gone of ["formulas", "calculations", "analyses", "publications", "securities", "parsers"]) await expect(sections.locator(`option[value="${gone}"]`)).toHaveCount(0);
  await expect(sections.locator('option[value="documents"]')).toHaveCount(1);
  await page.screenshot({ path: testInfo.outputPath("documents-tablet.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test("phone navigation remains accessible in dark theme", async ({ page }, testInfo) => {
  await setup(page, "viewer");
  await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_theme", "dark"));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin");
  await page.getByLabel("Section", { exact: true }).selectOption("documents");
  await expect(page.getByRole("heading", { name: "Documents", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "UZNF", exact: true }).click();
  await expect(page.getByRole("button", { name: "B2 123456" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("phone-dark.png"), fullPage: true });
});

test("server errors are visible and retry restores the registry", async ({ page }) => {
  await setup(page);
  let fail = true;
  await page.route("**/api/admin/control/documents?*", async route => {
    if (!fail) return route.fallback();
    fail = false;
    return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "SOURCE_UNAVAILABLE", message: "Source temporarily unavailable" } }) });
  });
  await page.goto("/admin/documents");
  await expect(page.getByRole("alert")).toContainText("SOURCE_UNAVAILABLE");
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("button", { name: "UZNF", exact: true })).toBeVisible();
});
