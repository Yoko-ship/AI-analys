import { test, expect } from "@playwright/test";

const TICKER = "UNVB";
const SECURITY = {
  name: "Universal Bank",
  company_name: "Universal Bank",
  security_type: "stock",
  last_price: 8200,
  close_price: 8200,
  industry: "Banks",
};

function priceHistory() {
  const out = [];
  const end = new Date();
  end.setUTCHours(0, 0, 0, 0);
  let price = 6100;
  for (let offset = 1450; offset >= 0; offset -= 1) {
    const day = new Date(end.getTime() - offset * 864e5);
    if (day.getUTCDay() === 0 || day.getUTCDay() === 6) continue;
    price *= 1 + ((((offset * 37) % 15) - 7) / 1000);
    const open = price * (1 + ((((offset * 17) % 7) - 3) / 1000));
    out.push({
      date: day.toISOString().slice(0, 10),
      open,
      high: Math.max(open, price) * 1.012,
      low: Math.min(open, price) * 0.988,
      close: price,
      // One genuine-looking spike keeps the regression honest: ordinary
      // sessions still need to remain visible next to the largest turnover.
      value: offset % 47 === 0 ? 0 : offset === 300 ? 1_600_000_000 : 10_000_000 + (offset % 31) * 500_000,
    });
  }
  return out;
}

