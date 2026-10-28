import { test, expect } from '@playwright/test';

// Phone layout of the shell and the quotes board, as measured on prod at 390px
// (2026-10-10): the topbar ran 25px off the right edge once «Войти» joined it,
// the «Колонки» label spilled out of its icon box, the period chips folded into
// two ragged rows and the ticker cell (a flex <td>) stopped matching its row.

async function mockBoard(page, theme = 'dark') {
  const stocks = Array.from({ length: 12 }, (_, i) => ({
    ticker: `TST${i}`, name: `Test company ${i}`, isin: `UZ00000000${i}`, type: 'stock',
    share_type: i % 3 ? 'ordinary' : 'preferred', price: 1000 + i, last_price: 1000 + i,
    change: 10, changePercent: 1, volume: 100000,
  }));
  const securities = Object.fromEntries(stocks.map((s,i) => [s.ticker, { ...s, sector: i % 2 ? 'finance' : 'manufacturing', security_type: 'stock' }]));
  await page.route('**/api/**', route => {
    const p = new URL(route.request().url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, json: body });
    if (p === '/api/securities') return json({ ok: true, securities });
    if (p === '/api/market/stocks') return json({ ok: true, stocks });
    if (p === '/api/auth/me') return json({ user: null }, 401);
    return json({});
  });
  await page.addInitScript((t) => { try { sessionStorage.setItem('uz_sponsor_seen', '1'); localStorage.setItem('uz_stock_analyzer_theme', t); } catch (e) { /* ignore */ } }, theme);
}

