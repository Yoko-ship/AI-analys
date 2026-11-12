export async function chooseMapArea(page, value) {
  await page.locator(`.heatmap-size-options button[data-area="${value}"]`).click();
}

export async function chooseMapTicker(page, ticker) {
  await page.locator(`.heatmap-ticker-list button[data-ticker="${ticker}"]`).click();
}
