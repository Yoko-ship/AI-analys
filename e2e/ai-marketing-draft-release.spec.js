import { test, expect } from '@playwright/test';
import { workspace } from './helpers/marketing-workspace.js';

for (const [width, mode] of [[1440, 'manual'], [390, 'automatic']]) test(`owner releases an internal draft through ${mode} account rules at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 950 });
  await page.addInitScript(theme => localStorage.setItem('uz_stock_analyzer_theme', theme), width === 390 ? 'light' : 'dark');
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing', stamp = Date.now();
  const expires = new Date(stamp + 86400000).toISOString();
  const account = { platform: 'telegram', label: 'Telegram · выпуск черновика', external_id: '-100123', mode: 'draft',
    languages: ['ru'], formats: ['post'], rubrics: ['news'], valid_until: expires, window_start: '00:00', window_end: '23:59' };
  expect(callApi({ method: 'PUT', path: `${base}/accounts/tg`, body: { expected_version: 0, data: account } }).status).toBe(200);
  expect(callApi({ method: 'PUT', path: `${base}/evidence/decision`, body: { expected_version: 0, data: {
    title: 'Решение HMKB', url: 'https://openinfo.uz/facts/123', publisher: 'HMKB', entity: 'HMKB',
    published_at: new Date(stamp - 3600000).toISOString(), retrieved_at: new Date(stamp - 60000).toISOString(), expires_at: expires,
    excerpt: 'Утверждено 120 сум на простую акцию.', rights: 'link_and_excerpt', status: 'verified',
    data: { dividend: 120, dividend_state: 'approved', share_class: 'ordinary' }, units: { dividend: 'UZS/share' },
  } } }).status).toBe(200);
  expect(callApi({ method: 'POST', path: `${base}/tasks`, body: { kind: 'content', message: 'Подготовить внутренний черновик решения HMKB', evidence_ids: ['decision'],
    production: { event_id: 'internal-hmkb-decision', rubric: 'news', entity: 'HMKB', expires_at: expires, mode: 'draft',
      destination_url: 'https://uzstock.uz/news/123', targets: [{ account_id: 'tg', languages: ['ru'], primary_language: 'ru', format: 'post' }] },
  } }).status).toBe(200);
  callApi({ method: 'MODEL_PRODUCTION' });
  await page.reload();
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'telegram · решение', exact: true }) });
  await expect(card).toContainText('Автоматические проверки пройдены');
  await expect(card.getByRole('button', { name: /Проверить (для ручного выпуска|и допустить к автовыпуску)/ })).toHaveCount(0);
  expect(callApi({ method: 'GET', path: `${base}/workspace` }).body.deliveries).toEqual([]);
  expect(callApi({ method: 'PUT', path: `${base}/accounts/tg`, body: { expected_version: 1, data: { ...account, mode } } }).status).toBe(200);
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  const release = card.getByRole('button', { name: mode === 'manual' ? 'Проверить для ручного выпуска' : 'Проверить и допустить к автовыпуску', exact: true });
  await expect(release).toBeVisible();
  await expect(release).toBeEnabled();
  await release.focus();
  await expect(release).toBeFocused();
  await release.evaluate(element => element.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath(`marketing-draft-release-action-${width}.png`) });
  await release.press('Enter');
  await expect(card).toContainText('Владелец перевёл черновик к выпуску');
  if (mode === 'manual') {
    await expect(card.getByRole('button', { name: 'Поставить в очередь', exact: true })).toHaveCount(0);
    await card.getByRole('button', { name: 'Утвердить эту версию', exact: true }).click();
  }
  await expect(card.getByRole('button', { name: 'Поставить в очередь', exact: true })).toBeVisible();
  await page.reload();
  await expect(card).toContainText('Владелец перевёл черновик к выпуску');
  const saved = callApi({ method: 'GET', path: `${base}/workspace` }).body;
  expect(saved.candidates).toHaveLength(1);
  expect(saved.candidates[0].mode).toBe(mode);
  expect(saved.candidates[0].release_decision.account_version).toBe(2);
  expect(saved.accounts[0].connection_status).toBe('not_connected');
  expect(saved.deliveries).toEqual([]);
  await card.getByRole('button', { name: 'Поставить в очередь', exact: true }).click();
  await expect(card).toContainText('Запланирован');
  await card.evaluate(element => element.scrollIntoView({ block: 'start', behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath(`marketing-draft-release-saved-${width}.png`) });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
