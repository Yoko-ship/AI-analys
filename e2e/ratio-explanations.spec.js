import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const columns=JSON.parse(readFileSync('e2e/fixtures/financial-columns-template.json','utf8')).annual;

async function setup(page,lang='en') {
  await page.addInitScript(lang=>{
    localStorage.setItem('uz_stock_analyzer_language',lang);
    localStorage.setItem('uz_stock_analyzer_token','ratio-help-test');
    sessionStorage.setItem('uz_sponsor_seen','1');
  },lang);
  await page.route('**/api/**',route=>{
    const path=new URL(route.request().url()).pathname;
    let data={ok:true,items:[],rows:[],companies:[],periods:[],series:{},availability:{}};
    if(path==='/api/auth/me')data={user:{id:1,is_admin:true}};
    if(path==='/api/catalog/companies')data={ok:true,companies:[{ticker:'HMKB',company_name:'Hamkorbank',sector:'finance'}]};
    if(path.startsWith('/api/catalog/index/'))data={ok:true,company_name:'Hamkorbank',availability:{NSBU:{annual:[{year:2025}]}}};
    if(path.endsWith('/financials'))data={ok:true,standard:'NSBU',periods:['2025'],series:Object.fromEntries(
      ['roe','roa','current_ratio','quick_ratio','debt_ratio','debt_to_equity','total_asset_turnover','return_to_capital_employed'].map(f=>[f,{money:false,unit:'%',values:{2025:20}}]))};
    if(path.endsWith('/financials/columns'))data=columns;
    if(path.endsWith('/analytics'))data={ok:true,snapshot:{kind:'bank',period:'2025',roe:20},growth:[],quarters:{rows:[]}};
    if(path.endsWith('/ai-report'))data={status:'available',period:'2025',ratios:[
      {metric_code:'nim',name_en:'NIM',name_ru:'Чистая процентная маржа',value:4.2,unit:'percent',meaning_en:'Net interest income relative to average earning assets.',meaning_ru:'Чистый процентный доход относительно средних доходных активов.'},
      {metric_code:'cost_of_risk',name_en:'Cost of risk',value:null,reason_code:'INPUTS_MISSING',meaning_en:'Credit loss expense relative to average loans.'},
    ]};
    return route.fulfill({json:data});
  });
}

test('every company ratio uses ! and opens its description above with keyboard and touch',async({page},testInfo)=>{
  await setup(page);
  await page.goto('/company/HMKB?tab=financials');
  await page.getByRole('button',{name:'Key Ratios',exact:true}).click();
  await page.getByRole('button',{name:'Table',exact:true}).click();
  const markers=page.locator('.company-financials .term-info-btn');
  await expect(markers).toHaveCount(8);
  expect(await markers.allTextContents()).toEqual(Array(8).fill('!'));
  const marker=markers.first(),tip=page.getByRole('tooltip');
  await marker.evaluate(el=>el.scrollIntoView({block:'center'}));
  await marker.focus();
  await expect(tip).toBeVisible();
  await expect(tip).toContainText('ROE');
  await expect.poll(async()=>{const a=await marker.boundingBox(),b=await tip.boundingBox();return b.y+b.height<a.y;}).toBe(true);
  await expect(marker).toHaveAttribute('aria-describedby',await tip.getAttribute('id'));
  await page.keyboard.press('Escape');
  await expect(tip).toHaveCount(0);
  await marker.hover();
  await expect(tip).toBeVisible();
  await expect(tip).toHaveCSS('opacity','1');
  await page.screenshot({path:testInfo.outputPath('ratio-help-desktop.png'),animations:'disabled'});
  await marker.click();
  await page.mouse.move(1,1);
  await expect(tip).toBeVisible();
  await expect(tip.getByRole('button',{name:'Copy',exact:true})).toBeVisible();
  await marker.click();
  await expect(tip).toHaveCount(0);
  await page.setViewportSize({width:390,height:844});
  await marker.evaluate(el=>el.scrollIntoView({block:'center'}));
  await marker.click();
  await expect(tip).toBeVisible();
  const box=await tip.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(390);
  await expect(tip).toHaveCSS('opacity','1');
  await page.screenshot({path:testInfo.outputPath('ratio-help-mobile.png'),animations:'disabled'});
  await page.mouse.click(1,1);
  await expect(tip).toHaveCount(0);
});

test('catalog ratio meanings move into ! while missing-data reasons remain visible',async({page})=>{
  await setup(page);
  await page.goto('/catalog?t=HMKB&f=RAT');
  const sector=page.locator('.terminal-sector-metrics');
  await expect(sector.locator('.term-info-btn')).toHaveText(['!','!']);
  await expect(sector).not.toContainText('Net interest income relative');
  await expect(sector).toContainText('INPUTS_MISSING');
  await sector.locator('.term-info-btn').first().click();
  await expect(page.getByRole('tooltip')).toContainText('Net interest income relative to average earning assets.');
  await page.keyboard.press('Escape');
  const [download]=await Promise.all([page.waitForEvent('download'),sector.getByRole('button',{name:'CSV',exact:true}).click()]);
  const csv=readFileSync(await download.path(),'utf8');
  expect(csv).toContain('NIM');
  expect(csv).not.toContain('!');
  await page.goto('/catalog?t=HMKB&f=SUM');
  const terminal=page.getByTestId('financial-columns');
  await terminal.getByRole('tab',{name:'Ratios',exact:true}).click();
  const rows=terminal.locator('.fc-table tbody tr[data-metric]');
  expect(await rows.count()).toBeGreaterThan(0);
  await expect(terminal.locator('.fc-table .term-info-btn')).toHaveCount(await rows.count());
});

test.describe('touch explanations',()=>{
  test.use({hasTouch:true,viewport:{width:390,height:844}});
  test('a tap toggles the explanation and a marker near the top keeps all text on screen',async({page})=>{
    await setup(page,'ru');
    await page.goto('/company/HMKB?tab=financials');
    await page.getByRole('button',{name:'Коэффициенты',exact:true}).click();
    await page.getByRole('button',{name:'Таблица',exact:true}).click();
    const marker=page.locator('.company-financials .term-info-btn').first(), tip=page.getByRole('tooltip');
    await marker.evaluate(el=>{el.scrollIntoView({block:'start'});window.scrollBy(0,-120);});
    await marker.tap();
    await expect(tip).toBeVisible();
    await expect(tip).toContainText('ROE');
    const box=await tip.boundingBox();
    expect(box.y).toBeGreaterThanOrEqual(0);expect(box.y+box.height).toBeLessThanOrEqual(844);
    await marker.tap();
    await expect(tip).toHaveCount(0);
  });
});