test("candle history zooms with Ctrl+wheel, pans by mouse, and resets", async ({ page }, testInfo) => {
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(message.text());
  });
  const history = priceHistory();
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    const json = (body, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
    if (p === "/api/securities") return json({ ok: true, securities: { [TICKER]: SECURITY } });
    if (p === `/api/price-history/${TICKER}`) return json({ ok: true, points: history, adjustments: [] });
    if (p === `/api/company/${TICKER}/metrics`) return json({ ok: true, quality: { candles_enabled: true } });
    if (p === `/api/securities/${TICKER}/info`) return json({ ok: true, security: SECURITY });
    if (p === "/api/auth/me") return json({ user: null }, 401);
    return json({});
  });

  await page.goto(`/chart/${TICKER}?type=candle&range=1y`);
  const chart = page.locator(".ac-canvas");
  const range = page.getByTestId("ac-visible-range");
  // The canvas has no DOM per bar; the wrapper states what is drawn on it.
  const bars = async () => Number(await chart.getAttribute("data-visible-bars"));
  await expect(chart).toBeVisible();
  await expect(range).toContainText("Ctrl + колесо");
  const advancedTools = page.getByTestId("advanced-chart-tool-strip");
  await expect(advancedTools).toBeVisible();
  await expect(advancedTools.locator("button")).toHaveCount(7);

  // Volume has its own pane under the price.
  await expect(chart).toHaveAttribute("data-series", /(^|,)volume(,|$)/);
  await expect(chart).toHaveAttribute("data-panes", "2");

  const chartWorkspace = page.locator(".advanced-chart");
  await page.getByRole("button", { name: "Развернуть график на весь экран" }).click();
  await expect(chartWorkspace).toHaveClass(/is-fullscreen/);
  await expect(advancedTools).toBeVisible();
  await expect(page.locator(".topbar")).toBeHidden();
  const fullscreenBox = await chartWorkspace.boundingBox();
  const viewport = page.viewportSize();
  expect(fullscreenBox).not.toBeNull();
  expect(Math.abs(fullscreenBox.width - viewport.width)).toBeLessThanOrEqual(1);
  expect(Math.abs(fullscreenBox.height - viewport.height)).toBeLessThanOrEqual(1);
  await page.keyboard.press("Escape");
  await expect(chartWorkspace).not.toHaveClass(/is-fullscreen/);
  await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");

  const initial = await range.evaluate((el) => ({
    from: el.dataset.from,
    to: el.dataset.to,
  }));
  await expect(chart).toHaveAttribute("data-chart-type", "candle");
  const initialCandles = await bars();
  expect(initialCandles).toBeGreaterThan(150);

  const box = await chart.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.45);
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -320);
  await page.keyboard.up("Control");

  await expect.poll(bars).toBeLessThan(initialCandles);
  await expect(page.getByRole("button", { name: "Сбросить" })).toBeVisible();

  const zoomed = await range.evaluate((el) => ({
    from: el.dataset.from,
    to: el.dataset.to,
  }));
  expect(zoomed.from).not.toBe(initial.from);

  // Pull the plotted paper to the right: the viewport moves to older sessions.
  await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.45);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.70, box.y + box.height * 0.45, { steps: 8 });
  await page.mouse.up();

  await expect.poll(async () => range.getAttribute("data-from")).not.toBe(zoomed.from);
  const pannedFrom = await range.getAttribute("data-from");
  expect(pannedFrom < zoomed.from).toBeTruthy();
  const desktopShot = testInfo.outputPath("candle-history-desktop.png");
  await page.screenshot({ path: desktopShot, fullPage: true });
  await testInfo.attach("candle-history-desktop", { path: desktopShot, contentType: "image/png" });

  await page.getByRole("button", { name: "Сбросить" }).click();
  await expect(range).toHaveAttribute("data-from", initial.from);
  await expect(range).toHaveAttribute("data-to", initial.to);
  await expect.poll(bars).toBe(initialCandles);

  // Line/area/baseline use the same movable viewport as candles. This was
  // previously wired only to candle mode, leaving the line frozen in place.
  await page.locator('.ac-type-btn[aria-label="Линия"]').click();
  await expect(chart).toHaveAttribute("data-chart-type", "line");
  const lineFrom = await range.getAttribute("data-from");
  const lineBox = await chart.boundingBox();
  await page.mouse.move(lineBox.x + lineBox.width * 0.4, lineBox.y + lineBox.height * 0.45);
  await page.mouse.down();
  await page.mouse.move(lineBox.x + lineBox.width * 0.7, lineBox.y + lineBox.height * 0.45, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => range.getAttribute("data-from")).not.toBe(lineFrom);

  // The compact expanded-view strip remains interactive: drawing mode owns
  // pointer clicks instead of accidentally starting the history-pan gesture.
  const drawTool = advancedTools.getByRole("button", { name: "Линия тренда" });
  await advancedTools.getByRole("button", { name: "Сравнить" }).click();
  await expect(advancedTools.locator(".ac-menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(advancedTools.locator(".ac-menu")).toHaveCount(0);
  await drawTool.click();
  await page.mouse.move(lineBox.x + lineBox.width * 0.30, lineBox.y + lineBox.height * 0.35);
  await page.waitForTimeout(50);
  await page.mouse.click(lineBox.x + lineBox.width * 0.30, lineBox.y + lineBox.height * 0.35);
  await page.mouse.move(lineBox.x + lineBox.width * 0.68, lineBox.y + lineBox.height * 0.55);
  await page.waitForTimeout(50);
  await page.mouse.click(lineBox.x + lineBox.width * 0.68, lineBox.y + lineBox.height * 0.55);
  await expect(chart).toHaveAttribute("data-trend-points", "2");
  await page.getByTitle("Светлая").click();
  await expect(page.locator("body")).toHaveAttribute("data-theme", "light");
  const lightShot = testInfo.outputPath("candle-history-light.png");
  await page.screenshot({ path: lightShot, fullPage: false });
  await testInfo.attach("candle-history-light", { path: lightShot, contentType: "image/png" });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(chart).toBeVisible();
  await expect(range).toBeVisible();
  await expect(page.locator(".advanced-chart")).not.toHaveClass(/rail-open/);
  await page.locator(".ac-rail-toggle").click();
  await expect(page.locator(".advanced-chart")).toHaveClass(/rail-open/);
  await page.locator(".ac-rail-toggle").click();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  const mobileShot = testInfo.outputPath("candle-history-mobile.png");
  await page.screenshot({ path: mobileShot, fullPage: true });
  await testInfo.attach("candle-history-mobile", { path: mobileShot, contentType: "image/png" });
  expect(runtimeErrors).toEqual([]);
});

