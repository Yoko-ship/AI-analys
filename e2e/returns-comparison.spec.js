import {test,expect} from '@playwright/test';

const companies=[{ticker:'HMKB',name:'Hamkorbank',family:'bank'},{ticker:'IPKY',name:'Ipak Yo‘li Bank',family:'bank'},{ticker:'SQBN',name:'SQB',family:'bank'}];
const histories={
  HMKB:[['2025-12-30',100],['2026-01-30',120],['2026-02-27',90],['2026-04-30',99],['2026-05-12',108.9]],
  IPKY:[['2025-12-30',200],['2026-01-30',220],['2026-02-27',242],['2026-04-30',240],['2026-05-12',250]],
  SQBN:[],
};
test.beforeEach(async({page})=>{
  await page.addInitScript(()=>{localStorage.setItem('uz_stock_analyzer_language','en');localStorage.setItem('uz_stock_analyzer_token','returns-admin-session');sessionStorage.setItem('uz_sponsor_seen','1');});
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url());
    if(url.pathname==='/api/auth/me')return route.fulfill({json:{user:{id:1,email:'returns@example.test',is_admin:true}}});
    if(url.pathname==='/api/company-comparison/options')return route.fulfill({json:{ok:true,companies,periods:[]}});
    if(url.pathname.startsWith('/api/price-history/')) {
      const ticker=url.pathname.split('/').pop();
      return route.fulfill({json:{ok:true,ticker,as_of:'2026-05-12',points:(histories[ticker]||[]).map(([date,close])=>({date,close})),adjustments:[]}});
    }
    return route.fulfill({json:{ok:true,user:null,companies:[],securities:{},stocks:[],items:[],stats:{}}});
  });
});
const url='/compare?view=returns&companies=HMKB,IPKY&from=2026-01&to=2026-05';
const crossYearUrl='/compare?view=returns&companies=HMKB,IPKY&from=2025-12&to=2026-11';

async function expectContinuousGrid(table) {
  const edges=await table.evaluate(element=>{
    const cells=Array.from(element.tBodies[0].rows[0].cells);
    const headers=Array.from(element.tHead.rows[0].cells);
    const stack=element.querySelector('td:has(button + button)');
    const rowEdge=stack.firstElementChild.getBoundingClientRect().bottom;
    const divider=(cell,edge)=>{
      const style=getComputedStyle(cell);
      return style[`border${edge}Style`]==='solid' && style[`border${edge}Width`]==='1px' &&
        style[`border${edge}Color`]!=='rgba(0, 0, 0, 0)';
    };
    return {
      columns:cells.slice(1).every((cell,i)=>cell.getBoundingClientRect().left===cells[i].getBoundingClientRect().right && divider(cells[i],'Right')),
      headers:headers.every((header,i)=>header.getBoundingClientRect().bottom===cells[i].getBoundingClientRect().top && divider(header,'Bottom') && divider(header,'Right')),
      rows:Array.from(element.tBodies[0].rows[0].querySelectorAll('td')).every(cell=>{
        const [first,second]=cell.children;
        return second && first.getBoundingClientRect().bottom===rowEdge && second.getBoundingClientRect().top===rowEdge && divider(first,'Bottom');
      }),
    };
  });
  expect.soft(edges).toEqual({columns:true,headers:true,rows:true});
}

