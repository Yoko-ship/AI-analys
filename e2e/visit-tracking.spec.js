import { test, expect } from "@playwright/test";

// The visit beacon: campaign tags on the first page, and a `leave` event with
// the time the page was actually on screen when the reader moves on.
test("a visit reports its campaign and how long each page was read", async ({ page }) => {
  const beacons = [];
  await page.route("**/api/**", (route) => {
    const request = route.request();
    if (new URL(request.url()).pathname === "/api/track") {
      beacons.push(JSON.parse(request.postData() || "{}"));
      return route.fulfill({ status: 204, body: "" });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, items: [] }) });
  });
  await page.goto("/news?utm_source=Telegram&utm_campaign=launch-oct");
  await expect.poll(() => beacons.filter((b) => !b.event).length).toBeGreaterThan(0);
  const first = beacons.find((b) => !b.event);
  expect(first).toMatchObject({ path: "/news", us: "Telegram", uc: "launch-oct" });

  await page.waitForTimeout(1200);
  await page.evaluate(() => window.history.pushState({}, "", "/market"));
  await page.evaluate(() => window.dispatchEvent(new PopStateEvent("popstate")));
  await expect.poll(() => beacons.filter((b) => b.event === "leave").length).toBeGreaterThan(0);
  const leave = beacons.find((b) => b.event === "leave");
  expect(leave.path).toBe("/news");
  expect(leave.sid).toBe(first.sid);
  expect(leave.ms).toBeGreaterThanOrEqual(1000);
  expect(leave.sp).toBeGreaterThanOrEqual(0);
  expect(leave.sp).toBeLessThanOrEqual(100);
  // later pages of the same visit do not repeat the campaign
  await expect.poll(() => beacons.filter((b) => !b.event && b.path === "/market").length).toBe(1);
  expect(beacons.find((b) => !b.event && b.path === "/market").us).toBeUndefined();
});

test("a browser the team excluded marks every beacon", async ({ page }) => {
  const beacons = [];
  await page.addInitScript(() => localStorage.setItem("uz_track_internal", "1"));
  await page.route("**/api/**", (route) => {
    const request = route.request();
    if (new URL(request.url()).pathname === "/api/track") {
      beacons.push(JSON.parse(request.postData() || "{}"));
      return route.fulfill({ status: 204, body: "" });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, items: [] }) });
  });
  await page.goto("/news");
  await expect.poll(() => beacons.length).toBeGreaterThan(0);
  expect(beacons.every((b) => b.int === 1)).toBe(true);
});

test('company feature actions retain the visit and ticker without inflating page views', async ({ page }) => {
  const beacons = [];
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_language', 'en'));
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/track') {
      beacons.push(JSON.parse(route.request().postData() || '{}'));
      return route.fulfill({ status: 204, body: '' });
    }
    if (path === '/api/auth/me') return route.fulfill({ status: 401, json: {} });
    return route.fulfill({ json: { ok: true, items: [], points: [], securities: { UZTL: { name: 'Uzbektelecom' } } } });
  });
  await page.goto('/company/UZTL?utm_source=telegram');
  const tabs = page.locator('.company-page-tabs');
  await tabs.getByRole('button', { name: 'Financials', exact: true }).click();
  await expect.poll(() => beacons.filter(b => b.event === 'feature_financials').length).toBe(1);
  await tabs.getByRole('button', { name: 'Financials', exact: true }).click();
  await tabs.getByRole('button', { name: 'Dividends', exact: true }).click();
  await expect.poll(() => beacons.filter(b => b.event === 'feature_dividends').length).toBe(1);
  const first = beacons.find(b => !b.event);
  expect(first.tv).toBe(2);
  expect(beacons.filter(b => !b.event)).toHaveLength(1);
  expect(beacons.filter(b => b.event === 'feature_financials')).toHaveLength(1);
  for (const action of beacons.filter(b => b.event?.startsWith('feature_'))) {
    expect(action).toMatchObject({ vid: first.vid, sid: first.sid, path: '/company/UZTL', ticker: 'UZTL', tv: 2 });
    expect(action.us).toBeUndefined();
  }
});

