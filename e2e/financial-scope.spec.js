import { test, expect } from "@playwright/test";

test("scope switch isolates tables and passport requests and remains usable when empty", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_language", "en"));
  const passportScopes = [];
  await page.route("**/api/**", route => {
    const url = new URL(route.request().url());
    let result = { ok: true, items: [], companies: [], securities: {} };
    if (url.pathname === "/api/company/DEMO/financials") {
      const scope = url.searchParams.get("scope") || "consolidated";
      const empty = url.searchParams.get("freq") === "quarterly";
      result = { ok: true, scope, available_scopes: ["consolidated", "separate"], periods: empty ? [] : ["2024"], series: empty ? {} : {
        interest_income: { money: true, unit: "UZS", values: { "2024": scope === "separate" ? 200000 : 800000 } },
        net_profit: { money: true, unit: "UZS", values: { "2024": scope === "separate" ? 100000 : 500000 } },
      } };
    }
    if (url.pathname.endsWith("/financials/passport")) {
      passportScopes.push(url.searchParams.get("scope"));
      result = { ok: true, status: "SOURCED", source: { scope: url.searchParams.get("scope"), perimeter: url.searchParams.get("scope"), page: 2, period_year: 2024, raw_value: 100, normalized_value: 100000, unit_scale: 1000, currency: "USD", fx: { rate: 12920.48, as_of: "2024-12-31", effective_date: "2024-12-31", source_url: "https://cbu.uz/ru/arkhiv-kursov-valyut/json/all/2024-12-31/", basis: "period_end_presentation" } } };
    }
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(result) });
  });
  await page.goto("/company/DEMO?tab=financials");
  await page.getByRole("button", { name: "МСФО", exact: true }).click();
  await page.getByRole("button", { name: "Table", exact: true }).click();
  await expect(page.getByRole("button", { name: "Consolidated group", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Separate entity", exact: true }).click();
  await expect(page.locator(".company-financials table").getByRole('button', { name: '100', exact: true })).toBeVisible();
  await expect(page.locator(".company-financials table").getByRole('button', { name: '500', exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "100", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("separate");
  await expect(page.getByRole("dialog")).toContainText("USD");
  await expect(page.getByRole("dialog")).toContainText("12920.48");
  await expect(page.getByRole("dialog")).toContainText("2024-12-31");
  expect(passportScopes).toEqual(["separate"]);
  await page.getByRole("button", { name: "Close source passport" }).click();
  await page.getByRole("button", { name: "Quarterly", exact: true }).click();
  await expect(page.getByText(/Quarterly figures are not available yet/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Consolidated group", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Annual", exact: true }).click();
  await page.getByRole("button", { name: "Consolidated group", exact: true }).click();
  await expect(page.locator(".company-financials table").getByRole('button', { name: '500', exact: true })).toBeVisible();
});
