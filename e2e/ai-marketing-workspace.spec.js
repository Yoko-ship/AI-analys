import { test, expect } from '@playwright/test';
import { workspace } from './helpers/marketing-workspace.js';
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';

test.afterEach(async ({}, info) => {
  if (!existsSync(info.outputPath('marketing.website-fixture.json'))) return;
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  execFileSync(python, ['-X', 'utf8', 'e2e/helpers/marketing-api.py', info.outputPath('marketing.sqlite3'), JSON.stringify({ method: 'WEBSITE_CLEANUP' })],
    { encoding: 'utf8', env: { ...process.env, PYTHONPATH: process.cwd() } });
});

for (const width of [1440, 390]) for (const format of ['image', 'carousel', 'video', 'story']) test(`Instagram ${format} processing and verified publication at ${width}px`, async ({ page }, info) => {
  test.setTimeout(120000);
  await page.setViewportSize({ width, height: 950 });
  const callApi = await workspace(page, info);
  const stamp = Date.now(), base = '/api/admin/ai-marketing', expires = new Date(stamp + 86400000).toISOString();
  callApi({ method: 'META_CONFIGURE' });
  expect(callApi({ method: 'PUT', path: `${base}/accounts/instagram`, body: { expected_version: 0, data: {
    platform: 'instagram', label: 'Instagram UZStock', external_id: '46801', mode: 'manual', formats: [format], rubrics: ['news'],
    languages: ['ru'], valid_until: expires, window_start: '00:00', window_end: '23:59', instagram_link_ready: true,
  } } }).status).toBe(200);
  const login = callApi({ method: 'POST', path: `${base}/accounts/instagram/meta/start`, body: { expected_version: 1 } });
  const selection = callApi({ method: 'POST', path: `${base}/oauth/meta/finish`, cookie: login.headers['set-cookie'].split(';')[0],
    body: { state: new URL(login.body.authorization_url).searchParams.get('state'), code: 'synthetic-instagram-login' } });
  expect(callApi({ method: 'POST', path: `${base}/accounts/instagram/meta/select`, body: {
    expected_version: 1, selection_id: selection.body.selection.selection_id, target_id: '46801',
  } }).status).toBe(200);
  callApi({ method: 'PUT', path: `${base}/evidence/release`, body: { expected_version: 0, data: {
    title: 'Сравнение компаний', url: 'https://uzstock.uz/news/comparison', publisher: 'UZStock', entity: '',
    published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(), expires_at: expires,
    excerpt: 'Доступно сравнение компаний.', rights: 'owned', status: 'verified', data: { feature: 'Сравнение компаний' },
  } } });
  expect(callApi({ method: 'POST', path: `${base}/candidates`, body: {
    event_id: `instagram-${format}`, account_id: 'instagram', mode: 'manual', rubric: 'news', language: 'ru', format,
    title: 'Сравнение компаний в Instagram', body: 'Доступно сравнение компаний. Какие показатели вы сопоставляете?', evidence_ids: ['release'],
    claims: [{ evidence_id: 'release', field: 'feature', value: 'Сравнение компаний', unit: '' }],
    destination_url: 'https://uzstock.uz/news/comparison', expires_at: expires,
  } }).status).toBe(200);
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Сравнение компаний в Instagram', exact: true }) })
    .filter({ has: page.getByRole('button', { name: 'Текст для отправки', exact: true }) });
  const profileLink = ['image', 'story'].includes(format);
  if (profileLink) {
    await card.getByRole('button', { name: 'Изменить материал', exact: true }).click();
    await page.getByRole('dialog').getByLabel('Переход из Instagram', { exact: true }).selectOption('profile');
    await expect(page.getByRole('dialog')).toContainText('должна вести на точную ссылку этого материала');
    await page.getByRole('dialog').getByRole('button', { name: 'Сохранить материал', exact: true }).click();
    await expect(card).toContainText('Переход через профиль · проверка перед отправкой');
  }
  await expect(card).toContainText(format === 'story' ? 'Story Instagram · текст в изображении' : format === 'video' ? 'Reel Instagram · с отметкой об использовании ИИ' : 'Instagram · с отметкой об использовании ИИ');
  if (profileLink) {
    await card.getByRole('button', { name: 'Текст для отправки', exact: true }).click();
    await expect(page.getByRole('dialog').getByRole('link', { name: 'Ссылка для профиля Instagram ↗', exact: true })).toHaveAttribute('href', 'https://uzstock.uz/news/comparison');
    if (format === 'story') {
      await expect(page.getByRole('dialog')).toContainText('Отправляется готовое изображение с текстом');
      await expect(page.getByRole('dialog')).toContainText('Ссылка-стикер и отдельная подпись не добавляются');
    } else await expect(page.getByRole('dialog')).toContainText('Подробнее — по ссылке в профиле.');
    await page.keyboard.press('Escape');
  }
  await card.getByRole('button', { name: 'Создать медиа', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Начать рендер', exact: true }).click();
  callApi({ method: 'RENDER_STEP' });
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  await card.getByRole('button', { name: 'Открыть медиа', exact: true }).click();
  const mediaPreview = format === 'video' ? page.getByRole('dialog').locator('video') : page.getByRole('dialog').getByRole('img').first();
  await expect(mediaPreview).toHaveJSProperty(format === 'video' ? 'videoWidth' : 'naturalWidth', 1080);
  await expect(mediaPreview).toHaveAttribute(format === 'video' ? 'aria-label' : 'alt', /Факт:/);
  await expect(mediaPreview).not.toHaveAttribute(format === 'video' ? 'aria-label' : 'alt', /feature:/);
  if (profileLink) await expect(mediaPreview).toHaveAttribute('alt', /Подробнее — по ссылке в профиле/);
  await mediaPreview.screenshot({ path: info.outputPath(`marketing-instagram-preview-${format}-${width}.png`) });
  await page.keyboard.press('Escape');
  await card.getByRole('button', { name: 'Проверить факты', exact: true }).click();
  await card.getByRole('button', { name: 'Утвердить эту версию', exact: true }).click();
  await card.getByRole('button', { name: 'Поставить в очередь', exact: true }).click();
  let started = Date.now();
  if (format === 'image' && width === 390) {
    const stopped = callApi({ method: 'DISPATCH_INSTAGRAM', at: new Date(started).toISOString(), profile_url: 'https://uzstock.uz/' }).body;
    expect(stopped.requests.some(value => value.startsWith('POST '))).toBe(false);
    await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
    await expect(card).toContainText('Ссылка в профиле Instagram не совпадает');
    await card.getByRole('button', { name: 'Проверить факты', exact: true }).click();
    await card.getByRole('button', { name: 'Утвердить эту версию', exact: true }).click();
    await expect(card.getByRole('button', { name: 'Поставить в очередь', exact: true })).toBeVisible();
    await card.getByRole('button', { name: 'Поставить в очередь', exact: true }).click();
    started = Date.now();
  }
  expect(callApi({ method: 'DISPATCH_INSTAGRAM', at: new Date(started).toISOString(), processing: 'IN_PROGRESS', profile_url: 'https://uzstock.uz/news/comparison' }).body.delivery_work).toBe(true);
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  await card.getByText('Загрузка медиа в Instagram', { exact: true }).click();
  await expect(card).toContainText('Instagram обрабатывает медиа');
  await page.reload();
  const resumed = callApi({ method: 'DISPATCH_INSTAGRAM', at: new Date(started + 61000).toISOString(), profile_url: 'https://uzstock.uz/news/comparison' }).body;
  expect(resumed.requests.filter(value => value === 'POST /v25.0/46801/media_publish')).toHaveLength(1);
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  await expect(card).toContainText('Принято площадкой');
  await expect(card).toContainText('Instagram проверяет видимость');
  if (profileLink) await expect(card).toContainText('Ссылка профиля проверена перед отправкой');
  callApi({ method: 'DISPATCH_INSTAGRAM', at: new Date(started + 121000).toISOString(), hidden: true });
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  await expect(card).toContainText('Повторная отправка не выполняется');
  await page.reload();
  if (format === 'story' && width === 390) {
    const expired = callApi({ method: 'DISPATCH_INSTAGRAM', at: new Date(started + 25 * 3600000).toISOString() }).body;
    expect(expired.confirmation_work).toBe(true);
    expect(expired.requests.some(value => value.startsWith('POST '))).toBe(false);
    await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
    await expect(card).toContainText('Срок проверки Story истёк');
    await expect(card).toContainText('Видимость не подтверждена');
    await expect(card).not.toContainText('Следующая:');
    await card.getByText('Срок проверки Story истёк', { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath('marketing-instagram-story-unverified-390.png'), fullPage: false });
    expect(callApi({ method: 'DISPATCH_INSTAGRAM', at: new Date(started + 26 * 3600000).toISOString() }).body.confirmation_work).toBe(false);
    return;
  }
  const confirmed = callApi({ method: 'DISPATCH_INSTAGRAM', at: new Date(started + 182000).toISOString() }).body;
  expect(confirmed.confirmation_work).toBe(true);
  expect(confirmed.requests.some(value => value.startsWith('POST '))).toBe(false);
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  await expect(card).toContainText('Опубликован');
  await expect(card).toContainText(format === 'story' ? 'Instagram подтвердил Story в выбранном аккаунте' : 'Instagram подтвердил аккаунт, текст и состав медиа');
  await expect(card.getByRole('link', { name: 'Открыть публикацию ↗' })).toHaveAttribute('href', format === 'story' ? 'https://www.instagram.com/stories/uzstock_test/456789/' : `https://www.instagram.com/${format === 'video' ? 'reel' : 'p'}/Checked_Post/`);
  if (format === 'story') await expect(card).toContainText('Срок показа — до');
  await card.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath(`marketing-instagram-${format}-${width}.png`), fullPage: false });
  await page.reload();
  await expect(card).toContainText('Опубликован');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

for (const width of [1440, 390]) for (const format of ['post', 'image', 'carousel', 'video']) test(`Facebook ${format} upload and independent visibility confirmation at ${width}px`, async ({ page }, info) => {
  test.setTimeout(120000);
  await page.setViewportSize({ width, height: 950 });
  const callApi = await workspace(page, info);
  const stamp = Date.now(), base = '/api/admin/ai-marketing', expires = new Date(stamp + 86400000).toISOString();
  const video = format === 'video', lostFinish = video && width === 390;
  callApi({ method: 'META_CONFIGURE' });
  expect(callApi({ method: 'PUT', path: `${base}/accounts/facebook`, body: { expected_version: 0, data: {
    platform: 'facebook', label: 'Facebook UZStock', external_id: '35790', mode: 'manual', formats: [format], rubrics: ['news'],
    languages: ['ru'], valid_until: expires, window_start: '00:00', window_end: '23:59',
  } } }).status).toBe(200);
  const login = callApi({ method: 'POST', path: `${base}/accounts/facebook/meta/start`, body: { expected_version: 1 } });
  const selection = callApi({ method: 'POST', path: `${base}/oauth/meta/finish`, cookie: login.headers['set-cookie'].split(';')[0],
    body: { state: new URL(login.body.authorization_url).searchParams.get('state'), code: 'synthetic-facebook-login' } });
  expect(callApi({ method: 'POST', path: `${base}/accounts/facebook/meta/select`, body: {
    expected_version: 1, selection_id: selection.body.selection.selection_id, target_id: '35790',
  } }).status).toBe(200);
  if (video) {
    await page.getByRole('button', { name: 'Настройки', exact: true }).click();
    await page.getByRole('button', { name: 'Обновить подключения', exact: true }).click();
    await page.getByRole('button', { name: 'Настроить Facebook UZStock', exact: true }).click();
    const form = page.locator('#account-facebook form');
    await expect(form.getByLabel('Видео · общедоступный Reel с отметкой ИИ', { exact: true })).toBeChecked();
    await expect(form).toContainText('Аудитория Reels: все');
  }
  callApi({ method: 'PUT', path: `${base}/evidence/release`, body: { expected_version: 0, data: {
    title: 'Сравнение компаний', url: 'https://uzstock.uz/news/comparison', publisher: 'UZStock', entity: '',
    published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(), expires_at: expires,
    excerpt: 'Доступно сравнение компаний.', rights: 'owned', status: 'verified', data: { feature: 'Сравнение компаний' },
  } } });
  expect(callApi({ method: 'POST', path: `${base}/candidates`, body: {
    event_id: `facebook-media-${format}`, account_id: 'facebook', mode: 'manual', rubric: 'news', language: 'ru', format,
    title: 'Сравнение компаний в Facebook', body: 'Доступно сравнение компаний. Какие показатели вы сопоставляете?', evidence_ids: ['release'],
    claims: [{ evidence_id: 'release', field: 'feature', value: 'Сравнение компаний', unit: '' }],
    destination_url: 'https://uzstock.uz/news/comparison', expires_at: expires,
  } }).status).toBe(200);
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Сравнение компаний в Facebook', exact: true }) })
    .filter({ has: page.getByRole('button', { name: 'Текст для отправки', exact: true }) });
  if (video) await expect(card).toContainText('Общедоступный Reel · с отметкой об использовании ИИ');
  if (format !== 'post') {
    await card.getByRole('button', { name: 'Создать медиа', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Начать рендер', exact: true }).click();
    callApi({ method: 'RENDER_STEP' });
    await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  }
  await card.getByRole('button', { name: 'Проверить факты', exact: true }).click();
  await card.getByRole('button', { name: 'Утвердить эту версию', exact: true }).click();
  await card.getByRole('button', { name: 'Поставить в очередь', exact: true }).click();
  let started = Date.now();
  const sent = callApi({ method: 'DISPATCH_FACEBOOK', at: new Date(started).toISOString(), processing: video ? 'in_progress' : 'completed' }).body;
  if (video) {
    expect(sent.reel_finishes).toBe(0);
    await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
    await card.getByText('Загрузка медиа в Facebook', { exact: true }).click();
    await expect(card).toContainText('Facebook обрабатывает видео');
    await page.reload();
    started += 61000;
    const resumed = callApi({ method: 'DISPATCH_FACEBOOK', at: new Date(started).toISOString(), lose_finish: lostFinish }).body;
    expect(resumed.reel_finishes).toBe(1);
    expect(resumed.requests.some(value => value.includes('/video-upload/'))).toBe(false);
  } else expect(sent.requests.filter(value => value === 'POST /v25.0/35790/feed')).toHaveLength(1);
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  await expect(card).toContainText(lostFinish ? 'Исход неясен' : 'Принято площадкой');
  await expect(card).toContainText(lostFinish ? 'Сверяем исход отправки Reel' : 'Facebook проверяет видимость');
  if (!lostFinish) await expect(card.getByRole('link', { name: 'Открыть публикацию ↗', exact: true })).toHaveAttribute('href', video ? 'https://www.facebook.com/reel/567890/' : 'https://www.facebook.com/35790/posts/78901/');
  await expect(card.getByRole('button', { name: 'Изменить материал', exact: true })).toHaveCount(0);
  if (format !== 'post') {
    await card.getByText('Загрузка медиа в Facebook', { exact: true }).click();
    await expect(card).toContainText(video ? 'Медиа готово' : 'Файл загружен');
  }
  const hidden = callApi({ method: 'DISPATCH_FACEBOOK', at: new Date(started + 60000).toISOString(), hidden: true }).body;
  expect(hidden.confirmation_work).toBe(true);
  expect(hidden.requests.some(value => value.startsWith('POST '))).toBe(false);
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  await expect(card).toContainText(lostFinish ? 'Исход неясен' : 'Принято площадкой');
  await expect(card).toContainText('Повторная отправка не выполняется');
  const nextCheck = callApi({ method: 'GET', path: `${base}/workspace` }).body.deliveries[0].confirmation.next_check_at;
  const localNext = new Date(nextCheck).toLocaleString('ru-RU', { timeZone: 'Asia/Tashkent', dateStyle: 'short', timeStyle: 'short' });
  await expect(card.locator(`time[datetime="${nextCheck}"]`)).toHaveText(localNext);
  await expect(card).toContainText('Время Ташкента');
  if (format === 'carousel' || video) {
    await card.getByText(lostFinish ? 'Сверяем исход отправки Reel' : 'Facebook проверяет видимость', { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(`marketing-facebook-pending-${width}.png`), fullPage: false });
  }
  await page.reload();
  const confirmed = callApi({ method: 'DISPATCH_FACEBOOK', at: new Date(started + 121000).toISOString() }).body;
  expect(confirmed.confirmation_work).toBe(true);
  expect(confirmed.requests.some(value => value.startsWith('POST '))).toBe(false);
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  await expect(card).toContainText('Опубликован');
  await expect(card).toContainText('Facebook подтвердил страницу, текст и медиа');
  await card.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath(`marketing-facebook-${format}-${width}.png`), fullPage: false });
  await page.reload();
  await expect(card).toContainText('Опубликован');
  expect(callApi({ method: 'DISPATCH_FACEBOOK', at: new Date(started + 3600000).toISOString() }).body.delivery_work).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

for (const width of [1440, 390]) for (const platform of ['facebook', 'instagram']) test(`Meta ${platform} login requires an explicit account choice at ${width}px`, async ({ page }, info) => {
  test.setTimeout(120000);
  await page.setViewportSize({ width, height: 950 });
  const callApi = await workspace(page, info);
  const label = platform === 'facebook' ? 'Facebook UZStock' : 'Instagram UZStock';
  const identifier = platform === 'facebook' ? '35790' : '46801';
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  const panel = page.getByRole('region', { name: `Подключение ${label}`, exact: true });
  await expect(panel.getByRole('button', { name: 'Войти через Meta', exact: true })).toBeDisabled();
  await expect(panel).toContainText('MARKETING_META_APP_ID');
  await page.getByRole('button', { name: `Настроить ${label}`, exact: true }).click();
  await page.locator(`#account-${platform} form`).getByRole('button', { name: 'Сохранить правила аккаунта' }).click();
  callApi({ method: 'META_CONFIGURE' });
  await page.getByRole('button', { name: 'Обновить подключения' }).click();
  await expect(panel.getByRole('button', { name: 'Войти через Meta', exact: true })).toBeEnabled();
  const origin = new URL(page.url()).origin;
  await page.route('https://www.facebook.com/v25.0/dialog/oauth?**', async route => {
    const url = new URL(route.request().url());
    expect(url.searchParams.get('config_id')).toBe(platform === 'facebook' ? '11111' : '22222');
    expect(url.searchParams.has('scope')).toBe(false);
    const callback = new URL('/admin/ai-marketing', origin);
    callback.searchParams.set('state', url.searchParams.get('state'));
    callback.searchParams.set('code', 'synthetic-meta-browser-code');
    await route.fulfill({ status: 302, headers: { location: callback.href } });
  });
  await panel.getByRole('button', { name: 'Войти через Meta', exact: true }).click();
  const choice = panel.getByRole('group', { name: 'Выбор аккаунта Meta' });
  await expect(choice).toBeVisible();
  await expect(panel).not.toContainText('Подключение проверено');
  await expect(page).not.toHaveURL(/synthetic-meta-browser-code|[?&]state=/);
  await page.reload();
  await expect(choice).toBeVisible();
  await expect(choice.getByRole('button', { name: 'Подключить выбранный аккаунт', exact: true })).toBeDisabled();
  await choice.getByLabel('Аккаунт для подключения', { exact: true }).selectOption(identifier);
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath(`marketing-meta-${platform}-choice-${width}.png`), fullPage: false });
  await choice.getByRole('button', { name: 'Подключить выбранный аккаунт', exact: true }).click();
  await expect(panel).toContainText('Подключение проверено');
  await expect(panel).toContainText(identifier);
  let saved = callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.accounts[0];
  expect(saved.mode).toBe('draft');
  expect(saved.external_id).toBe(identifier);
  await panel.getByRole('button', { name: 'Проверить аккаунт Meta', exact: true }).click();
  await expect(panel).toContainText('Подключение проверено');
  await page.reload();
  await expect(panel).toContainText(identifier);
  callApi({ method: 'META_EXPIRE', account_id: platform });
  await page.getByRole('button', { name: 'Обновить подключения' }).click();
  await expect(panel).not.toContainText('Подключение проверено');
  await expect(panel).toContainText('Повторите вход');
  await panel.getByRole('button', { name: 'Отключить Meta', exact: true }).click();
  await expect(panel).not.toContainText(identifier);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  saved = callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.accounts[0];
  expect(saved.connection_status).toBe('not_connected');
});

for (const width of [1440, 390]) for (const format of ['image', 'carousel', 'video']) test(`LinkedIn ${format} upload and visible-post review at ${width}px`, async ({ page }, info) => {
  test.setTimeout(120000);
  await page.setViewportSize({ width, height: 950 });
  const callApi = await workspace(page, info);
  const stamp = Date.now(), base = '/api/admin/ai-marketing', expires = new Date(stamp + 86400000).toISOString();
  callApi({ method: 'LINKEDIN_CONFIGURE' });
  expect(callApi({ method: 'PUT', path: `${base}/accounts/linkedin`, body: { expected_version: 0, data: {
    platform: 'linkedin', label: 'Профиль основателя', external_id: 'urn:li:person:example123', personal_profile: true,
    mode: 'manual', formats: [format], rubrics: ['news'], languages: ['ru'], valid_until: expires, window_start: '00:00', window_end: '23:59',
  } } }).status).toBe(200);
  const login = callApi({ method: 'POST', path: `${base}/accounts/linkedin/linkedin/start`, body: { expected_version: 1 } });
  expect(callApi({ method: 'POST', path: `${base}/oauth/linkedin/finish`, cookie: login.headers['set-cookie'].split(';')[0],
    body: { state: new URL(login.body.authorization_url).searchParams.get('state'), code: 'synthetic-media-login' } }).status).toBe(200);
  callApi({ method: 'PUT', path: `${base}/founder-facts/role`, body: { expected_version: 0, data: {
    title: 'Роль основателя', category: 'role', proof_url: 'https://uzstock.uz/about', verification_note: 'Владелец подтвердил свою роль.',
    wordings: { ru: ['Я развиваю UZStock.'] }, status: 'verified', valid_until: expires,
  } } });
  callApi({ method: 'PUT', path: `${base}/evidence/release`, body: { expected_version: 0, data: {
    title: 'Сравнение компаний', url: 'https://uzstock.uz/news/comparison', publisher: 'UZStock', entity: '',
    published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(), expires_at: expires,
    excerpt: 'Доступно сравнение компаний.', rights: 'owned', status: 'verified', data: { feature: 'Сравнение компаний' },
  } } });
  expect(callApi({ method: 'POST', path: `${base}/candidates`, body: {
    event_id: `linkedin-media-${format}`, account_id: 'linkedin', mode: 'manual', rubric: 'news', language: 'ru', format,
    title: 'Визуальный разбор новой функции', body: 'Я развиваю UZStock. Доступно сравнение компаний.', evidence_ids: ['release'],
    founder_fact_ids: ['role'], claims: [{ evidence_id: 'release', field: 'feature', value: 'Сравнение компаний', unit: '' }],
    destination_url: 'https://uzstock.uz/news/comparison', expires_at: expires,
  } }).status).toBe(200);
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Визуальный разбор новой функции', exact: true }) })
    .filter({ has: page.getByRole('button', { name: 'Текст для отправки', exact: true }) });
  await card.getByRole('button', { name: 'Создать медиа', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Начать рендер', exact: true }).click();
  callApi({ method: 'RENDER_STEP' });
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  await card.getByRole('button', { name: 'Открыть медиа', exact: true }).click();
  await expect(format === 'video' ? page.getByRole('dialog').locator('video') : page.getByRole('dialog').getByRole('img').first()).toBeVisible();
  await page.keyboard.press('Escape');
  await card.getByRole('button', { name: 'Проверить факты', exact: true }).click();
  await card.getByRole('button', { name: 'Утвердить эту версию', exact: true }).click();
  await card.getByRole('button', { name: 'Поставить в очередь', exact: true }).click();
  const started = Date.now();
  const first = callApi({ method: 'DISPATCH_LINKEDIN', at: new Date(started).toISOString(), video_status: format === 'video' ? 'PROCESSING' : 'AVAILABLE' }).body;
  expect(first.delivery_work).toBe(true);
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  if (format === 'video') {
    await expect(card).toContainText('LinkedIn обрабатывает видео');
    expect(first.requests).not.toContain('POST /rest/posts');
    await page.reload();
    const resumed = callApi({ method: 'DISPATCH_LINKEDIN', at: new Date(started + 61000).toISOString() }).body;
    expect(resumed.delivery_work).toBe(true);
    expect(resumed.requests.filter(value => value.startsWith('PUT '))).toHaveLength(0);
    expect(resumed.requests.filter(value => value === 'POST /rest/posts')).toHaveLength(1);
    await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  }
  await expect(card).toContainText('Принято площадкой');
  await expect(card.getByRole('button', { name: 'Изменить материал', exact: true })).toHaveCount(0);
  const reviews = page.getByRole('region', { name: 'Видимость публикаций LinkedIn' });
  await reviews.getByRole('button', { name: 'Проверить опубликованный пост', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Проверка видимости LinkedIn' });
  await expect(dialog.getByRole('link', { name: 'Открыть созданный пост ↗', exact: true })).toHaveAttribute('href', 'https://www.linkedin.com/feed/update/urn:li:share:123456789/');
  await expect(dialog).toContainText('Доступно сравнение компаний.');
  await expect(dialog.getByRole('button', { name: 'Подтвердить видимость', exact: true })).toBeDisabled();
  await dialog.getByLabel('Открыл пост в LinkedIn: он виден, текст и все медиа соответствуют материалу').check();
  await page.screenshot({ path: info.outputPath(`marketing-linkedin-${format}-review-${width}.png`), fullPage: false });
  await dialog.getByRole('button', { name: 'Подтвердить видимость', exact: true }).click();
  await expect(card).toContainText('Опубликован');
  await expect(card).toContainText('Видимость подтвердил владелец');
  await page.reload();
  await expect(card).toContainText('Опубликован');
  expect(callApi({ method: 'DISPATCH_LINKEDIN', at: new Date(started + 3600000).toISOString() }).body.delivery_work).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

for (const width of [1440, 390]) test(`personal LinkedIn consent binds the profile and preserves draft permissions at ${width}px`, async ({ page }, info) => {
  test.setTimeout(120000);
  await page.setViewportSize({ width, height: 950 });
  const callApi = await workspace(page, info);
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Подключение Личный LinkedIn', exact: true });
  await expect(panel.getByRole('button', { name: 'Войти через LinkedIn', exact: true })).toBeDisabled();
  await expect(panel).toContainText('MARKETING_LINKEDIN_CLIENT_ID');
  await page.getByRole('button', { name: 'Настроить Личный LinkedIn', exact: true }).click();
  const form = page.locator('#account-linkedin form');
  await form.getByLabel('Разрешаю этот личный профиль отдельно от корпоративных каналов').check();
  await form.getByRole('button', { name: 'Сохранить правила аккаунта' }).click();
  callApi({ method: 'LINKEDIN_CONFIGURE' });
  await page.getByRole('button', { name: 'Обновить подключения' }).click();
  await expect(panel).toContainText('https://uzstock.uz/admin/ai-marketing');
  await expect(panel.getByRole('button', { name: 'Войти через LinkedIn', exact: true })).toBeEnabled();
  const origin = new URL(page.url()).origin;
  let requestedScopes;
  await page.route('https://www.linkedin.com/oauth/v2/authorization?**', async route => {
    const url = new URL(route.request().url());
    requestedScopes = url.searchParams.get('scope');
    const callback = new URL('/admin/ai-marketing', origin);
    callback.searchParams.set('state', url.searchParams.get('state'));
    callback.searchParams.set('code', 'synthetic-browser-code');
    await route.fulfill({ status: 302, headers: { location: callback.href } });
  });
  await panel.getByRole('button', { name: 'Войти через LinkedIn', exact: true }).click();
  await expect(panel).toContainText('Подключение проверено');
  await expect(panel).toContainText('Test Owner');
  await expect(panel).toContainText('urn:li:person:example123');
  expect(requestedScopes.split(' ').sort()).toEqual(['openid', 'profile', 'w_member_social']);
  await expect(page).not.toHaveURL(/synthetic-browser-code|[?&]state=/);
  let saved = callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.accounts[0];
  expect(saved.mode).toBe('draft');
  await panel.getByRole('button', { name: 'Проверить профиль', exact: true }).click();
  await expect(panel).toContainText('Подключение проверено');
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath(`marketing-linkedin-${width}.png`), fullPage: false });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.reload();
  await expect(panel).toContainText('Test Owner');
  callApi({ method: 'LINKEDIN_EXPIRE' });
  await page.getByRole('button', { name: 'Обновить подключения' }).click();
  await expect(panel.getByRole('button', { name: 'Войти через LinkedIn', exact: true })).toBeEnabled();
  await expect(panel).not.toContainText('Подключение проверено');
  await expect(panel).toContainText('Повторите вход');
  await panel.getByRole('button', { name: 'Отключить LinkedIn', exact: true }).click();
  await expect(panel.getByRole('button', { name: 'Войти через LinkedIn', exact: true })).toBeEnabled();
  await expect(panel).not.toContainText('Test Owner');
  await page.goto(`/admin/ai-marketing?state=li_${'a'.repeat(43)}&code=synthetic-expired-code`);
  await expect(page.getByRole('alert')).toContainText('Начните подключение заново');
  await expect(page).not.toHaveURL(/synthetic-expired-code|[?&]state=/);
  saved = callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.accounts[0];
  expect(saved.connection_status).toBe('not_connected');
});

for (const width of [1440, 390]) test(`restored workspace shows the independent publication recovery lock at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 950 });
  const callApi = await workspace(page, info);
  callApi({ method: 'RESTORE_REHEARSAL' });
  await page.reload();
  await expect(page.getByRole('region', { name: 'Восстановление очереди' })).toBeVisible();
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Возобновить публикации', exact: true })).toBeDisabled();
  const notice = page.getByRole('region', { name: 'Восстановление очереди' });
  await expect(notice).toContainText('Сверка после восстановления');
  await expect(notice).toContainText('Снятие обычной паузы не разрешает отправку');
  callApi({ method: 'PUT', path: '/api/admin/ai-marketing/pause', body: { publications: false } });
  await page.reload();
  await expect(notice).toBeVisible();
  expect(callApi({ method: 'DISPATCH_STEP', at: new Date().toISOString() }).body.dispatched).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath(`marketing-recovery-${width}.png`), fullPage: true });
});

for (const width of [1440, 390]) for (const uncertain of [false, true]) test(`Telegram setup and ${uncertain ? 'reconciliation' : 'publishing'} use a verified adapter at ${width}px`, async ({ page }, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width, height: 950 });
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing', stamp = Date.now();
  callApi({ method: 'PUT', path: `${base}/accounts/tg`, body: { expected_version: 0, data: {
    platform: 'telegram', label: 'Telegram · проверяемое подключение', external_id: '-100123', mode: 'manual',
    rubrics: ['news'], formats: ['post'], languages: ['ru'], valid_until: new Date(stamp + 86400000).toISOString(), window_start: '00:00', window_end: '23:59', min_interval_minutes: 1,
  } } });
  await page.reload();
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  const channel = page.getByRole('region', { name: 'Подключение Telegram UZStock' });
  await expect(channel).toBeVisible();
  await expect(channel).toContainText('MARKETING_TELEGRAM_BOT_TOKEN');
  await expect(channel).toContainText('Не настроено');
  await expect(channel.getByRole('button', { name: 'Проверить подключение' })).toBeDisabled();
  callApi({ method: 'TELEGRAM_CONFIGURE' });
  await page.getByRole('button', { name: 'Обновить подключения' }).click();
  await expect(channel).toContainText('Нужна проверка');
  await channel.getByRole('button', { name: 'Проверить подключение' }).click();
  await expect(channel).toContainText('Подключение проверено');
  callApi({ method: 'PUT', path: `${base}/evidence/announcement`, body: { expected_version: 0, data: {
    title: 'Подтверждённая новость', url: 'https://uzstock.uz/news/announcement', publisher: 'UZStock',
    published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(), expires_at: new Date(stamp + 86400000).toISOString(),
    excerpt: 'Доступно сравнение компаний.', rights: 'owned', status: 'verified', data: { feature: 'Сравнение компаний' },
  } } });
  callApi({ method: 'POST', path: `${base}/candidates`, body: { event_id: 'adapter-publication', account_id: 'tg', mode: 'manual', rubric: 'news', language: 'ru',
    title: 'Новая функция UZStock', body: 'Доступно сравнение компаний.', evidence_ids: ['announcement'],
    claims: [{ evidence_id: 'announcement', field: 'feature', value: 'Сравнение компаний', unit: '' }],
    destination_url: 'https://uzstock.uz/news/announcement', expires_at: new Date(stamp + 86400000).toISOString(),
  } });
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  await page.getByRole('button', { name: 'Обновить материалы' }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Новая функция UZStock', exact: true }) })
    .filter({ has: page.getByRole('button', { name: 'Текст для отправки', exact: true }) });
  await card.getByRole('button', { name: 'Текст для отправки' }).click();
  await expect(page.getByRole('dialog')).toContainText('https://uzstock.uz/news/announcement');
  await page.keyboard.press('Escape');
  await card.getByRole('button', { name: 'Изменить материал' }).click();
  const localDue = new Date(Date.now() + 7 * 3600000).toISOString().slice(0, 16);
  const due = new Date(`${localDue}:00+05:00`);
  await page.getByRole('dialog').getByLabel('Публиковать не раньше · Ташкент').fill(localDue);
  await page.getByRole('dialog').getByRole('button', { name: 'Сохранить материал' }).click();
  await card.getByRole('button', { name: 'Проверить факты' }).click();
  await card.getByRole('button', { name: 'Утвердить эту версию' }).click();
  await card.getByRole('button', { name: 'Поставить в очередь' }).click();
  expect(callApi({ method: 'DISPATCH_TELEGRAM', at: new Date(due.getTime() - 1000).toISOString() }).body.delivery_work).toBe(false);
  await expect(card).toContainText('Не раньше');
  await page.getByRole('button', { name: 'Календарь очереди' }).click();
  const calendar = page.getByRole('region', { name: 'Календарь очереди' });
  await expect(calendar).toContainText('Не раньше');
  await page.screenshot({ path: info.outputPath(`marketing-schedule-${width}.png`), fullPage: true });
  const outcome = callApi({ method: 'DISPATCH_TELEGRAM', at: due.toISOString(), outcome: uncertain ? 'timeout' : 'confirmed' }).body;
  expect(outcome.delivery_work).toBe(true);
  expect(outcome.methods.filter(value => value.startsWith('send'))).toEqual(['sendMessage']);
  await page.getByRole('button', { name: 'Обновить материалы' }).click();
  if (uncertain) {
    await expect(card).toContainText('Исход неясен');
    const reconciliation = page.getByRole('region', { name: 'Сверка публикаций' });
    await expect(reconciliation).toBeVisible();
    await reconciliation.getByRole('button', { name: 'Получить подтверждения Telegram' }).click();
    await expect(reconciliation).toContainText('Подтверждение не найдено');
    const state = callApi({ method: 'GET', path: `${base}/workspace` }).body;
    const item = state.candidates.find(value => value.event_id === 'adapter-publication');
    callApi({ method: 'TELEGRAM_OBSERVE', candidate_id: item.id });
    await reconciliation.getByRole('button', { name: 'Получить подтверждения Telegram' }).click();
    await expect(reconciliation).toContainText('Найдено совпадение');
    await reconciliation.getByRole('button', { name: 'Проверить совпадение' }).click();
    const confirmation = page.getByRole('dialog', { name: 'Сопоставление с публикацией Telegram' });
    await expect(confirmation.getByRole('link', { name: 'Публикация 81 ↗' })).toHaveAttribute('href', 'https://t.me/marketing_test/81');
    await expect(confirmation.getByRole('button', { name: 'Подтвердить сопоставление' })).toBeDisabled();
    await confirmation.getByLabel('Проверил исходную публикацию: текст и все медиа соответствуют этому материалу').check();
    await page.screenshot({ path: info.outputPath(`marketing-reconciliation-${width}.png`), fullPage: true });
    await confirmation.getByRole('button', { name: 'Подтвердить сопоставление' }).click();
    await expect(confirmation).not.toBeVisible();
    expect(callApi({ method: 'DISPATCH_TELEGRAM', at: new Date(due.getTime() + 60000).toISOString() }).body.delivery_work).toBe(false);
  }
  await expect(card).toContainText('Опубликован');
  await expect(card.getByRole('link', { name: 'Открыть публикацию ↗', exact: true })).toHaveAttribute('href', 'https://t.me/marketing_test/81');
  await page.reload();
  await expect(card).toContainText('ID площадки: 81');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: info.outputPath(`marketing-telegram-${width}.png`), fullPage: true });
});

for (const width of [1440, 390]) test(`paid experiments require a separate current owner decision at ${width}px`, async ({ page }, info) => {
  test.setTimeout(120000);
  await page.setViewportSize({ width, height: 950 });
  const callApi = await workspace(page, info);
  const stamp = Date.now(), base = '/api/admin/ai-marketing';
  const day = offset => new Date(stamp + offset * 86400000).toISOString().slice(0, 10);
  callApi({ method: 'PUT', path: `${base}/goal`, body: { expected_version: 0, data: {
    title: 'Переходы к новостям', metric: 'news_open', formula: 'Подтверждённые открытия', unit: 'открытий', source: 'События сайта', target: 100,
    starts_on: day(-1), deadline: day(30), budget: 1000000, currency: 'UZS',
  } } });
  callApi({ method: 'POST', path: `${base}/goal/approve`, body: { expected_version: 1 } });
  callApi({ method: 'PUT', path: `${base}/accounts/tg`, body: { expected_version: 0, data: {
    platform: 'telegram', label: 'Telegram · рекламный креатив', mode: 'draft', external_id: '-100123', rubrics: ['news'], formats: ['post'], languages: ['ru'],
  } } });
  callApi({ method: 'PUT', path: `${base}/evidence/feature`, body: { expected_version: 0, data: {
    title: 'Подтверждённая функция', url: 'https://uzstock.uz/news/comparison', publisher: 'UZStock',
    published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(), expires_at: new Date(stamp + 7 * 86400000).toISOString(),
    excerpt: 'В UZStock доступно сравнение компаний.', rights: 'owned', status: 'verified', data: { feature: 'Сравнение компаний' },
  } } });
  await page.reload();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  await page.getByRole('button', { name: 'Новый материал', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Назначение материала').selectOption('paid');
  await dialog.getByLabel('Ключ события', { exact: true }).fill('paid-feature');
  await dialog.getByLabel('Заголовок материала').fill('Сравнивайте компании');
  await dialog.getByLabel('Текст публикации').fill('В UZStock доступно сравнение компаний.');
  await dialog.getByLabel('Прямая ссылка на UZStock').fill('https://uzstock.uz/news/comparison');
  await dialog.getByLabel('Подтверждённая функция', { exact: true }).check();
  await dialog.getByLabel('feature · Сравнение компаний', { exact: true }).check();
  await dialog.getByRole('button', { name: 'Сохранить материал' }).click();
  await page.getByRole('button', { name: 'Проверить факты', exact: true }).click();
  await expect(page.getByText('Автоматические проверки пройдены', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Эксперименты', exact: true }).click();
  await page.getByRole('button', { name: 'Новый эксперимент', exact: true }).click();
  for (const [label, value] of [
    ['Название эксперимента', 'Сравнение · платный пилот'], ['Рекламный кабинет', 'paid-cabinet-1'], ['Кампания или размещение', 'comparison-pilot'],
    ['Гипотеза', 'Сравнение привлечёт пользователей к исходной новости'], ['Аудитория', 'Начинающие инвесторы Узбекистана'], ['Размещения', 'approved-channel'],
    ['Вопрос читателя', 'Как сравнить показатели компаний?'], ['Единственная проверяемая переменная', 'Подача сравнения вместо общей новости'], ['Минимум наблюдений', '30'],
    ['Контроль или вариант сравнения', 'Обычная новость при сопоставимой теме'], ['Что и как измеряем', 'Подтверждённые открытия по метке кампании'],
    ['Предельный бюджет', '100000'], ['Условие остановки', 'При достижении лимита или ошибке фактов'], ['Бриф креатива', 'Показать реальную функцию и ссылку'],
    ['Правила площадки · ссылка', 'https://ads.telegram.org/guidelines'], ['Результат проверки правил', 'Ограничения проверены; модерация не гарантируется'],
  ]) await dialog.getByLabel(label, { exact: true }).fill(value);
  await dialog.getByLabel('Сравнивайте компании', { exact: true }).check();
  await dialog.getByRole('button', { name: 'Сохранить предложение' }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Сравнение · платный пилот', exact: true }) });
  await card.getByRole('button', { name: 'Запросить платное действие' }).click();
  await expect(page.locator('#marketing-error')).toContainText('отдельное решение владельца');
  await card.getByRole('button', { name: 'Утвердить платное действие' }).click();
  await expect(card).toContainText('Утверждено');
  await card.getByRole('button', { name: 'Запросить платное действие' }).click();
  await expect(page.locator('#marketing-error')).toContainText('рекламного кабинета');
  await card.getByRole('button', { name: 'Изменить эксперимент' }).click();
  await dialog.getByLabel('Предельный бюджет', { exact: true }).fill('150000');
  await dialog.getByRole('button', { name: 'Сохранить предложение' }).click();
  await expect(card).toContainText('Предложено');
  await card.getByRole('button', { name: 'Запросить платное действие' }).click();
  await expect(page.locator('#marketing-error')).toContainText('отдельное решение владельца');
  await page.reload();
  await expect(card).toContainText('150');
  await card.getByRole('button', { name: 'История эксперимента' }).click();
  await expect(dialog).toContainText('Версия 2');
  await page.keyboard.press('Escape');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: info.outputPath(`marketing-experiment-${width}.png`), fullPage: true });
  expect(callApi({ method: 'GET', path: `${base}/workspace` }).body.deliveries).toHaveLength(0);
  await expect(page.getByLabel('Задание таргетологу', { exact: true })).toBeVisible();
  await page.getByLabel('Задание таргетологу', { exact: true }).fill('Предложи вариант этого пилота; без расходов и запуска');
  await page.getByRole('button', { name: 'Запросить предложение команды' }).click();
  const existing = callApi({ method: 'GET', path: `${base}/workspace` }).body.experiments[0];
  callApi({ method: 'MODEL_STEP', experiment_id: existing.id });
  await page.getByRole('button', { name: 'Обновить эксперименты' }).click();
  const generated = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Вариант команды: Сравнение · платный пилот', exact: true }) });
  await expect(generated).toContainText('Предложено');
  expect(callApi({ method: 'GET', path: `${base}/workspace` }).body.experiments).toHaveLength(2);
});

for (const width of [1440, 390]) test(`owner investigates a changed published source and sends a linked clarification at ${width}px`, async ({ page }, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width, height: 950 });
  const callApi = await workspace(page, info);
  const stamp = Date.now();
  const path = '/api/admin/ai-marketing';
  callApi({ method: 'PUT', path: `${path}/accounts/tg`, body: { expected_version: 0, data: {
    platform: 'telegram', label: 'Telegram · проверка исправления', external_id: '-100123', mode: 'automatic',
    rubrics: ['news'], formats: ['post'], languages: ['ru'], window_start: '00:00', window_end: '23:59', min_interval_minutes: 1,
    correction_policy: 'manual', valid_until: new Date(stamp + 86400000).toISOString(),
  } } });
  const original = {
    title: 'Решение HMKB', url: 'https://openinfo.uz/facts/123', publisher: 'HMKB', entity: 'HMKB',
    published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(),
    expires_at: new Date(stamp + 86400000).toISOString(), excerpt: 'Утверждено 120 сум на простую акцию.',
    rights: 'link_and_excerpt', status: 'verified', data: { dividend: 120, dividend_state: 'approved', share_class: 'ordinary' }, units: { dividend: 'UZS/share' },
  };
  callApi({ method: 'PUT', path: `${path}/evidence/decision`, body: { expected_version: 0, data: original } });
  const created = callApi({ method: 'POST', path: `${path}/candidates`, body: {
    event_id: 'published-decision', account_id: 'tg', mode: 'automatic', rubric: 'news', entity: 'HMKB', language: 'ru',
    title: 'Первоначальное решение', body: 'Утверждено 120 сум на простую акцию.', evidence_ids: ['decision'],
    claims: [{ evidence_id: 'decision', field: 'dividend', value: 120, unit: 'UZS/share' }],
    destination_url: 'https://uzstock.uz/news/123', expires_at: new Date(stamp + 86400000).toISOString(),
  } }).body.item;
  expect(callApi({ method: 'POST', path: `${path}/candidates/${created.id}/check` }).body.item.status).toBe('ready');
  callApi({ method: 'POST', path: `${path}/candidates/${created.id}/schedule` });
  const dispatchedAt = Date.now() + 1000;
  expect(callApi({ method: 'DISPATCH_STEP', at: new Date(dispatchedAt).toISOString() }).body.dispatched).toBe(true);
  callApi({ method: 'PUT', path: `${path}/evidence/decision`, body: { expected_version: 1,
    data: { ...original, data: { ...original.data, dividend: 99 }, excerpt: 'Утверждено 99 сум на простую акцию.' } } });
  await page.reload();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  await page.getByRole('button', { name: 'Проверить изменения источников' }).click();
  const incidents = page.getByRole('region', { name: 'Изменения после публикации' });
  await expect(incidents).toContainText('Первоначальное решение');
  await expect(incidents).toContainText('120');
  await expect(incidents).toContainText('99');
  await incidents.getByRole('button', { name: 'Подготовить уточнение' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Почему нужно уточнение').fill('Первоисточник исправил размер дивиденда');
  await dialog.getByLabel('Заголовок уточнения').fill('Уточнён размер дивиденда');
  await dialog.getByLabel('Текст уточнения').fill('Утверждено 99 сум на простую акцию.');
  await dialog.getByLabel('Прямая ссылка уточнения').fill('https://uzstock.uz/news/123');
  await dialog.screenshot({ path: info.outputPath(`marketing-correction-form-${width}.png`) });
  await dialog.getByRole('button', { name: 'Сохранить уточнение' }).click();
  const corrected = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Уточнён размер дивиденда', exact: true }) });
  await expect(corrected).toContainText('Уточнение к предыдущей публикации');
  await corrected.getByRole('button', { name: 'Проверить факты' }).click();
  await expect(corrected).toContainText('Ожидает решения');
  await corrected.getByRole('button', { name: 'Утвердить эту версию' }).click();
  await corrected.getByRole('button', { name: 'Поставить в очередь' }).click();
  await expect(incidents).toContainText('Уточнение подготовлено');
  expect(callApi({ method: 'DISPATCH_STEP', at: new Date(dispatchedAt + 120000).toISOString() }).body.dispatched).toBe(true);
  await page.getByRole('button', { name: 'Обновить материалы' }).click();
  await expect(incidents).toContainText('Уточнение опубликовано');
  const preserved = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Первоначальное решение', exact: true }) });
  await expect(preserved).toContainText('Утверждено 120 сум на простую акцию.');
  await page.reload();
  await expect(page.getByRole('region', { name: 'Изменения после публикации' })).toContainText('Уточнение опубликовано');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('region', { name: 'Изменения после публикации' }).screenshot({ path: info.outputPath(`marketing-correction-${width}.png`) });
  // A later editorial source change can be assessed without overwriting either post.
  callApi({ method: 'PUT', path: `${path}/evidence/decision`, body: { expected_version: 2,
    data: { ...original, data: { ...original.data, dividend: 99 }, excerpt: 'Утверждено 99 сум на простую акцию. Изменено оформление документа.' } } });
  await page.getByRole('button', { name: 'Проверить изменения источников' }).click();
  await incidents.getByRole('button', { name: 'Уточнение не требуется', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Почему уточнение не требуется').fill('Изменено только оформление; размер и статус дивиденда остались прежними');
  await page.getByRole('dialog').getByRole('button', { name: 'Сохранить решение' }).click();
  await expect(incidents).toContainText('Уточнение не требуется');
  await page.reload();
  await expect(page.getByRole('region', { name: 'Изменения после публикации' })).toContainText('Изменено только оформление; размер и статус дивиденда остались прежними');
  expect(callApi({ method: 'GET', path: `${path}/workspace` }).body.candidates).toHaveLength(2);
});

test('dividend check rejects paid wording despite accurate claim fields and preserves a valid approval', async ({ page }, info) => {
  const callApi = await workspace(page, info);
  const stamp = Date.now();
  callApi({ method: 'PUT', path: '/api/admin/ai-marketing/accounts/tg', body: { expected_version: 0, data: {
    platform: 'telegram', label: 'Telegram · проверка дивиденда', external_id: '-100123', mode: 'manual',
    rubrics: ['dividend'], formats: ['post'], languages: ['ru'], valid_until: new Date(stamp + 86400000).toISOString(),
  } } });
  callApi({ method: 'PUT', path: '/api/admin/ai-marketing/evidence/orfi', body: { expected_version: 0, data: {
    title: 'Решение ORFI 4061', url: 'https://openinfo.uz/facts/32/4061', publisher: 'ORFI', entity: 'ORFI',
    published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(),
    expires_at: new Date(stamp + 86400000).toISOString(), excerpt: 'Утверждено 458,88 сум на простую акцию.',
    rights: 'link_and_excerpt', status: 'verified', data: { dividend: 458.88, dividend_state: 'approved', share_class: 'ordinary' }, units: { dividend: 'UZS/share' },
  } } });
  await page.reload();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  for (const [event, body] of [['bad-payment', 'Выплачено 458,88 сум на простую акцию.'], ['valid-approval', 'Утверждено 458,88 сум на простую акцию. Дата выплаты не объявлена.']]) {
    await page.getByRole('button', { name: 'Новый материал', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Ключ события', { exact: true }).fill(event);
    await dialog.getByLabel('Рубрика', { exact: true }).selectOption('dividend');
    await dialog.getByLabel('Режим материала', { exact: true }).selectOption(event === 'bad-payment' ? 'automatic' : 'manual');
    await dialog.getByLabel('Заголовок материала').fill(event);
    await dialog.getByLabel('Текст публикации').fill(body);
    await dialog.getByLabel('Эмитент или тикер').fill('ORFI');
    await dialog.getByLabel('Прямая ссылка на UZStock').fill('https://uzstock.uz/company/ORFI');
    await dialog.getByLabel('Решение ORFI 4061', { exact: true }).check();
    for (const field of ['dividend · 458.88 UZS/share', 'dividend_state · approved', 'share_class · ordinary']) await dialog.getByLabel(field, { exact: true }).check();
    await dialog.getByRole('button', { name: 'Сохранить материал', exact: true }).click();
    const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: event, exact: true }) });
    await card.getByRole('button', { name: 'Проверить факты' }).click();
    if (event === 'bad-payment') {
      await expect(card).toContainText('Пропущен');
      await expect(card).toContainText('Статус дивиденда в тексте не совпадает с первоисточником');
      await expect(card.getByRole('button', { name: 'Поставить в очередь' })).toHaveCount(0);
    } else {
      await expect(card).toContainText('Ожидает решения');
      await card.getByRole('button', { name: 'Утвердить эту версию' }).click();
      await expect(card).toContainText('Готов');
    }
  }
  await page.reload();
  await expect(page.getByRole('article').filter({ hasText: 'bad-payment' })).toContainText('Пропущен');
  await page.screenshot({ path: info.outputPath('dividend-checked.png'), fullPage: true });
});

test('owner records report decisions and sees the actual analyst to CMO handoff', async ({ page }, info) => {
  const callApi = await workspace(page, info);
  await page.getByRole('button', { name: 'Отчёты', exact: true }).click();
  await page.getByRole('button', { name: 'Рассчитать период' }).click();
  await page.getByRole('button', { name: 'Запросить анализ CMO' }).click();
  callApi({ method: 'MODEL_STEP' });
  callApi({ method: 'MODEL_STEP' });
  await page.getByRole('button', { name: 'Обновить отчёт' }).click();
  await expect(page.getByRole('region', { name: 'Выводы команды' })).toContainText('Сначала замерим открытия отчётов. Бюджет остаётся без изменений.');
  await page.getByLabel('Решения владельца').fill('Сначала измеряем базу, цель не меняется');
  await page.getByLabel('Следующие действия').fill('Проверить полноту событий');
  await page.getByRole('button', { name: 'Сохранить решения' }).click();
  await page.reload();
  await page.getByRole('button', { name: 'Рассчитать период' }).click();
  await expect(page.getByLabel('Решения владельца')).toHaveValue('Сначала измеряем базу, цель не меняется');
  await expect(page.getByRole('heading', { name: 'Работа команды', exact: true })).toBeVisible();
});

for (const width of [1440, 390]) test(`owner calculates freezes and compares reports at ${width}px`, async ({ page }, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width, height: 950 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const callApi = await workspace(page, info);
  await page.getByRole('button', { name: 'Отчёты', exact: true }).click();
  await page.getByRole('button', { name: 'Настроить расчёты' }).click();
  await page.getByLabel('Среда данных').selectOption('test');
  await page.getByRole('button', { name: 'Сохранить правила расчёта' }).click();
  await page.getByLabel('Начало отчёта').fill('2025-01-06');
  await page.getByLabel('Конец отчёта, не включая').fill('2025-01-13');
  await page.getByRole('button', { name: 'Рассчитать период' }).click();
  const registrations = page.getByRole('article', { name: 'Регистрации', exact: true });
  await expect(registrations).toContainText('Нет данных');
  await expect(page.getByText('Тестовые данные · не результат бизнеса', { exact: true })).toBeVisible();
  const base = { dataset: 'test', at: '2025-01-07T00:00:00Z', source: 'confirmed-export', confirmed: true, channel: 'telegram' };
  const events = [{ ...base, id: 'visit-1', kind: 'visit', subject_id: 'client-1' },
    { ...base, id: 'reg-1', kind: 'registration', subject_id: 'client-1' },
    { ...base, id: 'expense', kind: 'expense', amount: 600000, category: 'advertising' },
    { ...base, id: 'impressions', kind: 'impression', object_id: 'post-1', count: 200 },
    { ...base, id: 'clicks', kind: 'click', object_id: 'post-1', count: 20 }];
  const coverage = [{ dataset: 'test', categories: ['visits', 'registrations', 'expenses', 'clicks', 'impressions'], starts_on: '2024-01-01', ends_on: '2025-02-01', through: '2025-01-31T00:00:00Z', history_complete: true, status: 'complete', reference: 'Checked source export' }];
  await page.getByRole('button', { name: 'Импортировать события' }).click();
  await page.getByLabel('Подтверждённая выгрузка JSON').fill(JSON.stringify({ events, coverage }));
  await page.getByRole('button', { name: 'Сохранить выгрузку' }).click();
  await page.getByRole('button', { name: 'Рассчитать период' }).click();
  await expect(registrations.locator('strong').first()).toHaveText('1');
  const post = page.getByRole('table', { name: 'Наблюдения по материалам' }).getByRole('row').filter({ hasText: 'post-1' });
  await expect(post.getByRole('cell').nth(2)).toHaveText('200');
  await expect(post.getByRole('cell').nth(4)).toHaveText('10');
  await expect(page.getByRole('article', { name: 'Стоимость регистрации', exact: true }).locator('strong').first()).toHaveText(/600\s000/);
  await page.getByLabel('Название снимка').fill('Проверенная неделя');
  await page.getByRole('button', { name: 'Зафиксировать неделю' }).click();
  await expect(page.getByRole('heading', { name: 'Проверенная неделя', exact: true })).toBeVisible();
  const frozen = callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.snapshots[0];
  const late = events.slice(0, 2).map(e => ({ ...e, id: e.id + '-late', subject_id: 'client-2' }));
  expect(callApi({ method: 'POST', path: '/api/admin/ai-marketing/reports/import', body: { events: late, coverage: [] } }).status).toBe(200);
  await page.getByLabel('Причина пересчёта').fill('Пришла поздняя подтверждённая регистрация');
  await page.getByRole('button', { name: 'Создать пересчитанный снимок' }).click();
  await expect(registrations.locator('strong').first()).toHaveText('2');
  await page.getByLabel('Базовый снимок').selectOption(frozen.id);
  await page.getByRole('button', { name: 'Сравнить отчёты' }).click();
  await expect(page.getByRole('region', { name: 'Сравнение отчётов' }).getByTestId('comparison-registrations')).toContainText('+1');
  await expect(page.getByTestId('comparison-registrations').getByRole('cell').nth(1)).toHaveCSS('white-space', 'nowrap');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать JSON' }).click();
  await (await download).saveAs(info.outputPath('report.json'));
  const csvDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать CSV' }).click();
  const csvPath = info.outputPath('report.csv');
  await (await csvDownload).saveAs(csvPath);
  expect(readFileSync(csvPath, 'utf8')).toContain('metric,title,value');
  await page.getByLabel('Показать снимок').selectOption(frozen.id);
  await expect(registrations.locator('strong').first()).toHaveText('1');
  await page.getByRole('button', { name: 'Импортировать события' }).click();
  await page.getByLabel('Подтверждённая выгрузка JSON').fill(JSON.stringify({ corrections: [{ event_id: 'expense', dataset: 'test', replacement: { ...events[2], amount: 300000 }, expected_version: 0, reason: 'Уточнён счёт за рекламу' }] }));
  await page.getByRole('button', { name: 'Сохранить выгрузку' }).click();
  await page.getByLabel('Причина пересчёта').fill('Исправлены исходные расходы');
  await page.getByRole('button', { name: 'Создать пересчитанный снимок' }).click();
  await expect(page.getByRole('article', { name: 'Стоимость регистрации', exact: true }).locator('strong').first()).toHaveText(/150\s000/);
  await expect(page.getByText('Уточнён счёт за рекламу', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Настроить расчёты' }).click();
  await page.getByLabel('Окно атрибуции, дней').fill('30');
  await page.getByRole('button', { name: 'Сохранить правила расчёта' }).click();
  await page.getByRole('button', { name: 'Рассчитать период' }).click();
  await page.getByRole('button', { name: 'Сравнить отчёты' }).click();
  await expect(page.getByRole('region', { name: 'Сравнение отчётов' })).toContainText('Расчёты несопоставимы');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath(`marketing-reports-${width}.png`), fullPage: true });
  await page.getByRole('region', { name: 'Сравнение отчётов' }).screenshot({ path: info.outputPath(`marketing-comparison-${width}.png`) });
  expect(errors).toEqual([]);
});

for (const width of [1440, 390]) test(`native website observations reach reports with honest coverage at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 950 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const callApi = await workspace(page, info);
  await page.getByRole('button', { name: 'Отчёты', exact: true }).click();
  const source = page.getByRole('region', { name: 'События сайта UZStock', exact: true });
  await expect(source).toContainText('Настройте подключение на сервере');
  expect(callApi({ method: 'WEBSITE_CONFIGURE' }).body.reader).toBe(process.env.MARKETING_BROWSER_POSTGRES_URL ? 'postgres' : 'fixture');
  callApi({ method: 'PUT', path: '/api/admin/ai-marketing/reports/settings', body: { expected_version: 0, data: { dataset: 'test' } } });
  await page.reload();
  const starts = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
  const ends = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  await source.getByLabel('Среда событий сайта', { exact: true }).selectOption('test');
  await source.getByLabel('Начать чтение с', { exact: true }).fill(starts);
  await source.getByLabel('Разрешить сбор событий сайта').check();
  await source.getByRole('button', { name: 'Сохранить подключение сайта', exact: true }).click();
  await expect(source).toContainText('Сбор включён');
  await source.getByRole('button', { name: 'Прочитать сейчас', exact: true }).click();
  await expect(source).toContainText('Добавлено событий: 2');
  await source.getByRole('button', { name: 'Прочитать сейчас', exact: true }).click();
  await expect(source).toContainText('Добавлено событий: 3');
  await source.getByRole('button', { name: 'Прочитать сейчас', exact: true }).click();
  await expect(source).toContainText('Обход завершён');
  await expect(source).toContainText('Добавлено событий: 3');
  await expect(source).toContainText('Старых аккаунтов без дат: 2');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: info.outputPath(`marketing-website-source-${width}.png`), fullPage: true });
  await page.getByLabel('Начало отчёта', { exact: true }).fill(starts);
  await page.getByLabel('Конец отчёта, не включая', { exact: true }).fill(ends);
  await page.getByRole('button', { name: 'Рассчитать период', exact: true }).click();
  const registrations = page.getByRole('article', { name: 'Регистрации', exact: true });
  await expect(registrations).toContainText('Неполные данные');
  await registrations.getByText('Расчёт и источник', { exact: true }).click();
  await expect(registrations.locator('dd').first()).toHaveText('1');
  await expect(page.getByRole('table', { name: 'Атрибуция регистраций' })).toContainText('telegram');
  callApi({ method: 'WEBSITE_ERROR' });
  await source.getByRole('button', { name: 'Прочитать сейчас', exact: true }).click();
  await expect(source).toContainText('База сайта недоступна');
  await expect(source).not.toContainText('browser-private-password');
  await page.reload();
  await expect(source).toContainText('База сайта недоступна');
  await source.getByLabel('Разрешить сбор событий сайта').uncheck();
  await source.getByRole('button', { name: 'Сохранить подключение сайта', exact: true }).click();
  await expect(source.getByRole('button', { name: 'Прочитать сейчас', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

for (const width of [1440, 390]) test(`unknown acquisition stays unavailable until dated source evidence arrives at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 950 });
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing/reports';
  expect(callApi({ method: 'PUT', path: `${base}/settings`, body: { expected_version: 0, data: {
    dataset: 'test', monetization_live: true, legal_entities: ['ip'], shared_customer_ids: true,
    entity_launches: { ip: '2024-01-01T00:00:00Z' }, cost_categories: ['advertising'], acquisition_channels: ['telegram'],
  } } }).status).toBe(200);
  const common = { dataset: 'test', at: '2025-01-07T00:00:00Z', source: 'reconciled-billing', confirmed: true };
  const events = [
    { ...common, id: 'cost', kind: 'expense', amount: 1000, category: 'advertising', channel: 'telegram' },
    { ...common, id: 'reg', kind: 'registration', subject_id: 'customer' },
    { ...common, id: 'payment', kind: 'payment', subject_id: 'customer', transaction_id: 'receipt', amount: 5000,
      gross_profit: 2000, payment_type: 'first', legal_entity: 'ip', at: '2025-01-08T00:00:00Z' },
  ];
  const coverage = { dataset: 'test', categories: ['visits', 'registrations', 'payments', 'expenses', 'margin'],
    starts_on: '2024-01-01', ends_on: '2025-02-01', through: '2025-02-01T00:00:00Z', history_complete: true,
    status: 'complete', reference: 'Dates reconciled; acquisition identity still needs evidence' };
  expect(callApi({ method: 'POST', path: `${base}/import`, body: { events, coverage: [coverage] } }).status).toBe(200);
  await page.getByRole('button', { name: 'Отчёты', exact: true }).click();
  await page.getByLabel('Начало отчёта').fill('2025-01-06');
  await page.getByLabel('Конец отчёта, не включая').fill('2025-01-13');
  await page.getByRole('button', { name: 'Рассчитать период' }).click();
  const roas = page.getByRole('article', { name: 'ROAS', exact: true });
  const roi = page.getByRole('article', { name: 'Маркетинговый ROI', exact: true });
  await expect(roas.locator('strong').first()).toHaveText('Нет данных');
  await expect(roi.locator('strong').first()).toHaveText('Нет данных');
  const channelTable = page.getByRole('table', { name: 'Атрибуция регистраций', exact: true });
  await expect(channelTable.getByRole('columnheader').nth(1)).toContainText('Неполные данные');
  await expect(channelTable.getByRole('columnheader').nth(1)).toContainText('Наблюдаемые регистрации');
  await expect(page.getByRole('region', { name: 'Переходы из публикаций', exact: true })).toContainText('Регистраций с неуточнённым источником или публикацией: 1');
  await expect(page.getByRole('article', { name: 'Подтверждённая выручка', exact: true }).locator('strong').first()).toHaveText(/5\s000 UZS/);
  await roas.getByText('Расчёт и источник', { exact: true }).click();
  await expect(roas).toContainText('Клиентов без надёжной атрибуции: 1 из 1');
  await expect(roas).toContainText('Нет наблюдаемого источника в окне привлечения');
  await roas.screenshot({ path: info.outputPath(`marketing-acquisition-proof-${width}.png`) });
  await roas.evaluate(node => window.scrollTo({ top: window.scrollY + node.getBoundingClientRect().top - 100, behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath(`marketing-acquisition-viewport-${width}.png`) });
  await page.getByLabel('Название снимка').fill('Источник ещё не связан');
  await page.getByRole('button', { name: 'Зафиксировать неделю' }).click();
  const frozen = callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.snapshots[0];
  await page.getByRole('button', { name: 'Импортировать события' }).click();
  await page.getByLabel('Подтверждённая выгрузка JSON').fill(JSON.stringify({ events: [
    { ...common, id: 'late-source', kind: 'visit', subject_id: 'customer', channel: 'telegram', at: '2025-01-06T22:00:00Z', source: 'verified-landing' },
  ] }));
  await page.getByRole('button', { name: 'Сохранить выгрузку' }).click();
  await page.getByLabel('Причина пересчёта').fill('Восстановлена связь регистрации с источником');
  await page.getByRole('button', { name: 'Создать пересчитанный снимок' }).click();
  await expect(roas.locator('strong').first()).toHaveText('5 ×');
  await expect(roi.locator('strong').first()).toHaveText('100 %');
  await expect(channelTable.getByRole('columnheader').nth(1)).toContainText('Готово');
  await page.reload();
  await page.getByLabel('Показать снимок').selectOption(frozen.id);
  await expect(roas.locator('strong').first()).toHaveText('Нет данных');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

for (const width of [1440, 390]) test(`metric completeness follows its own observation window at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 950 });
  const callApi = await workspace(page, info);
  const base = '/api/admin/ai-marketing/reports';
  expect(callApi({ method: 'PUT', path: `${base}/settings`, body: { expected_version: 0, data: {
    dataset: 'test', monetization_live: true, legal_entities: ['ip'], shared_customer_ids: true,
    entity_launches: { ip: '2024-01-01T00:00:00Z' },
  } } }).status).toBe(200);
  const common = { dataset: 'test', subject_id: 'customer-a', at: '2025-01-07T00:00:00Z', source: 'verified-window-export', confirmed: true };
  const events = [{ ...common, id: 'visit', kind: 'visit', channel: 'direct' }, { ...common, id: 'registration', kind: 'registration' },
    { ...common, id: 'tagged-arrival', kind: 'publication_visit', publication_id: 'HMKB-news', channel: 'telegram', at: '2025-01-06T22:00:00Z' },
    { ...common, id: 'unconverted-arrival', subject_id: 'reader-b', kind: 'publication_visit', publication_id: 'LinkedIn-news', channel: 'linkedin', at: '2025-01-06T23:00:00Z' },
    { ...common, id: 'payment', kind: 'payment', transaction_id: 'receipt-a', amount: 100000, legal_entity: 'ip', payment_type: 'first', source: 'receipts-january' },
    { ...common, id: 'foreign-payment', kind: 'payment', transaction_id: 'receipt-usd', amount: 10, currency: 'USD', legal_entity: 'ip', payment_type: 'renewal', source: 'unrelated-usd-upload', at: '2025-01-12T00:00:00Z' },
    { ...common, id: 'use', kind: 'report_open', object_id: 'HMKB', at: '2025-01-08T00:00:00Z' }];
  const coverage = { dataset: 'test', categories: ['visits', 'registrations', 'payments', 'activity'], starts_on: '2025-01-06',
    ends_on: '2025-01-13', through: '2025-01-13T00:00:00Z', status: 'complete', history_complete: true, reference: 'Подтверждён только отчётный период' };
  expect(callApi({ method: 'POST', path: `${base}/import`, body: { events, coverage: [coverage] } }).status).toBe(200);
  await page.getByRole('button', { name: 'Отчёты', exact: true }).click();
  await page.getByLabel('Начало отчёта').fill('2025-01-06');
  await page.getByLabel('Конец отчёта, не включая').fill('2025-01-13');
  await page.getByRole('button', { name: 'Рассчитать период' }).click();
  const visits = page.getByRole('article', { name: 'Посещения', exact: true });
  const cash = page.getByRole('article', { name: 'Подтверждённая выручка', exact: true });
  const conversion = page.getByRole('article', { name: 'Регистрация → первая оплата', exact: true });
  await expect(visits.locator('strong').first()).toHaveText('1');
  await expect(cash.locator('strong').first()).toHaveText(/100\s000 UZS/);
  await expect(conversion.locator('strong').first()).toHaveText('Нет данных');
  const attribution = page.getByRole('region', { name: 'Переходы из публикаций', exact: true });
  await expect(attribution).toContainText('Неполные данные');
  await expect(attribution).toContainText('не добавляются к кликам площадки');
  const attributed = attribution.getByRole('row').filter({ hasText: 'HMKB-news' });
  await expect(attributed.getByRole('cell').nth(2)).toHaveText('1');
  await expect(attributed.getByRole('cell').nth(3)).toHaveText('1');
  await expect(page.getByLabel('Площадка отчёта').getByRole('option', { name: 'linkedin', exact: true })).toHaveCount(1);
  await page.getByLabel('Площадка отчёта').selectOption('linkedin');
  await expect(attributed).toHaveCount(0);
  await expect(attribution.getByRole('row').filter({ hasText: 'LinkedIn-news' }).getByRole('cell').nth(3)).toHaveText('0');
  await page.getByLabel('Площадка отчёта').selectOption('');
  await attribution.screenshot({ path: info.outputPath(`marketing-publication-attribution-${width}.png`) });
  await cash.getByText('Расчёт и источник', { exact: true }).click();
  await expect(cash).toContainText('Источники наблюдений');
  await expect(cash).toContainText('receipts-january');
  await expect(cash).not.toContainText('unrelated-usd-upload');
  await expect(cash.locator('dt').filter({ hasText: 'Последнее событие' }).locator('+ dd')).toHaveText('07.01.2025');
  await expect(cash).toContainText('Окна источников для этого показателя');
  await expect(cash).toContainText('06.01.2025');
  await expect(cash).toContainText('13.01.2025');
  await expect(cash).toContainText('История до начала окна не требуется');
  await cash.screenshot({ path: info.outputPath(`metric-cash-window-${width}.png`) });
  await conversion.getByText('Расчёт и источник', { exact: true }).click();
  await expect(conversion).toContainText('14.01.2025');
  await expect(conversion).toContainText('Нет подтверждения этого окна');
  await conversion.screenshot({ path: info.outputPath(`metric-followup-window-${width}.png`) });
  await page.getByLabel('Название снимка').fill('Без подтверждения последующих оплат');
  await page.getByRole('button', { name: 'Зафиксировать неделю' }).click();
  const frozen = callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.snapshots[0];
  await page.getByRole('button', { name: 'Импортировать события' }).click();
  await page.getByLabel('Подтверждённая выгрузка JSON').fill(JSON.stringify({ coverage: [{ ...coverage, categories: ['payments', 'activity'],
    ends_on: '2025-01-15', through: '2025-01-14T00:00:00Z', reference: 'Окна когорты сверены до последнего дня' }] }));
  await page.getByRole('button', { name: 'Сохранить выгрузку' }).click();
  await page.getByLabel('Причина пересчёта').fill('Подтверждено полное окно когорты');
  await page.getByRole('button', { name: 'Создать пересчитанный снимок' }).click();
  await expect(conversion.locator('strong').first()).toHaveText('100 %');
  await expect(page.getByRole('article', { name: 'Активация', exact: true }).locator('strong').first()).toHaveText('100 %');
  await page.reload();
  await page.getByLabel('Показать снимок').selectOption(frozen.id);
  await expect(conversion.locator('strong').first()).toHaveText('Нет данных');
  await expect(cash.locator('strong').first()).toHaveText(/100\s000 UZS/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

for (const width of [1440, 390]) test(`financial reconciliation preserves evidence and separates company expenses at ${width}px`, async ({ page }, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width, height: 950 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const callApi = await workspace(page, info);
  const base = '/api/admin/ai-marketing/reports';
  expect(callApi({ method: 'PUT', path: `${base}/settings`, body: { expected_version: 0, data: {
    dataset: 'test', monetization_live: true, legal_entities: ['ip', 'llc'], shared_customer_ids: true,
    entity_launches: { ip: '2024-01-01T00:00:00Z', llc: '2024-01-01T00:00:00Z' },
    cost_categories: ['advertising', 'sales'], acquisition_channels: ['telegram'],
  } } }).status).toBe(200);
  const common = { dataset: 'test', at: '2025-01-07T00:00:00Z', source: 'billing-acceptance', confirmed: true, channel: 'telegram' };
  const refund = { ...common, id: 'refund', kind: 'refund', subject_id: 'client-a', legal_entity: 'ip',
    transaction_id: 'refund-a', related_transaction_id: 'payment-a', amount: 130000 };
  const events = [{ ...common, id: 'payment', kind: 'payment', subject_id: 'client-a', transaction_id: 'payment-a',
    legal_entity: 'ip', amount: 120000, payment_type: 'first' }, refund,
    { ...common, id: 'ip-expense', kind: 'expense', legal_entity: 'ip', amount: 600000, category: 'advertising' },
    { ...common, id: 'llc-expense', kind: 'expense', legal_entity: 'llc', amount: 300000, category: 'sales' },
    { ...common, id: 'unassigned-expense', kind: 'expense', amount: 100000, category: 'advertising' }];
  const coverage = [{ dataset: 'test', categories: ['payments', 'expenses'], starts_on: '2024-01-01', ends_on: '2025-03-01',
    through: '2025-02-28T00:00:00Z', status: 'complete', history_complete: true, reference: 'Reconciled billing export' }];
  expect(callApi({ method: 'POST', path: `${base}/import`, body: { events, coverage } }).status).toBe(200);
  await page.getByRole('button', { name: 'Отчёты', exact: true }).click();
  await page.getByLabel('Начало отчёта').fill('2025-01-06');
  await page.getByLabel('Конец отчёта, не включая').fill('2025-01-13');
  await page.getByRole('button', { name: 'Рассчитать период' }).click();
  const problems = page.getByRole('region', { name: 'Сверка оплат и возвратов', exact: true });
  await expect(problems).toContainText('Сумма возвратов превышает исходную оплату');
  await expect(problems).toContainText('payment-a');
  const revenue = page.getByRole('article', { name: 'Подтверждённая выручка', exact: true });
  await expect(revenue.locator('strong').first()).toHaveText('Нет данных');
  const costs = page.getByRole('table', { name: 'Расходы по форме', exact: true });
  await expect(costs.getByRole('row').filter({ has: page.getByRole('rowheader', { name: 'ИП', exact: true }) })).toContainText(/600\s000/);
  await expect(costs.getByRole('row').filter({ has: page.getByRole('rowheader', { name: 'ООО', exact: true }) })).toContainText(/300\s000/);
  await expect(costs.getByRole('row').filter({ has: page.getByRole('rowheader', { name: 'Форма не указана', exact: true }) })).toContainText(/100\s000/);
  expect(await costs.locator('td').evaluateAll(cells => cells.filter(cell => /^[\d\s]+$/.test(cell.textContent)).every(cell => {
    const range = document.createRange();
    range.selectNodeContents(cell);
    return range.getClientRects().length === 1;
  }))).toBe(true);
  await problems.screenshot({ path: info.outputPath(`marketing-finance-issues-${width}.png`) });
  await page.getByRole('region', { name: 'ИП и ООО', exact: true }).screenshot({ path: info.outputPath(`marketing-finance-entities-${width}.png`) });
  await page.getByLabel('Название снимка').fill('До сверки возврата');
  await page.getByRole('button', { name: 'Зафиксировать неделю' }).click();
  const frozen = callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.snapshots[0];
  await page.getByRole('button', { name: 'Импортировать события' }).click();
  await page.getByLabel('Подтверждённая выгрузка JSON').fill(JSON.stringify({ corrections: [{ event_id: 'refund', dataset: 'test',
    replacement: { ...refund, amount: 20000 }, reason: 'Проверена исходная транзакция возврата', expected_version: 0 }] }));
  await page.getByRole('button', { name: 'Сохранить выгрузку' }).click();
  await page.getByLabel('Причина пересчёта').fill('Сверен возврат');
  await page.getByRole('button', { name: 'Создать пересчитанный снимок' }).click();
  await expect(revenue.locator('strong').first()).toHaveText(/100\s000 UZS/);
  await expect(problems).toHaveCount(0);
  await page.reload();
  await page.getByLabel('Показать снимок').selectOption(frozen.id);
  await expect(problems).toContainText('Сумма возвратов превышает исходную оплату');
  await expect(revenue.locator('strong').first()).toHaveText('Нет данных');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1)).toBe(true);
  expect(errors).toEqual([]);
});

test('owner saves and approves a goal, reloads history, and pauses publications', async ({ page }, info) => {
  await workspace(page, info);
  await expect(page.getByRole('heading', { name: 'Обзор команды' })).toBeVisible();
  await expect(page.getByText('Цель ещё не утверждена')).toBeVisible();
  await page.getByRole('button', { name: 'Цель и стратегия', exact: true }).click();
  await page.getByLabel('Бизнес-цель', { exact: true }).fill('Переходы к квартальным разборам');
  await page.getByLabel('Метрика', { exact: true }).fill('report_open');
  await page.getByLabel('Формула KPI').fill('Подтверждённые открытия отчётов');
  await page.getByLabel('Единица измерения').fill('открытий');
  await page.getByLabel('Источник KPI').fill('События продукта');
  await page.getByLabel('Целевое значение').fill('100');
  await page.getByLabel('Начало периода').fill('2026-11-23');
  await page.getByLabel('Срок достижения').fill('2026-12-23');
  await page.getByLabel('Общий бюджет').fill('0');
  await page.getByRole('button', { name: 'Сохранить проект цели' }).click();
  await expect(page.getByRole('button', { name: 'Утвердить эту версию цели' })).toBeVisible();
  await page.getByRole('button', { name: 'Утвердить эту версию цели' }).click();
  await page.reload();
  await expect(page.getByText('Действует версия 2', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'История цели' }).click();
  await expect(page.getByRole('dialog')).toContainText('Версия 1');
  await expect(page.getByRole('dialog')).toContainText('Версия 2');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'История цели' })).toBeFocused();
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  await page.getByRole('button', { name: 'Приостановить публикации' }).click();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Возобновить публикации' })).toBeVisible();
});

for (const width of [1440, 390]) test(`marketing overview and account settings fit ${width}px`, async ({ page }, info) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width, height: 900 });
  await workspace(page, info);
  await expect(page.getByRole('heading', { name: 'Обзор команды' })).toBeVisible();
  await page.getByRole('button', { name: 'Редактор качества', exact: false }).click();
  await expect(page.getByRole('dialog')).toContainText('Проверка оригиналов');
  await page.keyboard.press('Escape');
  await page.screenshot({ path: info.outputPath(`marketing-overview-${width}.png`), fullPage: true });
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  await page.getByRole('button', { name: 'Настроить Telegram UZStock' }).click();
  await expect(page.getByLabel('Режим выпуска')).toHaveValue('draft');
  await expect(page.getByText('Не подключён', { exact: true }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath(`marketing-settings-${width}.png`), fullPage: true });
  await page.reload();
  // Scroll offsets round to device pixels; a hidden selected tab had ratio 0.
  await expect(page.getByRole('navigation', { name: 'Разделы маркетинга' }).getByRole('button', { name: 'Настройки', exact: true })).toBeInViewport({ ratio: 0.99 });
  expect(errors).toEqual([]);
});

