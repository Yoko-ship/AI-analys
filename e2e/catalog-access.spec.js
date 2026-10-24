import { test, expect } from '@playwright/test';

async function accessFixture(page, { signedIn = false, admin = false, ready = Promise.resolve() } = {}) {
  await page.addInitScript(({ signedIn }) => {
    localStorage.setItem('uz_stock_analyzer_language', 'en');
    if (signedIn) localStorage.setItem('uz_stock_analyzer_token', 'catalog-access-session');
  }, { signedIn });
  const requests = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const json = body => route.fulfill({ json: body });
    if (path === '/api/auth/me') {
      await ready;
      return json({ user: { id: 1, email: 'catalog@example.test', is_admin: admin } });
    }
    if (path.startsWith('/api/catalog/') || path.startsWith('/api/terminal/')) requests.push(path);
    if (path === '/api/catalog/companies') return json({ ok: true, companies: [{ ticker: 'HMKB', company_name: 'Hamkorbank', sector: 'finance' }] });
    if (path === '/api/catalog/index/HMKB') return json({ ok: true, company_name: 'Hamkorbank', availability: { NSBU: { annual: [{ year: 2025, quarter: 0 }], quarter: [] } } });
    return json({ ok: true, companies: [], securities: {}, items: [], rows: [], points: [], rates: [] });
  });
  return requests;
}

for (const signedIn of [false, true]) {
  test(`${signedIn ? 'member' : 'guest'} cannot open the catalog or find it in either menu`, async ({ page }, testInfo) => {
    const requests = await accessFixture(page, { signedIn });
    await page.goto('/catalog?t=HMKB&f=SUM');
    if (signedIn) await expect(page.locator('.account-button')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Administrators only', exact: true })).toBeVisible();
    await expect(page.locator('.nav-catalog-wrap')).toHaveCount(0);
    await expect(page.locator('.terminal-command')).toHaveCount(0);
    expect(requests).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath('catalog-denied-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: 'Open menu', exact: true }).click();
    await expect(page.locator('.nav-catalog-wrap')).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath('catalog-denied-mobile.png'), fullPage: true, animations: 'disabled' });
    await page.getByRole('button', { name: 'Close menu', exact: true }).click();
    await page.screenshot({ path: testInfo.outputPath('catalog-denied-mobile-closed.png'), fullPage: true, animations: 'disabled' });
    await page.getByRole('button', { name: 'Back to the site', exact: true }).click();
    await expect(page.locator('.lv-h1')).toBeVisible();
    await page.goBack();
    await expect(page.getByRole('heading', { name: 'Administrators only', exact: true })).toBeVisible();
    await page.goto('/uz/catalog?t=HMKB&f=PL');
    await expect(page.getByRole('heading', { name: 'Faqat administratorlar uchun', exact: true })).toBeVisible();
    await expect(page.locator('.terminal-command')).toHaveCount(0);
  });
}

test('an admin bookmark waits for verified access, survives reload, and closes on logout', async ({ page }, testInfo) => {
  let verify;
  const ready = new Promise(resolve => { verify = resolve; });
  const requests = await accessFixture(page, { signedIn: true, admin: true, ready });
  await page.goto('/catalog?t=HMKB&f=CF');
  try {
    await expect(page.getByRole('status').filter({ hasText: 'Checking access' })).toBeVisible();
    await expect(page.locator('.nav-catalog-wrap')).toHaveCount(0);
    expect(requests).toEqual([]);
  } finally { verify(); }
  await expect(page.getByRole('heading', { name: 'Hamkorbank', exact: true })).toBeVisible();
  await expect(page.locator('.nav-catalog-wrap')).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Hamkorbank', exact: true })).toBeVisible();
  await expect(page).toHaveURL(/t=HMKB.*f=CF/);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open menu', exact: true }).click();
  await expect(page.locator('.nav-catalog-wrap')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('catalog-admin-mobile.png'), fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: 'Close menu', exact: true }).click();
  await page.locator('.account-button').click();
  await page.getByRole('menuitem', { name: 'Log out', exact: true }).click();
  await expect(page.locator('.nav-catalog-wrap')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Hamkorbank', exact: true })).toHaveCount(0);
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Administrators only', exact: true })).toBeVisible();
});

test('a member can add watchlist companies without being sent to the hidden catalog', async ({ page }) => {
  await accessFixture(page, { signedIn: true });
  await page.goto('/profile');
  await page.getByRole('button', { name: /Add company/ }).click();
  await expect(page).toHaveURL(/\/market$/);
  await expect(page.locator('.nav-catalog-wrap')).toHaveCount(0);
});
