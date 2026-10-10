// The news section's category tabs (customer, 2026-10-08): one compact row, the
// active tab highlighted, each tab asking the feed for its own category.
// Since 2026-10-10 the row holds five headings; the narrower sections fold into
// an «Ещё» menu, and the menu button wears the open section's name.
import { test, expect } from "@playwright/test";

const item = (id, category, title) => ({
  id, url: `https://example.test/${id}`, source: "Spot", source_id: "spot", lang: "ru", title,
  title_ru: title, summary_ru: title, published_at: "2026-10-08", type: "market", tone: "neutral",
  tone_score: 0, impact: "low", direction: "unclear", sectors: [], tickers: [], category, rank: 0.5,
});

async function openNews(page, path = "/news", { admin = false } = {}) {
  const asked = [];
  page.on("pageerror", (e) => { throw e; });
  await page.addInitScript(() => sessionStorage.setItem("uz_sponsor_seen", "1"));
  if (admin) await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_token", "admin-token"));
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === "/api/news/feed") {
      const category = url.searchParams.get("category");
      asked.push(category);
      const items = category ? [item(1, category, `Новость раздела ${category}`)] : [item(1, "economy", "Экономика"), item(2, "markets", "Рынки")];
      return json({ ok: true, count: items.length, items });
    }
    if (url.pathname === "/api/auth/me") {
      return admin ? json({ user: { id: 1, email: "admin@example.com", full_name: "Admin", is_admin: true } }) : json({ user: null }, 401);
    }
    return json({ ok: true, items: [] });
  });
  await page.goto(path);
  return asked;
}

test("every category is a tab that asks the feed for its own stories", async ({ page }) => {
  const asked = await openNews(page);
  const tabs = page.locator(".newsdesk-tabs .newsdesk-tab");
  const more = page.locator(".newsdesk-tab-more");
  await expect(tabs).toHaveText(["Все", "Экономика", "Рынки", "Корпоративные", "Календарь", "Ещё"]);
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Все");
  for (const [label, key, category] of [["Экономика", "economy", "economy"], ["Рынки", "markets", "markets"]]) {
    await tabs.filter({ hasText: label }).click();
    await expect(page.locator(".newsdesk-tab.active")).toHaveText(label);
    await expect(page).toHaveURL(new RegExp(`tab=${key}$`));
    await expect.poll(() => asked.at(-1)).toBe(category);
  }
  // The folded sections: each one is a menu item, and once chosen the menu
  // button carries its name as the active tab.
  for (const [label, key, category] of [["Финотчётность", "reporting", "reports"], ["Компании", "companies", "companies"],
    ["Политика", "politics", "politics"], ["Технологии", "technology", "technology"], ["Прочее", "other", "other"]]) {
    await more.click();
    const menu = page.locator(".newsdesk-more-menu");
    await expect(menu.getByRole("menuitem")).toHaveText(["Финотчётность", "Компании", "Политика", "Технологии", "Прочее"]);
    await menu.getByRole("menuitem", { name: label }).click();
    await expect(menu).toHaveCount(0);
    await expect(page.locator(".newsdesk-tab.active")).toHaveText(label);
    await expect(more).toHaveText(label);
    await expect(page).toHaveURL(new RegExp(`tab=${key}$`));
    await expect.poll(() => asked.at(-1)).toBe(category);
  }
  // The active tab is filled, the others are not.
  const fill = (loc) => loc.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(await fill(page.locator(".newsdesk-tab.active"))).not.toBe(await fill(tabs.first()));
  // Back on a bar tab, the button goes back to «Ещё».
  await tabs.filter({ hasText: "Все" }).click();
  await expect(more).toHaveText("Ещё");
});

test("the «Ещё» menu closes on Escape and on a click outside", async ({ page }) => {
  await openNews(page);
  const more = page.locator(".newsdesk-tab-more");
  const menu = page.locator(".newsdesk-more-menu");
  await more.click();
  await expect(more).toHaveAttribute("aria-expanded", "true");
  await page.screenshot({ path: "test-results/news-more-menu.png" });
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(more).toBeFocused();
  await more.click();
  await page.locator(".newsdesk-head h1").click();
  await expect(menu).toHaveCount(0);
});

test("an old «Регулятор» link opens «Политика»", async ({ page }) => {
  const asked = await openNews(page, "/news?tab=regulator");
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Политика");
  await expect.poll(() => asked.at(-1)).toBe("politics");
});

test("on a phone the tabs stay one row that pans, without widening the page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await openNews(page, "/news?tab=technology");
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Технологии");
  const bar = page.locator(".newsdesk-tabs");
  const box = await bar.boundingBox();
  expect(box.height).toBeLessThan(50);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const active = await page.locator(".newsdesk-tab.active").boundingBox();
  expect(active.x).toBeGreaterThanOrEqual(box.x - 1);
  expect(active.x + active.width).toBeLessThanOrEqual(box.x + box.width + 1);
  // The menu opens inside the screen, not clipped by the panning bar.
  await page.locator(".newsdesk-tab-more").click();
  const menu = await page.locator(".newsdesk-more-menu").boundingBox();
  expect(menu.x).toBeGreaterThanOrEqual(0);
  expect(menu.x + menu.width).toBeLessThanOrEqual(390);
  await expect(page.locator(".newsdesk-more-menu").getByRole("menuitem", { name: "Прочее" })).toBeVisible();
  await page.screenshot({ path: "test-results/news-more-menu-phone.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("an administrator's news page carries no Grok agent panel (customer, 2026-10-10)", async ({ page }) => {
  await openNews(page, "/news", { admin: true });
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Все");
  await expect(page.getByText("Экономика").first()).toBeVisible();
  await expect(page.getByText(/Новостной агент|Grok/)).toHaveCount(0);
  await page.screenshot({ path: "test-results/news-admin-no-agent.png" });
});

test("hovering «Новости» in the topbar opens its sections, and each one opens its tab", async ({ page }) => {
  const asked = await openNews(page, "/market");
  const trigger = page.locator(".topbar-nav .nav-dd-wrap").filter({ hasText: "Новости" });
  await trigger.locator(".topbar-nav-btn").first().hover();
  const panel = page.locator(".nav-dd-panel");
  await expect(panel.locator(".nav-dd-head")).toHaveText(["Лента", "Эмитенты", "События"]);
  await page.screenshot({ path: "test-results/news-nav-menu.png" });
  await panel.getByRole("menuitem", { name: "Календарь" }).click();
  await expect(page).toHaveURL(/\/news\?tab=calendar$/);
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Календарь");
  await expect(panel).toHaveCount(0);

  // Already on /news: the menu switches the tab in place.
  await trigger.locator(".topbar-nav-btn").first().hover();
  await page.locator(".nav-dd-panel").getByRole("menuitem", { name: "Финотчётность" }).click();
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Финотчётность");
  await expect(page).toHaveURL(/\/news\?tab=reporting$/);
  await expect.poll(() => asked.at(-1)).toBe("reports");

  // Back returns to the previous section.
  await page.goBack();
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Календарь");
});

test("the «Рынок» drop-down still opens its own sections", async ({ page }) => {
  await openNews(page);
  await page.locator(".topbar-nav .nav-dd-wrap").filter({ hasText: "Рынок" }).locator(".topbar-nav-btn").first().hover();
  await expect(page.locator(".nav-dd-panel .nav-dd-head")).toHaveText(["Биржа", "Валюта"]);
  await page.locator(".nav-dd-panel").getByRole("menuitem", { name: "Карта рынка" }).click();
  await expect(page).toHaveURL(/\/heatmap/);
});
