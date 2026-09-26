import { test, expect } from "@playwright/test";

const candidate = {
  ticker: "ZZCO",
  company_name: "ZZ Company aksiyadorlik jamiyati",
  org_id: "777",
  isin: "UZ0000000001",
  security_type: "stock",
  share_type: "ordinary",
  sector: "other",
  logo_url: "",
  resolved_by: "ticker",
  status: "pending",
  sync_status: "",
  warnings: [],
  can_approve: true,
  catalog_visible: 1,
};

async function mockAdminApi(page, state) {
  await page.addInitScript(() => {
    localStorage.setItem("uz_stock_analyzer_token", "admin-token");
    localStorage.setItem("uz_stock_analyzer_language", "en");
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const send = (body, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
    if (path === "/api/auth/me") return send({
      user: { id: 1, email: "admin@example.com", full_name: "Admin", is_admin: true },
    });
    if (path === "/api/companies") return send({ ok: true, companies: [] });
    if (path === "/api/securities") return send({ ok: true, securities: {} });
    if (path === "/api/catalog/status") return send({ ok: true, last_sync: null });
    if (path === "/api/notifications") return send({ ok: true, count: 0, notifications: [] });
    if (path === "/api/audit/rules") return send({ ok: true, items: [] });
    if (path === "/api/admin/overview") return send({
      ok: true,
      catalog: { securities: 92, stocks: 80, bonds: 12, preferred: 9 },
      audit: { open: {}, history: [], queue: [], latest: null },
      news: { days: 7, collected: 0, published: 0, rejected: 0, without_image: 0 },
      streams: [],
    });
    if (path === "/api/admin/companies" && request.method() === "GET") {
      const requestedStatus = url.searchParams.get("status");
      const currentStatus = state.approved ? "approved" : "pending";
      const visible = requestedStatus && requestedStatus !== currentStatus
        ? [] : [{ ...candidate, status: currentStatus, sector: state.sector,
          sync_status: state.approved ? "queued" : "",
          catalog_visible: state.catalogVisible ? 1 : 0 }];
      return send({
        ok: true,
        count: visible.length,
        summary: { pending: state.approved ? 0 : 1, approved: state.approved ? 1 : 0, rejected: 0 },
        unresolved: 0,
        items: visible,
      });
    }
    if (path === "/api/admin/companies/ZZCO/preview") {
      return send({ ok: true, company: { ...candidate, sector: state.sector } });
    }
    if (path === "/api/admin/companies/ZZCO/approve") {
      state.approved = true;
      state.sector = JSON.parse(request.postData() || "{}").sector;
      return send({
        ok: true,
        company: { ...candidate, status: "approved", sector: state.sector, sync_status: "queued",
          catalog_visible: state.catalogVisible ? 1 : 0 },
        sync_started: true,
        sync_requested: true,
      });
    }
    if (path === "/api/admin/companies/ZZCO/visibility" && request.method() === "PATCH") {
      state.catalogVisible = Boolean(JSON.parse(request.postData() || "{}").visible);
      return send({
        ok: true,
        company: { ...candidate, status: "approved", sector: state.sector,
          catalog_visible: state.catalogVisible ? 1 : 0, affected_tickers: ["ZZCO"] },
      });
    }
    return send({ ok: true });
  });
}

test("admin imports an OpenInfo company and publishes it without leaving the panel", async ({ page }, testInfo) => {
  const state = { approved: false, sector: "other", catalogVisible: true };
  await mockAdminApi(page, state);
  await page.goto("/admin/companies");

  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Companies/ })).toHaveAttribute("aria-selected", "true");
  const intake = page.locator(".admin-company-intake");
  await intake.getByLabel("Ticker").fill("ZZCO");
  await intake.getByRole("button", { name: "Check OpenInfo" }).click();

  const review = page.locator(".admin-company-review");
  await expect(review.getByRole("heading", { name: /ZZCO/ })).toBeVisible();
  await expect(review.getByText("OpenInfo 777")).toBeVisible();
  await review.getByLabel("Sector").selectOption("manufacturing");
  await review.getByRole("button", { name: "Publish and synchronize" }).click();

  await expect(page.getByText("Company published; synchronization started.")).toBeVisible();
  expect(state.approved).toBe(true);
  expect(state.sector).toBe("manufacturing");
  await page.getByRole("button", { name: /Published/ }).click();
  const catalogCheckbox = page.locator(".admin-company-table tr").filter({ hasText: "ZZCO" }).getByRole("checkbox");
  await expect(catalogCheckbox).toBeChecked();
  await catalogCheckbox.click();
  await expect(catalogCheckbox).not.toBeChecked();
  await expect(page.getByText("Company hidden from the catalog.")).toBeVisible();
  expect(state.catalogVisible).toBe(false);
  await catalogCheckbox.click();
  await expect(catalogCheckbox).toBeChecked();
  await expect(page.getByText("Company restored to the catalog.")).toBeVisible();
  expect(state.catalogVisible).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("admin-company-import-desktop.png"), fullPage: true });
});

test("company import form remains usable on a phone viewport", async ({ page }, testInfo) => {
  const state = { approved: false, sector: "other", catalogVisible: true };
  await mockAdminApi(page, state);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin/companies");
  const intake = page.locator(".admin-company-intake");
  await intake.getByLabel("Ticker").fill("ZZCO");
  await intake.getByRole("button", { name: "Check OpenInfo" }).click();

  await expect(page.locator(".admin-company-review")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
  await page.screenshot({ path: testInfo.outputPath("admin-company-import-mobile.png"), fullPage: true });
});
