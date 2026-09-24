import { test, expect } from "@playwright/test";

// Email-code screens: registration that must prove the inbox, and password
// reset. The API is mocked; the requests the page sends are captured so the
// test pins the contract (notably: verify carries the password the owner chose).

async function mockApi(page, { emailCodes = true } = {}) {
  const calls = [];
  await page.route("**/api/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const body = request.postData() ? JSON.parse(request.postData()) : null;
    calls.push({ path, body });
    const send = (payload, status = 200) => route.fulfill({
      status, contentType: "application/json", body: JSON.stringify(payload),
    });
    if (path === "/api/auth/me") return send({ detail: "Not authenticated" }, 401);
    if (path === "/api/auth/options") return send({ ok: true, email_codes: emailCodes });
    if (path === "/api/auth/register") {
      return send({ ok: true, verification_required: true, email: "reader@example.test" });
    }
    if (path === "/api/auth/email/verify" || path === "/api/auth/password/reset") {
      return send({
        ok: true, token: "tok-1", token_type: "bearer",
        user: { id: 1, email: "reader@example.test", full_name: "Reader", email_verified: true },
      });
    }
    if (path === "/api/companies") return send({ companies: [] });
    if (path === "/api/securities") return send({ ok: true, securities: {} });
    if (path === "/api/market/stocks") return send({ stocks: [] });
    return send({ ok: true });
  });
  return calls;
}

test("registration asks for the emailed code and signs in with it", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/login");
  await page.getByRole("tab", { name: "Регистрация" }).click();
  await page.getByLabel("Email").fill("Reader@Example.test");
  await page.getByLabel("Пароль", { exact: true }).fill("long-password");
  await page.getByRole("button", { name: /Создать аккаунт|Зарегистрироваться/ }).click();

  await expect(page.getByRole("heading", { name: "Подтвердите email" })).toBeVisible();
  await expect(page.getByText("reader@example.test")).toBeVisible();
  const confirm = page.getByRole("button", { name: /Подтвердить/ });
  await expect(confirm).toBeDisabled();
  await expect(page.getByRole("button", { name: /Отправить снова через/ })).toBeDisabled();

  await page.getByLabel("Код из письма").fill("123 456");
  await expect(page.getByLabel("Код из письма")).toHaveValue("123456");
  await confirm.click();

  await expect(page.getByRole("heading", { name: "Подтвердите email" })).toBeHidden();
  const verify = calls.find((c) => c.path === "/api/auth/email/verify");
  expect(verify.body).toMatchObject({ email: "reader@example.test", code: "123456", password: "long-password" });
  const register = calls.find((c) => c.path === "/api/auth/register");
  expect(register.body.language).toBe("ru");
});

test("forgot password sends a code and sets the new password", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/login");
  await page.getByLabel("Email").fill("reader@example.test");
  await page.getByRole("button", { name: "Забыли пароль?" }).click();

  await expect(page.getByRole("heading", { name: "Восстановление пароля" })).toBeVisible();
  await expect(page.getByLabel("Email")).toHaveValue("reader@example.test");
  await page.getByRole("button", { name: /Отправить код/ }).click();

  await expect(page.getByLabel("Код из письма")).toBeVisible();
  await page.getByLabel("Код из письма").fill("246810");
  await page.getByLabel("Новый пароль").fill("brand-new-pass");
  await page.getByRole("button", { name: /Сменить пароль/ }).click();

  await expect(page.getByRole("heading", { name: "Восстановление пароля" })).toBeHidden();
  expect(calls.find((c) => c.path === "/api/auth/password/forgot").body)
    .toMatchObject({ email: "reader@example.test", language: "ru" });
  expect(calls.find((c) => c.path === "/api/auth/password/reset").body)
    .toEqual({ email: "reader@example.test", code: "246810", new_password: "brand-new-pass" });
});

test("no reset link while the server cannot send mail", async ({ page }) => {
  await mockApi(page, { emailCodes: false });
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Войти в UZ Stock Analyzer" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Забыли пароль?" })).toHaveCount(0);
});

test("code screen fits a phone without horizontal overflow", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/login");
  await page.getByRole("button", { name: "Забыли пароль?" }).click();
  await page.getByLabel("Email").fill("reader@example.test");
  await page.getByRole("button", { name: /Отправить код/ }).click();
  await expect(page.getByLabel("Код из письма")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});
