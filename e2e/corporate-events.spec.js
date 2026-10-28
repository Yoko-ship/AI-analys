import { readFileSync } from 'node:fs';
import { test, expect } from '@playwright/test';
const doc = (id, code, ticker, category, stage, priority) => ({
  id, source_url: `https://openinfo.uz/ru/facts/${code}/${id}`, code, tickers: [ticker], isins: ['UZ7011340005'],
  security_types: ['stock'],
  organization: ticker === 'HMKB' ? 'Hamkorbank' : 'O‘zbekgeofizika', category, stage, priority,
  title: { ru: stage === 'proposed' ? 'Набсовет рекомендовал дивиденды' : 'Компания утратила лицензию', en: 'Board recommended dividends', uz: 'Kuzatuv kengashi dividendlarni tavsiya qildi' },
  published_at: '2026-07-06T15:01:18', decision_date: '2026-06-22', confidence: 'confirmed',
  amounts: [{ security: 'ordinary', amount: 8.01 }, { security: 'preferred', amount: 71.5 }],
});
const a = doc('577', 41, 'UZGF', 'dividends', 'proposed', 1);
const b = {...doc('1', 23, 'HMKB', 'risks', 'disclosed', 0), amounts: []};
const payload = { ok: true, sources: { facts: { ok: true } },
  categories: { dividends: { ru: 'Дивиденды и выплаты' }, risks: { ru: 'Риски и лицензии' } },
  facts: { 41: { title: { ru: 'Набсовет рекомендовал дивиденды' } }, 23: { title: { ru: 'Компания утратила лицензию' } } },
  items: [a, b].map(d => ({ ...d, story_id: d.id, documents: [d], document_count: 1 })) };
