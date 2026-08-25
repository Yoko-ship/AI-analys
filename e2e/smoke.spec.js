import { test, expect } from "@playwright/test";

/* Smoke tests for the dashboard app (visual restyle — logic unchanged).
   /api/** is mocked so tests are deterministic and need no backend. */

const COMPANIES = { companies: [
  { ticker: "AGBA", company_name: "AGBA Bank", sector: "Banks" },
  { ticker: "ALKB", company_name: "Aloqabank", sector: "Banks" },
  { ticker: "KVTS", company_name: "Kvarts", sector: "Industry" },
] };
const SECURITIES = { ok: true, securities: {
  AGBA: { name: "AGBA Bank", security_type: "stock", last_price: 1500, close_price: 1440, industry: "Banks" },
  ALKB: { name: "Aloqabank", security_type: "stock", last_price: 900, close_price: 930, industry: "Banks" },
  KVTS: { name: "Kvarts", security_type: "stock", last_price: 320, close_price: 300, industry: "Industry" },
} };
const FINANCIALS = { ok: true, financials: {
  AGBA: { net_income: 2e9, revenue: 9e9 }, ALKB: { net_income: 1.2e9, revenue: 6e9 }, KVTS: { net_income: 3e8, revenue: 1.5e9 },
} };
const RATIOS = { ok: true, ratios: {
  AGBA: { roe: 18.2, roa: 6.1, net_profit_margin: 22, debt_to_equity: 1.2, total_equity: 1e10 },
  ALKB: { roe: 12.0, roa: 4.0, net_profit_margin: 15, debt_to_equity: 2.1, total_equity: 6e9 },
  KVTS: { roe: 0.56, roa: 0.24, net_profit_margin: 0.23, debt_to_equity: 76.9, total_equity: 2e9 },
} };
// `updated_at` here is the uzse mirror's own stamp, which the API now hands over
// with an explicit Z — it belongs in the tooltip, not in the headline number.
const STOCKS = { updated_at: "2026-07-31T14:00:00.003527Z", stocks: [
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
    income_statement: { revenue: 9e9, net_income: 2e9, ebit: 2.4e9, ebitda: 2.9e9, ebitda_margin_pct: 32.2, debt_to_ebitda: 1.8, net_margin_pct: 22 },
    balance_sheet: { total_assets: 4e10, equity: 1e10, debt_to_equity: 1.5, current_ratio: 1.2 },
    quality: { roe_pct: 20, roa_pct: 5, interest_coverage: 2.2, altman: { zone: "grey" }, piotroski: { score: 5, max: 9 } },
  },
  article_report: { meta: { company: "AGBA Bank", ticker: "AGBA" }, abstract: "Демо.", sections: [] },
  risk_profile: { version: 1, debt_load: { tier: 1, level: "moderate", label: "Умеренная", tone: "warning", debt_to_equity: 1.5, debt_to_ebitda: 1.8 }, axes: [
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

// Editorial feed (§3.11). Items carry the classifier's output; the article page at
// /news/{id} reads the same stored fields back — no model call on either path.
const NEWS_DISCLAIMER = "Тональность новостей и оценка влияния — статистический сигнал, а не рекомендация.";
const NEWS_ITEMS = [
  { id: 11, url: "https://spot.uz/story-one", source: "Spot.uz", source_id: "spot", lang: "ru",
    title: "Биржа расширяет листинг банков",
    snippet: "Листинговый комитет допустил к торгам четыре выпуска акций.",
    summary_ru: "Краткое изложение первой новости.",
    image_url: "data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==",
    published_at: "2026-07-24 09:00:00", type: "market", tone: "positive", tone_score: 0.42,
    impact: "high", direction: "up", sectors: ["banking"], relevance_score: 0.81, coverage_weight: 0.7,
    tickers: ["AGBA"], rank: 0.71 },
  { id: 12, url: "https://uzdaily.uz/story-two", source: "UzDaily", source_id: "uzdaily", lang: "ru",
    title: "ЦБ уточнил требования к капиталу", snippet: "", summary_ru: "Краткое изложение второй новости.",
    image_url: null, published_at: "2026-07-23 12:00:00", type: "regulatory", tone: "neutral", tone_score: 0.0,
    impact: "medium", direction: "unclear", sectors: [], relevance_score: 0.6, coverage_weight: 0.6,
    tickers: [], rank: 0.5 },
  // An openinfo filing: the portal has no page per material fact, so its link can only
  // reach the issuer's card and the article page must say so instead of promising an article.
  { id: 13, url: "https://openinfo.uz/ru/organizations/422?fact=98584", source: "openinfo.uz",
    source_id: "openinfo_facts", lang: "ru",
    title: "«Hamkorbank» АТБ: Выплаты дивидендов",
    snippet: "Существенный факт №42 на openinfo.uz. Дивиденды: начислено 161 662 245 000 сум, "
      + "выплачено 72.38%, срок выплаты до 05.11.2026. Не выплачено 27.62% (367 500 сум). "
      + "Причина по данным эмитента: недостаточно средств на счёте.",
    summary_ru: "Эмитент отчитался о выплате дивидендов акционерам.",
    image_url: null, published_at: "2026-07-22 10:00:00", collected_at: "2026-07-22 11:00:00",
    type: "corporate_event", tone: "neutral", tone_score: 0, impact: "low", direction: "unclear",
    sectors: [], relevance_score: 0.9, coverage_weight: 0.95, tickers: [], rank: 0.6 },
];

// What the price did around story 11 — two dated closes, as `formulas.price_reaction`
// returns them. Never a claim that the story moved the price.
const REACTION = {
  ticker: "AGBA", isin: "UZ0001", status: "ok", data_tier: "full", quality_note: null,
  before: { date: "2026-07-23", close: 1440 },
  after: { date: "2026-07-24", close: 1500, same_day: true },
  latest: { date: "2026-07-26", close: 1530 },
  sessions_after: 3,
  change: { value: 4.1666, status: "ok", base_date: "2026-07-23", date: "2026-07-24" },
  since: { value: 6.25, status: "ok", base_date: "2026-07-23", date: "2026-07-26" },
  volume: { value: 24000, status: "ok", date: "2026-07-24" },
  volume_vs_normal: { value: 2.4, status: "ok", baseline_sessions: 30, baseline_volume: 10000 },
};

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
    // refreshed_at is what OUR collector wrote, in UTC with an explicit Z.
    // Production stores the session as compacted YYYYMMDD, so that is what the
    // badge tooltip has to render.
    if (p === "/api/market/trade-stats") return j({ ok: true, stats: {}, refreshed_at: "2026-07-31T11:10:04Z", trade_date: "20260731" });
    if (p === "/api/market/stocks") return j(STOCKS);
    if (p === "/api/market/trades") return j({ total_volume: 7.8e6, total_trade_count: 73 });
    if (p === "/api/auth/me") return j({ user: null }, 401);
    if (p === "/api/notifications") return j({ count: 0, notifications: [] });
    if (p === "/api/catalog/status") return j({ last_sync: null });
    if (p === "/api/news") return j({ ok: true, count: 3, items: [
      { type: "report", ticker: "AGBA", company: "AGBA Bank", report_form: "NAS", period_type: "annual", year: 2025, quarter: 0, date: "2026-07-10 09:40:00" },
      { type: "listing", ticker: "NSTK", company: "Navoiy Sanoat", share_type: "ORD", date: "2026-07-08" },
      { type: "delisting", ticker: "OLDZ", company: "Eski Zavod", date: "2026-04-30" },
    ] });
    if (p === "/api/news/feed") return j({ ok: true, count: NEWS_ITEMS.length, items: NEWS_ITEMS, disclaimer: NEWS_DISCLAIMER });
    if (p.startsWith("/api/news/ticker/")) {
      const tk = p.slice("/api/news/ticker/".length);
      const items = NEWS_ITEMS.filter((n) => (n.tickers || []).includes(tk));
      return j({ ok: true, ticker: tk, count: items.length, items,
                 sentiment: { ticker: tk, count: 4, weighted_tone: 0.31, positive: 3, neutral: 1, negative: 0 } });
    }
    // Before the item route below, which would otherwise swallow it.
    if (p.startsWith("/api/news/item/") && p.endsWith("/reaction")) {
      return j({ ok: true, id: 11, published_at: "2026-07-24 09:00:00", items: [REACTION] });
    }
    if (p.startsWith("/api/news/item/")) {
      const id = Number(p.slice("/api/news/item/".length));
      const item = NEWS_ITEMS.find((n) => n.id === id);
      if (!item) return j({ detail: "news item not found" }, 404);
      return j({ ok: true, item, related: NEWS_ITEMS.filter((n) => n.id !== id), disclaimer: NEWS_DISCLAIMER });
    }
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

test("analysis setup uses labeled controls and honest progressive disclosure", async ({ page }) => {
  await page.goto("/analysis");
  await expect(page.getByRole("heading", { name: "Анализ компании", level: 1 })).toBeVisible();
  await expect(page.getByLabel("Компания", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Тип анализа", { exact: true })).toBeVisible();
  await expect(page.getByText("Дополнительные параметры", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Обновить из источника (обойти кэш)")).not.toBeVisible();
  await expect(page.getByText("Режим", { exact: true })).toHaveCount(0);

  await page.getByText("Дополнительные параметры", { exact: true }).click();
  await expect(page.getByLabel("Обновить из источника (обойти кэш)")).toBeVisible();

  const companyButton = page.getByRole("button", { name: /AGBA.*AGBA Bank/ });
  await companyButton.click();
  await expect(companyButton).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("Компания", { exact: true })).toHaveValue("AGBA");
});

test("profile workspace exposes account state, accessible editing, and exact history filters", async ({ page }) => {
  const signedInUser = {
    full_name: "E2E Investor",
    email: "e2e@test.uz",
    created_at: "2026-07-01T10:00:00Z",
    avatar_data_url: null,
  };
  const profile = {
    ok: true,
    user: signedInUser,
    stats: { total_analyses: 2, avg_score: 61, cached_analyses: 1 },
    favorites: [],
    recent_analyses: [
      { company_name: "AGBA Bank", company_input: "AGBA", ticker: "AGBA", created_at: "2026-08-22T10:00:00Z", from_cache: false },
      { company_name: "Kvarts", company_input: "KVTS", ticker: "KVTS", created_at: "2026-08-21T10:00:00Z", from_cache: true },
    ],
  };

  await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_token", "e2e-token"));
  await page.route("**/api/auth/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: signedInUser }) }));
  await page.route("**/api/profile", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(profile) }));
  await page.goto("/profile");

  await expect(page.getByRole("heading", { name: "Личный кабинет", level: 1 })).toBeVisible();
  await expect(page.getByText("E2E Investor", { exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Разделы профиля" })).toBeVisible();

  const editButton = page.getByRole("button", { name: "Редактировать профиль" });
  await expect(editButton).toHaveAttribute("aria-expanded", "false");
  await editButton.click();
  await expect(page.getByRole("button", { name: "Отмена" }).first()).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByLabel("Отображаемое имя")).toHaveValue("E2E Investor");
  await expect(page.getByText("JPG, PNG или WebP, не более 512 КБ")).toBeVisible();

  await expect(page.locator(".history-item")).toHaveCount(2);
  await page.getByLabel("Все анализы").selectOption("favorites");
  await expect(page.locator(".history-item")).toHaveCount(0);
  await expect(page.getByText("Показано: 0")).toBeVisible();
  await page.getByLabel("Все анализы").selectOption("all");
  await page.getByLabel("Поиск по компании или тикеру").fill("KVTS");
  await expect(page.locator(".history-item")).toHaveCount(1);
  await expect(page.locator(".history-item")).toContainText("Kvarts");
});

test("profile and analysis workspaces do not overflow a phone viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/profile", "/analysis"]) {
    await page.goto(path);
    const widths = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
    expect(widths.scroll).toBeLessThanOrEqual(widths.client);
  }
});

test("Новости renders the editorial feed (§3.11)", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Новости", exact: true }).click();
  await expect(page.locator(".newsdesk-head")).toContainText("Новости рынка");
  await expect(page.locator(".newsdesk-priority-story--lead")).toContainText("Биржа расширяет листинг банков");
  await expect(page.locator(".newsdesk-priority-story--secondary").first()).toContainText("ЦБ уточнил требования");
  await expect(page.locator(".newsdesk-feed-layout")).toBeVisible();
});

// Source imagery is part of the newsroom when it exists; filings without an image stay
// honest and compact instead of receiving a generated placeholder.
test("the newsroom uses source imagery without inventing placeholders (§3.11)", async ({ page }) => {
  await page.goto("/news");
  await expect(page.locator(".newsdesk-priority-story--lead")).toBeVisible();
  await expect(page.locator(".newsdesk-priority-story--secondary")).toHaveCount(2);
  await expect(page.locator(".newsdesk-priority-story--lead .newsdesk-priority-picture img")).toHaveCount(1);
  await expect(page.locator(".newsdesk-priority-story--secondary .newsdesk-priority-picture img")).toHaveCount(0);
});

test("a story opens on its own /news/{id} page instead of the source site (§3.11)", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Новости", exact: true }).click();
  // The card is a real link to our own route, not to the outlet.
  await expect(page.locator(".newsdesk-priority-story--lead")).toHaveAttribute("href", "/news/11");
  await page.locator(".newsdesk-priority-story--lead").click();
  await expect(page).toHaveURL(/\/news\/11$/);
  await expect(page.locator(".led-art-title")).toContainText("Биржа расширяет листинг банков");
  await expect(page.locator(".led-art-lead")).toContainText("Краткое изложение первой новости");
  // Both stored texts are shown: our summary, then the source's own lead-in.
  await expect(page.locator(".led-art-quote")).toContainText("Листинговый комитет допустил");
  // Only the explicit CTA leaves the site, and the stored signal is shown alongside it.
  await expect(page.locator(".led-art-cta")).toHaveAttribute("href", "https://spot.uz/story-one");
  await expect(page.locator(".led-sig").first()).toContainText("высокое влияние");
  await expect(page.locator(".led-sig--rows")).toContainText("Опубликовано");
  // Issuer context: the quote and coverage tone we hold ourselves, not the outlet's text.
  await expect(page.locator(".led-iss-tk")).toContainText("AGBA");
  await expect(page.locator(".led-iss-name")).toContainText("AGBA Bank");
  await expect(page.locator(".led-iss-stats")).toContainText("1 500");
  await expect(page.locator(".led-iss-stats dd.pos").first()).toContainText("+4.2%");
  await expect(page.locator(".led-iss-basis")).toContainText("4");
  // Related stories stay in-app; the back link returns to the feed.
  await page.locator(".led-art-related .led-story").first().click();
  await expect(page).toHaveURL(/\/news\/12$/);
  await expect(page.locator(".led-art-title")).toContainText("ЦБ уточнил требования");
  await page.locator(".led-back").click();
  await expect(page).toHaveURL(/\/news$/);
  await expect(page.locator(".newsdesk-priority-story--lead")).toBeVisible();
});

test("the story page shows what the price did around it, and hedges it (§3.11)", async ({ page }) => {
  await page.goto("/news/11");
  const rx = page.locator(".led-rx");
  await expect(rx).toBeVisible();
  // Both closes carry their date: the pair means nothing without them.
  await expect(rx.locator(".led-rx-leg").first()).toContainText("1 440");
  await expect(rx.locator(".led-rx-leg").nth(1)).toContainText("1 500");
  await expect(rx.locator(".led-rx-chg")).toHaveText("+4.2%");
  await expect(rx.locator(".led-rx-meta")).toContainText("×2.4");
  await expect(rx.locator(".led-rx-meta")).toContainText("+6.3%");
  // A same-day session cannot be attributed to the story, and the note says so —
  // once, under the block, rather than on every row.
  await expect(rx.locator(".led-art-hint")).toContainText("не доказанная реакция");
  await expect(rx.locator(".led-art-hint")).toContainText("того же дня");
});

test("an issuer that has not traded since publication is not shown as a zero (§3.11)", async ({ page }) => {
  await page.route("**/api/news/item/*/reaction", (route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ ok: true, id: 11, items: [{
      ticker: "AGBA", status: "no_session_yet", data_tier: "illiquid",
      before: { date: "2026-07-23", close: 1440 }, after: null,
      change: { value: null, status: "no_data" },
    }] }),
  }));
  await page.goto("/news/11");
  await expect(page.locator(".led-rx-none")).toContainText("торгов по бумаге ещё не было");
  await expect(page.locator(".led-rx-chg")).toHaveCount(0);
});

