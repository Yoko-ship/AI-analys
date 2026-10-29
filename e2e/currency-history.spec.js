import { test, expect } from '@playwright/test';
const month = Array.from({length:31}, (_,i) => ({date:new Date(Date.UTC(2026,8,29+i)).toISOString().slice(0,10),value:11806.97+i*197.05/30,effective_date:new Date(Date.UTC(2026,8,29+i)).toISOString().slice(0,10)}));
const history = (ccy='USD', days=30) => ({ok:true,ccy,days,start:'2026-09-29',end:'2026-10-29',source:'cbu.uz',source_url:'https://cbu.uz/ru/arkhiv-kursov-valyut/',missing_days:0,points:days===30?month:month.slice(-8),summary:{latest:12004.02,latest_date:'2026-10-29',latest_effective_date:'2026-10-29',change:197.05,change_pct:1.66893,min:11806.97,max:12004.02}});
async function setup(page, {language='en',theme='light',mode='normal'}={}) {
 const calls=[];
 await page.addInitScript(({language,theme})=>{localStorage.setItem('uz_stock_analyzer_language',language);localStorage.setItem('uz_stock_analyzer_theme',theme);}, {language,theme});
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname;
  if(path==='/api/currency/history') {
   calls.push(url.searchParams.get('ccy')+':'+url.searchParams.get('days')+(url.searchParams.has('end')?'@'+url.searchParams.get('end'):''));
   if(mode==='error' && calls.length===1) return route.fulfill({status:503,json:{detail:'Unavailable'}});
   const data=history(url.searchParams.get('ccy'),Number(url.searchParams.get('days')));
   if(url.searchParams.has('end')) {
    const end=url.searchParams.get('end');
    data.points=Array.from({length:31},(_,i)=>{
     const date=new Date(Date.parse(end+'T00:00:00Z')-(30-i)*86400000).toISOString().slice(0,10);
     return {date,value:11800+i,effective_date:date};
    });
    data.start=data.points[0].date;data.end=end;
   }
   if(mode==='gap'||(mode==='pending'&&calls.length===1)) { data.points=data.points.map((p,i)=>i===10?{...p,value:null,effective_date:null}:p);data.missing_days=1; }
   if(mode==='pending'&&calls.length===1)data.pending_days=1;
   if(mode==='august') {
    const shift=day=>new Date(Date.parse(day+'T00:00:00Z')-62*86400000).toISOString().slice(0,10);
    data.points=data.points.map(p=>({...p,date:shift(p.date),effective_date:shift(p.effective_date)}));
    data.start=shift(data.start);data.end=shift(data.end);
    data.summary={...data.summary,latest_date:data.end,latest_effective_date:data.end};
   }
   if(mode==='empty') { data.points=[];data.summary={}; }
   return route.fulfill({json:data});
  }
  if(path==='/api/currency/rates') return route.fulfill({json:{ok:true,date:'29.10.2026',rates:[{ccy:'USD',rate:12004.02,nominal:1},{ccy:'EUR',rate:13361.67,nominal:1},{ccy:'RUB',rate:148.8,nominal:1}]}});
  if(path==='/api/bank-fx') return route.fulfill({json:{ok:true,banks:[{bank_code:'asia',bank_name:'Asia Alliance Bank',rates:{USD:{BANK:{buy:11920,sell:12010}},EUR:{BANK:{buy:13000,sell:13400}}}}]}});
  if(path==='/api/auth/me') return route.fulfill({status:401,json:{}});
  return route.fulfill({json:{ok:true,items:[]}});
 });
 await page.goto('/currency');
 return calls;
}
const card=page=>page.getByTestId('cbu-history');

