import { buildMarketStats } from "../../shared/marketModel.jsx";
export function summarizeMarket({
  activeIndustry,
  byClass,
  isDormant,
  windowed,
  matchesIndustry,
  mktCapOf
}) {
  const cardIndustry = activeIndustry;
  const stats = buildMarketStats(byClass.filter(r => !isDormant(r)), {
    windowed
  });
  const cardStats = cardIndustry ? buildMarketStats(byClass.filter(r => !isDormant(r) && matchesIndustry(r)), {
    windowed
  }) : stats;
  const capPeriodChange = (() => {
    if (!windowed) return null;
    const pool = byClass.filter(r => !isDormant(r) && matchesIndustry(r));
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
  const sectorDormant = cardIndustry ? byClass.filter(r => isDormant(r) && matchesIndustry(r)).length : 0;
  return {
    cardIndustry,
    stats,
    cardStats,
    capPeriodChange,
    sectorDormant
  };
}
