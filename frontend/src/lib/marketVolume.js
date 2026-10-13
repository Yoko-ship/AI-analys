import { marketRowDay } from "./valuation.js";

export function avgSharePrice(row) {
  const vol = row?.stockVolume, qty = row?.stockQuantity;
  return Number.isFinite(vol) && Number.isFinite(qty) && qty > 0 ? vol / qty : null;
}

// Over a period the server states the average deal itself (`avgTrade`), over the
// sessions that counted their deals. Dividing the whole period's сумы by those
// sessions' deals overstated it whenever the archive could not count some days —
// BNGPP over a month read 491 226 against 453 719, and 291 cells did likewise.
export function avgTradeValue(row) {
  if (Number.isFinite(row?.avgTrade)) return row.avgTrade;
  const vol = row?.stockVolume, count = row?.stockTradeCount;
  return Number.isFinite(vol) && Number.isFinite(count) && count > 0 ? vol / count : null;
}

export function marketVolumeShare(row, stats) {
  if (stats?.boardDay && marketRowDay(row) !== stats.boardDay) return 0;
  return Number.isFinite(row?.stockVolume) && stats?.totalVolume > 0
    ? row.stockVolume / stats.totalVolume * 100 : null;
}

export function marketVolumeMetrics(row, stats) {
  const finite = (value) => Number.isFinite(value) ? value : null;
  return {
    volume: finite(row?.stockVolume),
    volQty: finite(row?.stockQuantity),
    avgShare: Number.isFinite(row?.avgPrice) ? row.avgPrice : avgSharePrice(row),
    avgTrade: avgTradeValue(row),
    bigTrade: finite(row?.ts?.largest_value),
    volShare: marketVolumeShare(row, stats),
  };
}
