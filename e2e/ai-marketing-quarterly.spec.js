import { test, expect } from '@playwright/test';
import { workspace } from './helpers/marketing-workspace.js';

for (const width of [1440, 390]) test(`quarterly originals retain their periods and block legacy scope mismatch at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 950 });
  await page.addInitScript(theme => localStorage.setItem('uz_stock_analyzer_theme', theme), width === 390 ? 'light' : 'dark');
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  callApi({ method: 'QUARTER_SOURCE_FIXTURE' });
  await page.reload();
  await page.getByRole('button', { name: 'Источники', exact: true }).click();
  await expect(page.getByText('материалов: 2', { exact: false })).toBeVisible();
  const originals = callApi({ method: 'GET', path: `${base}/workspace` }).body.evidence;
  expect(originals).toHaveLength(2);
  const buttons = page.getByRole('button', { name: 'Открыть доказательство', exact: true });
  const periods = [];
  for (let index = 0; index < 2; index++) {
    await buttons.nth(index).click();
    const dialog = page.getByRole('dialog');
    const scope = dialog.locator('dt').filter({ hasText: /^Период$/ }).locator('+ dd');
    periods.push((await scope.innerText()).split(' · ')[0]);
    await expect(dialog.locator('dt').filter({ hasText: /^Начало периода$/ }).locator('+ dd')).toHaveText('2026-01-01');
    await expect(dialog.locator('blockquote.mkt-original')).not.toContainText('extracted_original_lines');
    await expect(dialog.getByRole('rowheader', { name: 'analysis_ready', exact: true })).toHaveCount(0);
    const field = dialog.getByRole('row').filter({ has: page.getByRole('rowheader', { name: 'Чистая прибыль', exact: true }) });
    await expect(field).toContainText(periods[index] === '2026-06-30' ? '600' : '900');
    await expect(field).toContainText('thousand UZS');
    await dialog.getByText('Исходная запись', { exact: true }).click();
    await expect(dialog.locator('pre.mkt-original')).toContainText('extracted_original_lines');
    await dialog.getByText('Исходная запись', { exact: true }).click();
    await scope.scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(`marketing-quarter-original-${width}-${periods[index]}.png`) });
    await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click();
  }
  expect(periods.sort()).toEqual(['2026-06-30', '2026-09-30']);
  const nine = originals.find(item => item.period === '2026-09-30');
  const expires = new Date(Date.now() + 86400000).toISOString();
  callApi({ method: 'PUT', path: `${base}/accounts/tg`, body: { expected_version: 0, data: {
    platform: 'telegram', label: 'Telegram · квартальные разборы', mode: 'automatic', external_id: '-100123',
    rubrics: ['quarterly'], formats: ['post'], languages: ['ru'], valid_until: expires,
  } } });
  expect(callApi({ method: 'POST', path: `${base}/candidates`, body: { event_id: 'analysis-hmkb-q3', account_id: 'tg',
    mode: 'automatic', rubric: 'quarterly', entity: 'HMKB', period: '2026Q3', title: 'HMKB · показатели за девять месяцев',
    body: 'Чистая прибыль за девять месяцев 900; активы 1200 тыс. сум.', evidence_ids: [nine.id],
    claims: [{ evidence_id: nine.id, field: 'net_income', value: 900, unit: 'thousand UZS' },
      { evidence_id: nine.id, field: 'total_assets', value: 1200, unit: 'thousand UZS' }],
    destination_url: nine.destination_url, expires_at: expires, language: 'ru', format: 'post',
  } }).status).toBe(200);
  callApi({ method: 'QUARTER_LEGACY_SCOPE', evidence_id: nine.id });
  await page.reload();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'HMKB · показатели за девять месяцев', exact: true }) });
  await card.getByRole('button', { name: 'Проверить факты', exact: true }).click();
  await expect(card).toContainText('Период, стандарт, состав отчётности или валюта оригинала не совпадают');
  await expect(card).toContainText('Пропущен');
  await expect(card.getByRole('button', { name: 'Поставить в очередь', exact: true })).toHaveCount(0);
  await card.locator('.mkt-error').evaluate(element => element.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath(`marketing-quarter-scope-blocked-${width}.png`) });
  await page.reload();
  await expect(card).toContainText('Пропущен');
  expect(callApi({ method: 'GET', path: `${base}/workspace` }).body.deliveries).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

for (const width of [1440, 390]) test(`automatic quarterly rule binds the published analysis and checks financial wording at ${width}px`, async ({ page }, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width, height: 950 });
  await page.addInitScript(theme => localStorage.setItem('uz_stock_analyzer_theme', theme), width === 390 ? 'light' : 'dark');
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  const fixture = callApi({ method: 'QUARTER_SOURCE_FIXTURE', plan: true });
  expect(fixture.status).toBe(200);
  await page.reload();
  await page.getByRole('button', { name: 'Рабочий цикл', exact: true }).click();
  await page.getByRole('button', { name: 'Добавить редакционное правило', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Название правила', { exact: true }).fill('Новые квартальные разборы');
  await page.keyboard.press('Tab');
  await expect(dialog.getByLabel('Утверждённая стратегия', { exact: true })).toBeFocused();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await expect(dialog.getByLabel('Рубрика', { exact: true })).toBeFocused();
  await dialog.getByLabel('Приоритет', { exact: true }).selectOption('urgent');
  await dialog.getByLabel('Рубрика', { exact: true }).selectOption('quarterly');
  await expect(dialog.getByLabel('Приоритет', { exact: true })).toHaveValue('normal');
  await expect(dialog).toContainText('первого опубликованного разбора');
  await expect(dialog).toContainText('Повторная генерация не обновляет возраст');
  await expect(dialog.getByLabel('Возраст события, часов', { exact: true })).toHaveAccessibleDescription(/первого опубликованного разбора/);
  await dialog.getByLabel('Готовые разборы UZStock', { exact: true }).check();
  await dialog.getByLabel('Возраст события, часов', { exact: true }).fill('48');
  await dialog.getByLabel('Результат работы', { exact: true }).selectOption('account');
  await expect(dialog.getByLabel('Включить автоматический выбор', { exact: true })).not.toBeChecked();
  await dialog.getByLabel('Включить автоматический выбор', { exact: true }).check();
  await dialog.getByLabel('Возраст события, часов', { exact: true }).evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath(`marketing-quarter-rule-${width}.png`) });
  await dialog.getByRole('button', { name: 'Сохранить правило', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(callApi({ method: 'WORKER_STEP' }).body.editorial_work).toBe(true);
  const selected = callApi({ method: 'GET', path: `${base}/workspace` }).body;
  expect(selected.tasks).toHaveLength(1);
  expect(selected.tasks[0].production.period).toBe('2026Q3');
  expect(selected.tasks[0].production.destination_url).toContain('report_version=');
  expect(selected.evidence.every(row => row.published_at.startsWith('2026-10-25'))).toBe(true);
  callApi({ method: 'MODEL_PRODUCTION', quarterly: true, quarter_wording: width === 390 });
  await page.reload();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'HMKB · разбор отчётности', exact: true }) });
  if (width === 390) {
    await expect(card).toContainText('Пропущен');
    await expect(card).toContainText('Показатель за квартал должен подтверждаться');
    await expect(card.getByRole('button', { name: 'Поставить в очередь', exact: true })).toHaveCount(0);
  } else {
    await expect(card).toContainText('Готов');
    await expect(card).toContainText('Чистая прибыль за девять месяцев');
  }
  await card.locator(width === 390 ? '.mkt-error' : 'h4').first().evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath(`marketing-quarter-result-${width}.png`) });
  await page.reload();
  const final = callApi({ method: 'GET', path: `${base}/workspace` }).body;
  expect(final.candidates).toHaveLength(1);
  expect(final.candidates[0].status).toBe(width === 390 ? 'skipped' : 'ready');
  expect(final.deliveries).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