test('CMO keeps a real queued task and shows the model response after background work', async ({ page }, info) => {
  const callApi = await workspace(page, info);
  await page.getByRole('button', { name: 'Цель и стратегия', exact: true }).click();
  await page.getByLabel('Сообщение CMO').fill('Как замерить переходы к разборам без рекламного бюджета?');
  await page.getByRole('button', { name: 'Отправить CMO' }).click();
  await expect(page.getByLabel('Сообщения команды').getByText('Как замерить переходы к разборам без рекламного бюджета?', { exact: true })).toBeVisible();
  callApi({ method: 'MODEL_STEP' });
  await page.getByRole('button', { name: 'Обновить обсуждение' }).click();
  await expect(page.getByText('Сначала замерим открытия отчётов. Бюджет остаётся без изменений.', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('Какой период используем для исходной базы?', { exact: true })).toBeVisible();
});

for (const width of [1440, 390]) test(`owner reviews comparable theme history without promoting incomplete data to growth at ${width}px`, async ({ page }, info) => {
  test.setTimeout(60000);
  await page.setViewportSize({ width, height: 950 });
  if (width === 390) await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_theme', 'light'));
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  expect(callApi({ method: 'PUT', path: `${base}/sources/mentions`, body: { expected_version: 0, data: {
    name: 'Проверенная подборка', url: 'https://example.test/news', category: 'manual', method: 'manual', owner: 'owner',
    rights: 'link_and_excerpt', terms_checked_on: '2026-11-23', may_store: true, may_display: true, commercial_use: true,
  } } }).status).toBe(200);
  const original = (id, day, event = id) => ({ source_item_id: id, canonical_event_id: event, title: `Решение ${id}`,
    url: `https://example.test/${id}`, publisher: 'Эмитент', published_at: `2026-11-${day}T06:00:00Z`,
    excerpt: 'Опубликовано решение эмитента.', rights: 'link_and_excerpt', themes: ['Дивиденды'] });
  expect(callApi({ method: 'POST', path: `${base}/sources/mentions/import`, body: {
    materials: [original('old', 10), original('a', 17), original('b', 22), original('reprint', 18, 'old')],
  } }).status).toBe(200);
  await page.getByRole('button', { name: 'Источники', exact: true }).click();
  await page.getByRole('button', { name: 'Обновить статусы источников', exact: true }).click();
  await page.getByRole('button', { name: 'Сравнить наблюдения темы', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Тема для сравнения', { exact: true }).fill('Дивиденды');
  await dialog.getByLabel('Проверенная подборка', { exact: true }).check();
  await dialog.getByLabel('Начало текущего окна', { exact: true }).fill('2026-11-16');
  await dialog.getByLabel('Конец окна, не включая', { exact: true }).fill('2026-11-23');
  await dialog.getByLabel('Связь с аудиторией', { exact: true }).fill('Инвесторы сопоставляют решения эмитентов.');
  await dialog.getByLabel('Риск интерпретации', { exact: true }).fill('Решение не означает выплату.');
  await dialog.getByLabel('Предлагаемый формат', { exact: true }).fill('Объясняющая карточка со ссылками.');
  await dialog.getByRole('button', { name: 'Сохранить наблюдение', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'дивиденды', exact: true }) });
  await expect(card).toContainText('Повторяющаяся тема');
  await expect(card).toContainText('Рост интереса не измерен');
  await expect(card.getByRole('row', { name: /Упоминания без перепечаток/ })).toContainText('1');
  await expect(card.getByRole('row', { name: /Упоминания без перепечаток/ })).toContainText('2');
  await card.getByRole('button', { name: 'Пересмотреть наблюдение', exact: true }).click();
  await dialog.getByLabel('Оба окна полны, темы и перепечатки проверены', { exact: true }).check();
  await dialog.getByLabel('Основание проверки полноты', { exact: true }).fill('Сверены полные выгрузки одного источника и ключи решений.');
  await dialog.getByRole('button', { name: 'Сохранить наблюдение', exact: true }).click();
  await expect(card).toContainText('Измеряемый рост интереса');
  await expect(card).toContainText('+100%');
  await expect(card).toContainText('09.11.2026');
  await expect(card).toContainText('Решение не означает выплату');
  await card.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath(`marketing-trends-${width}.png`), fullPage: false });
  await card.getByRole('heading', { name: 'дивиденды', exact: true }).scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -100));
  await page.screenshot({ path: info.outputPath(`marketing-trends-heading-${width}.png`), fullPage: false });
  await page.reload();
  await expect(card).toContainText('+100%');
  expect(callApi({ method: 'POST', path: `${base}/sources/mentions/import`, body: { materials: [original('late', 11)] } }).status).toBe(200);
  await page.getByRole('button', { name: 'Обновить статусы источников', exact: true }).click();
  await expect(card).toContainText('Данные изменились после проверки');
  await expect(card).not.toContainText('+100%');
  await card.getByRole('heading', { name: 'дивиденды', exact: true }).scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -100));
  await page.screenshot({ path: info.outputPath(`marketing-trends-stale-${width}.png`), fullPage: false });
  await card.getByRole('button', { name: 'Пересмотреть наблюдение', exact: true }).click();
  await expect(dialog.getByLabel('Оба окна полны, темы и перепечатки проверены', { exact: true })).not.toBeChecked();
  await dialog.getByLabel('Оба окна полны, темы и перепечатки проверены', { exact: true }).check();
  await dialog.getByRole('button', { name: 'Сохранить наблюдение', exact: true }).click();
  await expect(card).toContainText('Изменение: 0');
  await expect(card).not.toContainText('Измеряемый рост интереса');
  await card.getByRole('button', { name: 'История наблюдения', exact: true }).click();
  await expect(dialog).toContainText('Версия 3');
  await expect(dialog).toContainText('Упоминания: 1 → 2');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Рабочий цикл', exact: true }).click();
  await page.getByText('Новое исследование', { exact: true }).click();
  await page.getByLabel('Вопрос исследования', { exact: true }).fill('Как проверить интерес к теме?');
  await expect(page.getByLabel('Наблюдение · дивиденды', { exact: true })).toBeVisible();
  await page.getByLabel('Наблюдение · дивиденды', { exact: true }).check();
  await page.getByRole('button', { name: 'Передать исследователям', exact: true }).click();
  const task = callApi({ method: 'GET', path: `${base}/workspace` }).body.tasks[0];
  expect(Object.values(task.trend_versions)).toEqual([3]);
  callApi({ method: 'MODEL_STEP' });
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  const taskCard = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Как проверить интерес к теме?', exact: true }) });
  await taskCard.getByRole('button', { name: 'Результаты ролей', exact: true }).click();
  await expect(dialog).toContainText('Наблюдения в задаче');
  await expect(dialog).toContainText('дивиденды · версия 3');
  await expect(dialog).toContainText('упоминания 2 → 2');
  await dialog.screenshot({ path: info.outputPath(`marketing-trends-task-${width}.png`) });
  await page.keyboard.press('Escape');
  expect(callApi({ method: 'POST', path: `${base}/sources/mentions/import`, body: { materials: [original('later-arrival', 12)] } }).status).toBe(200);
  callApi({ method: 'MODEL_STEP' });
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await expect(taskCard).toContainText('Выбранные наблюдения темы изменились');
  await expect(taskCard.getByRole('button', { name: 'Повторить сохранённый шаг', exact: true })).toHaveCount(0);
  await taskCard.screenshot({ path: info.outputPath(`marketing-trends-task-changed-${width}.png`) });
  expect(callApi({ method: 'GET', path: `${base}/workspace` }).body.tasks[0].outputs).toHaveLength(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('owner registers a source, imports original evidence, verifies it and revokes permission', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await workspace(page, info);
  await page.getByRole('button', { name: 'Источники', exact: true }).click();
  await page.getByRole('button', { name: 'Добавить источник', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Название источника', { exact: true }).fill('Решения эмитента');
  await dialog.getByLabel('Адрес источника', { exact: true }).fill('https://openinfo.uz');
  await dialog.getByLabel('Условия использования', { exact: true }).selectOption('link_and_excerpt');
  await dialog.getByLabel('Дата проверки условий', { exact: true }).fill('2026-11-23');
  await dialog.getByLabel('Разрешено сохранять материалы').check();
  await dialog.getByLabel('Разрешено показывать фрагменты').check();
  await dialog.getByLabel('Разрешено коммерческое использование').check();
  await dialog.getByRole('button', { name: 'Сохранить источник', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Решения эмитента', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Импортировать материал', exact: true }).click();
  await dialog.getByLabel('Название материала').fill('Решение о дивидендах HMKB');
  await dialog.getByLabel('Ссылка на оригинал').fill('https://openinfo.uz/facts/123');
  await dialog.getByLabel('Издатель').fill('HMKB');
  await dialog.getByLabel('Эмитент или тикер').fill('HMKB');
  await dialog.getByLabel('Ключ события').fill('HMKB:dividend:2026');
  await dialog.getByLabel('Темы материала', { exact: true }).fill('Дивиденды, Банки');
  await dialog.getByLabel('Дата публикации оригинала').fill('2026-11-23T11:00');
  await dialog.getByLabel('Оригинальный фрагмент').fill('Утверждён дивиденд 120 UZS на обыкновенную акцию.');
  await dialog.getByLabel('Факты в JSON').fill('{"dividend":120}');
  await dialog.getByLabel('Единицы в JSON').fill('{"dividend":"UZS/share"}');
  await dialog.getByRole('button', { name: 'Импортировать', exact: true }).click();
  await page.getByRole('button', { name: 'Открыть доказательство', exact: true }).click();
  await expect(dialog).toContainText('120 UZS');
  await dialog.getByLabel('Как проверен оригинал').fill('Сверены решение эмитента, сумма и единица на акцию.');
  await dialog.getByRole('button', { name: 'Подтвердить факты', exact: true }).click();
  await expect(page.getByText('Проверен', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('Проверен', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('marketing-sources-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: 'Отключить источник', exact: true }).click();
  await expect(page.getByText('Отключён', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'История источника', exact: true }).click();
  await expect(dialog).toContainText('Версия 3');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'История источника', exact: true })).toBeFocused();
});

for (const width of [1280, 390]) test(`owner prepares and approves a post, sees terminal skip at ${width}px`, async ({ page }, info) => {
  // This journey performs two approvals, an edit, a terminal rejection and
  // full-page capture through the real Python adapter under parallel load.
  test.setTimeout(60000);
  await page.setViewportSize({ width, height: 900 });
  if (width === 390) await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_theme', 'light'));
  const callApi = await workspace(page, info);
  const stamp = Date.now();
  callApi({ method: 'PUT', path: '/api/admin/ai-marketing/accounts/tg', body: { expected_version: 0, data: {
    platform: 'telegram', label: 'Telegram · тестовый аккаунт', external_id: '-100123', mode: 'manual',
    rubrics: ['news'], formats: ['post'], languages: ['ru'], valid_until: new Date(stamp + 7 * 86400000).toISOString(),
  } } });
  callApi({ method: 'PUT', path: '/api/admin/ai-marketing/evidence/decision', body: { expected_version: 0, data: {
    title: 'Решение HMKB', url: 'https://openinfo.uz/facts/123', publisher: 'HMKB', entity: 'HMKB',
    published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(),
    expires_at: new Date(stamp + 86400000).toISOString(), excerpt: 'Утверждено 120 сум на простую акцию.',
    rights: 'link_and_excerpt', status: 'verified', data: { dividend: 120, dividend_state: 'approved', share_class: 'ordinary' }, units: { dividend: 'UZS/share' },
  } } });
  await page.reload();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  for (const [event, mode, amount] of [['decision-manual', 'manual', '120'], ['decision-automatic', 'automatic', '999']]) {
    await page.getByRole('button', { name: 'Новый материал', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Ключ события', { exact: true }).fill(event);
    await dialog.getByLabel('Режим материала', { exact: true }).selectOption(mode);
    await dialog.getByLabel('Заголовок материала').fill(event === 'decision-manual' ? 'Дивиденд утверждён' : 'Непроверенная сумма');
    await dialog.getByLabel('Текст публикации').fill(`Утверждено ${amount} сум на простую акцию.`);
    await dialog.getByLabel('Эмитент или тикер').fill('HMKB');
    await dialog.getByLabel('Прямая ссылка на UZStock').fill('https://uzstock.uz/news/123');
    await expect(dialog.getByRole('checkbox', { name: 'Связать переходы с этой публикацией', exact: true })).toBeChecked();
    await dialog.getByLabel('Решение HMKB', { exact: true }).check();
    await dialog.getByLabel('dividend · 120 UZS/share', { exact: true }).check();
    await dialog.getByRole('button', { name: 'Сохранить материал', exact: true }).click();
    const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: event === 'decision-manual' ? 'Дивиденд утверждён' : 'Непроверенная сумма', exact: true }) });
    await card.getByRole('button', { name: 'Проверить факты', exact: true }).click();
    if (mode === 'manual') {
      await expect(card.getByText('Ожидает решения', { exact: true })).toBeVisible();
      await card.getByRole('button', { name: 'Текст для отправки', exact: true }).click();
      const tracked = dialog.getByRole('link', { name: 'Ссылка с меткой публикации ↗', exact: true });
      const beforeRevision = await tracked.getAttribute('href');
      expect(beforeRevision).toMatch(/^https:\/\/uzstock\.uz\/news\/123\?uz_pub=[A-Za-z0-9_-]{32}$/);
      await expect(dialog.locator('.mkt-post-preview')).toContainText(beforeRevision);
      await expect(dialog).toContainText('Набор данных: рабочий');
      await dialog.screenshot({ path: info.outputPath(`marketing-tracked-link-${width}.png`) });
      await page.keyboard.press('Escape');
      await card.getByRole('button', { name: 'Утвердить эту версию', exact: true }).click();
      await card.getByRole('button', { name: 'Поставить в очередь', exact: true }).click();
      await expect(card.getByText('Запланирован', { exact: true })).toBeVisible();
      await card.getByRole('button', { name: 'Изменить материал', exact: true }).click();
      await dialog.getByLabel('Текст публикации').fill('Подтверждено 120 сум на простую акцию. Ссылка на решение ниже.');
      await dialog.getByRole('button', { name: 'Сохранить материал', exact: true }).click();
      await card.getByRole('button', { name: 'Текст для отправки', exact: true }).click();
      expect(await tracked.getAttribute('href')).not.toBe(beforeRevision);
      await page.keyboard.press('Escape');
      await card.getByRole('button', { name: 'Проверить факты', exact: true }).click();
      await card.getByRole('button', { name: 'Утвердить эту версию', exact: true }).click();
      await card.getByRole('button', { name: 'Поставить в очередь', exact: true }).click();
      await expect(card.getByText('Запланирован', { exact: true })).toBeVisible();
    } else {
      await expect(card.getByText('Пропущен', { exact: true })).toBeVisible();
      await expect(card).toContainText('999');
      await expect(card).toContainText('Число в тексте не связано с проверенным фактом: 999');
      await expect(card.getByRole('button', { name: 'Изменить материал' })).toHaveCount(0);
    }
  }
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Дивиденд утверждён', exact: true })).toBeVisible();
  await expect(page.getByText('Пропущен', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Календарь очереди', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Календарь очереди' })).toContainText('Telegram · тестовый аккаунт');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath(`marketing-content-${width}.png`), fullPage: true });
});

