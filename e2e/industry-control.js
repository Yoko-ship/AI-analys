import {expect} from '@playwright/test';
import {openMapFilters} from './helpers/map-controls.js';

export async function openIndustryChooser(page) {
  await openMapFilters(page);
  const trigger = page.locator('.market-industry-trigger');
  await expect(trigger).toBeAttached();
  if (!await trigger.isVisible()) await page.locator('.market-secondary > summary').click();
  const menu = page.locator('.industry-menu');
  if (!await menu.isVisible()) await trigger.click();
  await expect(menu).toBeVisible();
  return menu;
}

export async function chooseIndustry(page, value) {
  const menu = await openIndustryChooser(page);
  await menu.locator(`button[data-value="${value}"]`).click();
  await expect(menu).toHaveCount(0);
}
