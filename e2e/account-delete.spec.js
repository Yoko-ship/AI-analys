import { test, expect } from "@playwright/test";

// Deleting the account needs proof of the person, not just the session the
// browser holds: the current password, an authenticator code, or for an
// account made through Google, a fresh Google sign-in. The API is mocked; the
// request the page sends is captured.

const user = { id: 99, full_name: "E2E Investor", email: "e2e@test.uz", created_at: "2026-07-01T10:00:00Z", avatar_data_url: null };

async function openDangerZone(page, security) {
  const deletes = [];
  await page.addInitScript(() => {
    localStorage.setItem("uz_stock_analyzer_token", "e2e-token");
    localStorage.setItem("uz_stock_analyzer_language", "en");
  });
  await page.route("**/api/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const send = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/auth/me") return send({ user });
    if (path === "/api/profile") {
      return send({ ok: true, user, stats: { total_analyses: 0 }, preferences: { language: "en" },
        security: { email_verified: true, recent_sign_in_minutes: 10, ...security }, notes: [], favorites: [], recent_analyses: [] });
    }
    if (path === "/api/profile/account" && request.method() === "DELETE") {
      deletes.push(JSON.parse(request.postData()));
      return send({ ok: true, deleted: true });
    }
    return send({ ok: true, items: [], stocks: [], companies: [] });
  });
  await page.goto("/profile");
  await page.getByRole("button", { name: "Data & privacy" }).first().click();
  await page.getByLabel("Type your email to confirm").fill(user.email);
  return deletes;
}

test("a password account must enter its password before the button wakes", async ({ page }) => {
  const deletes = await openDangerZone(page, { two_factor_enabled: false, google_linked: false });
  const remove = page.getByRole("button", { name: "Delete account permanently" });
  await expect(remove).toBeDisabled();
  await expect(page.getByLabel("or authenticator code")).toHaveCount(0);
  await page.getByLabel("Current password").fill("Violin-Lamp-Tree-77");
  await remove.click();
  await expect.poll(() => deletes).toEqual([{ confirmation: user.email, password: "Violin-Lamp-Tree-77" }]);
});

test("a two-factor account may prove itself with its code instead", async ({ page }) => {
  const deletes = await openDangerZone(page, { two_factor_enabled: true, google_linked: false });
  await page.getByLabel("or authenticator code").fill("123456");
  await page.getByRole("button", { name: "Delete account permanently" }).click();
  await expect.poll(() => deletes).toEqual([{ confirmation: user.email, otp: "123456" }]);
});

test("a Google account is told to sign in again rather than asked for a password it never had", async ({ page }) => {
  await openDangerZone(page, { two_factor_enabled: false, google_linked: true });
  await expect(page.getByText("Sign in with Google again, then delete within 10 minutes")).toBeVisible();
  await expect(page.getByRole("button", { name: "Delete account permanently" })).toBeEnabled();
});
