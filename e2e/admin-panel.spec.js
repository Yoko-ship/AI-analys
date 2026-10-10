import { test, expect } from "@playwright/test";

async function mockAdmin(page) {
  await page.addInitScript(() => {
    localStorage.setItem("uz_stock_analyzer_token", "admin-token");
    localStorage.setItem("uz_stock_analyzer_language", "en");
  });
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const send = (body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/auth/me") return send({ user: { id: 1, email: "admin@example.com", full_name: "Admin", is_admin: true } });
    if (path === "/api/admin/overview") return send({ ok: true, catalog: {}, audit: { open: {}, history: [], queue: [], latest: null }, news: {}, streams: [] });
    return send({ ok: true, items: [] });
  });
}

test("admin opens straight on the product tabs, with no second navigation", async ({ page }, testInfo) => {
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await mockAdmin(page);
  await page.goto("/admin");
  const tabs = page.locator(".admin-tabs");
  await expect(tabs.getByRole("button", { name: "Overview" })).toHaveAttribute("aria-current", "page");
  await expect(page.locator(".control-sidebar")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("admin-desktop.png"), fullPage: true });
  await tabs.getByRole("button", { name: "Audience" }).click();
  await expect(page).toHaveURL(/\/admin\/audience$/);
  await tabs.getByRole("button", { name: "AI analysis" }).click();
  await expect(page).toHaveURL(/[/]admin[/]analysis$/);
  await expect(page.getByText("Sector analysis monitoring")).toHaveCount(0);
  await tabs.getByRole("button", { name: "System" }).click();
  await expect(page).toHaveURL(/\/admin\/companies$/);
  const subtabs = page.locator(".admin-subtabs");
  for (const gone of ["Data quality", "Data", "Audit", "Statements", "Rules", "Source"]) await expect(subtabs.getByRole("button", { name: gone, exact: true })).toHaveCount(0);
  await subtabs.getByRole("button", { name: "Collectors" }).click();
  await expect(page).toHaveURL(/\/admin\/streams$/);
  expect(failures).toEqual([]);
});

test("links to removed admin screens land on the overview", async ({ page }) => {
  await mockAdmin(page);
  for (const old of ["/admin/documents", "/admin/audit", "/admin/access", "/admin/product-overview", "/admin/findings", "/admin/quality", "/admin/intake", "/admin/rules", "/admin/source", "/admin/sector-analysis"]) {
    await page.goto(old);
    await expect(page).toHaveURL(/\/admin$/);
    await expect(page.locator(".admin-tabs").getByRole("button", { name: "Overview" })).toHaveAttribute("aria-current", "page");
  }
});

