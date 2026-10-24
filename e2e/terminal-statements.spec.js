import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const report=JSON.parse(readFileSync(new URL('../tests/fixtures/sector_ui_report.json',import.meta.url),'utf8'));

for(const [func,label] of [['PL','Мост: от доходов к чистой прибыли'],['BS','Из чего состоят активы']]){
  test(`${func} renders the mockup's statement overview using verified report facts`,async({page},testInfo)=>{
    await page.setViewportSize({width:1440,height:1000});
    await page.route('**/api/**',route=>{
      const path=new URL(route.request().url()).pathname;
      const json=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
      if(path==='/api/auth/me')return route.fulfill({status:401,body:'{}'});
      if(path.endsWith('/ai-report'))return json(report);
      if(path==='/api/catalog/companies')return json({ok:true,companies:[{ticker:'UZMK',company_name:'Узметкомбинат',sector:'manufacturing'}]});
      if(path.startsWith('/api/catalog/index/'))return json({ok:true,company_name:'Узметкомбинат',availability:{NSBU:{annual:[{year:2025,quarter:0}],quarter:[]}}});
      if(path.endsWith('/financials'))return json({ok:true,standard:'NSBU',scope:'separate',periods:['2025','2023'],series:{net_revenue:{money:true,values:{2023:100e9,2025:120e9}},net_profit:{money:true,values:{2023:5e9,2025:6e9}},total_assets:{money:true,values:{2023:200e9,2025:220e9}},total_equity:{money:true,values:{2023:50e9,2025:60e9}}}});
      return json({ok:true,items:[],rows:[],companies_synced:1,total_reports:24});
    });
    await page.goto(`/catalog?t=UZMK&f=${func}&std=NSBU`);
    const overview=page.locator('.terminal-statement-overview');
    await expect(overview.getByRole('img',{name:label})).toBeVisible();
    await expect(overview).toContainText('2026Q2');
    await expect(overview.locator('.terminal-statement-facts')).toBeVisible();
    await expect(overview.locator('.terminal-statement-facts')).toContainText('База сравнения');
    if(func==='PL'){
      await expect(overview.getByRole('heading',{name:'Маржинальность по годам',exact:true})).toBeVisible();
      await expect(overview).toContainText('Расчётная разница');
      await expect(page.locator('.fin-chart path')).toHaveCount(0);
    }else{
      await expect(overview.getByRole('heading',{name:'Устойчивость',exact:true})).toBeVisible();
      await expect(overview).toContainText('Капитал / активы');
    }
    await page.screenshot({path:testInfo.outputPath(`${func}-desktop.png`),fullPage:true,animations:'disabled'});
    await page.setViewportSize({width:390,height:844});
    if(func==='PL')expect(await overview.locator('.terminal-history-chart text').first().evaluate(el=>parseFloat(getComputedStyle(el).fontSize)*el.ownerSVGElement.getBoundingClientRect().width/el.ownerSVGElement.viewBox.baseVal.width)).toBeGreaterThanOrEqual(10);
    await page.screenshot({path:testInfo.outputPath(`${func}-mobile.png`),fullPage:true,animations:'disabled'});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  });
}