test("an openinfo filing says the link opens the issuer card, not an article (§3.11)", async ({ page }) => {
  await page.goto("/news/13");
  await expect(page.locator(".led-art-title")).toContainText("Выплаты дивидендов");
  // Not "Читать в источнике": openinfo publishes no page for a single material fact.
  await expect(page.locator(".led-art-cta")).toContainText("Карточка эмитента");
  await expect(page.locator(".led-art-note")).toContainText("не публикует отдельную страницу");
  // The filing's own figures are shown, under a label that does not call them a quote.
  await expect(page.locator(".led-art-quote .led-panel-h")).toContainText("Из раскрытия эмитента");
  await expect(page.locator(".led-art-quote")).toContainText("выплачено 72.38%");
  await expect(page.locator(".led-art-quote")).toContainText("Не выплачено 27.62%");
});

test("a /news/{id} deep link renders the story directly (§3.11)", async ({ page }) => {
  await page.goto("/news/12");
  await expect(page.locator(".led-art-title")).toContainText("ЦБ уточнил требования");
  await expect(page.getByRole("button", { name: "Новости", exact: true })).toHaveClass(/active/);
});

test("an unknown /news/{id} shows a not-found notice, not a blank page (§3.11)", async ({ page }) => {
  await page.goto("/news/999");
  await expect(page.locator(".led-empty")).toContainText("не найдена");
});

