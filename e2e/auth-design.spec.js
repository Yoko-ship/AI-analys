import { test, expect } from "@playwright/test";

const STOCKS = {
  updated_at: "2026-08-26T12:00:00Z",
  stocks: [
    { ticker: "AGBA", last_price: 1500, close_price: 1440 },
    { ticker: "KVTS", last_price: 320, close_price: 300 },
    { ticker: "ALKB", last_price: 900, close_price: 930 },
    { ticker: "UZMK", last_price: 11980, close_price: 12080 },
  ],
};

async function mockAuthPageApi(page) {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const send = (body, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
    if (path === "/api/companies") return send({ companies: [] });
    if (path === "/api/catalog/status") return send({ ok: true, last_sync: null });
    if (path === "/api/securities") return send({ ok: true, securities: {} });
    if (path === "/api/market/stocks") return send(STOCKS);
    if (path === "/api/auth/me") return send({ detail: "Not authenticated" }, 401);
    return send({ ok: true });
  });
}

test.beforeEach(async ({ page }) => {
  await mockAuthPageApi(page);
  await page.goto("/login");
});

test("renders centered login variant with working auth controls", async ({ page }, testInfo) => {
  await expect(page.locator("header.topbar")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Войти в UZ Stock Analyzer" })).toBeVisible();
  await expect(page.locator(".auth-hub-card")).toBeVisible();
  await expect(page.locator(".auth-market-strip")).toBeVisible();

  const password = page.getByLabel("Пароль", { exact: true });
  await expect(password).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Показать пароль" }).click();
  await expect(password).toHaveAttribute("type", "text");

  await page.getByRole("tab", { name: "Регистрация" }).click();
  await expect(page.getByRole("heading", { name: "Создать аккаунт" })).toBeVisible();
  await expect(page.getByLabel("Имя и фамилия")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("auth-desktop.png"), fullPage: true });
});

test("fits a phone viewport without horizontal overflow", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.reload();
  await expect(page.locator(".auth-hub-card")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
  await page.screenshot({ path: testInfo.outputPath("auth-mobile.png"), fullPage: true });
});
