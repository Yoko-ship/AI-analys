
import { marketTone } from "../lib/marketData.js";
import { formatMarketNumber, formatRatio } from "./format.jsx";

function MarketChangeBadge({ value, percent, language }) {
  const tone = marketTone(percent);
  const sign = Number(value) > 0 ? "+" : "";
  const percentSign = Number(percent) > 0 ? "+" : "";
  // A change over a WINDOW arrives as a percent alone: its absolute counterpart
  // would subtract a live price from a settled close of weeks ago, two figures
  // the exchange never puts side by side. The session's change carries both,
  // because both come off the same row.
  if (value === undefined && Number.isFinite(percent)) {
    return (
      <span className={`market-change-badge tone-${tone}`}>
        {`${percentSign}${formatRatio(percent, 2, language)}%`}
      </span>
    );
  }
  return (
    <span className={`market-change-badge tone-${tone}`}>
      {value === null || percent === null
        ? "—"
        : `${sign}${formatMarketNumber(value, language)} · ${percentSign}${formatRatio(percent, 2, language)}%`}
    </span>
  );
}

export { MarketChangeBadge };
