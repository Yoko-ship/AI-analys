import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

// Captured from the two Python public paths using UZMK's actual 2026 H1
// workbook. Python regression tests independently verify the arithmetic.
const DATA = JSON.parse(readFileSync(new URL("../tests/fixtures/profitability_display.json", import.meta.url), "utf8"));
const REPORT = JSON.parse(readFileSync(new URL("../tests/fixtures/sector_ui_report.json", import.meta.url), "utf8"));
const SEC = { ticker: "UZMK", name: "Узметкомбинат", type: "stock", isin: "QA-UZMK", last_price: 4000, last_trade_date: "2026-10-21" };

for (const mobile of [false, true]) {
  test(`screener and analysis display the same period returns ${mobile ? "mobile dark" : "desktop"}`, async ({ page }) => {
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript((dark) => {
      sessionStorage.setItem("uz_sponsor_seen", "1");
      localStorage.setItem("uz_stock_analyzer_token", "local-qa-token");
      localStorage.setItem("uz_market_cols_v3", JSON.stringify(["roe", "roa"]));
      localStorage.setItem("uz_stock_analyzer_theme", dark ? "dark" : "light");
    }, mobile);
    await page.route("**/api/**", route => {
      const path = new URL(route.request().url()).pathname;
      const json = body => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
      if (path.endsWith("/ai-report")) return json({ ...REPORT, ratios: DATA.ratios });
      if (path === "/api/securities") return json({ ok: true, securities: { UZMK: SEC } });
      if (path.endsWith("/info")) return json({ ok: true, security: SEC });
      if (path === "/api/companies") return json({ companies: [{ ticker: "UZMK", company_name: SEC.name }] });
      if (path === "/api/market/stocks") return json({ stocks: [SEC] });
      if (path === "/api/market/multiples") return json({ ok: true, items: [DATA.multiples] });
      if (path === "/api/market/financials") return json({ ok: true, financials: {} });
      if (path === "/api/auth/me") return json({ user: { id: 1, email: "qa@example.org", pro_access: true } });
      return json({ ok: true, items: [], points: [], series: {}, reports: [], periods: [], notifications: [] });
    });
    await page.goto("/market");
    const row = page.locator(".market-table tbody tr").filter({ hasText: "UZMK" });
    await expect(row).toContainText("10,16%");
    await expect(row).toContainText("4,44%");
    await expect(row).toContainText("2026Q2");
    await page.screenshot({ path: `tmp/roe-roa-board-${mobile ? "mobile" : "desktop"}.png` });
    await page.goto("/company/UZMK");
    await page.getByTestId("company-insight-card").getByRole("button", { name: "Открыть полный анализ" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByText("Финансовые коэффициенты", { exact: true }).click();
    for (const [code, value] of [["roe", "10,16%"], ["roa", "4,44%"]]) {
      const ratio = dialog.getByTestId(`verified-ratio-${code}`);
      await expect(ratio).toContainText(value);
      await expect(ratio).toContainText("среднее на начало и конец периода");
    }
    await dialog.getByTestId("verified-ratio-roe").scrollIntoViewIfNeeded();
    await page.screenshot({ path: `tmp/roe-roa-analysis-${mobile ? "mobile" : "desktop"}.png` });
    expect(errors).toEqual([]);
  });
}