test("advanced chart menu renders every extended chart type", async ({ page }) => {
  const history = priceHistory();
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/securities") return json({ ok: true, securities: { [TICKER]: SECURITY } });
    if (path === `/api/price-history/${TICKER}`) return json({ ok: true, points: history, adjustments: [] });
    if (path === `/api/company/${TICKER}/metrics`) return json({ ok: true, quality: { candles_enabled: true } });
    if (path === `/api/securities/${TICKER}/info`) return json({ ok: true, security: SECURITY });
    if (path === "/api/auth/me") return json({ user: null }, 401);
    return json({});
  });
  await page.goto(`/chart/${TICKER}?type=line&range=1y`);
  const tools = page.getByTestId("advanced-chart-tool-strip");
  const choose = async (name) => {
    await tools.getByRole("button", { name: "Вид графика" }).click();
    await tools.getByRole("button", { name, exact: true }).click();
  };
  await tools.getByRole("button", { name: "Вид графика" }).click();
  await expect(tools.locator(".ac-menu-item")).toHaveCount(10);
  await tools.getByRole("button", { name: "Вид графика" }).click();
  const chart = page.locator(".ac-canvas");
  for (const [name, type] of [["Бары", "bars"], ["Колонки", "columns"], ["Хейкин Аши", "heikin_ashi"],
    ["Ренко", "renko"], ["Каги", "kagi"], ["Крестики-нолики", "point_figure"]]) {
    await choose(name);
    await expect(chart).toHaveAttribute("data-chart-type", type);
    await expect(chart.locator("canvas").first()).toBeVisible();
    if (type !== "bars" && type !== "columns") await expect(page.locator(".ac-synthetic-note")).toBeVisible();
  }
});

