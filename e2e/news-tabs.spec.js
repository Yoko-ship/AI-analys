// Both news feeds and the calendar share the page's navigation row.
import { readFileSync } from "node:fs";
import { test, expect } from "@playwright/test";

const press = JSON.parse(readFileSync(new URL("../tests/fixtures/news-search.json", import.meta.url), "utf8"));
const filing = { ...press, id: 6576, source_id: "openinfo_facts", source: "OpenInfo",
  title: '"Olmaliq KMK" AJ: Решения высшего органа управления', title_ru: null, summary_ru: "Решения эмитента." };

async function openNews(page, path = "/news", { admin = false } = {}) {
  const asked = [];
  page.on("pageerror", error => { throw error; });
  await page.addInitScript(() => {
    sessionStorage.setItem("uz_sponsor_seen", "1");
    localStorage.setItem("uz_track_internal", "1");
  });
  if (admin) await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_token", "admin-token"));
  await page.route("**/api/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/news/feed") {
      asked.push({ section: url.searchParams.get("section"), category: url.searchParams.get("category") });
      const items = url.searchParams.get("section") === "general" ? [press] : [press, filing];
      return route.fulfill({ json: { ok: true, count: items.length, items } });
    }
    if (url.pathname === "/api/news/corporate-events") {
      return route.fulfill({ json: { ok: true, sources: {}, categories: {}, facts: {}, items: [] } });
    }
    if (url.pathname === "/api/auth/me") {
      return route.fulfill({ status: admin ? 200 : 401, json: { user: admin
        ? { id: 1, email: "admin@example.com", full_name: "Admin", is_admin: true } : null } });
    }
    return route.fulfill({ json: { ok: true, items: [] } });
  });
  await page.route(press.image_url, route => route.abort());
  await page.goto(path);
  return asked;
}

test("news tabs open both feeds and the calendar and general news excludes issuer disclosures", async ({ page }) => {
  const asked = await openNews(page);
  const tabs = page.locator(".newsdesk-tabs .newsdesk-tab");
  await expect(tabs).toHaveText(["Общие новости", "Корпоративные новости", "Календарь"]);
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Общие новости");
  await expect(page.locator(".newsdesk-tab-more")).toHaveCount(0);
  await expect(page.locator(".newsdesk-rows")).toContainText(press.title);
  await expect(page.locator(".newsdesk-side, .newsdesk-mood")).toHaveCount(0);
  await expect(page.locator(".newsdesk-rows")).not.toContainText(filing.title);
  await expect(page.locator(".newsdesk-row-kicker").first()).toContainText(press.source);
  expect(asked).toEqual([{ section: "general", category: null }]);
  await tabs.getByText("Корпоративные новости", { exact: true }).click();
  await expect(page.getByTestId("corporate-events")).toBeVisible();
  await expect(page).toHaveURL(/\/news\?tab=corporate$/);
  expect(asked).toHaveLength(1);
  await page.locator(".newsdesk-subtabs").getByRole("button", { name: "Акции", exact: true }).click();
  await expect(page).toHaveURL(/tab=corporate&instrument=stock$/);
  await tabs.getByText("Календарь", { exact: true }).click();
  await expect(page).toHaveURL(/\/news\?tab=calendar$/);
  await expect(page.locator(".newscal")).toBeVisible();
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Календарь");
  await expect(page.locator(".newsdesk-subtabs")).toHaveCount(0);
  expect(asked).toHaveLength(1);
  await page.reload();
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Календарь");
  await expect(page.locator(".newscal")).toBeVisible();
  await tabs.getByText("Общие новости", { exact: true }).click();
  await expect(page).toHaveURL(/\/news$/);
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Общие новости");
  await expect(page.locator(".newsdesk-search input")).toBeVisible();
  await expect.poll(() => asked.length).toBe(2);
});

test("an old financial-report category link opens corporate news", async ({ page }) => {
  const asked = await openNews(page, "/news?tab=reporting");
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Корпоративные новости");
  await expect(page.getByTestId("corporate-events")).toBeVisible();
  expect(asked).toEqual([]);
});

for (const [path, labels] of [
  ["/news", ["Общие новости", "Корпоративные новости", "Календарь"]],
  ["/uz/news", ["Umumiy yangiliklar", "Korporativ yangiliklar", "Taqvim"]],
]) test(`the three navigation labels fit a phone at ${path}`, async ({ page }, info) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await openNews(page, path);
  for (const theme of ["light", "dark"]) {
    await page.evaluate(value => { document.documentElement.dataset.theme = document.body.dataset.theme = value; }, theme);
    const tabs = page.locator(".newsdesk-tabs .newsdesk-tab");
    await expect(tabs).toHaveText(labels);
    const bounds = await page.locator(".newsdesk-tabs").boundingBox();
    for (const button of await tabs.all()) {
      const box = await button.boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(bounds.x - 1);
      expect(box.x + box.width).toBeLessThanOrEqual(bounds.x + bounds.width + 1);
      expect(await button.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    }
    expect(await page.locator(".newsdesk-tabs").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`news-sections-${theme}.png`), fullPage: true });
  }
});

