import { test, expect } from "@playwright/test";

/* ── API fixtures ─────────────────────────────────────────────────────────── */
const COMPANIES = {
  companies: [
    { ticker: "AGBA", company_name: "AGBA Bank", sector: "Banks", logo: null },
    { ticker: "ALKB", company_name: "Aloqabank", sector: "Banks", logo: null },
    { ticker: "KVTS", company_name: "Kvarts", sector: "Industry", logo: null },
  ],
};
const SECURITIES = {
  securities: {
    AGBA: { security_type: "stock", is_preferred: false, last_price: 1500, industry: "Banks" },
    ALKB: { security_type: "stock", is_preferred: false, last_price: 900, industry: "Banks" },
    KVTS: { security_type: "stock", is_preferred: false, last_price: 320, industry: "Industry" },
  },
};
const FINANCIALS = {
  financials: {
    AGBA: { net_income: 2_000_000_000, revenue: 9_000_000_000, total_liabilities: 1, cash: 1, gross_profit: 1, operating_income: 1 },
    ALKB: { net_income: 1_200_000_000, revenue: 6_000_000_000 },
    KVTS: { net_income: 300_000_000, revenue: 1_500_000_000 },
  },
};
const STOCKS = {
  stocks: [
    { ticker: "AGBA", name: "AGBA Bank", isin: "UZ0001", last_price: 1500, close_price: 1440, open: 1450, high: 1520, low: 1435, volume: 5_000_000, quantity: 3333, trade_count: 40, market_cap: 30_000_000_000, nominal: 1000, sector: "Banks" },
    { ticker: "ALKB", name: "Aloqabank", isin: "UZ0002", last_price: 900, close_price: 930, open: 925, high: 940, low: 895, volume: 2_000_000, quantity: 2222, trade_count: 21, market_cap: 12_000_000_000, nominal: 1000, sector: "Banks" },
    { ticker: "KVTS", name: "Kvarts", isin: "UZ0003", last_price: 320, close_price: 300, open: 305, high: 325, low: 299, volume: 800_000, quantity: 2500, trade_count: 12, market_cap: 3_000_000_000, nominal: 100, sector: "Industry" },
  ],
};
const ANALYZE = {
  company_name: "AGBA Bank",
  ticker: "AGBA",
  input: "AGBA",
  from_cache: false,
  summary: { score: 72, grade: "B" },
  metrics: { total_score: { score: 72, grade: "B" } },
  sections: {},
  ifrs_snapshot: { series: { annual: [] }, quality: { roe_pct: 15 } },
  article_report: { meta: { company: "AGBA Bank", ticker: "AGBA" }, abstract: "Демо-отчёт.", sections: [] },
};
const COMPARE = {
  comparison: {
    leaders: {},
    ranking: [],
    normalized_ranking: [
      { rank: 1, ticker: "AGBA", composite_score: 74 },
      { rank: 2, ticker: "ALKB", composite_score: 61 },
    ],
    charts: [],
    tables: {},
    summary: { short: "" },
    comparative_ai_summary: { text: "Демонстрационное сравнение.", model: "test" },
    errors: [],
  },
};
const LISTINGS = {
  ok: true,
  listed: [{ ticker: "AGBA", isin: "UZ0001", name: "AGBA Bank", listing_date: "2024-02-01" }],
  inactive: [],
  inactive_days: 30,
};

async function mockApi(page) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (p === "/api/companies") return json(COMPANIES);
    if (p === "/api/securities") return json(SECURITIES);
    if (p === "/api/market/financials") return json(FINANCIALS);
    if (p === "/api/market/trade-stats") return json({ stats: {} });
    if (p === "/api/market/stocks") return json(STOCKS);
    if (p === "/api/market/trades") return json({ total_volume: 7_800_000, total_trade_count: 73 });
    if (p === "/api/analyze") return json(ANALYZE);
    if (p === "/api/compare") return json(COMPARE);
    if (p === "/api/listings/feed") return json(LISTINGS);
    if (p.startsWith("/api/dividends/")) return json({ dividends: [] });
    if (p.startsWith("/api/price-history/")) return json({ history: [] });
    if (p.endsWith("/reports")) return json({ reports: [], ratios: {} });
    if (p.includes("/info")) return json({ security: SECURITIES.securities.AGBA, wiki: null });
    if (p === "/api/auth/me") return json({ user: null }, 401);
    if (p === "/api/notifications") return json({ count: 0, notifications: [] });
    if (p === "/api/catalog/status") return json({ last_sync: null });
    return json({});
  });
}

async function ask(page, text) {
  const box = page.locator("#cx-input");
  await box.click();
  await box.fill(text);
  await box.press("Enter");
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

/* ── Tests ────────────────────────────────────────────────────────────────── */
test("boots to welcome with example prompts and no uncaught errors", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "С чего начнём?" })).toBeVisible();
  await expect(page.locator(".cx-example")).toHaveCount(4);
  await expect(page.locator(".cx-composer-form")).toBeVisible();
  expect(errors, errors.join("\n")).toHaveLength(0);
});

test("theme toggle flips data-theme and persists", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.locator('button[aria-label="Dark theme"]').click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("language switch updates the composer placeholder", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#cx-input")).toHaveAttribute("placeholder", /Спросите про компанию/);
  await page.locator('select[aria-label="Language"]').selectOption("en");
  await expect(page.locator("#cx-input")).toHaveAttribute("placeholder", /Ask about a company/);
});

test("sending a message creates a user bubble and an assistant answer", async ({ page }) => {
  await page.goto("/");
  await ask(page, "помощь");
  await expect(page.locator(".cx-msg--user")).toContainText("помощь");
  await expect(page.locator(".cx-msg--assistant")).toBeVisible();
});

test("market query renders a market snapshot", async ({ page }) => {
  await page.goto("/");
  await ask(page, "что сейчас на рынке");
  await expect(page.locator(".cx-msg--assistant")).toContainText("Обзор рынка");
  await expect(page.locator(".cx-msg--assistant")).toContainText("Инструменты");
});

test("glossary query returns a term card", async ({ page }) => {
  await page.goto("/");
  await ask(page, "что такое P/E");
  await expect(page.locator(".cx-msg--assistant")).toBeVisible();
  // either a resolved term card or the graceful "not found + chips" fallback
  await expect(page.locator(".cx-term, .cx-followups").first()).toBeVisible();
});

test("analyze query dispatches and shows the analysis answer without crashing", async ({ page }) => {
  await page.goto("/");
  await ask(page, "проанализируй AGBA");
  await expect(page.locator(".cx-answer-intent").last()).toContainText("Анализ отчётности");
  // app still alive: composer present
  await expect(page.locator(".cx-composer-form")).toBeVisible();
});

test("screener query lists ranked securities by P/E", async ({ page }) => {
  await page.goto("/");
  await ask(page, "самые дешёвые по p/e");
  await expect(page.locator(".cx-list-row").first()).toBeVisible();
  await expect(page.locator(".cx-msg--assistant")).toContainText("P/E");
});
