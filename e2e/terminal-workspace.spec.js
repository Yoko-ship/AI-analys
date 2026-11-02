import { test, expect } from "@playwright/test";
import { execFileSync } from 'node:child_process';

async function fixture(page, companies = [{ticker:"AGBA",company_name:"Агробанк",sector:"finance",total_count:6}, {ticker:"QZSM",company_name:"Кызылкумцемент",sector:"manufacturing",total_count:5}]) {
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_token', 'admin-token'));
  let preferences = {};
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
    if(u.pathname.endsWith("/financials")) {
      if(u.searchParams.get('form')==='NSBU'&&u.searchParams.has('scope'))return route.fulfill({status:422,json:{detail:'scope requires MSFO'}});
      return json({ok:true,standard:u.searchParams.get("form")||"NSBU",scope:"separate",periods:["2025","2024"],series:{net_profit:{money:true,unit:"UZS",values:{2025:20e9,2024:18e9}}}});
    }
    return json({ok:true,items:[],rows:[],points:[],companies:[],total_reports:11,companies_synced:2});
  });
  await page.goto("/catalog");
  await expect(page.getByRole("heading",{name:companies[0].company_name,exact:true})).toBeVisible();
}
async function run(page, text) {
  await page.locator('.terminal-command').getByRole("combobox").fill(text);
  await page.locator('.terminal-command').getByRole("combobox").press("Enter");
}

