export async function openMapFilters(page) {
  const panel = page.locator('.heatmap-sidebar-panel');
  if (await panel.count() && await panel.getAttribute('open') === null) {
    await panel.locator(':scope > summary').click();
  }
}

export async function chooseMapArea(page, value) {
  await openMapFilters(page);
  await page.locator(`.heatmap-size-options button[data-area="${value}"]`).click();
}

export async function chooseMapTicker(page, ticker) {
  await openMapFilters(page);
  await page.locator(`.heatmap-ticker-list button[data-ticker="${ticker}"]`).click();
}
