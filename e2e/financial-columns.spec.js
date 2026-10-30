import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const fixture = JSON.parse(readFileSync('e2e/fixtures/financial-columns.json', 'utf8'));
const templateFixture = JSON.parse(readFileSync('e2e/fixtures/financial-columns-template.json', 'utf8'));
const original = JSON.parse(readFileSync('tests/fixtures/openinfo/iptb_2026q3_complete_rows.json', 'utf8'));
const hmkbFixture = JSON.parse(readFileSync('e2e/fixtures/hmkb-overview.json', 'utf8'));
const hmkbLabels = JSON.parse(readFileSync('tests/fixtures/financial_columns/hmkb_overview_labels.json', 'utf8'));
const recentReports = JSON.parse(readFileSync('e2e/fixtures/hmkb-recent-reports.json', 'utf8'));

test('HMKB current ratios show annualization and matching source periods',async({page},testInfo)=>{
  const reports=structuredClone(recentReports),end='2026-09-30';
  const source=(metric,period=end)=>reports.rows.find(r=>r.metric_id===metric).cells[period];
  reports.ratios=[
    ['roe','ROE','26.5133295211',true,'net_income / average(total_equity) × 100 × 12 / 9',
      [source('net_income'),source('total_equity','2025'),source('total_equity')]],
    ['roa','ROA','4.9162481672',true,'net_income / average(total_assets) × 100 × 12 / 9',
      [source('net_income'),source('total_assets','2025'),source('total_assets')]],
    ['cir','CIR',String(1819867178/4249412165*100),false,'operating costs / operating income before credit losses × 100',[]],
    ['nim','NIM',null,false,'net_interest_before_ecl / average(earning_assets) × 100 × 12 / 9',[]],
  ].map(([metric_id,label,value,annualized,formula,components])=>({
    id:`ratio:${metric_id}`,metric_id,label,unit:'percent',source_form:'RAT',kind:'ratio',
    cells:Object.fromEntries(reports.columns.map(c=>[c.key,c.key===end?
      {value,quality:value==null?'missing':'valid',annualized,formula,components,
        period_start:'2026-01-01',period_end:end,basis:'ytd',reason:value==null?'AVERAGE_EARNING_ASSETS_MISSING':null}:
      {value:null,quality:'missing'}])),
  }));
  await setup(page,{ticker:'HMKB',func:'SUM',reports});
  const terminal=page.getByTestId('financial-columns');
  await terminal.getByRole('tab',{name:'Ratios',exact:true}).click();
  const last=metric=>terminal.locator(`tr[data-metric="${metric}"] td`).last();
  await expect(last('roe')).toContainText('26.51');
  await expect(last('roe')).toContainText('annualized');
  await expect(last('roa')).toContainText('4.92');
  await expect(last('cir')).toHaveText('42.83');
  await expect(last('nim')).toHaveText('—');
  // Ratio and owner exports must not inherit the income/balance tab filter.
  for (const name of ['CSV', 'XLSX']) {
    const url = new URL(await terminal.getByRole('link', {name, exact:true}).getAttribute('href'), page.url());
    expect(url.searchParams.get('statement')).toBe('all');
    expect(url.searchParams.get('view')).toBe('template');
  }
  await terminal.getByRole('tab', {name:'Shareholders', exact:true}).click();
  await expect(terminal.getByRole('link', {name:'CSV', exact:true})).toHaveAttribute('href', /statement=all/);
  await terminal.getByRole('tab', {name:'Ratios', exact:true}).click();
  await last('roe').getByRole('button').click();
  const passport=page.getByRole('dialog',{name:'Source passport'});
  await expect(passport).toContainText('2026-01-01 — 2026-09-30');
  await expect(passport).toContainText('2025-12-31');
  await expect(passport).toContainText('× 12 / 9');
  await page.getByRole('button',{name:'Close',exact:true}).click();
  await last('nim').getByRole('button').click();
  await expect(passport).toContainText('A comparable average interest-earning asset base is missing.');
  await page.getByRole('button',{name:'Close',exact:true}).click();
  await terminal.locator('.fc-table').scrollIntoViewIfNeeded();
  await page.screenshot({path:testInfo.outputPath('hmkb-current-ratios.png')});
  await page.setViewportSize({width:390,height:844});
  await terminal.locator('.fc-scroll').evaluate(el=>{el.scrollLeft=el.scrollWidth;});
  await expect(last('roe')).toContainText('26.51');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('balance rows belong to BS while SUM and PL retain income rows',async({page},testInfo)=>{
  await setup(page,{ticker:'HMKB',func:'SUM',reports:recentReports});
  const terminal=page.getByTestId('financial-columns');
  await expect(terminal.locator('tr[data-metric="interest_income"]')).toBeVisible();
  await expect(terminal.locator('tr[data-metric="cash"]')).toHaveCount(0);
  await page.getByRole('button',{name:/BS Balance/}).click();
  await expect(terminal.locator('tr[data-metric="cash"]')).toBeVisible();
  await expect(terminal.locator('tr[data-metric="interest_income"]')).toHaveCount(0);
  await expect(terminal.getByRole('link',{name:'CSV',exact:true})).toHaveAttribute('href',/statement=balance/);
  await terminal.getByRole('button',{name:'Chart',exact:true}).click();
  await expect(terminal.locator('.fc-chart-metric').filter({hasText:'Итого процентных доходов'})).toHaveCount(0);
  await expect(terminal.locator('.fc-chart-metric').filter({hasText:'Кассовая наличность'})).toHaveCount(1);
  await terminal.getByRole('button',{name:'Table',exact:true}).click();
  await terminal.getByRole('tab',{name:'Original forms',exact:true}).click();
  await expect(terminal.locator('tr[data-metric="interest_income"]')).toHaveCount(0);
  await terminal.locator('.fc-table').scrollIntoViewIfNeeded();
  await page.screenshot({path:testInfo.outputPath('balance-tab.png'),animations:'disabled'});
  await page.getByRole('button',{name:/PL Profit/}).click();
  await expect(terminal.locator('tr[data-metric="cash"]')).toHaveCount(0);
  await expect(terminal.locator('tr[data-metric="interest_income"]')).toBeVisible();
  await expect(terminal.getByRole('link',{name:'XLSX',exact:true})).toHaveAttribute('href',/statement=income/);
});

for (const theme of ['light', 'dark']) test(`HMKB chart shows all metrics with individual and group toggles (${theme})`, async ({page}, testInfo) => {
  await setup(page, {ticker:'HMKB', func:'BS', reports:recentReports, theme});
  const terminal=page.getByTestId('financial-columns');
  await terminal.getByRole('button',{name:'Chart',exact:true}).click();
  const chart=terminal.locator('.fc-chart');
  await expect(chart.locator('select')).toHaveCount(0);
  const metrics=chart.locator('.fc-chart-metric');
  await expect(metrics).toHaveCount(16);
  await chart.getByRole('button',{name:'Show all',exact:true}).click();
  await expect(chart.locator('[data-chart-series]')).toHaveCount(16);
  const loans=chart.getByRole('button',{name:'Кредиты и лизинговые операции, брутто · 7а',exact:true});
  const leases=chart.getByRole('button',{name:'Кредиты и лизинговые операции, брутто · 7б',exact:true});
  const loanSeries=chart.locator('[data-chart-series]').filter({hasText:'Кредиты и лизинговые операции, брутто · 7а'});
  const leaseSeries=chart.locator('[data-chart-series]').filter({hasText:'Кредиты и лизинговые операции, брутто · 7б'});
  await expect(loanSeries.locator('rect')).toHaveCount(3);
  await expect(loanSeries).toContainText('30,361,825,389');
  await expect(leaseSeries).toContainText('1,056,352,067');
  await expect(chart).not.toContainText('31,418,177,456');
  await leaseSeries.locator('rect').last().click();
  await expect(chart.locator('.fc-chart-reading')).toContainText('1,056,352,067');
  const color=await leaseSeries.getAttribute('fill');
  await loans.click();
  await expect(loans).toHaveAttribute('aria-pressed','false');
  await expect(loanSeries).toHaveCount(0);
  await expect(leaseSeries).toHaveAttribute('fill',color);
  await expect(chart.locator('[data-chart-series]')).toHaveCount(15);
  const assets=chart.getByRole('button',{name:'Баланс банка · активы',exact:true});
  await expect(assets).toHaveAttribute('aria-pressed','mixed');
  await assets.click();
  await expect(chart.locator('[data-chart-series]')).toHaveCount(16);
  await assets.click();
  await expect(chart.locator('[data-chart-series]')).toHaveCount(7);
  await expect(loans).toHaveAttribute('aria-pressed','false');
  await expect(leases).toHaveAttribute('aria-pressed','false');
  await chart.getByRole('button',{name:'Hide all',exact:true}).click();
  await expect(chart.getByRole('status')).toContainText('Select metrics above');
  await expect(chart.locator('[data-chart-series]')).toHaveCount(0);
  await loans.focus();
  await page.keyboard.press('Space');
  await expect(loanSeries.locator('rect')).toHaveCount(3);
  await expect(chart.getByRole('status')).toHaveCount(0);
  await chart.getByRole('button',{name:'Show all',exact:true}).click();
  await chart.getByRole('button',{name:'Ungrouped',exact:true}).click();
  await expect(chart.locator('.fc-chart-group-toggle')).toHaveCount(0);
  await expect(metrics).toHaveCount(16);
  await chart.getByRole('button',{name:'By section',exact:true}).click();
  await expect(chart.locator('.fc-chart-group-toggle')).toHaveCount(2);
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:testInfo.outputPath(`hmkb-grouped-chart-${theme}.png`), fullPage:true, animations:'disabled'});
  await page.setViewportSize({width:390,height:844});
  await expect(metrics).toHaveCount(16);
  const bounds=await metrics.evaluateAll(nodes=>nodes.map(n=>({left:n.getBoundingClientRect().left,right:n.getBoundingClientRect().right})));
  expect(bounds.every(b=>b.left>=0&&b.right<=390)).toBe(true);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:testInfo.outputPath(`hmkb-grouped-chart-${theme}-mobile.png`), fullPage:true, animations:'disabled'});
});

