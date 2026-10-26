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
test('guest can save, reload, apply and delete a browser screener',async({page})=>{
 await setup(page); await page.addInitScript(()=>localStorage.removeItem('uz_stock_analyzer_token')); await page.goto('/market');
 await expect(page.locator('.market-table tbody tr')).toHaveCount(2);
 const panel=page.getByTestId('saved-screeners');
 await panel.getByRole('button',{name:'Растущие',exact:true}).click();
 await expect(page.locator('.market-table tbody tr')).toHaveCount(1);
 await panel.locator('summary').click();
 await panel.getByLabel('Название фильтра').fill('Рост');
 await panel.getByRole('button',{name:'Сохранить фильтр',exact:true}).click();
 await page.reload();
 await page.getByTestId('saved-screeners').locator('summary').click();
 await page.getByTestId('saved-screeners').getByLabel('Сохранённые скринеры').selectOption({label:'Рост'});
 await page.getByTestId('saved-screeners').getByRole('button',{name:'Применить',exact:true}).click();
 await expect(page.locator('.market-table tbody tr')).toHaveCount(1);
 await page.getByTestId('saved-screeners').getByRole('button',{name:'Удалить',exact:true}).click();
 await expect(page.getByTestId('saved-screeners').getByRole('option',{name:'Рост',exact:true})).toHaveCount(0);
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

test('home shows upcoming published events and the signed-in watchlist',async({page})=>{
 await setup(page);
 await page.route('**/api/news/calendar/events?**', route=>route.fulfill({json:{ok:true,items:[{id:'meeting:20828',type:'meeting',organization:'Hamkorbank',ticker:'HMKB',date:'2026-11-01',title:'Собрание акционеров'}]}}));
 await page.goto('/');
 await expect(page.getByTestId('landing-updates')).toContainText('Hamkorbank');
 await expect(page.getByTestId('landing-updates')).toContainText('AGBA');
 await page.getByTestId('landing-updates').getByRole('button',{name:'Календарь событий',exact:true}).click();
 await expect(page).toHaveURL(/news\?tab=calendar/);
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
