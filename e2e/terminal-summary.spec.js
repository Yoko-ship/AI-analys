import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const report=JSON.parse(readFileSync(new URL('../tests/fixtures/sector_ui_report.json',import.meta.url),'utf8'));
test.use({hasTouch:true});

async function hoverBar(page, chart, index) {
  const bar=chart.locator('rect').nth(index);
  await bar.scrollIntoViewIfNeeded();
  const box=await bar.boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
}

async function expectHistoryFirst(sum) {
  const history=await sum.locator('.terminal-summary-history').boundingBox();
  const kpis=await sum.locator('.terminal-summary-kpis').boundingBox();
  const narrative=await sum.locator('.terminal-summary-narrative').boundingBox();
  expect(history.y+history.height,'Financial history should appear above the KPI cards').toBeLessThanOrEqual(kpis.y);
  expect(history.y+history.height,'Financial history should appear above the written analysis').toBeLessThanOrEqual(narrative.y);
}

test('SUM shows sourced KPIs, conclusion, risks and annual charts with honest gaps',async({page},testInfo)=>{
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_token', 'admin-token'));
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_theme', 'light'));
  await page.setViewportSize({width:1440,height:1000});
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url()),path=url.pathname;
    const json=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
    if(path==='/api/auth/me')return json({user:{id:1,is_admin:true,email:'admin@example.test'}});
    if(path.endsWith('/ai-report'))return json(report);
    if(path==='/api/catalog/companies')return json({ok:true,companies:[{ticker:'UZMK',company_name:'Узметкомбинат',sector:'manufacturing',total_count:24}]});
    if(path.startsWith('/api/catalog/index/'))return json({ok:true,company_name:'Узметкомбинат',availability:{NSBU:{annual:[{year:2025,quarter:0}],quarter:[]}}});
    if(path.endsWith('/analytics'))return json({ok:true,snapshot:{kind:'industry',period:'2025',net_profit:1e9},growth:[],quarters:{rows:[]},template:{selected_template:'industry',reason_code:'catalog_sector',rule_version:'sector-analysis-3.0'}});
    if(path.endsWith('/financials')&&url.searchParams.get('freq')==='quarterly')return json({ok:true,standard:'NSBU',scope:'separate',periods:['2026Q2','2026Q1'],series:{
      net_revenue:{money:true,values:{'2026Q1':50e9,'2026Q2':60e9}},net_profit:{money:true,values:{'2026Q1':2e9,'2026Q2':3e9}},
      total_equity:{money:true,values:{'2026Q1':70e9,'2026Q2':80e9}},total_liabilities:{money:true,values:{'2026Q1':180e9,'2026Q2':190e9}},
    }});
    if(path.endsWith('/financials'))return json({ok:true,standard:'NSBU',scope:'separate',periods:['2025','2023'],series:{net_revenue:{money:true,values:{2023:100e9,2025:120e9}},net_profit:{money:true,values:{2023:-5e9,2025:0}},total_assets:{money:true,values:{2023:200e9,2025:220e9}},total_equity:{money:true,values:{2023:50e9,2025:60e9}},total_liabilities:{money:true,values:{2023:150e9,2025:160e9}}}});
    if(path==='/api/currency/rates')return json({ok:true,as_of:url.searchParams.get('as_of'),rates:[{ccy:'USD',per_unit:10000,effective_date:url.searchParams.get('as_of')}]});
    return json({ok:true,items:[],rows:[],companies_synced:1,total_reports:24});
  });
  await page.goto('/catalog?t=UZMK&f=SUM&std=NSBU');
  const sum=page.locator('.terminal-summary');
  await expect(sum.locator('.terminal-summary-kpis > div')).toHaveCount(6);
  await expect(sum.locator('.terminal-summary-kpis')).toContainText('315,89');
  await expect(sum.locator('.terminal-summary-kpis')).toContainText('январь–июнь 2026');
  await expect(page.locator('.terminal-analytics')).not.toContainText(/catalog_sector|sector-analysis-3\.0|Шаблон:|industry|separate/);
  await expect(sum.locator('.terminal-summary-history')).toContainText('Последние данные: январь–июнь 2026. Баланс на 30 июня 2026 г.');
  await expect(sum.getByLabel('Валюта графиков')).toHaveValue('UZS');
  await expect(sum.getByLabel('Валюта графиков').locator('option:checked')).toHaveText('Сумы');
  await expect(sum.locator('.terminal-summary-charts')).toContainText('млрд сумов');
  await expect(sum.getByRole('heading',{name:'Вывод',exact:true})).toBeVisible();
  await expect(sum.getByRole('heading',{name:'Риски и что смотреть',exact:true})).toBeVisible();
  await expect(sum.getByText('Качество прибыли',{exact:true})).toBeVisible();
  await expect(sum.getByRole('img',{name:'Выручка и прибыль по годам'})).toBeVisible();
  await expect(sum.getByRole('img',{name:'Структура баланса по годам'})).toBeVisible();
  await expectHistoryFirst(sum);
  await expect(sum.getByRole('img',{name:'Выручка и прибыль по годам'})).toContainText('6 мес. 2026');
  await expect(sum.getByRole('img',{name:'Выручка и прибыль по годам'})).toContainText('Выручка: 110');
  await expect(sum.getByRole('img',{name:'Структура баланса по годам'})).toContainText('Капитал: 80');
  const incomeChart=sum.getByRole('img',{name:'Выручка и прибыль по годам'});
  const balanceChart=sum.getByRole('img',{name:'Структура баланса по годам'});
  const incomeCard=sum.locator('.terminal-summary-card').filter({has:page.getByRole('img',{name:'Выручка и прибыль по годам'})});
  const balanceCard=sum.locator('.terminal-summary-card').filter({has:page.getByRole('img',{name:'Структура баланса по годам'})});
  await expect(incomeCard).toBeVisible();
  await expect(balanceCard).toBeVisible();
  const incomeTooltip=incomeCard.getByRole('tooltip');
  const balanceTooltip=balanceCard.getByRole('tooltip');
  await incomeCard.scrollIntoViewIfNeeded();
  await hoverBar(page,incomeChart,0);
  await expect(incomeTooltip).toBeVisible();
  await expect(incomeTooltip).toContainText('2023');
  await expect(incomeTooltip).toContainText('Выручка');
  await expect(incomeTooltip).toContainText('100 млрд сумов');
  await expect(incomeTooltip).toContainText('-5 млрд сумов');
  await incomeTooltip.hover();
  await expect(incomeTooltip).toBeVisible();
  await expect(incomeTooltip).toContainText('2023');
  await incomeCard.screenshot({path:testInfo.outputPath('history-tooltip-desktop.png'),animations:'disabled'});
  await page.mouse.move(0,0);
  await expect(incomeTooltip).toHaveCount(0);
  await incomeCard.getByRole('button',{name:'2024',exact:true}).focus();
  await expect(incomeTooltip).toContainText('Нет данных');
  await incomeCard.getByRole('button',{name:'2024',exact:true}).press('Escape');
  await expect(incomeTooltip).toHaveCount(0);
  await incomeCard.getByRole('button',{name:'2024',exact:true}).press('Enter');
  await expect(incomeTooltip).toBeVisible();
  await incomeCard.getByRole('button',{name:'2024',exact:true}).press('Tab');
  await expect(incomeCard.getByRole('button',{name:'2025',exact:true})).toBeFocused();
  await expect(incomeTooltip).toContainText('120 млрд сумов');
  await expect(incomeTooltip).toContainText('0 млрд сумов');
  await hoverBar(page,balanceChart,-1);
  await expect(balanceTooltip).toContainText('6 мес. 2026');
  await expect(balanceTooltip).toContainText('190 млрд сумов');
  await expect(balanceTooltip).toContainText('80 млрд сумов');
  const axisBoxes=await sum.getByRole('img',{name:'Выручка и прибыль по годам'}).locator('text[x="52"]').evaluateAll(nodes=>nodes.map(el=>{const r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom};}).sort((a,b)=>a.top-b.top));
  expect(axisBoxes.every((box,i)=>i===0||box.top>=axisBoxes[i-1].bottom)).toBe(true);
  await expect(sum).toContainText('2024');
  await expect(sum.locator('.terminal-history-gap')).toContainText('2024');
  await expect(page.locator('.catalog-selected-report')).toHaveCount(0);
  await expect(page.locator('.catalog-report-section')).toHaveCount(0);
  await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
  await page.screenshot({path:testInfo.outputPath('sum-desktop.png'),fullPage:true,animations:'disabled'});
  await sum.getByLabel('Валюта графиков').selectOption('USD');
  await expect(sum.getByLabel('Валюта графиков').locator('option:checked')).toHaveText('Доллары США');
  await expect(sum.locator('.terminal-summary-charts')).toContainText('млн долларов');
  await expect(sum.locator('.terminal-fx-rates')).toContainText('2025-12-31');
  await expect(sum.locator('.terminal-fx-rates')).toContainText('2026-06-30');
  await hoverBar(page,balanceChart,-1);
  await expect(balanceTooltip).toContainText('19 млн долларов');
  await expect(balanceTooltip).toContainText('8 млн долларов');
  await page.locator('.theme-toggle').click();
  await balanceCard.scrollIntoViewIfNeeded();
  await hoverBar(page,balanceChart,-1);
  await expect(balanceTooltip).toContainText('19 млн долларов');
  await balanceCard.screenshot({path:testInfo.outputPath('history-tooltip-dark.png'),animations:'disabled'});
  await page.locator('.theme-toggle').click();
  await sum.getByText('Таблица истории',{exact:true}).click();
  await expect(sum.locator('.terminal-history-table')).toContainText('12');
  const current=sum.locator('.terminal-history-table tr').filter({hasText:'6 мес. 2026'});
  await expect(current).toContainText('11');
  await expect(current).toContainText('0,5');
  await page.setViewportSize({width:390,height:844});
  await expectHistoryFirst(sum);
  await balanceCard.getByRole('button',{name:'6 мес. 2026',exact:true}).tap();
  await expect(balanceTooltip).toBeVisible();
  await expect(balanceTooltip).toContainText('8 млн долларов');
  const tooltipBox=await balanceTooltip.boundingBox();
  expect(tooltipBox.x).toBeGreaterThanOrEqual(0);
  expect(tooltipBox.x+tooltipBox.width).toBeLessThanOrEqual(390);
  await balanceCard.screenshot({path:testInfo.outputPath('history-tooltip-mobile.png'),animations:'disabled'});
  await balanceCard.getByRole('heading').tap();
  await expect(balanceTooltip).toHaveCount(0);
  await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
  await page.screenshot({path:testInfo.outputPath('sum-mobile.png'),fullPage:true,animations:'disabled'});
  await sum.locator('.terminal-summary-history').screenshot({path:testInfo.outputPath('sum-history-mobile.png'),animations:'disabled'});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.route('**/api/company/UZMK/financials?**',route=>new URL(route.request().url()).searchParams.get('freq')==='quarterly'
    ? route.fulfill({status:503,json:{detail:'Current filing temporarily unavailable'}}) : route.fallback());
  await page.reload();
  await expect(sum.locator('.terminal-summary-history [role="alert"]')).toHaveText('Не удалось загрузить текущий отчёт.');
  await expect(sum.getByRole('img',{name:'Выручка и прибыль по годам'})).toContainText('2025');
  await expect(sum.getByRole('img',{name:'Выручка и прибыль по годам'})).not.toContainText('2026');
});

