import { test as base, expect } from "@playwright/test";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const analysis = JSON.parse(readFileSync(new URL("./fixtures/research.json", import.meta.url), "utf8"));
const test = base.extend({
  researchURL: [async ({}, use) => {
    const server = await createServer({ configFile: false, root: fileURLToPath(new URL("./harness", import.meta.url)),
      plugins: [react()], server: { host: "127.0.0.1", port: 0,
        fs: { allow: [fileURLToPath(new URL("..", import.meta.url))] } } });
    await server.listen();
    try { await use(server.resolvedUrls.local[0]); } finally { await server.close(); }
  }, { scope: "worker" }],
});
test.beforeEach(async ({ page, researchURL }) => {
  await page.route("**/api/**", route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/analyze") return route.fulfill({ json: analysis });
    if (pathname.includes("/export/")) return route.fulfill({ contentType: "application/octet-stream", body: "test export" });
    if (pathname === "/api/periods") return route.fulfill({ json: { ok: true, periods: {
      annual_years: [2025, 2024], quarterly: [{ year: 2025, quarter: 2 }], latest_annual_year: 2025,
      latest_quarterly: { year: 2025, quarter: 2 },
    } } });
    if (pathname === "/api/compare") return route.fulfill({ json: { comparison: {
      summary: { short: "Comparison complete" }, leaders: [], ranking: [], normalized_ranking: [], charts: [], tables: {},
    } } });
    return route.fulfill({ json: {} });
  });
  await page.goto(researchURL);
  await page.evaluate(() => { document.body.dataset.theme = document.documentElement.dataset.theme = "light"; });
});

test("analysis setup uses labeled controls and progressive disclosure", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Анализ компании", level: 1 })).toBeVisible();
  await expect(page.getByLabel("Компания", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Тип анализа", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Обновить из источника (обойти кэш)")).not.toBeVisible();
  await page.getByText("Дополнительные параметры", { exact: true }).click();
  await expect(page.getByLabel("Обновить из источника (обойти кэш)")).toBeVisible();
  const company = page.getByRole("button", { name: /AGBA.*AGBA Bank/ });
  await company.click();
  await expect(company).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("Компания", { exact: true })).toHaveValue("AGBA");
});

test("analysis renders risk, observations and a downloadable report", async ({ page }) => {
  await page.getByLabel("Компания", { exact: true }).fill("AGBA");
  await page.locator('form button[type="submit"]').click();
  await expect(page.locator(".risk-profile-panel")).toContainText("Финансовый риск");
  await expect(page.locator(".risk-profile-panel")).toContainText("§3.11");
  await expect(page.locator(".debt-load-badge")).toContainText("Умеренная");
  await expect(page.locator(".metric-rings-grid")).toContainText("Маржа EBITDA");
  await expect(page.locator(".observations-panel")).toContainText("Одновременное ухудшение");
  await expect(page.locator(".financial-bars")).toContainText("EBITDA");
  await expect(page.locator(".structure-panel")).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /Скачать PDF/ }).click();
  expect((await download).suggestedFilename()).toMatch(/\.pdf$/);
});

for (const theme of ["light", "dark"]) {
  test(`comparison results keep their heading and exports readable on a phone (${theme})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(value => { document.body.dataset.theme = document.documentElement.dataset.theme = value; }, theme);
    await page.getByRole("button", { name: "QA Compare", exact: true }).click();
    await page.locator(".compare-inputs-grid input").nth(0).fill("AGBA");
    await page.locator(".compare-inputs-grid input").nth(1).fill("ALKB");
    await page.locator('form button[type="submit"]').click();
    await expect(page.getByText("Comparison complete")).toBeVisible();
    const heading = page.locator(".compare-overview-panel h2");
    const exports = page.locator(".compare-export-actions");
    for (const button of await exports.getByRole("button").all()) {
      const buttonBox = await button.boundingBox();
      expect(buttonBox.height).toBeGreaterThanOrEqual(36);
      expect(buttonBox.height).toBeLessThanOrEqual(64);
    }
    await heading.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`comparison-${theme}.png`), fullPage: true });
    const box = await heading.boundingBox();
    expect(box.width).toBeGreaterThan(220);
    expect((await exports.boundingBox()).y).toBeGreaterThanOrEqual(box.y + box.height);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const download = page.waitForEvent("download");
    await exports.getByRole("button", { name: /Скачать Excel/ }).click();
    expect((await download).suggestedFilename()).toMatch(/\.xlsx$/);
  });
}

test("research rejects duplicate companies, recovers from failure and clears results on logout", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/compare", route => {
    calls++;
    return calls === 1 ? route.fulfill({ status: 503, json: { detail: "Please retry" } }) : route.fallback();
  });
  await page.getByRole("button", { name: "QA Compare", exact: true }).click();
  const inputs = page.locator(".compare-inputs-grid input");
  await inputs.nth(0).fill("AGBA"); await inputs.nth(1).fill("agba");
  await page.locator('form button[type="submit"]').click();
  expect(calls).toBe(0);
  await inputs.nth(1).fill("ALKB");
  await page.locator('form button[type="submit"]').click();
  await expect(page.getByTestId("qa-toasts")).toContainText("Please retry");
  await page.locator('form button[type="submit"]').click();
  await expect(page.getByText("Comparison complete")).toBeVisible();
  await page.getByRole("button", { name: "QA Logout", exact: true }).click();
  await expect(inputs).toHaveCount(0);
  await expect(page.getByText("Comparison complete")).toHaveCount(0);
});
