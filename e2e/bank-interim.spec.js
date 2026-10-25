import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const fixture=JSON.parse(readFileSync('e2e/fixtures/ifrs-investor.json','utf8'));

test('IFRS interim captions retain YTD basis and BS excludes TTM',async({page})=>{
  await page.addInitScript(()=>localStorage.setItem('uz_stock_analyzer_language','en'));
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url());
    let result={ok:true,items:[],companies:[],securities:{},periods:[],series:{}};
    if(url.pathname.endsWith('/financials/columns')){
      result=structuredClone(fixture);
      result.columns=[{key:'2024-06-30',label:'2024-06-30',end:'2024-06-30',basis:'ytd'},{key:'ttm:2024-06-30',label:'TTM · 2024-06-30',end:'2024-06-30',basis:'ttm'}];
      for(const row of [...result.rows,...Object.values(result.statements).flatMap(gs=>gs.flatMap(g=>g.rows)),...result.ratios]){
        const cell=Object.values(row.cells)[0];
        row.cells={'2024-06-30':{...cell,period_end:'2024-06-30',period_start:'2024-01-01'},'ttm:2024-06-30':{value:null,quality:row.kind==='stock'?'not_applicable':'missing'}};
      }
    }
    return route.fulfill({json:result});
  });
  await page.goto('/company/SQBN?tab=financials');
  await page.getByRole('button',{name:'МСФО',exact:true}).click();
  const ui=page.getByTestId('ifrs-investor');
  await ui.getByRole('button',{name:'6M / 9M / TTM',exact:true}).click();
  await ui.getByRole('tab',{name:'PL Profit or loss',exact:true}).click();
  await expect(ui.locator('thead')).toContainText('YTD');
  await expect(ui.locator('thead')).toContainText('TTM');
  await expect(ui).not.toContainText('Growth QoQ');
  await ui.getByRole('tab',{name:'BS Balance',exact:true}).click();
  await expect(ui.locator('thead')).not.toContainText('TTM');
  await expect(ui.locator('thead')).toContainText('2024-06-30');
});