test("Рынок shows §3.8 multiplier columns and exports CSV", async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem("uz_market_cols", JSON.stringify(["change", "mktCap", "pe", "pb", "roe"]))
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  await expect(page.locator(".market-table-wrap .market-table thead")).toContainText("P/E");
  await expect(page.locator(".market-table-wrap .market-table thead")).toContainText("P/B");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator(".market-export-btn").click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.csv$/);
});

// The export used to emit a bare exchange-board dump — English headers on a Russian page,
// full-precision floats and a comma delimiter Russian Excel cannot split — which read as
// somebody else's file rather than our report. What makes it ours is the issuer reporting
// beside the quote, so that is what this pins.
test("the market CSV is our report, not a board dump (§3.8)", async ({ page }) => {
  await mockApi(page);
  // Registered after mockApi, so these win: the shared fixtures carry no reporting period
  // and no OHLC, and both are columns under test.
  await page.route("**/api/market/stocks**", (route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ stocks: [{
      ticker: "AGBA", name: "AGBA Bank", isin: "UZ0001", type: "stock", share_type: "ordinary",
      last_price: 1500, close_price: 1440, open: 1450, high: 1520, low: 1430,
      last_trade_date: "29.07.2026", volume: 5e6, quantity: 3333, trade_count: 40,
      market_cap: 3e10,
    }] }),
  }));
  await page.route("**/api/market/financials**", (route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ ok: true, financials: { AGBA: {
      year: 2026, quarter: 1, is_ytd: true, period_months: 3,
      revenue: 9e9, gross_profit: 4e9, operating_income: 3e9, net_income: 2e9,
      cash: 1e9, total_liabilities: 2e10, field_periods: {},
    } } }),
  }));

  await page.goto("/");
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator(".market-export-btn").click(),
  ]);

  const chunks = [];
  for await (const c of await download.createReadStream()) chunks.push(c);
  const buf = Buffer.concat(chunks);
  expect(buf.subarray(0, 3)).toEqual(Buffer.from([0xef, 0xbb, 0xbf]));   // Excel wants the BOM
  const CRLF = String.fromCharCode(13, 10);
  const text = buf.toString("utf8").replace(/^﻿/, "");
  expect(text).toContain(CRLF);
  const lines = text.split(CRLF);

  // It says what it is and where each part came from, instead of starting at row 1 with data.
  expect(lines[0]).toContain("рынок и отчётность эмитентов");
  expect(text).toContain("uzse.uz");
  expect(text).toContain("openinfo.uz");

  const header = lines.find((l) => l.startsWith("Тикер"));
  expect(header).toBeTruthy();
  // Semicolons, because Excel in a ru locale splits on ';' and reads ',' as the decimal mark.
  expect(header.split(";").length).toBeGreaterThan(30);
  for (const col of ["Выручка", "Чистая прибыль", "Общие обязательства", "Отчётный период",
    "Капитализация", "P/E", "Сектор"]) {
    expect(header.split(";")).toContain(col);
  }
  expect(header).not.toContain("Ticker");        // never English on the Russian UI
  expect(header).not.toContain("% объёма, %");   // the label already carries its unit

  const row = lines[lines.indexOf(header) + 1].split(";");
  expect(row[0]).toBe("AGBA");
  expect(row[header.split(";").indexOf("Отчётный период")]).toBe("2026 Q1");
  expect(row[header.split(";").indexOf("Выручка")]).toBe("9000000000");
  // Rounded like the screen and with a decimal comma — not "4.166666666666667".
  expect(row[header.split(";").indexOf("Изм., %")]).toBe("4,17");
});

