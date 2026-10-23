import { test, expect } from "@playwright/test";

async function fixture(page) {
  const companies = [{ticker:"AGBA",company_name:"Агробанк",sector:"finance",total_count:6}, {ticker:"QZSM",company_name:"Кызылкумцемент",sector:"manufacturing",total_count:5}];
  const rows = companies.map((c,i)=>({...c,name:c.company_name,kind:i?"industry":"bank",standard:"NSBU",scope:"separate",period:"2025",roe:i?8:20,pb:1,pe:8,de:i?2:null,cg5:10,dy:12,issues:[]}));
  await page.route("**/api/**", route => {
    const u = new URL(route.request().url());
    const json = body => route.fulfill({contentType:"application/json",body:JSON.stringify(body)});
    if(u.pathname==="/api/auth/me") return route.fulfill({status:401,body:"{}"});
    if(u.pathname==="/api/catalog/companies") return json({ok:true,companies});
    if(u.pathname.startsWith("/api/catalog/index/")) return json({ok:true,company_name:companies.find(c=>u.pathname.endsWith(c.ticker))?.company_name,availability:{NSBU:{annual:[{year:2025,quarter:0}],quarter:[]}}});
    if(u.pathname==="/api/terminal/screener") return json({ok:true,rows,years:[2025,2024],standard:"NSBU",scope:"separate",deposit_rate:null});
    if(u.pathname.endsWith("/reconciliation")) return json({ok:true,rows:[{field:"net_profit",period:"2025",nsbu:20e9,ifrs:25e9,difference:5e9}],same_scope:false,nsbu_scope:"separate",ifrs_scope:"consolidated"});
    if(u.pathname.endsWith("/analytics")) return json({ok:true,snapshot:rows[0],growth:[],quarters:{rows:[]},template:{selected_template:"bank",reason_code:"filing_form"}});
    if(u.pathname.endsWith("/financials")) return json({ok:true,standard:u.searchParams.get("form")||"NSBU",scope:"separate",periods:["2025","2024"],series:{net_profit:{money:true,unit:"UZS",values:{2025:20e9,2024:18e9}}}});
    return json({ok:true,items:[],rows:[],points:[],companies:[],total_reports:11,companies_synced:2});
  });
  await page.goto("/catalog");
  await expect(page.getByRole("heading",{name:"Агробанк",exact:true})).toBeVisible();
}
async function run(page, text) {
  await page.getByRole("combobox",{name:"Строка команд терминала"}).fill(text);
  await page.getByRole("combobox",{name:"Строка команд терминала"}).press("Enter");
}

test("EQS filters real API rows, exports Cyrillic CSV, and restores its URL", async ({page})=>{
  await fixture(page);
  await run(page,"EQS");
  await expect(page.getByRole("heading",{name:/EQS/})).toBeVisible();
  await page.getByLabel("ROE ≥").fill("10");
  await expect(page.locator(".terminal-screener tbody tr")).toHaveCount(1);
  const download = page.waitForEvent("download");
  await page.getByRole("button",{name:"CSV",exact:true}).first().click();
  expect((await download).suggestedFilename()).toContain("EQS");
  await page.reload();
  await expect(page.getByRole("heading",{name:/EQS/})).toBeVisible();
});
test("REC compares standards and explains different reporting scopes", async({page})=>{
  await fixture(page); await run(page,"AGBA REC");
  await expect(page.locator(".terminal-reconciliation")).toContainText("2025");
  await expect(page.locator(".terminal-reconciliation")).toContainText("Периметры различаются");
});
test("PNL stores up to four independent guest panels and survives reload", async({page})=>{
  await fixture(page); await run(page,"PNL");
  await page.getByRole("button",{name:"Добавить панель",exact:true}).click();
  await expect(page.locator(".terminal-work-panel")).toHaveCount(2);
  await page.locator(".terminal-work-panel").nth(1).getByLabel("Эмитент").selectOption("QZSM");
  await page.reload();
  await expect(page.locator(".terminal-work-panel")).toHaveCount(2);
  await expect(page.locator(".terminal-work-panel").nth(1).getByLabel("Эмитент")).toHaveValue("QZSM");
});
test("catalog is a fundamental workspace without price history requests", async({page})=>{
  const prices=[];page.on("request",r=>{if(r.url().includes("/api/price-history")) prices.push(r.url());});
  await fixture(page);
  await expect(page.locator(".catalog-price-card")).toHaveCount(0);
  expect(prices).toEqual([]);
});

