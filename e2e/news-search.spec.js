import { readFileSync } from "node:fs";
import { test, expect } from "@playwright/test";

// Requires the real Python renderer serving the current frontend build, with
// e2e.seo_news_app providing the fixture instead of a production database.
test.skip(!process.env.E2E_NEWS_SEO_APP, "Run against the local news SEO app.");
const item = JSON.parse(readFileSync(new URL("../tests/fixtures/news-search.json", import.meta.url), "utf8"));

test.describe("news without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("a crawler can follow the news index to a story and its original source", async ({ page }) => {
    const response = await page.goto("/news");
    expect(response.status()).toBe(200);
    const story = page.getByRole("link", { name: item.title, exact: true });
    await expect(story).toHaveAttribute("href", `/news/${item.id}`);
    await expect(page.locator(".seo-snapshot")).toContainText(item.summary_ru);
    await story.click();
    await expect(page).toHaveURL(new RegExp(`/news/${item.id}$`));
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(item.title);
    await expect(page.getByRole("link", { name: `Источник: ${item.source}`, exact: true })).toHaveAttribute("href", item.url);
    await expect(page.locator(".seo-snapshot")).toContainText("Изложение подготовлено UZStock");
  });
});

test("news metadata and source credit survive React rendering", async ({ page }) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => {
    localStorage.setItem("uz_track_internal", "1");
    sessionStorage.setItem("uz_sponsor_seen", "1");
  });
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me") return route.fulfill({ status: 401, json: { user: null } });
    if (path === `/api/news/item/${item.id}`) {
      return route.fulfill({ json: { ok: true, item, related: [] } });
    }
    return route.fulfill({ json: { ok: true, items: [], stocks: [], companies: [] } });
  });
  await page.route(item.image_url, route => route.abort());
  const response = await page.goto(`/news/${item.id}`);
  expect(response.status()).toBe(200);
  await expect(page.locator(".led-art-title")).toBeVisible();
  await expect(page.locator(".seo-snapshot")).toHaveCount(0);
  await expect(page).toHaveTitle(`${item.title} | UZStock`);
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", `https://uzstock.uz/news/${item.id}`);
  const blocks = await page.locator('script[type="application/ld+json"]').allTextContents();
  const article = blocks.map(block => JSON.parse(block)).find(block => block["@type"] === "NewsArticle");
  expect(article.citation).toEqual({
    "@type": "CreativeWork", url: item.url, name: item.title,
    publisher: { "@type": "Organization", name: item.source },
  });
  expect(article.author.name).toBe("UZStock");
  await expect(page.locator(".led-art-cta")).toHaveAttribute("href", item.url);
  await expect(page.locator(".led-art-note")).toContainText("подготовлено платформой");
  expect(errors).toEqual([]);
});
