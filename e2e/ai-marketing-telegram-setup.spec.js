import { test, expect } from '@playwright/test';
import { workspace } from './helpers/marketing-workspace.js';

for (const width of [1440, 390]) test(`Telegram daily schedule persists at ${width}px`, async ({ page }, info) => {
  test.setTimeout(90000);
  page.setDefaultTimeout(15000);
  await page.setViewportSize({ width, height: 950 });
  const api = await workspace(page, info), base = '/api/admin/ai-marketing';
  api({ method: 'TELEGRAM_CONFIGURE' });
  expect(api({ method: 'POST', path: `${base}/telegram/connect`, body: { channel: '-100123', expected_version: 0 } }).status).toBe(200);
  await page.reload();
  const panel = page.getByRole('region', { name: 'Telegram', exact: true });
  await panel.getByLabel('Постов в день', { exact: true }).fill('3');
  await panel.getByLabel('Когда публиковать', { exact: true }).selectOption('times');
  for (const [i, time] of ['10:00', '14:00', '18:00'].entries()) {
    await panel.getByLabel(`Время поста ${i + 1}`, { exact: true }).fill(time);
  }
  await panel.getByRole('button', { name: 'Сохранить расписание', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Расписание сохранено' })).toBeVisible();
  await page.reload();
  await expect(panel.getByLabel('Постов в день', { exact: true })).toHaveValue('3');
  await expect(panel.getByLabel('Время поста 2', { exact: true })).toHaveValue('14:00');
  let saved = api({ method: 'GET', path: `${base}/workspace` }).body.accounts[0];
  expect(saved.news_publish_times).toEqual(['10:00:00', '14:00:00', '18:00:00']);
  expect(saved.news_daily_limit).toBe(3);
  // Updating other channel rules must not erase its schedule.
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  await page.getByRole('button', { name: 'Настроить Telegram UZStock', exact: true }).click();
  await page.getByRole('button', { name: 'Сохранить правила аккаунта', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Правила аккаунта сохранены' })).toBeVisible();
  saved = api({ method: 'GET', path: `${base}/workspace` }).body.accounts[0];
  expect(saved.news_publish_times).toEqual(['10:00:00', '14:00:00', '18:00:00']);
  await page.getByRole('button', { name: 'Обзор команды', exact: true }).click();
  await page.reload();
  await panel.getByLabel('Время поста 2', { exact: true }).fill('10:00');
  await panel.getByRole('button', { name: 'Сохранить расписание', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Для каждого поста нужно отдельное время');
  await expect(panel.getByLabel('Время поста 2', { exact: true })).toHaveAttribute('aria-invalid', 'true');
  expect(api({ method: 'GET', path: `${base}/workspace` }).body.accounts[0].news_publish_times).toEqual(saved.news_publish_times);
  await panel.getByLabel('Время поста 2', { exact: true }).fill('14:00');
  await panel.getByRole('button', { name: 'Сохранить расписание', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Расписание сохранено' })).toBeVisible();
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath(`telegram-schedule-${width}.png`), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await panel.getByLabel('Когда публиковать', { exact: true }).selectOption('ready');
  await panel.getByRole('button', { name: 'Сохранить расписание', exact: true }).click();
  await page.reload();
  await expect(panel.getByLabel('Когда публиковать', { exact: true })).toHaveValue('ready');
  expect(api({ method: 'GET', path: `${base}/workspace` }).body.accounts[0].news_publish_times).toEqual([]);
});

for (const width of [1440, 390]) test(`Telegram connects without campaign configuration at ${width}px`, async ({ page }, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width, height: 950 });
  const api = await workspace(page, info);
  api({ method: 'TELEGRAM_CONFIGURE' });
  await page.reload();
  const panel = page.getByRole('region', { name: 'Telegram', exact: true });
  await panel.getByLabel('Канал Telegram', { exact: true }).fill('-100456');
  await panel.getByRole('button', { name: 'Подключить канал', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('Проверьте ID канала');
  await panel.getByLabel('Канал Telegram', { exact: true }).fill('-100123');
  await panel.getByRole('button', { name: 'Подключить канал', exact: true }).click();
  await expect(panel).toContainText('Канал подключён');
  await expect(panel).toContainText('автоматически');
  await expect(panel.getByLabel('Ключ события')).toHaveCount(0);
  await page.reload();
  await expect(panel).toContainText('Канал подключён');
  const result = api({ method: 'GET', path: '/api/admin/ai-marketing/workspace' });
  expect(result.status).toBe(200);
  expect(result.body.accounts[0]).toMatchObject({ automatic_news: true, connection_status: 'connected', valid_until: null });
  expect(result.body.goal).toBeNull();
  expect(result.body.strategies).toEqual([]);
  expect(result.body.editorial_rules).toEqual([]);
  await panel.getByRole('button', { name: 'Приостановить Telegram', exact: true }).click();
  await expect(panel).toContainText('На паузе');
  await page.reload();
  await expect(panel).toContainText('На паузе');
  await panel.getByRole('button', { name: 'Возобновить Telegram', exact: true }).click();
  await expect(panel.getByRole('button', { name: 'Приостановить Telegram', exact: true })).toBeVisible();
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath(`telegram-connected-${width}.png`) });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

for (const width of [1440, 390]) test(`Telegram branded news preview at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 950 });
  const api = await workspace(page, info), base = '/api/admin/ai-marketing', now = Date.now();
  api({ method: 'TELEGRAM_CONFIGURE' });
  expect(api({ method: 'POST', path: `${base}/telegram/connect`, body: { channel: '-100123', expected_version: 0 } }).status).toBe(200);
  const original = 'https://www.uzdaily.uz/ru/fitch-podtverdila-reiting-sqb-insurance-na-urovne-bb';
  expect(api({ method: 'PUT', path: `${base}/evidence/rating`, body: { expected_version: 0, data: {
    title: 'SQB Insurance', url: original, publisher: 'UzDaily.uz', rights: 'link_and_excerpt', status: 'verified',
    published_at: new Date(now - 3600000).toISOString(), retrieved_at: new Date(now).toISOString(),
    expires_at: new Date(now + 86400000).toISOString(), excerpt: 'Fitch подтвердило рейтинг BB.',
  } } }).status).toBe(200);
  expect(api({ method: 'POST', path: `${base}/candidates`, body: {
    event_id: 'news:10528', account_id: 'telegram', mode: 'draft', rubric: 'news', language: 'ru',
    title: 'Рейтинг SQB Insurance', body: `По сообщению UzDaily.uz, Fitch подтвердило рейтинг BB.\n\nИсточник: UzDaily.uz — ${original}`,
    evidence_ids: ['rating'], destination_url: 'https://uzstock.uz/news/10528', expires_at: new Date(now + 86400000).toISOString(),
  } }).status).toBe(200);
  await page.reload();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Рейтинг SQB Insurance', exact: true }) })
    .filter({ has: page.getByRole('button', { name: 'Текст для отправки', exact: true }) });
  await card.getByRole('button', { name: 'Текст для отправки', exact: true }).click();
  const preview = page.getByRole('dialog').locator('.mkt-post-preview');
  await expect(preview.getByRole('link', { name: 'Опубликовано на UZStock', exact: true })).toHaveAttribute('href', 'https://uzstock.uz/news/10528');
  await expect(preview).not.toContainText('https://');
  await expect(preview).not.toContainText('UzDaily');
  await expect(preview).not.toContainText('uzdaily.uz');
  await expect(page.getByRole('dialog')).not.toContainText('Текст включает прямую ссылку и оригиналы');
  await page.getByRole('dialog').screenshot({ path: info.outputPath(`telegram-branding-${width}.png`) });
});
