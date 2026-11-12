// IBM Plex Mono has a fixed advance near .6em. Reserve a little extra for
// rounding, and fit the actual ticker and formatted change before decoration.
const advance = .62;
const minimum = 8;

export function heatmapTileLabels(width, height, ticker, change, badgeWidth = 0) {
  const padding = width < 58 || height < 40 ? 2 : 5;
  const availableWidth = Math.max(0, width - 2 * (padding + 1));
  const availableHeight = Math.max(0, height - 2 * (padding + 1));
  const tickerUnits = Math.max(1, Array.from(ticker).length) * advance;
  const changeUnits = Math.max(1, Array.from(change).length) * advance;
  // A short, wide cell can carry both figures on one line even when there
  // isn't enough height for the usual stack (SANE was a common example).
  const rowSize = Math.min(16, availableHeight / 1.05,
    (availableWidth - 6 - badgeWidth) / (tickerUnits + changeUnits * .78));
  if (height < 40 && rowSize * .78 >= minimum) {
    return {flow: 'row', padding, showTicker: true, showPercent: true,
      tickerSize: rowSize, percentSize: rowSize * .78};
  }
  const showTicker = availableWidth - badgeWidth >= tickerUnits * minimum && availableHeight >= minimum * 1.05;
  const showPercent = availableWidth >= changeUnits * minimum && availableHeight >= (showTicker ? minimum * 2.1 + 2 : minimum * 1.05);
  const tickerSize = Math.max(minimum, Math.min(21,
    (availableWidth - badgeWidth) / tickerUnits,
    showPercent ? (availableHeight - 2) / (1.05 * 1.78) : availableHeight / 1.05));
  const percentSize = Math.max(minimum, Math.min(tickerSize * .78, availableWidth / changeUnits));
  return {flow: 'column', padding, showTicker, showPercent, tickerSize, percentSize};
}
