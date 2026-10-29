import { test, expect } from '@playwright/test';

async function setup(page, { language = 'en', theme = 'light', fail = false } = {}) {
  const votes = [];
  await page.addInitScript(({ language, theme }) => {
    localStorage.setItem('uz_stock_analyzer_language', language);
    localStorage.setItem('uz_stock_analyzer_theme', theme);
    Math.random = () => 0.5;
  }, { language, theme });
  await page.clock.install();
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/feedback/ratings') {
      votes.push(route.request().postDataJSON());
      return route.fulfill({ status: fail && votes.length === 1 ? 503 : 200, json: { ok: !(fail && votes.length === 1) } });
    }
    if (path === '/api/auth/me') return route.fulfill({ status: 401, json: {} });
    return route.fulfill({ json: { ok: true, items: [], stocks: [], rates: [], securities: [] } });
  });
  await page.goto('/');
  await page.locator('main h1').first().click({ clickCount: 2 });
  return votes;
}
const prompt = page => page.getByRole('region', { name: /How is UZStock|Как вам UZStock|UZStock sizga/ });
async function daysLater(page, days) {
  const now = await page.evaluate(() => Date.now());
  await page.clock.setSystemTime(now + days * 86400000);
  await page.clock.fastForward(1000);
}
async function show(page) {
  await page.clock.fastForward(181000);
  await expect(prompt(page)).toBeVisible();
}

test('asks after engaged use, supports 1/2/3, and remembers a successful answer', async ({ page }, testInfo) => {
  const votes = await setup(page);
  await page.clock.fastForward(89000);
  await expect(prompt(page)).toHaveCount(0);
  await show(page);
  expect((await prompt(page).boundingBox()).height).toBeLessThanOrEqual(120);
  await page.screenshot({ path: testInfo.outputPath('rating-desktop.png') });
  await page.keyboard.press('3');
  await expect(prompt(page)).toContainText('Thanks');
  expect(votes).toHaveLength(1);
  expect(votes[0]).toMatchObject({ rating: 3, language: 'en', page_path: '/' });
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  await page.locator('main h1').first().click({ clickCount: 2 });
  await daysLater(page, 29);
  await expect(prompt(page)).toHaveCount(0);
  await daysLater(page, 2);
  await expect(prompt(page)).toBeVisible();
});

