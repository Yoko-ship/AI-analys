import { test, expect } from "@playwright/test";

const day = "2026-09-25";
const row = (ticker, type, price, prev, volume, quantity, count, industry) => ({
  ticker, type, isin: `UZ${ticker}`, name: `${ticker} issuer`, last_price: price, close_price: prev,
  volume, quantity, trade_count: count, last_trade_date: day, industry,
});
const stocks = [row("AGBA", "stock", 1000, 900, 1e6, 1000, 4, "finance"),
  row("KVTS", "stock", 3000, 3100, 3e6, 1000, 6, "manufacturing"), row("EMPTY", "stock", null, 100, null, null, null, "finance")];
const bonds = [row("BOND1", "bond", 100000, 95000, 8e6, 80, 2, "finance"),
  row("BOND2", "bond", 100000, 99000, 12e6, 120, 3, "manufacturing")];
const all = [...stocks, ...bonds];
const tradeStats = Object.fromEntries(all.filter((r) => r.volume).map((r) => [r.isin, {
  trade_date: "20260925", total_value: r.volume, total_qty: r.quantity, trade_count: r.trade_count,
  avg_price: r.volume / r.quantity, largest_value: r.ticker === "AGBA" ? 700000 : r.volume / 2,
  block_value: r.volume * 2, block_qty: r.quantity * 4, block_count: 2,
}]));
const changes = Object.fromEntries(all.filter((r) => r.volume).map((r) => [r.ticker, {
  "1w": { pct: 12, from: "20260918" }, stats: { "1w": {
    value: r.volume * 10, qty: r.quantity * 2, trades: r.trade_count * 2,
    vwap: r.volume * 10 / (r.quantity * 2), largest_value: r.volume * 4,
    sessions: 5, detail_sessions: 3, from: "20260918", to: "20260925",
  } },
}]));

async function openMap(page, type = "stock") {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => sessionStorage.setItem("uz_sponsor_seen", "1"));
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === "/api/companies") return json({ companies: all.map((r) => ({ ticker: r.ticker, company_name: r.name, sector: r.industry })) });
    if (url.pathname === "/api/securities") return json({ ok: true, securities: Object.fromEntries(all.map((r) => [r.ticker, { ...r, security_type: r.type }])) });
    if (url.pathname === "/api/market/stocks") return json({ stocks: url.searchParams.get("type") === "bond" ? bonds : stocks });
    if (url.pathname === "/api/market/trade-stats") return json({ ok: true, stats: tradeStats });
    if (url.pathname === "/api/market/changes") return json({ ok: true, changes });
    if (url.pathname === "/api/auth/me") return json({ user: null }, 401);
    return json({ ok: true });
  });
  await page.goto("/heatmap");
  if (type === "bond") await page.locator(".market-type-control").getByRole("button", { name: "Облигации", exact: true }).click();
  await page.getByLabel("Бумага на карте").selectOption(type === "bond" ? "BOND1" : "AGBA");
  return errors;
}

