import {test,expect} from '@playwright/test';

const companies=[{ticker:'HMKB',name:'Hamkorbank',family:'bank'},{ticker:'IPKY',name:'Ipak Yo‘li Bank',family:'bank'},{ticker:'SQBN',name:'SQB',family:'bank'}];
const histories={
  HMKB:[['2025-12-30',100],['2026-01-30',120],['2026-02-27',90],['2026-04-30',99],['2026-05-12',108.9]],
  IPKY:[['2025-12-30',200],['2026-01-30',220],['2026-02-27',242],['2026-04-30',240],['2026-05-12',250]],
  SQBN:[],
};
test.beforeEach(async({page})=>{
  await page.addInitScript(()=>{localStorage.setItem('uz_stock_analyzer_language','en');sessionStorage.setItem('uz_sponsor_seen','1');});
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url());
    if(url.pathname==='/api/company-comparison/options')return route.fulfill({json:{ok:true,companies,periods:[]}});
    if(url.pathname.startsWith('/api/price-history/')) {
      const ticker=url.pathname.split('/').pop();
      return route.fulfill({json:{ok:true,ticker,as_of:'2026-05-12',points:(histories[ticker]||[]).map(([date,close])=>({date,close})),adjustments:[]}});
    }
    return route.fulfill({json:{ok:true,user:null,companies:[],securities:{},stocks:[],items:[],stats:{}}});
  });
});
const url='/compare?view=returns&companies=HMKB,IPKY&from=2026-01&to=2026-05';
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
  const cell=page.getByTestId('return-HMKB-2026-01'); await cell.focus(); await cell.press('Enter');
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
  await page.setViewportSize({width:1440,height:1000});await page.goto(url);
  await expect(page.getByTestId('return-HMKB-2026-01')).toContainText('+20%');
  await expect(page.locator('html')).toHaveAttribute('data-theme',theme);
  await page.screenshot({path:info.outputPath(`returns-desktop-${theme}.png`),fullPage:true,animations:'disabled'});
  await page.getByRole('button',{name:'Relative',exact:true}).click();
  await page.screenshot({path:info.outputPath(`returns-ranking-${theme}.png`),fullPage:true,animations:'disabled'});
  await page.setViewportSize({width:390,height:844});
  await page.reload();await expect(page.getByTestId('return-HMKB-2026-01')).toContainText('+20%');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath(`returns-phone-${theme}.png`),fullPage:true,animations:'disabled'});
  expect(errors).toEqual([]);
});

for(const locale of [
  {lang:'ru',path:'/compare',heading:'Сравнение доходности',value:'+20%'},
  {lang:'uz',path:'/uz/compare',heading:'Daromadlilikni solishtirish',value:'+20%'},
]) test(`returns localizes labels and preserves its link (${locale.lang})`,async({page})=>{
  await page.addInitScript(lang=>localStorage.setItem('uz_stock_analyzer_language',lang),locale.lang);
  await page.goto(locale.path+url.slice(url.indexOf('?')));
  await expect(page.getByRole('heading',{name:locale.heading,exact:true})).toBeVisible();
  await expect(page.getByTestId('return-HMKB-2026-01')).toContainText(locale.value);
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
  await page.goto(url.replace('from=2026-01','from=2025-12'));
  const december=page.getByTestId('return-HMKB-2025-12');
  await expect(december).toBeVisible();
  const box=await december.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x+box.width).toBeLessThanOrEqual(390);
});

for(const [index,invalid] of [
  {ticker:undefined}, {ticker:'HMKBP'}, {as_of:undefined}, {as_of:'2026-02-31'},
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