for (const language of ['ru', 'uz', 'en']) test(`desktop rating labels stay on one line (${language})`, async ({ page }) => {
  await setup(page, { language });
  await show(page);
  const card = prompt(page);
  expect((await card.boundingBox()).width).toBeGreaterThanOrEqual(440);
  expect((await card.boundingBox()).height).toBeLessThanOrEqual(120);
  await expect(card.locator('kbd')).toHaveText(['1', '2', '3']);
  for (const label of await card.locator('.rating-label').all()) {
    expect(await label.evaluate(el => el.getBoundingClientRect().height <= 18)).toBe(true);
    expect(await label.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  }
});

test('does not hijack typing or shortcuts; Escape dismisses for seven days', async ({ page }) => {
  const votes = await setup(page);
  await show(page);
  await page.evaluate(() => {
    const input = document.createElement('input'); input.id = 'typing-check'; document.body.append(input); input.focus();
  });
  await page.keyboard.type('123');
  await expect(page.locator('#typing-check')).toHaveValue('123');
  expect(votes).toHaveLength(0);
  await page.locator('#typing-check').evaluate(input => input.remove());
  await page.keyboard.press('Control+1');
  expect(votes).toHaveLength(0);
  await page.keyboard.press('Escape');
  await expect(prompt(page)).toHaveCount(0);
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  await page.locator('main h1').first().click({ clickCount: 2 });
  await daysLater(page, 6);
  await expect(prompt(page)).toHaveCount(0);
  await daysLater(page, 2);
  await expect(prompt(page)).toBeVisible();
});

test('waits while editing or in a dialog without moving focus', async ({ page }) => {
  await setup(page);
  await page.evaluate(() => {
    const input = document.createElement('input'); input.id = 'typing-check'; document.body.append(input); input.focus();
  });
  await page.clock.fastForward(181000);
  await expect(prompt(page)).toHaveCount(0);
  await expect(page.locator('#typing-check')).toBeFocused();
  await page.locator('#typing-check').evaluate(input => input.remove());
  await page.evaluate(() => { const dialog = document.createElement('dialog'); dialog.id = 'dialog-check'; document.body.append(dialog); dialog.showModal(); });
  await page.clock.fastForward(181000);
  await expect(prompt(page)).toHaveCount(0);
  await page.locator('#dialog-check').evaluate(dialog => dialog.remove());
  await show(page);
  await expect(page.locator('body')).toBeFocused();
});

test('failed submission can retry the same response without duplicate votes', async ({ page }) => {
  const votes = await setup(page, { fail: true });
  await show(page);
  await prompt(page).getByRole('button', { name: /Okay/  }).click();
  await expect(prompt(page).getByRole('alert')).toBeVisible();
  await prompt(page).getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(prompt(page)).toContainText('Thanks');
  expect(votes).toHaveLength(2);
  expect(votes[1]).toEqual(votes[0]);
});

test.describe('touch devices', () => {
  test.use({ hasTouch: true });
for (const [language, theme] of [['ru', 'light'], ['uz', 'dark'], ['en', 'light']]) {
  test(`phone rating has large tap targets and fits (${language}, ${theme})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 360, height: 740 });
    const votes = await setup(page, { language, theme });
    await show(page);
    const card = prompt(page);
    const choices = card.locator('.rating-choice');
    await expect(card.locator('kbd')).toHaveCount(0);
    const tapHint = { ru: 'Нажмите на ответ', uz: 'Javobni bosing', en: 'Tap an answer' }[language];
    await expect(card).toContainText(tapHint);
    await expect(choices).toHaveCount(3);
    for (const button of await choices.all()) {
      const box = await button.boundingBox();
      expect(box.height).toBeGreaterThanOrEqual(48);
      expect(box.width).toBeGreaterThanOrEqual(44);
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(360);
    }
    expect((await card.boundingBox()).height).toBeLessThanOrEqual(120);
    const close = await card.locator('.rating-dismiss').boundingBox();
    expect(close.width).toBeGreaterThanOrEqual(44);
    expect(close.height).toBeGreaterThanOrEqual(44);
    // A narrow phone must still show readable labels and all three choices.
    await page.setViewportSize({ width: 320, height: 640 });
    expect((await card.boundingBox()).height).toBeLessThanOrEqual(120);
    for (const button of await choices.all()) {
      expect(await button.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
      expect(await button.locator('.rating-label').evaluate(el => el.getBoundingClientRect().height <= 18)).toBe(true);
      await expect(button).not.toHaveAttribute('aria-keyshortcuts', /./);
      const box = await button.boundingBox();
      expect(box.x + box.width).toBeLessThanOrEqual(320);
    }
    await page.setViewportSize({ width: 360, height: 740 });
    await page.screenshot({ path: testInfo.outputPath('rating-mobile.png') });
    await choices.first().tap();
    await expect.poll(() => votes.length).toBe(1);
    expect(votes[0].rating).toBe(1);
  });
}

});

test('hidden time does not count and feedback/account pages never prompt', async ({ page }) => {
  await setup(page);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.fastForward(181000);
  await expect(prompt(page)).toHaveCount(0);
  await page.evaluate(() => {
    delete document.hidden;
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.fastForward(89000);
  await expect(prompt(page)).toHaveCount(0);
  await page.goto('/feedback');
  await page.locator('main h1').click({ clickCount: 2 });
  await page.clock.fastForward(181000);
  await expect(prompt(page)).toHaveCount(0);
});

test('no duplicate sends while waiting and Escape still dismisses a pending vote', async ({ page }) => {
  const votes = await setup(page);
  let release;
  await page.route('**/api/feedback/ratings', async route => {
    votes.push(route.request().postDataJSON());
    await new Promise(resolve => { release = resolve; });
    await route.fulfill({ json: { ok: true } });
  });
  await show(page);
  await page.keyboard.press('1');
  await expect(prompt(page)).toContainText('Saving');
  await page.keyboard.press('2');
  expect(votes).toHaveLength(1);
  await page.keyboard.press('Escape');
  await expect(prompt(page)).toHaveCount(0);
  release();
});

for (const unavailable of [false, true]) test(`admin feedback handles rating availability (${unavailable})`, async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('uz_stock_analyzer_token', 'admin-token');
    localStorage.setItem('uz_stock_analyzer_language', 'en');
  });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (unavailable && path === '/api/admin/feedback/ratings') return route.fulfill({ status: 503, json: { detail: 'Ratings unavailable' } });
    const data = path === '/api/auth/me' ? { user: { id: 1, email: 'admin@example.com', is_admin: true } }
      : path === '/api/admin/feedback/ratings' ? { total: 12, counts: { 1: 2, 2: 3, 3: 7 }, items: [{ rating: 1, page_path: '/company/HMKB', language: 'ru', created_at: '2026-10-29T10:00:00Z' }] }
      : path === '/api/admin/feedback' ? { items: [{ id: 5, status: 'open', subject: 'Export issue', message: 'PDF will not download.', created_at: '2026-10-29T10:00:00Z' }] }
      : { ok: true, items: [] };
    return route.fulfill({ json: data });
  });
  await page.goto('/admin/feedback');
  const ratings = page.getByRole('region', { name: 'Site ratings' });
  await expect(page.getByText('Export issue', { exact: true })).toBeVisible();
  if (unavailable) {
    await expect(ratings.getByRole('alert')).toContainText('Ratings unavailable');
    await expect(ratings).not.toContainText('0 responses');
    return;
  }
  await expect(ratings).toContainText('12 responses');
  await expect(ratings).toContainText('Needs work');
  await expect(ratings).toContainText('/company/HMKB');
  await expect(ratings).toContainText('Anonymous');
});
