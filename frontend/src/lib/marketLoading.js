export function blocksMarketContent(loading, rowCount) {
  return Boolean(loading && Number(rowCount) <= 0);
}
