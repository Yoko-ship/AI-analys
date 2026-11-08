import { test, expect } from "@playwright/test";

for (const width of [1280, 390]) test(`Russian collection failure explains partial CBU data at ${width}px`, async ({ page }, info) => {
  await mock(page);
  await page.setViewportSize({ width, height: 950 });
  await page.addInitScript(() => {
    localStorage.setItem("uz_stock_analyzer_language", "ru");
    localStorage.setItem("uz_stock_analyzer_theme", "light");
  });
  const latest = { ...job.latest, status: "partial", reason: "The service failed: exit-code; exit code 1.",
    failed_stage: null, started_at: "2026-11-08T01:30:09+00:00", finished_at: "2026-11-08T01:32:54+00:00",
    publication: "acknowledged", evidence: "inflation: FormatChanged", diagnosis: { saved_datasets: 9, evidence_limited: false,
      issues: [{ code: "table_missing", period: "2026-11", datasets: ["npl", "main", "structure", "capital", "liquidity", "profitability", "industry"] },
        { code: "format_changed", period: "2026-11", datasets: ["inflation"] }] } };
  await page.route("**/api/admin/collections", route => route.fulfill({ contentType: "application/json", body: JSON.stringify({
    observer: { online: true }, items: [{ ...job, id: "terminal-cbu", title_ru: "Публикации ЦБ", unit: "uzstock-terminal-cbu.service",
      schedule: "06:30 daily", next_run: "2026-11-09T01:30:00+00:00", run_command: "sudo systemctl start --no-block uzstock-terminal-cbu.service",
      logs_command: "sudo journalctl -u uzstock-terminal-cbu.service", latest }] }) }));
  await page.goto("/admin/streams");
  const card = page.locator(".collection-card");
  await expect(card.getByText("Обновление выполнено частично.", { exact: true })).toBeVisible();
  await expect(card.getByText(/Не найдены таблицы за 11\.2026/)).toBeVisible();
  await expect(card.getByText(/Инфляция: не удалось прочитать формат таблицы/)).toBeVisible();
  await expect(card.getByText(/Обновлено разделов: 9/)).toBeVisible();
  await expect(card.getByText(/exit code 1/)).not.toBeVisible();
  await expect(card.getByText("uzstock-terminal-cbu.service", { exact: true })).not.toBeVisible();
  await card.getByRole("button", { name: "Подробнее", exact: true }).click();
  await expect(card.getByText("inflation: FormatChanged", { exact: true })).not.toBeVisible();
  const technical = card.locator(".collection-technical summary").first();
  await technical.focus();
  await technical.press("Enter");
  await expect(card.getByText("inflation: FormatChanged", { exact: true })).toBeVisible();
  await technical.press("Enter");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: info.outputPath("cbu-explanation-ru.png"), fullPage: true });
});

const job = {
  id: "quotes-catchup", title: "Quotes", title_ru: "Котировки", title_uz: "Kotirovkalar",
  schedule: "09:30 daily; 16:10, 18:00, 21:30, 23:30 Mon–Sat",
  unit: "uzstock-quotes-catchup.service", next_run: "2026-11-07T13:00:00+00:00",
  schedule_issue: null, can_run: true, request: null,
  latest: { status: "failed", reason: "HTTP 429: source rate limit", reason_code: "failed",
    diagnosis: { issues: [{ code: "rate_limited" }] },
    failed_stage: "quotes", publication: "unverified", started_at: "2026-11-07T09:30:00+00:00",
    finished_at: "2026-11-07T09:31:00+00:00", evidence: "openinfo refused the request: HTTP 429", receipts: [] },
  history: [], run_command: "sudo systemctl start --no-block uzstock-quotes-catchup.service",
  logs_command: "sudo journalctl --no-pager -n 200 _SYSTEMD_UNIT=uzstock-quotes-catchup.service + UNIT=uzstock-quotes-catchup.service + SYSLOG_IDENTIFIER=uzstock-quotes-catchup",
};

async function mock(page, offline = false) {
  let request = null;
  await page.addInitScript(() => {
    localStorage.setItem("uz_stock_analyzer_token", "admin-token");
    localStorage.setItem("uz_stock_analyzer_language", "en");
  });
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const send = body => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/auth/me") return send({ user: { id: 1, email: "admin@example.com", is_admin: true } });
    if (path === "/api/admin/overview") return send({ ok: true, catalog: {}, audit: {}, streams: [] });
    if (path === "/api/admin/collections") return send({ observer: { online: !offline, last_seen: null }, items: [{ ...job, request, can_run: !offline && !request }] });
    if (path.endsWith("/quotes-catchup/run")) {
      request = { id: "request-1", status: "queued", detail: "Waiting for the server monitor" };
      return send(request);
    }
    return send({ ok: true, items: [] });
  });
}