const metric = (page, key) => page.locator(`.heatmap-metric-details [data-metric="${key}"] strong`);
for (const type of ["stock", "bond"]) {
  for (const width of [1280, 390]) {
    test(`${type} map exposes all six trading metrics at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      const errors = await openMap(page, type);
      const ticker = type === "bond" ? "BOND1" : "AGBA";
      const expected = type === "bond"
        ? ["8 000 000 UZS", "80 шт", "100 000 UZS", "4 000 000 UZS", "4 000 000 UZS", "40%"]
        : ["1 000 000 UZS", "1 000 шт", "1 000 UZS", "250 000 UZS", "700 000 UZS", "25%"];
      for (const [i, key] of ["volume", "volQty", "avgShare", "avgTrade", "bigTrade", "volShare"].entries()) {
        await expect(metric(page, key)).toHaveText(expected[i]);
      }
      if (width === 1280) await page.locator(".theme-toggle").click();
      const tile = page.locator(`.heatmap-tree-tile[data-ticker="${ticker}"]`);
      await expect(tile).toHaveAttribute("title", /Крупнейшая сделка/);
      if (width === 1280) await expect(tile.locator(".htt-metrics [data-metric]")).toHaveCount(6);
      await page.getByRole("button", { name: /Показатели/ }).click();
      const picker = page.locator(".market-cols-dropdown");
      await expect(picker.getByRole("checkbox")).toHaveCount(7);
      await picker.getByRole("checkbox", { name: type === "bond" ? "Ср. цена облигации" : "Ср. цена акции", exact: true }).uncheck();
      await page.keyboard.press("Escape");
      await expect(metric(page, "avgShare")).toHaveCount(0);
      await page.getByRole("button", { name: /Показатели/ }).click();
      await picker.getByRole("checkbox", { name: "Все", exact: true }).check();
      await page.screenshot({ path: testInfo.outputPath("metric-picker.png"), fullPage: false });
      await page.keyboard.press("Escape");
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: testInfo.outputPath("map-metrics.png"), fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.locator(".heatmap-focus-strip").click();
      await expect(page).toHaveURL(new RegExp(`/${type === "bond" ? "bond" : "company"}/${ticker}`));
      expect(errors).toEqual([]);
    });
  }
}

test("metrics follow the selected period, sector, missing data and negotiated board", async ({ page }) => {
  const errors = await openMap(page);
  await page.getByRole("button", { name: "1Н", exact: true }).click();
  await expect(metric(page, "volume")).toHaveText("10 000 000 UZS");
  await expect(metric(page, "avgShare")).toHaveText("5 000 UZS");
  await expect(metric(page, "avgTrade")).toHaveText("1 250 000 UZS");
  await expect(metric(page, "bigTrade")).toHaveText("4 000 000 UZS");
  await expect(page.locator('.heatmap-metric-details [data-metric="bigTrade"]')).toContainText("Детали по 3 из 5 сессий");
  await page.getByLabel("Отрасль", { exact: true }).selectOption({ label: "Финансы" });
  await expect(metric(page, "volShare")).toHaveText("25%");
  await page.getByLabel("Бумага на карте").selectOption("EMPTY");
  for (const key of ["volume", "volQty", "avgShare", "avgTrade", "bigTrade", "volShare"]) await expect(metric(page, key)).toHaveText("—");
  await page.getByLabel("Бумага на карте").selectOption("AGBA");
  await page.locator(".market-segment-control").getByRole("button", { name: /Переговорный/ }).click();
  await expect(metric(page, "volume")).toHaveText("2 000 000 UZS");
  await expect(metric(page, "avgShare")).toHaveText("500 UZS");
  await expect(metric(page, "avgTrade")).toHaveText("1 000 000 UZS");
  await expect(metric(page, "bigTrade")).toHaveText("—");
  expect(errors).toEqual([]);
});

test("metric choices persist on reload and apply to both instruments and languages", async ({ page }) => {
  const errors = await openMap(page);
  await page.getByRole("button", { name: /Показатели/ }).click();
  await page.getByRole("checkbox", { name: "Все", exact: true }).uncheck();
  await page.getByRole("checkbox", { name: "Объём (шт)", exact: true }).check();
  await page.keyboard.press("Escape");
  await page.reload();
  await expect(page.locator(".heatmap-metric-details [data-metric]")).toHaveCount(1);
  await expect(metric(page, "volQty")).toHaveText("1 000 шт");
  await page.locator(".market-type-control").getByRole("button", { name: "Облигации", exact: true }).click();
  await page.getByLabel("Бумага на карте").selectOption("BOND1");
  await expect(metric(page, "volQty")).toHaveText("80 шт");
  await page.locator("#languageSelect").selectOption("uz");
  await expect(page.locator(".heatmap-metric-details")).toContainText("Hajm (dona)");
  await page.locator("#languageSelect").selectOption("en");
  await expect(page.locator(".heatmap-metric-details")).toContainText("Volume (units)");
  expect(errors).toEqual([]);
});