// The site is served in three languages but every stored summary used to be Russian, so
// the English and Uzbek versions served a Russian feed. The classifier now writes all three
// and the read path ships one headline per language; this pins that each reader gets theirs.
const TRILINGUAL = [
  { id: 91, url: "https://spot.uz/a", source: "Spot.uz", source_id: "spot", lang: "ru",
    title: "ЦБ сохранил ставку на уровне 13,5%", snippet: "Совет ЦБ принял решение.",
    summary_ru: "Центробанк сохранил ставку.", summary_en: "The central bank held its rate.",
    summary_uz: "Markaziy bank stavkani saqlab qoldi.",
    title_ru: null, title_en: "The central bank held its rate.",
    title_uz: "Markaziy bank stavkani saqlab qoldi.",
    translatable: true, image_url: null, published_at: "2026-07-29 09:00:00",
    type: "regulatory", tone: "neutral", tone_score: 0, impact: "high", direction: "unclear",
    sectors: [], relevance_score: 0.8, coverage_weight: 0.9, tickers: [], rank: 0.8 },
];

for (const [lang, expected] of [
  ["ru", "ЦБ сохранил ставку на уровне 13,5%"],
  ["en", "The central bank held its rate."],
  ["uz", "Markaziy bank stavkani saqlab qoldi."],
]) {
  test(`the ${lang} feed reads in ${lang} (§3.11)`, async ({ page }) => {
    await mockApi(page);
    await page.route("**/api/news/feed**", (route) => route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ ok: true, count: 1, items: TRILINGUAL, disclaimer: "d" }),
    }));
    await page.addInitScript((l) => {
      try { localStorage.setItem("uz_stock_analyzer_language", l); } catch { /* ignore */ }
    }, lang);
    await page.goto("/news");
    await expect(page.locator(".newsdesk-priority-story--lead h2")).toHaveText(expected);
    if (lang !== "ru") {
      // The summary is now the headline, so it must not also be printed as the dek…
      await expect(page.locator(".newsdesk-priority-story--lead > p:not(.newsdesk-original)")).toHaveCount(0);
      // …and the publisher's own Russian headline stays on the card as attribution,
      // badged with the language it is in.
      await expect(page.locator(".newsdesk-original")).toContainText("ЦБ сохранил ставку");
      await expect(page.locator(".newsdesk-original span")).toHaveText("ru");
    }
  });
}

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
  // §3.3 4-tier debt-load indicator (Low/Moderate/High/Critical)
  await expect(page.locator(".debt-load-badge")).toContainText("Умеренная");
  // §3.3 EBITDA margin surfaced as a factual metric ring
  await expect(page.locator(".metric-rings-grid")).toContainText("Маржа EBITDA");
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

// The filter bar scrolls with the page: it was pinned under the topbar for a
// while and that is deliberately undone. Only the column headers stay.
test("the filter bar scrolls away, the column headers do not (§3.8)", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  await expect(page.locator(".market-table-wrap .market-table tbody tr").first()).toBeVisible();

  const bar = page.locator(".market-filterbar");
  const topbar = await page.locator("header.topbar").boundingBox();
  await page.mouse.wheel(0, 2000);
  await page.waitForTimeout(400);

  const box = await bar.boundingBox();
  expect(box.y).toBeLessThan(topbar.height - 1);
});

// "Фин. показатели", "Мультипликаторы" and the rest live inside this menu, so a
// menu that scrolls out of reach is a filter that cannot be used.
test("the column picker follows its button while the page scrolls (§3.8)", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  await page.locator(".market-cols-btn").click();

  const menu = page.locator(".market-cols-dropdown");
  const button = page.locator(".market-cols-btn");
  await expect(menu).toContainText("Фин. показатели");

  // A short scroll — enough to move the toolbar, not enough to take its button
  // off screen. The menu has to travel with it rather than stay where it opened.
  await page.mouse.wheel(0, 120);
  await page.waitForTimeout(400);
  const after = await menu.boundingBox();
  const btn = await button.boundingBox();
  expect(Math.abs(after.y - (btn.y + btn.height + 8))).toBeLessThan(3);
  expect(after.y).toBeGreaterThan(0);
  expect(after.y).toBeLessThan(await page.evaluate(() => window.innerHeight));
});

