import { test, expect } from "@playwright/test";

async function catalogFixture(page, { signedIn = true, errors = [], status = 200, waitForSync = Promise.resolve() } = {}) {
  let refreshed = false;
  const syncRequests = [];
  if (signedIn) await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_token", "catalog-test-session"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const json = (body, code = 200) => route.fulfill({ status: code, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/auth/me") return json(signedIn ? { user: { id: 1, email: "reader@example.test", tier: "free", is_admin: false } } : { detail: "Sign in required" }, signedIn ? 200 : 401);
    if (path === "/api/catalog/sync") {
      syncRequests.push(route.request().postDataJSON());
      await waitForSync;
      refreshed = status === 200;
      return json(status === 200 ? { ok: true, added: 1, errors } : { detail: "Source unavailable" }, status);
    }
    if (path === "/api/catalog/companies") return json({ ok: true, companies: [{ ticker: "BIOK", company_name: "Biokimyo", sector: "manufacturing", total_count: refreshed ? 2 : 1, nsbu_count: refreshed ? 2 : 1 }] });
    if (path === "/api/catalog/index/BIOK") return json({ ok: true, ticker: "BIOK", company_name: "Biokimyo", availability: { NSBU: { annual: (refreshed ? [2026, 2025] : [2025]).map(year => ({ year, quarter: 0 })), quarter: [] } } });
    if (path === "/api/catalog/status") return json({ ok: true, total_reports: refreshed ? 2 : 1, companies_synced: 1 });
    return json({ ok: true, companies: [], securities: {}, items: [], points: [] });
  });
  await page.goto("/catalog");
  await expect(page.getByRole("heading", { name: "Biokimyo", exact: true })).toBeVisible();
  return syncRequests;
}

test("catalog refresh updates reports and the obsolete analysis shortcut is absent", async ({ page }, testInfo) => {
  let finish;
  const waitForSync = new Promise(resolve => { finish = resolve; });
  const requests = await catalogFixture(page, { waitForSync });
  await expect(page.getByRole("button", { name: "Открыть в Анализе" })).toHaveCount(0);
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  try {
    await expect(page.getByRole("button", { name: "Синхронизация...", exact: true })).toBeDisabled();
    expect(requests).toEqual([{ force: true, ticker: "BIOK" }]);
  } finally { finish(); }
  await expect(page.locator(".catalog-report-table tbody tr")).toHaveCount(2);
  await expect(page.locator(".catalog-report-stats > span").filter({ hasText: "НСБУ" }).locator("strong")).toHaveText("2");
  await expect(page.getByText("Обновлено", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Обновить", exact: true })).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath("catalog-actions.png"), fullPage: true });
});

test("catalog refresh reports upstream errors instead of false success", async ({ page }) => {
  await catalogFixture(page, { errors: ["OpenInfo timeout"] });
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(page.getByText("Не удалось обновить все отчёты: источник вернул ошибки. Попробуйте позже.", { exact: true })).toBeVisible();
  await expect(page.getByText("Обновлено", { exact: true })).toHaveCount(0);
  await expect(page.locator(".catalog-report-table tbody tr")).toHaveCount(2);
});

test("catalog refresh surfaces HTTP failures and allows retry", async ({ page }) => {
  await catalogFixture(page, { status: 503 });
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(page.getByText("Source unavailable", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Обновить", exact: true })).toBeEnabled();
});

test("catalog refresh requires sign-in before starting a source sync", async ({ page }) => {
  const requests = await catalogFixture(page, { signedIn: false });
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(page.getByText("Войдите для синхронизации", { exact: true })).toBeVisible();
  expect(requests).toHaveLength(0);
});
