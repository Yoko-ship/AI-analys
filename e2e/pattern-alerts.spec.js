// Pattern alerts: a figure completed on a watchlist company arrives in the
// bell under its own name and opens that company; the notification settings
// offer the pattern types, with chart figures ticked by default.
import { test, expect } from "@playwright/test";

const user = { id: 99, full_name: "E2E Investor", email: "e2e@test.uz", created_at: "2026-07-01T10:00:00Z",
  avatar_data_url: null, pro_access: true };
const profile = { ok: true, user, stats: { total_analyses: 0 }, security: { email_verified: true }, notes: [],
  preferences: { language: "ru", theme: "dark", text_scale: 100, notify_patterns: true, pattern_alert_types: [] },
  favorites: [{ ticker: "HMKB", company_name: "Hamkorbank", position: 0, pattern_alert_enabled: true }],
  recent_analyses: [] };
const today = new Date().toISOString().slice(0, 10);

async function mockApi(page, saved) {
  await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_token", "e2e-token"));
  await page.route("**/api/**", (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const send = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/auth/me") return send({ user });
    if (path === "/api/profile") return send(profile);
    if (path === "/api/profile/preferences" && req.method() !== "GET") {
      saved.push(JSON.parse(req.postData() || "{}"));
      return send({ ok: true, preferences: { ...profile.preferences, ...saved.at(-1) } });
    }
    if (path === "/api/notifications") return send({ ok: true, count: 1, total: 1, items: [
      { id: "p1", read: false, kind: "pattern", ticker: "HMKB", pattern: "double_top", direction: "bearish",
        signal_date: today, detected_at: today, report_form: "PATTERN", year: null, quarter: 0, href: "/company/HMKB" },
    ] });
    if (path === "/api/securities") return send({ ok: true, securities: { HMKB: { name: "Hamkorbank", security_type: "stock" } } });
    if (path === "/api/market/stocks") return send({ stocks: [] });
    return send({ ok: true });
  });
}

test("a pattern alert names the figure and opens the company", async ({ page }) => {
  await mockApi(page, []);
  await page.goto("/market");
  await page.locator(".notif-bell").click();
  const item = page.locator(".notif-item").first();
  await expect(item).toContainText("HMKB · Двойная вершина");
  await expect(item).toContainText("фигура завершилась на графике");
  await item.locator(".notif-item-main").click();
  await expect(page).toHaveURL(/\/company\/HMKB/);
});

test("notification settings offer the pattern types, chart figures ticked by default", async ({ page }) => {
  const saved = [];
  await mockApi(page, saved);
  await page.goto("/profile");
  await page.getByRole("button", { name: /Уведомления/ }).first().click();
  const picker = page.getByTestId("pattern-alert-types");
  await expect(picker).toBeVisible();
  await expect(picker.getByLabel("Двойная вершина")).toBeChecked();
  await expect(picker.getByLabel("Молот")).not.toBeChecked();
  await picker.getByLabel("Молот").check();
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect.poll(() => saved.length).toBeGreaterThan(0);
  const types = saved.at(-1).pattern_alert_types;
  expect(types).toContain("hammer");
  expect(types).toContain("double_top");
});
