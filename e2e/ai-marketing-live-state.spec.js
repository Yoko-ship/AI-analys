import { test, expect } from '@playwright/test';
import { workspace } from './helpers/marketing-workspace.js';

for (const width of [1440, 390]) test(`background work refreshes without losing edits and recovers from read failures at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 950 });
  await page.clock.install();
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  const title = 'Проверить подтверждённые темы';
  expect(callApi({ method: 'POST', path: `${base}/tasks`, body: { kind: 'draft', message: title } }).status).toBe(200);
  await page.reload();
  await page.getByRole('button', { name: 'Рабочий цикл', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: title, exact: true }) });
  await expect(card).toContainText('В очереди');
  const message = page.getByLabel('Задание команде', { exact: true });
  await message.fill('Этот несохранённый текст должен остаться.');
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  let reads = 0, fail = false;
  await page.route('**/api/admin/ai-marketing/workspace', async route => {
    reads += 1;
    if (fail) return route.fulfill({ status: 503, json: { error: { message: 'Временно недоступно' } } });
    const result = callApi({ method: 'GET', path: `${base}/workspace` });
    await route.fulfill({ status: result.status, json: result.body });
  });
  await card.getByRole('button', { name: 'Результаты ролей', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Завершённых шагов пока нет');
  for (let i = 0; i < 3; i++) callApi({ method: 'MODEL_STEP' });
  await page.clock.fastForward(16000);
  await expect(dialog).toContainText('Сначала замерим открытия отчётов');
  await page.screenshot({ path: info.outputPath(`marketing-live-dialog-${width}.png`) });
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click();
  await expect(card).toContainText('Готово');
  await expect(message).toHaveValue('Этот несохранённый текст должен остаться.');
  fail = true;
  await page.clock.fastForward(16000);
  const sync = page.getByRole('region', { name: 'Обновление состояния', exact: true });
  await expect(sync).toContainText('Автообновление недоступно');
  await expect(card).toContainText('Готово');
  await expect(message).toHaveValue('Этот несохранённый текст должен остаться.');
  await sync.evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath(`marketing-refresh-error-${width}.png`) });
  fail = false;
  await sync.getByRole('button', { name: 'Обновить состояние', exact: true }).click();
  await expect(sync).not.toContainText('Автообновление недоступно');
  await expect(sync).toContainText('Ташкент');
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  const beforeHidden = reads;
  await page.clock.fastForward(60000);
  expect(reads).toBe(beforeHidden);
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect.poll(() => reads).toBeGreaterThan(beforeHidden);
  await expect(message).toHaveValue('Этот несохранённый текст должен остаться.');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('a delayed background response cannot undo the displayed owner cancellation', async ({ page }, info) => {
  await page.clock.install();
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  const title = 'Задача для отмены';
  callApi({ method: 'POST', path: `${base}/tasks`, body: { kind: 'research', message: title } });
  await page.reload();
  await page.getByRole('button', { name: 'Рабочий цикл', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: title, exact: true }) });
  await expect(card).toContainText('В очереди');
  let held, captured, reads = 0;
  await page.route('**/api/admin/ai-marketing/workspace', async route => {
    reads += 1;
    const result = callApi({ method: 'GET', path: `${base}/workspace` });
    if (!captured) { captured = result; held = route; return; }
    await route.fulfill({ status: result.status, json: result.body });
  });
  await page.clock.fastForward(16000);
  await expect.poll(() => Boolean(held)).toBe(true);
  await page.clock.fastForward(60000);
  expect(reads).toBe(1);
  await card.getByRole('button', { name: 'Отменить задачу', exact: true }).click();
  await expect(card).toContainText('Отменён');
  await held.fulfill({ status: captured.status, json: captured.body });
  await page.clock.fastForward(16000);
  await expect(card).toContainText('Отменён');
  await expect(card.getByRole('button', { name: 'Отменить задачу', exact: true })).toHaveCount(0);
});

test('a newer saved goal cannot replace edits or silently change their expected version', async ({ page }, info) => {
  await page.clock.install();
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  const goal = { title: 'Исходная цель владельца', metric: 'report_open', formula: 'confirmed report opens', unit: 'events',
    source: 'product events', baseline: null, target: 100, starts_on: '2026-11-23', deadline: '2026-12-23', budget: 0,
    currency: 'UZS', audiences: ['Начинающие инвесторы'] };
  const first = callApi({ method: 'PUT', path: `${base}/goal`, body: { data: goal, expected_version: 0 } });
  expect(first.status).toBe(200);
  await page.reload();
  await page.getByRole('button', { name: 'Цель и стратегия', exact: true }).click();
  const title = page.getByLabel('Бизнес-цель', { exact: true });
  await title.fill('Несохранённая правка владельца');
  const latest = callApi({ method: 'GET', path: `${base}/workspace` }).body.goal;
  expect(callApi({ method: 'PUT', path: `${base}/goal`, body: { data: { ...goal, title: 'Другая сохранённая версия' }, expected_version: latest.version } }).status).toBe(200);
  await page.clock.fastForward(16000);
  await expect(page.getByText('На сервере появилась новая версия.', { exact: true })).toBeVisible();
  await expect(title).toHaveValue('Несохранённая правка владельца');
  await title.evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath('marketing-live-goal-conflict.png') });
  const form = page.locator('form').filter({ has: title });
  await form.locator('button[type="submit"], button:not([type])').first().click();
  await expect(page.locator('#marketing-error')).not.toBeEmpty();
  expect(callApi({ method: 'GET', path: `${base}/workspace` }).body.goal.title).toBe('Другая сохранённая версия');
  await page.getByRole('button', { name: 'Загрузить новую версию и сбросить правки', exact: true }).click();
  await expect(title).toHaveValue('Другая сохранённая версия');
});

test('calculation edits expose a newer version inside the open dialog', async ({ page }, info) => {
  await page.clock.install();
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  await page.getByRole('button', { name: 'Отчёты', exact: true }).click();
  await page.getByRole('button', { name: 'Настроить расчёты', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const window = dialog.getByLabel('Окно атрибуции, дней', { exact: true });
  await window.fill('13');
  const current = callApi({ method: 'GET', path: `${base}/workspace` }).body.analytics_settings;
  expect(callApi({ method: 'PUT', path: `${base}/reports/settings`, body: { data: { ...current.data, attribution_days: 21 }, expected_version: current.version } }).status).toBe(200);
  await page.clock.fastForward(16000);
  await expect(window).toHaveValue('13');
  await expect(dialog.getByText('На сервере появилась новая версия.', { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('marketing-live-report-conflict.png') });
  await dialog.getByRole('button', { name: 'Загрузить новую версию и сбросить правки', exact: true }).click();
  await expect(window).toHaveValue('21');
});

test('reading website status retains unsaved source settings and their version', async ({ page }, info) => {
  await page.clock.install();
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  await page.getByRole('button', { name: 'Отчёты', exact: true }).click();
  const interval = page.getByLabel('Повторный обход, минут', { exact: true });
  await interval.fill('60');
  const current = callApi({ method: 'GET', path: `${base}/workspace` }).body.website.settings;
  expect(callApi({ method: 'PUT', path: `${base}/reports/website`, body: { expected_version: current.version,
    data: { enabled: false, dataset: 'production', starts_on: '2026-11-23', interval_minutes: 30 } } }).status).toBe(200);
  await page.clock.fastForward(16000);
  await expect(page.getByText('На сервере появилась новая версия.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Обновить состояние сайта', exact: true }).click();
  await expect(interval).toHaveValue('60');
  await expect(page.getByText('На сервере появилась новая версия.', { exact: true })).toBeVisible();
});