async function setup(page) {
  const requested = [];
  await page.addInitScript(() => { sessionStorage.setItem('uz_sponsor_seen', '1'); localStorage.setItem('uz_stock_analyzer_token', 'test'); });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    requested.push(path);
    return route.fulfill({ json: path === '/api/news/corporate-events' ? payload
      : path === '/api/news' ? { ok: true, items: [{ type: 'report', ticker: 'TRSB', company: '"Trastbank" CHAKB', date: '2026-10-16', report_form: 'NSBU', year: 2026, quarter: 3 }] }
      : path === '/api/auth/me' ? { user: { id: 1, email: 'reader@example.test' } }
      : path === '/api/profile' ? { user: { id: 1, email: 'reader@example.test' }, favorites: [{ ticker: 'HMKB' }] }
      : { ok: true, items: [] } });
  });
  await page.goto('/news?tab=corporate');
  return requested;
}
test('corporate feed keeps search, stages, filters and source history in one feed', async ({ page }) => {
  const requested = await setup(page);
  const feed = page.getByTestId('corporate-events');
  await expect(feed.getByRole('heading', { name: 'Корпоративные события' })).toBeVisible();
  await expect(feed.getByText('OPENINFO · UZSTOCK', { exact: true })).toHaveCount(0);
  await expect(feed.getByText('Решения, предложения и выплаты — с отдельными датами и первоисточниками.', { exact: true })).toHaveCount(0);
  await expect(feed.locator('.ce-story')).toHaveCount(2);
  await expect(page.locator('.newsdesk-disclosures')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Лента событий по бумагам', exact: true })).toHaveCount(0);
  expect(requested).not.toContain('/api/news');
  await expect(feed.locator('.ce-story').getByRole('link', { name: /OpenInfo/ })).toHaveCount(0);
  await expect(feed.locator('.ce-story .ce-priority, .ce-story .ce-stage')).toHaveCount(0);
  await feed.getByLabel('Компания, тикер или ISIN').fill('UZ7011340005');
  await expect(feed.locator('.ce-story')).toHaveCount(2);
  await feed.getByLabel('Компания, тикер или ISIN').fill('UZGF');
  await expect(feed.locator('.ce-story')).toHaveCount(1);
  await feed.getByRole('button', { name: /Документы и история/ }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Предложение');
  await expect(dialog).toContainText('8,01');
  await expect(dialog).toContainText('71,5');
  await expect(dialog.getByRole('link', { name: /OpenInfo/ }).first()).toHaveAttribute('href', a.source_url);
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await feed.getByLabel('Компания, тикер или ISIN').fill('HMKB');
  await expect(feed.locator('.ce-story')).toHaveCount(1);
  await expect(feed.locator('.ce-story')).toContainText('Hamkorbank');
  await feed.getByLabel('Компания, тикер или ISIN').fill('UNKNOWN');
  await expect(feed.locator('.ce-story')).toHaveCount(0);
  await expect(feed).toContainText('По выбранным фильтрам событий нет.');
  await feed.getByText('Расширенные фильтры', { exact: true }).click();
  await feed.getByRole('button', { name: 'Сбросить фильтры' }).click();
  await expect(feed.locator('.ce-story')).toHaveCount(2);
  await expect(feed.getByLabel('Компания, тикер или ISIN')).toHaveValue('');
});
for (const width of [390, 1440]) test(`corporate feed uses the full width without category navigation at ${width}px in both themes`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 900 });
  await setup(page);
  const feed = page.getByTestId('corporate-events');
  for (const theme of ['light', 'dark']) {
    await page.evaluate(t => { document.documentElement.dataset.theme = document.body.dataset.theme = t; }, theme);
    await expect(feed.locator('.ce-story')).toHaveCount(2);
    await expect(feed.getByRole('group', { name: 'Корпоративные события', exact: true })).toHaveCount(0);
    await expect(feed.getByRole('button', { name: /^(Все события|Важное|Мои компании|Для вас)$/ })).toHaveCount(0);
    await expect(feed.getByRole('complementary', { name: 'Категории' })).toHaveCount(0);
    await expect(feed.getByRole('button', { name: /Все категории|Дивиденды и выплаты|Риски и лицензии/ })).toHaveCount(0);
    const feedBox = await feed.boundingBox();
    const streamBox = await feed.locator('.ce-stream').boundingBox();
    expect(Math.abs(streamBox.x - feedBox.x)).toBeLessThan(2);
    expect(Math.abs(streamBox.width - feedBox.width)).toBeLessThan(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`events-${width}-${theme}.png`), fullPage: true });
  }
});

test('stock filter retains non-payment disclosures for registered shares', async ({page}) => {
 await setup(page);
 await page.locator('.newsdesk-subtabs').getByRole('button', {name:'Акции',exact:true}).click();
 await expect(page.locator('.ce-story')).toHaveCount(2);
 await page.locator('.newsdesk-subtabs').getByRole('button', {name:'Облигации',exact:true}).click();
 await expect(page.locator('.ce-story')).toHaveCount(0);
});
test('payment totals and approved resolutions are explained separately from per-share amounts',async({page})=>{
 await setup(page);
 const paid={...a,stage:'paid',amounts:[],payment:{calculated:6060825,paid:6060825,debt:0,paid_percent:100,unit:'thousand_uzs'},summary:{ru:'Общие суммы в тысячах сум'},evidence:['Dividendlar to‘liq to‘langan'],record_date:null};
 await page.route('**/api/news/corporate-events?**',r=>r.fulfill({json:{...payload,items:[{...paid,story_id:paid.id,documents:[paid],document_count:1}]}}));
 await page.reload();await expect(page.locator('.ce-story')).toHaveCount(1);
 await page.locator('.ce-story').getByRole('button',{name:/Документы и история/}).click();
 await expect(page.getByRole('dialog')).toContainText('Выплачено');
 await expect(page.getByRole('dialog')).toContainText('тыс. сум');
 await expect(page.getByRole('dialog')).toContainText('6 060 825');
 await expect(page.getByRole('dialog')).toContainText('Dividendlar to‘liq to‘langan');
});