test('meaningful clicks record repeat use and keyboard activation without field contents', async ({ page }) => {
  const beacons = [];
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_language', 'en'));
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/track') {
      beacons.push(JSON.parse(route.request().postData() || '{}'));
      return route.fulfill({ status: 204, body: '' });
    }
    if (path === '/api/auth/me') return route.fulfill({ status: 401, json: {} });
    return route.fulfill({ json: { ok: true, items: [], points: [], securities: { UZTL: { name: 'Uzbektelecom' } } } });
  });
  await page.goto('/company/UZTL');
  const tabs = page.locator('.company-page-tabs');
  await tabs.getByRole('button', { name: 'Financials', exact: true }).click();
  await tabs.getByRole('button', { name: 'Financials', exact: true }).click();
  await tabs.getByRole('button', { name: 'Dividends', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect.poll(() => beacons.filter(b => b.event === 'ui_click').length).toBe(3);
  const clicks = beacons.filter(b => b.event === 'ui_click');
  expect(clicks.map(b => b.val)).toEqual(['financials', 'financials', 'dividends']);
  for (const click of clicks) expect(click).toMatchObject({ ctl: 'company_tab', ticker: 'UZTL', path: '/company/UZTL', tv: 2 });
  await page.evaluate(() => {
    const input = document.createElement('input');
    input.type = 'password'; input.value = 'private-typed-secret';
    input.setAttribute('data-track-control', 'company_tab'); input.setAttribute('data-track-value', 'financials');
    document.body.append(input);
  });
  await page.locator('input[type=password]').click();
  await page.locator('input[type=password]').fill('private@example.test');
  // A known button with an unapproved value still never exports its text or value.
  await page.evaluate(() => {
    const button = document.createElement('button');
    button.textContent = 'private@example.test';
    button.setAttribute('data-track-control', 'company_tab'); button.setAttribute('data-track-value', 'private@example.test');
    button.id = 'privacy-probe'; document.body.append(button);
  });
  await page.locator('#privacy-probe').click();
  await expect.poll(() => beacons.filter(b => b.event === 'ui_click').length).toBe(4);
  expect(beacons.filter(b => !b.event)).toHaveLength(1);
  expect(JSON.stringify(beacons)).not.toContain('private');
});

test('named selections and public navigation omit search queries and external destinations', async ({ page }) => {
  const beacons = [];
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_language', 'en'));
  await page.route('**/api/**', async route => {
    if (new URL(route.request().url()).pathname === '/api/track') {
      beacons.push(JSON.parse(route.request().postData() || '{}'));
      return route.fulfill({ status: 204, body: '' });
    }
    return route.fulfill({ json: { ok: true, items: [], points: [], securities: {} } });
  });
  await page.goto('/market');
  await page.evaluate(() => {
    const select = document.createElement('select');
    select.id = 'scope-probe'; select.dataset.trackControl = 'finance_scope';
    select.innerHTML = '<option value="separate">Separate</option><option value="consolidated">Consolidated</option><option value="secret@example.com">Private</option>';
    document.body.append(select);
    for (const [id, href] of [['public-probe','/company/HMKB?token=private'], ['external-probe','https://other.test/private']]) {
      const a = document.createElement('a'); a.id = id; a.href = href; a.textContent = 'private';
      a.onclick = e => e.preventDefault(); document.body.append(a);
    }
  });
  await page.locator('#scope-probe').selectOption('consolidated');
  await page.locator('#scope-probe').selectOption('secret@example.com');
  await page.locator('#public-probe').click();
  await page.locator('#external-probe').click();
  await expect.poll(() => beacons.filter(b => b.event === 'ui_click').length).toBe(3);
  const clicks = beacons.filter(b => b.event === 'ui_click');
  expect(clicks[0]).toMatchObject({ ctl: 'finance_scope', val: 'consolidated' });
  expect(clicks[1].val).toBeUndefined();
  expect(clicks[2]).toMatchObject({ ctl: 'navigation', dest: '/company/HMKB' });
  expect(JSON.stringify(clicks)).not.toMatch(/private|secret|other.test/);
});
