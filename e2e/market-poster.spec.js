import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import logos from "../company_logos.json" with {type: "json"};

const shares = [
  ["UZTL", "O‘zbektelekom AK", 20880, 181733590.13],
  ["ALKB", "Aloqabank", 1.9, 151368463.56, 763],
  ["URTS", "O‘zRTXB", 13699, 129786408.72],
  ["KASU", "Kapital sug‘urta", 0.01, null, 365],
  ["IPTB", "Ipoteka bank", 6.51, null, 344],
];

async function openStudio(page, {partial=false, empty=false} = {}) {
  await page.addInitScript(() => {
    localStorage.setItem("uz_stock_analyzer_token", "admin");
    localStorage.setItem("uz_stock_analyzer_language", "en");
  });
  const stocks = shares.map(([ticker,name,last_price,volume]) => ({
    ticker, name, isin:ticker, last_price, volume, type:"stock", last_trade_date:"2026-11-19",
  }));
  stocks.push({...stocks[0], ticker:"OLD", isin:"OLD", volume:9e9, last_trade_date:"2026-11-18"});
  const stats = Object.fromEntries(shares.filter(row => row[4]).map(([ticker,,,,trade_count]) =>
    [ticker, {trade_date:"20261119", trade_count}]));
  stats.UZTL = {trade_date:"20261118", trade_count:9999, total_value:9e9};
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    const send = json => route.fulfill({json});
    if (path === "/api/auth/me") return send({user:{id:1,is_admin:true}});
    if (path === "/api/market/stocks") return send({ok:true,stocks:empty ? [] : stocks});
    if (path === "/api/market/trade-stats") return send({ok:true,stats,trade_date:"20261119",validation:{partial,trade_date:"20261119"}});
    if (path === "/api/securities") return send({ok:true,securities:Object.fromEntries(shares.map(([ticker]) => [ticker,{logo_url:logos[ticker]}]))});
    return send({ok:true,items:[]});
  });
  await page.route("**/logos/**", route => route.fulfill({path:"."+new URL(route.request().url()).pathname}));
  await page.goto("/admin/marketing");
  await page.getByRole("button", {name:"Bozor sharhi"}).click();
  return page.getByRole("region", {name:"Bozor sharhi"});
}

test("export the sunset market poster and copy the matching caption", async ({page,context}, info) => {
  await page.setViewportSize({width:390,height:844});
  await context.grantPermissions(["clipboard-read","clipboard-write"]);
  const studio = await openStudio(page);
  const caption = studio.getByRole("textbox", {name:"Caption", exact:true});
  await expect(studio.getByRole("img")).toHaveAccessibleName(/Turnover \(UZS\): UZTL 181733590.13, ALKB 151368463.56, URTS 129786408.72 · Trades: ALKB 763, KASU 365, IPTB 344$/);
  await expect(caption).toHaveValue(/UZTL.*181 733 590,13/s);
  await expect(caption).toHaveValue(/ALKB.*763/s);
  await expect(caption).not.toHaveValue(/OLD|9999/);
  const png = page.waitForEvent("download");
  await studio.getByRole("button",{name:"Download PNG"}).click();
  const file = await png;
  expect(file.suggestedFilename()).toBe("uzstock-bozor-sharhi-20261119-uz.png");
  const path = info.outputPath("bozor-sharhi.png");
  await file.saveAs(path);
  const bytes = await readFile(path);
  expect([bytes.readUInt32BE(16),bytes.readUInt32BE(20)]).toEqual([1080,1350]);
  expect(bytes.toString("base64")).toBe(await studio.locator("canvas").evaluate(canvas => canvas.toDataURL().split(",")[1]));
  await studio.getByLabel("Caption language").selectOption("ru");
  await expect(caption).toHaveValue(/сделок/u);
  await caption.fill("Итоги торгов за 19 ноября");
  await studio.getByRole("button",{name:"Copy caption"}).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(await caption.inputValue());
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

for (const state of ["empty", "partial"]) test(`suppress poster export for ${state} session data`, async ({page}) => {
  const studio = await openStudio(page,{[state]:true});
  await expect(studio.getByRole("status")).toContainText(/rankings unavailable/i);
  await expect(studio.getByRole("button",{name:"Download PNG"})).toHaveCount(0);
});
