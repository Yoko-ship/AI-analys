import {test,expect} from '@playwright/test';
async function setup(page){
 await page.addInitScript(()=>{localStorage.setItem('uz_stock_analyzer_language','en');localStorage.setItem('uz_stock_analyzer_theme','light');localStorage.setItem('uz_stock_analyzer_token','reference-test');sessionStorage.setItem('uz_sponsor_seen','1');});
 const user={id:19,full_name:'Investor',email:'investor@example.test'};
 const stocks=[{ticker:'HMKB',name:'Hamkorbank',type:'stock',last_price:55,close_price:50,volume:4000000,quantity:1000,trade_count:7,last_trade_date:'2026-10-26'}];
 await page.route('**/api/**',r=>{const path=new URL(r.request().url()).pathname;return r.fulfill({json:path==='/api/auth/me'?{user}:path==='/api/profile'?{user,preferences:{saved_screeners:[]},favorites:[{ticker:'HMKB',company_name:'Hamkorbank'}],notes:[],security:{}}:path==='/api/market/stocks'?{stocks}:path==='/api/companies'?{companies:stocks.map(s=>({...s,company_name:s.name}))}:path==='/api/securities'?{ok:true,securities:{HMKB:{...stocks[0],sector:'banks'}}}:path==='/api/currency/rates'?{ok:true,rates:[{ccy:'USD',rate:12500,nominal:1,diff:0},{ccy:'EUR',rate:14000,nominal:1,diff:0}]}:path==='/api/bank-fx'?{ok:true,banks:[{bank_code:'hamkorbank',bank_name:'Hamkorbank',rates:{USD:{BANK:{buy:12400,sell:12600}}}}],best:{USD:{BANK:{best_buy:{value:12400},best_sell:{value:12600}}}}}:path==='/api/portfolio'?{ok:true,items:[],transactions:[],count:0,priced_count:0,market_value:'0',cost_value:'0',valuation_complete:true}:path==='/api/news/feed'?{ok:true,items:[{id:'a',title:'Market update',title_en:'Market update',published_at:'2026-10-26T09:00:00Z',summary_en:'Disclosed market events.',tickers:['HMKB'],category:'market'}]}:{ok:true,items:[],stats:{},changes:{}}});});
}
for(const width of [1440,390]){
 test(`reference home groups market, watchlist, currencies and events at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:1000});await setup(page);await page.goto('/');
  const board=page.getByTestId('home-market-table'),aside=page.getByTestId('home-personal-sidebar');
  await expect(board).toBeVisible();await expect(aside).toBeVisible();
  await expect(page.getByTestId('home-focus-news')).toBeVisible();await expect(page.getByTestId('home-currency-card')).toContainText('USD');
  const a=await board.boundingBox(),b=await aside.boundingBox();expect(width>800?b.x>a.x+a.width-1:b.y>=a.y+a.height-1).toBeTruthy();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 });
 test(`reference profile has overview portfolio and quick actions at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:1000});await setup(page);await page.goto('/profile');
  await expect(page.getByTestId('profile-quick-actions')).toBeVisible();await expect(page.getByTestId('profile-portfolio-preview')).toBeVisible();
  await page.getByTestId('profile-quick-actions').getByRole('button',{name:'New note',exact:true}).click();await expect(page.getByRole('dialog')).toBeVisible();
 });
}
test('currency workspace includes actual bank summary and working official-rate converter',async({page})=>{
 await setup(page);await page.goto('/currency');await expect(page.getByTestId('currency-stats').locator('article')).toHaveCount(4);
 await expect(page.getByTestId('currency-bank-table')).toContainText('12,400');
 const converter=page.getByTestId('currency-converter');await converter.getByLabel('Amount', {exact:true}).fill('2');
 await converter.getByLabel('From currency').selectOption('EUR');await converter.getByLabel('To currency').selectOption('UZS');
 await expect(converter.getByTestId('converted-amount')).toContainText('28,000');
});
test('public issuer directory is searchable and opens real company routes',async({page})=>{
 await setup(page);await page.goto('/issuers');await page.getByRole('searchbox',{name:'Search issuers'}).fill('Hamkor');
 await page.getByRole('button',{name:/HMKB.*Hamkorbank/}).click();await expect(page).toHaveURL(/company\/HMKB/);
});
test('corporate detail shows extracted fields and the reason for its attention level',async({page})=>{
 await setup(page);await page.route('**/api/news/corporate-events?**',r=>r.fulfill({json:{ok:true,items:[{id:'license',story_id:'license',organization:'Issuer',title:{en:'Licence returned'},summary:{en:'Voluntary licence return'},stage:'disclosed',category:'risks',priority:1,confidence:'confirmed',priority_provisional:false,priority_explanation:{en:'The issuer reports voluntary licence return.'},facts:[{source_field:'type_activity',label:{en:'Licensed activity'},value:'Payment system',unit:'text'}],source_url:'https://openinfo.uz/ru/facts/23/1',published_at:'2026-10-26',documents:[],document_count:1}],categories:{risks:{en:'Risks'}},facts:{}}}));
 await page.goto('/news?tab=corporate');await page.getByRole('button',{name:/Documents & history/}).click();
 await expect(page.getByRole('dialog')).toContainText('Payment system');await expect(page.getByRole('dialog')).toContainText('voluntary licence return');
});
test('home map can switch to a table without losing its search',async({page})=>{
 await setup(page);await page.goto('/');const map=page.getByTestId('home-market-dashboard');
 await map.getByRole('button',{name:'Table view',exact:true}).click();await expect(map.getByRole('table')).toContainText('HMKB');
 await map.getByRole('searchbox',{name:'Search map'}).fill('missing');await expect(map.getByRole('table').locator('tbody tr')).toHaveCount(0);
 await map.getByRole('button',{name:'Map view',exact:true}).click();await expect(map).toContainText('No securities match');
});
test('reference header exposes live source rates and the issuer directory on a phone',async({page})=>{
 await setup(page);await page.setViewportSize({width:390,height:844});await page.goto('/');
 await expect(page.getByTestId('market-source-strip')).toContainText('12,500');
 await page.getByRole('button',{name:'Open menu',exact:true}).click();
 await page.locator('.nav-dd-mobile-item').getByText('Company directory',{exact:true}).click();await expect(page).toHaveURL(/issuers$/);
});
test('currency dashboard uses readable heading and KPI sizes',async({page})=>{
 await setup(page);await page.goto('/currency');
 expect(await page.locator('.currency-banner h1').evaluate(e=>parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(26);
 expect(await page.getByTestId('currency-stats').locator('strong').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(24);
});
test('profile allocation uses the account valuation and hides the chart when incomplete',async({page})=>{
 await setup(page);let complete=true;
 await page.route('**/api/portfolio',r=>r.fulfill({json:{ok:true,valuation_complete:complete,market_value:complete?'100':'60',items:[{ticker:'HMKB',quantity:'2',market_value:'60',allocation_pct:complete?'60':null},{ticker:'UZTL',quantity:'1',market_value:complete?'40':null,allocation_pct:complete?'40':null}]}}));
 await page.goto('/profile');await expect(page.getByRole('img',{name:'Portfolio allocation'})).toBeVisible();await expect(page.getByTestId('profile-portfolio-preview')).toContainText('60%');
 complete=false;await page.reload();await expect(page.getByTestId('profile-portfolio-preview')).toContainText('HMKB');await expect(page.getByRole('img',{name:'Portfolio allocation'})).toHaveCount(0);
});
test('issuer directory presents the reference quote table with actual market values',async({page})=>{
 await setup(page);await page.goto('/issuers');const table=page.getByRole('table');await expect(table).toContainText('HMKB');await expect(table).toContainText('55');await expect(table).toContainText('+10');
});
test('currency bank table sorts offers and links related news',async({page})=>{
 await setup(page);await page.route('**/api/bank-fx',r=>r.fulfill({json:{ok:true,banks:[{bank_code:'a',bank_name:'Hamkorbank',rates:{USD:{BANK:{buy:12400,sell:12600}}}},{bank_code:'b',bank_name:'Second Bank',rates:{USD:{BANK:{buy:12500,sell:12800}}}}]}}));
 await page.goto('/currency');const rows=page.getByTestId('currency-bank-table').locator('tbody tr');await expect(rows.first()).toContainText('Second Bank');await page.getByLabel('Sort bank quotes').selectOption('sell');await expect(rows.first()).toContainText('Hamkorbank');await page.getByLabel('Sort bank quotes').selectOption('spread');await expect(rows.first()).toContainText('Hamkorbank');
 await page.getByTestId('currency-news').getByRole('button',{name:/Market update/}).click();await expect(page).toHaveURL(/news\/a$/);
});
test('profile applies an account saved screener from its overview',async({page})=>{
 await setup(page);await page.route('**/api/profile',r=>r.fulfill({json:{user:{id:19,email:'investor@example.test',full_name:'Investor'},preferences:{saved_screeners:[{id:'gainers',name:'My gainers',filters:{sector:'',query:'HMKB',direction:'gain',period:'1d',type:'stock',favoriteOnly:false,sortKeys:[]}}]},favorites:[],notes:[],security:{}}}));
 await page.goto('/profile');await page.getByTestId('profile-saved-screeners').getByRole('button',{name:'My gainers'}).click();await expect(page).toHaveURL(/market\?screener=gainers$/);await expect(page.getByTestId('saved-screeners').getByRole('button',{name:'Gainers',exact:true})).toHaveAttribute('aria-pressed','true');await expect(page.locator('.market-table-wrap tbody tr')).toContainText('HMKB');
});