// The light theme is its own case: its select brought back the native arrow.
for (const [width, theme] of [[320, 'dark'], [360, 'dark'], [390, 'dark'], [390, 'light']]) {
  test(`phone shell and board fit ${width}px (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await mockBoard(page, theme);
    await page.goto('/market');
    await expect(page.locator('.market-table-wrap tbody tr').first()).toBeVisible();

    // Every visible topbar control lies inside the screen.
    const overhang = await page.evaluate(() => [...document.querySelectorAll('.topbar > *, .topbar-controls > *')]
      .map(el => el.getBoundingClientRect())
      .filter(r => r.width > 0 && r.right > 0)
      .filter(r => r.left < 0 || r.right > document.documentElement.clientWidth).length);
    expect(overhang).toBe(0);
    if (width >= 360) expect((await page.locator('.topbar-brand').boundingBox()).width).toBeGreaterThanOrEqual(30);
    await expect(page.locator('.theme-toggle')).toBeInViewport({ ratio: 1 });

    // Toolbar buttons are icon-only on a phone.
    await page.getByText('Фильтры и инструменты',{exact:true}).click();
    const colsBox = await page.locator('.market-cols-btn').boundingBox();
    expect(colsBox.width).toBeLessThanOrEqual(40);
    await expect(page.locator('.market-cols-btn .market-btn-label')).toBeHidden();

    // The period chips stay on one line.
    const tops = await page.locator('.market-period-control button').evaluateAll(bs => bs.map(b => Math.round(b.getBoundingClientRect().top)));
    expect(new Set(tops).size).toBe(1);

    // The pinned ticker cell is as tall as its row.
    const [rowH, cellH] = await page.locator('.market-table-wrap tbody tr').first().evaluate(r => [r.getBoundingClientRect().height, r.cells[0].getBoundingClientRect().height]);
    expect(Math.abs(rowH - cellH)).toBeLessThanOrEqual(1);
  });
}

test('phone drawer carries the text-size control', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockBoard(page);
  await page.goto('/market');
  await expect(page.locator('.topbar-controls .topbar-textsize')).toBeHidden();
  await page.locator('.topbar-burger').click();
  const drawerSize = page.locator('.topbar-nav-textsize');
  await expect(drawerSize).toBeVisible();
  await drawerSize.getByRole('button', { name: 'Увеличить шрифт' }).click();
  await expect(drawerSize.locator('.topbar-textsize-now')).not.toHaveText('100%');
  await drawerSize.locator('.topbar-textsize-now').click();
  await expect(drawerSize.locator('.topbar-textsize-now')).toHaveText('100%');
});

test('audit: closed phone drawer cannot receive focus and open drawer contains it', async ({page}) => {
  await page.setViewportSize({width:390,height:844});
  await mockBoard(page);
  await page.goto('/market');
  const burger=page.locator('.topbar-burger');
  await burger.focus();
  await page.keyboard.press('Tab');
  expect(await page.evaluate(()=>Boolean(document.activeElement.closest('.topbar-nav')))).toBe(false);
  await burger.click();
  await expect(page.locator('.topbar-nav').getByRole('button',{name:'Главная',exact:true})).toBeFocused();
  for(let i=0;i<15;i++) {
    await page.keyboard.press('Tab');
    expect(await page.evaluate(()=>Boolean(document.activeElement.closest('.topbar-nav')) || document.activeElement.matches('.topbar-burger'))).toBe(true);
  }
  await page.keyboard.press('Escape');
  await expect(burger).toHaveAttribute('aria-expanded','false');
  await expect(burger).toBeFocused();
  await page.setViewportSize({width:1440,height:1000});
  await expect(page.locator('.topbar-nav').getByRole('button',{name:'Главная',exact:true})).toBeVisible();
});

test('audit: phone empty feedback stays visible and filtered results can be reset', async ({page}) => {
  await page.setViewportSize({width:390,height:844});
  await mockBoard(page,'light');
  await page.goto('/market');
  await page.getByRole('searchbox',{name:'Поиск по тикеру или компании'}).fill('missing-issuer');
  const feedback=page.locator('.market-empty-cell');
  await expect(feedback).toContainText('Нет данных');
  const rect=await feedback.evaluate(el=>{const range=document.createRange();range.selectNodeContents(el);const r=range.getBoundingClientRect();return {left:r.left,right:r.right};});
  expect(rect.left).toBeGreaterThanOrEqual(0);
  expect(rect.right).toBeLessThanOrEqual(390);
  await page.getByRole('button',{name:'Сбросить фильтры',exact:true}).click();
  await expect(page.locator('.market-table-wrap tbody tr')).toHaveCount(12);
});

test('audit: phone quotes lead secondary tools and filters remain usable', async ({page},info) => {
  await page.setViewportSize({width:390,height:844});
  await mockBoard(page,'light');
  await page.goto('/market');
  const first=page.locator('.market-table-wrap tbody tr').first();
  await expect(first).toBeVisible();
  expect((await first.boundingBox()).y).toBeLessThan(480);
  await page.getByText('Фильтры и инструменты',{exact:true}).click();
  await expect(page.getByLabel('Отрасль',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Привилегированные',exact:true}).click();
  await expect(page.locator('.market-table-wrap tbody tr')).toHaveCount(4);
  await page.screenshot({path:info.outputPath('market-phone-fixed.png'),fullPage:true});
});

for(const theme of ['light','dark']) test(`audit: gain and loss text have readable contrast (${theme})`,async({page})=>{
  await mockBoard(page,theme);
  await page.route('**/api/market/stocks?**',route=>route.fulfill({json:{stocks:[
    {ticker:'UZPN',name:'O\'zpartamponaj',last_price:3926.7,close_price:3272.25,volume:3927,last_trade_date:'2026-10-28'},
    {ticker:'UNVB',name:'Universal bank',last_price:8314,close_price:10392,volume:44143645,last_trade_date:'2026-10-28'},
  ]}}));
  await page.goto('/market');
  for(const tone of ['good','danger']){
    const badge=page.locator(`.market-change-badge.tone-${tone}`).first();
    await expect(badge).toBeVisible();
    const ratio=await badge.evaluate(el=>{
      const ctx=document.createElement('canvas').getContext('2d');ctx.canvas.width=ctx.canvas.height=1;
      const rgb=c=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=c;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data].map((v,i)=>i===3?v/255:v);};
      const blend=(fg,bg)=>fg.slice(0,3).map((v,i)=>v*fg[3]+bg[i]*(1-fg[3])).concat(1);
      const colors=[];for(let node=el;node;node=node.parentElement)colors.unshift(rgb(getComputedStyle(node).backgroundColor));
      const bg=colors.reduce((base,c)=>blend(c,base),[255,255,255,1]);
      const luminance=c=>c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
      const a=luminance(blend(rgb(getComputedStyle(el).color),bg)),b=luminance(bg);
      return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
    });
    expect(ratio).toBeGreaterThanOrEqual(4.5);
  }
});

test('audit: market help and column actions have usable targets',async({page})=>{
  await page.setViewportSize({width:390,height:844});await mockBoard(page);await page.goto('/market');
  for(const selector of ['.term-info-btn','.market-th-menu-btn']){
    const box=await page.locator(selector).first().boundingBox();
    expect(box.width).toBeGreaterThanOrEqual(24);expect(box.height).toBeGreaterThanOrEqual(40);
  }
});

for(const width of [320,360,390]) test(`phone quote values remain fully visible beside the ticker at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:844});await mockBoard(page,'light');
  await page.route('**/api/market/stocks?**',route=>route.fulfill({json:{stocks:[
    {ticker:'UZPN',name:"O'zpartamponaj",share_type:'ordinary',last_price:3926.7,volume:3927},
    {ticker:'BNGPP',name:'Buxoroneftgazparmalash',share_type:'preferred',last_price:100000,volume:5007554},
    {ticker:'UTYK',name:"O'ZTEMIRYOLKONTEYNER",share_type:'ordinary',last_price:450000,volume:90409072},
  ]}}));
  await page.goto('/market');
  await expect(page.locator('.market-table-wrap tbody tr')).toHaveCount(3);
  await expect(page.locator('.market-table-wrap tbody tr').filter({hasText:'BNGPP'}).locator('.market-share-short')).toHaveText('прив.');
  for(const row of await page.locator('.market-table-wrap tbody tr').all()){
    const quote=await row.locator('td.num').first().evaluate(el=>{const range=document.createRange();range.selectNodeContents(el);const r=range.getBoundingClientRect();return {left:r.left,right:r.right};});
    const ticker=await row.locator('td').first().boundingBox();
    expect(quote.left).toBeGreaterThanOrEqual(ticker.x+ticker.width);
    expect(quote.right).toBeLessThanOrEqual(width-14);
  }
});