test('chart keeps units separate and never draws missing or blocked values as zero', async ({page}) => {
  const reports=structuredClone(recentReports);
  const cells=(values,quality='valid')=>Object.fromEntries(reports.columns.map((c,i)=>[c.key,{value:values[i],quality}]));
  reports.ratios=[
    {id:'roe',metric_id:'roe',label:'ROE',unit:'percent',source_form:'RAT',cells:cells([0,-5,null])},
    {id:'leverage',metric_id:'debt_to_equity',label:'Leverage',unit:'ratio',source_form:'RAT',cells:cells([1.7,null,2])},
    {id:'blocked',metric_id:'roa',label:'Blocked',unit:'percent',source_form:'RAT',cells:cells([99,99,99],'blocked')},
  ];
  await setup(page,{ticker:'HMKB',func:'BS',reports});
  const terminal=page.getByTestId('financial-columns');
  await terminal.getByRole('tab',{name:'Ratios',exact:true}).click();
  await terminal.getByRole('button',{name:'Chart',exact:true}).click();
  const chart=terminal.locator('.fc-chart');
  await expect(chart.locator('.fc-chart-metric')).toHaveCount(2);
  await expect(chart.getByRole('img')).toHaveCount(2);
  const roe=chart.locator('[data-chart-series="roe"]');
  await expect(roe.locator('rect')).toHaveCount(2);
  await expect(roe).toContainText('0');
  await expect(roe).toContainText('-5');
  await expect(chart.locator('[data-chart-series="leverage"] rect')).toHaveCount(2);
  await expect(chart).not.toContainText('99');
  const retained=await roe.getAttribute('fill');
  await terminal.getByRole('searchbox').fill('ROE');
  await expect(chart.locator('.fc-chart-metric')).toHaveCount(1);
  await expect(roe).toHaveAttribute('fill',retained);
});