// On a phone the picker is a bottom sheet, and the page behind it is frozen:
// the complaint was that scrolling "gets in the way" of filtering.
test("mobile: the column picker is a sheet and the page behind it holds still (§3.12)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 780 });
  await page.goto("/");
  await page.locator(".topbar-burger").click();
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  await expect(page.locator(".market-table-wrap .market-table tbody tr").first()).toBeVisible();

  await page.mouse.wheel(0, 900);
  await page.waitForTimeout(300);

  await page.locator(".market-cols-btn").click();
  const sheet = page.locator(".market-cols-sheet");
  await expect(sheet).toBeVisible();
  const box = await sheet.boundingBox();
  expect(Math.round(box.y + box.height)).toBe(780); // sits on the bottom edge

  // Measured with the sheet already open: freezing the body clamps the scroll
  // offset once, and what matters is that it does not move after that.
  const scrollBefore = await page.evaluate(() => window.scrollY);
  await page.mouse.wheel(0, 600);
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => window.scrollY)).toBe(scrollBefore);
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");

  await sheet.locator(".market-cols-sheet-close").click();
  await expect(sheet).toHaveCount(0);
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
});

// The badge used to echo the uzse mirror's own stamp — a naive UTC string the
// browser then read as local time, so a Tashkent reader saw 14:00 for data
// five hours younger, and the number could never report our own schedule.
test.describe("the market timestamp", () => {
  test.use({ timezoneId: "Asia/Tashkent" });

  test("reports our own refresh, in the reader's timezone (§3.8)", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Рынок", exact: true }).click();
    const badge = page.locator(".market-hero-panel .status-badge").first();
    // 11:10:04Z is the 16:10 Tashkent quotes run.
    await expect(badge).toContainText("16:10");
    await expect(badge).toContainText("31");
    // The exchange feed's stamp and the session it describes move to the tooltip.
    await expect(badge).toHaveAttribute("title", /Биржевая лента/);
    await expect(badge).toHaveAttribute("title", /Торговая сессия: 31 июл\. 2026/);
  });
});

// Floating sponsor unit. The rules an ad has to keep are the ones worth pinning:
// nothing before the delay, sound never starts on its own, the close control
// always arrives, and a dismissed ad stays dismissed for the session.
test("the sponsor overlay starts muted, becomes closable, and stays closed (§ads)", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".sponsor-overlay")).toHaveCount(0); // not before the delay
  await expect(page.locator(".sponsor-overlay")).toBeVisible({ timeout: 15000 });

  await expect(page.locator(".sponsor-overlay-label")).toHaveText("Реклама");
  expect(await page.locator(".sponsor-overlay video").evaluate((v) => v.muted)).toBe(true);
  // The countdown holds the close control back for a full 15s, then hands it
  // over. Ten seconds in it is still a counter, not an ×.
  await expect(page.locator(".sponsor-overlay-count")).toBeVisible();
  await page.waitForTimeout(10000);
  await expect(page.locator(".sponsor-overlay-close")).toHaveCount(0);
  await expect(page.locator(".sponsor-overlay-close")).toBeVisible({ timeout: 12000 });

  await page.locator(".sponsor-overlay-close").click();
  await expect(page.locator(".sponsor-overlay")).toHaveCount(0);

  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  await page.waitForTimeout(4000);
  await expect(page.locator(".sponsor-overlay")).toHaveCount(0);
});

// Two sessions, and volumes that deliberately disagree with the dates: the heaviest
// row of all sits on the OLDER day, so a volume-only sort heads the table with it and
// a date-only sort cannot separate the two rows that tie.
const SORT_STOCKS = { updated_at: "2026-07-31T14:00:00Z", stocks: [
  { ticker: "AAA", name: "Alpha", isin: "UZ00A", last_price: 100, close_price: 100,
    volume: 1e6, quantity: 10, trade_count: 2, last_trade_date: "31.07.2026" },
  { ticker: "BBB", name: "Beta", isin: "UZ00B", last_price: 100, close_price: 100,
    volume: 5e6, quantity: 50, trade_count: 5, last_trade_date: "31.07.2026" },
  { ticker: "CCC", name: "Gamma", isin: "UZ00C", last_price: 100, close_price: 100,
    volume: 9e6, quantity: 90, trade_count: 9, last_trade_date: "30.07.2026" },
] };

async function sortBoard(page) {
  await page.route("**/api/market/stocks**", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(SORT_STOCKS),
  }));
  await page.goto("/");
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  const tickers = page.locator(".market-table-wrap .market-table tbody .market-ticker-btn");
  await expect(tickers.first()).toBeVisible();
  return {
    tickers,
    dateTh: page.locator('.market-table thead th[data-sort-key="date"]'),
    volTh: page.locator('.market-table thead th[data-sort-key="volume"]'),
    chips: page.locator(".market-sort-chain-chip"),
  };
}

// The board is read with two questions at once — "what traded most recently" and
// "what traded most heavily" — and a single sort key could only ever answer one:
// clicking ОБЪЁМ threw away the date order that put those rows on screen. The chain
// has to hold, and each key may only decide the rows the ones before it tied on.
test("the board sorts on a chain of keys, not just the last one clicked", async ({ page }) => {
  const { tickers, dateTh, volTh, chips } = await sortBoard(page);

  // One key: the newest session leads, and the two rows on it stay in feed order.
  await dateTh.click();
  await expect(tickers).toHaveText(["AAA", "BBB", "CCC"]);
  await expect(chips).toHaveCount(1);

  // Shift-click APPENDS. The date still decides first — CCC's 9 млн does not jump
  // the queue — and volume only breaks the 31.07 tie.
  await volTh.click({ modifiers: ["Shift"] });
  await expect(tickers).toHaveText(["BBB", "AAA", "CCC"]);
  await expect(chips).toHaveCount(2);

  // Second shift-click on the same header flips that key alone.
  await volTh.click({ modifiers: ["Shift"] });
  await expect(tickers).toHaveText(["AAA", "BBB", "CCC"]);
  await expect(chips).toHaveCount(2);

  // Third drops it back out of the chain, leaving the date behind it intact.
  await volTh.click({ modifiers: ["Shift"] });
  await expect(chips).toHaveCount(1);
  await expect(tickers).toHaveText(["AAA", "BBB", "CCC"]);

  // A plain click still collapses to one key — the old behaviour, unbroken.
  await volTh.click({ modifiers: ["Shift"] });
  await expect(chips).toHaveCount(2);
  await volTh.click();
  await expect(chips).toHaveCount(1);
  await expect(tickers).toHaveText(["CCC", "BBB", "AAA"]);

  // And there is a way back to the board's own order, which a sorted header alone
  // never offered: before this, the default could not be restored at all.
  await page.locator(".market-sort-chain-reset").click();
  await expect(page.locator(".market-sort-chain")).toHaveCount(0);
  await expect(tickers).toHaveText(["AAA", "BBB", "CCC"]);
});

