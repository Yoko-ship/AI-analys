import {chooseIndustry} from './industry-control.js';
import { selectLanguage, toggleTheme } from './language-control.js';
import { test, expect } from "@playwright/test";
import path from "node:path";

const day = "2026-09-25";
const row = (ticker, type, price, prev, volume, quantity, count, industry) => ({
  ticker, type, isin: `UZ${ticker}`, name: `${ticker} issuer`, last_price: price, close_price: prev,
  volume, quantity, trade_count: count, last_trade_date: day, industry,
});
const stocks = [row("AGBA", "stock", 1000, 900, 1e6, 1000, 4, "finance"),
  row("KVTS", "stock", 3000, 3100, 3e6, 1000, 6, "manufacturing"), row("EMPTY", "stock", null, null, null, null, null, "finance")];
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

async function openMap(page, type = "stock", path = "/heatmap", selectTicker = true, user = null) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => sessionStorage.setItem("uz_sponsor_seen", "1"));
  if (user) await page.addInitScript(() => localStorage.setItem("uz_stock_analyzer_token", "role-test"));
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === "/api/companies") return json({ companies: all.map((r) => ({ ticker: r.ticker, company_name: r.name, sector: r.industry })) });
    if (url.pathname === "/api/securities") return json({ ok: true, securities: Object.fromEntries(all.map((r) => [r.ticker, { ...r, security_type: r.type,
      logo_url: r.ticker === "AGBA" ? "/logos/AGBA.png" : r.ticker === "KVTS" ? "/logos/KVTS.png" : null }])) });
    if (url.pathname === "/api/market/stocks") return json({ stocks: url.searchParams.get("type") === "bond" ? bonds : stocks });
    if (url.pathname === "/api/market/trade-stats") return json({ ok: true, stats: tradeStats });
    if (url.pathname === "/api/market/changes") return json({ ok: true, changes });
    if (url.pathname === "/api/auth/me") return json({ user }, user ? 200 : 401);
    return json({ ok: true });
  });
  await page.goto(path);
  if (path !== "/heatmap") return errors;
  if (type === "bond") await page.locator(".market-type-control").getByRole("button", { name: "Облигации", exact: true }).click();
  if (selectTicker) await page.getByLabel("Бумага на карте").selectOption(type === "bond" ? "BOND1" : "AGBA");
  return errors;
}

const metric = (page, key) => page.locator(`.heatmap-metric-details [data-metric="${key}"] strong`);
async function chooseMapPeriod(page, code) {
  const trigger=page.locator('.heatmap-performance-trigger');
  if(await trigger.count()) {
    await trigger.click();
    await page.locator(`.heatmap-performance-menu button[data-period="${code}"]`).click();
  } else {
    const codes=['1d','1w','1m','3m','6m','1y','ytd'];
    await page.locator('.market-filterbar .market-period-control').getByRole('button').nth(codes.indexOf(code)).click();
  }
}

