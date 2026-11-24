export async function openMapFilters(page) {
  const panel = page.locator('.heatmap-sidebar-panel');
  if (await panel.count() && await panel.getAttribute('open') === null) {
    await panel.locator(':scope > summary').click();
  }
}

export async function chooseMapArea(page, value) {
  const option = page.locator(`.heatmap-size-options button[data-area="${value}"]`);
  await option.waitFor({state: 'attached'});
  await openMapFilters(page);
  await option.click();
}

export async function chooseMapTicker(page, ticker) {
  await page.locator('.heatmap-ticker-input input').fill(ticker);
  await page.locator(`.heatmap-ticker-list button[data-ticker="${ticker}"]`).click();
}
