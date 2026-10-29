import { test, expect } from '@playwright/test';
const stocks=[{ticker:'AGBA',type:'stock',name:'AGBA issuer',last_price:1000,close_price:900,volume:1e6,quantity:1000,last_trade_date:'2026-10-26'},
 {ticker:'KVTS',type:'stock',name:'KVTS issuer',last_price:3000,close_price:3100,volume:3e6,quantity:1000,last_trade_date:'2026-10-26'}];
async function setup(page){
 await page.addInitScript(()=>{sessionStorage.setItem('uz_sponsor_seen','1');localStorage.setItem('uz_stock_analyzer_token','test');});
 await page.route('**/api/**',route=>{
  const path=new URL(route.request().url()).pathname;
  const user={id:1,full_name:'Reader',email:'reader@example.test'};
  return route.fulfill({json:path==='/api/market/stocks'?{stocks}:path==='/api/companies'?{companies:stocks.map(s=>({ticker:s.ticker,company_name:s.name}))}
   :path==='/api/securities'?{ok:true,securities:Object.fromEntries(stocks.map(s=>[s.ticker,{...s,security_type:'stock'}]))}
   :path==='/api/auth/me'?{user}:path==='/api/profile'?{user,favorites:stocks.map(s=>({ticker:s.ticker,company_name:s.name})),notes:[],preferences:{},security:{}}
   :{ok:true,items:[],stats:{},financials:{}}});
 });
}
for(const width of [390,1440]) test(`market omits screener and price-direction controls at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});
 await setup(page); await page.addInitScript(()=>localStorage.removeItem('uz_stock_analyzer_token')); await page.goto('/market');
 await expect(page.locator('.market-table tbody tr')).toHaveCount(2);
 if(width===390) await page.getByText('Фильтры и инструменты',{exact:true}).click();
 await expect(page.getByTestId('saved-screeners')).toHaveCount(0);
 await expect(page.getByText('Сохранённые скринеры',{exact:false})).toHaveCount(0);
 await expect(page.getByRole('group',{name:'Динамика цены'})).toHaveCount(0);
 await expect(page.getByRole('button',{name:/^(Растущие|Снижающиеся)$/})).toHaveCount(0);
 await expect(page.locator('.market-table tbody tr')).toHaveCount(2);
});
test('profile watchlist supports search and CSV export',async({page})=>{
 await setup(page);await page.goto('/profile');
 await page.getByLabel('Поиск в избранном').fill('KVTS');
 await expect(page.locator('.pf-watch-item')).toHaveCount(1);
 const download=page.waitForEvent('download');
 await page.getByRole('button',{name:'Экспорт избранного CSV',exact:true}).click();
 const body=(await(await(await download).createReadStream()).toArray()).join('');
 expect(body).toContain('KVTS');expect(body).not.toContain('AGBA');
});

test('editorial news search narrows the current category and has an empty state',async({page})=>{
 await setup(page);
 await page.route('**/api/news/feed?**',route=>route.fulfill({json:{ok:true,items:[
  {id:1,title:'Hamkorbank опубликовал отчёт',title_ru:'Hamkorbank опубликовал отчёт',source:'OpenInfo',published_at:'2026-10-26',tickers:['HMKB']},
  {id:2,title:'Обзор экономики',title_ru:'Обзор экономики',source:'Spot',published_at:'2026-10-25',tickers:[]}
 ]}}));
 await page.goto('/news');
 await page.getByLabel('Поиск новостей').fill('HMKB');
 await expect(page.locator('.newsdesk-board')).toContainText('Hamkorbank');
 await expect(page.locator('.newsdesk-board')).not.toContainText('Обзор экономики');
 await page.getByLabel('Поиск новостей').fill('no-match');
 await expect(page.getByText('По вашему запросу новостей нет.')).toBeVisible();
});
