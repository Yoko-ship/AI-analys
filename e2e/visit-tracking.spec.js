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
