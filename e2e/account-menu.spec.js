import { test, expect } from "@playwright/test";

// Sign-out used to live only on the profile page — a small header button on
// desktop and an unlabeled «↪» icon on phones — so users could not find it.
// The top bar now carries the account on every page.

const user = { id: 99, full_name: "E2E Investor", email: "e2e@test.uz", created_at: "2026-07-01T10:00:00Z", avatar_data_url: null };
const profile = { ok: true, user, stats: { total_analyses: 0 }, preferences: { language: "ru", theme: "dark", text_scale: 100 }, security: { email_verified: true }, notes: [], favorites: [], recent_analyses: [] };

async function mockApi(page, { signedIn }) {
  const calls = [];
  if (signedIn) await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_token", "e2e-token"));
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    calls.push(path);
    const send = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/auth/me") return signedIn ? send({ user }) : send({ detail: "Not authenticated" }, 401);
    if (path === "/api/profile") return send(profile);
    if (path === "/api/market/stocks") return send({ stocks: [] });
    if (path === "/api/companies") return send({ companies: [] });
    return send({ ok: true });
  });
  return calls;
}

for (const [device, viewport] of [["desktop", { width: 1440, height: 900 }], ["phone", { width: 390, height: 844 }]]) {
  test(`signed-in user can sign out from the top bar on ${device}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const calls = await mockApi(page, { signedIn: true });
    await page.goto("/market");

    const account = page.locator(".topbar").getByRole("button", { name: /Аккаунт/ });
    await expect(account).toBeVisible();
    await expect(account).toHaveText("EI");
    await account.click();

    const menu = page.getByRole("menu", { name: /Аккаунт/ });
    await expect(menu.getByText("E2E Investor")).toBeVisible();
    await expect(menu.getByText("e2e@test.uz")).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: "Профиль" })).toBeVisible();
    await menu.getByRole("menuitem", { name: "Выйти" }).click();

    expect(calls).toContain("/api/auth/logout");
    await expect(page.locator(".topbar").getByRole("button", { name: "Войти" })).toBeVisible();
    await expect(account).toHaveCount(0);
    expect(await page.evaluate(() => localStorage.getItem("uz_stock_analyzer_token"))).toBeNull();
  });
}

test("the account menu opens the profile and closes on Escape", async ({ page }) => {
  await mockApi(page, { signedIn: true });
  await page.goto("/market");
  const account = page.locator(".topbar").getByRole("button", { name: /Аккаунт/ });
  await account.click();
  await expect(page.getByRole("menu", { name: /Аккаунт/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu", { name: /Аккаунт/ })).toHaveCount(0);

  await account.click();
  await page.getByRole("menu", { name: /Аккаунт/ }).getByRole("menuitem", { name: "Профиль" }).click();
  await expect(page).toHaveURL(/\/profile$/);
  await expect(page.getByRole("menu", { name: /Аккаунт/ })).toHaveCount(0);
});

test("signed-out visitor sees a sign-in button in the top bar", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page, { signedIn: false });
  await page.goto("/market");
  const signIn = page.locator(".topbar").getByRole("button", { name: "Войти" });
  await expect(signIn).toBeVisible();
  await signIn.click();
  await expect(page).toHaveURL(/\/login$/);
});

test("the top bar still fits a phone without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 780 });
  await mockApi(page, { signedIn: true });
  await page.goto("/market");
  await expect(page.locator(".topbar").getByRole("button", { name: /Аккаунт/ })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});

test("the open account menu stays fully on screen on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 780 });
  await mockApi(page, { signedIn: true });
  await page.goto("/market");
  await page.locator(".topbar").getByRole("button", { name: /Аккаунт/ }).click();
  const box = await page.getByRole("menu", { name: /Аккаунт/ }).boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(360);
  await expect(page.getByRole("menuitem", { name: "Выйти" })).toBeInViewport();
});
