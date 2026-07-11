import { test, expect } from "@playwright/test";

/* Smoke tests for the dashboard app (visual restyle — logic unchanged).
   /api/** is mocked so tests are deterministic and need no backend. */

const COMPANIES = { companies: [
  { ticker: "AGBA", company_name: "AGBA Bank", sector: "Banks" },
  { ticker: "ALKB", company_name: "Aloqabank", sector: "Banks" },
  { ticker: "KVTS", company_name: "Kvarts", sector: "Industry" },
] };
const SECURITIES = { securities: {
  AGBA: { security_type: "stock", last_price: 1500, industry: "Banks" },
  ALKB: { security_type: "stock", last_price: 900, industry: "Banks" },
  KVTS: { security_type: "stock", last_price: 320, industry: "Industry" },
} };
const FINANCIALS = { ok: true, financials: {
  AGBA: { net_income: 2e9, revenue: 9e9 }, ALKB: { net_income: 1.2e9, revenue: 6e9 }, KVTS: { net_income: 3e8, revenue: 1.5e9 },
} };
const RATIOS = { ok: true, ratios: {
  AGBA: { roe: 18.2, roa: 6.1, net_profit_margin: 22, debt_to_equity: 1.2, total_equity: 1e10 },
  ALKB: { roe: 12.0, roa: 4.0, net_profit_margin: 15, debt_to_equity: 2.1, total_equity: 6e9 },
  KVTS: { roe: 0.56, roa: 0.24, net_profit_margin: 0.23, debt_to_equity: 76.9, total_equity: 2e9 },
} };
const STOCKS = { stocks: [
  { ticker: "AGBA", name: "AGBA Bank", isin: "UZ0001", last_price: 1500, close_price: 1440, volume: 5e6, quantity: 3333, trade_count: 40, market_cap: 3e10, nominal: 1000, sector: "Banks" },
  { ticker: "ALKB", name: "Aloqabank", isin: "UZ0002", last_price: 900, close_price: 930, volume: 2e6, quantity: 2222, trade_count: 21, market_cap: 1.2e10, nominal: 1000, sector: "Banks" },
  { ticker: "KVTS", name: "Kvarts", isin: "UZ0003", last_price: 320, close_price: 300, volume: 8e5, quantity: 2500, trade_count: 12, market_cap: 3e9, nominal: 100, sector: "Industry" },
] };

const ANALYZE = {
  company_name: "AGBA Bank", ticker: "AGBA", input: "AGBA", from_cache: false,
  summary: { score: 60, grade: "B" },
  metrics: { total_score: { score: 60, grade: "B" } },
  sections: {},
  ifrs_snapshot: {
    series: { annual: [{ year: 2023, revenue: 8e9, net_income: 1.5e9, equity: 9e9, total_assets: 3e10, net_profit_margin: 18 }, { year: 2024, revenue: 9e9, net_income: 2e9, equity: 1e10, total_assets: 4e10, net_profit_margin: 22 }] },
    income_statement: { revenue: 9e9, net_income: 2e9, ebit: 2.4e9, ebitda: 2.9e9, net_margin_pct: 22 },
    balance_sheet: { total_assets: 4e10, equity: 1e10, debt_to_equity: 1.5, current_ratio: 1.2 },
    quality: { roe_pct: 20, roa_pct: 5, interest_coverage: 2.2, altman: { zone: "grey" }, piotroski: { score: 5, max: 9 } },
  },
  article_report: { meta: { company: "AGBA Bank", ticker: "AGBA" }, abstract: "Демо.", sections: [] },
  risk_profile: { version: 1, axes: [
    { key: "financial", label: "Финансовый риск", level: "medium", level_label: "Средний", drivers: ["Altman в серой зоне", "Повышенный долг/капитал (1.5)"] },
    { key: "market", label: "Рыночный риск", level: "low", level_label: "Низкий", drivers: ["Показатели ликвидности в норме"] },
    { key: "informational", label: "Информационный риск", level: "na", level_label: "Недостаточно данных", drivers: ["Требуется модуль анализа новостей (§3.11)"] },
  ] },
  observations: [
    { type: "anomaly", tone: "warning", text: "Выручка на 2.3σ выше исторической нормы за 4 лет" },
    { type: "joint", tone: "danger", text: "Одновременное ухудшение показателей: прибыль, маржа, долг/капитал" },
  ],
};
const PERIODS = { ok: true, periods: { annual_years: [2024, 2023, 2022], quarterly: ["2024Q2", "2024Q1"], latest_annual_year: 2024, latest_quarterly: "2024Q2" } };

