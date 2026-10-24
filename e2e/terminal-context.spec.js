import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const report=JSON.parse(readFileSync(new URL('../tests/fixtures/sector_ui_report.json',import.meta.url),'utf8'));

for(const [func,kind] of [['RAT','bank'],['BS','insurance']]){
  test(`${func} keeps financial-sector ratios and reporting periods explicit`,async({page})=>{
    await page.route('**/api/**',route=>{
      const path=new URL(route.request().url()).pathname;
      const json=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
      if(path==='/api/auth/me')return route.fulfill({status:401,body:'{}'});
      if(path.endsWith('/ai-report'))return json({...report,issuer:{...report.issuer,organization_type:kind},ratios:[{metric_code:'nim',name_ru:'Чистая процентная маржа',value:4.2,unit:'percent'}]});
      if(path==='/api/catalog/companies')return json({ok:true,companies:[{ticker:'TEST',company_name:'Test issuer',sector:'finance'}]});
      if(path.startsWith('/api/catalog/index/'))return json({ok:true,company_name:'Test issuer',availability:{NSBU:{annual:[{year:2025,quarter:0}],quarter:[]}}});
      if(path.endsWith('/analytics'))return json({ok:true,snapshot:{kind,period:'2025',roe:20,de:null},growth:[],quarters:{rows:[]}});
      return json({ok:true,items:[],rows:[],periods:[],series:{},companies_synced:1,total_reports:1});
    });
    await page.goto(`/catalog?t=TEST&f=${func}&std=NSBU`);
    if(func==='RAT'){
      await expect(page.locator('.terminal-sector-metrics')).toContainText('2026Q2');
      await expect(page.locator('.terminal-annual-ratios caption')).toContainText('2025');
      await expect(page.locator('.terminal-annual-ratios')).not.toContainText('D/E');
    }else{
      await expect(page.locator('.terminal-stability-kpis')).not.toContainText('Обязательства / капитал');
      await expect(page.locator('.terminal-stability-kpis')).toContainText('Деньги / текущие обязательства');
    }
  });
}
