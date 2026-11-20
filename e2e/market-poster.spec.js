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

test("editor copies a bilingual earnings post and downloads its six-figure card", async ({page, context}, info) => {
  await context.grantPermissions(["clipboard-read","clipboard-write"]);
  await page.setViewportSize({width:390,height:844});
  await openStudio(page);
  const filing = "https://openinfo.uz/ru/reports/jsc/quarter/";
  const periods = [
    {end:"2026-09-30", values:{net_income:4691715000,revenue:682158199000,total_assets:3889578134000,
      total_equity:2990561496000,retained_earnings:1812985275000,selling_expense:-86075671000,
      bank_borrowings_long:510046719000,other_borrowings_short:33350000000},sources:[filing+"19277"],profit_mismatch:true},
    {end:"2026-06-30",values:{net_income:5602521000},sources:[filing+"18907"]},
    {end:"2025-09-30", values:{net_income:-16045148000,revenue:1114957419000,total_assets:3964852208000,
      total_equity:3004007375000,retained_earnings:1791259790000,selling_expense:-143499884000,
      bank_borrowings_long:0,other_borrowings_short:19100000000},sources:[filing+"17666"]},
    {end:"2025-06-30",values:{net_income:-70109301000},sources:[filing+"17335"]},
  ];
  await page.route("**/api/admin/marketing/earnings/QZSM", route => route.fulfill({json:{
    ticker:"QZSM",issuer:"Qizilqumsement",periods
  }}));
  await page.getByRole("button",{name:"Earnings report"}).click();
  const studio = page.getByRole("region",{name:"Earnings report"});
  const caption = studio.getByLabel("Bilingual post");
  await expect(caption).toHaveValue(/4,7 млрд.*16,0 млрд.*910,8 млн.*54,1 млрд/s);
  await expect(caption).toHaveValue(/682,2 млрд.*86,1 млрд.*510,0 млрд.*33,4 млрд/s);
  await expect(caption).toHaveValue(/4,7 mlrd.*910,8 mln.*#QZSM #отчет/s);
  await expect(caption).toHaveValue(/строк.*270/is);
  await expect(studio.getByRole("img")).toHaveAccessibleName(/−910,8 млн.*4,7 млрд/s);
  const downloaded = page.waitForEvent("download");
  await studio.getByRole("button",{name:"Download PNG"}).click();
  const png = await downloaded;
  expect((await caption.inputValue()).length).toBeLessThanOrEqual(1024);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  expect(png.suggestedFilename()).toBe("uzstock-QZSM-2026-09-30.png");
  await png.saveAs(info.outputPath("qzsm-earnings.png"));
  const edited = (await caption.inputValue()) + "\nРедакторская правка";
  await caption.fill(edited);
  await studio.getByRole("button",{name:"Copy bilingual post"}).click();
  expect(await page.evaluate(()=>navigator.clipboard.readText())).toBe(edited);
  await studio.getByLabel("Reporting period").selectOption("2026-06-30");
  await expect(caption).not.toHaveValue(/910,8|Редакторская правка|33,4/);
  await expect(studio.getByRole("img")).not.toHaveAccessibleName(/910,8/);
  await studio.getByLabel("Reporting period").selectOption("2026-09-30");
  await expect(caption).toHaveValue(edited);
  await studio.getByLabel("Ticker").fill("OTHER");
  await studio.getByRole("button",{name:"Load filings"}).click();
  await expect(studio.getByText("No usable filings for this ticker.")).toBeVisible();
  await expect(studio.getByRole("button",{name:"Download PNG"})).toHaveCount(0);
});
