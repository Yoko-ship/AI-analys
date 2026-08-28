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
const PEER = {
  name: "Aloqabank",
  company_name: "Aloqabank",
  security_type: "stock",
  last_price: 9400,
  close_price: 9200,
  industry: "Banks",
};

function priceHistory() {
  const out = [];
  const end = new Date();
  end.setUTCHours(0, 0, 0, 0);
  let price = 6100;
  for (let offset = 1800; offset >= 0; offset -= 1) {
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
      value: 10_000_000 + (offset % 31) * 500_000,
    });
  }
  return out.reverse();
}

test("the company overview chart zooms, pans through history, and resets", async ({ page }, testInfo) => {
  const runtimeErrors = [];
  let requestedMonths = null;
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
    if (p === "/api/securities") return json({ ok: true, securities: { [TICKER]: SECURITY, ALKB: PEER } });
    if (p === "/api/market/stocks") return json({ stocks: [
      { ticker: TICKER, name: SECURITY.name, last_price: 8200, close_price: 8100, market_cap: 20_000_000_000, sector: "Banks" },
      { ticker: "ALKB", name: PEER.name, last_price: 9400, close_price: 9200, market_cap: 12_000_000_000, sector: "Banks" },
    ] });
    if (p === `/api/price-history/${TICKER}`) {
      requestedMonths = url.searchParams.get("months");
      return json({ ok: true, points: history, adjustments: [] });
    }
    if (p === "/api/quotes/series") return json({ ok: true, series: {
      ALKB: [...history].reverse().map((point) => [point.date, point.close * 1.12, point.value * 0.7]),
    } });
    if (p === `/api/company/${TICKER}/metrics`) return json({ ok: true, quality: { candles_enabled: true } });
    if (p === `/api/securities/${TICKER}/info`) return json({ ok: true, security: SECURITY });
    if (p === "/api/auth/me") return json({ user: null }, 401);
    return json({});
  });

  await page.goto(`/company/${TICKER}`);
  const chart = page.locator(".company-price-chart-svg");
  const range = page.getByTestId("company-visible-range");
  await expect(chart).toBeVisible();
  await expect(range).toContainText("Ctrl + колесо");
  await expect.poll(() => requestedMonths).toBe("240");

  const initial = await range.evaluate((el) => ({
    from: el.dataset.from,
    to: el.dataset.to,
  }));
  expect(initial.from > history[history.length - 1].date).toBeTruthy();

  // Every reference-style toolbar button controls a real chart behavior.
  const intervalTool = page.getByTestId("company-chart-interval");
  await intervalTool.click();
  await page.getByRole("menuitemradio", { name: /Неделя/ }).click();
  await expect(chart).toHaveAttribute("data-chart-interval", "W");
  await intervalTool.click();
  await page.getByRole("menuitemradio", { name: /День/ }).click();
  await expect(chart).toHaveAttribute("data-chart-interval", "D");

  const cursorTool = page.getByTestId("company-chart-cursor");
  await expect(cursorTool).toHaveAttribute("aria-pressed", "true");
  await cursorTool.click();
  await expect(cursorTool).toHaveAttribute("aria-pressed", "false");
  await cursorTool.click();

  const typeTool = page.getByTestId("company-chart-type");
  await typeTool.click();
  await page.getByRole("menuitemradio", { name: "Свечи" }).click();
  await expect(chart).toHaveAttribute("data-chart-type", "candle");
  expect(await page.locator(".cpc-candle").count()).toBeGreaterThan(20);
  await typeTool.click();
  await page.getByRole("menuitemradio", { name: "Область" }).click();
  await expect(page.locator(".cpc-area-fill")).toBeVisible();

  await page.getByTestId("company-chart-compare").click();
  const peer = page.getByRole("menuitemcheckbox", { name: /Aloqabank/ });
  await expect(peer).toBeVisible();
  await peer.click();
  await expect(page.locator(".cpc-compare-path")).toBeVisible();
  await peer.click();
  await expect(page.locator(".cpc-compare-path")).toHaveCount(0);

  const boxForDrawing = await chart.boundingBox();
  expect(boxForDrawing).not.toBeNull();
  await page.getByTestId("company-chart-draw").click();
  await chart.click({ position: { x: boxForDrawing.width * 0.30, y: boxForDrawing.height * 0.40 } });
  await chart.click({ position: { x: boxForDrawing.width * 0.65, y: boxForDrawing.height * 0.58 } });
  await expect(page.locator(".cpc-drawing-line")).toBeVisible();
  await page.getByRole("button", { name: "Очистить" }).click();
  await expect(page.locator(".cpc-drawing-line")).toHaveCount(0);

  await page.getByTestId("company-chart-indicators").click();
  await page.getByRole("menuitemcheckbox", { name: /MA20/ }).click();
  await expect(page.locator(".cpc-ma20")).toBeVisible();

  await page.getByTestId("company-chart-settings").click();
  const menuShot = testInfo.outputPath("company-chart-toolbar-menu.png");
  await page.screenshot({ path: menuShot, fullPage: false });
  await testInfo.attach("company-chart-toolbar-menu", { path: menuShot, contentType: "image/png" });
  const gridSetting = page.getByLabel("Сетка");
  await gridSetting.uncheck();
  await expect(page.locator(".cpc-grid-line")).toHaveCount(0);
  await gridSetting.check();
  await expect.poll(() => page.locator(".cpc-grid-line").count()).toBeGreaterThan(0);
  await page.keyboard.press("Escape");

  const box = await chart.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.45);
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -320);
  await page.keyboard.up("Control");

  await expect(page.getByRole("button", { name: "Сбросить" })).toBeVisible();
  await expect.poll(async () => range.getAttribute("data-from")).not.toBe(initial.from);
  const zoomedFrom = await range.getAttribute("data-from");

  // Pulling the chart right moves the viewport to older sessions.
  await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.45);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.70, box.y + box.height * 0.45, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => range.getAttribute("data-from")).not.toBe(zoomedFrom);
  expect((await range.getAttribute("data-from")) < zoomedFrom).toBeTruthy();

  const desktopShot = testInfo.outputPath("company-chart-history-desktop.png");
  await page.screenshot({ path: desktopShot, fullPage: true });
  await testInfo.attach("company-chart-history-desktop", { path: desktopShot, contentType: "image/png" });

  await page.getByRole("button", { name: "Сбросить" }).click();
  await expect(range).toHaveAttribute("data-from", initial.from);
  await expect(range).toHaveAttribute("data-to", initial.to);
  await page.getByTitle("Светлая").click();
  await expect(page.locator("body")).toHaveAttribute("data-theme", "light");
  const lightShot = testInfo.outputPath("company-chart-history-light.png");
  await page.screenshot({ path: lightShot, fullPage: false });
  await testInfo.attach("company-chart-history-light", { path: lightShot, contentType: "image/png" });
  await page.getByTitle("Тёмная").click();

  // Hourly presets retain their established session behavior and do not claim
  // that the daily archive can be panned at the same density.
  await page.getByRole("button", { name: "1Н", exact: true }).click();
  await expect(range).toHaveCount(0);
  await page.getByRole("button", { name: "1М", exact: true }).click();
  await expect(range).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  const mobileShot = testInfo.outputPath("company-chart-history-mobile.png");
  await page.screenshot({ path: mobileShot, fullPage: true });
  await testInfo.attach("company-chart-history-mobile", { path: mobileShot, contentType: "image/png" });
  expect(runtimeErrors).toEqual([]);
});