test('unreviewed draft URLs are never rendered as executable links', async ({ page }, info) => {
  const callApi = await workspace(page, info);
  callApi({ method: 'POST', path: '/api/admin/ai-marketing/candidates', body: {
    event_id: 'untrusted-link', account_id: 'draft', rubric: 'news', title: 'Черновик со ссылкой',
    body: 'Непроверенный входящий текст', destination_url: 'javascript:alert(document.domain)',
    expires_at: new Date(Date.now() + 86400000).toISOString(),
  } });
  await page.reload();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Черновик со ссылкой', exact: true }) });
  await expect(card.getByRole('link')).toHaveCount(0);
  await expect(card).toContainText('Ссылка не прошла проверку адреса');
});

for (const width of [1440, 390]) test(`research references expose their actual evidence and original fallback at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 950 });
  const callApi = await workspace(page, info);
  const stamp = Date.now();
  const excerpt = 'Один график на карточку, затем ссылка на источник.';
  for (const [id, title, status] of [['format', 'Зарубежный пример структуры', 'verified'], ['missing', 'Недоступное видео', 'unavailable']]) {
    expect(callApi({ method: 'PUT', path: `/api/admin/ai-marketing/evidence/${id}`, body: { expected_version: 0, data: {
      title, status, url: `https://example.org/${id}`, publisher: 'Example publication', rights: 'link_and_excerpt',
      published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(),
      expires_at: new Date(stamp + 86400000).toISOString(), excerpt,
    } } }).status).toBe(200);
  }
  await page.reload();
  await page.getByRole('button', { name: 'Рабочий цикл', exact: true }).click();
  await page.getByText('Новое исследование', { exact: true }).click();
  await page.getByLabel('Вопрос исследования').fill('Найти приём для объяснения квартального результата.');
  await page.getByLabel('Референс · Зарубежный пример структуры', { exact: true }).check();
  await page.getByLabel('Референс · Недоступное видео', { exact: true }).check();
  await page.getByRole('button', { name: 'Передать исследователям', exact: true }).click();
  const item = callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.tasks[0];
  expect(item.kind).toBe('research');
  const common = { questions: [], risks: [], recommendations: [], verdict: 'accept', handoff: 'Передать следующий проверяемый тест.' };
  const reference = { evidence_id: 'format', recommendation: 'adapt', observed_excerpt: excerpt, technique: 'Одна мысль и один график.', rationale: 'Упрощает сравнение периодов.', test_plan: 'Сравнить переходы к разборам на сопоставимых темах.' };
  for (const result of [
    { ...common, summary: 'Доступна только переданная выдержка.' },
    { ...common, summary: 'Сравнили доступный текст и недоступный материал.', reference_cards: [reference,
      { ...reference, evidence_id: 'missing', recommendation: 'reject', observed_excerpt: '', technique: 'Видео недоступно; его кадры не оценены.',
        rationale: 'Без доступного материала нельзя оценить приём.', test_plan: 'Получить разрешённую выдержку или продолжить со своим форматом.' },
      { ...reference, evidence_id: '', recommendation: 'original', observed_excerpt: '', technique: 'Свой формат: вопрос, график, вывод.' }] },
    { ...common, summary: 'Подготовить собственный визуал и измерить переходы.' },
  ]) callApi({ method: 'MODEL_STEP', result });
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await page.getByRole('button', { name: 'Результаты ролей', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('article', { name: 'Адаптировать приём' })).toContainText(excerpt);
  await expect(dialog).toContainText('Только выдержка');
  await expect(dialog).toContainText('Материал недоступен для анализа');
  await expect(dialog).toContainText('Сделать свой формат');
  await expect(dialog).toContainText('Источник не использован');
  await expect(dialog.getByRole('link', { name: 'Зарубежный пример структуры' })).toHaveAttribute('href', 'https://example.org/format');
  await expect(dialog).toContainText('Права: ссылка и выдержка');
  await dialog.screenshot({ path: info.outputPath(`marketing-references-${width}.png`) });
  await dialog.getByRole('article', { name: 'Сделать свой формат', exact: true }).scrollIntoViewIfNeeded();
  await dialog.screenshot({ path: info.outputPath(`marketing-reference-fallback-${width}.png`) });
  await page.keyboard.press('Escape');
  await page.reload();
  await page.getByRole('button', { name: 'Результаты ролей', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Свой формат: вопрос, график, вывод.');
  expect(callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.deliveries).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

for (const width of [1440, 390]) test(`competitor comparison preserves dated facts and undisclosed metrics at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 950 });
  const callApi = await workspace(page, info);
  const stamp = Date.now();
  const products = [['local', 'Локальный пример', 'direct', 'Тариф: 100 условных единиц в месяц.'],
    ['international', 'Зарубежный ориентир', 'inspiration', 'Тариф: 200 условных единиц в месяц.']];
  for (const [id, product, , price] of products) {
    expect(callApi({ method: 'PUT', path: `/api/admin/ai-marketing/evidence/${id}`, body: { expected_version: 0, data: {
      title: `Выдержка · ${product}`, entity: product, status: 'verified', url: `https://example.org/${id}`, publisher: product,
      rights: 'link_and_excerpt', published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(),
      expires_at: new Date(stamp + 86400000).toISOString(), excerpt: `Графики эмитентов и списки наблюдения. ${price}`,
    } } }).status).toBe(200);
  }
  await page.reload();
  await page.getByRole('button', { name: 'Рабочий цикл', exact: true }).click();
  await page.getByText('Новое исследование', { exact: true }).click();
  await page.getByLabel('Тип исследования').selectOption('competitors');
  await page.getByLabel('Вопрос исследования').fill('Сопоставить функции и видимые тарифы, не оценивать неизвестную выручку.');
  for (const [, product] of products) await page.getByLabel(`Референс · Выдержка · ${product}`, { exact: true }).check();
  await page.getByRole('button', { name: 'Передать исследователям', exact: true }).click();
  const task = callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.tasks[0];
  expect(task.kind).toBe('competitors');
  expect(task.steps).toEqual(['market', 'cmo']);
  const cards = products.map(([id, product, relationship, price]) => ({ product, relationship,
    relationship_reason: relationship === 'direct' ? 'Та же задача местного инвестора.' : 'Приём для вдохновения, другая география.',
    difference_hypothesis: 'Проверить понятность пояснений квартальных изменений.',
    facts: ['purpose', 'audience', 'features', 'pricing', 'communication', 'revenue', 'conversion', 'audience_size'].map(field => ({
      field, evidence_id: ['features', 'pricing'].includes(field) ? id : '',
      observed_excerpt: field === 'features' ? 'Графики эмитентов и списки наблюдения.' : field === 'pricing' ? price : '',
    })) }));
  const common = { questions: [], risks: [], recommendations: [], verdict: 'accept', handoff: 'Проверить гипотезу на нашей аудитории.' };
  callApi({ method: 'MODEL_STEP', result: { ...common, summary: 'Разделены конкуренты и ориентиры.', competitor_cards: cards } });
  callApi({ method: 'MODEL_STEP', result: { ...common, summary: 'Сравнение сохранено; бизнес-показатели не раскрыты.' } });
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await page.getByRole('button', { name: 'Результаты ролей', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const local = dialog.getByRole('article', { name: 'Локальный пример', exact: true });
  await expect(local).toContainText('Прямой конкурент');
  await expect(dialog.getByRole('article', { name: 'Зарубежный ориентир', exact: true })).toContainText('Ориентир для вдохновения');
  await expect(local.getByRole('row').filter({ hasText: 'Видимый тариф' })).toContainText(products[0][3]);
  for (const name of ['Выручка', 'Конверсия', 'Размер аудитории']) await expect(local.getByRole('row').filter({ hasText: name })).toContainText('Не раскрыто в выбранных материалах');
  await expect(local).toContainText('Дата получения');
  await expect(local).toContainText('Гипотеза отличия UZStock');
  await local.scrollIntoViewIfNeeded();
  await dialog.screenshot({ path: info.outputPath(`marketing-competitors-${width}.png`) });
  await local.getByRole('row').filter({ hasText: 'Размер аудитории' }).scrollIntoViewIfNeeded();
  await dialog.screenshot({ path: info.outputPath(`marketing-competitors-unknown-${width}.png`) });
  await page.keyboard.press('Escape');
  await page.reload();
  await page.getByRole('button', { name: 'Результаты ролей', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Тариф: 200 условных единиц в месяц.');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

test('team workflow produces separate channel variants and the owner selects a language', async ({ page }, info) => {
  test.setTimeout(90000);
  const callApi = await workspace(page, info);
  const stamp = Date.now();
  for (const platform of ['telegram', 'instagram', 'facebook', 'linkedin']) callApi({ method: 'PUT', path: `/api/admin/ai-marketing/accounts/${platform}`, body: { expected_version: 0, data: {
    platform, label: `${platform} · рабочий пример`, mode: 'draft', languages: ['ru', 'uz'], formats: ['post', 'image'],
  } } });
  callApi({ method: 'PUT', path: '/api/admin/ai-marketing/evidence/decision', body: { expected_version: 0, data: {
    title: 'Решение HMKB', url: 'https://openinfo.uz/facts/123', publisher: 'HMKB', entity: 'HMKB',
    published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(),
    expires_at: new Date(stamp + 86400000).toISOString(), excerpt: 'Утверждено 120 сум на простую акцию.',
    rights: 'link_and_excerpt', status: 'verified', data: { dividend: 120, dividend_state: 'approved', share_class: 'ordinary' }, units: { dividend: 'UZS/share' },
  } } });
  await page.reload();
  await page.getByRole('button', { name: 'Рабочий цикл', exact: true }).click();
  await page.getByLabel('Задание команде').fill('Подготовить решение для четырёх площадок на русском и узбекском.');
  await page.getByLabel('Точная ссылка для читателя', { exact: true }).fill('https://uzstock.uz/news/123');
  await expect(page.getByLabel('Публиковать не раньше · Ташкент')).toBeVisible();
  const localDue = new Date(stamp + 7 * 3600000).toISOString().slice(0, 16);
  await page.getByLabel('Публиковать не раньше · Ташкент').fill(localDue);
  await page.getByLabel('Ключ события', { exact: true }).fill('hmkb-decision-123');
  await page.getByLabel('Эмитент или тикер').fill('HMKB');
  for (const platform of ['telegram', 'instagram', 'facebook', 'linkedin']) await page.getByLabel(`Подготовить для ${platform} · рабочий пример`, { exact: true }).check();
  await page.getByLabel('Переход из Instagram · instagram · рабочий пример', { exact: true }).selectOption('profile');
  await page.getByLabel('Решение HMKB', { exact: true }).check();
  await page.getByRole('button', { name: 'Передать команде', exact: true }).click();
  await expect(page.getByText('Подготовить решение для четырёх площадок на русском и узбекском.', { exact: true })).toBeVisible();
  callApi({ method: 'MODEL_PRODUCTION' });
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Открыть варианты · 8', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Открыть варианты · 8', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('article')).toHaveCount(8);
  const variant = dialog.getByRole('article').filter({ has: page.getByRole('heading', { name: 'telegram · qaror', exact: true }) });
  await variant.getByRole('button', { name: 'Выбрать эту версию', exact: true }).click();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'telegram · qaror', exact: true })).toBeVisible();
  await expect(page.getByRole('article')).toHaveCount(4);
  const saved = callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body;
  expect(saved.candidates.every(item => new Date(item.not_before).getTime() === new Date(`${localDue}:00+05:00`).getTime())).toBe(true);
  expect(saved.candidates.find(item => item.account_id === 'instagram').instagram_link).toBe('profile');
  expect(saved.tasks[0].production.destination_url).toBe('https://uzstock.uz/news/123');
  await page.reload();
  await expect(page.getByText('telegram: Oddiy aksiya uchun 120 so‘m dividend tasdiqlandi.', { exact: true })).toBeVisible();
  const missing = callApi({ method: 'POST', path: '/api/admin/ai-marketing/tasks', body: { kind: 'content', message: 'Черновик ожидает точную ссылку', evidence_ids: ['decision'],
    production: { event_id: 'awaiting-reader-link', rubric: 'news', entity: 'HMKB', expires_at: new Date(stamp + 86400000).toISOString(), mode: 'draft',
      targets: [{ account_id: 'telegram', languages: ['ru'], primary_language: 'ru', format: 'post' }] },
  } });
  expect(missing.status).toBe(200);
  callApi({ method: 'MODEL_PRODUCTION' });
  await page.reload();
  const awaitingLink = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'telegram · решение', exact: true }) });
  await expect(awaitingLink).toContainText('Нужна проверенная ссылка');
  await awaitingLink.getByRole('button', { name: 'Изменить материал', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Прямая ссылка на UZStock', { exact: true }).fill('https://uzstock.uz/news/123');
  await page.getByRole('dialog').getByRole('button', { name: 'Сохранить материал', exact: true }).click();
  await awaitingLink.getByRole('button', { name: 'Проверить факты', exact: true }).click();
  await expect(awaitingLink).toContainText('Автоматические проверки пройдены');
  await expect(awaitingLink).toContainText('Ссылку выбрал владелец');
  expect(callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.deliveries).toEqual([]);
});

