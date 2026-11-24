import { execFileSync } from 'node:child_process';
import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const report=JSON.parse(readFileSync('e2e/fixtures/ifrs-investor.json','utf8'));

async function setup(page,theme='dark') {
  await page.addInitScript(theme=>{
    localStorage.setItem('uz_stock_analyzer_language','en');
    localStorage.setItem('uz_stock_analyzer_theme',theme);
    localStorage.setItem('uz_stock_analyzer_token','investor-test');
    sessionStorage.setItem('uz_sponsor_seen','1');
  },theme);
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url()),path=url.pathname;
    let data={ok:true,items:[],rows:[],companies:[],series:{},periods:[],availability:{}};
    if(path==='/api/auth/me')data={user:{id:1,is_admin:true}};
    if(path==='/api/catalog/companies')data={ok:true,companies:[{ticker:'HMKB',company_name:'Hamkorbank',sector:'finance'}]};
    if(path.startsWith('/api/catalog/index/'))data={ok:true,company_name:'Hamkorbank',availability:{MSFO:{annual:[{year:2025}]}}};
    if(path.endsWith('/financials/columns')&&url.searchParams.get('view')==='investor') {
      data=url.searchParams.get('scope')==='separate'?{...report,scope:'separate',rows:[],columns:[],statements:{pl:[],bs:[],cf:[],equity:[]}}:report;
    }
    return route.fulfill({json:data});
  });
}

for(const theme of ['light','dark'])test(`shared IFRS investor has all sections, sources and mobile layout (${theme})`,async({page},testInfo)=>{
  await setup(page,theme);
  await page.goto('/company/HMKB?tab=financials&standard=MSFO');
  const ui=page.getByTestId('ifrs-investor');
  await expect(ui).toBeVisible();
  await expect(ui.locator('.investor-kpis > article')).toHaveCount(6);
  await expect(ui.getByRole('tab')).toHaveCount(9);
  await expect(ui).not.toContainText('5 400');
  await page.screenshot({path:testInfo.outputPath(`investor-overview-${theme}.png`),fullPage:true});
  await ui.getByRole('tab',{name:'BS Balance',exact:true}).click();
  const assets=ui.locator('tr[data-field="assets"]');
  await expect(assets).toBeVisible();
  await expect(ui.locator('tr[data-field="interestRevenue"]')).toHaveCount(0);
  await assets.getByRole('button').last().click();
  await expect(page.getByRole('dialog')).toContainText('consolidated');
  await expect(page.getByRole('dialog').getByRole('link',{name:'Open source',exact:true})).toHaveAttribute('href',/^https:/);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  const [download]=await Promise.all([page.waitForEvent('download'),ui.getByRole('button',{name:'CSV',exact:true}).click()]);
  const csv=readFileSync(await download.path(),'utf8');
  expect(csv).toContain('млрд UZS');expect(csv).not.toContain('Процентные доходы');
  for(const name of ['CF Cash flows','EQ Equity','RAT Ratios','Dashboards','Notes','Quality']) {
    await ui.getByRole('tab',{name,exact:true}).click();
    await expect(ui.locator('[role="tabpanel"]')).toBeVisible();
  }
  await ui.getByRole('tab',{name:'Dashboards',exact:true}).click();
  await expect(ui.getByRole('heading',{name:'Debt and liquidity',exact:true})).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  await ui.getByRole('tab',{name:'Overview',exact:true}).click();
  const issuerBounds=await ui.getByLabel('Issuer',{exact:true}).boundingBox();
  expect(issuerBounds.x+issuerBounds.width).toBeLessThanOrEqual(390);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:testInfo.outputPath(`investor-mobile-${theme}.png`),fullPage:true});
  await ui.getByLabel('Scope',{exact:true}).selectOption('separate');
  await expect(ui.getByText('No approved source rows for this scope.',{exact:true})).toBeVisible();
  await expect(ui.locator('.investor-kpis')).toHaveCount(0);
});