test("an administrator's news page carries no agent panel", async ({ page }) => {
  await openNews(page, "/news", { admin: true });
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Общие новости");
  await expect(page.getByText(/Новостной агент|Grok/)).toHaveCount(0);
});

test("the news menu offers two sections and a separate calendar", async ({ page }, info) => {
  await openNews(page, "/market");
  const trigger = page.locator(".topbar-nav .nav-dd-wrap").filter({ hasText: "Новости" });
  await trigger.locator(".topbar-nav-btn").first().hover();
  const panel = page.locator(".nav-dd-panel");
  await expect(panel.getByRole("menuitem")).toHaveText(["Общие новости", "Корпоративные новости", "Календарь"]);
  await page.screenshot({ path: info.outputPath("news-menu.png") });
  await panel.getByRole("menuitem", { name: "Корпоративные новости", exact: true }).click();
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Корпоративные новости");
  await trigger.locator(".topbar-nav-btn").first().hover();
  await panel.getByRole("menuitem", { name: "Календарь", exact: true }).click();
  await expect(page).toHaveURL(/\/news\?tab=calendar$/);
  await expect(page.locator(".newscal")).toBeVisible();
  await expect(page.getByRole('heading',{name:'Календарь событий',level:1})).toBeVisible();
  await expect(page.locator(".newsdesk-tabs .newsdesk-tab")).toHaveCount(3);
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Календарь");
  await page.goBack();
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Корпоративные новости");
});

test("the calendar is in the news tabs without duplicate buttons or sidebar previews", async ({ page }) => {
  await openNews(page);
  await expect(page.locator(".newsdesk-rows")).toContainText(press.title);
  await expect(page.locator(".newsdesk .event-preview, .newsdesk-calendar-callout")).toHaveCount(0);
  await page.locator(".newsdesk-tabs").getByRole("button", { name: "Календарь", exact: true }).click();
  await expect(page.locator(".newscal")).toBeVisible();
  await expect(page).toHaveURL(/tab=calendar$/);
  await page.locator(".newsdesk-tabs").getByRole("button", { name: "Корпоративные новости", exact: true }).click();
  await expect(page.getByTestId("corporate-events")).toBeVisible();
  await expect(page.locator(".ce-heading").getByRole("button", { name: /Календарь/ })).toHaveCount(0);
});

test("the market menu still opens its own sections", async ({ page }) => {
  await openNews(page);
  await page.locator(".topbar-nav .nav-dd-wrap").filter({ hasText: "Рынок" }).locator(".topbar-nav-btn").first().hover();
  await expect(page.locator(".nav-dd-panel .nav-dd-head")).toHaveText(["Биржа", "Валюта"]);
  await page.locator(".nav-dd-panel").getByRole("menuitem", { name: "Карта рынка" }).click();
  await expect(page).toHaveURL(/\/heatmap/);
});

for (const label of ['Рынок', 'Новости']) {
  test(`audit: ${label} menu supports keyboard navigation and dismissal`, async ({page}) => {
    await openNews(page, '/market');
    await page.mouse.move(1400, 900);
    const trigger = page.locator('.topbar-nav').getByRole('button', {name: label, exact: true});
    await trigger.focus();
    await trigger.press('ArrowDown');
    const items = page.locator('.nav-dd-panel').getByRole('menuitem');
    await expect(items.first()).toBeFocused();
    await page.keyboard.press('ArrowUp');
    await expect(items.last()).toBeFocused();
    await page.keyboard.press('Home');
    await expect(items.first()).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(page.locator('.nav-dd-panel')).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await trigger.press('Enter');
    await expect(items.first()).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.locator('.nav-dd-panel')).toHaveCount(0);
  });
}

test('audit: calendar identifies itself and offers a route back to news', async ({page}) => {
  await openNews(page, '/news?tab=calendar');
  await expect(page.getByRole('heading', {name:'Календарь событий', level:1})).toBeVisible();
  await page.getByRole('button', {name:'← Новости', exact:true}).click();
  await expect(page).toHaveURL(/\/news$/);
  await expect(page.getByRole('heading', {name:'Новости', level:1})).toBeVisible();
});
