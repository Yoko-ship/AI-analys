import { test, expect } from "@playwright/test";

test.skip(!process.env.E2E_BASE_URL, "Set E2E_BASE_URL to run checks against a deployed environment.");

test("live Russian calendar data fits the screenshot-width viewport", async ({ page }) => {
  await page.setViewportSize({ width: 705, height: 1001 });
  await page.goto("/news?tab=calendar");
  await page.locator("#languageSelect").selectOption("ru");

  const grid = page.locator(".newscal-grid");
  const weekdays = page.locator(".newscal-dow");
  const titles = page.locator(".newscal-row-title");
  await expect(grid).toBeVisible({ timeout: 30_000 });
  await expect(weekdays).toHaveCount(7);
  await expect(titles.first()).toBeVisible({ timeout: 30_000 });

  const geometry = await page.evaluate(() => {
    const calendar = document.querySelector(".newscal-grid");
    const days = [...document.querySelectorAll(".newscal-dow")];
    const gridRect = calendar.getBoundingClientRect();
    const lastDayRect = days.at(-1).getBoundingClientRect();
    return {
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      gridLeft: gridRect.left,
      gridRight: gridRect.right,
      lastDayLeft: lastDayRect.left,
      lastDayRight: lastDayRect.right,
    };
  });

  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth);
  expect(geometry.gridLeft).toBeGreaterThanOrEqual(0);
  expect(geometry.gridRight).toBeLessThanOrEqual(geometry.clientWidth);
  expect(geometry.lastDayLeft).toBeGreaterThan(geometry.gridLeft);
  expect(geometry.lastDayRight).toBeLessThanOrEqual(geometry.clientWidth);

  const visibleTitles = await titles.evaluateAll((nodes) => nodes.slice(0, 10).map((node) => node.textContent.trim()));
  expect(visibleTitles.every((title) => /[А-Яа-яЁё]/.test(title))).toBe(true);
  expect(visibleTitles.every((title) => !/(акциядор|умумий\s+йиғилиш|aksiyador|umumiy\s+yig)/i.test(title))).toBe(true);
});
