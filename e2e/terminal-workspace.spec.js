import { test, expect } from "@playwright/test";
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import {expectFullWidth} from './helpers/full-width.js';

async function fixture(page, companies = [{ticker:"AGBA",company_name:"Агробанк",sector:"finance",total_count:6}, {ticker:"QZSM",company_name:"Кызылкумцемент",sector:"manufacturing",total_count:5}], user = {id:1,is_admin:true,email:"admin@example.test"}, start = "/catalog?f=CF") {
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_token', 'admin-token'));
  let preferences = {};
  const rows = companies.map((c,i)=>({...c,name:c.company_name,kind:i?"industry":"bank",standard:"NSBU",scope:"separate",period:"2025",roe:i?8:20,pb:1,pe:8,de:i?2:null,cg5:10,dy:12,issues:[]}));
  await page.route("**/api/**", route => {
    const u = new URL(route.request().url());
    const json = body => route.fulfill({contentType:"application/json",body:JSON.stringify(body)});
    if(u.pathname==="/api/auth/me") return json({user});
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
  // Tests install their screen-specific responses after this shared setup.
  // Start on filings so SUM cannot cache placeholder analytics/history first.
  await page.goto(start);
  if (start.startsWith("/catalog")) await expect(page.getByRole("heading",{name:companies[0].company_name,exact:true})).toBeVisible();
}
async function run(page, text) {
  await page.locator('.terminal-command').getByRole("combobox").fill(text);
  await page.locator('.terminal-command').getByRole("combobox").press("Enter");
}

for (const [ticker,expected] of [['CBSK','0,18 ×'],['QATT','0,09 ×']])
for (const width of [1440, 390]) test(`${ticker} verified debt remains visible despite an unrelated profit discrepancy (${width}px)`, async ({page},testInfo) => {
  await page.setViewportSize({width,height:1000});
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  const report = JSON.parse(execFileSync(python, ['-c', `
import json
from pathlib import Path
from financial_columns import nsbu, observations
from financial_analysis.report_investor_metrics import calculate
case = json.loads(Path('tests/fixtures/${ticker.toLowerCase()}_2026q3_investor_inputs.json').read_text(encoding='utf8'))
report = case['report']
if case.get('source_fixture'):
    sources = json.loads((Path('tests/fixtures') / case['source_fixture']).read_text(encoding='utf8'))
    doc = next(d for d in sources['${ticker}']['documents'] if d['period_end'] == report['financial_as_of'])
else:
    doc = dict(issuer_id=report['issuer']['id'], scope='separate', period_end=report['financial_as_of'],
               unit_scale='1000', currency='UZS', quality='valid', source_version=case['source']['source_url'],
               rows=nsbu.rows(case['source'], template='general'))
rows = observations.nsbu([doc])
observations.check(rows)
print(json.dumps({**report, 'ratios': calculate(report, rows)}))
`], {encoding: 'utf8'}));
  await fixture(page,[{ticker,company_name:report.issuer.name,sector:'trade'}]);
  await page.route(`**/api/v1/issuers/${ticker}/ai-report?**`,r=>r.fulfill({json:report}));
  await run(page,`${ticker} RAT`);
  const table=page.locator('.terminal-sector-metrics');
  await expect(table).toContainText('2026Q3');
  await expect(table.getByRole('row').filter({hasText:'Долг / капитал'})).toContainText(expected);
  const pb=table.getByRole('row').filter({hasText:'P/BV'});
  await expect(pb).toContainText('число обычных акций на отчётную дату');
  await expect(pb).toContainText('2026-11-06');
  await expect(pb).not.toContainText('актуальной котировки');
  await expect(table.getByRole('row').filter({hasText:'Базовая прибыль'})).toContainText('средневзвешенное число обычных акций');
  expect(await table.locator('.terminal-table-wrap').evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await table.screenshot({path:testInfo.outputPath(`${ticker.toLowerCase()}-ratios-${width}.png`)});
});

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
  const industry=table.getByRole('row').filter({has:page.getByRole('button',{name:'UTHK',exact:true})});
  for(const index of [10,11,12]) await expect(industry.getByRole('cell').nth(index)).toBeEmpty();
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

for(const [theme,width] of [['light',1440],['dark',390]]) test(`credit metrics appear only for banks and leasing across EQS, RV and RAT (${theme}, ${width}px)`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:1000});
  await page.addInitScript(theme=>localStorage.setItem('uz_stock_analyzer_theme',theme),theme);
  const companies=[
    {ticker:'UTHK',company_name:'Uz Tong Hong',kind:'industry',credit_metrics_applicable:false},
    {ticker:'URTS',company_name:'Respublika tovar-xom ashyo birjasi',kind:'financial',credit_metrics_applicable:false},
    {ticker:'UZAL',company_name:'O‘zagrolizing',kind:'financial',credit_metrics_applicable:true},
    {ticker:'ALSK',company_name:'Alskom',kind:'insurance',credit_metrics_applicable:false},
    {ticker:'HMKB',company_name:'Hamkorbank',kind:'bank',credit_metrics_applicable:true},
  ];
  const rows=companies.map(c=>({...c,name:c.company_name,period:'2025',standard:'NSBU',scope:'separate',roe:20,npl:null,nim:null,cost_of_risk:null}));
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await fixture(page,companies);
  await page.route('**/api/terminal/screener?**',route=>route.fulfill({json:{ok:true,rows,years:['2025']}}));
  await page.route('**/api/terminal/issuer/*/analytics?**',route=>{
    const ticker=new URL(route.request().url()).pathname.split('/').at(-2);
    return route.fulfill({json:{ok:true,snapshot:rows.find(r=>r.ticker===ticker),growth:[],quarters:{rows:[]}}});
  });
  const creditHeaders=/^(NPL|NIM|CoR), %/;
  await run(page,'EQS');
  const screen=page.locator('.terminal-market-screen');
  const table=screen.locator('.terminal-screener');
  await screen.getByRole('combobox',{name:'Тип',exact:true}).selectOption('industry');
  await expect(table.getByRole('columnheader').filter({hasText:creditHeaders})).toHaveCount(0);
  await expect(screen.getByLabel('NIM ≥', {exact:true})).toHaveCount(0);
  await expect(table.locator('tbody tr')).toHaveCount(1);
  await screen.screenshot({path:testInfo.outputPath('credit-metrics-industry.png')});
  const download=page.waitForEvent('download');
  await screen.getByRole('button',{name:'CSV',exact:true}).click();
  const {readFile}=await import('node:fs/promises');
  const csv=await readFile(await (await download).path(),'utf8');
  expect(csv).not.toMatch(/NPL|NIM|CoR/);
  await screen.getByRole('combobox',{name:'Тип',exact:true}).selectOption('financial');
  await expect(table.getByRole('columnheader').filter({hasText:creditHeaders})).toHaveCount(3);
  for(const [ticker,expected] of [['UZAL','—'],['URTS','']]) {
    const cells=table.getByRole('row').filter({has:page.getByRole('button',{name:ticker,exact:true})}).getByRole('cell');
    for(const index of [10,11,12]) await expect(cells.nth(index)).toHaveText(expected);
  }
  // A hidden credit filter must not empty an unrelated sector after switching types.
  await screen.getByLabel('NIM ≥',{exact:true}).fill('1');
  await screen.getByRole('combobox',{name:'Тип',exact:true}).selectOption('insurance');
  await expect(table.locator('tbody tr')).toHaveCount(1);
  await expect(table.getByRole('columnheader').filter({hasText:creditHeaders})).toHaveCount(0);
  for(const [ticker,count] of [['UTHK',0],['URTS',0],['UZAL',3],['HMKB',3]]) {
    await run(page,`${ticker} RV`);
    const peers=page.getByRole('heading',{name:'RV · Аналоги',exact:true}).locator('..');
    await expect(peers.locator('table').first().locator('tbody button').first()).toHaveText(ticker);
    await expect(peers.locator('table').first().getByRole('columnheader').filter({hasText:creditHeaders})).toHaveCount(count);
    if(ticker==='URTS'||ticker==='UZAL')await peers.screenshot({path:testInfo.outputPath(`credit-metrics-${ticker}.png`)});
    await run(page,`${ticker} RAT`);
    const annual=page.locator('.terminal-annual-ratios');
    await expect(annual).toBeVisible();
    await expect(annual.getByRole('row').filter({hasText:/^(NIM|CoR), %/})).toHaveCount(count?2:0);
  }
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  expect(errors).toEqual([]);
});

