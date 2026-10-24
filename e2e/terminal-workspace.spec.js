import { test, expect } from "@playwright/test";

async function fixture(page) {
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_token', 'admin-token'));
  let preferences = {};
  const companies = [{ticker:"AGBA",company_name:"Агробанк",sector:"finance",total_count:6}, {ticker:"QZSM",company_name:"Кызылкумцемент",sector:"manufacturing",total_count:5}];
  const rows = companies.map((c,i)=>({...c,name:c.company_name,kind:i?"industry":"bank",standard:"NSBU",scope:"separate",period:"2025",roe:i?8:20,pb:1,pe:8,de:i?2:null,cg5:10,dy:12,issues:[]}));
  await page.route("**/api/**", route => {
    const u = new URL(route.request().url());
    const json = body => route.fulfill({contentType:"application/json",body:JSON.stringify(body)});
    if(u.pathname==="/api/auth/me") return json({user:{id:1,is_admin:true,email:'admin@example.test'}});
    if(u.pathname==="/api/profile") return json({preferences});
    if(u.pathname==="/api/profile/preferences") { preferences = route.request().postDataJSON(); return json({ok:true,preferences}); }
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

test("RV compares the selected reporting year and handles missing peers", async({page},testInfo)=>{
  await fixture(page);
  const requests=[];
  await page.route('**/api/terminal/screener?**', route=>{
    const year=new URL(route.request().url()).searchParams.get('year')||'2025';
    requests.push(year);
    const base={kind:'bank',standard:'NSBU',scope:'separate',period:year,years:['2025','2024','2023'],
      cbu:year==='2023'?{}:{main:{date:`${year}-12-01`,source_url:`https://cbu.uz/${year}`}},
      cbu_assets_share_pct:year==='2023'?null:year==='2024'?4.2:5.1};
    return route.fulfill({json:{ok:true,years:['2025','2024','2023'],rows:[
      {...base,ticker:'AGBA'},
      ...(year==='2023'?[]:[{...base,ticker:'ALKB',roe:year==='2024'?14:27}]),
      {...base,ticker:'WRONG',period:'2022',roe:99},
    ]}});
  });
  await run(page,'AGBA RV');
  const screen=page.getByRole('heading',{name:'RV · Аналоги',exact:true}).locator('..');
  const year=screen.getByRole('combobox',{name:'Год отчётности',exact:true});
  const peers=screen.locator('table').first();
  await expect(year).toHaveValue('');
  await expect(peers.locator('tbody tr')).toHaveCount(1);
  await expect(peers).toContainText('27');
  await year.selectOption('2024');
  await expect(peers).toContainText('14');
  await expect(screen).toContainText('2024 · bank');
  await expect(screen.locator('.terminal-bank-comparison')).toContainText('2024-12-01');
  await expect(screen.locator('.terminal-bank-comparison')).not.toContainText('2025-12-01');
  await expect(screen.locator('.terminal-bank-comparison')).toContainText('4,2');
  expect(requests).toContain('2024');
  await page.screenshot({path:testInfo.outputPath('rv-year-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:testInfo.outputPath('rv-year-mobile.png'),fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await year.selectOption('2023');
  await expect(screen.getByText('Сопоставимые эмитенты не найдены',{exact:true})).toBeVisible();
  await expect(peers.locator('tbody tr')).toHaveCount(0);
  await expect(screen.locator('.terminal-bank-comparison')).not.toContainText('2024-12-01');
  await year.selectOption('');
  await expect(peers).toContainText('27');
  await expect(screen.locator('.terminal-bank-comparison')).toContainText('2025-12-01');
});
test("PNL saves independent admin panels to the profile and survives reload", async({page})=>{
  await fixture(page); await run(page,"PNL");
  await page.getByRole("button",{name:"Добавить панель",exact:true}).click();
  await expect(page.locator(".terminal-work-panel")).toHaveCount(2);
  await page.locator(".terminal-work-panel").nth(1).getByLabel("Эмитент").selectOption("QZSM");
  await page.getByRole('button',{name:'Сохранить раскладку',exact:true}).click();
  await expect(page.getByRole('button',{name:'Сохранить раскладку',exact:true})).toBeDisabled();
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
  await page.getByText('Ранее опубликованные показатели', { exact: true }).click();
  await page.getByLabel('Валюта').selectOption('USD');
  await expect(page.locator('.terminal-fx-rates')).toContainText('2025-12-31');
  await expect(page.locator('.terminal-fx-rates')).toContainText('2024-12-31');
  await expect(page.locator('.fin-note').filter({hasText:'Суммы в USD'})).toBeVisible();
  await page.locator('[data-currency=USD]').getByRole('button',{name:'Таблица',exact:true}).click();
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

test("RAT keeps bank figures and quarterly ratios without CBU sector accordions",async({page},testInfo)=>{
  await fixture(page);
  const sectorSeries = Object.fromEntries(['capital','liquidity','profitability','industry'].map(key => [key, {
    date: '2026-09-01', source_url: `https://cbu.uz/${key}`,
    rows: [{name: key, unit: '%', observations: {'2026-09-01': 12}}],
  }]));
  await page.route('**/api/v1/issuers/AGBA/ai-report?*',r=>r.fulfill({contentType:'application/json',body:JSON.stringify({status:'available',period:'2026Q2',scope:'separate',ratios:[{metric_code:'nim',name_ru:'Чистая процентная маржа',value:4.2,unit:'percent'}],verdict_line:'Вердикт: смешанно',sources:[]})}));
  await page.route('**/api/terminal/issuer/AGBA/analytics?*',r=>r.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,snapshot:{period:'2025',kind:'bank'},growth:[],quarters:{rows:[{period:'2026Q1',value:100,yoy:10}]},cbu:{npl:{date:'2026-09-01',npl_pct:3.4,company_deposits_bn:150,source_url:'https://cbu.uz/npl'}},sector_series:sectorSeries,template:{selected_template:'bank'}})}));
  await run(page,'AGBA RAT');
  await expect(page.getByText('Чистая процентная маржа',{exact:true})).toBeVisible();
  await expect(page.locator('.terminal-cbu')).toContainText('2026-09-01');
  await expect(page.locator('.terminal-cbu')).toContainText('Депозиты юрлиц');
  await expect(page.locator('.terminal-heatmap')).toContainText('2026');
  for (const name of ['Достаточность капитала','Ликвидность','Доходность сектора','Кредиты по отраслям']) {
    await expect(page.getByText(`${name} · CBU · 2026-09-01`, {exact: true})).toHaveCount(0);
  }
  await page.locator('.terminal-analytics').screenshot({path:testInfo.outputPath('catalog-rat-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  await page.locator('.terminal-analytics').screenshot({path:testInfo.outputPath('catalog-rat-mobile.png')});
});

test('quarterly profit and LTM display and export billions without scaling percentages', async ({page}, testInfo) => {
  await fixture(page);
  await page.route('**/api/terminal/issuer/AGBA/analytics?*', route => route.fulfill({json: {
    ok: true, snapshot: {period: '2025', kind: 'bank'}, growth: [], template: {selected_template: 'bank'},
    quarters: {rows: [
      {period: '2026Q1', value: -1500000000, yoy: -5.2, ltm: 0, seasonality: null, cg3: -3.4},
      {period: '2026Q2', value: 0, yoy: 0, ltm: null, seasonality: 0, cg3: null},
      {period: '2026Q3', value: 510460312000, yoy: 10.73, ltm: 1917587479000, seasonality: null, cg3: 10.75},
    ]},
  }}));
  await run(page, 'AGBA RAT');
  const table = page.locator('.terminal-quarter-map');
  await expect(table.locator('thead th')).toHaveText(['Квартал', 'млрд UZS', 'YoY, %', 'LTM, млрд UZS', 'Доля в году, %', 'CAGR 3Y, %']);
  const cells = period => table.getByRole('row').filter({has: page.getByRole('rowheader', {name: period, exact: true})}).getByRole('cell');
  await expect(cells('2026Q1')).toHaveText(['-1,5', '-5,2', '0', '—', '-3,4']);
  await expect(cells('2026Q2')).toHaveText(['0', '0', '—', '0', '—']);
  await expect(cells('2026Q3')).toHaveText(['510,46', '10,73', /1\s917,59/, '—', '10,75']);
  const wrapper = table.locator('..');
  const pendingDownload = page.waitForEvent('download');
  await wrapper.getByRole('button', {name: 'CSV', exact: true}).click();
  const {readFile} = await import('node:fs/promises');
  const csv = await readFile(await (await pendingDownload).path(), 'utf8');
  expect(csv).toContain('Квартал,млрд UZS,"YoY, %","LTM, млрд UZS"');
  expect(csv).toMatch(/2026Q3,"510,46","10,73","1\s917,59",—,"10,75"/);
  await wrapper.screenshot({path: testInfo.outputPath('quarterly-billions-desktop.png')});
  await page.setViewportSize({width: 390, height: 844});
  await wrapper.screenshot({path: testInfo.outputPath('quarterly-billions-mobile.png')});
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

test('EQS and RV show bank market shares, loan/deposit structure and source dates', async ({page})=>{
  await fixture(page);
  const rows=['AGBA','HMKB'].map((ticker,i)=>({ticker,name:ticker,kind:'bank',standard:'NSBU',scope:'separate',period:'2025',roe:20,pb:1,years:['2025'],
    cbu_assets_share_pct:i?4.2:12.5,cbu_household_loans_bn:i?100:200,cbu_company_loans_bn:300,cbu_household_deposits_bn:90,cbu_company_deposits_bn:150,
    cbu:{main:{date:'2026-09-01',source_url:'https://cbu.uz/main.xlsx'},structure:{date:'2026-09-01',source_url:'https://cbu.uz/structure.xlsx'}}}));
  await page.route('**/api/terminal/screener?**',r=>r.fulfill({json:{ok:true,rows,years:['2025'],sector_series:{},deposit:null}}));
  await run(page,'EQS');
  await expect(page.locator('.terminal-bank-comparison')).toContainText('Доля активов');
  await expect(page.locator('.terminal-bank-comparison')).toContainText('Депозиты юрлиц');
  await expect(page.locator('.terminal-bank-comparison')).toContainText('2026-09-01');
  await page.getByLabel('Доля активов ЦБ ≥').fill('10');
  await expect(page.locator('.terminal-bank-comparison tbody tr')).toHaveCount(1);
  await run(page,'AGBA RV');
  await expect(page.locator('.terminal-bank-comparison')).toContainText('HMKB');
  await expect(page.locator('.terminal-bank-comparison')).toContainText('Кредиты физлиц');
});
