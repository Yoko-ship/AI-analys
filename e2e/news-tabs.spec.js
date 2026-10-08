// The news section's category tabs (customer, 2026-10-08): one compact row, the
// active tab highlighted, each tab asking the feed for its own category.
import { test, expect } from "@playwright/test";

const item = (id, category, title) => ({
  id, url: `https://example.test/${id}`, source: "Spot", source_id: "spot", lang: "ru", title,
  title_ru: title, summary_ru: title, published_at: "2026-10-08", type: "market", tone: "neutral",
  tone_score: 0, impact: "low", direction: "unclear", sectors: [], tickers: [], category, rank: 0.5,
});

async function openNews(page, path = "/news") {
  const asked = [];
  page.on("pageerror", (e) => { throw e; });
  await page.addInitScript(() => sessionStorage.setItem("uz_sponsor_seen", "1"));
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === "/api/news/feed") {
      const category = url.searchParams.get("category");
      asked.push(category);
      const items = category ? [item(1, category, `Новость раздела ${category}`)] : [item(1, "economy", "Экономика"), item(2, "markets", "Рынки")];
      return json({ ok: true, count: items.length, items });
    }
    if (url.pathname === "/api/auth/me") return json({ user: null }, 401);
    return json({ ok: true, items: [] });
  });
  await page.goto(path);
  return asked;
}

test("every category is a tab that asks the feed for its own stories", async ({ page }) => {
  const asked = await openNews(page);
  const tabs = page.locator(".newsdesk-tabs .newsdesk-tab");
  await expect(tabs).toHaveText(["Все", "Экономика", "Корпоративные", "Финотчётность", "Рынки", "Компании",
    "Политика", "Технологии", "Прочее", "Календарь"]);
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Все");
  for (const [label, key, category] of [["Экономика", "economy", "economy"], ["Финотчётность", "reporting", "reports"],
    ["Рынки", "markets", "markets"], ["Технологии", "technology", "technology"], ["Прочее", "other", "other"]]) {
    await tabs.filter({ hasText: label }).click();
    await expect(page.locator(".newsdesk-tab.active")).toHaveText(label);
    await expect(page).toHaveURL(new RegExp(`tab=${key}$`));
    await expect.poll(() => asked.at(-1)).toBe(category);
  }
  // The active tab is filled, the others are not.
  const fill = (loc) => loc.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(await fill(page.locator(".newsdesk-tab.active"))).not.toBe(await fill(tabs.first()));
});

test("an old «Регулятор» link opens «Политика»", async ({ page }) => {
  const asked = await openNews(page, "/news?tab=regulator");
  await expect(page.locator(".newsdesk-tab.active")).toHaveText("Политика");
  await expect.poll(() => asked.at(-1)).toBe("politics");
});

test("on a phone the tabs stay one row that pans, without widening the page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await openNews(page, "/news?tab=technology");
  const bar = page.locator(".newsdesk-tabs");
  const box = await bar.boundingBox();
  expect(box.height).toBeLessThan(50);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const active = await page.locator(".newsdesk-tab.active").boundingBox();
  expect(active.x).toBeGreaterThanOrEqual(box.x - 1);
  expect(active.x + active.width).toBeLessThanOrEqual(box.x + box.width + 1);
});
