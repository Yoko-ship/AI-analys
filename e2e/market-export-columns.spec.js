import { test, expect } from "@playwright/test";

// The board's export must carry exactly the columns the reader has on screen —
// a column switched off in «Колонки» is absent from the file, and the file
// follows the board's column order.
import {openBoard, stocks, row} from "./helpers/market-board.js";

for (const [lang, equityLabel, psText, equityText] of [
  ['ru', 'Капитал/Активы', /капитализаци.*выручк/i, /собственн.*капитал.*актив/i],
  ['en', 'Equity/Assets', /capitalisation.*revenue/i, /equity.*assets/i],
  ['uz', 'Kapital/Aktivlar', /kapitalizatsiya.*tushum/i, /kapital.*aktiv/i],
]) {
  test(`mobile column picker explains P/S and Equity/Assets (${lang})`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(language => localStorage.setItem('uz_stock_analyzer_language', language), lang);
    await openBoard(page, ['ps', 'eqAssets']);
    // The same glossary must serve both the header and the picker.
    for (const key of ['ps', 'eqAssets']) {
      await expect(page.locator(`th[data-sort-key="${key}"] .term-info-btn`)).toHaveCount(1);
    }
    await page.locator('.market-secondary > summary').click();
    await page.locator('.market-cols-btn').click();
    const picker = page.locator('.market-cols-dropdown');
    const search = picker.locator('.market-cols-search input');
    for (const [label, description] of [['P/S', psText], [equityLabel, equityText]]) {
      await search.fill(label);
      const option = picker.locator('.market-cols-row').filter({ has: page.getByText(label, { exact: true }) });
      const checkbox = option.getByRole('checkbox');
      await expect(checkbox).toBeChecked();
      await option.locator('.term-info-btn').click();
      const tip = page.getByRole('tooltip');
      await expect(tip).toBeVisible();
      await expect(tip).toContainText(description);
      await expect(checkbox).toBeChecked();
      const box = await tip.boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(390);
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.y + box.height).toBeLessThanOrEqual(844);
      await page.keyboard.press('Escape');
      await expect(tip).toBeHidden();
    }
    if (lang === 'ru') {
      await search.clear();
      const group = picker.locator('.market-cols-group').filter({ hasText: 'Мультипликаторы' });
      await group.locator('.market-cols-group-head').click();
      // Future columns added to this group must also have a definition.
      for (const option of await group.locator('.market-cols-row:not(.market-cols-all)').all()) {
        await expect(option.locator('.term-info-btn')).toHaveCount(1);
      }
    }
  });
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


for (const admin of [false, true]) test(`incomplete trade statistics stay off the market page (${admin ? "admin" : "visitor"})`, async ({ page }) => {
  await openBoard(page, ["date"], { partial: true, trade_date: "20261105", withheld: [{ ticker: "UZMK", isin: "UZ7021720006" }] },
    "2026-11-06T04:32:43Z", [stocks[0], { ...row("UZMK", 8640, 8799, 107598373.03),
      isin: "UZ7021720006", quantity: 12389, trade_count: null, last_trade_date: "2026-11-05" }], { admin });
  await expect(page.getByTestId("market-last-update").locator("time")).toHaveAttribute("datetime", "2026-11-06T04:32:43Z");
  await expect(page.getByText(/Статистика сделок неполная/)).toHaveCount(0);
  await expect(page.getByText(/Официальные дневные котировки обновляются независимо/)).toHaveCount(0);
  await expect(page.getByText(/сохранены данные с прежней датой/)).toHaveCount(0);
  const stock = page.locator(".market-table tbody tr").filter({ hasText: "UZMK" });
  await expect(stock).toContainText(/8\s*640/);
  await expect(stock).toContainText("2026-11-05");
  await expect(page.locator(".market-table tbody tr")).toHaveCount(2);
  await page.getByRole("button", { name: "Карта", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("market-last-update")).toBeVisible();
  await expect(page.getByText(/Статистика сделок неполная/)).toHaveCount(0);
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
