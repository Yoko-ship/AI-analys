

/* ── Расширенный график ─────────────────────────────────────────────────────
 * The reference page's «Expand to advanced chart», on our data: a page of its
 * own at /chart/{TICKER} carrying the whole toolbox — periods and a custom
 * range, four chart types, indicators, fundamentals as their own panes, the
 * peer comparison, a volume strip and a crosshair that reads every series at
 * once.
 *
 * Three things the reference has that our data cannot honestly carry, and are
 * therefore absent rather than faked:
 *   • 1D and 5D. The exchange publishes a SESSION, not a tape we keep — the
 *     smallest true unit here is one close. An intraday button would draw a
 *     day out of a single point.
 *   • Delayed live prices. Ours is the settled record; the header says so.
 *   • Analyst/estimate overlays. Nobody publishes them for this market.
 * ------------------------------------------------------------------------ */

/* The four chart types, as icons — the reference draws the shape each button
 * produces rather than naming it. The name stays as the tooltip and the
 * accessible label: an icon-only control that no screen reader can read is not
 * a simplification, and «От базы» is not a shape anyone recognises cold.
 *
 * Drawn at 24×24 with currentColor so one glyph serves idle, hover, active and
 * disabled without a second asset. */
const AC_TYPE_ICONS = {
  line: (
    <path d="M3 16.5l5-5.5 3.5 3L15 8l6 6.5" />
  ),
  candle: (
    <>
      <path d="M8.5 3.5v17M16 5v14" />
      <rect x="6" y="7.5" width="5" height="8" rx="1" />
      <rect x="13.5" y="9" width="5" height="6.5" rx="1" />
    </>
  ),
  area: (
    <>
      <path d="M3 19V9.5l5 4L12 6l4.5 6 4.5-3.5V19z" fill="currentColor" fillOpacity="0.22" />
      <path d="M3 9.5l5 4L12 6l4.5 6 4.5-3.5" />
    </>
  ),
  baseline: (
    <>
      <path d="M3 12.5h18" strokeDasharray="2.5 2.5" strokeOpacity="0.75" />
      <path d="M3 17l4-7.5 3.5 5 4-8.5 6.5 8" />
    </>
  ),
};

const AC_TYPES = [
  { key: "line", label: ["Линия", "Chiziq", "Line"] },
  { key: "area", label: ["Область", "Maydon", "Area"] },
  { key: "baseline", label: ["От базы", "Bazadan", "Baseline"] },
  { key: "candle", label: ["Свечи", "Shamlar", "Candles"] },
  { key: "bars", label: ["Бары", "Barlar", "Bars"] },
  { key: "columns", label: ["Колонки", "Ustunlar", "Columns"] },
  { key: "kagi", label: ["Каги", "Kagi", "Kagi"] },
  { key: "point_figure", label: ["Крестики-нолики", "Nuqta va shakl", "Point and Figure"] },
  { key: "heikin_ashi", label: ["Хейкин Аши", "Heikin Ashi", "Heikin Ashi"] },
  { key: "renko", label: ["Ренко", "Renko", "Renko"] },
];

const AC_SYNTHETIC_TYPES = new Set(["kagi", "point_figure", "heikin_ashi", "renko"]);

const AC_OHLC_TYPES = new Set(["candle", "bars", "heikin_ashi"]);

const AC_COMPARISON_TYPES = new Set(["line", "area", "baseline", "columns"]);

// Windows are CALENDAR DAYS, never bars — see lib/indicators.js for why that
// is a correctness matter here and not a preference. The labels say «дн.» so
// the screen states the same window the calculation used.
const AC_INDICATORS = [
  { key: "sma50", pane: "price", n: 50, color: "#3b82f6", label: ["SMA 50 дн.", "SMA 50 kun", "SMA 50d"] },
  { key: "sma200", pane: "price", n: 200, color: "#8b5cf6", label: ["SMA 200 дн.", "SMA 200 kun", "SMA 200d"] },
  { key: "ema50", pane: "price", n: 50, color: "#f59e0b", label: ["EMA 50 дн.", "EMA 50 kun", "EMA 50d"] },
  { key: "ema200", pane: "price", n: 200, color: "#ec4899", label: ["EMA 200 дн.", "EMA 200 kun", "EMA 200d"] },
  { key: "bb", pane: "price", n: 20, color: "#14b8a6", label: ["Полосы Боллинджера 20 дн.", "Bollinger 20 kun", "Bollinger Bands 20d"] },
  { key: "rsi", pane: "sub", n: 14, color: "#22d3ee", label: ["RSI 14 дн.", "RSI 14 kun", "RSI 14d"] },
  { key: "macd", pane: "sub", color: "#f472b6", label: ["MACD 12/26/9", "MACD 12/26/9", "MACD 12/26/9"] },
  { key: "stoch", pane: "sub", n: 14, color: "#a3e635", label: ["Стохастик 14/3", "Stoxastik 14/3", "Stochastic 14/3"] },
];

// The fundamentals the fact store actually holds, in statement order. The
// reference offers twenty-five lines because it buys an estimates feed; these
// twenty are the ones /api/company/{t}/financials can answer from filings.
const AC_FIN_FIELDS = [
  "net_revenue", "gross_profit", "operating_expenses", "operating_income", "net_profit",
  "total_assets", "total_liabilities", "total_equity", "cash",
  "roe", "roa", "return_to_capital_employed",
  "net_margin", "gross_profit_margin", "ebit_margin",
  "current_ratio", "quick_ratio", "debt_ratio", "debt_to_equity", "total_asset_turnover",
];

const AC_FIN_MAX = 2;

const AC_FIN_COLORS = ["#38bdf8", "#fb923c"];

/** A percentage-style fundamental is drawn and labelled as one. */
const acFinIsRate = (field) => /(_margin|^roe$|^roa$|_ratio$|return_to_capital|_turnover$)/.test(field);

/**
 * An annual figure placed on a daily axis.
 *
 * The value of period Y is attached to 31 December Y and carried forward from
 * there — never backwards over the year it describes. A reader looking at
 * March 2025 must not see the 2025 result: it did not exist yet, and drawing
 * it there is the one mistake that turns a fundamentals overlay into
 * hindsight dressed as information.
 */
function acFinancialAtDates(values, dates) {
  const years = Object.keys(values || {})
    .filter((y) => Number.isFinite(Number(values[y])))
    .sort();
  if (!years.length) return dates.map(() => null);
  let j = 0, held = null;
  return dates.map((d) => {
    const iso = String(d);
    while (j < years.length && `${years[j]}-12-31` <= iso) { held = Number(values[years[j]]); j += 1; }
    return held;
  });
}

export { AC_COMPARISON_TYPES, AC_FIN_COLORS, AC_FIN_FIELDS, AC_FIN_MAX, AC_INDICATORS, AC_OHLC_TYPES, AC_SYNTHETIC_TYPES, AC_TYPES, AC_TYPE_ICONS, acFinIsRate, acFinancialAtDates };