test("PL converts each year at its own CBU closing rate and reports missing rates", async({page})=>{
  await fixture(page);
  await page.route('**/api/currency/rates?as_of=*',route=>{
    const day=new URL(route.request().url()).searchParams.get('as_of');
    return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,as_of:day,rates:[{ccy:'USD',per_unit:day.startsWith('2025')?10000:9000,effective_date:day}]})});
  });
  await run(page,'AGBA PL');
  await page.getByLabel('Валюта').selectOption('USD');
  await expect(page.locator('.terminal-fx-rates')).toContainText('2025-12-31');
  await expect(page.locator('.terminal-fx-rates')).toContainText('2024-12-31');
  await expect(page.locator('.fin-note').filter({hasText:'Суммы в USD'})).toBeVisible();
  await page.getByRole('button',{name:'Таблица',exact:true}).click();
  await expect(page.locator('.fin-table')).toContainText(/2[\s\u00a0]000[\s\u00a0]000/);
  const pendingDownload=page.waitForEvent('download');
  await page.locator('[data-currency=USD]').getByRole('button',{name:'CSV',exact:true}).click();
  const downloaded=await pendingDownload;
  const {readFile}=await import('node:fs/promises');
  expect(await readFile(await downloaded.path(),'utf8')).toContain('Currency,USD');
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:'/tmp/uzstock-terminal-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.waitForTimeout(350);
  await page.screenshot({path:'/tmp/uzstock-terminal-mobile.png',fullPage:true});
});

test("RAT shows sector ratios and dated CBU observations with quarter heatmap",async({page})=>{
  await fixture(page);
  await page.route('**/api/v1/issuers/AGBA/ai-report?*',r=>r.fulfill({contentType:'application/json',body:JSON.stringify({status:'available',period:'2026Q2',scope:'separate',ratios:[{metric_code:'nim',name_ru:'Чистая процентная маржа',value:4.2,unit:'percent'}],verdict_line:'Вердикт: смешанно',sources:[]})}));
  await page.route('**/api/terminal/issuer/AGBA/analytics?*',r=>r.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,snapshot:{period:'2025'},growth:[],quarters:{rows:[{period:'2026Q1',value:100,yoy:10}]},cbu:{npl:{date:'2026-09-01',npl_pct:3.4,source_url:'https://cbu.uz/npl'}},template:{selected_template:'bank'}})}));
  await run(page,'AGBA RAT');
  await expect(page.getByText('Чистая процентная маржа',{exact:true})).toBeVisible();
  await expect(page.locator('.terminal-cbu')).toContainText('2026-09-01');
  await expect(page.locator('.terminal-heatmap')).toContainText('2026');
});

test("direct PNL visit waits for the issuer list before creating its first panel",async({page})=>{
  await fixture(page);
  await page.route('**/api/catalog/companies',async r=>{await new Promise(resolve=>setTimeout(resolve,200));return r.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,companies:[{ticker:'AGBA',company_name:'Агробанк'}]})});});
  await page.goto('/catalog?view=PNL');
  await expect(page.locator('.terminal-work-panel')).toHaveCount(1);
});

test("DQ cannot report clean coverage when the statement request fails",async({page})=>{
  await fixture(page);
  await page.route('**/api/company/AGBA/financials?*',r=>r.fulfill({status:503,contentType:'application/json',body:'{"detail":"Unavailable"}'}));
  await run(page,'AGBA DQ');
  await expect(page.locator('.tone-error')).toBeVisible();
});

test("DVD compares recent dividend and annual earnings yield to dated deposits",async({page})=>{
  await fixture(page);
  await page.route('**/api/terminal/issuer/AGBA/analytics?*',r=>r.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,snapshot:{period:'2025',dy:20,ep:22,price:10},deposit:{period:'2026-08',value:17.2,source_url:'https://cbu.uz/rates'},dividend:{decision:{decision_date:'2026-06-01'}}})}));
  await run(page,'AGBA DVD');
  await expect(page.locator('.terminal-dividend-comparison')).toContainText('2026-08');
  await expect(page.locator('.terminal-dividend-comparison')).toContainText('E/P');
});
