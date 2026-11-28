import { test, expect } from '@playwright/test';
import { workspace } from './helpers/marketing-workspace.js';

for (const width of [1440, 390]) test(`owner edits source-bound digest items and checks each decision at ${width}px`, async ({ page }, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width, height: 950 });
  await page.addInitScript(theme => localStorage.setItem('uz_stock_analyzer_theme', theme), width === 390 ? 'light' : 'dark');
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  const originals = callApi({ method: 'DIGEST_SOURCE_FIXTURE' }).body.evidence;
  const mode = width === 390 ? 'automatic' : 'manual';
  expect(callApi({ method: 'PUT', path: `${base}/accounts/tg`, body: { expected_version: 0, data: {
    platform: 'telegram', label: 'Telegram · дайджест', external_id: '-100123', mode,
    languages: ['ru'], formats: ['post'], rubrics: ['digest'], valid_until: new Date(Date.now() + 86400000).toISOString(),
  } } }).status).toBe(200);
  expect(callApi({ method: 'PUT', path: `${base}/accounts/ig`, body: { expected_version: 0, data: {
    platform: 'instagram', label: 'Instagram · изображения', external_id: '123456', mode: 'draft',
    languages: ['ru'], formats: ['image'], rubrics: ['digest'],
  } } }).status).toBe(200);
  await page.reload();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  await page.getByRole('button', { name: 'Новый материал', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Ключ события', { exact: true }).fill('digest-owner-decisions');
  await dialog.getByLabel('Рубрика', { exact: true }).selectOption('digest');
  await dialog.getByLabel('Целевой аккаунт', { exact: true }).selectOption('ig');
  await expect(dialog.getByRole('button', { name: 'Сохранить материал', exact: true })).toBeDisabled();
  await dialog.getByLabel('Целевой аккаунт', { exact: true }).selectOption('tg');
  await dialog.getByLabel('Режим материала', { exact: true }).selectOption(mode);
  await dialog.getByLabel('Заголовок материала', { exact: true }).fill('HMKB и UZTL · дивидендный дайджест');
  await dialog.getByLabel('Прямая ссылка на UZStock', { exact: true }).fill(originals[0].destination_url);
  const proof = dialog.getByRole('group', { name: 'Доказательства и используемые факты', exact: true });
  for (const original of originals) await proof.getByLabel(original.title, { exact: true }).check();
  for (const claim of await proof.locator('input[name="claims"]').all()) await claim.check();
  await expect(dialog.getByRole('button', { name: 'Добавить пункт дайджеста', exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: 'Добавить пункт дайджеста', exact: true }).click();
  await dialog.getByRole('button', { name: 'Добавить пункт дайджеста', exact: true }).click();
  for (const [index, original] of originals.entries()) {
    const section = dialog.getByRole('group', { name: `Пункт ${index + 1}`, exact: true });
    await section.getByLabel(original.title, { exact: true }).check();
    await section.getByLabel(`Текст пункта ${index + 1}`, { exact: true }).fill(index === 1
      ? 'Выплачено 45 сум на привилегированную акцию.'
      : mode === 'automatic' ? 'Выплачено 120 сум на простую акцию.' : 'Утверждено 120 сум на простую акцию.');
  }
  await dialog.getByLabel('Текст пункта 1', { exact: true }).evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath(`marketing-digest-editor-${width}.png`) });
  await dialog.getByRole('button', { name: 'Сохранить материал', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'HMKB и UZTL · дивидендный дайджест', exact: true }) });
  await card.getByRole('button', { name: 'Проверить факты', exact: true }).click();
  if (mode === 'manual') {
    await expect(card).toContainText('Ожидает решения');
    await card.getByRole('button', { name: 'Утвердить эту версию', exact: true }).click();
    await card.getByRole('button', { name: 'Изменить материал', exact: true }).click();
    await expect(dialog.getByLabel('Текст пункта 2', { exact: true })).toHaveValue('Выплачено 45 сум на привилегированную акцию.');
    await dialog.getByLabel('Текст пункта 1', { exact: true }).fill('Выплачено 120 сум на простую акцию.');
    await dialog.getByRole('button', { name: 'Сохранить материал', exact: true }).click();
    await expect(card.getByRole('button', { name: 'Поставить в очередь', exact: true })).toHaveCount(0);
    await card.getByRole('button', { name: 'Проверить факты', exact: true }).click();
    await expect(card).toContainText('Нужна доработка');
  } else await expect(card).toContainText('Пропущен');
  await expect(card).toContainText('Пункт дайджеста 1');
  await card.locator('.mkt-error').evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath(`marketing-digest-rejected-${width}.png`) });
  await page.reload();
  const state = callApi({ method: 'GET', path: `${base}/workspace` }).body;
  expect(state.candidates).toHaveLength(1);
  expect(state.candidates[0].digest_items).toHaveLength(2);
  expect(state.candidates[0].approval).toBeNull();
  for (const original of originals) {
    expect(state.candidates[0].body).toContain(original.entity);
    expect(state.candidates[0].body).toContain(original.destination_url);
    expect(state.candidates[0].body).toContain(original.url);
    expect(state.candidates[0].body).toContain(new Date(original.published_at).toLocaleDateString('ru-RU', { timeZone: 'Asia/Tashkent' }));
  }
  expect(state.deliveries).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

