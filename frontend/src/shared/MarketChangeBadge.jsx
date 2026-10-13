
import { marketTone } from "../lib/marketData.js";
import { formatChangePercent, formatMarketChange } from "./format.jsx";

function MarketChangeBadge({ value, percent, language }) {
  const tone = marketTone(percent);
  // A change over a WINDOW arrives as a percent alone: its absolute counterpart
  // would subtract a live price from a settled close of weeks ago, two figures
  // the exchange never puts side by side. The session's change carries both,
  // because both come off the same row.
  if (value === undefined && Number.isFinite(percent)) {
    return (
      <span className={`market-change-badge tone-${tone}`}>
        {formatChangePercent(percent, language)}
      </span>
    );
  }
  return (
    <span className={`market-change-badge tone-${tone}`}>
      {formatMarketChange(value, percent, language)}
    </span>
  );
}

export { MarketChangeBadge };