test("advanced chart interval rolls sessions up into weeks and months", async ({ page }) => {
  const history = priceHistory();
  await page.route("**/api/**", (route) => {
    const p = new URL(route.request().url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (p === "/api/securities") return json({ ok: true, securities: { [TICKER]: SECURITY } });
    if (p === `/api/price-history/${TICKER}`) return json({ ok: true, points: history, adjustments: [] });
    if (p === `/api/company/${TICKER}/metrics`) return json({ ok: true, quality: { candles_enabled: true } });
    if (p === `/api/securities/${TICKER}/info`) return json({ ok: true, security: SECURITY });
    if (p === "/api/auth/me") return json({ user: null }, 401);
    return json({});
  });

  await page.goto(`/chart/${TICKER}?type=candle&range=1y`);
  const interval = page.getByTestId("advanced-chart-interval");
  await expect(interval).toHaveText("D");
  const chart = page.locator(".ac-canvas");
  const bars = async () => Number(await chart.getAttribute("data-visible-bars"));
  await expect.poll(bars).toBeGreaterThan(200);

  await interval.click();
  await page.locator(".ac-menu-item", { hasText: "Неделя" }).click();
  await expect(interval).toHaveText("W");
  await expect(page).toHaveURL(/iv=W/);
  await expect(chart).toHaveAttribute("data-chart-interval", "W");
  const weekly = await bars();
  expect(weekly).toBeGreaterThanOrEqual(50);
  expect(weekly).toBeLessThanOrEqual(56);

  await interval.click();
  await page.locator(".ac-menu-item", { hasText: "Месяц" }).click();
  await expect(interval).toHaveText("M");
  await expect(chart).toHaveAttribute("data-chart-interval", "M");
  const monthly = await bars();
  expect(monthly).toBeGreaterThanOrEqual(12);
  expect(monthly).toBeLessThanOrEqual(14);

  // The choice is in the link, so a reload keeps it.
  await page.reload();
  await expect(page.getByTestId("advanced-chart-interval")).toHaveText("M");
});

test("advanced chart draws the same hourly 1Д and 1Н bars as the company chart", async ({ page }) => {
  const history = priceHistory();
  // Seven hourly bars on each of the last two sessions.
  const sessions = history.slice(-2).map((p) => p.date);
  const bars = sessions.flatMap((day) => [10, 11, 12, 13, 14, 15, 16].map((h, i) => ({
    date: `${day}T${String(h).padStart(2, "0")}:00`,
    open: 8000 + i, high: 8010 + i, low: 7990 + i, close: 8005 + i, volume: 100, value: 800_000,
  })));
  const requested = [];
  await page.route("**/api/**", (route) => {
    const p = new URL(route.request().url()).pathname;
    requested.push(p);
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (p === "/api/securities") return json({ ok: true, securities: { [TICKER]: SECURITY } });
    if (p === `/api/price-history/${TICKER}`) return json({ ok: true, points: history, adjustments: [] });
    if (p === `/api/intraday/${TICKER}`) return json({ ok: true, points: bars });
    if (p === `/api/company/${TICKER}/metrics`) return json({ ok: true, quality: { candles_enabled: true } });
    if (p === `/api/securities/${TICKER}/info`) return json({ ok: true, security: SECURITY });
    if (p === "/api/auth/me") return json({ user: null }, 401);
    return json({});
  });

  await page.goto(`/chart/${TICKER}?type=candle&range=1d`);
  await expect(page.getByRole("button", { name: "1Д", exact: true })).toHaveClass(/active/);
  const chart = page.locator(".ac-canvas");
  await expect(chart).toHaveAttribute("data-visible-bars", "7");
  await expect(page.getByTestId("advanced-chart-interval")).toHaveText("1ч");
  await expect(page.getByTestId("advanced-chart-interval")).toBeDisabled();
  await expect(page.getByTestId("ac-visible-range")).toHaveAttribute("data-from", `${sessions[1]}T10:00`);
  expect(requested).toContain(`/api/intraday/${TICKER}`);

  // 1Н: hourly bars for the two banked sessions, daily closes for the rest of the week.
  await page.getByRole("button", { name: "1Н", exact: true }).click();
  await expect.poll(async () => Number(await chart.getAttribute("data-visible-bars"))).toBeGreaterThanOrEqual(16);
  const weekly = Number(await chart.getAttribute("data-visible-bars"));
  expect(weekly).toBeGreaterThanOrEqual(16);
  expect(weekly).toBeLessThanOrEqual(19);
});

test("«Час» draws the stored hourly bars on a longer range, on both charts", async ({ page }) => {
  const history = priceHistory();
  // Seven hourly bars on each of the last ten sessions: all the bank holds.
  const bars = history.slice(-10).flatMap((p) => [10, 11, 12, 13, 14, 15, 16].map((h, i) => ({
    date: `${p.date}T${String(h).padStart(2, "0")}:00`,
    open: 8000 + i, high: 8010 + i, low: 7990 + i, close: 8005 + i, volume: 100, value: 800_000,
  })));
  const asked = [];
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (p === "/api/securities") return json({ ok: true, securities: { [TICKER]: SECURITY } });
    if (p === `/api/price-history/${TICKER}`) return json({ ok: true, points: history, adjustments: [] });
    if (p === `/api/intraday/${TICKER}`) { asked.push(url.searchParams.get("days")); return json({ ok: true, points: bars }); }
    if (p === `/api/company/${TICKER}/metrics`) return json({ ok: true, quality: { candles_enabled: true } });
    if (p === `/api/securities/${TICKER}/info`) return json({ ok: true, security: SECURITY });
    if (p === "/api/auth/me") return json({ user: null }, 401);
    return json({});
  });

  await page.goto(`/chart/${TICKER}?type=candle&range=3m`);
  const interval = page.getByTestId("advanced-chart-interval");
  await interval.click();
  await page.locator(".ac-menu-item", { hasText: "Час" }).click();
  const chart = page.locator(".ac-canvas");
  await expect(chart).toHaveAttribute("data-chart-interval", "H");
  await expect(interval).toHaveText("1ч");
  await expect(page).toHaveURL(/iv=H/);
  await expect(chart).toHaveAttribute("data-visible-bars", "70");
  await expect(page.getByTestId("ac-hourly-note")).toContainText("Часовые бары");
  expect(asked).toContain("60");

  await page.goto(`/company/${TICKER}`);
  await page.getByTestId("company-chart-interval").click();
  await page.getByRole("menuitemradio", { name: /Час/ }).click();
  const company = page.locator(".company-price-chart");
  await expect(company).toHaveAttribute("data-chart-interval", "H");
  await expect(company).toHaveAttribute("data-visible-bars", "70");
  await expect(page.getByTestId("cpc-hourly-note")).toContainText("Часовые бары");
});
