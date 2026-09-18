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

test("operations overview, navigation and desktop layout", async ({ page }, testInfo) => {
  const failures = [];
  page.on("pageerror", error => failures.push(error.message));
  await setup(page);
  await page.setViewportSize({ width: 1600, height: 1050 });
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
  await expect(page.getByText("96%", { exact: true })).toBeVisible();
  await expect(page.getByText("PERIOD_CLASSIFICATION_ERROR", { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("overview-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "Documents", exact: true }).first().click();
  await expect(page).toHaveURL(/\/admin\/documents$/);
  await expect(page.getByRole("heading", { name: "Documents", exact: true })).toBeVisible();
  expect(failures).toEqual([]);
});

test("bank pipeline alerts and monitor freshness appear in the dashboard", async ({ page }) => {
  const fixture = await setup(page, "administrator");
  fixture.financialIngestion.incidents = [{ code: "FAILED_JOBS", detail: "2 failed jobs require investigation", first_seen: "2026-09-18T10:00:00Z" }];
  await page.goto("/admin");
  const card = page.getByRole("region", { name: "Bank data pipeline" });
  await expect(card.getByText("2 failed jobs require investigation")).toBeVisible();
  await expect(card.getByText(/Published periods: 19/)).toBeVisible();
  fixture.financialIngestion.incidents = [];
  fixture.financialIngestion.monitor_stale = true;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(card.getByText(/Monitor is overdue/)).toBeVisible();
  await expect(card.getByText(/No active failures/)).toHaveCount(0);
  fixture.financialIngestion.monitor_stale = false;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(card.getByText(/No active failures/)).toBeVisible();
});

test("incidents explain the issue in the selected language while retaining its audit code", async ({ page }, testInfo) => {
  await setup(page);
  await page.goto("/admin/incidents");
  await expect(page.getByText("Reporting period is classified incorrectly", { exact: true })).toBeVisible();
  await expect(page.getByText("Classification", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "First page", exact: true })).toBeVisible();
  await expect(page.getByText("Первая страница", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Priority 1", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: /Reporting period is classified incorrectly/ });
  await expect(dialog.locator(".control-incident-explainer code")).toHaveText("PERIOD_CLASSIFICATION_ERROR");
  await expect(dialog.getByText("Classification", { exact: true })).toBeVisible();
  await expect(dialog.getByText(/The check stopped publication or flagged the data for review/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("incident-detail.png"), fullPage: true });
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

test("calculation to source and retry creates a tracked job", async ({ page }, testInfo) => {
  const fixture = await setup(page);
  await page.goto("/admin/calculations?object=calc-fixture");
  await expect(page.getByText("market_price / NAV_per_share", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Net asset value 123456/ }).click();
  await expect(page.getByText("Balance!B2", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Reprocess", exact: true }).click();
  const confirm = page.getByRole("dialog", { name: "Review this action" });
  await confirm.getByLabel("Reason", { exact: true }).fill("Verify the classified half-year period");
  await confirm.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/jobs\?object=job-new/);
  await expect(page.getByRole("progressbar")).toBeVisible();
  const submitted = fixture.calls.find(call => call.method === "POST");
  expect(submitted.body.version).toBe(1);
  expect(submitted.body.reason).toContain("half-year");
  await page.screenshot({ path: testInfo.outputPath("tracked-job.png"), fullPage: true });
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

test("rule draft is reachable and narrow viewport does not overflow", async ({ page }, testInfo) => {
  await setup(page);
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.goto("/admin/formulas");
  await page.getByRole("button", { name: "New rule", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Review this action" });
  await dialog.getByLabel("Title", { exact: true }).fill("Reviewed liquidity formula");
  await dialog.getByLabel("Reason", { exact: true }).fill("Check source-line compatibility");
  await dialog.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Formulas", exact: true }).getByText("Reviewed liquidity formula", { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("rule-tablet.png"), fullPage: true });
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