// A modifier nobody is told about is a feature nobody has: shift-click is invisible,
// and the chain row that would demonstrate it only exists once you have already done
// it. So the hint has to arrive on the FIRST sort — and then get out of the way.
test("the board teaches the multi-sort modifier once, then stops", async ({ page }) => {
  const { dateTh, volTh } = await sortBoard(page);
  const teach = page.locator(".market-sort-teach");

  // Not on a cold board — there is nothing to add a second key to yet.
  await expect(teach).toHaveCount(0);

  await dateTh.click();
  await expect(teach).toBeVisible();
  await expect(teach).toContainText("Shift");

  // Using it retires it: a reader who has built a two-key order has been taught.
  await volTh.click({ modifiers: ["Shift"] });
  await expect(teach).toHaveCount(0);

  // And it stays retired across a reload — the lesson is not repeated every visit.
  await page.reload();
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  await page.locator('.market-table thead th[data-sort-key="date"]').click();
  await expect(page.locator(".market-sort-chain-chip")).toHaveCount(1);
  await expect(teach).toHaveCount(0);
});

// Dismissing is the other way to be done with it, and it must stick just as hard.
test("dismissing the multi-sort hint keeps it dismissed", async ({ page }) => {
  const { dateTh } = await sortBoard(page);
  await dateTh.click();
  await expect(page.locator(".market-sort-teach")).toBeVisible();
  await page.locator(".market-sort-teach-close").click();
  await expect(page.locator(".market-sort-teach")).toHaveCount(0);
  // The chain row itself stays — it is the way back to the default order.
  await expect(page.locator(".market-sort-chain-chip")).toHaveCount(1);

  await page.reload();
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  await page.locator('.market-table thead th[data-sort-key="date"]').click();
  await expect(page.locator(".market-sort-chain-chip")).toHaveCount(1);
  await expect(page.locator(".market-sort-teach")).toHaveCount(0);
});

// A bond section that printed one issue's April session beside another's this
// morning. The quote feed and the day statistics are two feeds describing two
// days: IQMK5B8 sat at its 3 April price with April turnover — 101,92 млрд —
// while the statistics held its trade of that very morning at 124,53 млрд, and
// «Сделки» was empty for 15 of 17 because the feed carries no trade count for a
// bond at all. The server reconciles them now; this pins what the reader sees.
const ref = (nominal, coupon) => ({
  is_complete: false, missing: ["maturity_date"], has_nominal: !!nominal, has_coupon: !!coupon,
  nominal, coupon_rate: coupon, coupon_freq: 12, maturity_date: null, issue_volume: 400000,
});
const ok = (v) => ({ value: v, status: "ok" });
const no = (note) => ({ value: null, status: "no_bond_reference", note });

const BONDS = {
  ok: true, count: 4, board_day: "2026-08-11", traded_today: 2, stale: 2,
  issue_value_total: 2153364985020, day_count_basis: "ACT/365",
  with_reference: 0, with_nominal: 3, with_coupon: 3, trade_date: "2026-08-11",
  items: [
    { ticker: "ACMT1B3", issuer: "\"AGAT CREDIT\" Aksiyadorlik jamiyati mikromoliya tashkiloti",
      price: 104999.99, change_pct: -1.5, turnover: 4718157.99, trades: 17, issue_value: 42e9,
      last_trade_date: "2026-08-11", is_current: true, status: "ok",
      quality: { data_tier: "full" }, reference: ref(100000, 27),
      price_pct: ok(105), simple_yield: ok(25.71), ytm: no("нет справочных данных по выпуску") },
    { ticker: "IQMK5B8", issuer: "<O'zbekiston ipotekani qayta moliyalashtirish kompaniyasi> AJ",
      price: 1037753.42, change_pct: 1.82, turnover: 124530410400, trades: 1, issue_value: 305.75e9,
      last_trade_date: "2026-08-11", is_current: true, status: "ok",
      quality: { data_tier: "illiquid" }, reference: ref(null, null),
      price_pct: no("нет номинала"), simple_yield: no("нет купона"), ytm: no("нет справочных данных по выпуску") },
    { ticker: "UZUMN2B2", issuer: "<MAKESENSE> mas'uliyati cheklangan jamiyati",
      price: 100460273.98, change_pct: 0.2, turnover: 301380821.94, trades: 1, issue_value: 401.84e9,
      last_trade_date: "2026-08-07", is_current: false, status: "ok",
      quality: { data_tier: "illiquid" }, reference: ref(100000000, 24),
      price_pct: ok(100.46), simple_yield: ok(23.89), ytm: no("нет справочных данных по выпуску") },
    { ticker: "ACMT1B2", issuer: "\"AGAT CREDIT\" Aksiyadorlik jamiyati mikromoliya tashkiloti",
      price: 100000.01, change_pct: -0.5, turnover: 4300000.36, trades: 7, issue_value: null,
      last_trade_date: "2026-07-17", is_current: false, status: "matured",
      reason: "выпуск погашается с 2026-07-23",
      quality: { data_tier: "full" },
      reference: { ...ref(100000, 28), is_complete: true, missing: [], maturity_date: "2026-07-23" },
      price_pct: ok(100), simple_yield: ok(28),
      ytm: { value: null, status: "matured", note: "выпуск погашен 2026-07-23" } },
  ],
};