test('meeting documents distinguish publication from the date supported by source text', async ({ page }) => {
  await setup(page);
  const meeting = { ...b, id: '21404', source_url: 'https://openinfo.uz/ru/announce/21404',
    organization: 'Issiqlik Elektr Stansiyalari', stage: 'announced',
    title: {ru:'Объявлено собрание акционеров'}, published_at:'2026-10-02T17:33:06',
    event_date:'2026-10-23', decision_date:null, meeting_time:'11:00', date_source:'announcement_body',
    date_conflict:true, date_evidence:'2026-yil 23-oktabr kuni soat 11:00da yig‘ilishi bo‘lib o‘tishi ma’lum qilinadi.' };
  await page.route('**/api/news/corporate-events?**', r => r.fulfill({json:{...payload,items:[{...meeting,story_id:'21404',documents:[meeting],document_count:1}]}}));
  await page.reload();
  const card = page.locator('.ce-story');
  await expect(card.locator('time').first()).toHaveAttribute('datetime','2026-10-02T17:33:06');
  await card.getByRole('button',{name:/Документы/}).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('11:00');
  await expect(dialog).toContainText('Дата собрания взята из текста объявления');
  await expect(dialog.locator('.ce-date-evidence')).toContainText(meeting.date_evidence);
});

for (const prefix of ['', '/uz']) test(`corporate headlines open reloadable detail pages at ${prefix || '/'}`, async ({ page }, info) => {
  await page.setViewportSize({ width: prefix ? 390 : 1440, height: 900 });
  await setup(page);
  await page.route('**/api/news/corporate-events?**', route => {
    const query = new URL(route.request().url()).searchParams;
    const matching = query.get('start') === '2026-07-01' && query.get('end') === '2026-07-31';
    return route.fulfill({ json: { ...payload, items: matching ? payload.items : [] } });
  });
  await page.goto(`${prefix}/news?tab=corporate&instrument=stock&start=2026-07-01&end=2026-07-31`);
  await expect(page.locator('.newsdesk-subtabs')).toBeVisible();
  const card = page.locator('.ce-story').filter({ hasText: 'O‘zbekgeofizika' });
  const headline = card.getByRole('link', { name: prefix ? 'Kuzatuv kengashi dividendlarni tavsiya qildi' : a.title.ru, exact: true });
  await expect(headline).toHaveAttribute('href', /event=577/);
  const detailURL = await headline.getAttribute('href');
  await headline.click();
  await expect(page).toHaveURL(detailURL);
  const detail = page.getByTestId('corporate-event-detail');
  await expect(detail.getByRole('heading', { level: 1 })).toHaveText(prefix ? a.title.uz : a.title.ru);
  await expect(page.locator('.newsdesk-subtabs')).toHaveCount(0);
  await expect(detail).toContainText(prefix ? '8.01' : '8,01');
  await expect(detail.getByRole('link', { name: /OpenInfo/ }).first()).toHaveAttribute('href', a.source_url);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('.ce-story')).toHaveCount(0);
  await page.reload();
  await expect(detail).toContainText(prefix ? '71.5' : '71,5');
  await expect(page.locator('.newsdesk-subtabs')).toHaveCount(0);
  for (const theme of ['light', 'dark']) {
    await page.evaluate(t => { document.documentElement.dataset.theme = document.body.dataset.theme = t; }, theme);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`detail-${theme}.png`), fullPage: true });
  }
  await page.goBack();
  await expect(page.locator('.ce-story')).toHaveCount(2);
  await expect(page.locator('.newsdesk-subtabs')).toBeVisible();
  await expect(page).toHaveURL(/tab=corporate&instrument=stock&start=2026-07-01&end=2026-07-31$/);
  await page.goForward();
  await expect(detail).toBeVisible();
  await expect(page.locator('.newsdesk-subtabs')).toHaveCount(0);
  await detail.locator('.led-back').click();
  await expect(page.locator('.ce-story')).toHaveCount(2);
  await expect(page.locator('.newsdesk-subtabs')).toBeVisible();
  await expect(page).toHaveURL(/tab=corporate&instrument=stock$/);
});

