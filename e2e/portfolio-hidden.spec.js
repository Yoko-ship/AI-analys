import { test, expect } from '@playwright/test';

for (const [device, width] of [['desktop', 1440], ['phone', 390]]) {
  for (const signedIn of [false, true]) {
    test(`portfolio stays hidden on ${device} for ${signedIn ? 'members' : 'visitors'}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript(({ signedIn }) => {
        localStorage.setItem('uz_stock_analyzer_language', 'en');
        if (signedIn) localStorage.setItem('uz_stock_analyzer_token', 'hidden-portfolio-test');
      }, { signedIn });
      const portfolioRequests = [];
      await page.route('**/api/**', async route => {
        const path = new URL(route.request().url()).pathname;
        if (path.startsWith('/api/portfolio')) portfolioRequests.push(path);
        const user = signedIn ? { id: 99, full_name: 'Investor', email: 'investor@example.test', tier: 'free' } : null;
        const body = path === '/api/auth/me' ? { user }
          : path === '/api/profile' ? { ok: true, user, stats: {}, preferences: {}, favorites: [], recent_analyses: [], security: {} }
          : { ok: true, items: [], stocks: [], companies: [] };
        await route.fulfill({ json: body });
      });
      for (const path of ['/portfolio', '/uz/portfolio']) {
        await page.goto(path);
        await expect(page).toHaveURL(path.startsWith('/uz') ? /\/uz$/ : /\/$/);
        await expect(page.getByTestId('portfolio-market-value')).toHaveCount(0);
        await expect(page.locator('a[href$="/portfolio"]')).toHaveCount(0);
        await expect(page.getByRole('button', { name: /^(Portfolio|Портфель|Portfel)$/ })).toHaveCount(0);
      }
      if (signedIn) {
        await page.goto('/market');
        await page.getByRole('button', { name: /Account:|Аккаунт:|Akkaunt:/ }).click();
        await expect(page.getByRole('menu')).toBeVisible();
        await expect(page.getByRole('menuitem', { name: /Portfolio|Портфель|Portfel/ })).toHaveCount(0);
      }
      expect(portfolioRequests).toEqual([]);
    });
  }
}
