import { expect } from '@playwright/test';

export async function expectPlainActiveNavigation(page, theme) {
  const active = page.locator('.topbar .topbar-nav-btn.active');
  await expect(active).toHaveCount(1);
  await expect(active).toHaveCSS('color', theme === 'dark' ? 'rgb(138, 180, 255)' : 'rgb(6, 61, 233)');
  await expect(active).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await expect(active).toHaveCSS('border-top-width', '0px');
  await expect(active).toHaveCSS('box-shadow', 'none');
}