for(const role of ['guest','member','editor']) test(`returns are hidden from ${role}, including direct links`,async({page},info)=>{
  await page.addInitScript(role=>{
    if(role==='guest')localStorage.removeItem('uz_stock_analyzer_token');
  },role);
  await page.route('**/api/auth/me',route=>route.fulfill({json:{user:role==='guest'?null:{id:2,email:'member@example.test',is_admin:false,admin_role:role==='editor'?'editor':null}}}));
  const requests=[];
  page.on('request',request=>{if(request.url().includes('include_unknown=true'))requests.push(request.url());});
  await page.goto(url);
  await expect(page.getByRole('status')).toHaveText('This view is available to administrators only.');
  if(role!=='guest')await expect(page.locator('.account-button')).toBeVisible();
  await expect(page.getByRole('heading',{name:'Compare returns',exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Returns',exact:true})).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('status')).toHaveText('This view is available to administrators only.');
  await expect(page.getByRole('heading',{name:'Compare returns',exact:true})).toHaveCount(0);
  expect(requests).toEqual([]);
  await page.screenshot({path:info.outputPath(`comparison-${role}.png`),fullPage:true});
  await page.getByRole('button',{name:'Fundamentals',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Compare companies',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Returns',exact:true})).toHaveCount(0);
  await page.goto('/company/HMKB');
  await expect(page.locator('.company-page-tabs')).toBeVisible();
  await expect(page.getByRole('link',{name:'Compare returns',exact:true})).toHaveCount(0);
});

test('returns wait for verified admin access and preserve the direct link',async({page})=>{
  let release;
  const gate=new Promise(resolve=>{release=resolve;});
  await page.route('**/api/auth/me',async route=>{
    await gate;
    await route.fulfill({json:{user:{id:1,email:'admin@example.test',is_admin:false,admin_role:'administrator'}}});
  });
  const requests=[];
  page.on('request',request=>{if(request.url().includes('include_unknown=true'))requests.push(request.url());});
  await page.goto(url);
  await expect(page.getByRole('status')).toHaveText('This view is available to administrators only.');
  await expect(page.getByRole('heading',{name:'Compare returns',exact:true})).toHaveCount(0);
  expect(requests).toEqual([]);
  release();
  await expect(page.getByRole('heading',{name:'Compare returns',exact:true})).toBeVisible();
  await expect(page.getByTestId('return-HMKB-2026-01')).toContainText('+20%');
});
test('returns heatmap calculates calendar returns and preserves dates in annual and relative views',async({page},info)=>{
  await page.goto(url);
  await expect(page.getByRole('heading',{name:'Compare returns'})).toBeVisible();
  await expect(page.getByTestId('return-HMKB-2026-01')).toContainText('+20%');
  await expect(page.getByTestId('return-HMKB-2026-02')).toContainText('-25%');
  await expect(page.getByTestId('return-HMKB-2026-03')).toContainText('—');
  await page.getByTestId('return-HMKB-2026-04').click();
  await expect(page.getByTestId('return-detail')).toContainText('2026-02-27');
  await expect(page.getByTestId('return-detail')).toContainText('Older baseline');
  await page.getByRole('button',{name:'Relative',exact:true}).click();
  await expect(page.getByTestId('returns-period-2026-02').getByRole('button').first()).toContainText('IPKY');
  await page.getByRole('button',{name:'Annual',exact:true}).click();
  await expect(page.getByTestId('return-HMKB-2026')).toContainText('+8.9%');
  await expect(page.getByLabel('From month')).toHaveValue('2026-01');
  await expect(page.getByLabel('To month')).toHaveValue('2026-05');
  await page.reload();
  await expect(page.getByRole('button',{name:'Annual',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.screenshot({path:info.outputPath('returns-annual.png'),fullPage:true,animations:'disabled'});
});
test('selection, empty histories, date validation, keyboard details and phone layout',async({page},info)=>{
  await page.setViewportSize({width:390,height:844}); await page.goto(url);
  await page.getByRole('button',{name:'Add company',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:/SQB/}).click();
  await expect(page.getByTestId('return-SQBN-2026-01')).toContainText('—');
  await page.getByLabel('From month').fill('2026-06');
  await expect(page.getByRole('alert')).toContainText('Start month');
  await page.getByLabel('From month').fill('2026-01');
  const cell=page.getByTestId('return-HMKB-2026-01');
  await expect(cell).toBeEnabled();
  await page.getByRole('region',{name:'Returns',exact:true}).focus();
  await page.keyboard.press('Tab');
  await expect(cell).toBeFocused();
  await expect(cell).toHaveCSS('outline-style','solid');
  await cell.press('Enter');
  await expect(page.getByTestId('return-detail')).toContainText('100');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('returns-phone.png'),fullPage:true,animations:'disabled'});
  await page.getByRole('button',{name:'Remove SQBN',exact:true}).click();
  await expect(page.getByTestId('return-SQBN-2026-01')).toHaveCount(0);
  await page.getByRole('button',{name:'Remove HMKB',exact:true}).click();
  await page.getByRole('button',{name:'Remove IPKY',exact:true}).click();
  await expect(page.getByText('Add a company to compare its price returns.')).toBeVisible();
});
test('history errors can be retried without hiding the other instrument',async({page})=>{
  let failed=true;
  await page.route('**/api/price-history/HMKB?**',route=>failed?route.fulfill({status:502,json:{ok:false}}):route.fulfill({json:{ok:true,ticker:'HMKB',as_of:'2026-05-12',points:histories.HMKB.map(([date,close])=>({date,close}))}}));
  await page.goto(url);
  await expect(page.getByRole('alert')).toContainText('HMKB');
  await expect(page.getByTestId('return-IPKY-2026-01')).toContainText('+10%');
  failed=false;await page.getByRole('button',{name:'Retry',exact:true}).click();
  await expect(page.getByTestId('return-HMKB-2026-01')).toContainText('+20%');
});

test('company page links to its returns and the comparison offers both views',async({page})=>{
  await page.goto('/company/HMKB');
  await page.getByRole('link',{name:'Compare returns',exact:true}).click();
  await expect(page).toHaveURL(/view=returns/);
  await expect(page.getByRole('heading',{name:'Compare returns'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Remove HMKB',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Fundamentals',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Compare companies'})).toBeVisible();
  await page.getByRole('button',{name:'Returns',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Compare returns'})).toBeVisible();
});

for(const theme of ['dark','light']) test(`heatmap is readable on desktop and phone (${theme})`,async({page},info)=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(theme=>localStorage.setItem('uz_stock_analyzer_theme',theme),theme);
  await page.route('**/api/price-history/*?**',route=>{
    const ticker=new URL(route.request().url()).pathname.split('/').pop();
    const points=[['2025-11-28',histories[ticker][0][1]],...histories[ticker],['2026-09-30',100],['2026-11-18',125]];
    return route.fulfill({json:{ok:true,ticker,as_of:'2026-11-18',points:points.map(([date,close])=>({date,close})),adjustments:[]}});
  });
  await page.setViewportSize({width:1440,height:1000});await page.goto(crossYearUrl);
  await expect(page.getByTestId('return-HMKB-2026-01')).toContainText('+20%');
  await expect(page.locator('html')).toHaveAttribute('data-theme',theme);
  for(const label of ['From month','To month']) {
    const {width,height}=await page.getByLabel(label).boundingBox();
    expect.soft(width).toBeLessThan(165);
    expect.soft(height).toBeLessThan(42);
  }
  const tables=page.getByRole('table');
  for(const year of ['2025','2026']) await expectContinuousGrid(page.getByRole('table',{name:year,exact:true}));
  const november=page.getByTestId('return-HMKB-2026-11').locator('strong');
  await expect(november).toHaveText('+25%*†');
  expect.soft(parseFloat(await november.evaluate(element=>getComputedStyle(element).fontSize))).toBeGreaterThan(11);
  await page.screenshot({path:info.outputPath(`returns-desktop-${theme}.png`),fullPage:true,animations:'disabled'});
  await page.getByRole('button',{name:'Relative',exact:true}).click();
  await expectContinuousGrid(page.getByRole('table',{name:'2026',exact:true}));
  await page.screenshot({path:info.outputPath(`returns-ranking-${theme}.png`),fullPage:true,animations:'disabled'});
  await page.getByRole('button',{name:'Annual',exact:true}).click();
  await expectContinuousGrid(tables);
  await page.screenshot({path:info.outputPath(`returns-annual-${theme}.png`),fullPage:true,animations:'disabled'});
  await page.getByRole('button',{name:'Monthly',exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  await page.reload();await expect(page.getByTestId('return-HMKB-2026-01')).toContainText('+20%');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath(`returns-phone-${theme}.png`),fullPage:true,animations:'disabled'});
  expect(errors).toEqual([]);
});

for(const locale of [
  {lang:'ru',path:'/compare',heading:'Сравнение доходности',value:'+20%',method:'Как считается'},
  {lang:'uz',path:'/uz/compare',heading:'Daromadlilikni solishtirish',value:'+20%',method:'Hisoblash usuli'},
  {lang:'en',path:'/compare',heading:'Compare returns',value:'+20%',method:'How returns are calculated'},
]) test(`returns localizes labels and preserves its link (${locale.lang})`,async({page})=>{
  await page.addInitScript(lang=>localStorage.setItem('uz_stock_analyzer_language',lang),locale.lang);
  await page.goto(locale.path+url.slice(url.indexOf('?')));
  await expect(page.getByRole('heading',{name:locale.heading,exact:true})).toBeVisible();
  await expect(page.getByTestId('return-HMKB-2026-01')).toContainText(locale.value);
  await expect(page.getByText(locale.method,{exact:true})).toHaveCount(0);
  await page.reload();await expect(page.getByRole('heading',{name:locale.heading,exact:true})).toBeVisible();
});

test('mode changes reuse history and selection rejects duplicates',async({page})=>{
  const requests=[];
  page.on('request',request=>{if(request.url().includes('/api/price-history/'))requests.push(request.url());});
  await page.goto(url);
  await expect(page.getByTestId('return-HMKB-2026-01')).toContainText('+20%');
  await page.getByRole('button',{name:'Annual',exact:true}).click();
  await page.getByRole('button',{name:'Relative',exact:true}).click();
  await page.getByLabel('From month').fill('2026-02');
  await expect(page.getByTestId('return-HMKB-2026')).toContainText('-9.25%');
  expect(requests).toHaveLength(2);
  await page.getByRole('button',{name:'Add company',exact:true}).click();
  await expect(page.getByRole('dialog').getByRole('button',{name:/Hamkorbank/})).toBeDisabled();
  await expect(page.getByRole('dialog')).not.toContainText('Reported financials');
  await page.getByRole('dialog').press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('a partial first year shows its selected month immediately on a phone',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto(crossYearUrl);
  const december=page.getByTestId('return-HMKB-2025-12');
  await expect(december).toBeVisible();
  const box=await december.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x+box.width).toBeLessThanOrEqual(390);
  const scroller=page.getByRole('region',{name:'Returns',exact:true});
  await scroller.evaluate(element=>{element.scrollLeft=element.scrollWidth;});
  const total=page.getByTestId('return-HMKB-2026');
  await expect(total).toBeInViewport();
  const totalBox=await total.boundingBox();
  const scrollBox=await scroller.boundingBox();
  expect(totalBox.x).toBeGreaterThan(scrollBox.x);
  expect(totalBox.x+totalBox.width).toBeLessThanOrEqual(scrollBox.x+scrollBox.width);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
});

for(const [index,invalid] of [
  {ticker:undefined}, {ticker:'HMKBP'}, {as_of:undefined}, {as_of:'2026-02-31'},
  {points:[...histories.HMKB.map(([date,close])=>({date,close})),{date:'2026-02-31',close:125}]},
].entries()) test(`unverified history is retryable and cannot truncate another company (${index})`,async({page})=>{
  await page.route('**/api/price-history/HMKB?**',route=>route.fulfill({json:{
    ok:true,ticker:'HMKB',as_of:'2026-05-12',points:[{date:'2026-01-30',close:120}],...invalid,
  }}));
  await page.goto(url);
  await expect(page.getByRole('alert')).toContainText('HMKB');
  await expect(page.getByTestId('return-IPKY-2026-05')).toContainText('+4.17%');
  await expect(page.getByTestId('return-HMKB-2026-01')).toContainText('—');
});

test('ambiguous prices withhold only dependent cells and explain the missing value',async({page})=>{
  await page.route('**/api/price-history/HMKB?**',route=>route.fulfill({json:{ok:true,ticker:'HMKB',as_of:'2026-05-12',
    points:[...histories.HMKB,['2026-01-30',125]].map(([date,close])=>({date,close})),
  }}));
  await page.goto(url);
  await expect(page.getByTestId('return-HMKB-2026-01')).toContainText('—');
  await expect(page.getByTestId('return-HMKB-2026-02')).toContainText('—');
  await expect(page.getByTestId('return-HMKB-2026-05')).toContainText('+10%');
  await page.getByTestId('return-HMKB-2026-01').click();
  await expect(page.getByTestId('return-detail')).toContainText('Unverified or conflicting');
});

test('each comparison view retains its nondefault settings on a round trip',async({page})=>{
  await page.goto('/compare?companies=HMKB,IPKY&period=2025&standard=IFRS&scope=consolidated&unit=million');
  await expect(page.getByRole('heading',{name:'Compare companies'})).toBeVisible();
  await page.getByRole('button',{name:'Returns',exact:true}).click();
  await page.getByLabel('From month').fill('2026-02');
  await page.getByLabel('To month').fill('2026-04');
  await page.getByRole('button',{name:'Annual',exact:true}).click();
  await page.getByRole('button',{name:'Relative',exact:true}).click();
  await page.getByRole('button',{name:'Fundamentals',exact:true}).click();
  for(const [key,value] of Object.entries({period:'2025',standard:'IFRS',scope:'consolidated',unit:'million'})) {
    await expect.poll(()=>new URL(page.url()).searchParams.get(key)).toBe(value);
  }
  await page.getByRole('button',{name:'Returns',exact:true}).click();
  await expect(page.getByLabel('From month')).toHaveValue('2026-02');
  await expect(page.getByLabel('To month')).toHaveValue('2026-04');
  await expect(page.getByRole('button',{name:'Annual',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(page.getByRole('button',{name:'Relative',exact:true})).toHaveAttribute('aria-pressed','true');
});

test('a late market anchor invalidates a previously selected calculation',async({page})=>{
  let release;
  const gate=new Promise(resolve=>{release=resolve;});
  await page.route('**/api/price-history/IPKY?**',async route=>{
    await gate;
    await route.fulfill({json:{ok:true,ticker:'IPKY',as_of:'2026-04-30',
      points:histories.IPKY.map(([date,close])=>({date,close})),adjustments:[]}});
  });
  await page.goto(url);
  await page.getByTestId('return-HMKB-2026-05').click();
  await expect(page.getByTestId('return-detail')).toContainText('108.9');
  release();
  await expect(page.getByTestId('return-HMKB-2026-05')).toContainText('—');
  await expect(page.getByTestId('return-detail')).not.toContainText('108.9');
  await expect(page.getByTestId('return-detail')).toContainText('Select a cell');
});

test('a carry-forward-only month remains missing and exposes the actual baseline age',async({page})=>{
  await page.route('**/api/price-history/HMKB?**',route=>route.fulfill({json:{ok:true,ticker:'HMKB',as_of:'2026-05-12',
    points:[...histories.HMKB.map(([date,close])=>({date,close})),{date:'2026-03-31',close:90,volume:0,value:0}],
  }}));
  await page.goto(url);
  await expect(page.getByTestId('return-HMKB-2026-03')).toContainText('—');
  await page.getByTestId('return-HMKB-2026-04').click();
  await expect(page.getByTestId('return-detail')).toContainText('2026-02-27');
  await expect(page.getByTestId('return-detail')).toContainText('Older baseline');
});

test('the last calendar day completes a monthly return',async({page})=>{
  await page.route('**/api/price-history/HMKB?**',route=>route.fulfill({json:{ok:true,ticker:'HMKB',as_of:'2026-04-30',
    points:histories.HMKB.map(([date,close])=>({date,close})),
  }}));
  await page.goto(url.replace('to=2026-05','to=2026-04'));
  await expect(page.getByTestId('return-HMKB-2026-04')).toContainText('+10%');
  await expect(page.getByTestId('return-HMKB-2026-04')).not.toContainText('*');
});
