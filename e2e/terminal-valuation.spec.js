import { test, expect } from '@playwright/test';

const parameters = {key_rate:14,default_spread:3.06,equity_premium:8.89,growth:9.8};
function valuation(ticker='HMKB', standard='NSBU') {
  const band = (value,low,high) => ({value,low,high,reason:null,unit:'UZS/share'});
  return {ok:true,ticker,period:'2025',standard,scope:'separate',parameters,required_return:19.83,current_price:97.44,market_date:'2026-10-15',
    configuration:{values:parameters,as_of:'2026-10-15',version:'reviewed-v2',reference_only:false},
    inputs:{roe:25.43,equity:6704709904000,net_profit:1704969118000,market_cap:12655218894000,dividend:null},
    summary:{value:80,low:70,high:110,price_to_value_pct:121.8,method_count:3,wide_spread:false},
    models:{
      peers_pb:{per_share:band(70,60,90),peer_count:5,multiple:1.36},
      peers_pe:{per_share:band(110,90,130),peer_count:4,multiple:8.38},
      justified_pb:{per_share:band(80,72,89),value:1.55},
      gordon:{per_share:{...band(null,null,null),reason:'RECENT_DIVIDEND_UNAVAILABLE'}},
    }};
}

async function setup(page, {admin=true, fail=false}={}) {
  await page.addInitScript(() => {
    localStorage.setItem('uz_stock_analyzer_token','admin-token');
    localStorage.setItem('uz_stock_analyzer_language','en');
    localStorage.setItem('uz_stock_analyzer_theme','dark');
  });
  const requests=[];
  const companies=[{ticker:'HMKB',company_name:'Hamkorbank',sector:'finance',nsbu_count:45,msfo_count:1,total_count:46},{ticker:'AGBA',company_name:'Agrobank',sector:'finance',total_count:42}];
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url()), path=url.pathname;
    const json=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
    if(path==='/api/auth/me')return json({user:{id:1,is_admin:admin,email:'test@example.com'}});
    if(path==='/api/catalog/companies')return json({ok:true,companies});
    if(path.startsWith('/api/catalog/index/'))return json({ok:true,company_name:companies.find(c=>path.endsWith(c.ticker))?.company_name,availability:{NSBU:{annual:[{year:2025,quarter:0}],quarter:[]}}});
    if(path.startsWith('/api/admin/terminal/valuation/')) {
      requests.push(url);
      if(fail)return route.fulfill({status:503,body:'{}'});
      return json(valuation(path.split('/').at(-1),url.searchParams.get('form')));
    }
    if(path==='/api/admin/terminal/templates')return json({ok:true,valuation:{values:parameters,as_of:'2026-10-15',version:'v2'}});
    return json({ok:true,items:[],rows:[],companies:[],snapshot:{},quarters:{rows:[]},growth:[],companies_synced:2,total_reports:88});
  });
  await page.goto('/catalog?t=HMKB&f=FV&std=NSBU');
  return requests;
}

