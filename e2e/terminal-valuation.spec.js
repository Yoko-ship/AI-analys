import { toggleTheme } from './language-control.js';
import { test, expect } from '@playwright/test';
import {expectFullWidth} from './helpers/full-width.js';

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

async function setup(page, {admin=true, fail=false, theme='dark', referenceOnly=false, lang='en', valuationResult=null, beforeNavigate}={}) {
  await page.addInitScript(({theme,lang}) => {
    localStorage.setItem('uz_stock_analyzer_token','admin-token');
    localStorage.setItem('uz_stock_analyzer_language',lang);
    localStorage.setItem('uz_stock_analyzer_theme',theme);
  }, {theme,lang});
  const requests=[];
  const companies=[{ticker:'HMKB',company_name:'Hamkorbank',sector:'finance',nsbu_count:45,msfo_count:1,total_count:46},{ticker:'AGBA',company_name:'Agrobank',sector:'finance',total_count:42}];
  if(valuationResult)companies.push({ticker:valuationResult.ticker,company_name:valuationResult.ticker,sector:'industry',nsbu_count:7,total_count:7});
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url()), path=url.pathname;
    const json=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
    if(path==='/api/auth/me')return json({user:{id:1,is_admin:admin,email:'test@example.com'}});
    if(path==='/api/catalog/companies')return json({ok:true,companies});
    if(path.startsWith('/api/catalog/index/'))return json({ok:true,company_name:companies.find(c=>path.endsWith(c.ticker))?.company_name,availability:{NSBU:{annual:[{year:2025,quarter:0}],quarter:[]}}});
    if(path.startsWith('/api/admin/terminal/valuation/')) {
      requests.push(url);
      if(fail)return route.fulfill({status:503,body:'{}'});
      const result=valuationResult||valuation(path.split('/').at(-1),url.searchParams.get('form'));
      if(referenceOnly)result.configuration={...result.configuration,version:'tz-reference-2026-10-15',reference_only:true};
      return json(result);
    }
    if(path==='/api/admin/terminal/templates')return json({ok:true,valuation:{values:parameters,as_of:'2026-10-15',version:'v2'}});
    return json({ok:true,items:[],rows:[],companies:[],snapshot:{},quarters:{rows:[]},growth:[],companies_synced:2,total_reports:88});
  });
  await beforeNavigate?.();
  await page.goto(`/catalog?t=${valuationResult?.ticker||'HMKB'}&f=FV&std=NSBU`);
  return requests;
}

test('BIOK FV and RV reuse loaded data and request only the peer universe', async ({page}) => {
  const peers=[];
  const requests=await setup(page,{valuationResult:valuation('BIOK'),beforeNavigate:() =>
    page.route('**/api/terminal/screener?*',route=>{
      peers.push(new URL(route.request().url()));
      return route.fulfill({json:{ok:true,years:['2025','2024'],rows:[{ticker:'BIOK',name:'BIOK',kind:'industry',standard:'NSBU',scope:'separate',period:'2025'}]}});
    })});
  const tab=code=>page.locator('.terminal-tab').filter({has:page.locator('strong',{hasText:new RegExp(`^${code}$`)})});
  await expect(page.locator('.terminal-fv-kpis')).toBeVisible();
  for(const code of ['RV','FV','RV','FV']) {
    await tab(code).click();
    await expect(page.locator(code==='FV'?'.terminal-fv-kpis':'.terminal-peers-screen .terminal-peer-table')).toBeVisible();
  }
  expect(requests).toHaveLength(1);
  expect(peers).toHaveLength(1);
  expect(peers[0].searchParams.get('peer_ticker')).toBe('BIOK');
  await tab('RV').click();
  await page.getByRole('combobox',{name:'Reporting year',exact:true}).selectOption('2024');
  await expect.poll(()=>peers.length).toBe(2);
  expect(peers[1].searchParams.get('peer_ticker')).toBe('BIOK');
  expect(peers[1].searchParams.get('year')).toBe('2024');
});

test('BIOK FV refreshes after catalog sync instead of keeping an old valuation', async ({page}) => {
  const result=valuation('BIOK');
  const requests=await setup(page,{valuationResult:result});
  await expect(page.locator('.terminal-fv-kpis')).toContainText('97.44');
  result.current_price=14400;
  await page.locator('.catalog-sync-all').click();
  await expect.poll(()=>requests.length).toBe(2);
  await expect(page.locator('.terminal-fv-kpis')).toContainText('14,400');
});

