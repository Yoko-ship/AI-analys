import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const REPORT = JSON.parse(readFileSync(new URL("../tests/fixtures/sector_ui_report.json", import.meta.url), "utf8"));
const SEC = { ticker: "UZMK", name: "Узметкомбинат", type: "stock", isin: "QA-UZMK", last_price: 4000, sector: "manufacturing" };

async function api(page, report = REPORT, admin = false) {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path.endsWith("/ai-report")) return json(report);
    if (path === "/api/securities") return json({ ok: true, securities: { UZMK: SEC } });
    if (path.endsWith("/info")) return json({ ok: true, security: SEC });
    if (path === "/api/companies") return json({ companies: [{ ticker: "UZMK", company_name: SEC.name }] });
    if (path === "/api/market/stocks") return json({ stocks: [SEC] });
    if (path === "/api/market/financials") return json({ ok: true, financials: {} });
    if (path === "/api/market/ratios") return json({ ok: true, ratios: {} });
    if (path === "/api/auth/me") return admin ? json({ user: { id: 1, email: "qa@example.org", is_admin: true } }) : json({ user: null }, 401);
    if (path === "/api/notifications") return json({ count: 0, notifications: [] });
    if (path === "/api/admin/sector-analysis") return json({
      ok: true, role: "administrator", capabilities: ["read", "retry", "activate", "rollback"], counts: { available: 1 }, regression: { status: "passed", checks: [{ code: "P1", status: "passed" }] },
      runs: [{ version: REPORT.version, ticker: "UZMK", language: "ru", standard: "nsbu", period: REPORT.period, status: "available" }],
      jobs: [], audit: [], overrides: [],
    });
    if (path === "/api/admin/sector-analysis/runs/" + REPORT.version) return json(REPORT);
    return json({ ok: true, items: [], points: [], series: {}, reports: [], periods: [], rules: [], findings: [], users: [] });
  });
}

test("sector report opens from the company card and exposes sourced formulas", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await api(page);
  await page.goto("/company/UZMK");
  const details = page.getByTestId("company-insight-card").getByRole("button", { name: "Подробнее" });
  await expect(page.getByTestId("company-insight-card")).toContainText("-8.90%");
  await details.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByTestId("verified-report")).toBeVisible();
  await dialog.getByText("Проверенные формулы НСБУ", { exact: true }).click();
  await expect(dialog.getByText("quick_ratio: 1,02", { exact: true })).toBeVisible();
  await dialog.getByText("Финансовый результат", { exact: true }).click();
  await expect(dialog.locator("table").first()).toContainText("315");
  await expect(dialog.getByRole("link", { name: "form2:c270" })).toHaveAttribute("href", REPORT.sources[0].url);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(details).toBeFocused();
  expect(errors).toEqual([]);
});

test("blocked reports keep a dated prior report and never open empty details", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await api(page, { ...REPORT, status: "quality_blocked", headline: "Анализ временно недоступен: данные не прошли сверку.",
    data_quality: [{ code: "BALANCE_IDENTITY_FAILED", message: "Баланс не сходится" }],
    availability: { last_source_period: "2026Q2", next_action: "Повтор после обновления источника" },
    last_successful_report: { period: "2026Q1", paragraphs: ["Проверенный отчёт за I квартал 2026 года."] },
  });
  await page.goto("/company/UZMK");
  const card = page.getByTestId("company-insight-card");
  await expect(card).toContainText("BALANCE_IDENTITY_FAILED");
  await expect(card.getByRole("button", { name: "Подробнее" })).toHaveCount(0);
  await card.getByText(/Последний проверенный анализ/).click();
  await expect(card).toContainText("Проверенный отчёт за I квартал");
  const width = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
  expect(width.scroll).toBeLessThanOrEqual(width.client);
});

test("a source error can be retried successfully", async ({ page }) => {
  await api(page);
  let attempts = 0;
  await page.route("**/api/v1/issuers/*/ai-report**", (route) => route.fulfill({
    status: ++attempts === 1 ? 503 : 200, contentType: "application/json",
    body: JSON.stringify(attempts === 1 ? { detail: "Temporary source failure" } : REPORT),
  }));
  await page.goto("/company/UZMK");
  const card = page.getByTestId("company-insight-card");
  await card.getByRole("button", { name: "Повторить" }).click();
  await expect(card.getByRole("button", { name: "Подробнее" })).toBeVisible();
  expect(attempts).toBe(2);
});

