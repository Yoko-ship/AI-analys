import { test, expect } from "@playwright/test";
import { SERVICE, DEPLOYMENT, OLDER, snapshot, history, runtimeLogs } from "./railway-fixture.js";

async function setup(page, { configured = true, admin = true } = {}) {
  const state = { status: structuredClone(snapshot), requests: [], failStatus: false, failRecovery: false };
  state.status.configured = configured;
  if (!configured) state.status.services = [];
  await page.addInitScript(() => {
    localStorage.setItem("uz_stock_analyzer_token", "e2e-admin");
    localStorage.setItem("uz_stock_analyzer_language", "en");
    localStorage.setItem("uz_stock_analyzer_theme", "light");
  });
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    state.requests.push({ path: url.pathname, method: req.method(), body: req.postDataJSON() });
    const send = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === "/api/auth/me") return send({ user: { id: 41, email: "qa@example.com", full_name: "QA Admin", is_admin: admin } });
    if (url.pathname === "/api/admin/railway") return state.failStatus ? send({ detail: "Railway is unavailable" }, 502) : send(state.status);
    if (url.pathname.endsWith("/recover")) {
      if (state.failRecovery) return send({ detail: "Railway did not confirm the request" }, 502);
      state.status.services[0].deployment.status = "SUCCESS";
      state.status.services[0].recovery_action = null;
      return send({ accepted: true, action: "restart" }, 202);
    }
    if (url.pathname.endsWith("/deployments")) return send(history);
    if (url.pathname.endsWith("/logs")) return url.searchParams.get("kind") === "build" ? send({ kind: "build", lines: [], error_excerpt: null }) : send(runtimeLogs);
    if (url.pathname === "/api/admin/overview") return send({ ok: true });
    return send({ ok: true, items: [], companies: [], securities: {}, stocks: [], financials: {}, ratios: {}, sources: [], alerts: [] });
  });
  return state;
}

test("admin Railway navigation, status, runtime/build logs, history, and confirmed recovery", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (err) => errors.push(err.message));
  const state = await setup(page);
  await page.goto("/admin/system");
  await page.locator(".admin-subtabs").getByRole("button", { name: "Railway", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/railway$/);
  const crashed = page.getByRole("article", { name: "reports-watch" });
  await expect(crashed).toContainText("Crashed");
  await expect(page.getByRole("article", { name: "bank-fx" })).toContainText("Scheduled");
  await expect(page.getByRole("article", { name: "AI-analys" })).toContainText("Running");
  await crashed.getByRole("button", { name: "Logs & history" }).click();
  await expect(page.locator(".railway-excerpt")).toContainText("ModuleNotFoundError");
  await page.getByLabel("Deployment", { exact: true }).selectOption(OLDER);
  await expect.poll(() => state.requests.some((r) => r.path.includes(OLDER) && r.path.endsWith("/logs"))).toBe(true);
  await page.getByLabel("Logs", { exact: true }).selectOption("build");
  await expect(page.locator(".railway-log")).toContainText("No logs available");
  await crashed.getByRole("button", { name: "Restart", exact: true }).click();
  await expect(crashed.getByRole("group", { name: "Confirm recovery" })).toBeVisible();
  expect(state.requests.filter((r) => r.method === "POST" && r.path.endsWith("/recover"))).toHaveLength(0);
  await crashed.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(crashed.getByRole("group")).toHaveCount(0);
  await crashed.getByRole("button", { name: "Restart", exact: true }).click();
  await crashed.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("recovery is not confirmed yet");
  await expect(crashed.getByRole("button", { name: "Restart", exact: true })).toHaveCount(0);
  const sent = state.requests.filter((r) => r.path.endsWith("/recover"));
  expect(sent).toHaveLength(1);
  expect(sent[0].path).toBe(`/api/admin/railway/services/${SERVICE}/recover`);
  expect(sent[0].body).toEqual({ action: "restart", deployment_id: DEPLOYMENT, confirm: true });
  await page.reload();
  await expect(crashed).toContainText("Scheduled");
  expect(errors).toEqual([]);
});

test("unconfigured integration gives setup instructions without fake health", async ({ page }) => {
  await setup(page, { configured: false });
  await page.goto("/admin/railway");
  await expect(page.getByText("Railway is not connected yet")).toBeVisible();
  await expect(page.locator(".railway-service")).toHaveCount(0);
});

test("failed refresh marks old data stale and disables recovery; later refresh heals it", async ({ page }) => {
  const state = await setup(page);
  await page.goto("/admin/railway");
  const restart = page.getByRole("button", { name: "Restart", exact: true });
  await expect(restart).toBeEnabled();
  state.failStatus = true;
  await page.locator(".railway-panel").getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Current service state is unknown");
  await expect(restart).toBeDisabled();
  await expect(page.locator(".railway-toolbar")).toContainText("Data is stale");
  state.failStatus = false;
  await page.locator(".railway-panel").getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(restart).toBeEnabled();
});

test("unconfirmed recovery is not retried or displayed as success", async ({ page }) => {
  const state = await setup(page);
  state.failRecovery = true;
  await page.goto("/admin/railway");
  await page.getByRole("button", { name: "Restart", exact: true }).click();
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Check status before trying again");
  await expect(page.getByRole("button", { name: "Waiting…", exact: true })).toBeDisabled();
  expect(state.requests.filter((r) => r.path.endsWith("/recover"))).toHaveLength(1);
});

test("non-admin cannot enter Railway screen", async ({ page }) => {
  const state = await setup(page, { admin: false });
  await page.goto("/admin/railway");
  await expect(page.getByRole("heading", { name: "Administrators only" })).toBeVisible();
  expect(state.requests.some((r) => r.path.startsWith("/api/admin/railway"))).toBe(false);
});

test("phone layout contains logs and action controls without page overflow", async ({ page }) => {
  await setup(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin/railway");
  await page.getByRole("article", { name: "reports-watch" }).getByRole("button", { name: "Logs & history" }).click();
  await expect(page.locator(".railway-log")).toContainText("ModuleNotFoundError");
  expect(await page.locator(".railway-panel").evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  await expect.poll(() => page.locator(".railway-details h3").evaluate((el) =>
    el.getBoundingClientRect().top >= document.querySelector(".topbar").getBoundingClientRect().bottom)).toBe(true);
  await page.getByRole("button", { name: "Restart", exact: true }).click();
  await expect(page.getByRole("button", { name: "Confirm", exact: true })).toBeVisible();
});