test('annual income gaps explain why a comparative balance can still be populated', async ({page},testInfo) => {
  const reports=structuredClone(recentReports);
  reports.columns=[{key:'2023',label:'2023',end:'2023-12-31',basis:'annual'},
    {key:'2025',label:'2025',end:'2025-12-31',basis:'annual',notice:'ANNUAL_INCOME_NOT_IMPORTED',balance_source:'comparative'},
    {key:'2026-06-30',label:'2026 · 6M',end:'2026-06-30',basis:'ytd'}];
  const observations=JSON.parse(readFileSync('tests/fixtures/financial_columns/agmkp_comparative_balance.json','utf8'));
  reports.rows=['revenue','ppe'].map(metric=>{
    const cells=observations.filter(c=>c.metric_id===metric), sample=cells[0];
    return {id:metric,metric_id:metric,label:sample.raw_label,kind:sample.kind,source_form:sample.source_form,source_code:sample.source_code,
      cells:Object.fromEntries(reports.columns.map(c=>[c.key,cells.find(v=>v.period_end===c.end)||{value:null,quality:'missing'}]))};
  });
  reports.overview_rows=reports.rows;
  await setup(page,{ticker:'AGMKP',func:'SUM',reports});
  const terminal=page.getByTestId('financial-columns');
  await expect(terminal.locator('.fc-period-notice')).toContainText('2025');
  await expect(terminal.locator('.fc-period-notice')).toContainText('Annual income statement is not available');
  await expect(terminal.locator('.fc-period-notice')).toContainText('comparative');
  await expect(terminal.locator('tr[data-metric="revenue"] td').nth(1)).toHaveText('—');
  await expect(terminal.locator('tr[data-metric="ppe"]')).toHaveCount(0);
  await terminal.locator('.fc-period-notice').scrollIntoViewIfNeeded();
  await page.screenshot({path:testInfo.outputPath('agmkp-annual-income-notice.png')});
  await page.getByRole('button',{name:/BS Balance/}).click();
  await expect(terminal.locator('tr[data-metric="ppe"] td').nth(1)).toHaveText('13,358,866,945');
  await expect(terminal.locator('.fc-period-notice')).toHaveCount(0);
});

