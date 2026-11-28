import { test, expect } from '@playwright/test';
import { workspace } from './helpers/marketing-workspace.js';

for (const width of [1440, 390]) test(`unsupported provider formats are unavailable before login at ${width}px`, async ({ page }, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width, height: 950 });
  await page.addInitScript(theme => localStorage.setItem('uz_stock_analyzer_theme', theme), width === 390 ? 'light' : 'dark');
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const callApi = await workspace(page, info), base = '/api/admin/ai-marketing';
  const platforms = { telegram: 'Telegram UZStock', instagram: 'Instagram UZStock', facebook: 'Facebook UZStock', linkedin: 'Личный LinkedIn' };
  for (const [id, label] of Object.entries(platforms)) {
    expect(callApi({ method: 'PUT', path: `${base}/accounts/${id}`, body: { expected_version: 0, data: {
      platform: id, label, mode: 'draft', languages: ['ru'], formats: ['post', 'image', 'carousel', 'video', 'story'], rubrics: ['news', 'calendar'],
    } } }).status).toBe(200);
  }
  await page.reload();
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  for (const [id, label] of Object.entries(platforms)) {
    await page.getByRole('button', { name: `Настроить ${label}`, exact: true }).click();
    const formats = page.getByRole('group', { name: 'Форматы', exact: true });
    await expect(formats.getByRole('checkbox', { name: id === 'instagram' ? /^Пост/ : /^Stories/ })).toBeDisabled();
    await expect(formats.getByRole('checkbox', { name: 'Изображение', exact: true })).toBeEnabled();
    if (id === 'instagram') await expect(formats.getByRole('checkbox', { name: /^Stories/ })).toBeEnabled();
    if (id === 'facebook') {
      await formats.evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
      await page.screenshot({ path: info.outputPath(`marketing-formats-settings-${width}.png`) });
    }
    await page.getByRole('button', { name: 'Сохранить правила аккаунта', exact: true }).click();
    await expect(page.getByText('Правила аккаунта сохранены. Подключение проверяется отдельно.', { exact: true })).toBeVisible();
  }
  await page.getByRole('button', { name: 'Контент и очередь', exact: true }).click();
  await page.getByRole('button', { name: 'Новый материал', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Целевой аккаунт', { exact: true }).selectOption('instagram');
  const formats = dialog.getByLabel('Формат материала', { exact: true });
  await expect(formats.locator('option[value="post"]')).toHaveCount(0);
  await expect(formats.locator('option[value="story"]')).toHaveCount(1);
  await dialog.getByLabel('Рубрика', { exact: true }).selectOption('calendar');
  await expect(dialog.getByRole('button', { name: 'Сохранить материал', exact: true })).toBeDisabled();
  await dialog.getByLabel('Целевой аккаунт', { exact: true }).selectOption('telegram');
  await expect(formats).toHaveValue('post');
  await expect(dialog.getByRole('button', { name: 'Сохранить материал', exact: true })).toBeEnabled();
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click();
  await page.getByRole('button', { name: 'Рабочий цикл', exact: true }).click();
  for (const [id, label] of Object.entries(platforms)) {
    await page.getByLabel(`Подготовить для ${label}`, { exact: true }).check();
    const target = page.getByLabel(`Формат · ${label}`, { exact: true });
    await expect(target.locator(`option[value="${id === 'instagram' ? 'post' : 'story'}"]`)).toHaveCount(0);
  }
  const state = callApi({ method: 'GET', path: `${base}/workspace` }).body;
  for (const account of state.accounts) {
    expect(account.formats).toEqual(state.platforms.find(row => row.id === account.platform).formats);
    expect(account.connection_status).toBe('not_connected');
    expect(account.mode).toBe('draft');
  }
  expect(state.tasks).toEqual([]);
  expect(state.deliveries).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