for (const width of [1280, 390]) test(`searchable heatmap performance periods at ${width}px`, async ({page}, testInfo) => {
  await page.setViewportSize({width, height: 844});
  const errors = await openMap(page, "stock", "/heatmap", true, {id:1,admin_role:"administrator"});
  const trigger = page.locator('.heatmap-performance-trigger');
  await expect(trigger).toContainText('За сессию');
  await trigger.click();
  const menu = page.getByRole('dialog', {name: 'Период изменения', exact: true});
  const search = menu.getByRole('searchbox', {name: 'Найти период'});
  await expect(search).toBeFocused();
  await expect(menu.locator('[data-period]')).toHaveCount(7);
  await expect(menu.locator('[data-period="1d"]')).toHaveAttribute('aria-pressed', 'true');
  await search.fill('  НЕДЕЛ  ');
  await expect(menu.locator('[data-period]')).toHaveCount(1);
  await search.press('ArrowDown');
  await expect(menu.locator('[data-period="1w"]')).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(menu).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(trigger).toContainText('За неделю');
  await expect(page.locator('.heatmap-tree-tile[data-ticker="AGBA"] .htt-pct')).toContainText('+12');
  await expect(metric(page, 'volume')).toHaveText('10 000 000 UZS');
  await page.reload();
  await expect(trigger).toContainText('За неделю');
  await trigger.click();
  await expect(search).toHaveValue('');
  await expect(menu.locator('[data-period="1w"]')).toHaveAttribute('aria-pressed', 'true');
  await search.fill('no such period');
  await expect(menu.getByRole('status')).toHaveText('Ничего не найдено');
  await menu.getByRole('button', {name: 'Очистить поиск'}).click();
  await expect(search).toBeFocused();
  for (const theme of ['light', 'dark']) {
    await page.evaluate(theme => { document.body.dataset.theme = theme; document.documentElement.dataset.theme = theme; }, theme);
    const bounds = await menu.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(8);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width - 8);
    expect(bounds.y).toBeGreaterThanOrEqual(8);
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(836);
    await page.screenshot({path: testInfo.outputPath(`performance-${theme}.png`)});
  }
  // A phone keyboard reduces the space available to the open menu.
  await page.setViewportSize({width, height: 420});
  await expect.poll(async () => { const box = await menu.boundingBox(); return box.y >= 8 && box.y + box.height <= 412; }).toBe(true);
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  await page.setViewportSize({width, height: 844});
  await selectLanguage(page, 'en');
  await expect(trigger).toContainText('1-Week Performance');
  await trigger.click();
  await page.getByRole('searchbox', {name: 'Find a period'}).fill('month');
  await expect(page.locator('.heatmap-performance-menu [data-period]')).toHaveCount(3);
  await page.keyboard.press('Escape');
  await selectLanguage(page, 'uz');
  await expect(trigger).toContainText('1 haftalik o‘zgarish');
  await chooseMapPeriod(page, '1y');
  await expect(metric(page, 'volume')).toHaveText('—');
  await chooseMapPeriod(page, '1d');
  await expect(metric(page, 'volume')).toHaveText('1,000,000 UZS');
  await page.locator('.market-view-toggle button').first().click();
  await expect(page).toHaveURL(/\/market$/);
  await expect(page.locator('.market-period-control')).toBeVisible();
  expect(errors).toEqual([]);
});
test('market map draws its tiles when market data arrives after mounting', async ({page}) => {
  await openMap(page, 'stock', '/heatmap', false);
  await expect(page.locator('.heatmap-tree-tile[data-ticker="AGBA"]')).toBeVisible();
});
for (const width of [1280, 390, 320]) {
  test(`heatmap opens with the main movement and metrics above the map at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    const errors = await openMap(page, "stock", "/heatmap", false);
    const assertSummaryFirst = async () => {
      await expect(page.locator('.heatmap-tree-tile[data-ticker="AGBA"]')).toBeVisible();
      await expect.poll(() => page.evaluate(() => {
        const tree = document.querySelector('.heatmap-tree').getBoundingClientRect();
        const wrap = document.querySelector('.heatmap-wrap');
        const focus = document.querySelector('.heatmap-focus-strip').getBoundingClientRect();
        const details = document.querySelector('.heatmap-metric-details').getBoundingClientRect();
        return { atTop: scrollY === 0, focusFirst: wrap.firstElementChild.matches('.heatmap-focus-strip'),
          metricsAfterFocus: details.top >= focus.bottom,
          detailsAboveMap: details.bottom <= tree.top,
          summaryBelowMap: document.querySelector('.market-stats-grid').getBoundingClientRect().top >= tree.bottom,
          noOverflow: document.documentElement.scrollWidth <= innerWidth };
      })).toEqual({ atTop: true, focusFirst: true, metricsAfterFocus: true, detailsAboveMap: true, summaryBelowMap: true, noOverflow: true });
    };
    await assertSummaryFirst();
    await page.screenshot({ path: testInfo.outputPath('summary-on-arrival.png') });
    await page.reload();
    await assertSummaryFirst();
    await page.locator('.market-view-toggle button[title="Таблица"]').click();
    await expect(page).toHaveURL(/\/market$/);
    await expect(page.locator('.market-hero-search')).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.locator('.market-view-toggle button[title="Карта рынка"]').click();
    await expect(page).toHaveURL(/\/heatmap$/);
    await assertSummaryFirst();
    expect(errors).toEqual([]);
  });
}

for (const width of [1280, 390]) {
  test(`round company logos fit heatmap tiles at ${width}px and survive image failures`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/logos/AGBA.png', route => route.fulfill({ path: path.resolve('logos/AGBA.png'), contentType: 'image/png' }));
    await page.route('**/logos/KVTS.png', route => route.fulfill({ status: 404, body: '' }));
    const errors = await openMap(page);
    const agba = page.locator('.heatmap-tree-tile[data-ticker="AGBA"]');
    const logo = agba.locator('.htt-logo');
    await expect(logo).toBeVisible();
    await expect(logo).toHaveCSS('border-radius', '50%');
    await expect.poll(() => logo.locator('img').evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
    await expect(page.locator('.heatmap-tree-tile[data-ticker="KVTS"] .htt-logo .chip-logo-fallback')).toHaveText('KV');
    await expect(page.locator('.heatmap-tree-tile.is-micro .htt-logo')).toHaveCount(0);
    for (const theme of ['dark', 'light']) {
      await page.evaluate(theme => document.body.dataset.theme = theme, theme);
      const bounds = await agba.evaluate(tile => {
        const t = tile.getBoundingClientRect();
        const badge = tile.querySelector('.htt-logo').getBoundingClientRect();
        const ticker = tile.querySelector('.htt-ticker').getBoundingClientRect();
        return { square: Math.abs(badge.width - badge.height) < 1,
          inside: badge.top >= t.top && badge.left >= t.left && badge.right <= t.right,
          aboveTicker: badge.bottom <= ticker.top,
          fits: tile.scrollHeight <= tile.clientHeight && tile.scrollWidth <= tile.clientWidth };
      });
      expect(bounds).toEqual({ square: true, inside: true, aboveTicker: true, fits: true });
      await page.locator('.heatmap-tree').screenshot({ path: testInfo.outputPath(`logos-${theme}.png`) });
    }
    await agba.click();
    await expect(page).toHaveURL(/\/company\/AGBA$/);
    expect(errors).toEqual([]);
  });
}

for (const type of ["stock", "bond"]) {
  for (const width of [1280, 390]) {
    test(`${type} map exposes all six trading metrics at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      const errors = await openMap(page, type, "/heatmap", true, {id:1,is_admin:true});
      const ticker = type === "bond" ? "BOND1" : "AGBA";
      const expected = type === "bond"
        ? ["8 000 000 UZS", "80 шт", "100 000 UZS", "4 000 000 UZS", "4 000 000 UZS", "40%"]
        : ["1 000 000 UZS", "1 000 шт", "1 000 UZS", "250 000 UZS", "700 000 UZS", "25%"];
      for (const [i, key] of ["volume", "volQty", "avgShare", "avgTrade", "bigTrade", "volShare"].entries()) {
        await expect(metric(page, key)).toHaveText(expected[i]);
      }
      if (width === 1280) await toggleTheme(page);
      const tile = page.locator(`.heatmap-tree-tile[data-ticker="${ticker}"]`);
      await tile.hover();
      await expect(page.locator('.heatmap-preview-metrics')).toContainText('Крупнейшая сделка');
      await page.keyboard.press('Escape');
      // A tile carries price and turnover only; the six metrics live in the panel.
      if (width === 1280) await expect(tile.locator(".htt-metrics [data-metric]")).toHaveCount(2);
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

test("metrics follow the selected period, sector and missing data on the one combined board", async ({ page }) => {
  const errors = await openMap(page);
  await chooseMapPeriod(page, '1w');
  await expect(metric(page, "volume")).toHaveText("10 000 000 UZS");
  await expect(metric(page, "avgShare")).toHaveText("5 000 UZS");
  await expect(metric(page, "avgTrade")).toHaveText("1 250 000 UZS");
  await expect(metric(page, "bigTrade")).toHaveText("4 000 000 UZS");
  await expect(page.locator('.heatmap-metric-details [data-metric="bigTrade"]')).toContainText("Детали по 3 из 5 сессий");
  await chooseIndustry(page, 'finance');
  await expect(metric(page, "volShare")).toHaveText("25%");
  await page.getByLabel("Бумага на карте").selectOption("EMPTY");
  for (const key of ["volume", "volQty", "avgShare", "avgTrade", "bigTrade", "volShare"]) await expect(metric(page, key)).toHaveText("—");
  await page.getByLabel("Бумага на карте").selectOption("AGBA");
  // Main and negotiated boards were merged: no board switch, and the negotiated
  // deal never leaks into the session metrics.
  await expect(page.locator(".market-segment-control")).toHaveCount(0);
  await expect(metric(page, "volume")).toHaveText("10 000 000 UZS");
  expect(errors).toEqual([]);
});

test("the market table flags a negotiated deal beside the turnover without adding it", async ({ page }) => {
  const errors = await openMap(page, "stock", "/market");
  const row = page.locator(".market-table tbody tr").filter({ has: page.getByRole("button", { name: "AGBA", exact: true }) });
  const mark = row.locator(".market-block-mark");
  await expect(mark).toHaveText("†");
  await expect(mark).toHaveAttribute("title", /Сделка вне сессии 25\.09\.2026 \(переговорная или размещение\): 2\s000\s000\sUZS/);
  // The cell's turnover is the auction's 1 000 000, not 3 000 000 with the deal added.
  await expect(mark.locator("xpath=..")).toContainText(/^1\s000\s000†/);
  await mark.locator("xpath=..").scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath("nego-mark-row.png") });
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
  await selectLanguage(page, 'uz');
  await expect(page.locator(".heatmap-metric-details")).toContainText("Hajm (dona)");
  await selectLanguage(page, 'en');
  await expect(page.locator(".heatmap-metric-details")).toContainText("Volume (units)");
  expect(errors).toEqual([]);
});

