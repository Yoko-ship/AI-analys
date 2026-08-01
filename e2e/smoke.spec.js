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
  { id: 11, url: "https://kursiv.uz/story-one", source: "Kursiv", source_id: "kursiv", lang: "ru",
    title: "Биржа расширяет листинг банков",
    snippet: "Листинговый комитет допустил к торгам четыре выпуска акций.",
    summary_ru: "Краткое изложение первой новости.",
    image_url: null, published_at: "2026-07-24 09:00:00", type: "market", tone: "positive", tone_score: 0.42,
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

test("Новости renders the editorial feed (§3.11)", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Новости", exact: true }).click();
  await expect(page.locator(".led-head")).toContainText("Новости рынка");
  await expect(page.locator(".led-lead")).toContainText("Биржа расширяет листинг банков");
  await expect(page.locator(".led-stack .led-story").first()).toContainText("ЦБ уточнил требования");
  await expect(page.locator(".led-latest")).toBeVisible();
});

test("a story opens on its own /news/{id} page instead of the source site (§3.11)", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Новости", exact: true }).click();
  // The card is a real link to our own route, not to the outlet.
  await expect(page.locator(".led-lead")).toHaveAttribute("href", "/news/11");
  await page.locator(".led-lead").click();
  await expect(page).toHaveURL(/\/news\/11$/);
  await expect(page.locator(".led-art-title")).toContainText("Биржа расширяет листинг банков");
  await expect(page.locator(".led-art-lead")).toContainText("Краткое изложение первой новости");
  // Both stored texts are shown: our summary, then the source's own lead-in.
  await expect(page.locator(".led-art-quote")).toContainText("Листинговый комитет допустил");
  // Only the explicit CTA leaves the site, and the stored signal is shown alongside it.
  await expect(page.locator(".led-art-cta")).toHaveAttribute("href", "https://kursiv.uz/story-one");
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
  await expect(page.locator(".led-lead")).toBeVisible();
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
  { id: 91, url: "https://kursiv.uz/a", source: "Kursiv", source_id: "kursiv", lang: "ru",
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
    await expect(page.locator(".led-lead-title")).toHaveText(expected);
    if (lang !== "ru") {
      // The summary is now the headline, so it must not also be printed as the dek…
      await expect(page.locator(".led-dek:not(.led-orig)")).toHaveCount(0);
      // …and the publisher's own Russian headline stays on the card as attribution,
      // badged with the language it is in.
      await expect(page.locator(".led-orig")).toContainText("ЦБ сохранил ставку");
      await expect(page.locator(".led-orig .led-lang")).toHaveText("ru");
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
