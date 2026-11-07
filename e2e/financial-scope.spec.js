import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const fixture=JSON.parse(readFileSync('e2e/fixtures/ifrs-investor.json','utf8'));

test('GRBK finance hides the redundant standard selector on desktop and mobile, including empty quarters',async({page},testInfo)=>{
  const forms=[];
  await page.addInitScript(()=>{
    localStorage.setItem('uz_stock_analyzer_language','ru');
    sessionStorage.setItem('uz_sponsor_seen','1');
  });
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url());
    let data={ok:true,items:[],companies:[],securities:{},periods:[],series:{}};
    if(url.pathname==='/api/company/GRBK/financials'){
      forms.push(url.searchParams.get('form'));
      if(url.searchParams.get('freq')!=='quarterly')data={ok:true,periods:['2025'],series:{
        net_profit:{money:true,unit:'UZS',values:{2025:5150000000}},
      }};
    }
    return route.fulfill({json:data});
  });
  await page.goto('/company/GRBK?tab=financials');
  const standard=page.getByRole('group',{name:'Стандарт',exact:true});
  await expect(standard).toHaveCount(0);
  await expect(page.getByRole('button',{name:/^(НСБУ|МСФО)$/})).toHaveCount(0);
  await page.getByRole('button',{name:'Таблица',exact:true}).click();
  await expect(page.locator('.fin-table')).toContainText('5,15');
  await page.locator('.company-financials').screenshot({path:testInfo.outputPath('grbk-standard-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'Квартальные',exact:true}).click();
  await expect(page.locator('.company-financials')).toContainText('Квартальные финансовые данные пока недоступны');
  await expect(standard).toHaveCount(0);
  await expect(page.getByRole('button',{name:/^(НСБУ|МСФО)$/})).toHaveCount(0);
  await page.getByRole('button',{name:'Годовые',exact:true}).click();
  await expect(page.locator('.fin-table')).toContainText('5,15');
  await page.locator('.company-financials').screenshot({path:testInfo.outputPath('grbk-standard-mobile.png')});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  expect(forms.length).toBeGreaterThan(0);
  expect(forms.every(form=>form==='NSBU')).toBe(true);
});

test('scope switch isolates tables and embedded source passports and remains usable when empty',async({page})=>{
  await page.addInitScript(()=>localStorage.setItem('uz_stock_analyzer_language','en'));
  const scopes=[];
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url());
    let result={ok:true,items:[],companies:[],securities:{},periods:[],series:{}};
    if(url.pathname.endsWith('/financials/columns')){
      const scope=url.searchParams.get('scope')||'consolidated';scopes.push(scope);
      result=structuredClone(fixture);result.scope=scope;
      const raw=scope==='separate'?1000:5000;
      for(const row of [...result.rows,...Object.values(result.statements).flatMap(gs=>gs.flatMap(g=>g.rows))]){
        if(row.metric_id!=='net_income')continue;
        for(const column of result.columns)row.cells[column.key]={...row.cells[column.key],scope,value:String(raw*12920.48),raw_value:raw,unit_scale:1000,currency:'USD',fx:{rate:12920.48,as_of:'2025-12-31',effective_date:'2025-12-31'}};
      }
      if(url.searchParams.get('freq')==='quarter')result={...result,columns:[],rows:[],statements:{pl:[],bs:[],cf:[],equity:[]}};
    }
    return route.fulfill({json:result});
  });
  await page.goto('/company/DEMO?tab=financials&standard=MSFO');
  const ui=page.getByTestId('ifrs-investor');
  await ui.getByRole('tab',{name:'PL Profit or loss',exact:true}).click();
  await ui.getByLabel('Scope',{exact:true}).selectOption('separate');
  const profit=ui.locator('tr[data-field="profit"]');
  await expect(profit).toContainText('12.92');
  await expect(profit).not.toContainText('64.6');
  await profit.getByRole('button').last().click();
  await expect(page.getByRole('dialog')).toContainText('separate');
  await expect(page.getByRole('dialog')).toContainText('USD');
  await expect(page.getByRole('dialog')).toContainText('12920.48');
  await expect(page.getByRole('dialog')).toContainText('2025-12-31');
  await page.keyboard.press('Escape');
  await ui.getByRole('button',{name:'Quarters',exact:true}).click();
  await expect(ui.getByText('No approved source rows for this scope.')).toBeVisible();
  await expect(ui.getByLabel('Scope',{exact:true})).toBeVisible();
  await ui.getByRole('button',{name:'Annual',exact:true}).click();
  await ui.getByLabel('Scope',{exact:true}).selectOption('consolidated');
  await expect(profit).toContainText('64.6');
  expect(scopes).toContain('separate');
});
