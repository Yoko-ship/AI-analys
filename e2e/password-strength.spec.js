import { test, expect } from "@playwright/test";

// New-password forms explain refusals while typing and keep submit disabled
// for passwords the server would refuse; server refusals arrive translated.

async function mockApi(page, overrides = {}) {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const send = (body, status = 200, headers = {}) => route.fulfill({ status, headers, contentType: "application/json", body: JSON.stringify(body) });
    if (overrides[path]) return overrides[path](send);
    if (path === "/api/auth/me") return send({ detail: "Not authenticated" }, 401);
    if (path === "/api/auth/options") return send({ ok: true, email_codes: true });
    if (path === "/api/market/stocks") return send({ stocks: [] });
    if (path === "/api/companies") return send({ companies: [] });
    return send({ ok: true });
  });
}

test("registration shows the meter and blocks a common password", async ({ page }) => {
  await mockApi(page);
  await page.goto("/login");
  await page.getByRole("tab", { name: "Регистрация" }).click();
  await page.getByLabel("Email").fill("reader@example.uz");
  const password = page.getByLabel("Пароль", { exact: true });
  const submit = page.getByRole("button", { name: /Создать аккаунт|Зарегистрироваться/ });

  await password.fill("12345678");
  await expect(page.locator(".password-meter")).toContainText("Слабый");
  await expect(page.locator(".password-meter")).toContainText("слишком распространён");
  await expect(submit).toBeDisabled();

  await password.fill("reader2026!!");
  await expect(page.locator(".password-meter")).toContainText("имя или email");
  await expect(submit).toBeDisabled();

  await password.fill("Samarqand-Registon-1");
  await expect(page.locator(".password-meter")).toContainText("Надёжный");
  await expect(submit).toBeEnabled();
});

test("a locked account is explained in the reader's language", async ({ page }) => {
  await mockApi(page, {
    "/api/auth/login": (send) => send({ detail: "Too many failed sign-in attempts. Try again in 15 min or reset your password." }, 429, { "Retry-After": "900" }),
  });
  await page.goto("/login");
  await page.getByLabel("Email").fill("reader@example.uz");
  await page.getByLabel("Пароль", { exact: true }).fill("whatever-it-is");
  await page.getByRole("button", { name: /Войти/ }).last().click();
  await expect(page.locator(".auth-message")).toContainText("Слишком много неудачных попыток входа. Попробуйте через 15 мин");
});

test("password reset refuses a weak new password before sending it", async ({ page }) => {
  await mockApi(page);
  await page.goto("/login");
  await page.getByRole("button", { name: "Забыли пароль?" }).click();
  await page.getByLabel("Email").fill("reader@example.uz");
  await page.getByRole("button", { name: /Отправить код/ }).click();
  await page.getByLabel("Код из письма").fill("246810");
  const change = page.getByRole("button", { name: /Сменить пароль/ });
  await page.getByLabel("Новый пароль").fill("qwertyuiop");
  await expect(page.locator(".password-meter")).toContainText("Слабый");
  await expect(change).toBeDisabled();
  await page.getByLabel("Новый пароль").fill("Violin-Lamp-Tree-77");
  await expect(change).toBeEnabled();
});
