import { buildMarketStats } from "../../shared/marketModel.jsx";
export function summarizeMarket({
  activeSector,
  byClass,
  isDormant,
  windowed,
  rowSector,
  mktCapOf
}) {
  const cardSector = activeSector;
  const stats = buildMarketStats(byClass.filter(r => !isDormant(r)), {
    windowed
  });
  const cardStats = cardSector ? buildMarketStats(byClass.filter(r => !isDormant(r) && rowSector(r) === cardSector), {
    windowed
  }) : stats;
  const moverStats = cardStats;
  const capPeriodChange = (() => {
    if (!windowed) return null;
    const pool = byClass.filter(r => !isDormant(r) && (!cardSector || rowSector(r) === cardSector));
    let now = 0;
    let before = 0;
    pool.forEach(r => {
      const cap = mktCapOf(r);
      const pct = r.changePercent;
      if (!(cap > 0) || !Number.isFinite(pct) || pct <= -100) return;
      now += cap;
      before += cap / (1 + pct / 100);
    });
    return before > 0 ? (now - before) / before * 100 : null;
  })();
  const sectorDormant = cardSector ? byClass.filter(r => isDormant(r) && rowSector(r) === cardSector).length : 0;
  const periodMovers = moverStats;
  return {
    cardSector,
    stats,
    cardStats,
    capPeriodChange,
    sectorDormant,
    periodMovers
  };
}