test('a missing corporate detail has a clear state and a working return link', async ({ page }) => {
  await setup(page);
  await page.goto('/news?tab=corporate&event=missing&start=2026-07-01&end=2026-07-31');
  const detail = page.getByTestId('corporate-event-detail');
  await expect(detail).toContainText('Событие не найдено');
  await expect(page.locator('.newsdesk-subtabs')).toHaveCount(0);
  await detail.getByRole('link', { name: /К корпоративным новостям/ }).click();
  await expect(page.locator('.ce-story')).toHaveCount(2);
});


test('corporate instrument filter works after returning from detail', async ({ page }) => {
  await setup(page);
  await page.locator('.ce-story').filter({hasText:'O‘zbekgeofizika'}).getByRole('link',{name:a.title.ru,exact:true}).click();
  await expect(page.getByTestId('corporate-event-detail')).toBeVisible();
  await page.getByTestId('corporate-event-detail').locator('.led-back').click();
  await page.locator('.newsdesk-subtabs').getByRole('button',{name:'Акции',exact:true}).click();
  await expect(page.getByTestId('corporate-event-detail')).toHaveCount(0);
  await expect(page.locator('.ce-story')).toHaveCount(2);
});


const photo = '/news-fixtures/disclosure-photo.png';
async function setupEditorial(page, { brokenPhoto = false, brokenLogo = false } = {}) {
  await setup(page);
  await page.route('**/api/securities', r => r.fulfill({json:{ok:true,securities:{
    UZGF:{name:'O‘zbekgeofizika',logo_url:'/logos/UZGFP.svg'},
    HMKB:{name:'Hamkorbank',logo_url:'/logos/HMKB_MARK.png'},
  }}}));
  await page.route('**/logos/UZGFP.svg', r => brokenLogo ? r.abort() : r.fulfill({contentType:'image/svg+xml',body:readFileSync(new URL('../logos/UZGFP.svg',import.meta.url))}));
  await page.route('**/logos/HMKB_MARK.png', r => r.fulfill({contentType:'image/png',body:readFileSync(new URL('../logos/HMKB_MARK.png',import.meta.url))}));
  await page.route(`**${photo}`, r => brokenPhoto ? r.abort() : r.fulfill({contentType:'image/png',body:readFileSync(new URL('../logos/HMKB.png',import.meta.url))}));
  const withPhoto = {...b, image_url:photo, summary:{ru:'Эмитент раскрыл сведения о прекращении действия лицензии.',uz:'Emitent litsenziya bekor qilinganini oshkor qildi.'}};
  const unknown = {...b,id:'unknown',story_id:'unknown',organization:'Новый эмитент',tickers:[],image_url:null,title:{ru:'Изменились контакты компании'},documents:[]};
  await page.route('**/api/news/corporate-events?**',r=>r.fulfill({json:{...payload,items:[
    {...a,story_id:a.id,documents:[a],document_count:1},
    {...withPhoto,story_id:b.id,documents:[withPhoto],document_count:1},
    {...unknown,documents:[unknown],document_count:1},
  ]}}));
  await page.reload();
}

