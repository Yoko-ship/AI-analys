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
      value: offset === 300 ? 1_600_000_000 : 10_000_000 + (offset % 31) * 500_000,
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
  const chart = page.locator(".ac-svg");
  const range = page.getByTestId("ac-visible-range");
  await expect(chart).toBeVisible();
  await expect(range).toContainText("Ctrl + колесо");

  const volume = await page.locator(".ac-volume-bar").evaluateAll((bars) => ({
    maxHeight: Math.max(...bars.map((bar) => Number(bar.getAttribute("height")))),
    minHeight: Math.min(...bars.map((bar) => Number(bar.getAttribute("height")))),
    opacity: [...new Set(bars.map((bar) => bar.getAttribute("fill-opacity")))],
  }));
  expect(volume.maxHeight).toBeGreaterThanOrEqual(95);
  expect(volume.minHeight).toBeGreaterThanOrEqual(2.5);
  expect(volume.opacity).toEqual(["0.76"]);

  const chartWorkspace = page.locator(".advanced-chart");
  await page.getByRole("button", { name: "Развернуть график на весь экран" }).click();
  await expect(chartWorkspace).toHaveClass(/is-fullscreen/);
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
  const initialCandles = await page.locator(".ac-candle").count();
  expect(initialCandles).toBeGreaterThan(150);

  const box = await chart.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.45);
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -320);
  await page.keyboard.up("Control");

  await expect.poll(() => page.locator(".ac-candle").count()).toBeLessThan(initialCandles);
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
  await expect(page.locator(".ac-candle")).toHaveCount(initialCandles);
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
