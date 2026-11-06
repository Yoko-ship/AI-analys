import { test, expect } from "@playwright/test";

// The board's export must carry exactly the columns the reader has on screen —
// a column switched off in «Колонки» is absent from the file, and the file
// follows the board's column order.
const day = "2026-09-25";
const row = (ticker, price, prev, volume) => ({
  ticker, type: "stock", isin: `UZ${ticker}`, name: `${ticker} issuer`, last_price: price, close_price: prev,
  volume, quantity: 1000, trade_count: 4, last_trade_date: day, industry: "finance",
});
const stocks = [row("AGBA", 1000, 900, 1e6), row("KVTS", 3000, 3100, 3e6)];

async function openBoard(page, cols, validation = null, refreshedAt = null, boardStocks = stocks) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript((saved) => {
    sessionStorage.setItem("uz_sponsor_seen", "1");
    localStorage.setItem("uz_track_internal", "1");
    localStorage.setItem("uz_market_cols_v3", JSON.stringify(saved));
    localStorage.removeItem("uz_market_col_order_v2");
    localStorage.removeItem("uz_market_pinned_cols");
  }, cols);
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === "/api/companies") return json({ companies: boardStocks.map((r) => ({ ticker: r.ticker, company_name: r.name, sector: r.industry })) });
    if (url.pathname === "/api/securities") return json({ ok: true, securities: Object.fromEntries(boardStocks.map((r) => [r.ticker, { ...r, security_type: "stock" }])) });
    if (url.pathname === "/api/market/stocks") return json({ stocks: boardStocks, updated_at: "2026-11-05T05:00:00Z" });
    if (url.pathname === "/api/market/trade-stats") return json({ ok: true, stats: {}, validation,
      refreshed_at: "2026-11-05T04:30:00Z", quotes_refreshed_at: refreshedAt });
    if (url.pathname === "/api/market/financials") return json({ ok: true, financials: {} });
    if (url.pathname === "/api/market/multiples") return json({ ok: true, items: [] });
    if (url.pathname === "/api/auth/me") return json({ user: null }, 401);
    return json({ ok: true });
  });
  await page.goto("/market");
  await expect(page.locator(".market-table tbody tr")).toHaveCount(boardStocks.length);
  return errors;
}

async function exportedTable(page) {
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /Экспорт CSV/ }).click(),
  ]);
  const text = (await (await download.createReadStream()).toArray()).join("");
  const lines = text.replace(/^﻿/, "").split("\r\n");
  const at = lines.findIndex((l) => l.startsWith("Тикер;"));
  return lines.slice(at).map((l) => l.split(";"));
}

test("export carries only the columns shown on the board", async ({ page }) => {
  const errors = await openBoard(page, ["volume", "open", "date"]);
  // Header cells carry a grip, an info mark and a sort arrow around the label, and CSS uppercases it.
  const screen = (await page.locator(".market-table thead th").allInnerTexts()).map((t) => t.split("\n").find((l) => /\p{L}{2}/u.test(l)).toLowerCase());
  expect(screen).toHaveLength(2 + 4); // ticker, company + Последняя + three chosen

  let [header, first] = await exportedTable(page);
  expect(header).toEqual(["Тикер", "Компания", "Последняя", "Открытие", "Дата сделки", "Объём"]);
  expect(header.slice(2).map((h) => h.toLowerCase())).toEqual(screen.slice(2));
  expect(first.slice(0, 2)).toEqual(["AGBA", "AGBA issuer"]);
  expect(first).toHaveLength(header.length);

  // Switch one column off in the picker: the next export drops it as well.
  await page.getByRole("button", { name: /Колонки/ }).click();
  await page.getByRole("checkbox", { name: /^Открытие/ }).uncheck();
  await page.keyboard.press("Escape");
  [header] = await exportedTable(page);
  expect(header).toEqual(["Тикер", "Компания", "Последняя", "Дата сделки", "Объём"]);
  expect(header).not.toContain("ISIN");
  expect(header).not.toContain("P/E");
  expect(errors).toEqual([]);
});


test("incomplete trade statistics do not hide the official daily quote", async ({ page }) => {
  await openBoard(page, ["date"], { partial: true, trade_date: "20261105", withheld: [{ ticker: "UZMK", isin: "UZ7021720006" }] },
    "2026-11-06T04:32:43Z", [stocks[0], { ...row("UZMK", 8640, 8799, 107598373.03),
      isin: "UZ7021720006", quantity: 12389, trade_count: null, last_trade_date: "2026-11-05" }]);
  await expect(page.getByText(/Статистика сделок неполная.*UZMK/)).toBeVisible();
  await expect(page.getByText(/Официальные дневные котировки обновляются независимо/)).toBeVisible();
  await expect(page.getByText(/сохранены данные с прежней датой/)).toHaveCount(0);
  const stock = page.locator(".market-table tbody tr").filter({ hasText: "UZMK" });
  await expect(stock).toContainText(/8\s*640/);
  await expect(stock).toContainText("2026-11-05");
  await expect(page.locator(".market-table tbody tr")).toHaveCount(2);
});

test("readers see the successful quote update, not a newer mirror timestamp", async ({ page }) => {
  await openBoard(page, ["date"], null, "2026-11-03T16:31:00Z");
  const status = page.getByTestId("market-last-update");
  await expect(status).toContainText("Последнее обновление котировок");
  await expect(status.locator("time")).toHaveAttribute("datetime", "2026-11-03T16:31:00Z");
  await expect(status).toContainText("21:31"); // Tashkent, independent of browser timezone
  await expect(status).toContainText("2026");
  await page.getByRole("button", { name: "Карта", exact: true }).click();
  await expect(status).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(status).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("missing collection time is explicit even if the mirror has refreshed", async ({ page }) => {
  await openBoard(page, ["date"]);
  const status = page.getByTestId("market-last-update");
  await expect(status).toContainText("Время обновления котировок неизвестно");
  await expect(status.locator("time")).toHaveCount(0);
});

for (const width of [1024, 1440, 2512]) {
  test(`market filters use available width without a blank column at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.addInitScript(theme => localStorage.setItem('uz_stock_analyzer_theme', theme), width === 1440 ? 'light' : 'dark');
    await openBoard(page, ["volume", "date"]);
    // Measure both groups in one frame, including during the board's entrance.
    const [types, filters] = await page.evaluate(() => ['.market-type-control', '.market-secondary-controls']
      .map(selector => document.querySelector(selector).getBoundingClientRect().toJSON()));
    expect(filters.x - (types.x + types.width)).toBeGreaterThanOrEqual(0);
    expect(filters.x - (types.x + types.width)).toBeLessThanOrEqual(16);
    expect(Math.abs(filters.y - types.y)).toBeLessThanOrEqual(2);
    for (const selector of ['.market-export-btn', '.market-cols-btn']) {
      const box = await page.locator(selector).boundingBox();
      expect(box.x + box.width).toBeLessThanOrEqual(width);
    }
    await page.locator('.market-filterbar').screenshot({ path: testInfo.outputPath(`market-toolbar-${width}.png`) });
  });
}