for (const width of [1440, 390]) test(`scheduled digest uses the owner cutoff and retains selected events at ${width}px`, async ({ page }, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width, height: 950 });
  await page.addInitScript(theme => localStorage.setItem('uz_stock_analyzer_theme', theme), width === 390 ? 'light' : 'dark');
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  const fixture = callApi({ method: 'DIGEST_SOURCE_FIXTURE', plan: true, count: width === 390 ? 3 : 2 });
  expect(fixture.status).toBe(200);
  const cutoff = new Date().toLocaleTimeString('en-GB', { timeZone: 'Asia/Tashkent', hour: '2-digit', minute: '2-digit' });
  await page.reload();
  await page.getByRole('button', { name: 'Рабочий цикл', exact: true }).click();
  await page.getByRole('button', { name: 'Добавить редакционное правило', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Название правила', { exact: true }).fill('Дневной дайджест');
  await dialog.getByLabel('Рубрика', { exact: true }).selectOption('digest');
  const time = dialog.getByLabel('Время подбора дайджеста · Ташкент', { exact: true });
  await expect(time).toBeVisible();
  await expect(time).toHaveAccessibleDescription(/два разных/);
  await time.fill(cutoff);
  await time.focus();
  await expect(time).toBeFocused();
  await expect(dialog.getByLabel('Формат', { exact: true })).toHaveValue('post');
  const sources = dialog.getByRole('group', { name: 'Разрешённые источники', exact: true });
  await sources.getByRole('checkbox').check();
  await dialog.getByLabel('Результат работы', { exact: true }).selectOption('account');
  await dialog.getByLabel('Включить автоматический выбор', { exact: true }).check();
  await time.evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath(`marketing-digest-rule-${width}.png`) });
  await dialog.getByRole('button', { name: 'Сохранить правило', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const ruleCard = page.getByRole('article', { name: 'Дневной дайджест', exact: true });
  await expect(ruleCard).toContainText(cutoff);
  expect(callApi({ method: 'WORKER_STEP' }).body.editorial_work).toBe(true);
  callApi({ method: 'MODEL_PRODUCTION', digest: true, omit_event: width === 390 });
  await page.reload();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Дивидендные решения и выплаты', exact: true }) });
  await expect(card).toContainText(width === 390 ? 'Пропущен' : 'Готов');
  if (width === 390) await expect(card).toContainText('Каждое выбранное событие должно войти в автоматический дайджест');
  await card.locator(width === 390 ? '.mkt-error' : 'h4').first().evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath(`marketing-digest-scheduled-${width}.png`) });
  await page.getByRole('button', { name: 'Рабочий цикл', exact: true }).click();
  await ruleCard.getByRole('button', { name: 'Изменить правило', exact: true }).click();
  await expect(time).toHaveValue(cutoff);
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click();
  await ruleCard.getByRole('button', { name: 'Отключить правило', exact: true }).click();
  await expect(ruleCard).toContainText('Отключён');
  const final = callApi({ method: 'GET', path: `${base}/workspace` }).body;
  expect(final.tasks).toHaveLength(1);
  expect(Object.keys(final.tasks[0].evidence_versions)).toHaveLength(fixture.body.evidence.length);
  expect(final.candidates).toHaveLength(1);
  expect(final.deliveries).toEqual([]);
  expect(final.editorial_rules[0].enabled).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