async function setup(page, { fail = false, theme = 'light', func = 'PL', ticker = 'IPTB', reports } = {}) {
  await page.addInitScript(theme => localStorage.setItem('uz_stock_analyzer_theme', theme), theme);
  await page.addInitScript(() => {
    sessionStorage.setItem('uz_sponsor_seen', '1');
    localStorage.setItem('uz_stock_analyzer_language', 'en');
    localStorage.setItem('uz_stock_analyzer_token', 'columns-admin');
  });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    const json = value => route.fulfill({ json: value });
    if (path === '/api/auth/me') return json({ user: { id: 1, is_admin: true } });
    if (path === '/api/catalog/companies') return json({ ok: true, total: 1, companies: [{ ticker, company_name: ticker === 'HMKB' ? 'Hamkorbank' : 'Ipoteka bank', sector: 'finance' }] });
    if (path === `/api/catalog/index/${ticker}`) return json({ ok: true, company_name: ticker === 'HMKB' ? 'Hamkorbank' : 'Ipoteka bank', availability: { NSBU: { annual: [{ year: 2025 }], quarter: [{ year: 2026, quarter: 3 }] } } });
    if (path.endsWith('/financials/columns')) {
      if (fail) return route.fulfill({ status: 503, json: { detail: 'Source temporarily unavailable' } });
      const data = reports || (ticker === 'HMKB' ? hmkbFixture : (url.searchParams.get('view') === 'template' ? templateFixture : fixture)[url.searchParams.get('freq') || 'annual']);
      if (url.searchParams.get('form') === 'MSFO') return json({ ...data, presentation:'investor',statements:{pl:[],bs:[],cf:[],equity:[]},standard: 'MSFO', rows: [], overview_rows: [], ratios: [], source_forms: [], coverage: { complete: false, notes: 'missing', issues: ['NOTES_MISSING'] } });
      return json({ ...data, source_forms: [{ period_end: '2026-09-30', documents: [original] }] });
    }
    return json({ ok: true, companies_synced: 1, total_reports: 2, companies: [], rows: [], items: [], series: {}, periods: [], rates: [], availability: {} });
  });
  await page.goto(`/catalog?t=${ticker}&f=${func}`);
}

