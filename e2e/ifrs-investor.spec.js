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
  await page.goto('/company/HMKB?tab=financials');
  await page.getByRole('button',{name:'МСФО',exact:true}).click();
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

test('catalog and workspace panels use the same IFRS investor',async({page})=>{
  await setup(page);
  await page.goto('/catalog?t=HMKB&f=BS&form=MSFO');
  const standard=page.getByRole('group',{name:'Accounting standard'});
  await standard.getByRole('button',{name:'MSFO',exact:true}).click();
  const ui=page.getByTestId('ifrs-investor');
  await expect(ui.getByRole('tab',{name:'BS Balance',exact:true})).toHaveAttribute('aria-selected','true');
  await page.getByRole('button',{name:'PNL · Panels',exact:true}).click();
  await page.locator('.terminal-work-panel').getByLabel(/^Standard/).selectOption('MSFO');
  await expect(page.locator('.terminal-work-panel').getByTestId('ifrs-investor')).toBeVisible();
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