test('FV opens the automatic per-share dashboard and exports its calculation table',async({page},testInfo)=>{
  await page.setViewportSize({width:1440,height:1000});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  const requests=await setup(page);
  const fv=page.locator('.terminal-valuation');
  await expect(fv.locator('.terminal-fv-kpis > div')).toHaveCount(6);
  await expect(fv).toContainText('97.44');
  await expect(fv).toContainText('121.8%');
  await expect(fv.getByRole('img',{name:'Valuation methods and ranges'})).toBeVisible();
  await expect(fv.getByText('No recent ordinary dividend',{exact:true})).toBeVisible();
  await expect(fv.getByRole('spinbutton')).toHaveCount(0);
  await expect(fv.getByRole('button',{name:'Calculate',exact:true})).toHaveCount(0);
  expect(requests[0].searchParams.has('key_rate')).toBe(false);
  const csvButton=fv.getByRole('button',{name:'CSV',exact:true});
  await csvButton.hover();
  // The shared opaque hover overlay previously painted over this text node.
  await expect.poll(()=>csvButton.evaluate(el=>getComputedStyle(el,'::before').content)).toBe('none');
  const download=page.waitForEvent('download');
  await fv.getByRole('button',{name:'CSV',exact:true}).click();
  const {readFile}=await import('node:fs/promises');
  const csv=await readFile(await (await download).path(),'utf8');
  expect(csv).toContain('UZS/share');
  expect(csv).toContain('No recent ordinary dividend');
  await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
  await page.screenshot({path:testInfo.outputPath('fv-desktop.png'),fullPage:true,animations:'disabled'});
  const tabs=page.locator('.terminal-tabs');
  expect(await tabs.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
  await page.screenshot({path:testInfo.outputPath('fv-mobile.png'),fullPage:true,animations:'disabled'});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.locator('.theme-toggle').click();
  await expect(page.locator('body')).toHaveAttribute('data-theme','light');
  await page.screenshot({path:testInfo.outputPath('fv-mobile-light.png'),fullPage:true,animations:'disabled'});
  await page.getByRole('combobox',{name:'Terminal command line'}).fill('AGBA MSFO FV');
  await page.getByRole('combobox',{name:'Terminal command line'}).press('Enter');
  await expect(fv.locator('.terminal-context')).toContainText('AGBA · 2025 · NSBU');
  expect(requests.at(-1).searchParams.get('form')).toBe('NSBU');
  expect(errors).toEqual([]);
  const standards=page.getByRole('group',{name:'Accounting standard',exact:true});
  await standards.getByRole('button',{name:'NSBU',exact:true}).click();
  await expect(fv.locator('.terminal-context')).toContainText('AGBA · 2025 · NSBU');
});

test('FV explains load errors and retries without leaving a stale valuation',async({page})=>{
  await setup(page,{fail:true});
  const fv=page.locator('.terminal-valuation');
  await expect(fv.getByRole('alert')).toBeVisible();
  await expect(fv.locator('.terminal-fv-kpis')).toHaveCount(0);
  await page.route('**/api/admin/terminal/valuation/**',r=>r.fulfill({contentType:'application/json',body:JSON.stringify(valuation())}));
  await fv.getByRole('button',{name:'Retry',exact:true}).click();
  await expect(fv.locator('.terminal-fv-kpis > div')).toHaveCount(6);
  await expect(fv.getByRole('alert')).toHaveCount(0);
});

test('a non-admin cannot open a catalog valuation bookmark',async({page})=>{
  const requests=await setup(page,{admin:false});
  await expect(page.getByRole('heading',{name:'Administrators only',exact:true})).toBeVisible();
  await expect(page.locator('.terminal-valuation')).toHaveCount(0);
  expect(requests).toHaveLength(0);
});

test('admin EQS filters price-to-valuation using the same protected model context',async({page})=>{
  await setup(page);
  await page.route('**/api/terminal/screener?**',r=>r.fulfill({json:{ok:true,rows:[{ticker:'HMKB',name:'Hamkorbank',kind:'bank',period:'2025',standard:'NSBU',scope:'separate'},{ticker:'AGBA',name:'Agrobank',kind:'bank',period:'2025',standard:'NSBU',scope:'separate'}],years:['2025']}}));
  let authorised=false;
  await page.route('**/api/admin/terminal/valuations?**',r=>{
    authorised=r.request().headers().authorization==='Bearer admin-token';
    return r.fulfill({json:{ok:true,configuration:{as_of:'2026-10-15',version:'reference-v1',reference_only:true},rows:[{ticker:'HMKB',period:'2025',standard:'NSBU',scope:'separate',price_to_value_pct:121.8},{ticker:'AGBA',period:'2025',standard:'NSBU',scope:'separate',price_to_value_pct:80}]}});
  });
  await page.getByRole('combobox',{name:'Terminal command line'}).fill('EQS');
  await page.getByRole('combobox',{name:'Terminal command line'}).press('Enter');
  await expect(page.locator('.terminal-screener')).toContainText('121.8');
  await expect(page.locator('.terminal-valuation-basis')).toContainText('2026-10-15');
  await expect(page.locator('.terminal-valuation-basis')).toContainText('Dated reference assumptions');
  await page.getByLabel('Price / valuation ≤, %').fill('100');
  await expect(page.locator('.terminal-screener tbody tr')).toHaveCount(1);
  await expect(page.locator('.terminal-screener tbody tr')).toContainText('AGBA');
  expect(authorised).toBe(true);
  await page.getByRole('combobox',{name:'Year',exact:true}).selectOption('2025');
  await expect(page.locator('.terminal-screener tbody tr')).toHaveCount(2);
  await expect(page.getByLabel('Price / valuation ≤, %')).toBeDisabled();
});

test('an administrator can use FV in an independent saved panel',async({page})=>{
  await setup(page);
  await page.getByRole('combobox',{name:'Terminal command line'}).fill('PNL');
  await page.getByRole('combobox',{name:'Terminal command line'}).press('Enter');
  await page.locator('.terminal-work-panel').getByRole('combobox',{name:'Function',exact:true}).selectOption('FV');
  await expect(page.locator('.terminal-work-panel .terminal-fv-kpis > div')).toHaveCount(6);
});
