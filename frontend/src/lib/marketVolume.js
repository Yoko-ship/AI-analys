import { marketRowDay } from "./valuation.js";

export function avgSharePrice(row) {
  const vol = row?.stockVolume, qty = row?.stockQuantity;
  return Number.isFinite(vol) && Number.isFinite(qty) && qty > 0 ? vol / qty : null;
}

export function avgTradeValue(row) {
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