for(const referenceOnly of [false,true]) test(`FV opens without the assumptions banner and exports its calculation table (${referenceOnly?'reference':'reviewed'})`,async({page},testInfo)=>{
  await page.setViewportSize({width:1440,height:1000});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  const requests=await setup(page,{referenceOnly});
  const fv=page.locator('.terminal-valuation');
  await expect(fv.locator('.terminal-fv-kpis > div')).toHaveCount(6);
  await expect(fv.locator('.terminal-fv-assumptions')).toHaveCount(0);
  await expect(fv).not.toContainText('tz-reference-2026-10-15');
  await expect(fv).not.toContainText('Model calculation, not a recommendation.');
  await expect(fv.locator('.terminal-fv-kpis')).toContainText('19.83%');
  await expect(fv.locator('.terminal-fv-kpis')).toContainText('9.8%');
  await expect(fv).toContainText('97.44');
  await expect(fv).toContainText('121.8%');
  await expect(fv.getByRole('img',{name:'Valuation methods and ranges'})).toBeVisible();
  const [chartCard,calculationCard]=await fv.locator('.terminal-fv-card').evaluateAll(cards=>cards.map(card=>card.getBoundingClientRect().toJSON()));
  expect(calculationCard.x).toBeGreaterThan(chartCard.x+chartCard.width);
  expect(Math.abs(calculationCard.y-chartCard.y)).toBeLessThanOrEqual(1);
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
  await expect(page.locator('.terminal-tab.active span')).toBeVisible();
  await expect.poll(async () => (await fv.locator('.terminal-fv-kpis').boundingBox()).y).toBeLessThan(760);
  expect(await fv.locator('.terminal-fv-kpis dt').first().evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(12);
  await page.screenshot({path:testInfo.outputPath('fv-mobile.png'),fullPage:true,animations:'disabled'});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await toggleTheme(page);
  await expect(page.locator('body')).toHaveAttribute('data-theme','light');
  await page.screenshot({path:testInfo.outputPath('fv-mobile-light.png'),fullPage:true,animations:'disabled'});
  await page.getByRole('combobox',{name:'Company search'}).fill('AGBA MSFO FV');
  await page.getByRole('combobox',{name:'Company search'}).press('Enter');
  await expect(fv.locator('.terminal-context')).toContainText('AGBA · 2025 · NSBU');
  expect(requests.at(-1).searchParams.get('form')).toBe('NSBU');
  expect(errors).toEqual([]);
  const standards=page.getByRole('group',{name:'Accounting standard',exact:true});
  await standards.getByRole('button',{name:'NSBU',exact:true}).click();
  await expect(fv.locator('.terminal-context')).toContainText('AGBA · 2025 · NSBU');
});

for(const theme of ['light','dark']) test(`FV details keep wide valuation ranges readable on desktop and mobile (${theme})`,async({page},testInfo)=>{
  const result=valuation('BIOK');
  // Values from the reported screen: two usable methods and a very wide P/E range.
  result.current_price=14400;
  result.summary={value:46680.06,low:39368.08,high:53992.04,price_to_value_pct:30.85,method_count:2,wide_spread:false};
  Object.assign(result.models.peers_pb,{multiple:1.9,peer_count:24,per_share:{value:39368.08,low:19675.09,high:92461.75}});
  Object.assign(result.models.peers_pe,{multiple:23.3,peer_count:23,per_share:{value:53992.04,low:26618.59,high:265509.73}});
  result.models.justified_pb.per_share={value:null,reason:'NOT_A_BANK'};
  await page.setViewportSize({width:2260,height:1000});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await setup(page,{theme,lang:'ru',valuationResult:result});
  const detail=page.locator('.terminal-fv-detail');
  await expect(detail).toBeVisible();
  await expectFullWidth(detail,'.terminal-valuation');
  const chart=detail.getByRole('region',{name:'Методы и диапазоны',exact:true});
  const calculation=detail.getByRole('region',{name:'Как посчитано',exact:true});
  const csv=calculation.getByRole('button',{name:'CSV',exact:true});
  // Read both positions in one frame while the surrounding page settles.
  const [chartBox,tableBox]=await detail.locator('.terminal-fv-card').evaluateAll(cards=>cards.map(card=>card.getBoundingClientRect().toJSON()));
  expect(Math.abs(chartBox.y-tableBox.y)).toBeLessThanOrEqual(1);
  expect(tableBox.x).toBeGreaterThan(chartBox.x+chartBox.width);
  expect(chartBox.height).toBeLessThan(450);
  expect((await csv.boundingBox()).height).toBeGreaterThanOrEqual(44);
  const heading=await calculation.getByRole('heading').boundingBox(),button=await csv.boundingBox();
  expect(Math.abs(heading.y+heading.height/2-button.y-button.height/2)).toBeLessThan(16);
  for(const row of await calculation.locator('tbody tr').all())expect((await row.boundingBox()).height).toBeGreaterThanOrEqual(60);
  await expect(chart).toContainText('39 368,08');
  await expect(chart).toContainText('265 509,73');
  await expect(calculation).toContainText('Метод применяется только к банкам');
  await csv.focus();
  expect(await csv.evaluate(el=>getComputedStyle(el).outlineStyle)).not.toBe('none');
  const download=page.waitForEvent('download');await csv.press('Enter');
  const {readFile}=await import('node:fs/promises');
  const content=await readFile(await (await download).path(),'utf8');
  expect(content.replaceAll('\u00a0',' ')).toContain('39 368,08');
  expect(content).toContain('Метод применяется только к банкам');
  for(const width of [2260,768,390]) {
    await page.setViewportSize({width,height:1000});
    await expectFullWidth(detail,'.terminal-valuation');
    const [a,b]=await detail.locator('.terminal-fv-card').evaluateAll(cards=>cards.map(card=>card.getBoundingClientRect().toJSON()));
    if(width<1000)expect(b.y).toBeGreaterThanOrEqual(a.y+a.height);
    for(const text of await detail.locator('h3,.terminal-fv-method-name,.terminal-fv-estimate,tbody th,tbody td').all()) {
      const size=await text.evaluate(el=>parseFloat(getComputedStyle(el).fontSize));
      expect(size).toBeGreaterThanOrEqual(14);expect(size).toBeLessThanOrEqual(20);
      expect(await text.evaluate(el=>el.scrollWidth<=el.clientWidth+1),`${width}px: ${await text.textContent()}`).toBe(true);
    }
    const tracks=await chart.locator('.terminal-fv-track').all();
    expect(tracks).toHaveLength(2);
    for(const track of tracks) {
      const bounds=await track.boundingBox();
      for(const mark of await track.locator('.terminal-fv-band,.terminal-fv-dot,.terminal-fv-price-line').all()) {
        const box=await mark.boundingBox();
        expect(box.x).toBeGreaterThanOrEqual(bounds.x-1);
        expect(box.x+box.width).toBeLessThanOrEqual(bounds.x+bounds.width+1);
      }
    }
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
    await detail.screenshot({path:testInfo.outputPath(`valuation-details-${width}.png`),animations:'disabled'});
  }
  // A price above both ranges must still share their scale and remain in the plot.
  result.current_price=300000;
  await page.reload();
  await expect(chart.locator('.terminal-fv-price-label')).toContainText('300 000');
  const track=chart.locator('.terminal-fv-track').first();
  const price=await track.locator('.terminal-fv-price-line').boundingBox();
  const band=await track.locator('.terminal-fv-band').boundingBox();
  expect(price.x).toBeGreaterThan(band.x+band.width);
  for(const model of Object.values(result.models))model.per_share={value:null,reason:'MARKET_BASIS_UNAVAILABLE'};
  result.summary.method_count=0;
  await page.reload();
  await expect(chart).toContainText('Нет применимых методов');
  await expect(chart.locator('.terminal-fv-track')).toHaveCount(0);
  await expect(calculation.locator('tbody tr')).toHaveCount(4);
  expect(errors).toEqual([]);
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

for (const [theme, width] of [['light',1440],['dark',390]]) test(`admin EQS has aligned readable filters and preserves valuation context (${theme}, ${width}px)`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:1000});
  await setup(page,{theme});
  await page.route('**/api/terminal/screener?**',r=>r.fulfill({json:{ok:true,rows:[{ticker:'HMKB',name:'Hamkorbank',kind:'bank',period:'2025',standard:'NSBU',scope:'separate'},{ticker:'AGBA',name:'Agrobank',kind:'bank',period:'2025',standard:'NSBU',scope:'separate'}],years:['2025']}}));
  let authorised=false;
  await page.route('**/api/admin/terminal/valuations?**',r=>{
    authorised=r.request().headers().authorization==='Bearer admin-token';
    return r.fulfill({json:{ok:true,configuration:{as_of:'2026-10-15',version:'tz-reference-2026-10-15',reference_only:true},rows:[{ticker:'HMKB',period:'2025',standard:'NSBU',scope:'separate',price_to_value_pct:121.8},{ticker:'AGBA',period:'2025',standard:'NSBU',scope:'separate',price_to_value_pct:80}]}});
  });
  await page.getByRole('combobox',{name:'Company search'}).fill('EQS');
  await page.getByRole('combobox',{name:'Company search'}).press('Enter');
  await expect(page.locator('.terminal-screener')).toContainText('121.8');
  await expect(page.locator('.terminal-valuation-basis')).toContainText('2026-10-15');
  await expect(page.locator('.terminal-valuation-basis')).toContainText('Dated reference assumptions');
  const screen=page.locator('.terminal-market-screen');
  const fields=['Standard','Year','Search','Type'].map(name=>screen.getByRole(name==='Search'?'searchbox':'combobox',{name,exact:true}));
  const boxes=await Promise.all(fields.map(field=>field.boundingBox()));
  if(width>600) {
    expect(Math.max(...boxes.map(box=>box.y))-Math.min(...boxes.map(box=>box.y))).toBeLessThanOrEqual(1);
    expect(boxes[2].width).toBeGreaterThanOrEqual(240);
  }
  for(const field of fields) {
    expect((await field.boundingBox()).height).toBeGreaterThanOrEqual(43.99);
    expect(await field.evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(14);
    expect(await field.evaluate(el=>parseFloat(getComputedStyle(el.closest('label')).fontSize))).toBeGreaterThanOrEqual(12);
  }
  const basis=screen.locator('.terminal-valuation-basis');
  await expect(basis.locator('time')).toHaveText('2026-10-15');
  await expect(basis.locator('code')).toHaveText('tz-reference-2026-10-15');
  expect(await basis.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
  await fields[2].fill('Agrobank');
  await expect(screen.locator('.terminal-screener tbody tr')).toHaveCount(1);
  await fields[2].fill('');
  await expect(screen.locator('.terminal-screener tbody tr')).toHaveCount(2);
  await fields[2].focus();
  await expect(fields[2]).toBeFocused();
  expect(await fields[2].evaluate(el=>getComputedStyle(el).outlineStyle)).not.toBe('none');
  await screen.screenshot({path:testInfo.outputPath('screener-filter-layout.png')});
  const toolbar=await screen.getByRole('group',{name:'List filters',exact:true}).boundingBox();
  const note=await basis.boundingBox();
  await page.screenshot({path:testInfo.outputPath('screener-filter-detail.png'),animations:'disabled',clip:{
    x:toolbar.x,y:toolbar.y,width:toolbar.width,height:note.y+note.height-toolbar.y,
  }});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.getByLabel('Price / valuation ≤, %').fill('100');
  await expect(page.locator('.terminal-screener tbody tr')).toHaveCount(1);
  await expect(page.locator('.terminal-screener tbody tr')).toContainText('AGBA');
  expect(authorised).toBe(true);
  await page.getByRole('combobox',{name:'Year',exact:true}).selectOption('2025');
  await expect(page.locator('.terminal-screener tbody tr')).toHaveCount(2);
  await expect(page.getByLabel('Price / valuation ≤, %')).toBeDisabled();
  await page.locator('.terminal-market-nav').getByRole('button',{name:/^MON/}).click();
  const metric=screen.getByRole('combobox',{name:'Metric',exact:true});
  await metric.selectOption('cg5');
  await expect(metric).toHaveValue('cg5');
  expect((await metric.boundingBox()).height).toBeGreaterThanOrEqual(43.99);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('an administrator can use FV in an independent saved panel',async({page})=>{
  await setup(page);
  await page.getByRole('combobox',{name:'Company search'}).fill('PNL');
  await page.getByRole('combobox',{name:'Company search'}).press('Enter');
  await page.locator('.terminal-work-panel').getByRole('combobox',{name:'Function',exact:true}).selectOption('FV');
  await expect(page.locator('.terminal-work-panel .terminal-fv-kpis > div')).toHaveCount(6);
});
