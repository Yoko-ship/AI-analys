import { test, expect } from "@playwright/test";

// ТЗ 12.10.2026, задача 3: six cards had no «За период» block at all. The block
// was drawn only when the window's high stood above its low, so a year with ONE
// session (ORFIP, PLSTP) lost its turnover, volume and VWAP with the range bar,
// and a year with none (DRBK, INFB) said nothing about why the block was missing.

const metric = (value) => ({ value, status: value == null ? "no_data" : "ok" });
const windowOf = (points, close, turnover, volume, day) => ({
  code: "1y", label: "за 12 мес.", points,
  vwap: metric(volume ? turnover / volume : null),
  min_close: metric(close), max_close: metric(close), mean_close: metric(close),
  turnover: metric(points ? turnover : null), volume: metric(points ? volume : null),
  first_date: day, last_date: day,
});

async function openCard(page, ticker, window) {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.route("**/api/**", (route) => {
    const p = new URL(route.request().url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    const security = { name: ticker, company_name: ticker, security_type: "stock", last_price: 1000, close_price: 1000 };
    if (p === "/api/securities") return json({ ok: true, securities: { [ticker]: security } });
    if (p === "/api/market/stocks") return json({ stocks: [{ ticker, isin: "UZ0000000009", name: ticker,
      last_price: 1000, close_price: 1000, last_trade_date: "2026-09-11" }] });
    if (p === `/api/company/${ticker}/metrics`) return json({ ok: true, window, absolute: {}, quality: { candles_enabled: false } });
    if (p === `/api/securities/${ticker}/info`) return json({ ok: true, security });
    if (p === "/api/auth/me") return json({ user: null }, 401);
    return json({});
  });
  await page.goto(`/company/${ticker}`);
  return page.locator('[data-block="range"]').first();
}

test("a year with one session still states what traded in it", async ({ page }) => {
  // ORFIP: one session in the year, 11.09.2026.
  const block = await openCard(page, "ORFIP", windowOf(1, 1000, 250000, 250, "2026-09-11"));
  await expect(block).toBeVisible();
  await expect(block).toContainText("За период");
  await expect(block).toContainText("Средняя цена");
  await expect(block).toContainText("2026-09-11");
});

test("a year with no session says so instead of vanishing", async ({ page }) => {
  // DRBK: last trade 31.10.2019.
  const block = await openCard(page, "DRBK", windowOf(0, null, null, null, null));
  await expect(block).toBeVisible();
  await expect(block).toContainText("Сделок за период не было");
});