test('admin catalog still hides MSFO including old links and panels',async({page})=>{
  await setup(page);
  const layout=[{ticker:'HMKB',func:'BS',form:'MSFO',scope:'consolidated'}];
  await page.route('**/api/profile',route=>route.fulfill({json:{preferences:{terminal_layout:layout}}}));
  const ifrsRequests=[];
  page.on('request',request=>{
    const url=new URL(request.url());
    if(url.pathname.startsWith('/api/') && (url.searchParams.get('form')==='MSFO'||url.searchParams.get('standard')==='ifrs'||url.searchParams.get('view')==='investor'))ifrsRequests.push(url.pathname+url.search);
  });
  await page.goto('/catalog?t=HMKB&f=BS&std=MSFO&scope=consolidated');
  const standard=page.getByRole('group',{name:'Accounting standard',exact:true});
  await expect(standard.getByRole('button',{name:'NSBU',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(standard.getByRole('button',{name:'MSFO',exact:true})).toHaveCount(0);
  await expect(page).not.toHaveURL(/std=MSFO|scope=consolidated/);
  await page.reload();
  await expect(standard.getByRole('button')).toHaveText(['NSBU']);
  const command=page.getByRole('combobox',{name:'Company search'});
  await command.fill('HMKB IFRS PL');await command.press('Enter');
  await expect(page).toHaveURL(/f=PL/);
  await expect(standard.getByRole('button',{name:'NSBU',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.getByRole('button',{name:'EQS · Screener',exact:true}).click();
  await expect(page.getByLabel(/^Standard/).locator('option')).toHaveText(['NSBU']);
  await page.getByRole('button',{name:'PNL · Panels',exact:true}).click();
  const panel=page.locator('.terminal-work-panel');
  await expect(panel).toHaveAttribute('data-terminal-standard','NSBU');
  await expect(panel).toHaveAttribute('data-terminal-scope','separate');
  await expect(panel.getByLabel(/^Standard/).locator('option')).toHaveText(['NSBU']);
  await page.setViewportSize({width:390,height:844});
  await expect(panel.getByLabel(/^Standard/)).toBeVisible();
  await expect(page.getByTestId('ifrs-investor')).toHaveCount(0);
  expect(ifrsRequests).toEqual([]);
});

test('IFRS deep link, retry, notes and print remain connected',async({page})=>{
  await setup(page);
  let fail=true;
  await page.route('**/financials/columns?*',route=>{
    if(fail){fail=false;return route.fulfill({status:503,json:{detail:'Unavailable'}});}
    return route.fulfill({json:{...report,source_forms:[{period_end:'2025-12-31',source_url:'https://example.test/audit.pdf',documents:[{form:'Notes',page:12,text:'Verified segment disclosure'}]}]}});
  });
  await page.goto('/company/HMKB?tab=financials&standard=MSFO');
  const ui=page.getByTestId('ifrs-investor');
  await expect(ui.getByRole('alert')).toContainText('Could not load IFRS reports.');
  await ui.getByRole('button',{name:'Retry',exact:true}).click();
  await expect(ui.locator('.investor-kpis > article')).toHaveCount(6);
  await ui.getByRole('tab',{name:'Notes',exact:true}).click();
  await ui.locator('.investor-note summary').click();
  await expect(ui).toContainText('Verified segment disclosure');
  await expect(ui.getByRole('link',{name:'Open PDF'})).toHaveAttribute('href','https://example.test/audit.pdf#page=12');
  await page.evaluate(()=>{window.print=()=>{window.__printed=true;};});
  await ui.getByRole('button',{name:'PDF / Print'}).click();
  expect(await page.evaluate(()=>window.__printed)).toBe(true);
  await page.emulateMedia({media:'print'});
  await expect(ui.locator('.investor-tabs')).toBeHidden();
});

for (const example of [
  {ticker:'BTRL', file:'btrl_ifrs_2025', tab:'PL Profit or loss', field:'tax', value:'-0.33'},
  {ticker:'ANBK3B', file:'anbk_customer_loans_2025', template:'bank', tab:'BS Balance', field:'loans', value:/10[ ,\u202f\u00a0]?596[.,]15/},
  {ticker:'UZNGP', file:'uzngp_inventory_2025', tab:'BS Balance', field:'inventory', value:'452'},
]) test(example.ticker+' reviewed '+example.field+' opens the FY2025 source in the investor statement', async ({page}) => {
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  const filing = JSON.parse(execFileSync(python, ['-c', `
import json, sys
from pathlib import Path
from financial_columns import investor, matrix, observations
snapshot = json.loads(Path('tests/fixtures/financial_columns', sys.argv[1]+'.json').read_text())
rows = observations.ifrs([snapshot])
table = matrix.build(rows, mode='annual')
payload = dict(**table, ok=True, ticker=sys.argv[2], issuer_id=snapshot['org_id'], issuer_name=sys.argv[2],
               standard='MSFO', template=sys.argv[3], scope=snapshot['scope'], available_scopes=[snapshot['scope']],
               unit='UZS_thousand', freq='annual', issues=[], ratios=[], published_ratios=[], source_forms=[],
               coverage={'issues':[]}, shareholders=[])
print(json.dumps(investor.project(payload, rows)))
`,example.file,example.ticker,example.template || 'industry'], {encoding:'utf8'}));
  await setup(page);
  await page.route('**/api/company/'+example.ticker+'/financials/columns?**', route => route.fulfill({json:filing}));
  await page.goto('/company/'+example.ticker+'?tab=financials&standard=MSFO');
  const panel = page.getByTestId('ifrs-investor');
  await panel.getByRole('tab',{name:example.tab,exact:true}).click();
  const value = panel.locator('tr[data-field="'+example.field+'"]').getByRole('button');
  await expect(value).toHaveText(example.value);
  await value.click();
  await expect(page.getByRole('dialog').getByRole('link',{name:'Open source'}))
    .toHaveAttribute('href', JSON.parse(readFileSync('tests/fixtures/financial_columns/'+example.file+'.json','utf8')).payload.source.pdf_url);
});

test('KASU shows the restated 2023 balance sheet alongside the two later years', async ({page}) => {
  const source = 'https://openinfo.uz/media/int_report/e1ccfed8-fc8f-48dc-bb0d-6a7da0f40029.pdf';
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  const filing = JSON.parse(execFileSync(python, ['-c', `
import json, os, sys, tempfile
from unittest.mock import patch
from financial_columns import service
with tempfile.TemporaryDirectory() as scratch:
    os.environ['CATALOG_DB_PATH'] = scratch + '/catalog.db'
    rows = []
    for year, amount in [(2023, '338699936'), (2024, '395564291'), (2025, '467708505')]:
        end = f'{year}-12-31'
        rows.append(dict(metric_id='total_assets', source_form='BS', source_code=None, raw_label='ИТОГО АКТИВЫ',
                         value=amount, kind='stock', quality='valid', unit='UZS_thousand', currency='UZS',
                         page=6, period_start=end, period_end=end, standard='MSFO', scope='separate',
                         issuer_id='34', source_version='312', source_url=sys.argv[1]))
    rows.append(dict(rows[0], metric_id='cash_begin', source_form='CF', period_start='2022-12-31',
                     period_end='2022-12-31', statement_period_end='2023-12-31', raw_label='Opening cash', value='1'))
    with patch.object(service.publication, 'snapshots', return_value=[]), patch.object(service.publication, 'scopes', return_value=['separate']), patch.object(service.observations, 'ifrs', return_value=rows):
        print(json.dumps(service.load('KASU', form='MSFO', view='investor', scope='separate', freq='annual')))
`, source], {encoding:'utf8'}));
  await setup(page);
  await page.route('**/api/company/KASU/financials/columns?**', route => route.fulfill({json:filing}));
  await page.goto('/company/KASU?tab=financials&standard=MSFO');
  const panel = page.getByTestId('ifrs-investor');
  await panel.getByRole('tab',{name:'BS Balance', exact:true}).click();
  const headers = panel.locator('thead th');
  await expect(headers).toHaveCount(4);
  await expect(headers.nth(1)).toContainText('2023');
  const assets = panel.locator('tr[data-field="assets"]').getByRole('button').first();
  await expect(assets).toHaveText('338.7');
  await assets.click();
  await expect(page.getByRole('dialog').getByRole('link',{name:'Open source'})).toHaveAttribute('href',source);
});

test('UZNF retains its audited first year when an interim filing reports opening cash', async ({page}) => {
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  const filing = JSON.parse(execFileSync(python, ['-c', `
import json, os, tempfile
from unittest.mock import patch
from financial_columns import service
from financial_columns.investor_sources import audited_fund
with tempfile.TemporaryDirectory() as scratch:
    os.environ['CATALOG_DB_PATH'] = scratch + '/catalog.db'
    cash = next(r for r in audited_fund('UZNF', '1059', 'separate') if r['metric_id'] == 'cash')
    opening = dict(cash, metric_id='cash_begin', source_code=None, source_form='CF', statement_period_end='2026-09-30',
                   raw_label='Cash and cash equivalents at the beginning of the period')
    annual_profit = next(r for r in audited_fund('UZNF', '1059', 'separate') if r['metric_id'] == 'net_income')
    interim_profit = dict(annual_profit, period_start='2026-01-01', period_end='2026-09-30', value='1936551000',
                          raw_label='Profit for the period', source_code=None, source_version='interim-profit', reported_annual=False)
    with patch.object(service.publication, 'snapshots', return_value=[]), patch.object(service.publication, 'scopes', return_value=['separate']), patch.object(service.observations, 'ifrs', return_value=[opening, interim_profit]):
        print(json.dumps(service.load('UZNF', form='MSFO', view='investor', scope='separate', include_ratios=False)))
`], {encoding:'utf8'}));
  await setup(page);
  await page.route('**/api/company/UZNF/financials/columns?**', route => route.fulfill({json:filing}));
  await page.goto('/company/UZNF?tab=financials&standard=MSFO');
  const panel = page.getByTestId('ifrs-investor');
  await panel.getByRole('tab',{name:'PL Profit or loss',exact:true}).click();
  await expect(panel.locator('thead')).toContainText('24.12.2024–31.12.2025');
  const profit = panel.locator('tr[data-field="profit"]').getByRole('button', {name:/24\.12\.2024–31\.12\.2025/});
  await expect(profit).toHaveText(/1[\s,]?403\.15/);
  await profit.click();
  await expect(page.getByRole('dialog').getByRole('link',{name:'Open source'})).toHaveAttribute(
    'href', 'https://openinfo.uz/media/int_report/c0227ba5-b817-4d90-a3b1-2b1f9a9da524.pdf');
});

test('SQBN investor ratios use the staged loan portfolio from the signed note', async ({page}) => {
  await openSignedFiling(page, 'SQBN', 'bank', 'sqbn_2025_loan_note.json');
  const panel = page.getByTestId('ifrs-investor');
  await panel.getByRole('tab',{name:'RAT Ratios',exact:true}).click();
  for (const [label, value] of [['Stage 3 / gross loans', '7.48%'], ['ECL coverage', '5.99%']]) {
    const card = panel.locator('.investor-ratios article').filter({hasText:label});
    await expect(card.locator('.investor-number')).toHaveText(value);
  }
});

test('URTS shows the EBITDA margin calculated from its income and cash flow statements', async ({page}) => {
  await openSignedFiling(page, 'URTS', 'industry', 'urts_2025_ebitda.json');
  const panel = page.getByTestId('ifrs-investor');
  await panel.getByRole('tab', {name:'RAT Ratios', exact:true}).click();
  const margin = panel.locator('.investor-ratios article').filter({hasText:'EBITDA margin'});
  await expect(margin.locator('.investor-number')).toHaveText('47.77%');
});

async function openSignedFiling(page, ticker, kind, filename) {
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  const filing = JSON.parse(execFileSync(python, ['-c', `
import json, os, sys, tempfile
from pathlib import Path
from unittest.mock import patch
from financial_columns import service
ticker, kind, filename = sys.argv[1:]
rows = json.loads((Path('tests/fixtures/financial_columns') / filename).read_text())
with tempfile.TemporaryDirectory() as scratch:
    os.environ['CATALOG_DB_PATH'] = scratch + '/catalog.db'
    with patch.object(service, 'organization_kind', return_value=kind), patch.object(service.publication, 'snapshots', return_value=[]), patch.object(service.publication, 'scopes', return_value=['consolidated']), patch.object(service.observations, 'ifrs', return_value=rows):
        print(json.dumps(service.load(ticker, form='MSFO', view='investor', scope='consolidated', freq='annual')))
`, ticker, kind, filename], {encoding:'utf8'}));
  await setup(page);
  await page.route(`**/api/company/${ticker}/financials/columns?**`, route => route.fulfill({json:filing}));
  await page.goto(`/company/${ticker}?tab=financials&standard=MSFO`);
}

test('ANBK3B shows the foreign exchange result from the signed trading and translation lines', async ({page}) => {
  await openSignedFiling(page, 'ANBK3B', 'bank', 'anorbank_2025_fx.json');
  const panel = page.getByTestId('ifrs-investor');
  await panel.getByRole('tab', {name:'PL Profit or loss', exact:true}).click();
  const value = panel.locator('tr[data-field="fxResult"]').getByRole('button', {name:/2025/});
  await expect(value).toHaveText('37.76');
  await value.click();
  await expect(page.getByRole('dialog')).toContainText('46,919,123');
});

test('UZINP shows consolidated other comprehensive income with both source totals', async ({page}) => {
  await openSignedFiling(page, 'UZINP', 'insurance', 'uzinvest_2025_comprehensive_income.json');
  const panel = page.getByTestId('ifrs-investor');
  await panel.getByRole('tab', {name:'PL Profit or loss', exact:true}).click();
  const cell = panel.locator('tr[data-field="oci"]').getByRole('button', {name:/2025/});
  await expect(cell).toHaveText(/[-−]3\.59/);
  await cell.click();
  const passport = page.getByRole('dialog');
  await expect(passport).toContainText('79,104,448');
  await expect(passport).toContainText('82,691,849');
});
