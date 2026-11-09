import {test, expect} from '@playwright/test';
import {row} from './helpers/market-board.js';

const technicalKeys = ['sma20','sma50','sma200','high52w','low52w','rsi14','dayChange','changeOpen','gap','dayVolume'];
const technical = {
  HMKB: {as_of:'2026-11-06', observations:240, values:{sma20:5, sma50:8, sma200:12, high52w:-10, low52w:30, rsi14:65, dayChange:2, changeOpen:1, gap:0.99, dayVolume:12000, atr14:3.5, beta:null}, missing:{beta:'benchmark_unavailable'}},
  SQBNP: {as_of:'2026-11-05', observations:20, values:{sma20:-2, sma50:null, sma200:null, high52w:null, low52w:null, rsi14:25, dayChange:-1, changeOpen:0, gap:-1, dayVolume:0, atr14:null, beta:null}, missing:{sma50:'insufficient_history', sma200:'insufficient_history', high52w:'insufficient_history',low52w:'insufficient_history',atr14:'missing_ohlc', beta:'benchmark_unavailable'}},
};
async function setup(page, {role='administrator', saved=[], fail=false, authenticate}={}) {
  const requests=[];
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  const stocks=[row('HMKB',118,116,12000),row('SQBNP',89,90,0)];
  await page.route('**/api/**',route=>{
    const path=new URL(route.request().url()).pathname;
    const data=path==='/api/market/stocks'?{stocks}
      :path==='/api/securities'?{securities:Object.fromEntries(stocks.map(s=>[s.ticker,s]))}
      :path==='/api/companies'?{companies:stocks.map(s=>({...s,company_name:s.name}))}
      :{items:[],stats:{},financials:{}};
    return route.fulfill({json:{ok:true,...data}});
  });
  await page.addInitScript(({role,saved})=>{
    if(role) localStorage.setItem('uz_stock_analyzer_token','technical-session');
    if(!localStorage.getItem('uz_market_cols_v3')) localStorage.setItem('uz_market_cols_v3',JSON.stringify(saved));
    sessionStorage.setItem('uz_sponsor_seen','1');
    localStorage.setItem('uz_track_internal','1');
  },{role,saved});
  await page.route('**/api/auth/me',async route=>{
    await authenticate?.();
    return route.fulfill({status:role?200:401,json:{user:role?{id:1,email:`${role}@example.test`,admin_role:role,is_admin:role==='administrator'}:null}});
  });
  await page.route('**/api/market/technical',route=>{
    requests.push(route.request().headers().authorization);
    return route.fulfill({status:fail?503:200,json:fail?{detail:'unavailable'}:{ok:true,as_of:'2026-11-06',technical}});
  });
  await page.goto('/market');
  await expect(page.locator('.market-table tbody tr')).toHaveCount(2);
  if(role && !authenticate) await expect(page.getByRole('button',{name:`Аккаунт и настройки: ${role}@example.test`})).toBeVisible();
  return {requests,errors};
}
async function settings(page) {
  const disclosure=page.locator('.market-secondary > summary');
  if(await disclosure.isVisible()) await disclosure.click();
  await page.locator('.market-cols-btn').click();
  await page.getByRole('button',{name:/^Technical/}).click();
  return page.getByTestId('technical-settings');
}
const cell=(page,ticker,key)=>page.locator('.market-table tbody tr').filter({hasText:ticker}).locator(`[data-technical="${key}"]`);

for(const role of [null,'reader','analyst']) test(`${role||'guest'} cannot use saved Technical columns or filters`,async({page})=>{
  const {requests}=await setup(page,{role,saved:technicalKeys});
  await page.locator('.market-cols-btn').click();
  await expect(page.getByRole('button',{name:/^Technical/})).toHaveCount(0);
  await expect(page.locator('[data-technical]')).toHaveCount(0);
  expect(requests).toEqual([]);
});