for (const theme of ['light', 'dark']) test(`two annual reports and the current report appear together (${theme})`, async ({ page }, testInfo) => {
  await setup(page, { ticker: 'HMKB', func: 'SUM', theme, reports: recentReports });
  const terminal = page.getByTestId('financial-columns');
  await expect(terminal.locator('.fc-table thead th')).toHaveText(['Metric', '2024', '2025', '2026 · 9MYTD']);
  await expect(terminal.locator('.fc-table tbody tr[data-metric]')).toHaveCount(8);
  await expect(terminal.locator('.fc-stats > div').filter({ hasText: 'Net profit' })).toContainText('1,480,422,343');
  const income = terminal.locator('.fc-table tr[data-metric="interest_income"]');
  await expect(income.locator('td')).toHaveCount(3);
  await expect(income.locator('td').last()).not.toHaveText('—');
  await income.locator('td').last().getByRole('button').click();
  await expect(page.getByRole('dialog')).toContainText('2026-01-01 — 2026-09-30');
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await terminal.locator('.fc-table').evaluate(el => el.scrollIntoView({ block: 'start' }));
  await page.evaluate(() => window.scrollBy(0, -130));
  await page.screenshot({ path: testInfo.outputPath(`recent-reports-${theme}.png`), animations: 'disabled' });
  await page.setViewportSize({ width: 390, height: 844 });
  await terminal.locator('.fc-scroll').evaluate(el => { el.scrollLeft = el.scrollWidth; });
  await expect(terminal.getByRole('columnheader', { name: /2026 · 9M/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath(`recent-reports-${theme}-mobile.png`), animations: 'disabled' });
});

for (const theme of ['light', 'dark']) test(`HMKB reference fields are split between income and balance (${theme})`, async ({ page }, testInfo) => {
  await setup(page, { ticker: 'HMKB', func: 'SUM', theme });
  const terminal = page.getByTestId('financial-columns');
  const rows = terminal.locator('.fc-table tbody tr[data-metric]');
  await expect(rows).toHaveCount(8);
  expect(await rows.locator('th').evaluateAll(nodes => nodes.map(n => n.firstChild.textContent))).toEqual(hmkbLabels.slice(0,8));
  await page.getByRole('button',{name:/BS Balance/}).click();
  await expect(rows).toHaveCount(16);
  expect(await rows.locator('th').evaluateAll(nodes => nodes.map(n => n.firstChild.textContent))).toEqual(hmkbLabels.slice(8));
  await expect(terminal.getByRole('link', { name: 'CSV', exact: true })).toHaveAttribute('href', /view=overview/);
  const loans = rows.filter({ hasText: 'Кредиты и лизинговые операции, брутто' });
  await expect(loans).toHaveCount(1);
  await expect(loans.getByRole('button')).toHaveCount(2);
  await loans.getByRole('button').first().click();
  await expect(page.getByRole('dialog', { name: 'Source passport' })).toContainText('7а');
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await terminal.locator('.fc-subnav').scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath(`hmkb-overview-${theme}.png`), animations: 'disabled' });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(rows).toHaveCount(16);
  await terminal.locator('.fc-table').evaluate(el => el.scrollIntoView({ block: 'start' }));
  await page.screenshot({ path: testInfo.outputPath(`hmkb-overview-${theme}-mobile.png`), animations: 'disabled' });
  await terminal.getByRole('tab', { name: 'Original forms', exact: true }).click();
  await expect(rows).toHaveCount(hmkbFixture.rows.filter(r=>r.kind==='stock').length);
  await expect(terminal.getByRole('link', { name: 'CSV', exact: true })).toHaveAttribute('href', /view=template/);
  await terminal.getByRole('tab', { name: 'Overview', exact: true }).click();
  await expect(rows).toHaveCount(16);
});

test('the terminal displays and exports only the reference field list', async ({ page }) => {
  await setup(page, { func: 'SUM' });
  const terminal = page.getByTestId('financial-columns');
  await terminal.getByRole('button', { name: '6M / 9M', exact: true }).click();
  await expect(terminal.locator('tr[data-metric="interest_income"]')).toHaveCount(1);
  await expect(terminal.getByRole('button', { name: '▾ Баланс банка · активы', exact: true })).toHaveCount(0);
  await expect(terminal.locator('tr[data-metric="staff_expense"]')).toHaveCount(0);
  await expect(terminal.locator('tr[data-metric="travel_expense"]')).toHaveCount(0);
  await expect(terminal.getByRole('link', { name: 'CSV', exact: true })).toHaveAttribute('href', /view=overview/);
  await expect(terminal.getByRole('link', { name: 'XLSX', exact: true })).toHaveAttribute('href', /view=overview/);
  await terminal.getByRole('tab', { name: 'Original forms', exact: true }).click();
  await expect(terminal.locator('tr[data-metric="staff_expense"]')).toHaveCount(0);
  await expect(terminal.locator('.fc-documents')).toHaveCount(0);
  await terminal.getByRole('searchbox').fill('7а');
  await expect(terminal.locator('tr[data-metric="staff_expense"]')).toHaveCount(0);
});

for (const theme of ['light','dark']) test(`financial statements share the catalog theme and controls (${theme})`, async ({page},testInfo) => {
  await setup(page,{theme,func:'BS'});
  const terminal=page.getByTestId('financial-columns');
  await expect(terminal.locator('tr[data-metric="cash"]')).toBeVisible();
  const styles=await terminal.evaluate(el=>{
    const own=getComputedStyle(el), catalog=getComputedStyle(el.closest('.catalog-terminal-ui'));
    return {ownColor:own.color,catalogColor:catalog.color,ownFont:own.fontFamily,catalogFont:catalog.fontFamily};
  });
  expect(styles.ownColor).toBe(styles.catalogColor);
  expect(styles.ownFont).toBe(styles.catalogFont);
  await expect(page.getByRole('button',{name:'NSBU',exact:true})).toHaveCount(1);
  await expect(terminal.locator('.fc-toolbar').getByRole('button',{name:'IFRS',exact:true})).toHaveCount(0);
  await page.screenshot({path:testInfo.outputPath(`financial-integrated-${theme}.png`),fullPage:true,animations:'disabled'});
  await page.setViewportSize({width:390,height:844});
  await terminal.getByRole('button',{name:'Chart',exact:true}).click();
  await expect(terminal.getByRole('img',{name:'Financial history'})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:testInfo.outputPath(`financial-integrated-${theme}-mobile.png`),fullPage:true,animations:'disabled'});
});

