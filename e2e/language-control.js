const languageNames = { ru: 'Русский', uz: 'O‘zbekcha', en: 'English' };

export async function openAccountMenu(page) {
  if (!await page.locator('.account-preferences').isVisible()) await page.locator('.topbar .account-button').click();
}

export async function selectLanguage(page, language) {
  await openAccountMenu(page);
  await page.locator('#languageSelect').click();
  await page.getByRole('option', { name: languageNames[language], exact: true }).click();
  await page.keyboard.press('Escape');
}

export async function toggleTheme(page) {
  await openAccountMenu(page);
  await page.locator('.account-preferences .theme-toggle').click();
  await page.keyboard.press('Escape');
}