test('daily chart has a readable scale, period change, dates and keyboard/hover inspection',async({page},info)=>{
 const calls=await setup(page);
 await expect(card(page).getByRole('heading',{name:'CBU rate history'})).toBeVisible();
 await expect(card(page).getByTestId('history-latest')).toContainText('12,004.02');
 expect(await card(page).getByTestId('history-latest').evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(22);
 await expect(card(page).getByTestId('history-change')).toContainText('+197.05');
 await expect(card(page).getByTestId('history-change')).toContainText('+1.67%');
 expect(calls.filter(call=>!call.includes('@'))).toEqual(['USD:30']);
 await expect(card(page).locator('canvas').first()).toBeVisible();
 const plot=card(page).getByRole('slider');
 await plot.focus();await page.keyboard.press('Home');
 await expect(plot).toHaveAttribute('aria-valuetext',/11,806.97/);
 await page.keyboard.press('ArrowRight');
 await expect(plot).toHaveAttribute('aria-valuetext',/30 Sept 2026/);
 await plot.hover({position:{x:120,y:80}});
 await expect(card(page).getByTestId('history-readout')).not.toContainText('29 Oct');
 await card(page).getByRole('button',{name:'1W',exact:true}).click();
 await expect.poll(()=>calls.filter(call=>!call.includes('@'))).toEqual(['USD:30','USD:7']);
 await expect(card(page).getByRole('button',{name:'1D',exact:true})).toHaveCount(0);
 await page.screenshot({path:info.outputPath('cbu-history-desktop.png'),fullPage:true});
});

test('missing observations split the line and expose the missing day',async({page})=>{
 await setup(page,{mode:'gap'});
 await expect(card(page).getByRole('slider')).toHaveAttribute('data-segments','2');
 await expect(card(page)).toContainText('1 day unavailable');
 const plot=card(page).getByRole('slider');await plot.focus();await page.keyboard.press('Home');
 for(let i=0;i<10;i++) await page.keyboard.press('ArrowRight');
 await expect(plot).toHaveAttribute('aria-valuetext',/Unavailable/);
});

test('history failure is retryable; no chart is invented for an empty series',async({page})=>{
 await setup(page,{mode:'error'});
 await card(page).getByRole('button',{name:'Retry',exact:true}).click();
 await expect(card(page).getByRole('slider')).toBeVisible();
 await page.route('**/api/currency/history*',route=>route.fulfill({json:{...history(),points:[],summary:{}}}));
 await card(page).getByRole('button',{name:'6M',exact:true}).click();
 await expect(card(page)).toContainText('Historical rates unavailable');
 await expect(card(page).getByRole('slider')).toHaveCount(0);
});

test.describe('phone history',()=>{
 test.use({hasTouch:true,viewport:{width:390,height:844}});
 for(const [language,theme,title] of [['ru','light','История курса'],['uz','dark','Kurs tarixi'],['en','light','Rate history']]) test(`collapsed until requested, touch inspection fits (${language})`,async({page},info)=>{
  const calls=await setup(page,{language,theme});
  const summary=card(page).locator('summary');
  await expect(summary).toHaveText(title);
  expect(calls).toEqual([]);
  await expect(card(page).getByRole('slider')).toHaveCount(0);
  await summary.tap();
  const plot=card(page).getByRole('slider');await expect(plot).toBeVisible();
  await plot.tap({position:{x:100,y:80}});
  await expect(plot).not.toHaveAttribute('aria-valuenow','30');
  expect(await card(page).evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
  await page.setViewportSize({width:320,height:740});
  expect(await card(page).evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('cbu-history-mobile.png'),fullPage:true});
  await summary.tap();await expect(plot).toHaveCount(0);
 });
});


test('a cold archive range continues loading without requiring repeated clicks', async ({page})=>{
 const calls=await setup(page,{mode:'pending'});
 await expect.poll(()=>calls.length).toBe(2);
 await expect(card(page).getByRole('slider')).toHaveAttribute('data-segments','1');
 await expect(card(page)).not.toContainText('1 day unavailable');
});

test('currency history uses the company chart gestures and resets the visible dates', async ({page})=>{
 await setup(page);
 await expect(card(page)).toContainText('Official Central Bank rate');
 const plot=card(page).getByRole('slider');
 await expect(plot.locator('canvas').first()).toBeVisible();
 const range=card(page).getByTestId('history-visible-range');
 await expect(range).toHaveAttribute('data-from','2026-09-29');
 const initial={from:await range.getAttribute('data-from'),to:await range.getAttribute('data-to')};
 await plot.scrollIntoViewIfNeeded();
 const box=await plot.boundingBox();
 await page.mouse.move(box.x+box.width*.5,box.y+80);
 await page.keyboard.down('Control');await page.mouse.wheel(0,-320);await page.keyboard.up('Control');
 await expect.poll(()=>range.getAttribute('data-from')).not.toBe(initial.from);
 const zoomed=await range.getAttribute('data-from');
 await page.mouse.move(box.x+box.width*.4,box.y+80);await page.mouse.down();
 await page.mouse.move(box.x+box.width*.65,box.y+80,{steps:8});await page.mouse.up();
 await expect.poll(()=>range.getAttribute('data-from')).not.toBe(zoomed);
 expect((await range.getAttribute('data-from'))<zoomed).toBe(true);
 await card(page).getByRole('button',{name:'Reset view',exact:true}).click();
 await expect(range).toHaveAttribute('data-from',initial.from);
 await expect(range).toHaveAttribute('data-to',initial.to);
 const before=await page.evaluate(()=>scrollY);
 await plot.hover();await page.mouse.wheel(0,180);
 await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(before);
 await expect(range).toHaveAttribute('data-from',initial.from);
});

test.describe('touch chart navigation',()=>{
 test.use({hasTouch:true,viewport:{width:390,height:844}});
 test('pinch zooms, horizontal swipe pans, and vertical swipe scrolls the page',async({page})=>{
  await setup(page,{language:'en'});
  await card(page).locator('summary').tap();
  const plot=card(page).getByRole('slider'),range=card(page).getByTestId('history-visible-range');
  await expect(plot.locator('canvas').first()).toBeVisible();
  await plot.scrollIntoViewIfNeeded();
  const box=await plot.boundingBox(),x=box.x+box.width*.42,y=box.y+80;
  const cdp=await page.context().newCDPSession(page);
  const touch=(type,points)=>cdp.send('Input.dispatchTouchEvent',{type,touchPoints:points.map(([id,x,y])=>({id,x,y,radiusX:2,radiusY:2,force:1}))});
  const initial=await range.getAttribute('data-from');
  await touch('touchStart',[[0,x-20,y],[1,x+20,y]]);
  for(let offset=30;offset<=70;offset+=10)await touch('touchMove',[[0,x-offset,y],[1,x+offset,y]]);
  await touch('touchEnd',[]);
  await expect.poll(()=>range.getAttribute('data-from')).not.toBe(initial);
  const zoomed=await range.getAttribute('data-from');
  await touch('touchStart',[[0,x-50,y]]);
  for(let offset=-40;offset<=50;offset+=10)await touch('touchMove',[[0,x+offset,y]]);
  await touch('touchEnd',[]);
  await expect.poll(()=>range.getAttribute('data-from')).not.toBe(zoomed);
  await card(page).getByRole('button',{name:'Reset view',exact:true}).tap();
  await expect(range).toHaveAttribute('data-from',initial);
  await plot.scrollIntoViewIfNeeded();
  const fresh=await plot.boundingBox(),before=await page.evaluate(()=>scrollY);
  await touch('touchStart',[[0,fresh.x+120,fresh.y+150]]);
  for(let offset=130;offset>=30;offset-=20)await touch('touchMove',[[0,fresh.x+120,fresh.y+offset]]);
  await touch('touchEnd',[]);
  await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(before);
  await expect(range).toHaveAttribute('data-from',initial);
 });
});

for(const pointer of ['hover','outside']) test(`panning before September 29 loads September without shifting dates or losing the period reset (${pointer})`,async({page})=>{
 await setup(page);
 let release;
 const requested=[];
 await page.route('**/api/currency/history*',async route=>{
  const url=new URL(route.request().url());
  if(!url.searchParams.has('end'))return route.fallback();
  requested.push(url.searchParams.get('end'));
  await new Promise(resolve=>{release=resolve;});
  const points=Array.from({length:31},(_,i)=>({date:new Date(Date.UTC(2026,7,29+i)).toISOString().slice(0,10),value:11700+i,effective_date:new Date(Date.UTC(2026,7,29+i)).toISOString().slice(0,10)}));
  await route.fulfill({json:{...history(),start:points[0].date,end:points.at(-1).date,points,missing_days:0,pending_days:0}});
 });
 const plot=card(page).getByRole('slider'),range=card(page).getByTestId('history-visible-range');
 await expect(plot).toBeVisible();await plot.scrollIntoViewIfNeeded();
 const box=await plot.boundingBox();
 await page.mouse.move(box.x+box.width*.25,box.y+80);await page.mouse.down();
 await page.mouse.move(box.x+box.width*.65,box.y+80,{steps:10});await page.mouse.up();
 await expect.poll(()=>requested).toEqual(['2026-09-28']);
 await expect(card(page)).toContainText('Loading earlier rates');
 const right=await range.getAttribute('data-to');
 if(pointer==='outside')await page.mouse.move(box.x-10,box.y);
 const stableReading=await card(page).getByTestId('history-readout').locator('span').first().innerText();
 await card(page).evaluate(el=>{
  window.currencyFrames=[];
  window.currencyObserver=new MutationObserver(records=>{
   const current={to:el.querySelector('[data-testid="history-visible-range"]').dataset.to,
    reading:el.querySelector('[data-testid="history-readout"]').textContent};
   window.currencyFrames.push(current);
   for(const record of records){
    if(record.attributeName==='data-to'&&record.oldValue)window.currencyFrames.push({...current,to:record.oldValue});
    if(record.type==='characterData'&&record.target.parentElement?.matches('[data-testid="history-readout"] > span')&&record.oldValue)
     window.currencyFrames.push({...current,reading:record.oldValue});
   }
  });
  window.currencyObserver.observe(el,{subtree:true,childList:true,characterData:true,attributes:true,attributeOldValue:true,characterDataOldValue:true});
 });
 release();
 await expect.poll(()=>range.getAttribute('data-from')).toMatch(/^2026-09-(0|1|2)/);
 await expect(range).toHaveAttribute('data-to',right);
 await expect(card(page)).not.toContainText('Loading earlier rates');
 const frames=await page.evaluate(()=>{window.currencyObserver.disconnect();return window.currencyFrames;});
 expect(frames.length).toBeGreaterThan(0);
 expect(frames.filter(frame=>frame.to!==right||!frame.reading.includes(stableReading))).toEqual([]);
 await page.mouse.move(box.x-10,box.y);
 const lastVisible=new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(right+'T12:00:00Z'));
 await expect(card(page).getByTestId('history-readout')).toContainText(lastVisible);
 await plot.focus();await page.keyboard.press('Home');
 await expect(plot).toHaveAttribute('aria-valuetext',/29 Aug 2026/);
 await card(page).getByRole('button',{name:'Reset view',exact:true}).click();
 await expect(range).toHaveAttribute('data-from','2026-09-29');
 await expect(range).toHaveAttribute('data-to','2026-10-29');
 await expect(card(page).getByTestId('history-change')).toContainText('+197.05');
});

