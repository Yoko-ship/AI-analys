import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const fund=JSON.parse(readFileSync(new URL('./fixtures/ifrs-investor-fund.json',import.meta.url),'utf8'));
const reports=JSON.parse(readFileSync(new URL('../tests/fixtures/terminal_sector_reports.json',import.meta.url),'utf8')).reports;

for(const ticker of ['UZAS','HMKB','UZNF'])for(const func of ['SUM','PL'])test(`${ticker} ${func} follows its sector template`,async({page},testInfo)=>{
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_token', 'admin-token'));
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_theme', 'light'));
  const report=reports[ticker],kind=report.issuer.organization_type,form=ticker==='UZNF'?'MSFO':'NSBU';
  const main={ticker,date:'2026-09-01',source_url:'https://cbu.uz/main.xlsx',assets_bn:43114.828277036795,assets_share_pct:4.2,assets_rank:8,rank_population:35};
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url()),path=url.pathname;
    const json=body=>route.fulfill({json:body});
    if(path==='/api/auth/me')return json({user:{id:1,is_admin:true,email:'admin@example.test'}});
    if(path.endsWith('/financials/columns')&&ticker==='UZNF')return json(fund);
    if(path.endsWith('/ai-report'))return json(report);
    if(path.endsWith('/financials')){
      if(url.searchParams.get('form')==='NSBU'&&url.searchParams.has('scope'))return route.fulfill({status:422,json:{detail:'scope must be consolidated or separate and requires MSFO'}});
      return json({ok:true,organization_type:ticker==='UZNF'?'fund':kind,periods:['2025','2024'],series:{net_revenue:{money:true,label_ru:kind==='insurance'?'Заработанные премии':'Совокупные доходы',values:{2025:100e9,2024:80e9}},net_profit:{money:true,values:{2025:5e9,2024:4e9}}}});
    }
    if(path==='/api/catalog/companies')return json({ok:true,companies:[{ticker,company_name:report.issuer.name,sector:'finance'}]});
    if(path.startsWith('/api/catalog/index/'))return json({ok:true,company_name:report.issuer.name,availability:{[form]:{annual:[{year:2025,quarter:0}],quarter:[]}}});
    if(path.endsWith('/analytics'))return json({ok:true,snapshot:{kind,period:'2025'},growth:[],quarters:{rows:[]},cbu:kind==='bank'?{main,npl:{ticker,date:'2026-08-01',npl_pct:1.4,source_url:'https://cbu.uz/npl.xlsx'}}:{},cbu_history:kind==='bank'?[{...main,date:'2026-07-01'},main]:[]});
    return json({ok:true,rows:[],periods:[],series:{},companies_synced:1,total_reports:1});
  });
  await page.goto(`/catalog?t=${ticker}&f=${func}&std=${form}`);
  if(ticker==='UZNF'){
    const ui=page.getByTestId('ifrs-investor');
    await expect(ui).toBeVisible();
    if(func==='SUM'){
      await expect(ui.locator('.investor-kpis')).toContainText('29 861,54'.replaceAll(' ','\u00a0'));
    }else{
      await expect(ui.locator('tr[data-field="profit"]')).toContainText('1 403,15'.replaceAll(' ','\u00a0'));
      await expect(ui).toContainText('24.12.2024–31.12.2025');
    }
    await expect(ui).not.toContainText('5 400');
    return;
  }
  if(func==='PL'){
    await page.getByText('Ранее опубликованные показатели', { exact: true }).click();
    const overview=page.locator('.terminal-statement-overview');
    await expect(overview.getByRole('img',{name:'Мост: от доходов к чистой прибыли'})).toBeVisible();
    const contrast=await overview.evaluate(root=>{
      const luminance=color=>{
        const rgb=color.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
        return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
      };
      return [...root.querySelectorAll('.terminal-summary-card h3,svg text,td,.terminal-csv')].map(node=>{
        let parent=node;
        while(parent && ['rgba(0, 0, 0, 0)','transparent'].includes(getComputedStyle(parent).backgroundColor))parent=parent.parentElement;
        const background=luminance(parent?getComputedStyle(parent).backgroundColor:'rgb(255,255,255)');
        const ink=luminance(node.tagName==='text'?getComputedStyle(node).fill:getComputedStyle(node).color);
        return (Math.max(ink,background)+.05)/(Math.min(ink,background)+.05);
      });
    });
    for(const ratio of contrast)expect(ratio).toBeGreaterThanOrEqual(4.5);
    if(ticker==='HMKB'){
      await page.locator('.company-financials').getByRole('button',{name:'Таблица',exact:true}).click();
      await expect(page.locator('.fin-table td button').first()).toHaveCSS('background-color','rgba(0, 0, 0, 0)');
      await page.evaluate(()=>window.scrollTo(0,0));
      await page.screenshot({path:testInfo.outputPath('hmkb-chart-light-theme.png'),fullPage:true,animations:'disabled'});
    }
    if(kind==='insurance'){
      await expect(page.locator('.company-financials')).toContainText('Заработанные премии');
      await expect(overview).toContainText('Заработанные премии');
      await expect(overview).toContainText('Комбинированный коэффициент');
      await expect(overview).not.toContainText('Маржинальность по годам');
    }else if(ticker==='UZNF'){
      await expect(page.locator('.company-financials')).not.toContainText('Выручка');
      await expect(overview).toContainText('Дивидендный доход');
      await expect(overview).toContainText('Нереализованная переоценка');
      await expect(overview).not.toContainText('Маржинальность по годам');
    }else{
      await expect(page.locator('.company-financials')).toContainText('Совокупные доходы');
      await expect(overview).toContainText('Чистая прибыль / совокупные доходы');
      await expect(overview).not.toContainText('Валовая');
    }
    return;
  }
  const sum=page.locator('.terminal-summary');
  await expect(sum.locator('.terminal-summary-history').getByRole('img').first()).toBeVisible();
  await expect(sum.locator('.terminal-summary-history')).not.toContainText('Не удалось загрузить историю.');
  await expect(sum.locator(':scope > .terminal-summary-kpis>div')).toHaveCount(6);
  if(kind==='insurance'){
    await expect(sum.locator('.terminal-summary-kpis')).toContainText('Заработанные премии');
    await expect(sum.locator('.terminal-summary-kpis')).toContainText('107,2%');
    await expect(sum.locator('.terminal-summary-kpis')).not.toContainText('маржа');
    await expect(sum).not.toContainText('Выручка и прибыль по годам');
  }else if(ticker==='UZNF'){
    await expect(sum.locator('.terminal-summary-kpis')).toContainText('NAV на акцию');
    await expect(sum.locator('.terminal-summary-kpis')).toContainText('29 861,54'.replaceAll(' ','\u00a0'));
    await expect(sum).toContainText('Нужна сверка количества и номинала акций');
    await expect(sum).not.toContainText('Выручка и прибыль по годам');
    await expect(sum.locator('.terminal-summary-kpis')).not.toContainText('ROE');
  }else{
    const context=page.locator('.terminal-bank-overview');
    await expect(context).toContainText('8 / 35');
    await expect(context).toContainText('2026-09-01');
    await expect(context).toContainText('2026-08-01');
    await context.getByText('Ежемесячная история ЦБ',{exact:true}).click();
    await expect(context.locator('tbody tr')).toHaveCount(2);
    await expect(context).toContainText('2026-07-01');
    await expect(context).not.toContainText('2026-08-01 · млрд');
  }
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:testInfo.outputPath(`${ticker}-overview-mobile.png`),fullPage:true});
});