test("light theme keeps a confirmed publication and its history readable", async ({ page }, info) => {
  await mock(page);
  await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_theme", "light"));
  const run = { ...job.latest, invocation: "run-2", status: "completed", publication: "acknowledged",
    diagnosis: { issues: [] },
    failed_stage: null, reason: "The server acknowledged writes.", evidence: "quotes saved",
    receipts: [{ stage: "/api/admin/quotes", ok: true, counts: { upserted: 12 } }] };
  await page.route("**/api/admin/collections", route => route.fulfill({ contentType: "application/json",
    body: JSON.stringify({ observer: { online: true }, items: [{ ...job, latest: run, history: [run] }] }) }));
  await page.route("**/api/admin/collections/quotes-catchup/runs/run-2", route => route.fulfill({ contentType: "application/json", body: JSON.stringify(run) }));
  await page.goto("/admin/streams");
  await page.getByRole("button", { name: "Details", exact: true }).click();
  await expect(page.getByText("Writes acknowledged by server", { exact: true })).toBeVisible();
  await page.locator(".collection-past summary").first().click();
  await page.locator(".collection-past .collection-technical summary").click();
  await expect(page.locator(".collection-past .collection-log")).toHaveText("quotes saved");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: info.outputPath("collectors-light-history.png"), fullPage: true });
});

test("manual collection uses the administrator authenticator flow", async ({ page }) => {
  await mock(page);
  let proved = false;
  let launches = 0;
  await page.route("**/api/admin/collections/quotes-catchup/run", route => {
    if (!proved) return route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: { code: "MFA_REQUIRED", message: "Enter a current authenticator code." } }) });
    launches += 1;
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: "accepted", status: "queued" }) });
  });
  await page.route("**/api/auth/admin/step-up", route => {
    proved = JSON.parse(route.request().postData()).code === "123456";
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: proved, expires_in: 900 }) });
  });
  await page.goto("/admin/streams");
  await page.getByRole("button", { name: "Run now", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Confirm this action" });
  await expect(dialog).toBeVisible();
  expect(launches).toBe(0);
  await dialog.locator("input").fill("123456");
  await dialog.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect.poll(() => launches).toBe(1);
});

for (const width of [1440, 390]) test(`collector failure and manual retry at ${width}px`, async ({ page }, info) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await mock(page);
  await page.setViewportSize({ width, height: 950 });
  await page.goto("/admin/streams");
  await expect(page.getByText("The source temporarily limited the number of requests.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Details" }).click();
  await page.locator(".collection-detail > .collection-evidence .collection-technical summary").click();
  await expect(page.getByText(job.run_command, { exact: true })).toBeVisible();
  await expect(page.getByText("openinfo refused the request: HTTP 429", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Run now", exact: true }).click();
  await expect(page.getByText("Queued", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run now", exact: true })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath(`collectors-${width}.png`), fullPage: true });
  expect(errors).toEqual([]);
});

test("a disconnected monitor never presents old results as live", async ({ page }) => {
  await mock(page, true);
  await page.goto("/admin/streams");
  await expect(page.getByRole("alert").filter({ hasText: "monitor" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run now", exact: true })).toBeDisabled();
});

test("merged quotes preserve readable results from retired schedules", async ({ page }, info) => {
  await mock(page);
  const archived = { ...job.latest, job: "quotes-1610", invocation: "old-close-run",
    diagnosis: { issues: [] },
    status: "completed", publication: "acknowledged", reason: "174 writes acknowledged", evidence: "retained closing quote journal" };
  await page.route("**/api/admin/collections", route => route.fulfill({ contentType: "application/json",
    body: JSON.stringify({ observer: { online: true }, items: [{ ...job, title: "Quotes",
      history: [archived], schedule: "09:30 daily; 16:10, 18:00, 21:30, 23:30 Mon–Sat" }] }) }));
  await page.route("**/api/admin/collections/quotes-1610/runs/old-close-run", route => route.fulfill({
    contentType: "application/json", body: JSON.stringify(archived) }));
  await page.goto("/admin/streams");
  await expect(page.locator(".collection-card")).toHaveCount(1);
  await page.getByRole("button", { name: "Details", exact: true }).click();
  await page.locator(".collection-past summary").first().click();
  await page.locator(".collection-past .collection-technical summary").click();
  await expect(page.locator(".collection-past .collection-log")).toHaveText("retained closing quote journal");
  await expect(page.locator(".collection-past").getByText("Writes acknowledged by server", { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath("merged-quotes-history.png"), fullPage: true });
});