test('admin Technical columns support exact values, numeric filtering, sorting and CSV',async({page},testInfo)=>{
  const {requests,errors}=await setup(page);
  expect(requests).toEqual([]);
  const panel=await settings(page);
  await panel.getByRole('button',{name:'Показать Technical',exact:true}).click();
  await expect(panel.getByRole('checkbox',{name:'ATR (14), UZS',exact:true})).not.toBeChecked();
  await expect(panel.getByRole('checkbox',{name:'Beta',exact:true})).not.toBeChecked();
  await panel.getByRole('checkbox',{name:'ATR (14), UZS',exact:true}).check();
  await panel.getByRole('checkbox',{name:'Beta',exact:true}).check();
  await page.keyboard.press('Escape');
  await expect(cell(page,'HMKB','sma20')).toContainText('5');
  await expect(cell(page,'SQBNP','sma50')).toHaveText('—');
  await expect(cell(page,'SQBNP','dayVolume')).toHaveText('0');
  await expect(cell(page,'HMKB','beta')).toHaveAttribute('title',/индекс/);
  await expect(cell(page,'HMKB','atr14')).toContainText('3,5');
  await page.locator('.market-table thead th[data-sort-key="rsi14"]').click();
  await expect(page.locator('.market-table tbody tr').first()).toContainText('HMKB');
  await page.locator('.market-table thead th[data-sort-key="rsi14"]').click();
  await expect(page.locator('.market-table tbody tr').first()).toContainText('SQBNP');
  await page.locator('.market-cols-btn').click();
  await panel.getByLabel('RSI (14): от', {exact:true}).fill('30');
  await page.keyboard.press('Escape');
  await expect(page.locator('.market-table tbody tr')).toHaveCount(1);
  await expect(page.locator('.market-table tbody tr')).toContainText('HMKB');
  await expect(page.getByTestId('technical-status')).toContainText('2026-11-06');
  const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:/Экспорт CSV/}).click()]);
  const csv=(await(await download.createReadStream()).toArray()).join('');
  expect(csv).toContain('SMA20');
  expect(csv).toContain('RSI (14)');
  expect(csv).toContain('2026-11-06');
  expect(csv).not.toContain('SQBNP;');
  expect(requests).toEqual(['Bearer technical-session']);
  await page.screenshot({path:testInfo.outputPath('technical-table.png')});
  expect(errors).toEqual([]);
});

for(const width of [390,1440]) test(`Technical settings fit ${width}px and keep optional columns after reload`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:900});
  await setup(page);
  const panel=await settings(page);
  await panel.getByRole('button',{name:'Показать Technical',exact:true}).click();
  await panel.getByRole('checkbox',{name:'ATR (14), UZS',exact:true}).check();
  await panel.getByLabel('SMA20, %: от',{exact:true}).fill('-5');
  await panel.getByLabel('SMA20, %: до',{exact:true}).fill('10');
  await panel.getByRole('button',{name:'Показать Technical',exact:true}).scrollIntoViewIfNeeded();
  await page.locator('.market-cols-dropdown').screenshot({path:testInfo.outputPath(`technical-settings-${width}.png`)});
  const box=await panel.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  if(width===1440) expect(box.width).toBeGreaterThanOrEqual(380);
  expect(box.x+box.width).toBeLessThanOrEqual(width);
  expect(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
  await page.keyboard.press('Escape');
  // Keep the selected columns across a genuine reload without resetting storage.
  expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('uz_market_cols_v3')))).toContain('atr14');
  await page.evaluate(()=>localStorage.setItem('uz_market_col_order_v2',JSON.stringify(['last','atr14','sma20'])));
  await page.reload();
  await expect(cell(page,'HMKB','atr14')).toBeVisible();
  await expect(cell(page,'HMKB','beta')).toHaveCount(0);
  expect((await page.locator('.market-table thead th').evaluateAll(nodes=>nodes.map(n=>n.dataset.sortKey))).slice(2,5)).toEqual(['last','atr14','sma20']);
});

test('failed Technical request is explicit and retryable',async({page})=>{
  await setup(page,{fail:true});
  const panel=await settings(page);
  await panel.getByRole('button',{name:'Показать Technical',exact:true}).click();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('technical-status')).toContainText('Не удалось');
  await expect(cell(page,'HMKB','sma20')).toHaveText('—');
  await page.route('**/api/market/technical',route=>route.fulfill({json:{ok:true,as_of:'2026-11-06',technical}}));
  await page.getByRole('button',{name:'Повторить Technical',exact:true}).click();
  await expect(cell(page,'HMKB','sma20')).toContainText('5');
});

test('Technical waits for authenticated admin and is removed on logout',async({page})=>{
  let release; const waiting=new Promise(resolve=>{release=resolve;});
  const {requests}=await setup(page,{saved:['sma20'],authenticate:()=>waiting});
  expect(requests).toEqual([]);
  await expect(page.locator('[data-technical]')).toHaveCount(0);
  release();
  await expect(cell(page,'HMKB','sma20')).toContainText('5');
  await page.getByRole('button',{name:'Аккаунт и настройки: administrator@example.test'}).click();
  await page.getByRole('button',{name:'Выйти',exact:true}).click();
  await expect(page.locator('[data-technical]')).toHaveCount(0);
  await expect(page.getByTestId('technical-status')).toHaveCount(0);
  expect(requests).toHaveLength(1);
});
