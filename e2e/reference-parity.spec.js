import {test,expect} from '@playwright/test';
async function setup(page,{admin=false,language='en',theme='light'}={}){
 await page.addInitScript(({language,theme})=>{localStorage.setItem('uz_stock_analyzer_language',language);localStorage.setItem('uz_stock_analyzer_theme',theme);localStorage.setItem('uz_stock_analyzer_token','reference-test');sessionStorage.setItem('uz_sponsor_seen','1');},{language,theme});
 const user={id:19,full_name:'Investor',email:'investor@example.test',is_admin:admin};
 const stocks=[{ticker:'HMKB',name:'Hamkorbank',type:'stock',last_price:55,close_price:50,volume:4000000,quantity:1000,trade_count:7,last_trade_date:'2026-10-26'}];
 await page.route('**/api/**',r=>{const path=new URL(r.request().url()).pathname;return r.fulfill({json:path==='/api/auth/me'?{user}:path==='/api/profile'?{user,preferences:{saved_screeners:[]},favorites:[{ticker:'HMKB',company_name:'Hamkorbank'}],notes:[],security:{}}:path==='/api/market/stocks'?{stocks}:path==='/api/companies'?{companies:stocks.map(s=>({...s,company_name:s.name}))}:path==='/api/securities'?{ok:true,securities:{HMKB:{...stocks[0],sector:'banks'}}}:path==='/api/currency/rates'?{ok:true,rates:[{ccy:'USD',rate:12500,nominal:1,diff:0},{ccy:'EUR',rate:14000,nominal:1,diff:0}]}:path==='/api/bank-fx'?{ok:true,banks:[{bank_code:'hamkorbank',bank_name:'Hamkorbank',rates:{USD:{BANK:{buy:12400,sell:12600}}}}],best:{USD:{BANK:{best_buy:{value:12400},best_sell:{value:12600}}}}}:path==='/api/portfolio'?{ok:true,items:[],transactions:[],count:0,priced_count:0,market_value:'0',cost_value:'0',valuation_complete:true}:path==='/api/news/feed'?{ok:true,items:[{id:'a',title:'Market update',title_en:'Market update',published_at:'2026-10-26T09:00:00Z',summary_en:'Disclosed market events.',tickers:['HMKB'],category:'market'}]}:{ok:true,items:[],stats:{},changes:{}}});});
}
for(const width of [1440,390]){
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
 await converter.getByRole('combobox',{name:'From currency'}).click();
 await page.getByRole('option',{name:'Euro',exact:true}).click();
 await expect(converter.getByTestId('converted-amount')).toContainText('28,000');
});
test('currency selectors show emblems, full names and the selected check in the dark menu',async({page},info)=>{
 await page.setViewportSize({width:1440,height:1100});
 await setup(page,{language:'ru',theme:'dark'});await page.goto('/currency');
 const converter=page.getByTestId('currency-converter');
 const from=converter.getByRole('combobox',{name:'Из валюты',exact:true,includeHidden:true});
 const to=converter.getByRole('combobox',{name:'В валюту',exact:true,includeHidden:true});
 await expect(from).toHaveText('USD');await expect(to).toHaveText('UZS');
 await expect(converter.locator('.currency-select-label')).toHaveText(['Валюта','Валюта']);
 for (const label of await converter.locator('.currency-select-label').all()) {
  expect(await label.evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(22);
 }
 for(const trigger of [from,to]){
  await expect(trigger.locator('img')).toBeVisible();
  expect(await trigger.locator('img').evaluate(img=>img.complete&&img.naturalWidth>0)).toBe(true);
  const artwork=await page.request.get(await trigger.locator('img').getAttribute('src'));
  expect(artwork.headers()['content-type']).toContain('image/svg+xml');
  const svg=await artwork.text();
  expect(svg).toContain('<path');
  expect(svg).not.toMatch(/<image\b|data:image|<script\b|<foreignObject\b/i);
  expect(await trigger.evaluate(el=>parseFloat(getComputedStyle(el).borderTopWidth))).toBe(2);
  expect((await trigger.boundingBox()).height).toBeGreaterThanOrEqual(74);
  const badge = await trigger.locator('img').boundingBox();
  expect(badge.width).toBeGreaterThanOrEqual(58);
  expect(badge.height).toBeCloseTo(badge.width);
  const code = trigger.getByText(await trigger.innerText(), { exact: true });
  expect(await code.evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(24);
 }
 expect((await converter.getByLabel('Сумма',{exact:true}).boundingBox()).y).toBeLessThan((await from.boundingBox()).y);
 await from.click();const menu=page.getByRole('listbox');
 await expect(menu.getByRole('option')).toHaveCount(3);
 for(const name of ['Узбекский сум','Доллар США','Евро'])await expect(menu.getByRole('option',{name,exact:true})).toBeVisible();
 const selected=menu.getByRole('option',{name:'Доллар США',exact:true});
 await expect(selected).toHaveAttribute('aria-selected','true');
 await expect(selected.locator('.currency-select-check')).toBeVisible();
 const selectedName = selected.getByText('Доллар США', { exact: true });
 expect(await selectedName.evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(20);
 const box=await menu.boundingBox(),triggerBox=await from.boundingBox();
 expect(Math.abs(box.width-triggerBox.width)).toBeLessThan(2);
 expect(box.y).toBeGreaterThanOrEqual(triggerBox.y+triggerBox.height);
 expect(await selected.evaluate(el=>getComputedStyle(el).backgroundColor)).not.toBe(await menu.evaluate(el=>getComputedStyle(el).backgroundColor));
 await expect(selected).toHaveCSS('outline-style', 'none');
 await page.screenshot({path:info.outputPath('currency-selector-dark.png')});
 const som = menu.getByRole('option', { name: 'Узбекский сум', exact: true });
 await page.keyboard.press('ArrowUp');
 await expect(som).toBeFocused();
 await expect(som).toHaveCSS('outline-style', 'solid');
 await som.click();
 await expect(from).toHaveText('UZS');await expect(converter.getByTestId('converted-amount')).toContainText(/1\s000/);
 await to.click();await page.keyboard.press('Escape');await expect(menu).toHaveCount(0);await expect(to).toBeFocused();
});

async function expectPartsToFit(row, parts) {
 const bounds = await row.boundingBox();
 let right = bounds.x;
 for (const part of parts) {
  await expect(part).toBeVisible();
  const box = await part.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(right);
  expect(box.y).toBeGreaterThanOrEqual(bounds.y);
  expect(box.y + box.height).toBeLessThanOrEqual(bounds.y + bounds.height);
  expect(await part.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  right = box.x + box.width;
 }
 expect(right).toBeLessThanOrEqual(bounds.x + bounds.width);
}

for (const width of [719, 800, 1024, 1240]) {
 test(`currency selector contents stay inside the converter at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 1100 });
  await setup(page, { language: 'ru', theme: 'dark' });
  await page.goto('/currency');
  const converter = page.getByTestId('currency-converter');
  const from = converter.getByRole('combobox', { name: 'Из валюты' });
  const to = converter.getByRole('combobox', { name: 'В валюту' });
  await converter.scrollIntoViewIfNeeded();
  for (const [trigger, code] of [[from, 'USD'], [to, 'UZS']]) {
   await expectPartsToFit(trigger, [
    trigger.locator('img'), trigger.getByText(code, { exact: true }), trigger.locator('.currency-select-chevron'),
   ]);
  }
  const fromBox = await from.boundingBox();
  const toBox = await to.boundingBox();
  if (width === 719) expect(toBox.y).toBeCloseTo(fromBox.y);
  await from.click();
  const menu = page.getByRole('listbox');
  for (const name of ['Узбекский сум', 'Доллар США']) {
   const option = menu.getByRole('option', { name, exact: true });
   const optionName = option.getByText(name, { exact: true });
   const parts = [option.locator('img'), optionName];
   if (name === 'Доллар США') parts.push(option.locator('.currency-select-check'));
   await expectPartsToFit(option, parts);
   const lineCount = await optionName.evaluate(el => {
    const range = document.createRange();
    range.selectNodeContents(el);
    return range.getClientRects().length;
   });
   expect(lineCount).toBe(1);
  }
  const menuBox = await menu.boundingBox();
  expect(menuBox.x).toBeGreaterThanOrEqual(0);
  expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(width);
  await page.screenshot({ path: info.outputPath(`currency-selector-${width}.png`) });
  await menu.getByRole('option', { name: 'Узбекский сум', exact: true }).click();
  await expect(from).toHaveText('UZS');
  await expect(converter.getByTestId('converted-amount')).toContainText(/1\s000/);
 });
}
test('currency selectors fit a phone and support keyboard selection, swapping and outside dismissal',async({page},info)=>{
 await page.setViewportSize({width:390,height:844});await setup(page);await page.goto('/currency');
 const converter=page.getByTestId('currency-converter'),from=converter.getByRole('combobox',{name:'From currency'}),to=converter.getByRole('combobox',{name:'To currency'});
 await converter.getByLabel('Amount',{exact:true}).fill('2');
 await from.focus();await page.keyboard.press('Enter');
 const selected = page.getByRole('option', { name: 'US dollar', exact: true });
 await expect(selected).toBeFocused();
 await expect(selected).toHaveCSS('outline-style', 'solid');
 await page.keyboard.press('End');await expect(page.getByRole('option',{name:'Euro',exact:true})).toBeFocused();await page.keyboard.press('Enter');
 await expect(from).toContainText('EUR');await expect(converter.getByTestId('converted-amount')).toContainText('28,000');
 await converter.getByRole('button',{name:'Swap currencies'}).click();
 await expect(from).toHaveText('UZS');await expect(to).toContainText('EUR');
 for(const width of [390,320]){
  await page.setViewportSize({width,height:844});await to.click();
  const menu=page.getByRole('listbox');await expect(menu).toBeVisible();const box=await menu.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(width);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath(`currency-selector-${width}.png`)});
  await page.mouse.click(2,2);await expect(menu).toHaveCount(0);
 }
});
test('public issuer directory is searchable and opens real company routes',async({page})=>{
 await setup(page);await page.goto('/issuers');await page.getByRole('searchbox',{name:'Search issuers'}).fill('Hamkor');
 const issuer=page.locator('[data-issuer="HMKB"]');await expect(issuer).toContainText('Hamkorbank');
 await issuer.getByRole('button',{name:'HMKB',exact:true}).click();await expect(page).toHaveURL(/company\/HMKB/);
});
test('corporate detail shows extracted fields and the reason for its attention level',async({page})=>{
 await setup(page);await page.route('**/api/news/corporate-events?**',r=>r.fulfill({json:{ok:true,items:[{id:'license',story_id:'license',organization:'Issuer',title:{en:'Licence returned'},summary:{en:'Voluntary licence return'},stage:'disclosed',category:'risks',priority:1,confidence:'confirmed',priority_provisional:false,priority_explanation:{en:'The issuer reports voluntary licence return.'},facts:[{source_field:'type_activity',label:{en:'Licensed activity'},value:'Payment system',unit:'text'}],source_url:'https://openinfo.uz/ru/facts/23/1',published_at:'2026-10-26',documents:[],document_count:1}],categories:{risks:{en:'Risks'}},facts:{}}}));
 await page.goto('/news?tab=corporate');await page.getByRole('link',{name:'Licence returned',exact:true}).click();
 const detail=page.getByTestId('corporate-event-detail');
 await expect(detail).toContainText('Payment system');await expect(detail).toContainText('voluntary licence return');
});
test('simplified header keeps bank rates accessible for an admin on a phone',async({page})=>{
 await setup(page,{admin:true});await page.setViewportSize({width:390,height:844});await page.goto('/');
 await page.getByRole('button',{name:'Open menu',exact:true}).click();
 await page.locator('.nav-dd-mobile-item').getByText('Bank exchange rates',{exact:true}).click();await expect(page).toHaveURL(/currency$/);
});
test('currency dashboard uses readable heading and KPI sizes',async({page})=>{
 await setup(page);await page.goto('/currency');
 expect(await page.locator('.currency-banner h1').evaluate(e=>parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(26);
 expect(await page.getByTestId('currency-stats').locator('strong').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(24);
});

test('audit: phone exchange amount comes before the long bank list',async({page},info)=>{
 await setup(page);await page.setViewportSize({width:390,height:844});
 await page.route('**/api/bank-fx',r=>r.fulfill({json:{ok:true,banks:Array.from({length:30},(_,i)=>({bank_code:`bank-${i}`,bank_name:`Bank ${i}`,rates:{USD:{BANK:{buy:11920-i,sell:12010+i}}}}))}}));
 await page.goto('/currency');
 const amount=page.locator('.bankfx-amount input');await expect(amount).toBeVisible();
 expect((await amount.boundingBox()).y).toBeLessThan(700);
 const bankTable=page.getByTestId('currency-bank-table');
 expect((await amount.boundingBox()).y).toBeLessThan((await bankTable.boundingBox()).y);
 await page.getByRole('link',{name:'Currency converter',exact:true}).click();
 await expect(page.getByTestId('currency-converter')).toBeInViewport();
 await page.screenshot({path:info.outputPath('currency-phone-fixed.png'),fullPage:true});
});
test('profile allocation uses the account valuation and hides the chart when incomplete',async({page})=>{
 await setup(page);let complete=true;
 await page.route('**/api/portfolio',r=>r.fulfill({json:{ok:true,valuation_complete:complete,market_value:complete?'100':'60',items:[{ticker:'HMKB',quantity:'2',market_value:'60',allocation_pct:complete?'60':null},{ticker:'UZTL',quantity:'1',market_value:complete?'40':null,allocation_pct:complete?'40':null}]}}));
 await page.goto('/profile');await expect(page.getByRole('img',{name:'Portfolio allocation'})).toBeVisible();await expect(page.getByTestId('profile-portfolio-preview')).toContainText('60%');
 complete=false;await page.reload();await expect(page.getByTestId('profile-portfolio-preview')).toContainText('HMKB');await expect(page.getByRole('img',{name:'Portfolio allocation'})).toHaveCount(0);
});
test('issuer directory presents the reference quote table with actual market values',async({page})=>{
 await setup(page);await page.goto('/issuers');const row=page.locator('[data-ticker="HMKB"]');await expect(row.getByRole('rowheader')).toContainText('HMKB');await expect(row.getByRole('cell')).toHaveText(['—','55','+10.00%','4.00M']);
});
test('currency bank table sorts offers and links related news',async({page})=>{
 await setup(page);await page.route('**/api/bank-fx',r=>r.fulfill({json:{ok:true,banks:[{bank_code:'a',bank_name:'Hamkorbank',rates:{USD:{BANK:{buy:12400,sell:12600}}}},{bank_code:'b',bank_name:'Second Bank',rates:{USD:{BANK:{buy:12500,sell:12800}}}}]}}));
 await page.goto('/currency');const rows=page.getByTestId('currency-bank-table').locator('tbody tr');await expect(rows.first()).toContainText('Second Bank');await page.getByLabel('Sort bank quotes').selectOption('sell');await expect(rows.first()).toContainText('Hamkorbank');await page.getByLabel('Sort bank quotes').selectOption('spread');await expect(rows.first()).toContainText('Hamkorbank');
 await page.getByTestId('currency-news').getByRole('button',{name:/Market update/}).click();await expect(page).toHaveURL(/news\/a$/);
});
test('profile applies an account saved screener from its overview',async({page})=>{
 await setup(page);await page.route('**/api/profile',r=>r.fulfill({json:{user:{id:19,email:'investor@example.test',full_name:'Investor'},preferences:{saved_screeners:[{id:'gainers',name:'My gainers',filters:{sector:'',query:'HMKB',direction:'gain',period:'1d',type:'stock',favoriteOnly:false,sortKeys:[]}}]},favorites:[],notes:[],security:{}}}));
 await page.goto('/profile');await page.getByTestId('profile-saved-screeners').getByRole('button',{name:'My gainers'}).click();await expect(page).toHaveURL(/market\?screener=gainers$/);await expect(page.getByRole('searchbox')).toHaveValue('HMKB');await expect(page.locator('.market-table-wrap tbody tr')).toContainText('HMKB');
});
