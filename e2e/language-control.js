const languageNames = { ru: 'Русский', uz: 'O‘zbekcha', en: 'English' };

export async function selectLanguage(page, language) {
  await page.locator('#languageSelect').click();
  await page.getByRole('option', { name: languageNames[language], exact: true }).click();
}
