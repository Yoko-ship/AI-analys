import { test, expect } from '@playwright/test';
import { workspace } from './helpers/marketing-workspace.js';

for (const width of [1440, 390]) test(`approved plan work respects dependencies and records owner results at ${width}px`, async ({ page }, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width, height: 950 });
  if (width === 390) await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_theme', 'light'));
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  const goal = { title: 'Проверяемые открытия отчётов', metric: 'report_open', formula: 'Подтверждённые открытия', unit: 'events', source: 'События сайта',
    target: 100, budget: 0, currency: 'UZS', starts_on: '2026-11-23', deadline: '2026-12-23' };
  expect(callApi({ method: 'PUT', path: `${base}/goal`, body: { data: goal, expected_version: 0 } }).status).toBe(200);
  expect(callApi({ method: 'POST', path: `${base}/goal/approve`, body: { expected_version: 1 } }).status).toBe(200);
  const taskStep = (id, owner, action, dependencies = []) => ({ id, owner, action, dependencies, starts_on: '2026-11-23', due: '2026-11-23',
    mode: 'operations', channel: 'internal', rubric: '', budget: 0, deliverable: 'Проверяемый результат с ограничениями' });
  const plan = { title: 'Рабочая неделя команды', goal_version: 2, segments: ['Начинающие инвесторы'], positioning: 'Объясняем оригиналы',
    channels: ['telegram'], rubrics: ['quarterly', 'news'], measurement: 'Подтверждённые открытия без подстановки нулей',
    steps: [taskStep('brief', 'pr', 'Сформулировать редакционный бриф'), taskStep('research', 'market', 'Исследовать утверждённый бриф', ['brief']),
      taskStep('owner', 'owner', 'Сверить исходную выгрузку', ['brief']),
      { ...taskStep('draft', 'copywriter', 'Подготовить проверенный черновик', ['brief']), mode: 'organic', channel: 'telegram', rubric: 'news' }],
    kpis: [{ metric: goal.metric, formula: goal.formula, unit: goal.unit, source: goal.source, target: goal.target, owner: 'analytics', checkpoint: goal.deadline }],
    scenarios: ['conservative', 'base', 'target'].map(kind => ({ kind, assumptions: ['Отклик неизвестен'], actions: ['Сначала замерить'], resources: 'Существующая команда',
      budget: 0, constraints: ['Без расходов'], risks: ['Нет базы'], checkpoint: '2026-12-01', formula: 'Измеренный охват × отклик', measurement_plan: 'Сверить полное окно' })),
  };
  const proposed = callApi({ method: 'POST', path: `${base}/strategies`, body: { data: plan, expected_version: 0 } }).body.item;
  expect(callApi({ method: 'POST', path: `${base}/strategies/${proposed.id}/approve`, body: { expected_version: 1 } }).status).toBe(200);
  const stamp = Date.now();
  expect(callApi({ method: 'PUT', path: `${base}/accounts/telegram`, body: { expected_version: 0, data: {
    platform: 'telegram', label: 'Telegram · план', mode: 'draft', languages: ['ru', 'uz'], formats: ['post'],
  } } }).status).toBe(200);
  expect(callApi({ method: 'PUT', path: `${base}/evidence/decision`, body: { expected_version: 0, data: {
    title: 'Решение для рабочего плана', url: 'https://openinfo.uz/facts/123', publisher: 'HMKB', entity: 'HMKB',
    published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(), expires_at: new Date(stamp + 86400000).toISOString(),
    excerpt: 'Утверждено 120 сум на простую акцию.', rights: 'link_and_excerpt', status: 'verified',
    data: { dividend: 120, dividend_state: 'approved', share_class: 'ordinary' }, units: { dividend: 'UZS/share' },
  } } }).status).toBe(200);
  await page.getByRole('button', { name: 'Цель и стратегия', exact: true }).click();
  await page.getByRole('button', { name: 'Обновить обсуждение', exact: true }).click();
  await page.getByRole('button', { name: 'Открыть полный план', exact: true }).click();
  await page.getByRole('button', { name: 'Добавить шаги в рабочий цикл', exact: true }).click();
  await page.getByRole('button', { name: 'Рабочий цикл', exact: true }).click();
  const first = page.getByRole('article', { name: 'Сформулировать редакционный бриф', exact: true });
  const second = page.getByRole('article', { name: 'Исследовать утверждённый бриф', exact: true });
  const owner = page.getByRole('article', { name: 'Сверить исходную выгрузку', exact: true });
  await expect(first).toContainText('Просрочено');
  await expect(second.getByRole('button', { name: 'Подготовить задание', exact: true })).toBeDisabled();
  await second.getByRole('button', { name: 'Подготовить заранее', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Решение для рабочего плана', { exact: true }).check();
  await page.getByRole('dialog').getByRole('button', { name: 'Сохранить для автоматического старта', exact: true }).click();
  await expect(second).toContainText('Ожидает автоматического старта');
  await second.getByRole('button', { name: 'Отменить автоматический старт', exact: true }).click();
  await expect(second).toContainText('Ожидает назначения');
  await second.getByRole('button', { name: 'Подготовить заранее', exact: true }).click();
  await expect(page.getByRole('dialog').getByLabel('Решение для рабочего плана', { exact: true })).toBeChecked();
  await page.getByRole('dialog').getByRole('button', { name: 'Сохранить для автоматического старта', exact: true }).click();
  await page.reload();
  await second.getByText('Сохранённые входные данные', { exact: false }).click();
  await expect(second).toContainText('Решение для рабочего плана · версия 1');
  await first.getByRole('button', { name: 'Подготовить задание', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Назначить задачу', exact: true }).click();
  callApi({ method: 'MODEL_STEP' });
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await expect(second).toContainText('Ожидает автоматического старта');
  callApi({ method: 'MODEL_STEP' });
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await expect(first).toContainText('Готово');
  const { id: originalId, version: originalVersion, updated_at: originalUpdatedAt, ...originalData } = callApi({ method: 'GET', path: `${base}/workspace` }).body.evidence.find(value => value.id === 'decision');
  expect(originalUpdatedAt).toBeTruthy();
  expect(callApi({ method: 'PUT', path: `${base}/evidence/${originalId}`, body: { expected_version: originalVersion,
    data: { ...originalData, excerpt: `${originalData.excerpt} Сверено с оригиналом повторно.` } } }).status).toBe(200);
  expect(callApi({ method: 'WORKER_STEP' }).body.plan_work).toBe(false);
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await expect(second).toContainText('Подготовленный оригинал изменился');
  await second.evaluate(element => element.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await second.screenshot({ path: info.outputPath(`marketing-plan-inputs-changed-${width}.png`) });
  await second.getByRole('button', { name: 'Подготовить заранее', exact: true }).click();
  await expect(page.getByRole('dialog').getByLabel('Решение для рабочего плана', { exact: true })).toBeChecked();
  await page.getByRole('dialog').getByRole('button', { name: 'Сохранить для автоматического старта', exact: true }).click();
  expect(callApi({ method: 'WORKER_STEP' }).body.plan_work).toBe(true);
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await expect(second).toContainText('Результат задачи');
  expect(callApi({ method: 'WORKER_STEP' }).body.plan_work).toBe(false);
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await expect(second).toContainText('Готово');
  await owner.getByRole('button', { name: 'Записать результат владельца', exact: true }).click();
  await page.getByLabel('Что выполнено', { exact: true }).fill('Сверена полная исходная выгрузка регистраций за выбранный период.');
  await page.getByLabel('Основание результата', { exact: true }).fill('Исходный реестр и сверка дат завершения регистрации.');
  await page.getByRole('dialog').getByRole('button', { name: 'Сохранить результат', exact: true }).click();
  await expect(owner).toContainText('Готово');
  await page.reload();
  await expect(owner).toContainText('Исходный реестр');
  const draft = page.getByRole('article', { name: 'Подготовить проверенный черновик', exact: true });
  await draft.getByRole('button', { name: 'Подготовить заранее', exact: true }).click();
  const drafting = page.getByRole('dialog');
  await expect(drafting).toContainText('Публикация рассматривается отдельно');
  await drafting.getByLabel('Ключ события', { exact: true }).fill('plan-hmkb-decision');
  await drafting.getByLabel('Точная ссылка для читателя', { exact: true }).fill('https://uzstock.uz/news/123');
  await drafting.getByLabel('Точная ссылка для читателя', { exact: true }).evaluate(element => element.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath(`marketing-plan-reader-destination-${width}.png`) });
  await drafting.getByLabel('Эмитент или тикер', { exact: true }).fill('HMKB');
  await drafting.getByLabel('Подготовить для Telegram · план', { exact: true }).check();
  await drafting.getByLabel('Решение для рабочего плана', { exact: true }).check();
  await drafting.getByRole('button', { name: 'Сохранить для автоматического старта', exact: true }).click();
  await draft.getByRole('button', { name: 'Изменить подготовку', exact: true }).click();
  await expect(drafting.getByLabel('Ключ события', { exact: true })).toHaveValue('plan-hmkb-decision');
  await expect(drafting.getByLabel('Точная ссылка для читателя', { exact: true })).toHaveValue('https://uzstock.uz/news/123');
  await expect(drafting.getByLabel('Подготовить для Telegram · план', { exact: true })).toBeChecked();
  await expect(drafting.getByLabel('Решение для рабочего плана', { exact: true })).toBeChecked();
  await page.keyboard.press('Escape');
  await draft.evaluate(element => element.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await draft.screenshot({ path: info.outputPath(`marketing-plan-prepared-${width}.png`) });
  expect(callApi({ method: 'WORKER_STEP' }).body.plan_work).toBe(true);
  callApi({ method: 'MODEL_PRODUCTION' });
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await expect(draft).toContainText('Готово');
  await draft.getByRole('button', { name: 'Открыть варианты · 2', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('article')).toHaveCount(2);
  const variant = page.getByRole('dialog').getByRole('article').filter({ has: page.getByRole('heading', { name: 'telegram · qaror', exact: true }) });
  await variant.getByRole('button', { name: 'Выбрать эту версию', exact: true }).click();
  await expect(draft).toContainText('Подготовленный материал изменился');
  await draft.getByRole('button', { name: 'Передать текущие черновики CMO', exact: true }).click();
  callApi({ method: 'MODEL_STEP' });
  await page.getByRole('button', { name: 'Обновить рабочий цикл', exact: true }).click();
  await expect(draft.getByRole('button', { name: 'Передать текущие черновики CMO', exact: true })).toHaveCount(0);
  await second.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath(`marketing-plan-work-${width}.png`), fullPage: true });
  for (const [name, card] of [['draft', draft], ['owner', owner], ['ready', second]]) {
    await card.evaluate(element => element.scrollIntoView({ block: 'center', behavior: 'instant' }));
    await card.screenshot({ path: info.outputPath(`marketing-plan-${name}-${width}.png`) });
  }
  await first.getByRole('button', { name: 'История шага', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Версия 1');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Приостановить план', exact: true }).click();
  await expect(second).toContainText('Рабочий план приостановлен');
  await page.getByRole('button', { name: 'Продолжить план', exact: true }).click();
  await expect(second).not.toContainText('Рабочий план приостановлен');
  expect(callApi({ method: 'GET', path: `${base}/workspace` }).body.deliveries).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

for (const width of [1440, 390]) test(`owner reviews full strategy scenarios and rejects a changed measured basis at ${width}px`, async ({ page }, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width, height: 950 });
  if (width === 390) await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_theme', 'light'));
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  const goal = { title: 'Регистрации после чтения разборов', metric: 'registrations', formula: 'Подтверждённые новые регистрации',
    unit: 'users', source: 'События сайта', baseline: null, target: 100, starts_on: '2026-11-23', deadline: '2026-11-30', budget: 3000000,
    currency: 'UZS', audiences: ['Начинающие инвесторы'] };
  expect(callApi({ method: 'PUT', path: `${base}/goal`, body: { expected_version: 0, data: goal } }).status).toBe(200);
  expect(callApi({ method: 'PUT', path: `${base}/reports/settings`, body: { expected_version: 0, data: { dataset: 'test' } } }).status).toBe(200);
  const event = id => ({ id, kind: 'registration', subject_id: id, channel: 'direct', dataset: 'test', at: '2025-01-07T08:00:00Z', source: 'registration-inventory', confirmed: true });
  expect(callApi({ method: 'POST', path: `${base}/reports/import`, body: { events: [event('a'), event('b')], coverage: [{
    dataset: 'test', categories: ['registrations'], starts_on: '2025-01-06', ends_on: '2025-01-13', through: '2025-01-13T00:00:00Z',
    history_complete: true, status: 'complete', reference: 'Сверен реестр регистраций за полную неделю',
  }] } }).status).toBe(200);
  const snapshot = callApi({ method: 'POST', path: `${base}/reports/snapshots`, body: {
    name: 'Неделя регистраций', period: { starts_on: '2025-01-06', ends_on: '2025-01-13' }, expected_settings_version: 1,
  } }).body.item;
  const scenarios = ['conservative', 'base', 'target'].map(kind => ({ kind, assumptions: ['Отклик аудитории нужно проверить'],
    actions: ['Сопоставить один формат на одинаковых окнах'], resources: 'Аналитик и редактор', budget: 800000,
    constraints: ['Нет разрешения запускать рекламу'], risks: ['Малая выборка'], checkpoint: '2026-11-29',
    formula: 'Измеренный охват × подтверждённая конверсия', measurement_plan: 'Сверить источники и собрать полный период', projection: null }));
  const output = extras => ({ summary: 'Сначала проверим условия и измерения.', questions: [], risks: [], recommendations: [], verdict: 'accept', handoff: 'Владелец рассматривает полный план', ...extras });
  await page.getByRole('button', { name: 'Цель и стратегия', exact: true }).click();
  await page.getByRole('button', { name: 'Обновить обсуждение', exact: true }).click();
  await page.getByLabel('Сообщение CMO', { exact: true }).fill('Покажите три сценария до утверждения цели.');
  await page.getByRole('button', { name: 'Отправить CMO', exact: true }).click();
  callApi({ method: 'MODEL_STEP', result: output({ feasibility: scenarios }) });
  await page.getByRole('button', { name: 'Обновить обсуждение', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Консервативный сценарий', exact: true })).toBeVisible();
  await expect(page.getByText('Числовая оценка не рассчитана', { exact: true })).toHaveCount(3);
  expect(callApi({ method: 'GET', path: `${base}/workspace` }).body.goal.status).toBe('draft');
  await page.getByRole('button', { name: 'Утвердить эту версию цели', exact: true }).click();
  await page.getByLabel('Сообщение CMO', { exact: true }).fill('Подготовьте полный недельный план по выбранной базе.');
  await page.getByLabel('Что подготовить', { exact: true }).selectOption('strategy');
  await page.getByLabel('База планирования · Неделя регистраций', { exact: true }).check();
  await page.getByRole('button', { name: 'Отправить CMO', exact: true }).click();
  for (let i = 0; i < 4; i++) callApi({ method: 'MODEL_STEP' });
  const plan = { title: 'Проверяемый недельный план', goal_version: 2, segments: goal.audiences, positioning: 'Объясняем биржевые данные с оригиналами',
    channels: ['telegram', 'instagram'], rubrics: ['quarterly'], measurement: 'Одинаковые окна и подтверждённые регистрации',
    risks: ['Небольшая база'], assumptions: ['Отклик при новом формате остаётся гипотезой'], allowed_changes: ['Порядок независимых задач в пределах недели'],
    steps: [
      { id: 'measure', owner: 'analytics', action: 'Сверить исходные регистрации', deliverable: 'Снимок с источником', starts_on: '2026-11-23', due: '2026-11-24', budget: 0, dependencies: [], channel: 'internal', rubric: '', mode: 'measurement' },
      { id: 'write', owner: 'copywriter', action: 'Подготовить объяснение для Telegram', deliverable: 'Проверенный черновик', starts_on: '2026-11-25', due: '2026-11-26', budget: 200000, dependencies: ['measure'], channel: 'telegram', rubric: 'quarterly', mode: 'organic' },
      { id: 'paid', owner: 'targeting', action: 'Подготовить рекламное предложение', deliverable: 'Параметры для отдельного решения', starts_on: '2026-11-27', due: '2026-11-28', budget: 600000, dependencies: ['write'], channel: 'instagram', rubric: '', mode: 'paid_proposal' },
    ], kpis: [{ metric: goal.metric, formula: goal.formula, unit: goal.unit, source: goal.source, target: goal.target, owner: 'analytics', checkpoint: goal.deadline }],
    scenarios: scenarios.map((row, i) => ({ ...row, projection: { snapshot_id: snapshot.id, factor: [0.5, 1, 1.5][i], assumption: 'Условное изменение отклика за такой же недельный период' } })),
  };
  callApi({ method: 'MODEL_STEP', result: output({ strategy: plan }) });
  await page.getByRole('button', { name: 'Обновить обсуждение', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: plan.title, exact: true }) });
  await card.getByRole('button', { name: 'Открыть полный план', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Состав расходов и календарь');
  await expect(dialog).toContainText('Подготовить объяснение для Telegram');
  await expect(dialog).toContainText('После: Сверить исходные регистрации');
  await expect(dialog).toContainText('Параметры для отдельного решения');
  await expect(dialog).toContainText('Плановый предел на единицу цели');
  await expect(dialog).toContainText('30 000');
  await expect(dialog).toContainText('registration-inventory');
  await expect(dialog).toContainText('Тестовые данные');
  await expect(dialog.getByRole('heading', { name: 'Целевой сценарий', exact: true })).toBeVisible();
  await dialog.getByRole('heading', { name: 'Базовый сценарий', exact: true }).scrollIntoViewIfNeeded();
  await dialog.screenshot({ path: info.outputPath(`marketing-strategy-scenarios-${width}.png`) });
  await dialog.getByRole('heading', { name: 'Состав расходов и календарь', exact: true }).scrollIntoViewIfNeeded();
  await dialog.screenshot({ path: info.outputPath(`marketing-strategy-calendar-${width}.png`) });
  await dialog.getByRole('button', { name: 'Утвердить полную стратегию', exact: true }).click();
  await expect(card).toContainText('Утверждено');
  await page.reload();
  await card.getByRole('button', { name: 'Версии стратегии', exact: true }).click();
  await expect(dialog).toContainText('Версия 2');
  await expect(dialog).toContainText('Версия 1');
  await page.keyboard.press('Escape');
  const next = callApi({ method: 'POST', path: `${base}/strategies`, body: { expected_version: 0, data: { ...plan, title: 'Повторная оценка базы' } } });
  expect(next.status).toBe(200);
  await page.getByRole('button', { name: 'Обновить обсуждение', exact: true }).click();
  const stale = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Повторная оценка базы', exact: true }) });
  await stale.getByRole('button', { name: 'Открыть полный план', exact: true }).click();
  expect(callApi({ method: 'POST', path: `${base}/reports/import`, body: { events: [event('late')], coverage: [] } }).status).toBe(200);
  await dialog.getByRole('button', { name: 'Утвердить полную стратегию', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('База измерений или её определения изменились');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Обновить обсуждение', exact: true }).click();
  await stale.getByRole('button', { name: 'Открыть полный план', exact: true }).click();
  await expect(dialog).toContainText('База измерений или её определения изменились');
  await expect(dialog.getByRole('button', { name: 'Утвердить полную стратегию', exact: true })).toBeDisabled();
  await dialog.locator('h3').first().scrollIntoViewIfNeeded();
  await dialog.screenshot({ path: info.outputPath(`marketing-strategy-stale-${width}.png`) });
  await page.keyboard.press('Escape');
  const saved = callApi({ method: 'GET', path: `${base}/workspace` }).body;
  expect(saved.deliveries).toHaveLength(0);
  expect(saved.goal.budget).toBe(3000000);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