for (const chart of [false, true]) test(`owner renders and downloads real ${chart ? 'chart' : 'image'} media`, async ({ page }, info) => {
  await page.setViewportSize({ width: chart ? 1440 : 390, height: 940 });
  const callApi = await workspace(page, info);
  const stamp = Date.now();
  expect(callApi({ method: 'PUT', path: '/api/admin/ai-marketing/accounts/telegram', body: { expected_version: 0, data: {
    platform: 'telegram', label: 'Telegram · медиа', external_id: '-100123', mode: 'manual', formats: ['image'], rubrics: ['news', 'chart'],
    valid_until: new Date(stamp + 86400000).toISOString(),
  } } }).status).toBe(200);
  callApi({ method: 'PUT', path: '/api/admin/ai-marketing/evidence/decision', body: { expected_version: 0, data: {
    title: 'Оригинал HMKB', url: 'https://openinfo.uz/facts/123', publisher: 'HMKB', entity: 'HMKB',
    published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(),
    expires_at: new Date(stamp + 86400000).toISOString(), excerpt: 'Утверждено 120 сум на простую акцию.',
    rights: 'link_and_excerpt', status: 'verified', data: chart ? { close: [{ date: '2026-11-19', value: 120 }, { date: '2026-11-20', value: 100 }] } : { dividend: 120, dividend_state: 'approved', share_class: 'ordinary' },
    units: chart ? { close: 'UZS/share' } : { dividend: 'UZS/share' },
  } } });
  const material = callApi({ method: 'POST', path: '/api/admin/ai-marketing/candidates', body: {
    event_id: 'media-case', account_id: 'telegram', rubric: chart ? 'chart' : 'news', mode: 'manual', format: 'image', entity: 'HMKB', track_visits: true,
    title: chart ? 'Как менялась цена?' : 'Дивиденд утверждён', body: chart ? 'Динамика цены за выбранные даты.' : 'Утверждено 120 сум на простую акцию.',
    evidence_ids: ['decision'], claims: chart ? [] : [{ evidence_id: 'decision', field: 'dividend', value: 120, unit: 'UZS/share' }],
    destination_url: 'https://uzstock.uz/news/123', expires_at: new Date(stamp + 86400000).toISOString(),
  } }).body.item;
  if (chart) {
    expect(callApi({ method: 'POST', path: `/api/admin/ai-marketing/candidates/${material.id}/render`, body: { expected_version: material.version } }).status).toBe(200);
    callApi({ method: 'RENDER_STEP' });
  }
  await page.reload();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: chart ? 'Как менялась цена?' : 'Дивиденд утверждён', exact: true }) });
  if (chart) {
    await card.getByRole('button', { name: 'Проверить факты', exact: true }).click();
    await expect(card.getByText('Нужна доработка', { exact: true })).toBeVisible();
    expect(callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.candidates.find(item => item.id === material.id).check.passed).toBe(false);
  }
  await card.getByRole('button', { name: 'Создать медиа', exact: true }).click();
  const dialog = page.getByRole('dialog');
  if (chart) await dialog.getByLabel('Данные графика', { exact: true }).selectOption('decision|close');
  await dialog.getByRole('button', { name: 'Начать рендер', exact: true }).click();
  callApi({ method: 'RENDER_STEP' });
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  await card.getByRole('button', { name: 'Открыть медиа', exact: true }).click();
  await expect(dialog.getByRole('img')).toBeVisible();
  await expect(dialog.getByRole('img')).toHaveJSProperty('naturalWidth', 1080);
  await expect(dialog).toContainText('JPEG');
  await expect(dialog.getByRole('link', { name: 'Скачать файл', exact: true })).toHaveAttribute('download', /\.jpg$/);
  const imageDownload = page.waitForEvent('download');
  await dialog.getByRole('link', { name: 'Скачать файл', exact: true }).click();
  const imageFile = await imageDownload;
  expect(imageFile.suggestedFilename()).toMatch(/\.jpg$/);
  const jpeg = readFileSync(await imageFile.path());
  expect([jpeg[0], jpeg[1], jpeg[2]]).toEqual([0xff, 0xd8, 0xff]);
  await expect(dialog).toContainText('UZS/share');
  if (chart) {
    const download = page.waitForEvent('download');
    await dialog.getByRole('button', { name: 'Скачать данные CSV', exact: true }).click();
    expect((await download).suggestedFilename()).toMatch(/\.csv$/);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath(`marketing-media-${chart ? 'chart' : 'image'}.png`), fullPage: true });
  await page.keyboard.press('Escape');
  await expect(card.getByRole('button', { name: 'Открыть медиа', exact: true })).toBeFocused();
  const download = page.waitForEvent('download');
  await card.getByRole('button', { name: 'Скачать черновик ZIP', exact: true }).click();
  const archiveFile = await download;
  expect(archiveFile.suggestedFilename()).toMatch(/\.zip$/);
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  const exported = JSON.parse(execFileSync(python, ['-X', 'utf8', '-c',
    "import json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); print(json.dumps({'text':z.read('draft.txt').decode(),'package':json.loads(z.read('material.json'))}))", await archiveFile.path()], { encoding: 'utf8' }));
  const preview = callApi({ method: 'GET', path: `/api/admin/ai-marketing/candidates/${material.id}/publication-preview` }).body;
  expect(exported.text).toBe(preview.text);
  expect(exported.text).toContain(preview.tracked_destination);
  expect(exported.package.publication.text).toBe(preview.text);
  await card.getByRole('button', { name: 'Проверить факты', exact: true }).click();
  await expect(card.getByText('Ожидает решения', { exact: true })).toBeVisible();
});