test('an unavailable earlier month preserves the current chart and offers retry',async({page})=>{
 await setup(page);
 let calls=0;
 await page.route('**/api/currency/history*',async route=>{
  const url=new URL(route.request().url());
  if(!url.searchParams.has('end'))return route.fallback();
  calls++;
  return route.fulfill({status:503,json:{detail:'Unavailable'}});
 });
 const plot=card(page).getByRole('slider');await expect(plot).toBeVisible();await plot.scrollIntoViewIfNeeded();
 const box=await plot.boundingBox();
 await page.mouse.move(box.x+box.width*.25,box.y+80);await page.mouse.down();
 await page.mouse.move(box.x+box.width*.65,box.y+80,{steps:10});await page.mouse.up();
 await expect(card(page)).toContainText('Earlier rates unavailable');
 await expect(plot).toBeVisible();
 await card(page).getByRole('button',{name:'Retry earlier rates'}).click();
 await expect.poll(()=>calls).toBe(2);
});


test('the July edge never becomes blank while the previous month is delayed or fails',async({page})=>{
 await setup(page,{mode:'august'});
 let release;
 const requests=[];
 await page.route('**/api/currency/history*',async route=>{
  const url=new URL(route.request().url());
  if(!url.searchParams.has('end'))return route.fallback();
  requests.push(url.searchParams.get('end'));
  await new Promise(resolve=>{release=resolve;});
  await route.fulfill({status:503,json:{detail:'Slow archive unavailable'}});
 });
 const plot=card(page).getByRole('slider'),range=card(page).getByTestId('history-visible-range');
 await expect(range).toHaveAttribute('data-from','2026-07-29');
 await plot.scrollIntoViewIfNeeded();const box=await plot.boundingBox();
 for(let drag=0;drag<3;drag++){
  await page.mouse.move(box.x+box.width*.2,box.y+80);await page.mouse.down();
  await page.mouse.move(box.x+box.width*.75,box.y+80,{steps:12});await page.mouse.up();
 }
 await expect.poll(()=>requests).toEqual(['2026-07-28']);
 expect(Number(await plot.getAttribute('data-logical-from'))).toBeGreaterThanOrEqual(-1);
 await expect(card(page)).toContainText('Loading earlier rates');
 await expect(range).toHaveAttribute('data-from','2026-07-29');
 release();
 await expect(card(page)).toContainText('Earlier rates unavailable');
 expect(Number(await plot.getAttribute('data-logical-from'))).toBeGreaterThanOrEqual(-1);
 await expect(plot.locator('canvas').first()).toBeVisible();
});