test("the bonds table says which session each row is from", async ({ page }) => {
  await page.route("**/api/bonds", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(BONDS),
  }));
  await page.goto("/");
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  await page.getByRole("button", { name: "Облигации", exact: true }).click();
  await expect(page.locator(".bonds-table tbody tr").first()).toBeVisible();

  // The section names the session it is read against, and how much of it is that session.
  await expect(page.locator(".bonds-head")).toContainText("сессия: 2026-08-11");
  await expect(page.locator(".bonds-head")).toContainText("2 сегодня");

  // Every row carries its own day, and the two that are not today's are marked.
  const session = page.locator(".bonds-table tbody .bond-session");
  await expect(session).toHaveText(["2026-08-11", "2026-08-11", "2026-08-07", "2026-07-17"]);
  await expect(page.locator(".bonds-table tbody .bond-stale")).toHaveCount(2);

  // The redeemed issue blames its redemption, never a missing reference.
  const acmt = page.locator(".bonds-table tbody tr", { hasText: "ACMT1B2" });
  await expect(acmt.locator(".cell-status", { hasText: "в погашении" })).toBeVisible();
});

// A chip row of «Все» + one sector is not a filter — both buttons select the same
// securities. That is exactly the bonds segment, where the catalog carries no sector
// for an issue and every one of them answers to «Прочее»; the customer had that chip
// off. Under Акции the same «Прочее» holds the issuers the catalog has not classified
// yet, so there it stays and the rows keep a chip to answer to.
const SECTOR_SHARES = { updated_at: "2026-08-11T14:00:00Z", stocks: [
  { ticker: "AGBA", name: "AGBA Bank", isin: "UZ0001", last_price: 1500, close_price: 1250,
    volume: 1.2e9, quantity: 100, trade_count: 40, nominal: 1000, last_trade_date: "11.08.2026" },
  { ticker: "KVTS", name: "Kvarts", isin: "UZ0003", last_price: 320, close_price: 300,
    volume: 4e8, quantity: 100, trade_count: 12, nominal: 100, last_trade_date: "11.08.2026" },
  { ticker: "NOCL", name: "Unclassified", isin: "UZ0009", last_price: 100, close_price: 90,
    volume: 1e7, quantity: 10, trade_count: 2, nominal: 100, last_trade_date: "11.08.2026" },
] };
const SECTOR_BONDS = { updated_at: "2026-08-11T14:00:00Z", stocks: [
  { ticker: "BFMT2B5", name: "Biznes Finans", isin: "UZ00B1", last_price: 1000, close_price: 1000,
    volume: 5e7, quantity: 50, trade_count: 3, nominal: 1000, last_trade_date: "11.08.2026", type: "bond" },
] };
const SECTOR_SECURITIES = { ok: true, securities: {
  AGBA: { name: "AGBA Bank", type: "stock", sector: "finance" },
  KVTS: { name: "Kvarts", type: "stock", sector: "manufacturing" },
  NOCL: { name: "Unclassified", type: "stock" },          // no sector: «Прочее»
  BFMT2B5: { name: "Biznes Finans", type: "bond" },
} };

test("the sector row is drawn only where it can actually choose", async ({ page }) => {
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const j = (b) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(b) });
    if (url.pathname === "/api/market/stocks") {
      return j(url.searchParams.get("type") === "bond" ? SECTOR_BONDS : SECTOR_SHARES);
    }
    if (url.pathname === "/api/securities") return j(SECTOR_SECURITIES);
    if (url.pathname === "/api/bonds") return j({ ok: true, count: 1, items: [
      { ticker: "BFMT2B5", name: "Biznes Finans", isin: "UZ00B1", price: 1000, nominal: 1000 },
    ] });
    return route.fallback();
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Рынок", exact: true }).click();

  const chips = page.locator(".market-sector-filter .sector-chip");
  await expect(chips).toHaveText(["Все", "Финансы", "Производство", "Прочее"]);

  const tickers = page.locator(".market-table tbody .market-ticker-btn");
  await page.getByRole("button", { name: "Финансы", exact: true }).click();
  await expect(tickers).toHaveText(["AGBA"]);

  // Bonds: one sector between them, so no row — and the choice made on the shares
  // side must not be left applying invisibly, with no control left to undo it.
  await page.getByRole("button", { name: "Облигации", exact: true }).click();
  await expect(page.locator(".bonds-table tbody tr")).toHaveCount(1);
  await expect(page.locator(".market-sector-filter")).toHaveCount(0);

  // It is suspended, not thrown away.
  await page.getByRole("button", { name: "Акции", exact: true }).click();
  await expect(tickers).toHaveText(["AGBA"]);
});

// The strip above the board reads one session three ways. The two percent lists say
// who moved; «Топ ликвидности» says who was actually tradeable — the question they
// cannot answer, since a +20 % struck on one thin trade leads them either way. Its
// number is the same «Объём» (turnover in money) the column and the turnover card use.
const MOVERS_STOCKS = { updated_at: "2026-08-11T14:00:00Z", stocks: [
  // Heaviest turnover of the day AND the biggest move.
  { ticker: "AAA", name: "Alpha", isin: "UZ00A", last_price: 120, close_price: 100,
    volume: 1.2e9, quantity: 1000, trade_count: 40, last_trade_date: "11.08.2026" },
  // Traded heavily and closed flat: in NEITHER percent list, second by turnover.
  // This row is the reason the third panel exists.
  { ticker: "QQQ", name: "Quiet", isin: "UZ00Q", last_price: 100, close_price: 100,
    volume: 9e8, quantity: 9000, trade_count: 60, last_trade_date: "11.08.2026" },
  { ticker: "BBB", name: "Beta", isin: "UZ00B", last_price: 86, close_price: 100,
    volume: 8e8, quantity: 800, trade_count: 30, last_trade_date: "11.08.2026" },
  { ticker: "CCC", name: "Gamma", isin: "UZ00C", last_price: 105, close_price: 100,
    volume: 3e8, quantity: 300, trade_count: 12, last_trade_date: "11.08.2026" },
  { ticker: "DDD", name: "Delta", isin: "UZ00D", last_price: 97, close_price: 100,
    volume: 5e7, quantity: 50, trade_count: 4, last_trade_date: "11.08.2026" },
  // A move with no turnover figure behind it: the day statistics never matched this
  // row's session. It is a mover, and it is NOT a liquidity entry — an absent
  // turnover must not sort as a zero that says the security traded for nothing.
  { ticker: "EEE", name: "Epsilon", isin: "UZ00E", last_price: 102, close_price: 100,
    volume: null, quantity: null, trade_count: null, last_trade_date: "11.08.2026" },
] };