for (const theme of ['light', 'dark']) test(`SUM shows financial year columns directly in the overview (${theme})`, async ({ page }, testInfo) => {
  await setup(page, { func: 'SUM', theme });
  const terminal = page.getByTestId('financial-columns');
  await expect(terminal).toHaveCount(1);
  await expect(terminal.locator('.fc-table thead')).toContainText('2025');
  await expect(terminal.locator('tr[data-metric="interest_income"]')).toBeVisible();
  await expect(page.getByRole('button', { name: 'NSBU', exact: true })).toHaveCount(1);
  const summary = page.locator('.terminal-summary');
  await expect(summary).toBeVisible();
  expect((await terminal.boundingBox()).y).toBeLessThan((await summary.boundingBox()).y);
  await terminal.locator(".fc-stats").evaluate(el => el.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: testInfo.outputPath(`sum-columns-${theme}.png`), animations: "disabled" });
  await page.setViewportSize({ width: 390, height: 844 });
  await terminal.getByRole('button', { name: '6M / 9M', exact: true }).click();
  const income = terminal.locator('tr[data-metric="interest_income"]').filter({ hasText: 'Итого' });
  await expect(income).toContainText('9,447,836,814');
  await terminal.locator('.fc-scroll').evaluate(el=>{el.scrollLeft=el.scrollWidth;});
  await income.evaluate(el=>el.scrollIntoView({block:'center'}));
  await income.getByRole('button').last().click();
  const passport = page.getByRole('dialog', { name: 'Source passport' });
  await expect(passport.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', /openinfo/);
  await passport.getByRole('button', { name: 'Close', exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await terminal.locator(".fc-stats").evaluate(el => el.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: testInfo.outputPath(`sum-columns-${theme}-mobile.png`), animations: "disabled" });
  await page.getByRole('group', { name: 'Accounting standard' }).getByRole('button', { name: 'MSFO', exact: true }).click();
  await expect(terminal.locator('tr[data-metric="interest_income"]')).toHaveCount(0);
  await expect(page.getByTestId('ifrs-investor').getByText('No approved source rows for this scope.')).toBeVisible();
});

test('SUM workspace panels include the same year columns', async ({ page }) => {
  await setup(page, { func: 'SUM' });
  await page.getByRole('button', { name: 'PNL · Panels', exact: true }).click();
  const panel = page.locator('.terminal-work-panel').first();
  await expect(panel).toHaveAttribute('data-terminal-function', 'SUM');
  await expect(panel.getByTestId('financial-columns').locator('.fc-table thead')).toContainText('2025');
  await expect(panel.locator('tr[data-metric="interest_income"]')).toBeVisible();
  await expect(panel.locator('.terminal-summary')).toBeVisible();
  await expect(panel.locator('tr[data-metric="cash"]')).toHaveCount(0);
  await panel.getByLabel(/^Function/).selectOption('BS');
  await expect(panel.locator('tr[data-metric="cash"]')).toBeVisible();
  await expect(panel.locator('tr[data-metric="interest_income"]')).toHaveCount(0);
});

for (const fallback of [false, true]) test(`report panels expand and restore without losing state (fallback=${fallback})`, async ({ page }, testInfo) => {
  if (fallback) await page.addInitScript(() => {
    Element.prototype.requestFullscreen = () => Promise.reject(new Error('Fullscreen unavailable'));
  });
  await setup(page, { ticker: 'HMKB', func: 'SUM', theme: fallback ? 'light' : 'dark', reports: recentReports });
  await page.getByRole('button', { name: 'PNL · Panels', exact: true }).click();
  const panels = page.locator('.terminal-work-panel'), first = panels.first();
  await expect(panels).toHaveCount(1);
  const grid = await page.locator('.terminal-panel-grid').boundingBox();
  expect((await first.boundingBox()).width).toBeGreaterThan(grid.width - 2);
  await page.getByRole('button', { name: 'Add panel', exact: true }).click();
  await expect(panels).toHaveCount(2);
  const second = panels.nth(1);
  const search = second.getByRole('searchbox');
  await search.fill('процентных доходов');
  const assertExpanded = async () => {
    await expect(second).toHaveClass(/is-expanded/);
    const box = await second.boundingBox(), viewport = page.viewportSize();
    expect(Math.abs(box.width - viewport.width)).toBeLessThanOrEqual(1);
    expect(Math.abs(box.height - viewport.height)).toBeLessThanOrEqual(1);
    expect(Math.abs(box.x) + Math.abs(box.y)).toBeLessThanOrEqual(1);
    await expect(second.getByRole('button', { name: 'Restore', exact: true })).toBeInViewport();
    await expect(second.locator('.fc-table thead')).toContainText('2026 · 9M');
  };
  await second.getByRole('button', { name: 'Full screen', exact: true }).click();
  await assertExpanded();
  if (fallback) {
    await page.evaluate(() => {
      const overlay = document.createElement('aside');
      overlay.className = 'sponsor-overlay'; overlay.dataset.fullscreenTest = 'true';
      overlay.style.height = '390px'; overlay.textContent = 'Advertisement';
      document.body.append(overlay);
    });
    await expect(page.locator('[data-fullscreen-test]')).toBeHidden();
  }
  if (!fallback) await expect.poll(() => page.evaluate(() => !!document.fullscreenElement)).toBe(true);
  await second.locator('.fc-table tbody td').last().getByRole('button').click();
  await expect(page.getByRole('dialog', { name: 'Source passport' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Source passport' })).toHaveCount(0);
  await assertExpanded();
  await page.screenshot({ path: testInfo.outputPath(`panel-fullscreen-${fallback}.png`), animations: 'disabled' });
  await second.getByRole('button', { name: 'Restore', exact: true }).click();
  await expect(second).not.toHaveClass(/is-expanded/);
  if (fallback) await page.locator('[data-fullscreen-test]').evaluate(el => el.remove());
  await expect(search).toHaveValue('процентных доходов');
  await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBe(true);
  expect((await second.boundingBox()).width).toBeLessThan(grid.width * .6);
  if (!fallback) {
    await second.getByRole('button', { name: 'Full screen', exact: true }).click();
    await expect.poll(() => page.evaluate(() => !!document.fullscreenElement)).toBe(true);
    await page.evaluate(() => document.exitFullscreen());
    await expect(second).not.toHaveClass(/is-expanded/);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await second.getByRole('button', { name: 'Full screen', exact: true }).click();
  await assertExpanded();
  await page.screenshot({ path: testInfo.outputPath(`panel-fullscreen-${fallback}-mobile.png`), animations: 'disabled' });
  await page.keyboard.press('Escape');
  await expect(second).not.toHaveClass(/is-expanded/);
  await expect(search).toHaveValue('процентных доходов');
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden');
  await first.getByRole('button', { name: 'Full screen', exact: true }).click();
  await first.getByRole('button', { name: 'Remove panel', exact: true }).click();
  await expect(panels).toHaveCount(1);
  await expect(panels.first()).not.toHaveClass(/is-expanded/);
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden');
});

test('source columns preserve units, periods and passports at desktop and mobile sizes', async ({ page }, testInfo) => {
  await setup(page);
  const terminal = page.getByTestId('financial-columns');
  await expect(terminal).toBeVisible();
  await terminal.getByRole('button', { name: '6M / 9M', exact: true }).click();
  await expect(terminal.locator('.fc-stats > div').filter({ hasText: 'Assets' })).toContainText('2026-09-30');
  const income = terminal.locator('tr[data-metric="interest_income"]').filter({ hasText: 'Итого' });
  await expect(income).toContainText('9,447,836,814');
  await expect(terminal.getByText('Amounts: thousands UZS', { exact: false })).toBeVisible();
  await expect(income.locator('th')).toHaveText('Итого процентных доходовОтчёт о финансовых результатах: 1.л');
  await income.getByRole('button').last().click();
  const passport = page.getByRole('dialog', { name: 'Source passport' });
  await expect(passport.locator('h4').first()).toHaveText('Итого процентных доходов');
  await expect(passport).toContainText('л. Итого процентных доходов');
  await expect(passport).toContainText('1л');
  await expect(passport).toContainText('separate');
  await expect(passport.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', /openinfo/);
  await passport.getByRole('button', { name: 'Close', exact: true }).click();
  await terminal.getByRole('button', { name: 'Chart', exact: true }).click();
  await expect(terminal.getByRole('img', { name: 'Financial history' })).toBeVisible();
  await terminal.getByRole('button', { name: 'Table', exact: true }).click();
  await terminal.getByRole('tab', { name: 'Original forms', exact: true }).click();
  await expect(terminal.locator('tr[data-metric="staff_expense"]')).toHaveCount(0);
  await terminal.getByRole('searchbox').fill('1л');
  await expect(terminal.locator('tbody tr[data-metric]')).toHaveCount(1);
  await terminal.getByRole('button', { name: 'Reset', exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath('financial-columns-desktop.png'), fullPage: true, animations: 'disabled' });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(terminal.getByRole('button', { name: '6M / 9M', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('financial-columns-mobile.png'), fullPage: true, animations: 'disabled' });
});

test('changing standard clears source rows and gives an explicit missing-data state', async ({ page }) => {
  await setup(page);
  const terminal = page.getByTestId('financial-columns');
  await expect(terminal.locator('tr[data-metric="interest_income"]')).toBeVisible();
  await page.getByRole('group', { name: 'Accounting standard' }).getByRole('button', { name: 'MSFO', exact: true }).click();
  await expect(terminal.locator('tr[data-metric="interest_income"]')).toHaveCount(0);
  await expect(page.getByTestId('ifrs-investor').getByText('No approved source rows for this scope.')).toBeVisible();
  await expect(terminal.locator('.fc-legacy')).toHaveCount(0);
  await page.getByTestId('ifrs-investor').getByRole('tab', { name: 'Quality', exact: true }).click();
  await expect(page.getByTestId('ifrs-investor').getByText('No approved source rows for this scope.')).toBeVisible();
});

test('a failed financial source request can be retried without showing stale amounts', async ({ page }) => {
  await setup(page, { fail: true });
  const terminal = page.getByTestId('financial-columns');
  await expect(terminal.getByRole('alert')).toContainText('Could not load financial statements');
  await expect(terminal.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
  await expect(terminal.locator('tr[data-metric]')).toHaveCount(0);
});

for (const [width,theme] of [[1440,'dark'],[390,'light']]) test(`HMKB quarterly chart has readable recent periods and inspectable values at ${width}px`,async({page},info)=>{
  await page.setViewportSize({width,height:1000});
  const reports=JSON.parse(readFileSync('e2e/fixtures/hmkb-quarterly-chart.json','utf8'));
  await setup(page,{ticker:'HMKB',func:'PL',reports,theme});
  const terminal=page.getByTestId('financial-columns');
  await terminal.getByRole('button',{name:'Quarters',exact:true}).click();
  await terminal.getByRole('button',{name:'Chart',exact:true}).click();
  const chart=terminal.locator('.fc-chart'),plot=chart.locator('.fc-chart-plot');
  await expect(chart.locator('[data-chart-series]')).toHaveCount(3);
  await expect(plot.locator('.fc-chart-range')).toContainText('2026 Q3');
  await expect(plot.locator('svg')).toHaveAttribute('data-period-count',width===390?'3':'8');
  const svg=await plot.locator('svg').boundingBox();
  expect(svg.width).toBeLessThan(width);expect(svg.height).toBeGreaterThanOrEqual(280);
  await expect(plot.getByRole('button',{name:'Next periods',exact:true})).toBeDisabled();
  await plot.getByRole('button',{name:'Previous periods',exact:true}).click();
  await expect(plot.locator('.fc-chart-range')).not.toContainText('2026 Q3');
  await plot.getByRole('button',{name:'Latest periods',exact:true}).click();
  await expect(plot.locator('.fc-chart-range')).toContainText('2026 Q3');
  await plot.locator('[data-period-hit]').first().click({position:{x:10,y:20}});
  await expect(plot.locator('.fc-chart-reading')).toContainText(width===390?'2026 Q1':'2024 Q4');
  const period=plot.locator('[data-period-hit]').first();
  await period.focus();await page.keyboard.press('ArrowRight');
  await expect(plot.locator('.fc-chart-reading')).toContainText(width===390?'2026 Q2':'2025 Q1');
  if(width===390) {
    const client=await page.context().newCDPSession(page);
    const bounds=await plot.locator('svg').boundingBox(),y=bounds.y+100;
    await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:bounds.x+80,y}]});
    await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:bounds.x+160,y}]});
    await client.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
    await expect(plot.locator('.fc-chart-range')).toContainText('2025 Q4');
    await client.detach();
  }
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await chart.screenshot({path:info.outputPath('quarterly-chart.png')});
});