async function mockApi(page) {
  await page.route("**/api/**", (route) => {
    const p = new URL(route.request().url()).pathname;
    const j = (b, s = 200) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(b) });
    if (p === "/api/companies") return j(COMPANIES);
    if (p === "/api/securities") return j(SECURITIES);
    if (p === "/api/market/financials") return j(FINANCIALS);
    if (p === "/api/market/ratios") return j(RATIOS);
    if (p === "/api/analyze") return j(ANALYZE);
    if (p === "/api/analyze/export/pdf") return route.fulfill({ status: 200, headers: { "content-type": "application/pdf" }, body: "%PDF-1.4\n%%EOF" });
    if (p.startsWith("/api/periods")) return j(PERIODS);
    if (p === "/api/market/trade-stats") return j({ stats: {} });
    if (p === "/api/market/stocks") return j(STOCKS);
    if (p === "/api/market/trades") return j({ total_volume: 7.8e6, total_trade_count: 73 });
    if (p === "/api/auth/me") return j({ user: null }, 401);
    if (p === "/api/notifications") return j({ count: 0, notifications: [] });
    if (p === "/api/catalog/status") return j({ last_sync: null });
    return j({});
  });
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("boots to the landing view without uncaught errors", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.locator("header.topbar")).toBeVisible();
  await expect(page.locator(".hero-copy-block h1")).toBeVisible();
  await expect(page.locator(".topbar-nav-btn").first()).toBeVisible();
  expect(errors, errors.join("\n")).toHaveLength(0);
});

test("theme toggle flips the data-theme attribute", async ({ page }) => {
  await page.goto("/");
  const before = await page.locator("html").getAttribute("data-theme");
  await page.locator(".theme-toggle").click();
  const after = before === "dark" ? "light" : "dark";
  await expect(page.locator("html")).toHaveAttribute("data-theme", after);
});

test("language switch re-renders the hero copy", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".hero-copy-block h1")).toContainText(/\S/);
  await page.locator("#languageSelect").selectOption("en");
  await expect(page.locator(".hero-copy-block h1")).not.toContainText("Современный");
});

test("navigating to Рынок shows the market board", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  await expect(page.getByText(/Цены акций/)).toBeVisible();
  await expect(page.getByText("AGBA Bank").first()).toBeVisible();
});

test("navigating to Анализ shows the analysis form", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Анализ", exact: true }).click();
  await expect(page.locator(".analysis-form-modern").first()).toBeVisible();
});

test("Рынок shows §3.8 multiplier columns and exports CSV", async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem("uz_market_cols", JSON.stringify(["change", "mktCap", "pe", "pb", "roe"]))
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  await expect(page.locator(".market-table thead")).toContainText("P/E");
  await expect(page.locator(".market-table thead")).toContainText("P/B");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator(".market-export-btn").click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.csv$/);
});

test("analysis renders the §3.4 risk profile", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_token", "e2e-token"));
  await page.route("**/api/auth/me", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: { full_name: "E2E", email: "e2e@test.uz" } }) }));
  await page.goto("/");
  await page.getByRole("button", { name: "Анализ", exact: true }).click();
  await page.locator(".analysis-input-wrapper input").first().fill("AGBA");
  await page.waitForTimeout(600);
  await page.getByRole("button", { name: /Анализировать/ }).click();
  await expect(page.locator(".risk-profile-panel")).toBeVisible({ timeout: 12000 });
  await expect(page.locator(".risk-profile-panel")).toContainText("Финансовый риск");
  await expect(page.locator(".risk-profile-panel")).toContainText("§3.11");
  // §3.5 statistical observations
  await expect(page.locator(".observations-panel")).toBeVisible();
  await expect(page.locator(".observations-panel")).toContainText("Одновременное ухудшение");
  // C1 EBITDA row + C4 stacked structure chart + C5 server PDF
  await expect(page.locator(".financial-bars")).toContainText("EBITDA");
  await expect(page.locator(".structure-panel")).toBeVisible();
  const [pdf] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /Скачать PDF/ }).first().click(),
  ]);
  expect(pdf.suggestedFilename()).toMatch(/\.pdf$/);
});

test("mobile: hamburger opens the nav drawer (§3.12)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 780 });
  await page.goto("/");
  await expect(page.locator(".topbar-burger")).toBeVisible();
  await page.locator(".topbar-burger").click();
  await expect(page.locator(".topbar")).toHaveClass(/is-nav-open/);
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  await expect(page.locator(".topbar")).not.toHaveClass(/is-nav-open/);
  await expect(page.getByText(/Цены акций/)).toBeVisible();
});