test("the movers strip says who moved AND what was tradeable", async ({ page }) => {
  await page.route("**/api/market/stocks**", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(MOVERS_STOCKS),
  }));
  await page.goto("/");
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  await expect(page.locator(".market-movers-col")).toHaveCount(3);

  const names = (col) => page.locator(`.market-movers-col.${col} .market-movers-name`);
  // EEE is a mover like any other — a missing turnover figure hides it from the
  // liquidity list below, never from the move it actually made.
  await expect(names("up")).toHaveText(["AAA", "CCC", "EEE"]);
  await expect(names("down")).toHaveText(["BBB", "DDD"]);

  // Ordered by turnover, and it is turnover that is printed — not a percent.
  await expect(names("vol")).toHaveText(["AAA", "QQQ", "BBB", "CCC", "DDD"]);
  await expect(page.locator(".market-movers-col.vol .market-movers-chg").first())
    .toHaveText("1,2B");

  // The flat security is here and nowhere else; the one with no figure is nowhere.
  await expect(names("vol")).toContainText(["QQQ"]);
  await expect(names("up")).not.toContainText(["QQQ"]);
  await expect(names("vol")).not.toContainText(["EEE"]);
  await expect(names("up")).toContainText(["CCC"]);
});

// A phone has no Shift key and the board stays a table there, so the gesture has to
// change and the hint has to name the one that device actually has. Touch emulation
// is what makes `(pointer: coarse)` true — the wording is chosen off that query.
test.describe("mobile multi-sort", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("long-press appends a sort key, and the hint says so (§3.12)", async ({ page }) => {
    await page.route("**/api/market/stocks**", (route) => route.fulfill({
      status: 200, contentType: "application/json", body: JSON.stringify(SORT_STOCKS),
    }));
    await page.goto("/");
    await page.locator(".topbar-burger").tap();
    await page.getByRole("button", { name: "Рынок", exact: true }).tap();
    const tickers = page.locator(".market-table-wrap .market-table tbody .market-ticker-btn");
    await expect(tickers.first()).toBeVisible();

    const dateTh = page.locator('.market-table thead th[data-sort-key="date"]');
    await dateTh.scrollIntoViewIfNeeded();
    await dateTh.tap();
    await expect(tickers).toHaveText(["AAA", "BBB", "CCC"]);
    // The hint must not tell a phone to press a key it does not have.
    await expect(page.locator(".market-sort-teach")).toContainText("удерживайте");

    // Hold past the 500ms threshold, then release: the touch equivalent of Shift.
    const volTh = page.locator('.market-table thead th[data-sort-key="volume"]');
    await volTh.scrollIntoViewIfNeeded();
    await volTh.dispatchEvent("touchstart");
    await page.waitForTimeout(700);
    await volTh.dispatchEvent("touchend");
    await expect(page.locator(".market-sort-chain-chip")).toHaveCount(2);
    await expect(tickers).toHaveText(["BBB", "AAA", "CCC"]);

    // A short tap must still REPLACE, or the chain would grow on every touch.
    // Aimed away from the header's own ℹ marker, which deliberately swallows
    // the tap so that asking what a column means never reorders the board.
    await volTh.tap({ position: { x: 6, y: 6 } });
    await expect(page.locator(".market-sort-chain-chip")).toHaveCount(1);
    await expect(tickers).toHaveText(["CCC", "BBB", "AAA"]);
  });
});

// Every economic label carries its own definition (ТЗ §3.2). The glossary page was
// deleted; these markers are where the terms live now, so they have to actually
// answer — and they must not fire the sort or the drag on the header underneath.
test("a column header explains its own term without sorting the board", async ({ page }) => {
  await page.route("**/api/market/stocks**", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(SORT_STOCKS),
  }));
  await page.goto("/");
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  const tickers = page.locator(".market-table-wrap .market-table tbody .market-ticker-btn");
  await expect(tickers.first()).toBeVisible();

  const volTh = page.locator('.market-table thead th[data-sort-key="volume"]');
  const marker = volTh.locator(".term-info-btn");
  await expect(marker).toBeVisible();

  // Hover opens it, and it says what OUR column counts — turnover in soum, not
  // a share count — which is the whole reason the definition is worth carrying.
  await marker.hover();
  const tip = page.locator(".term-tooltip");
  await expect(tip).toBeVisible();
  await expect(tip).toContainText("Оборот");
  await expect(tip).toContainText("не количество бумаг");

  // The header underneath is a sort control and a drag handle. Asking what the
  // column means must do neither: no chip appeared, so nothing sorted.
  await expect(page.locator(".market-sort-chain")).toHaveCount(0);
  await marker.click();
  await expect(page.locator(".market-sort-chain")).toHaveCount(0);

  // Clicking the header proper still sorts, so the marker stole nothing.
  await volTh.click();
  await expect(page.locator(".market-sort-chain-chip")).toHaveCount(1);
});

// A column that is not an economic term must not sprout a marker promising an
// explanation there is none of.
test("only economic columns carry a term marker", async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem("uz_market_cols", JSON.stringify(["volume", "source", "pe"]))
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Рынок", exact: true }).click();
  await expect(page.locator(".market-table-wrap .market-table tbody tr").first()).toBeVisible();
  await expect(page.locator('th[data-sort-key="volume"] .term-info-btn')).toHaveCount(1);
  await expect(page.locator('th[data-sort-key="pe"] .term-info-btn')).toHaveCount(1);
  // «UZSE» is a link to the exchange and «Компания» is a name — neither is a term.
  await expect(page.locator('th[data-sort-key="source"] .term-info-btn')).toHaveCount(0);
  await expect(page.locator('th[data-sort-key="company"] .term-info-btn')).toHaveCount(0);
});

// The definitions follow the site's language — the glossary they replaced was
// Russian only, so an English reader met Russian text on an English page.
test("term definitions follow the interface language", async ({ page }) => {
  await page.goto("/");
  await page.locator("#languageSelect").selectOption("en");
  await page.getByRole("button", { name: "Market", exact: true }).click();
  await expect(page.locator(".market-table-wrap .market-table tbody tr").first()).toBeVisible();
  await page.locator('th[data-sort-key="volume"] .term-info-btn').hover();
  await expect(page.locator(".term-tooltip")).toContainText("turnover in soum");
});