for (const width of [390,1440]) test(`corporate news uses issuer imagery and editorial detail at ${width}px`, async ({page},info) => {
  await page.setViewportSize({width,height:950});
  await setupEditorial(page);
  const logoCard=page.locator('.ce-story').filter({hasText:'O‘zbekgeofizika'});
  const photoCard=page.locator('.ce-story').filter({hasText:'Hamkorbank'});
  await expect(logoCard.locator('.ce-story-media img')).toHaveAttribute('src','/logos/UZGFP.svg');
  await expect(photoCard.locator('.ce-story-media img')).toHaveAttribute('src',photo);
  await expect(page.locator('.ce-story').filter({hasText:'Новый эмитент'}).locator('.chip-logo-fallback')).toBeVisible();
  for(const theme of ['light','dark']) {
    await page.evaluate(t=>{document.documentElement.dataset.theme=document.body.dataset.theme=t;},theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`editorial-feed-${theme}.png`),fullPage:true,animations:'disabled'});
  }
  await photoCard.getByRole('link',{name:b.title.ru,exact:true}).click();
  const detail=page.getByTestId('corporate-event-detail');
  await expect(page.getByRole('heading',{level:1})).toHaveCount(1);
  await expect(detail.getByRole('complementary')).toHaveCount(0);
  await expect(detail.getByRole('navigation', {name:'Документы раскрытия'})).toHaveCount(0);
  await expect(detail.getByText(/Краткое изложение UZStock/)).toHaveCount(0);
  const detailBox = await detail.boundingBox();
  const articleBox = await detail.locator('.ce-article').boundingBox();
  const pageBox = await page.locator('.news-view').boundingBox();
  const pagePadding = await page.locator('.news-view').evaluate(el => {
    const style = getComputedStyle(el);
    return {left:parseFloat(style.paddingLeft),right:parseFloat(style.paddingRight)};
  });
  expect(Math.abs(detailBox.x - pageBox.x - pagePadding.left)).toBeLessThan(2);
  expect(Math.abs(detailBox.width - (pageBox.width - pagePadding.left - pagePadding.right))).toBeLessThan(2);
  expect(Math.abs(articleBox.width - detailBox.width)).toBeLessThan(2);
  const articleHeader = await detail.locator('.ce-article-header').boundingBox();
  const articleTitle = await detail.getByRole('heading', {level:1}).boundingBox();
  expect(Math.abs(articleTitle.width - articleHeader.width)).toBeLessThan(2);
  await expect(detail.locator('.ce-article-photo img')).toHaveAttribute('src',photo);
  await expect.poll(()=>detail.locator('.ce-article-photo img').evaluate(img=>img.naturalWidth)).toBeGreaterThan(0);
  expect(await detail.locator('.ce-article-photo img').evaluate(img=>img.getBoundingClientRect().width <= img.naturalWidth)).toBe(true);
  await expect(detail.locator('.ce-article-issuer img')).toHaveAttribute('src','/logos/HMKB_MARK.png');
  await expect(detail).toContainText('Эмитент раскрыл сведения');
  await expect(page.locator('.newsdesk-disclosures')).toHaveCount(0);
  await expect(detail.getByRole('link',{name:/Первоисточник OpenInfo/}).first()).toHaveAttribute('href',b.source_url);
  for(const theme of ['light','dark']) {
    await page.evaluate(t=>{document.documentElement.dataset.theme=document.body.dataset.theme=t;},theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`editorial-detail-${theme}.png`),fullPage:true,animations:'disabled'});
  }
  await detail.locator('.led-back').click();
  await logoCard.getByRole('link',{name:a.title.ru,exact:true}).click();
  await expect(detail.locator('.ce-article-issuer img')).toHaveAttribute('src','/logos/UZGFP.svg');
  await expect(detail.locator('.ce-article-photo')).toHaveCount(0);
  await expect(detail).toContainText('Предложение не означает утверждённую выплату');
});

test('failed corporate images fall back to issuer identity without hiding the story', async ({page})=>{
  await setupEditorial(page,{brokenPhoto:true,brokenLogo:true});
  const logoCard=page.locator('.ce-story').filter({hasText:'O‘zbekgeofizika'});
  const photoCard=page.locator('.ce-story').filter({hasText:'Hamkorbank'});
  await expect(logoCard.locator('.ce-story-media .chip-logo-fallback')).toBeVisible();
  await expect(photoCard.locator('.ce-story-media img')).toHaveAttribute('src','/logos/HMKB_MARK.png');
  await logoCard.getByRole('link',{name:a.title.ru,exact:true}).click();
  const detail=page.getByTestId('corporate-event-detail');
  await expect(detail.locator('.ce-article-issuer .chip-logo-fallback')).toBeVisible();
  await expect(detail).toContainText('8,01');
});