test("turnover and change filters choose which tiles are drawn, not the market pulse", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const errors = await openMap(page);
  await expect(page.locator(".fx-bar")).toHaveCount(0);
  const tiles = page.locator(".heatmap-tree-tile");
  await expect(tiles).toHaveCount(3);
  const pulse = await page.locator(".heatmap-pulse-main strong").innerText();
  const filters = page.locator(".heatmap-filters");
  await filters.getByRole("group", { name: "Оборот" }).getByRole("button", { name: "≥ 1 млн" }).click();
  await expect(tiles).toHaveCount(2);
  await filters.getByRole("group", { name: "Изменение" }).getByRole("button", { name: "Рост" }).click();
  await expect(tiles).toHaveCount(1);
  await expect(page.locator('.heatmap-tree-tile[data-ticker="AGBA"]')).toHaveCount(1);
  await expect(filters).toContainText("Показано: 1/3");
  await expect(page.locator(".heatmap-pulse-main strong")).toHaveText(pulse);
  await filters.getByRole("group", { name: "Оборот" }).getByRole("button", { name: "≥ 1 млрд" }).click();
  await expect(tiles).toHaveCount(0);
  await expect(page.locator('.heatmap-empty-state')).toContainText("Нет бумаг под выбранные фильтры");
  await page.getByRole("button", { name: "Сбросить фильтры" }).first().click();
  await expect(tiles).toHaveCount(3);
  expect(errors).toEqual([]);
});