test("admin rules require evidence and a reason, then send a scoped update", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_token", "local-qa-token"));
  await api(page, REPORT, true);
  let mutation;
  await page.route("**/api/admin/sector-analysis/overrides", (route) => {
    mutation = route.request().postDataJSON();
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, version: "qa-only" }) });
  });
  await page.goto("/admin/analysis");
  await expect(page.getByText("Мониторинг отраслевого анализа")).toBeVisible();
  await page.getByText("Правила выбора шаблона", { exact: true }).click();
  await page.getByLabel("Тикер", { exact: true }).fill("UZMK");
  await page.getByLabel("Шаблон", { exact: true }).selectOption("metallurgy");
  await page.getByLabel("Источник решения", { exact: true }).fill("https://example.org/verified-activity");
  await page.getByLabel("Причина", { exact: true }).fill("Source confirms principal activity");
  await page.getByRole("button", { name: "Сохранить версию и пересчитать эмитента" }).click();
  await expect.poll(() => mutation?.ticker).toBe("UZMK");
  expect(mutation.override_template).toBe("metallurgy");
  expect(mutation.evidence_source).toBe("https://example.org/verified-activity");
  await expect(page.getByRole("status")).toContainText("Изменение сохранено");
  await page.screenshot({ path: "audit/sector-v2.2/admin-rules.png", fullPage: true });
});

test("verified financial tables stay inside the mobile dark report", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_theme", "dark"));
  await api(page);
  await page.goto("/company/UZMK");
  await page.getByTestId("company-insight-card").getByRole("button", { name: "Подробнее" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByText("Финансовый результат", { exact: true }).click();
  await dialog.getByRole("region", { name: "Финансовый результат", exact: true }).scrollIntoViewIfNeeded();
  const geometry = await dialog.evaluate((node) => {
    const box = node.getBoundingClientRect();
    return { left: box.left, right: box.right, width: innerWidth, page: document.documentElement.scrollWidth };
  });
  expect(geometry.left).toBeGreaterThanOrEqual(0);
  expect(geometry.right).toBeLessThanOrEqual(geometry.width);
  expect(geometry.page).toBeLessThanOrEqual(geometry.width);
  await page.screenshot({ path: "audit/sector-v2.2/report-mobile-dark.png" });
  const close = dialog.getByRole("button", { name: "Закрыть" });
  await expect(close).toBeInViewport();
  await close.click();
  await expect(dialog).toHaveCount(0);
});

test("a viewer can inspect analysis but has no mutation controls", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_token", "local-viewer-token"));
  await api(page, REPORT, true);
  await page.route("**/api/auth/me", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ user: { id: 2, email: "viewer@example.org", is_admin: false } }) }));
  await page.route("**/api/admin/sector-analysis", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, role: "viewer", capabilities: ["read"], counts: {}, runs: [], jobs: [], audit: [], overrides: [] }) }));
  await page.goto("/admin/sector-analysis");
  await expect(page.getByText("Мониторинг отраслевого анализа")).toBeVisible();
  await expect(page.getByText("Запусков пока нет.")).toBeVisible();
  await expect(page.getByText("Правила выбора шаблона", { exact: true })).toHaveCount(0);
});

test("a bond opens its shared issuer report without borrowing the share verdict", async ({ page }) => {
  await api(page);
  await page.route("**/api/bonds/EX1B", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({
    ok: true, ticker: "EX1B", isin: "QA-BOND", issuer: "Узметкомбинат", state: "live",
    reference: { nominal: 1000, currency: "UZS" }, price: 1000, schedule: {}, coupons: [],
    freshness: { status: "very_stale" }, quote_as_of: "2026-05-01", days_since_trade: 121,
    issuer_report: { ...REPORT, instrument: undefined, market_as_of: null },
    issuer_id: REPORT.issuer.id, issuer_analysis_id: REPORT.financial_snapshot_id,
    financial_as_of: REPORT.financial_as_of, instrument_verdict: "insufficient_data",
  }) }));
  await page.goto("/bond/EX1B");
  await expect(page.getByText(/Цена устарела; текущего рыночного вердикта нет/)).toBeVisible();
  await page.getByText(/Финансовый профиль эмитента ·/).click();
  await expect(page.getByTestId("verified-report")).toBeVisible();
  await expect(page.getByTestId("verified-report")).toContainText("2026-06-30");
  await page.screenshot({ path: "audit/sector-v2.2/bond-issuer-report.png" });
});