for(const theme of ['light','dark']) test(`RV comparison stays readable with sticky labels and accessible exports (${theme})`,async({page},testInfo)=>{
  await page.setViewportSize({width:2260,height:1000});
  await page.addInitScript(theme=>localStorage.setItem('uz_stock_analyzer_theme',theme),theme);
  // Reproduce the industrial peer table, including losses, >100 P/E and missing dividends.
  const examples=[
    ['BIOK',13.24,11.31,6.21,16.09,.69,.08,null,10.43],
    ['BTRL',10.99,5.84,39.04,2.56,4.16,.7,1.29,-8.24],
    ['CBSK',25.1,23.18,7.98,12.53,1.8,.09,7.65,15.84],
    ['DORI',-23.38,-8.32,null,-35.66,.66,1.8,null,null],
    ['FRAZP',5.42,4.52,null,null,null,.14,null,-19.04],
    ['JASM',9.52,2.5,15.48,6.46,1.37,2.11,null,7.02],
    ['KVTS',.56,.21,244,.41,1.37,1.35,.21,-50.92],
    ['METQ',48.41,13.54,4.08,24.53,1.6,3.68,null,144.15],
    ['MIQE',7.17,6.36,16.91,5.92,1.18,.08,5.91,20.34],
    ['NGQS',6.59,2.54,42.11,2.37,2.63,1.46,.59,51.05],
    ['OHDN',6.85,1.88,11.64,8.59,.77,2.2,null,-24.99],
    ['ORGS',null,null,6.09,16.42,null,null,null,10.77],
    ['PLST',-145.47,-24.78,null,null,null,2.16,null,null],
    ['QATT',3.64,3.07,23.3,4.29,.86,.19,1.93,4.56],
    ['QZSM',.03,.03,625,.16,.21,.31,null,-72.08],
    ['SANE',3.55,3.41,232,.43,8.2,.04,.8,69.57],
    ['TGPG',9.52,7.33,74.4,1.34,6.82,.25,.55,-25.49],
    ['TKDM',-31.26,-3.98,null,-56.1,.66,7.68,null,null],
    ['UPOS',.54,.2,1000,.1,4.35,1.59,.05,26.66],
    ['UQEQ',41.89,11.29,7.37,13.56,1.99,1.99,.81,28.41],
    ['UTHK',90.18,17.6,null,null,null,2.56,null,null],
  ];
  const rows=examples.map(([ticker,roe,roa,pe,ep,pb,de,dy,cg5])=>({ticker,roe,roa,pe,ep,pb,de,dy,cg5,kind:'industry',standard:'NSBU',scope:'separate',period:'2025',credit_metrics_applicable:false,
    metric_reasons:{...(dy==null?{dy:{code:'NO_RECENT_DIVIDEND'}}:{}),...(pe==null?{pe:{code:'NON_POSITIVE_PROFIT'}}:{})}}));
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await fixture(page,rows.map(row=>({ticker:row.ticker,company_name:row.ticker,sector:'industry'})));
  await page.route('**/api/terminal/screener?**',route=>route.fulfill({json:{ok:true,rows,years:['2025']}}));
  await run(page,'BIOK RV');
  const screen=page.getByRole('heading',{name:'RV · Аналоги',exact:true}).locator('..');
  const table=screen.locator('table').first();
  await expect(table.locator('tbody tr')).toHaveCount(21);
  const card=screen.locator('.terminal-peer-card');
  await expectFullWidth(card,'.terminal-peers-screen');
  const scroll=card.getByRole('region',{name:'Сравнение показателей',exact:true});
  await expect(table.getByRole('columnheader')).toHaveText(['Эмитент','ROE, %','ROA, %','P/E','E/P, %','P/B','D/E','DVD¹, %','CAGR 5Y, %']);
  const selected=table.getByRole('row').filter({has:page.getByRole('rowheader',{name:'BIOK',exact:true})});
  await expect(selected.getByRole('cell')).toHaveText(['13,24','11,31','6,21','16,09','0,69','0,08','—','10,43']);
  await expect(table.getByRole('row').filter({has:page.getByRole('rowheader',{name:'KVTS',exact:true})})).toContainText('>100');
  expect(await selected.evaluate(el=>getComputedStyle(el).backgroundColor)).not.toBe(await table.locator('tbody tr').nth(1).evaluate(el=>getComputedStyle(el).backgroundColor));
  for(const width of [2260,390]) {
    await page.setViewportSize({width,height:1000});
    await expectFullWidth(card,'.terminal-peers-screen');
    await scroll.evaluate(el=>{el.scrollTop=0;el.scrollLeft=0;});
    for(const cell of await table.locator('thead th,tbody tr:first-child th,tbody tr:first-child td').all()) {
      expect((await cell.boundingBox()).height).toBeGreaterThanOrEqual(44);
      expect(await cell.evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(12);
    }
    expect(await selected.getByRole('cell').first().evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(14);
    const issuer=selected.getByRole('rowheader'),header=table.getByRole('columnheader',{name:'Эмитент',exact:true});
    await scroll.focus();
    await expect(scroll).toBeFocused();
    expect(await scroll.evaluate(el=>getComputedStyle(el).outlineStyle)).not.toBe('none');
    const before=await issuer.boundingBox();
    if(width<600) {
      await scroll.press('ArrowRight');
      await expect.poll(()=>scroll.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
      await scroll.evaluate(el=>{el.scrollLeft=el.scrollWidth;});
      expect(Math.abs((await issuer.boundingBox()).x-before.x)).toBeLessThanOrEqual(1);
    }
    const headerY=(await header.boundingBox()).y;
    await scroll.evaluate(el=>{el.scrollTop=300;});
    expect(Math.abs((await header.boundingBox()).y-headerY)).toBeLessThanOrEqual(1);
    await scroll.evaluate(el=>{el.scrollTop=0;el.scrollLeft=0;});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
    await card.screenshot({path:testInfo.outputPath(`peer-comparison-${width}.png`),animations:'disabled'});
  }
  const missing=selected.getByRole('button',{name:/BIOK · DVD/});
  await missing.focus();
  await expect(page.getByRole('tooltip')).toContainText('366');
  await missing.press('Escape');
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  const csv=card.getByRole('button',{name:'CSV',exact:true});
  expect((await csv.boundingBox()).height).toBeGreaterThanOrEqual(44);
  await csv.focus();
  expect(await csv.evaluate(el=>getComputedStyle(el).outlineStyle)).not.toBe('none');
  const download=page.waitForEvent('download');await csv.press('Enter');
  const {readFile}=await import('node:fs/promises');
  const content=await readFile(await (await download).path(),'utf8');
  expect(content).toContain('BIOK,"13,24","11,31","6,21","16,09","0,69","0,08",—,"10,43"');
  expect(content).not.toMatch(/NPL|NIM|CoR|что это значит/);
  await table.getByRole('button',{name:'BTRL',exact:true}).click();
  await expect(page).toHaveURL(url=>url.searchParams.get('t')==='BTRL'&&(url.searchParams.get('f')||'SUM')==='SUM');
  expect(errors).toEqual([]);
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
  const uzal = table.getByRole('row').filter({has: page.getByRole('button', {name: 'UZAL', exact: true})}).locator('th,td');
  const uzml = table.getByRole('row').filter({has: page.getByRole('button', {name: 'UZML', exact: true})}).locator('th,td');
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
  await expect(peers.locator('tbody tr').first().getByRole('cell').first()).toHaveText('20');
  await expect(peers).toContainText('27');
  await year.selectOption('2024');
  await expect(peers).toContainText('14');
  await expect(peers.locator('tbody tr').first().getByRole('cell').first()).toHaveText('18');
  await expect(screen.locator('.terminal-bank-comparison tbody tr')).toHaveCount(2);
  await expect(screen).toContainText('2024 · Банки');
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
    await expect(screen).toContainText('Финансовые компании');
    await expect(screen).not.toContainText('financial');
    await expect(table.locator('tbody tr').first().getByRole('cell').first()).toHaveText('0');
    await expect(table.locator('tbody tr').first().getByRole('cell').nth(2)).toHaveText('—');
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
  await run(page, 'AGBA SUM');
  await expect(page.locator('.terminal-summary')).toBeVisible();
  await expect(page.locator(".catalog-price-card")).toHaveCount(0);
  expect(prices).toEqual([]);
});

test("PL converts each year at its own CBU closing rate with a brief summary and no rate links", async({page}, testInfo)=>{
  await fixture(page);
  let missingRate = false;
  await page.route('**/api/currency/rates?as_of=*',route=>{
    const day=new URL(route.request().url()).searchParams.get('as_of');
    return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,as_of:day,rates:missingRate && day.startsWith('2024') ? [] : [{ccy:'USD',per_unit:day.startsWith('2025')?10000:9000,effective_date:day}]})});
  });
  await run(page,'AGBA PL');
  await page.getByText('Ранее опубликованные показатели', { exact: true }).click();
  await page.getByLabel('Валюта').selectOption('USD');
  const summary = page.locator('.terminal-fx-rates');
  await expect(summary).toHaveText('Пересчёт в USD — по курсу ЦБ на конец каждого отчётного периода.');
  await expect(summary.locator('a, ul, li, summary')).toHaveCount(0);
  await expect(page.locator('.fin-note').filter({hasText:'Суммы в USD'})).toBeVisible();
  await page.locator('[data-currency=USD]').getByRole('button',{name:'Таблица',exact:true}).click();
  await expect(page.locator('.fin-table')).toContainText(/2[\s\u00a0]000[\s\u00a0]000/);
  const pendingDownload=page.waitForEvent('download');
  await page.locator('[data-currency=USD]').getByRole('button',{name:'CSV',exact:true}).click();
  const downloaded=await pendingDownload;
  const {readFile}=await import('node:fs/promises');
  expect(await readFile(await downloaded.path(),'utf8')).toContain('Currency,USD');
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:testInfo.outputPath('fx-summary-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await summary.scrollIntoViewIfNeeded();
  expect((await summary.boundingBox()).height).toBeLessThan(100);
  await page.screenshot({path:testInfo.outputPath('fx-summary-mobile.png')});
  await page.goto('/company/AGBA?tab=financials');
  await page.getByLabel('Валюта').selectOption('USD');
  await expect(summary).toHaveText('Пересчёт в USD — по курсу ЦБ на конец каждого отчётного периода.');
  await expect(summary.locator('a, ul, li, summary')).toHaveCount(0);
  await summary.scrollIntoViewIfNeeded();
  await page.screenshot({path:testInfo.outputPath('company-fx-summary-mobile.png')});
  await page.getByLabel('Валюта').selectOption('UZS');
  await expect(summary).toHaveCount(0);
  missingRate = true;
  await page.getByLabel('Валюта').selectOption('USD');
  await expect(summary).toContainText('Нет курса для 1 из 2 периодов — суммы за них скрыты.');
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

for(const [theme,width] of [['light',2260],['dark',1440],['light',390],['dark',390]]) test(`RAT keeps readable ratio sections without internal method codes (${theme}, ${width}px)`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:900});
  await page.addInitScript(theme=>localStorage.setItem('uz_stock_analyzer_theme',theme),theme);
  const report=JSON.parse(readFileSync(new URL('../tests/fixtures/profitability_display.json',import.meta.url),'utf8'));
  await fixture(page,[{ticker:report.ticker,company_name:'Узметкомбинат',sector:'manufacturing'}]);
  await page.route('**/api/v1/issuers/UZMK/ai-report?*',route=>route.fulfill({json:{...report,status:'available',scope:'separate'}}));
  await page.route('**/api/terminal/issuer/UZMK/analytics?*',route=>route.fulfill({json:{ok:true,
    snapshot:{period:'2025',kind:'industry',roe:13.24,roa:11.31,ep:16.09,de:0.08,cg5:10.43},
    growth:['net_profit','total_equity','total_assets'].flatMap((field,i)=>[3,5].map(years=>({field,years,start:String(2025-years),end:'2025',nominal:10.43+i,real:0,usd:null}))),
    quarters:{rows:[]},
  }}));
  await run(page,'UZMK RAT');
  const section=page.locator('.terminal-sector-metrics');
  const table=section.getByRole('table');
  await expect(table.locator('thead th')).toHaveText(['Показатель',report.period]);
  await expect(table.locator('tbody tr')).toHaveCount(report.ratios.length);
  await expect(table).toContainText('Текущая ликвидность');
  await expect(table).toContainText('Абсолютная ликвидность');
  await expect(section).not.toContainText('separate');
  await expect(table).not.toContainText('current_ratio');
  await expect(table).not.toContainText('quick_ratio');
  for(const row of await table.locator('tbody tr').all())await expect(row.locator('th,td')).toHaveCount(2);
  await expect(table.locator('tbody tr').first().getByRole('cell')).toHaveText('2,14%');
  await expect(section).not.toContainText('nsbu-enterprise-profitability');
  await expect(section).not.toContainText('period-returns-1.0');
  await table.locator('tbody tr').first().getByRole('button').click();
  await expect(page.getByRole('tooltip')).toContainText(report.ratios[0].meaning_ru);
  await page.keyboard.press('Escape');
  const download=page.waitForEvent('download');
  await section.getByRole('button',{name:'CSV',exact:true}).click();
  const {readFile}=await import('node:fs/promises');
  const csv=await readFile(await (await download).path(),'utf8');
  expect(csv).toContain('2,14%');
  expect(csv).not.toMatch(/Метод \/ причина пропуска|nsbu-enterprise-|period-returns-/);
  expect(await table.locator('tbody td').evaluateAll(cells=>cells.every(cell=>{
    const text=document.createRange();text.selectNodeContents(cell);
    return text.getBoundingClientRect().height<=parseFloat(getComputedStyle(cell).lineHeight)+1;
  }))).toBe(true);
  await section.screenshot({path:testInfo.outputPath('rat-without-method-codes.png')});
  expect(await table.evaluate(el=>el.scrollWidth<=el.closest('.terminal-table-wrap').clientWidth+1)).toBe(true);
  const annual=page.locator('.terminal-annual-ratios');
  await expectFullWidth(page.locator('.terminal-ratio-overview'),'.terminal-analytics');
  const heights=await annual.getByRole('row').evaluateAll(rows=>rows.map(row=>row.getBoundingClientRect().height));
  expect(Math.min(...heights)).toBeGreaterThanOrEqual(44);
  expect(Math.max(...heights)-Math.min(...heights)).toBeLessThanOrEqual(1);
  const topBorders=await annual.getByRole('row').first().locator('th,td').evaluateAll(cells=>cells.map(cell=>getComputedStyle(cell).borderTopWidth));
  expect(new Set(topBorders).size).toBe(1);
  const annualHeading=page.getByRole('heading',{name:'Годовые показатели',exact:true});
  await expect(annualHeading).toBeVisible();
  expect(await annualHeading.evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(18);
  const roe=annual.getByRole('row').filter({hasText:'ROE, %'});
  await expect(roe.getByRole('cell')).toHaveText('13,24');
  expect(await roe.getByRole('cell').evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16);
  await roe.getByRole('button').focus();
  await expect(page.getByRole('tooltip')).toBeVisible();
  await page.keyboard.press('Escape');
  const annualCard=annual.locator('..').locator('..');
  const growthCard=page.getByRole('heading',{name:'CAGR',exact:true}).locator('..').locator('..');
  const annualBox=await annualCard.boundingBox(), growthBox=await growthCard.boundingBox();
  if(width>=1440){
    expect(Math.abs(annualBox.y-growthBox.y)).toBeLessThanOrEqual(1);
    expect(growthBox.x-annualBox.x-annualBox.width).toBeCloseTo(16,0);
  }else {
    expect(growthBox.y).toBeGreaterThanOrEqual(annualBox.y+annualBox.height);
    await expectFullWidth(annualCard,'.terminal-ratio-overview');
    await expectFullWidth(growthCard,'.terminal-ratio-overview');
  }
  await expect(growthCard).toContainText('2022–2025');
  await expect(growthCard).toContainText('10,43');
  const annualDownload=page.waitForEvent('download');
  await annualCard.getByRole('button',{name:'CSV',exact:true}).click();
  expect(await readFile(await (await annualDownload).path(),'utf8')).toContain('"ROE, %","13,24"');
  await page.locator('.terminal-ratio-overview').screenshot({path:testInfo.outputPath('annual-ratios-layout.png'),style:'.topbar {visibility:hidden}'});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

for(const theme of ['light','dark']) test(`quarterly profit and LTM stay readable and export billions (${theme})`, async ({page}, testInfo) => {
  await page.setViewportSize({width:2260,height:1050});
  await page.addInitScript(theme=>localStorage.setItem('uz_stock_analyzer_theme',theme),theme);
  await fixture(page);
  await page.route('**/api/terminal/issuer/AGBA/analytics?*', route => route.fulfill({json: {
    ok: true, snapshot: {period: '2025', kind: 'bank'}, growth: [], template: {selected_template: 'bank'},
    quarters: {rows: [
      {period: '2022Q1', value: 0, yoy: -99.92, ltm: 4200000000, seasonality: 0.03, cg3: -86.54},
      {period: '2022Q4', value: 2690000000, yoy: 843.86, ltm: 6940000000, seasonality: 38.78, cg3: 58.52},
      {period: '2023Q1', value: 630000000, yoy: 27233.24, ltm: 7560000000, seasonality: 6.2, cg3: -25.67},
      {period: '2024Q2', value: 3170000000, yoy: 249.91, ltm: 14850000000, seasonality: 21.01, cg3: 11.29},
      {period: '2025Q4', value: 5440000000, yoy: 1.95, ltm: 13240000000, seasonality: 41.11, cg3: 26.48},
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
  await expectFullWidth(page.locator('.terminal-quarterly-overview'),'.terminal-analytics');
  for(const row of await table.locator('tbody tr').all())expect((await row.boundingBox()).height).toBeGreaterThanOrEqual(44);
  expect(await cells('2026Q3').first().evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(14);
  const wrapper = table.locator('..');
  const card=wrapper.locator('..');
  await expectFullWidth(card,'.terminal-quarterly-overview');
  const heading=card.getByRole('heading',{name:'Кварталы · чистая прибыль',exact:true});
  expect(await heading.evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(18);
  expect((await wrapper.getByRole('button',{name:'CSV',exact:true}).boundingBox()).height).toBeGreaterThanOrEqual(44);
  const heatmap=page.locator('.terminal-heatmap');
  await expectFullWidth(page.locator('.terminal-heatmap-card'),'.terminal-quarterly-overview');
  await expect(heatmap.locator('tbody tr')).toHaveCount(5);
  await expect(heatmap.getByRole('row').filter({has:page.getByRole('rowheader',{name:'2023',exact:true})}).getByRole('cell').first()).toHaveText(/27\s233,24/);
  await expect(heatmap.getByRole('row').filter({has:page.getByRole('rowheader',{name:'2026',exact:true})}).getByRole('cell')).toHaveText(['-5,2','0','10,73','—']);
  expect(await heatmap.getByRole('cell').evaluateAll(cells=>cells.every(cell=>getComputedStyle(cell).opacity==='1'&&cell.scrollWidth<=cell.clientWidth+1))).toBe(true);
  const contrast=await page.locator('.terminal-quarterly-overview td.positive, .terminal-quarterly-overview td.negative').evaluateAll(cells=>{
    const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
    const ctx=canvas.getContext('2d');
    const luminance=color=>{
      ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);
      return Array.from(ctx.getImageData(0,0,1,1).data).slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
    };
    return cells.map(cell=>{
      const style=getComputedStyle(cell);
      const ink=luminance(style.color),paper=luminance(style.backgroundColor==='rgba(0, 0, 0, 0)'?getComputedStyle(cell.closest('.terminal-ratio-card')).backgroundColor:style.backgroundColor);
      return (Math.max(ink,paper)+.05)/(Math.min(ink,paper)+.05);
    });
  });
  expect(Math.min(...contrast)).toBeGreaterThanOrEqual(4.5);
  const pendingDownload = page.waitForEvent('download');
  await wrapper.getByRole('button', {name: 'CSV', exact: true}).click();
  const {readFile} = await import('node:fs/promises');
  const csv = await readFile(await (await pendingDownload).path(), 'utf8');
  expect(csv).toContain('Квартал,млрд UZS,"YoY, %","LTM, млрд UZS"');
  expect(csv).toMatch(/2026Q3,"510,46","10,73","1\s917,59",—,"10,75"/);
  const overview=page.locator('.terminal-quarterly-overview');
  await heatmap.locator('..').locator('..').screenshot({path:testInfo.outputPath('quarterly-heatmap-desktop.png')});
  await card.screenshot({path:testInfo.outputPath('quarterly-table-desktop.png')});
  await overview.screenshot({path:testInfo.outputPath('quarterly-desktop.png'),style:'.topbar, .topbar * {visibility:hidden !important}'});
  await page.setViewportSize({width: 390, height: 844});
  await expectFullWidth(overview,'.terminal-analytics');
  await expectFullWidth(card,'.terminal-quarterly-overview');
  await expectFullWidth(page.locator('.terminal-heatmap-card'),'.terminal-quarterly-overview');
  await wrapper.focus();
  await expect(wrapper).toBeFocused();
  const periodCell=table.locator('tbody th').first(), periodLeft=(await periodCell.boundingBox()).x;
  await wrapper.press('ArrowRight');
  expect(await wrapper.evaluate(el=>getComputedStyle(el).outlineStyle)).not.toBe('none');
  await expect.poll(()=>wrapper.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
  expect(Math.abs((await periodCell.boundingBox()).x-periodLeft)).toBeLessThanOrEqual(1);
  await wrapper.evaluate(el=>{el.scrollLeft=0;});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await overview.screenshot({path:testInfo.outputPath('quarterly-mobile.png'),style:'.topbar, .topbar * {visibility:hidden !important}'});
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

for (const [role,user,admin] of [['guest',null,false],['member',{id:2},false],['pro',{id:3,pro_access:true},false],['admin',{id:1,is_admin:true},true],['administrator',{id:1,admin_role:'administrator'},true]]) test(`company presentation changes are admin-only: ${role}`,async({page})=>{
  await fixture(page,undefined,user,"/market");
  await page.route("**/api/market/multiples?**",route=>route.fulfill({json:{ok:true,items:[{ticker:"AGBA",pe:{value:8,status:"ok",base_period:"2025"}}]}}));
  await page.route('**/api/currency/rates?as_of=*',route=>{
    const day=new URL(route.request().url()).searchParams.get('as_of');
    return route.fulfill({json:{ok:true,as_of:day,rates:[{ccy:'USD',per_unit:10000,effective_date:day}]}});
  });
  await page.goto('/company/AGBA');
  await expect.soft(page.getByRole('heading',{name:admin?'Мультипликатор':'Оценка',exact:true})).toBeVisible();
  await expect.soft(page.getByRole('heading',{name:admin?'Оценка':'Мультипликатор',exact:true})).toHaveCount(0);
  await page.goto('/company/AGBA?tab=financials');
  await page.getByLabel('Валюта').selectOption('USD');
  const rates=page.locator('.terminal-fx-rates');
  if(admin){
    await expect(rates).toContainText('Пересчёт в USD');
    await expect(rates.locator('a')).toHaveCount(0);
  } else {
    await expect(rates.locator('summary')).toHaveText('Курсы ЦБ на конец каждого периода');
    await expect(rates.getByRole('link',{name:'CBU',exact:true})).toHaveCount(2);
    await expect(rates).not.toContainText('Пересчёт в USD');
  }
});

test('BIOK P/BV uses Yangiyul’s filed shares and mobile EPS shows the missing basis', async ({page}, testInfo) => {
  await page.setViewportSize({width: 390, height: 844});
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  const report = JSON.parse(execFileSync(python, ['-c', `
import json
from pathlib import Path
from financial_analysis.report_investor_metrics import calculate
from financial_columns.share_disclosures import form5_basis
source = json.loads(Path('tests/fixtures/openinfo/biok_2026q3_equity.json').read_text(encoding='utf8'))
basis = form5_basis(source, ticker='BIOK', issuer_id=source['issuer_id'], tin=source['tin'], period_end=source['period_end'])
report = {
    'ok': True, 'status': 'available', 'period': '2026Q3', 'standard': 'nsbu', 'scope': 'separate',
    'financial_as_of': source['period_end'], 'issuer': {'id': '396', 'ticker': 'BIOK', 'name': 'Biokimyo', 'organization_type': 'non_financial'},
    'instrument': {'instrument_type': 'ordinary_share', 'last_price': 14301, 'market_as_of': '2026-11-12', 'freshness': {'status': 'fresh'}},
    'verified_facts': [{'metric_code': metric, 'value': value, 'period': '2026Q3', 'unit_normalized': 'thousand UZS',
                        'verification_status': 'verified'} for metric, value in [('total_equity', 130595895), ('net_income', 12628226)]]
}
print(json.dumps({**report, 'ratios': calculate(report, [], {**basis, 'verification_status': 'verified'})}))
`], {encoding:'utf8'}));
  await fixture(page, [{ticker:'BIOK',company_name:'Biokimyo',sector:'manufacturing'}]);
  await page.route('**/api/v1/issuers/BIOK/ai-report?**', route => route.fulfill({json:report}));
  await run(page, 'BIOK RAT');
  const table = page.locator('.terminal-sector-metrics');
  await expect(table.getByRole('row').filter({hasText:'P/BV'})).toContainText('0,63 ×');
  await expect(table.getByRole('row').filter({hasText:'Базовая прибыль'})).toContainText('средневзвешенное число обычных акций');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await table.screenshot({path:testInfo.outputPath('biok-share-ratios-mobile.png')});
});

test('quarterly blanks distinguish loss bases from missing reports', async ({page}) => {
  await fixture(page);
  await page.route('**/api/terminal/issuer/AGBA/analytics?*', route => route.fulfill({json:{
    ok:true,snapshot:{period:'2025',kind:'bank'},growth:[],quarters:{rows:[
      {period:'2024Q2',value:99630592000,yoy:null,ltm:null,seasonality:null,cg3:null,
        metric_reasons:{yoy:{code:'NON_POSITIVE_BASE',required_period:'2023Q2'},
          ltm:{code:'MISSING_QUARTERS',periods:['2023Q3']},seasonality:{code:'INCOMPLETE_YEAR'},cg3:{code:'NON_POSITIVE_ENDPOINT'}}},
      {period:'2026Q3',value:483738227000,yoy:null,metric_reasons:{yoy:{code:'MISSING_COMPARATIVE_INPUT',required_period:'2025Q3'}}}
    ]}
  }}));
  await run(page,'AGBA RAT');
  const row=page.locator('.terminal-quarter-map tbody tr').filter({hasText:'2024Q2'});
  await expect(row.getByRole('cell').nth(1)).toHaveAttribute('title',/2023Q2.*убыток|убыток.*2023Q2/);
  await expect(row.getByRole('cell').nth(2)).toHaveAttribute('title',/2023Q3/);
  const missing=page.locator('.terminal-quarter-map tbody tr').filter({hasText:'2026Q3'});
  await expect(missing.getByRole('cell').nth(1)).toHaveAttribute('title',/2025Q3/);
  const heatmap=page.locator('.terminal-heatmap tbody tr').filter({hasText:'2024'});
  await expect(heatmap.getByRole('cell').nth(1)).toHaveAttribute('title',/2023Q2/);
  await expect(page.locator('.terminal-quarterly-overview')).toContainText('Убыток или нулевая база');
  await page.setViewportSize({width:390,height:844});
  await expect(row.getByRole('cell').nth(1)).toHaveAttribute('aria-label',/2023Q2/);
});
