import { test, expect } from '@playwright/test';
import { workspace } from './helpers/marketing-workspace.js';

for (const width of [1440, 390]) test(`owner bounds automatic event selection and revokes queued work at ${width}px`, async ({ page }, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width, height: 950 });
  if (width === 390) await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_theme', 'light'));
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  const invoke = (method, path, body) => {
    const result = callApi({ method, path: base + path, body });
    expect(result.status, JSON.stringify(result.body)).toBe(200);
    return result.body;
  };
  const goal = { title: 'Подтверждённые открытия', metric: 'report_open', formula: 'Подтверждённые открытия', unit: 'events', source: 'События сайта',
    target: 100, budget: 0, currency: 'UZS', starts_on: '2026-11-23', deadline: '2026-12-23' };
  invoke('PUT', '/goal', { data: goal, expected_version: 0 });
  invoke('POST', '/goal/approve', { expected_version: 1 });
  const proposed = invoke('POST', '/strategies', { expected_version: 0, data: {
    title: 'Проверенные новости', goal_version: 2, segments: ['Инвесторы'], positioning: 'Объясняем оригиналы', channels: ['telegram'], rubrics: ['news'],
    measurement: 'Подтверждённые открытия', steps: [{ id: 'news', owner: 'copywriter', action: 'Объяснять подтверждённые решения', deliverable: 'Проверенные материалы',
      starts_on: '2026-11-23', due: '2026-12-23', mode: 'organic', channel: 'telegram', rubric: 'news', budget: 0, dependencies: [] }],
    kpis: [{ metric: goal.metric, formula: goal.formula, unit: goal.unit, source: goal.source, target: 100, owner: 'analytics', checkpoint: goal.deadline }],
    scenarios: ['conservative', 'base', 'target'].map(kind => ({ kind, assumptions: ['Отклик неизвестен'], actions: ['Замерить'], resources: 'Редакция',
      budget: 0, constraints: ['Без расходов'], risks: ['Нет базы'], checkpoint: '2026-12-20', formula: 'Охват × отклик', measurement_plan: 'Полное окно' })),
  } }).item;
  invoke('POST', `/strategies/${proposed.id}/approve`, { expected_version: 1 });
  invoke('PUT', '/accounts/tg', { expected_version: 0, data: { platform: 'telegram', label: 'Telegram · редакция', mode: 'draft', rubrics: ['news'], languages: ['ru'], formats: ['post'] } });
  invoke('PUT', '/sources/disclosures', { expected_version: 0, data: { name: 'Подписанные раскрытия', url: 'https://openinfo.uz', category: 'issuer', method: 'manual',
    language: 'ru', owner: 'owner', geography: 'UZ', topics: ['issuers'], frequency_minutes: 60, stale_after_hours: 24,
    rights: 'link_and_excerpt', terms_checked_on: '2026-11-23', may_store: true, may_display: true, commercial_use: true } });
  const material = { source_item_id: '123', canonical_event_id: 'decision-123', title: 'Подтверждённое решение HMKB', url: 'https://openinfo.uz/facts/123',
    publisher: 'HMKB', entity: 'HMKB', published_at: new Date(Date.now() - 3600000).toISOString(), event_at: new Date(Date.now() - 7200000).toISOString(),
    excerpt: 'Утверждено 120 сум на простую акцию.', data: { dividend: 120, dividend_state: 'approved', share_class: 'ordinary' },
    units: { dividend: 'UZS/share' }, rights: 'link_and_excerpt', suggested_rubric: 'news', destination_url: 'https://uzstock.uz/news/123' };
  invoke('POST', '/sources/disclosures/import', { materials: [material] });
  await page.getByRole('button', { name: 'Рабочий цикл', exact: true }).click();
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await page.getByRole('button', { name: 'Добавить редакционное правило', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Название правила', { exact: true }).fill('Срочные решения эмитентов');
  await dialog.getByLabel('Утверждённая стратегия', { exact: true }).selectOption(proposed.id);
  await dialog.getByLabel('Аккаунт', { exact: true }).selectOption('tg');
  await dialog.getByLabel('Рубрика', { exact: true }).selectOption('news');
  await dialog.getByLabel('Приоритет', { exact: true }).selectOption('urgent');
  await dialog.getByLabel('Заданий за день', { exact: true }).fill('1');
  await dialog.getByLabel('Возраст события, часов', { exact: true }).fill('24');
  await dialog.getByLabel('Конец периода', { exact: true }).fill('2026-12-20');
  await expect(dialog.getByLabel('Включить автоматический выбор', { exact: true })).not.toBeChecked();
  await dialog.getByRole('button', { name: 'Сохранить правило', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('Выберите источники');
  await dialog.getByLabel('Подписанные раскрытия', { exact: true }).check();
  await dialog.getByLabel('Название правила', { exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath(`marketing-automation-form-${width}.png`) });
  await dialog.getByRole('button', { name: 'Сохранить правило', exact: true }).click();
  const card = page.getByRole('article', { name: 'Срочные решения эмитентов', exact: true });
  await expect(card).toContainText('Отключён');
  await expect(card).toContainText('Только черновики');
  await card.getByRole('button', { name: 'Изменить правило', exact: true }).click();
  await expect(dialog.getByLabel('Подписанные раскрытия', { exact: true })).toBeChecked();
  await dialog.getByLabel('Включить автоматический выбор', { exact: true }).check();
  await dialog.getByRole('button', { name: 'Сохранить правило', exact: true }).click();
  expect(callApi({ method: 'WORKER_STEP' }).body.editorial_work).toBe(false);
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await expect(card).toContainText('Нет нового проверенного события');
  const original = invoke('GET', '/workspace').evidence[0];
  invoke('POST', `/evidence/${original.id}/verify`, { expected_version: original.version, reason: 'Сверено с подписанным оригиналом' });
  expect(callApi({ method: 'WORKER_STEP' }).body.editorial_work).toBe(true);
  await page.reload();
  await expect(card).toContainText('Подтверждённое решение HMKB');
  await expect(card).toContainText('Срочная подтверждённая новость');
  await card.getByRole('button', { name: 'Передачи выбранного события', exact: true }).click();
  await expect(dialog).toContainText('Сначала замерим открытия отчётов');
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click();
  expect(invoke('GET', '/workspace').deliveries).toEqual([]);
  await card.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath(`marketing-automation-assigned-${width}.png`) });
  await card.getByRole('button', { name: 'Отключить правило', exact: true }).click();
  callApi({ method: 'MODEL_STEP' });
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await expect(card).toContainText('Отключён');
  await expect(card).toContainText('Правило автоматического выбора изменено или отключено');
  await card.getByRole('button', { name: 'История правила', exact: true }).click();
  await expect(dialog).toContainText('Версия 3');
  await expect(dialog).not.toContainText('NaN');
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click();
  const state = invoke('GET', '/workspace');
  expect(state.tasks).toHaveLength(1);
  expect(state.tasks[0].status).toBe('blocked');
  expect(state.deliveries).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