test("the panel fits a phone without sideways scrolling", async ({ page }, testInfo) => {
  await mockAdmin(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin/system");
  await expect(page).toHaveURL(/\/admin\/companies$/);
  await expect(page.locator(".admin-subtabs")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("admin-phone.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

const AUDIENCE = {
  ok: true, days: 30,
  daily: [
    { day: "2026-10-08", visitors: 41, sessions: 52, pageviews: 140, new_visitors: 30, bounce_rate: 0.5, avg_seconds: 40, top_channel: { name: "direct", sessions: 30 }, top_site: null },
    { day: "2026-10-09", visitors: 73, sessions: 90, pageviews: 260, new_visitors: 40, bounce_rate: 0.42, avg_seconds: 80, top_channel: { name: "telegram", sessions: 35 }, top_site: { name: "org.telegram.messenger", sessions: 20 } },
  ],
  totals: { visitors: 96, sessions: 142, pageviews: 400, new_visitors: 70, returning_visitors: 26, pages_per_session: 2.8, avg_session_seconds: 95, bounce_rate: 0.46, engaged_session_seconds: 74 },
  referrers: [{ host: "(direct)", sessions: 60, kind: "direct" }, { host: "google.com", sessions: 30, kind: "search" }],
  channels: [{ channel: "direct", sessions: 60, bounce_rate: 0.5, avg_seconds: 50 }, { channel: "telegram", sessions: 45, bounce_rate: 0.31, avg_seconds: 112 }, { channel: "search", sessions: 30, bounce_rate: 0.62, avg_seconds: 21 }],
  sites: [
    { host: "kun.uz", channel: "referral", sessions: 14, bounce_rate: 0.29, avg_seconds: 88, pages: [{ path: "/news/2026/10/09/uztl", sessions: 6 }] },
    { host: "google.com", channel: "search", sessions: 30, bounce_rate: 0.62, avg_seconds: 21, pages: [] },
    { host: "org.telegram.messenger", channel: "telegram", sessions: 5, bounce_rate: 0.4, avg_seconds: 60, pages: [] },
  ],
  campaigns: [{ source: "telegram", medium: null, campaign: "launch-oct", sessions: 40, bounce_rate: 0.3, avg_seconds: 120 }],
  landings: [{ path: "/market", view: "market", sessions: 80, bounce_rate: 0.4, avg_seconds: 60 }, { path: "/company/UZTL", view: "company", sessions: 20, bounce_rate: 0.2, avg_seconds: 150 }],
  countries: [{ name: "UZ", visitors: 80 }, { name: "RU", visitors: 9 }, { name: "(unknown)", visitors: 7 }],
  cities: [{ name: "Tashkent", country: "UZ", visitors: 60 }, { name: "Samarkand", country: "UZ", visitors: 12 }],
  devices: [{ name: "mobile", visitors: 70 }], screens: [{ name: "380–419", visitors: 50 }], languages: [{ name: "ru", visitors: 80 }], browsers: [{ name: "Chrome", visitors: 60 }], os: [],
  journey: [{ key: "visited", count: 96 }, { key: "security", count: 40 }, { key: "signed_in", count: 9 }, { key: "analysed", count: 4 }],
  quality: { visitors: 96, networks: 81, team_excluded: 3, crowded_networks: [{ network: "a1b2c3", visitors: 6, clients: 2, city: "Tashkent", country: "UZ" }] },
};
const ENGAGEMENT = {
  ok: true, days: 30, views: [{ view: "market", pageviews: 200, visitors: 80 }], tickers: [], news: [], events: [],
  reading: [{ view: "company", measured: 40, avg_seconds: 96, avg_scroll: 71, quick_share: 0.18 }, { view: "market", measured: 150, avg_seconds: 34, avg_scroll: 40, quick_share: 0.44 }],
  exits: [{ path: "/market", view: "market", exits: 70, exit_rate: 0.35 }],
};

for (const [label, size] of [["desktop", { width: 1440, height: 1000 }], ["phone", { width: 390, height: 844 }]]) {
  test(`audience and engagement show sources, places, journey and reading on ${label}`, async ({ page }, testInfo) => {
    await mockAdmin(page);
    await page.route("**/api/admin/metrics/audience*", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(AUDIENCE) }));
    await page.route("**/api/admin/metrics/engagement*", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(ENGAGEMENT) }));
    await page.setViewportSize(size);
    await page.goto("/admin/audience");
    await expect(page.locator(".admin-hbar-name", { hasText: "Telegram" }).first()).toBeVisible();
    await expect(page.getByText("telegram · launch-oct")).toBeVisible();
    await expect(page.getByText("Tashkent, Uzbekistan", { exact: true })).toBeVisible();
    await expect(page.getByText("Ran an AI analysis")).toBeVisible();
    await expect(page.getByText("network a1b2c3 · Tashkent, Uzbekistan")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`audience-${label}.png`), fullPage: true });

    const sites = page.locator("#admin-referring-sites");
    await expect(sites.getByText("/news/2026/10/09/uztl · 6")).toBeVisible();
    await expect(sites.getByText("Telegram app (Android)")).toBeVisible();
    await sites.getByRole("button", { name: "Other sites" }).click();
    await expect(sites.getByText("google.com")).toHaveCount(0);
    await expect(sites.getByText("kun.uz", { exact: true })).toBeVisible();
    // a channel in «Каналы» opens its own sites; one without sites is not a link
    await page.locator(".admin-hbars").first().getByRole("button", { name: "Search engines" }).click();
    await expect(sites.getByText("google.com")).toBeVisible();
    await expect(sites.getByText("kun.uz", { exact: true })).toHaveCount(0);
    await expect(page.locator(".admin-hbars").first().getByRole("button", { name: "Direct" })).toHaveCount(0);
    await sites.screenshot({ path: testInfo.outputPath(`sites-${label}.png`) });

    await page.getByRole("button", { name: "Don't count this browser" }).click();
    expect(await page.evaluate(() => localStorage.getItem("uz_track_internal"))).toBe("1");
    await expect(page.getByRole("button", { name: /not counted/ })).toBeVisible();

    await page.goto("/admin/engagement");
    await expect(page.getByText("How long they read, and where they give up")).toBeVisible();
    await expect(page.getByRole("cell", { name: "1m 36s" })).toBeVisible();
    await expect(page.getByText("Exit pages")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`engagement-${label}.png`), fullPage: true });
  });
}

test("a day opens its own report, from the table or the chart, and the range comes back", async ({ page }, testInfo) => {
  const asked = [];
  await mockAdmin(page);
  await page.route("**/api/admin/metrics/audience*", (route) => {
    const url = new URL(route.request().url());
    asked.push(url.searchParams.get("day"));
    const day = url.searchParams.get("day");
    const body = day
      ? { ...AUDIENCE, day, daily: [AUDIENCE.daily[1]], hourly: Array.from({ length: 24 }, (_, hour) => ({ hour, visitors: hour === 21 ? 9 : hour % 5, pageviews: hour })) }
      : { ...AUDIENCE, day: null, hourly: [] };
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/admin/audience");
  await expect(page.getByRole("heading", { name: "Day by day" })).toBeVisible();
  await expect(page.getByRole("row", { name: /09\.10.*73.*40.*Telegram · Telegram app \(Android\)/ })).toBeVisible();
  await page.getByRole("button", { name: "09.10", exact: true }).click();
  await expect(page.getByText("Report for 09.10.2026")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Visitors by hour" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Day by day" })).toHaveCount(0);
  expect(asked.at(-1)).toBe("2026-10-09");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("day-report.png"), fullPage: true });

  await page.getByRole("button", { name: /back to 30 days/ }).click();
  await expect(page.getByRole("heading", { name: "Visitors by day" })).toBeVisible();
  expect(asked.at(-1)).toBeNull();
  // a bar in the chart is a door to its day too
  await page.locator(".admin-bars .bar.pickable").first().click();
  await expect(page.getByText("Report for 08.10.2026")).toBeVisible();
  // and the date field picks any day
  await page.getByLabel("Pick a day").fill("2026-10-01");
  await expect(page.getByText("Report for 01.10.2026")).toBeVisible();
  expect(asked.at(-1)).toBe("2026-10-01");
});