test('area selector and legend describe the same measure',async({page})=>{
 await openMap(page);
 await page.getByLabel('Площадь плитки').selectOption('turnover');
 await expect(page.locator('.heatmap-area-note')).toContainText('Оборот');
 await page.getByLabel('Площадь плитки').selectOption('equal');
 await expect(page.locator('.heatmap-area-note')).toContainText('Равные плитки');
});

test('heatmap hover keeps missing quotes empty and follows the selected period', async ({page}) => {
  await openMap(page, 'stock', '/heatmap', true, {id:1,is_admin:true});
  await page.getByLabel('Площадь плитки').selectOption('equal');
  await page.locator('.heatmap-tree-tile[data-ticker="EMPTY"]').hover();
  const card = page.locator('.heatmap-preview');
  await expect(card).toBeVisible();
  await expect(card.locator('.heatmap-preview-price')).toHaveText('— UZS');
  await expect(card.locator('.heatmap-preview-change')).toContainText('—');
  await expect(card.locator('svg')).toHaveCount(0);
  await expect(card.locator('.heatmap-preview-no-history').first()).toHaveText('—');
  await expect(card.locator('.heatmap-preview-metrics dd')).toHaveText(['—', '—', '—', '—', '—', '—']);
  await page.keyboard.press('Escape');
  await chooseMapPeriod(page, '1w');
  await page.locator('.heatmap-tree-tile[data-ticker="AGBA"]').hover();
  await expect(card.locator('.heatmap-preview-change')).toContainText('+12');
  await expect(card.locator('.heatmap-preview-change')).toContainText('нед.');
  await expect(card.locator('.heatmap-preview-metrics')).toContainText('10 000 000 UZS');
  await expect(card.locator('.heatmap-preview-metrics')).toContainText('Детали по 3 из 5 сессий');
});