for(const [theme,width] of [['light',1440],['dark',390]]) test(`bank annual ratios and missing-value explanations work on EQS and RV (${theme}, ${width}px)`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:1000});
  await page.addInitScript(theme=>localStorage.setItem('uz_stock_analyzer_theme',theme),theme);
  await fixture(page,[{ticker:'HMKB',company_name:'Hamkorbank',sector:'finance'}]);
  const rows=[
    {ticker:'HMKB',name:'Hamkorbank',kind:'bank',period:'2025',standard:'NSBU',scope:'separate',roe:25.43,nim:7.54771480661079,cost_of_risk:2.7957533920595985,de:null,metric_reasons:{de:{code:'NOT_APPLICABLE'}}},
    {ticker:'UTHK',name:'Uz Tong Hong',kind:'industry',period:'2025',standard:'NSBU',scope:'separate',roe:90.18,pe:null,cg5:null,metric_reasons:{pe:{code:'MARKET_CAP_UNAVAILABLE'},cg5:{code:'NON_POSITIVE_ENDPOINT',start:'2020',end:'2025'},nim:{code:'NOT_APPLICABLE'},cost_of_risk:{code:'NOT_APPLICABLE'}}},
  ];
  await page.route('**/api/terminal/screener?**',r=>r.fulfill({json:{ok:true,rows,years:['2025']}}));
  await run(page,'EQS');
  const table=page.locator('.terminal-screener');
  const bank=table.getByRole('row').filter({has:page.getByRole('button',{name:'HMKB',exact:true})});
  await expect(bank).toContainText('7,55');
  await expect(bank).toContainText('2,8');
  const missing=bank.getByRole('button',{name:/HMKB · D\/E/});
  expect(await missing.evaluate(el=>getComputedStyle(el,'::before').content)).toBe('none');
  await missing.focus();
  await expect(page.getByRole('tooltip')).toContainText('не применяется');
  await missing.press('Escape');
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await table.getByRole('button',{name:/UTHK · CAGR/}).click();
  await expect(page.getByRole('tooltip')).toContainText('2020');
  await expect(page.getByRole('tooltip')).toContainText('прибыль');
  await page.screenshot({path:testInfo.outputPath('missing-ratio-explanation.png'),animations:'disabled'});
  await page.keyboard.press('Escape');
  const download=page.waitForEvent('download');
  await table.locator('..').getByRole('button',{name:'CSV',exact:true}).click();
  const {readFile}=await import('node:fs/promises');
  const csv=await readFile(await (await download).path(),'utf8');
  expect(csv).toContain('7,55');
  expect(csv).toContain('—');
  expect(csv).not.toContain('что это значит');
  await run(page,'HMKB RV');
  const peers=page.getByRole('heading',{name:'RV · Аналоги',exact:true}).locator('..').locator('table').first();
  await expect(peers).toContainText('7,55');
  await peers.getByRole('button',{name:/HMKB · D\/E/}).click();
  await expect(page.getByRole('tooltip')).toContainText('не применяется');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('RV calculates UZAL market ratios without letting inactive preferred shares block them', async ({page}, testInfo) => {
  await page.setViewportSize({width: 1440, height: 900});
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_theme', 'light'));
  // Feed the browser the actual backend calculations, not precomputed ratios.
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  const rows = JSON.parse(execFileSync(python, ['-c', `
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch
import public_contract
from server.terminal import analytics, service
data = json.loads(Path('tests/fixtures/terminal_uzal_uzml_20261102.json').read_text())
checked = public_contract.market_class_input
with patch.object(service, 'get_securities_map', return_value=data['securities']), \\
     patch('catalogue.market_store.get_all_listings', return_value=data['listings']), \\
     patch('catalogue.market_store.get_all_quotes', return_value=data['quotes']), \\
     patch.object(public_contract, 'market_class_input', side_effect=lambda row: checked(row, reference_date=date(2026, 11, 2))):
    market = service.market_context()
print(json.dumps([{'ticker': ticker, **analytics.snapshot(annual, kind='financial', market_cap=market[ticker]['market_cap']), **market[ticker]}
                  for ticker, annual in data['annuals'].items()]))
`], {encoding: 'utf8'}));
  await fixture(page, [{ticker: 'UZAL', company_name: 'O‘zagrolizing'}, {ticker: 'UZML', company_name: 'UzMED-lizing'}]);
  await page.route('**/api/terminal/screener?**', route => route.fulfill({json: {ok: true, rows, years: ['2025']}}));
  await run(page, 'UZAL RV');
  const screen = page.getByRole('heading', {name: 'RV · Аналоги', exact: true}).locator('..');
  const table = screen.locator('table').first();
  const uzal = table.getByRole('row').filter({has: page.getByRole('button', {name: 'UZAL', exact: true})}).getByRole('cell');
  const uzml = table.getByRole('row').filter({has: page.getByRole('button', {name: 'UZML', exact: true})}).getByRole('cell');
  await expect(uzal.nth(3)).toHaveText('65,74');
  await expect(uzal.nth(4)).toHaveText('1,52');
  await expect(uzal.nth(5)).toHaveText('1,68');
  await expect(uzal.nth(8)).toHaveText('12,91');
  await expect(uzml.nth(3)).toHaveText('—');
  await expect(uzml.nth(4)).toHaveText('-1,05');
  await expect(uzml.nth(5)).toHaveText('28,53');
  await expect(uzml.nth(8)).toHaveText('—');
  await screen.screenshot({path: testInfo.outputPath('rv-uzal-market-ratios-desktop.png')});
  await page.setViewportSize({width: 390, height: 844});
  await page.reload();
  await expect(uzal.nth(4)).toHaveText('1,52');
  await screen.screenshot({path: testInfo.outputPath('rv-uzal-market-ratios-mobile.png')});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

for (const [theme,width] of [['light',1440],['dark',390]]) test(`EQS template controls align, save filters, export CSV and restore (${theme}, ${width}px)`, async ({page},testInfo)=>{
  await page.setViewportSize({width,height:1000});
  await page.addInitScript(theme=>localStorage.setItem('uz_stock_analyzer_theme',theme),theme);
  await fixture(page);
  await run(page,"EQS");
  await expect(page.getByRole("heading",{name:/EQS/})).toBeVisible();
  const screen=page.locator('.terminal-market-screen');
  const template=screen.getByRole('textbox',{name:'Шаблон',exact:true});
  const save=screen.getByRole('button',{name:'Сохранить фильтры',exact:true});
  const saved=screen.getByRole('combobox',{name:'Сохранённые фильтры',exact:true});
  const reset=screen.getByRole('button',{name:'Сбросить',exact:true});
  const controls=[template,save,saved,reset];
  const boxes=await Promise.all(controls.map(control=>control.boundingBox()));
  expect(Math.max(...boxes.map(box=>box.height))-Math.min(...boxes.map(box=>box.height))).toBeLessThanOrEqual(1);
  if(width>600)expect(Math.max(...boxes.map(box=>box.y))-Math.min(...boxes.map(box=>box.y))).toBeLessThanOrEqual(1);
  for(const control of controls) {
    expect((await control.boundingBox()).height).toBeGreaterThanOrEqual(43.99);
    expect(await control.evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(14);
    expect(await control.evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeLessThanOrEqual(16);
    expect(await control.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
  }
  for(const control of [template,saved]) {
    expect(await control.evaluate(el=>el.closest('label')?.textContent)).toBeTruthy();
    expect(await control.evaluate(el=>parseFloat(getComputedStyle(el.closest('label')).fontSize))).toBeGreaterThanOrEqual(12);
  }
  const templateRow=template.locator('..').locator('..');
  await expect(save).toBeDisabled();
  await templateRow.screenshot({path:testInfo.outputPath('template-controls-empty.png')});
  await page.getByLabel("ROE ≥").fill("10");
  await expect(page.locator(".terminal-screener tbody tr")).toHaveCount(1);
  const templateName='Банки с рентабельностью капитала от 10%';
  await template.fill(templateName);
  await template.press('Tab');
  await expect(save).toBeFocused();
  expect(await save.evaluate(el=>getComputedStyle(el).outlineStyle)).not.toBe('none');
  await save.press('Enter');
  await expect(templateRow.getByRole('status')).toHaveText('Сохранено в этом браузере');
  await reset.click();
  await expect(page.locator('.terminal-screener tbody tr')).toHaveCount(2);
  await saved.selectOption(templateName);
  await expect(page.locator('.terminal-screener tbody tr')).toHaveCount(1);
  await expect(page.getByLabel('ROE ≥')).toHaveValue('10');
  await templateRow.screenshot({path:testInfo.outputPath('template-controls-saved.png')});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  const download = page.waitForEvent("download");
  await page.getByRole("button",{name:"CSV",exact:true}).first().click();
  expect((await download).suggestedFilename()).toContain("EQS");
  await page.reload();
  await expect(page.getByRole("heading",{name:/EQS/})).toBeVisible();
  await saved.selectOption(templateName);
  await expect(page.locator('.terminal-screener tbody tr')).toHaveCount(1);
});
test("issuer tabs omit the NSBU/IFRS reconciliation tab", async ({page}) => {
  await fixture(page);
  const tabs = page.locator('.terminal-tabs');
  await expect(tabs.getByRole('button', {name: /SUM/})).toBeVisible();
  await expect(tabs.getByRole('button', {name: /DQ/})).toBeVisible();
  await expect(tabs.getByRole('button', {name: /REC/})).toHaveCount(0);
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
      {...base,ticker:'AGBA',roe:year==='2024'?18:20},
      ...(year==='2023'?[]:[{...base,ticker:'ALKB',roe:year==='2024'?14:27}]),
      {...base,ticker:'WRONG',period:'2022',roe:99},
    ]}});
  });
  await run(page,'AGBA RV');
  const screen=page.getByRole('heading',{name:'RV · Аналоги',exact:true}).locator('..');
  const year=screen.getByRole('combobox',{name:'Год отчётности',exact:true});
  const peers=screen.locator('table').first();
  await expect(year).toHaveValue('');
  await expect(peers.locator('tbody tr')).toHaveCount(2);
  await expect(peers.locator('tbody tr').first()).toContainText('AGBA');
  await expect(peers.locator('tbody tr').first().getByRole('cell').nth(1)).toHaveText('20');
  await expect(peers).toContainText('27');
  await year.selectOption('2024');
  await expect(peers).toContainText('14');
  await expect(peers.locator('tbody tr').first().getByRole('cell').nth(1)).toHaveText('18');
  await expect(screen.locator('.terminal-bank-comparison tbody tr')).toHaveCount(2);
  await expect(screen).toContainText('2024 · bank');
  const bankCells=screen.locator('.terminal-bank-comparison tbody tr').first().getByRole('cell');
  await expect(bankCells.first()).toHaveText('4,2');
  expect(requests).toContain('2024');
  await page.screenshot({path:testInfo.outputPath('rv-year-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:testInfo.outputPath('rv-year-mobile.png'),fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await year.selectOption('2023');
  await expect(screen.getByText('Сопоставимые эмитенты не найдены',{exact:true})).toBeVisible();
  await expect(peers.locator('tbody tr')).toHaveCount(1);
  await expect(peers.locator('tbody tr').first()).toContainText('AGBA');
  await expect(screen.locator('.terminal-bank-comparison tbody tr')).toHaveCount(1);
  await expect(bankCells.first()).toHaveText('—');
  await year.selectOption('');
  await expect(peers).toContainText('27');
  await expect(bankCells.first()).toHaveText('5,1');
  await expect(screen.locator('.terminal-bank-sector')).toHaveCount(0);
});
for (const [theme, width] of [['light', 1440], ['dark', 390]]) {
  test(`RV includes UZAL before its financial peers and in CSV (${theme}, ${width}px)`, async ({page}, testInfo) => {
    await page.setViewportSize({width, height:900});
    await page.addInitScript(theme => localStorage.setItem('uz_stock_analyzer_theme', theme), theme);
    const errors=[];
    page.on('pageerror', error=>errors.push(error.message));
    await fixture(page, [
      {ticker:'UZAL',company_name:'O‘zagrolizing',sector:'finance',total_count:50},
      {ticker:'URTS',company_name:'Respublika tovar-xom ashyo birjasi',sector:'finance',total_count:10},
      {ticker:'UZML',company_name:'O‘zbeklizing',sector:'finance',total_count:10},
    ]);
    const base={kind:'financial',standard:'NSBU',scope:'separate',period:'2025'};
    await page.route('**/api/terminal/screener?**', route=>route.fulfill({json:{ok:true,years:['2025'],rows:[
      {...base,ticker:'URTS',roe:65.12},
      {...base,ticker:'UZML',roe:-26.05},
      {...base,ticker:'UZAL',roe:0,pe:null},
      {...base,ticker:'WRONG_KIND',kind:'bank'},
      {...base,ticker:'WRONG_STANDARD',standard:'MSFO'},
      {...base,ticker:'WRONG_SCOPE',scope:'consolidated'},
      {...base,ticker:'WRONG_YEAR',period:'2024'},
    ]}}));
    await page.locator('.terminal-tabs').getByRole('button',{name:/RV/}).click();
    const screen=page.getByRole('heading',{name:'RV · Аналоги',exact:true}).locator('..');
    const table=screen.locator('table').first();
    await expect(table.locator('tbody button')).toHaveText(['UZAL','URTS','UZML']);
    await expect(table.locator('tbody tr').first().getByRole('cell').nth(1)).toHaveText('0');
    await expect(table.locator('tbody tr').first().getByRole('cell').nth(3)).toHaveText('—');
    const download=page.waitForEvent('download');
    await screen.getByRole('button',{name:'CSV',exact:true}).click();
    const {readFile}=await import('node:fs/promises');
    const csv=await readFile(await (await download).path(),'utf8');
    expect(csv.split(/\r?\n/).filter(line=>/^(UZAL|URTS|UZML),/.test(line)).map(line=>line.split(',')[0])).toEqual(['UZAL','URTS','UZML']);
    await screen.screenshot({path:testInfo.outputPath('rv-selected-issuer.png')});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
    await table.getByRole('button',{name:'URTS',exact:true}).click();
    await expect(page).toHaveURL(url=>url.searchParams.get('t')==='URTS'&&(url.searchParams.get('f')||'SUM')==='SUM');
    await expect(page.locator('.terminal-tabs').getByRole('button',{name:/SUM/})).toHaveAttribute('aria-current','page');
    await expect(page.getByRole('heading',{name:'Respublika tovar-xom ashyo birjasi',exact:true})).toBeVisible();
    expect(errors).toEqual([]);
  });
}

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

test('DQ loads both NSBU history frequencies with the accepted scope contract', async ({page}) => {
  await fixture(page);
  await run(page, 'AGBA DQ');
  await expect(page.locator('.terminal-dq')).toBeVisible();
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

for(const [theme,width] of [['light',1440],['dark',390]]) test(`EQS and RV keep bank figures without date/source columns (${theme}, ${width}px)`, async ({page},testInfo)=>{
  await page.setViewportSize({width,height:1000});
  await page.addInitScript(theme=>localStorage.setItem('uz_stock_analyzer_theme',theme),theme);
  await fixture(page);
  const rows=['AGBA','HMKB'].map((ticker,i)=>({ticker,name:ticker,kind:'bank',standard:'NSBU',scope:'separate',period:'2025',roe:20,pb:1,years:['2025'],
    cbu_assets_share_pct:i?4.2:12.5,cbu_loans_share_pct:0,cbu_equity_share_pct:null,cbu_deposits_share_pct:8.91,
    cbu_household_loans_bn:i?100:200,cbu_company_loans_bn:300,cbu_household_deposits_bn:90,cbu_company_deposits_bn:150,
    cbu:{main:{date:'2026-09-01',source_url:'https://cbu.uz/main.xlsx'},structure:{date:'2026-09-01',source_url:'https://cbu.uz/structure.xlsx'}}}));
  const sectorSeries={
    capital:{date:'2026-10-01',source_url:'https://cbu.uz/capital.xlsx',metrics:{capital_adequacy:{value:18.18}}},
    profitability:{date:'2026-10-01',source_url:'https://cbu.uz/profitability.xlsx',metrics:{roe:{value:14.07},nim:{value:4.24}}},
  };
  await page.route('**/api/terminal/screener?**',r=>{
    const historical=new URL(r.request().url()).searchParams.get('year')==='2024';
    return r.fulfill({json:{ok:true,rows:historical?rows.map(row=>({...row,period:'2024'})):rows,years:['2025','2024'],sector_series:historical?{
      capital:{metrics:{capital_adequacy:{value:0}}},profitability:{metrics:{roe:{value:null}}},
    }:sectorSeries,deposit:null}});
  });
  const comparison=page.locator('.terminal-bank-comparison');
  const sector=comparison.locator('.terminal-bank-sector');
  const headers=['Банк','Доля активов, %','Доля кредитов, %','Доля капитала, %','Доля депозитов, %','Кредиты физлиц','Кредиты юрлиц','Депозиты физлиц','Депозиты юрлиц'];
  async function checkFigures(mode) {
    await expect(comparison.getByRole('columnheader')).toHaveText(headers);
    await expect(comparison.locator('table a')).toHaveCount(0);
    const agba=comparison.getByRole('row').filter({has:page.getByRole('rowheader',{name:'AGBA',exact:true})});
    await expect(agba.getByRole('cell')).toHaveText(['12,5','0','—','8,91','200','300','90','150']);
    await expect(comparison).not.toContainText('2026-10-01');
    await expect(sector.getByRole('heading',{name:'Банковский сектор · ЦБ',exact:true})).toBeVisible();
    await expect(sector.locator('dt')).toHaveText(['Достаточность капитала','ROE','NIM']);
    await expect(sector.locator('dd')).toHaveText(['18,18%','14,07%','4,24%']);
    await expect(sector.getByRole('link',{name:'Достаточность капитала',exact:true})).toHaveAttribute('href','https://cbu.uz/capital.xlsx');
    await expect(sector.getByRole('link',{name:'ROE',exact:true})).toHaveAttribute('href','https://cbu.uz/profitability.xlsx');
    await sector.getByRole('link',{name:'ROE',exact:true}).focus();
    expect(await sector.getByRole('link',{name:'ROE',exact:true}).evaluate(el=>getComputedStyle(el).outlineStyle)).not.toBe('none');
    for(const text of await sector.locator('dt, dd').all()) {
      expect(await text.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
      expect(await text.evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(12);
    }
    await sector.screenshot({path:testInfo.outputPath(`bank-sector-${mode}.png`)});
    await comparison.screenshot({path:testInfo.outputPath(`bank-comparison-${mode}.png`)});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  }
  await run(page,'EQS');
  await checkFigures('eqs');
  const pendingDownload=page.waitForEvent('download');
  await comparison.getByRole('button',{name:'CSV',exact:true}).click();
  const {readFile}=await import('node:fs/promises');
  const csv=await readFile(await (await pendingDownload).path(),'utf8');
  expect(csv).not.toMatch(/дата \/ источник|2026-09-01/);
  expect(csv).toContain('AGBA,"12,5",0,—,"8,91",200,300,90,150');
  await page.getByLabel('Доля активов ЦБ ≥').fill('10');
  await expect(comparison.locator('tbody tr')).toHaveCount(1);
  await run(page,'AGBA RV');
  await expect(comparison).toContainText('HMKB');
  await checkFigures('rv');
  await page.getByRole('combobox',{name:'Год отчётности',exact:true}).selectOption('2024');
  await expect(sector.locator('dt')).toHaveText(['Достаточность капитала','ROE']);
  await expect(sector.locator('dd')).toHaveText(['0%','—']);
  await expect(sector.getByRole('link')).toHaveCount(0);
});
