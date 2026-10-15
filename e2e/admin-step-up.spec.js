import { test, expect } from "@playwright/test";

// A session token alone no longer changes anything as an admin, and a Google
// sign-in no longer skips two-factor. The API is mocked; the requests the page
// sends are captured so the test pins what the browser proves and when.

test("an admin change asks for the authenticator code once, then goes through", async ({ page }) => {
  const calls = [];
  let proved = false;
  await page.addInitScript(() => {
    localStorage.setItem("uz_stock_analyzer_token", "admin-token");
    localStorage.setItem("uz_stock_analyzer_language", "en");
  });
  await page.route("**/api/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const send = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (request.method() !== "GET") calls.push({ method: request.method(), path, body: request.postData() });
    if (path === "/api/auth/me") return send({ user: { id: 1, email: "admin@example.com", full_name: "Admin", is_admin: true } });
    if (path === "/api/admin/overview") return send({ ok: true, catalog: {}, audit: { open: {}, history: [], queue: [], latest: null }, news: {}, streams: [] });
    if (path === "/api/admin/feedback") return send({ ok: true, items: [{ id: 5, status: "open", subject: "Chart", message: "Broken", email: "r@example.com", created_at: "2026-10-15T10:00:00Z" }] });
    if (path === "/api/auth/admin/step-up") {
      proved = JSON.parse(request.postData()).code === "123456";
      return proved ? send({ ok: true, expires_in: 900 }) : send({ detail: "Invalid two-factor code" }, 400);
    }
    if (path === "/api/admin/feedback/5") {
      return proved ? send({ ok: true }) : send({ detail: { code: "MFA_REQUIRED", message: "Enter a current authenticator code." } }, 403);
    }
    return send({ ok: true, items: [] });
  });
  await page.goto("/admin/feedback");
  await page.getByLabel("Change status").selectOption("resolved");

  const dialog = page.getByRole("dialog", { name: "Confirm this action" });
  await expect(dialog).toBeVisible();
  await dialog.locator("input").fill("000000");
  await dialog.getByRole("button", { name: "Confirm" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("Invalid code. Try again.");
  await dialog.locator("input").fill("123456");
  await dialog.getByRole("button", { name: "Confirm" }).click();
  await expect(dialog).toHaveCount(0);

  await expect.poll(() => calls.map((c) => `${c.method} ${c.path}`)).toEqual([
    "PATCH /api/admin/feedback/5",
    "POST /api/auth/admin/step-up",
    "POST /api/auth/admin/step-up",
    "PATCH /api/admin/feedback/5",
  ]);
});

test("Google sign-in to an account with two-factor waits for the code", async ({ page }) => {
  const exchanges = [];
  await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_language", "en"));
  await page.route("**/api/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const send = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/auth/oauth/exchange") {
      const body = JSON.parse(request.postData());
      exchanges.push(body);
      if (!body.otp) return send({ detail: "Two-factor code required" }, 401);
      if (body.otp !== "123456") return send({ detail: "Invalid two-factor code" }, 401);
      return send({ ok: true, provider: "google", token: "tok-google" });
    }
    if (path === "/api/auth/me") {
      const signedIn = (request.headers().authorization || "") === "Bearer tok-google";
      return signedIn ? send({ user: { id: 9, email: "person@example.com", full_name: "Person" } }) : send({ detail: "Not authenticated" }, 401);
    }
    return send({ ok: true, items: [] });
  });
  await page.goto("/#provider=google&oauth_code=one-time-code");

  await expect(page.getByRole("heading", { name: "Two-factor protection" })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("uz_stock_analyzer_token"))).toBeNull();
  const code = page.getByLabel("Authenticator code");
  await code.fill("000000");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.locator(".auth-message")).toHaveText("Invalid authenticator code. Try again.");
  await code.fill("123456");
  await page.getByRole("button", { name: "Confirm" }).click();

  await expect.poll(() => page.evaluate(() => localStorage.getItem("uz_stock_analyzer_token"))).toBe("tok-google");
  expect(exchanges).toEqual([
    { code: "one-time-code" },
    { code: "one-time-code", otp: "000000" },
    { code: "one-time-code", otp: "123456" },
  ]);
});