for (const [lang, currencyLabel, period, balanceDate, scopeLabel, unit] of [
  ['ru', 'Валюта графиков', 'январь–сентябрь 2026', '30 сентября 2026 г.', 'Отчётность компании', 'млрд сумов'],
  ['uz', 'Grafiklar valyutasi', '2026-yil yanvar–sentabr', '30-sentabr, 2026', 'Kompaniya hisoboti', 'mlrd so‘m'],
  ['en', 'Chart currency', 'January–September 2026', 'September 30, 2026', 'Company financial statements', 'billion som'],
]) test(`nine-month history uses reader-friendly reporting labels (${lang})`, async ({page}, testInfo) => {
  await page.addInitScript(language => {
    localStorage.setItem('uz_stock_analyzer_token', 'admin-token');
    localStorage.setItem('uz_stock_analyzer_language', language);
    localStorage.setItem('uz_stock_analyzer_theme', 'light');
  }, lang);
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url()), path = url.pathname;
    const json = body => route.fulfill({json: body});
    if (path === '/api/auth/me') return json({user: {id: 1, is_admin: true}});
    if (path === '/api/catalog/companies') return json({ok: true, companies: [{ticker: 'UZMK', company_name: 'Узметкомбинат'}]});
    if (path.startsWith('/api/catalog/index/')) return json({ok: true, company_name: 'Узметкомбинат', availability: {NSBU: {annual: [{year: 2025, quarter: 0}], quarter: []}}});
    if (path.endsWith('/analytics')) return json({ok: true, snapshot: {kind: 'industry', period: '2025'}, template: {selected_template: 'industry', reason_code: 'catalog_sector', rule_version: 'sector-analysis-3.0'}});
    if (path.endsWith('/financials')) return json({ok: true, standard: 'NSBU', period_basis: 'cumulative_ytd', periods: url.searchParams.get('freq') === 'quarterly' ? ['2026Q3'] : ['2025'], series: {}});
    if (path.endsWith('/ai-report')) return json({status: 'unavailable'});
    return json({ok: true, rows: [], items: []});
  });
  await page.goto('/catalog?t=UZMK&f=SUM&std=NSBU');
  const history = page.locator('.terminal-summary-history');
  await expect(history.getByLabel(currencyLabel)).toBeVisible();
  await expect(history).toContainText(period);
  await expect(history).toContainText(balanceDate);
  await expect(history).toContainText(scopeLabel);
  await expect(history.locator('.terminal-summary-charts')).toContainText(unit);
  await expect(page.locator('.terminal-analytics')).not.toContainText(/catalog_sector|sector-analysis|industry|separate|NSBU|2026Q3|9M/);
  await page.setViewportSize({width: 390, height: 844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({path: testInfo.outputPath(`reporting-copy-${lang}-mobile.png`), fullPage: true, animations: 'disabled'});
});