test('owner confirms founder wording, uses it in a personal post, then revokes it', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 940 });
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_theme', 'light'));
  const callApi = await workspace(page, info);
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  await page.getByRole('button', { name: 'Добавить факт основателя', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Название факта', { exact: true }).fill('Роль в UZStock');
  await dialog.getByLabel('Подтверждающая ссылка', { exact: true }).fill('https://uzstock.uz/about');
  await dialog.getByLabel('Основание подтверждения', { exact: true }).fill('Роль сверена владельцем продукта.');
  await dialog.getByLabel('Разрешённые формулировки · Русский', { exact: true }).fill('Я развиваю UZStock.');
  await dialog.getByLabel('Я проверил факт и разрешаю эти формулировки', { exact: true }).check();
  await dialog.getByRole('button', { name: 'Сохранить факт', exact: true }).click();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Роль в UZStock', exact: true })).toBeVisible();
  await page.getByRole('heading', { name: 'Роль в UZStock', exact: true }).scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('marketing-founder-mobile.png'), fullPage: true });
  const data = callApi({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body;
  expect(data.founder_facts[0].status).toBe('verified');
  const stamp = Date.now();
  expect(callApi({ method: 'PUT', path: '/api/admin/ai-marketing/accounts/personal', body: { expected_version: 0, data: {
    platform: 'linkedin', label: 'Личный профиль', external_id: 'owner', personal_profile: true, mode: 'manual', formats: ['post'], rubrics: ['news'],
    valid_until: new Date(stamp + 86400000).toISOString(),
  } } }).status).toBe(200);
  callApi({ method: 'PUT', path: '/api/admin/ai-marketing/evidence/decision', body: { expected_version: 0, data: {
    title: 'Решение HMKB', url: 'https://openinfo.uz/facts/123', publisher: 'HMKB', entity: 'HMKB',
    published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(),
    expires_at: new Date(stamp + 86400000).toISOString(), excerpt: 'Утверждено 120 сум на простую акцию.',
    rights: 'link_and_excerpt', status: 'verified', data: { dividend: 120, dividend_state: 'approved', share_class: 'ordinary' }, units: { dividend: 'UZS/share' },
  } } });
  await page.reload();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  await page.getByRole('button', { name: 'Новый материал', exact: true }).click();
  await dialog.getByLabel('Ключ события', { exact: true }).fill('personal-decision');
  await dialog.getByLabel('Режим материала').selectOption('manual');
  await dialog.getByLabel('Заголовок материала').fill('Личная заметка');
  await dialog.getByLabel('Текст публикации').fill('Я развиваю UZStock. Утверждено 120 сум на простую акцию.');
  await dialog.getByLabel('Эмитент или тикер').fill('HMKB');
  await dialog.getByLabel('Прямая ссылка на UZStock').fill('https://uzstock.uz/news/123');
  await dialog.getByLabel('Решение HMKB', { exact: true }).check();
  await dialog.getByLabel('dividend · 120 UZS/share', { exact: true }).check();
  await dialog.getByLabel('Роль в UZStock', { exact: true }).check();
  await dialog.getByRole('button', { name: 'Сохранить материал', exact: true }).click();
  await page.getByRole('button', { name: 'Проверить факты', exact: true }).click();
  await expect(page.getByText('Ожидает решения', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  const fact = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Роль в UZStock', exact: true }) });
  await fact.getByRole('button', { name: 'Отозвать факт', exact: true }).click();
  await expect(fact.getByText('Отключён', { exact: true })).toBeVisible();
  await fact.getByRole('button', { name: 'История факта', exact: true }).click();
  await expect(dialog).toContainText('Версия 1');
  await expect(dialog).toContainText('Версия 2');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  await page.getByRole('button', { name: 'Проверить факты', exact: true }).click();
  await expect(page.getByText('Нужна доработка', { exact: true })).toBeVisible();
});
