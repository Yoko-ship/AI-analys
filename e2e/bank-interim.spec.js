import { test, expect } from "@playwright/test";

test("IFRS interim captions retain YTD basis without NSBU or QoQ claims", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_language", "en"));
  await page.route("**/api/**", route => {
    const url = new URL(route.request().url());
    let result = { ok: true, items: [], companies: [], securities: {} };
    if (url.pathname === "/api/company/SQBN/financials") {
      result = url.searchParams.get("form") === "MSFO" && url.searchParams.get("freq") === "quarterly"
        ? { ok: true, periods: ["2024Q2", "2024Q1"], period_basis: "cumulative_ytd", series: {
          interest_income: { money: true, unit: "UZS", values: { "2024Q2": 4243637000000, "2024Q1": 2000000000000 } },
          net_profit: { money: true, unit: "UZS", values: { "2024Q2": 247268000000, "2024Q1": 100000000000 } },
        } }
        : { ok: true, periods: [], series: {} };
    }
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(result) });
  });
  await page.goto("/company/SQBN?tab=financials&freq=quarterly");
  await page.getByRole("button", { name: "МСФО", exact: true }).click();
  await expect(page.getByText(/IFRS: income and expenses are cumulative from January/)).toBeVisible();
  await expect(page.getByText(/Sums in UZS from interim IFRS filings/)).toBeVisible();
  await expect(page.getByText(/Sums in UZS per discrete quarter/)).toHaveCount(0);
  await page.getByRole("button", { name: "Table", exact: true }).click();
  await expect(page.getByText("Growth QoQ", { exact: true })).toHaveCount(0);
});
