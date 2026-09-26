import { changePeriodLabel } from "../../shared/marketPeriods.jsx";
import { avgSharePrice, avgTradeValue, finValue, marketDisplayPrice, sessionCountLabel, tradeCountLabel } from "../../shared/marketModel.jsx";
import { mt } from "../../shared/marketCopy.jsx";
import { RangeHelpIcon, incompleteIssuerCapAvailability, lossLabel, lossTitle, multipleStatusText, notApplicableTitle, outlierLabel, outlierTitle } from "../../shared/valuationLabels.jsx";
import { formatMarketNumber, formatRatio } from "../../shared/format.jsx";
import { finFieldCoverage, finFieldPeriod, finPeriodCoverage, marketRowDay } from "../../lib/valuation.js";
import { MarketChangeBadge } from "../../shared/MarketChangeBadge.jsx";
export function createMarketCells({
  lang,
  finOf,
  ratioOf,
  changeOver,
  MARKET_COLS,
  windowed,
  changePeriod,
  MOVABLE_KEYS,
  parOf,
  priceToPar,
  stats,
  mktCapOf,
  valuationOf,
  multipleOf,
  multiplesOf
}) {
  const statusText = status => multipleStatusText(status, lang);
  const multipleCell = (row, metric, digits, suffix = "×") => {
    // Keep an outlier visible for audit, but label it so it is never mistaken
    // for an ordinary comparable multiple.
    if (metric?.value != null && metric.status === "out_of_range") {
      const help = outlierTitle(metric, digits, suffix, lang);
      return (
        <td className="num">
          <strong>{formatRatio(metric.value, digits, lang)}{suffix}</strong>
          <span className="fin-cell-period metric-warning metric-warning--out_of_range">
            {outlierLabel(lang)} <RangeHelpIcon title={help} />
          </span>
        </td>
      );
    }
    if (metric?.value != null) {
      const flags = [];
      if (metric.estimate) flags.push(mt(lang, "estimateFlag"));
      const period = metric.base_period || metric.financial_period || null;
      const title = [
        period,
        metric.denominator_period && metric.denominator_period !== period
          ? `${lang === "ru" ? "средняя база" : lang === "uz" ? "o‘rtacha baza" : "average base"}: ${metric.denominator_period}`
          : null,
        metric.note,
        metric.allowed ? `∉ [${metric.allowed.join("; ")}]` : null,
      ].filter(Boolean).join(" · ") || undefined;
      const sub = [period, ...flags].filter(Boolean).join(" · ");
      return (
        <td className="num" title={title}>
          <strong>{formatRatio(metric.value, digits, lang)}{suffix}</strong>
          {sub && <span className="fin-cell-period">{sub}</span>}
        </td>
      );
    }
    if (metric?.computed != null && metric.status === "loss_making") {
      return (
        <td className="num">
          <span className="cell-status" title={lossTitle(metric, digits, suffix, lang)}>{lossLabel(lang)}</span>
        </td>
      );
    }
    if (metric?.computed != null && metric.status === "unverified") {
      const period = metric?.base_period || null;
      return (
        <td className="num" title={period || undefined}>
          <strong>{formatRatio(metric.computed, digits, lang)}{suffix}</strong>
          {period && <span className="fin-cell-period">{period}</span>}
        </td>
      );
    }
    const issuerCapGap = incompleteIssuerCapAvailability(
      metric, multiplesOf(row)?.market_cap_issuer, row?.ticker, lang,
    );
    const label = issuerCapGap?.label || statusText(metric?.status);
    if (!label) return <td className="num">{noSecLabel(row)}</td>;
    if (metric?.status === "not_applicable") {
      return (
        <td className="num">
          <span className="cell-status">{label} <RangeHelpIcon title={notApplicableTitle(lang)} /></span>
        </td>
      );
    }
    const reasons = issuerCapGap?.title || (metric?.reasons || []).join("; ")
      || (metric?.computed != null
        ? `${formatRatio(metric.computed, digits, lang)}${suffix} ∉ [${metric.allowed?.join(", ")}]`
        : metric?.note || "");
    const period = metric?.base_period ? ` · ${metric.base_period}` : "";
    return <td className="num"><span className="cell-status" title={(reasons + period).trim() || undefined}>{label}</span></td>;
  };
  const noSecLabel = r => r.isin ? "—" : lang === "ru" ? "нет бумаг" : lang === "uz" ? "qog'oz yo'q" : "no securities";
  const naLabel = () => lang === "ru" ? "н/п" : lang === "uz" ? "t/e" : "n/a";
  const tsDate = r => {
    const d = String(r.ts?.trade_date || "");
    return /^\d{8}$/.test(d) ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` : null;
  };
  const neverTraded = r => !r.last_trade_date && !r.ts ? mt(lang, "noTrade") : "—";
  const finCell = (row, field, {
    naWhenTopLine = false
  } = {}) => {
    const f = finOf(row.ticker);
    const value = f?.[field];
    if (value == null && naWhenTopLine && Number.isFinite(f?.revenue)) {
      return <td className="num">{naLabel()}</td>;
    }
    if (!Number.isFinite(value)) return <td className="num">—</td>;
    const period = finFieldPeriod(f, field);
    const borrowed = Boolean((f?.field_periods || {})[field]);
    const coverage = finPeriodCoverage(period, lang);
    // How much trading the figure covers, printed rather than only hovered: NSBU
    // quarters are cumulative, so this column routinely sets one issuer's six
    // months beside another's three and a third's completed year. Balance lines
    // get no suffix — they are a position on the closing date, not an accumulation.
    const length = finFieldCoverage(period, field, lang);
    return <td className="num">
        <strong>{finValue(value, lang)}</strong>
        {period && <span className={`fin-cell-period${borrowed ? " borrowed" : ""}`} title={borrowed ? `${period} · ${coverage} — ${lang === "ru" ? "период отличается от периода строки" : lang === "uz" ? "davr qator davridan farq qiladi" : "a different period than the row"}` : `${period} · ${coverage}`}>
            {period}{length ? ` · ${length}` : ""}{borrowed ? " *" : ""}
          </span>}
      </td>;
  };
  const LIQUIDITY_FIELDS = new Set(["current_ratio", "quick_ratio"]);
  const ratioCell = (row, field, {
    digits = 2,
    suffix = ""
  } = {}) => {
    const r = ratioOf(row.ticker);
    const value = r?.[field];
    if (!Number.isFinite(value)) {
      const form = finOf(row.ticker)?.org_type;
      if (LIQUIDITY_FIELDS.has(field) && form === "bank") {
        return <td className="num">
            <span className="cell-status" title={lang === "en" ? "The bank balance is not split into current and non-current assets — no liquidity ratio is defined on it" : lang === "uz" ? "Bank balansi joriy va uzoq muddatli aktivlarga bo'linmaydi — likvidlik koeffitsiyenti aniqlanmaydi" : "Банковский баланс не делится на текущие и долгосрочные активы — коэффициент ликвидности на нём не определён"}>
              {lang === "en" ? "n/a" : "н/п"}
            </span>
          </td>;
      }
      return <td className="num">—</td>;
    }
    const period = (r.periods || {})[field] || null;
    return <td className="num">
        {formatRatio(value, digits, lang)}{suffix}
        {period && <span className="fin-cell-period">{period}</span>}
      </td>;
  };
  const sessionChangeCell = row => {
    if (!row.tradedToday) {
      const when = row.last_trade_date || row.ts?.trade_date;
      return <td className="num">
          <span className="cell-status" title={when ? `${lang === "ru" ? "цена за" : lang === "uz" ? "narx" : "price from"} ${when}` : undefined}>
            {lang === "en" ? "no trades" : lang === "uz" ? "bitim yo'q" : "нет сделок"}
          </span>
        </td>;
    }
    return <td className="num"><MarketChangeBadge value={row.changeValue} percent={row.changePercent} language={lang} /></td>;
  };
  const windowChangeCell = (row, code) => {
    const hit = changeOver(row.ticker, code);
    if (!hit) {
      return <td className="num">
          <span className="cell-status" title={lang === "en" ? "no settled close that far back" : lang === "uz" ? "bu davr uchun yopilish narxi yo'q" : "нет закрытия за этот период"}>—</span>
        </td>;
    }
    const from = String(hit.from || "");
    const pretty = from.length === 8 ? `${from.slice(6)}.${from.slice(4, 6)}.${from.slice(0, 4)}` : from;
    return <td className="num" title={pretty ? `${lang === "en" ? "from the close of" : lang === "uz" ? "yopilishdan" : "от закрытия"} ${pretty}` : undefined}>
        <MarketChangeBadge percent={hit.pct} language={lang} />
      </td>;
  };
  const PERIOD_COLS = new Set(["open", "high", "low", "volume", "volQty", "avgShare", "avgTrade", "bigTrade", "volShare"]);
  const LABEL_OF = Object.fromEntries([["last", mt(lang, "last")], ...MARKET_COLS].map(([k, label]) => [k, windowed && PERIOD_COLS.has(k) ? `${label} · ${changePeriodLabel(changePeriod, lang, "short")}` : label]));
  const NUM_COLS = new Set(MOVABLE_KEYS.filter(k => k !== "date" && k !== "source"));
  const prettyDay = d => {
    const v = String(d || "");
    return v.length === 8 ? `${v.slice(6)}.${v.slice(4, 6)}.${v.slice(0, 4)}` : v;
  };
  const periodHint = (row, {
    extremes = false,
    detail = false
  } = {}) => {
    if (!windowed || !row?.periodSessions) return undefined;
    const label = changePeriodLabel(changePeriod, lang, "short");
    const sessions = `${formatRatio(row.periodSessions, 0, lang)} ${sessionCountLabel(row.periodSessions, lang)}`;
    const span = row.periodFrom ? `${lang === "en" ? "from" : lang === "uz" ? "dan" : "с"} ${prettyDay(row.periodFrom)}${row.periodTo ? ` ${lang === "en" ? "to" : lang === "uz" ? "gacha" : "по"} ${prettyDay(row.periodTo)}` : ""}` : "";
    // A session banked before the day statistics existed carries no high or low,
    // and its close stands in for both. The extreme is then a bound, not a
    // reading, and the cell that shows it says so rather than implying precision.
    const bound = extremes && row.periodApprox ? lang === "en" ? "some sessions counted by their close" : lang === "uz" ? "ba'zi sessiyalar yopilish narxi bo'yicha" : "по закрытиям части сессий" : "";
    // The deal count and the largest deal exist only for the sessions banked
    // with the day statistics beside them; over a year that is a subset, and a
    // floor presented as a total is the one thing these cells must not be.
    const partial = detail && row.periodDetailSessions ? lang === "en" ? `by ${formatRatio(row.periodDetailSessions, 0, lang)} of ${formatRatio(row.periodSessions, 0, lang)} sessions` : lang === "uz" ? `${formatRatio(row.periodSessions, 0, lang)} sessiyadan ${formatRatio(row.periodDetailSessions, 0, lang)} tasi bo'yicha` : `по ${formatRatio(row.periodDetailSessions, 0, lang)} из ${formatRatio(row.periodSessions, 0, lang)} сессий` : "";
    return [label, sessions, span, bound, partial].filter(Boolean).join(" · ");
  };
  const CELL_OF = {
    last: row => <td className="num">{(() => {
        const p = marketDisplayPrice(row);
        return p == null ? "—" : formatMarketNumber(p, lang);
      })()}</td>,
    // ТЗ §2.4/§9: "отсутствие данных показывается как нулевое изменение" was
    // the defect. This cell substituted 0 whenever a close price existed, so a
    // security that has not traded since 15.07 read as "unchanged today" beside
    // securities that genuinely did not move. Measured against the trade
    // archive, seven rows showed 0 % where the last real session moved by up to
    // 20 %. No trading in this session means no change to report — the cell
    // says so, and names the day the price is actually from.
    change: row => changePeriod === "1d" ? sessionChangeCell(row) : windowChangeCell(row, changePeriod),
    change1w: row => windowChangeCell(row, "1w"),
    change1m: row => windowChangeCell(row, "1m"),
    nominal: row => {
      const par = parOf(row);
      return <td className="num">{par == null ? "—" : formatMarketNumber(par, lang)}</td>;
    },
    priceToPar: row => {
      const ratio = priceToPar(row);
      return <td className="num" title={ratio == null ? undefined : lang === "en" ? `price ${formatMarketNumber(marketDisplayPrice(row), lang)} · par ${formatMarketNumber(parOf(row), lang)}` : lang === "uz" ? `narx ${formatMarketNumber(marketDisplayPrice(row), lang)} · nominal ${formatMarketNumber(parOf(row), lang)}` : `цена ${formatMarketNumber(marketDisplayPrice(row), lang)} · номинал ${formatMarketNumber(parOf(row), lang)}`}>
          {ratio == null ? "—" : `${formatRatio(ratio, 2, lang)}×`}
        </td>;
    },
    // Over a window `openPrice` is the period's own opening price and is
    // `undefined` when no stored session can say — which is why the fallback
    // below tests for `null` exactly: a window with no open must print a dash,
    // never today's quote under a heading that says a year.
    open: row => <td className="num" title={periodHint(row)}>{(() => {
        const v = row.openPrice !== null ? row.openPrice : marketDisplayPrice(row);
        return v == null ? "—" : formatMarketNumber(v, lang);
      })()}</td>,
    high: row => <td className="num" title={periodHint(row, {
      extremes: true
    })}>{(() => {
        const v = row.highPrice !== null ? row.highPrice : marketDisplayPrice(row);
        return v == null ? "—" : formatMarketNumber(v, lang);
      })()}</td>,
    low: row => <td className="num" title={periodHint(row, {
      extremes: true
    })}>{(() => {
        const v = row.lowPrice !== null ? row.lowPrice : marketDisplayPrice(row);
        return v == null ? "—" : formatMarketNumber(v, lang);
      })()}</td>,
    volume: row => <td className="num" title={periodHint(row)}>
        {row.stockVolume !== null ? formatRatio(row.stockVolume, 0, lang) : "—"}
        {row.stockTradeCount !== null && <span title={periodHint(row, {
        detail: true
      })}>{formatRatio(row.stockTradeCount, 0, lang)} {tradeCountLabel(row.stockTradeCount, lang)}</span>}
      </td>,
    volQty: row => <td className="num" title={periodHint(row)}>{row.stockQuantity !== null ? formatRatio(row.stockQuantity, 0, lang) : "—"}</td>,
    avgShare: row => {
      const v = Number.isFinite(row.avgPrice) ? row.avgPrice : avgSharePrice(row);
      return <td className="num" title={periodHint(row)}>{v === null || v === undefined ? neverTraded(row) : formatMarketNumber(v, lang)}</td>;
    },
    avgTrade: row => <td className="num" title={periodHint(row, {
      detail: true
    })}>{avgTradeValue(row) !== null ? formatRatio(avgTradeValue(row), 0, lang) : neverTraded(row)}</td>,
    // Over a window this is the biggest deal of the whole period, and the
    // tooltip names the session it was struck in — «крупнейшая сделка за год»
    // is a fact about one day inside the year.
    bigTrade: row => <td className="num" title={periodHint(row, {
      detail: true
    })}>
        {row.ts && Number.isFinite(row.ts.largest_value) ? <>
            {formatRatio(row.ts.largest_value, 0, lang)}
            <span>
              {Number.isFinite(row.ts.largest_qty) ? `${formatRatio(row.ts.largest_qty, 0, lang)} ${mt(lang, "tradeQtyUnit")}` : ""}
              {Number.isFinite(row.ts.largest_pct_value) ? ` · ${formatRatio(row.ts.largest_pct_value, 1, lang)}%` : ""}
            </span>
          </> : neverTraded(row)}
      </td>,
    volShare: row => <td className="num" title={periodHint(row)}>{(() => {
        // Share of the LATEST session's turnover: an untraded security's
        // backfilled old-day volume contributes 0% of today, by definition.
        // Over a window there is no such session — `stats.boardDay` is null — and
        // the share is of the window's own total, which is the same statement one
        // period longer.
        if (stats.boardDay && marketRowDay(row) !== stats.boardDay) return `0%`;
        return Number.isFinite(row.stockVolume) && stats.totalVolume > 0 ? `${formatRatio(row.stockVolume / stats.totalVolume * 100, 2, lang)}%` : "—";
      })()}</td>,
    finRevenue: row => finCell(row, "revenue"),
    // Bank/insurer/fund filings have no gross-profit or operating-income
    // lines (their reporting form differs) — when the issuer's top line IS
    // published but the form carries no such line, say "not applicable"
    // instead of an ambiguous dash.
    finGross: row => finCell(row, "gross_profit", {
      naWhenTopLine: true
    }),
    finCash: row => finCell(row, "cash"),
    finLiab: row => finCell(row, "total_liabilities"),
    finNet: row => finCell(row, "net_income"),
    finOperating: row => finCell(row, "operating_income", {
      naWhenTopLine: true
    }),
    mktCap: row => <td className="num">{(() => {
        const v = mktCapOf(row);
        return v == null ? noSecLabel(row) : formatRatio(v, 0, lang);
      })()}</td>,
    pe: row => {
      const m = valuationOf(row).pe;
      if (m?.value == null || m.status === "out_of_range") return multipleCell(row, m, 2);
      // Name the earnings period on the cell: this is the one multiple whose
      // denominator can come from a different filing than the row's own figures.
      const period = m.base_period;
      const months = m.base_months;
      return <td className="num" title={period ? `${lang === "ru" ? "прибыль за" : lang === "uz" ? "foyda" : "earnings for"} ${period}${months ? ` · ${months} ${lang === "ru" ? "мес." : lang === "uz" ? "oy" : "months"}` : ""}` : undefined}>
          <strong>{formatRatio(m.value, 2, lang)}×</strong>
          {(() => {
          const sub = [period, m.estimate ? mt(lang, "estimateFlag") : null].filter(Boolean).join(" · ");
          return sub ? <span className="fin-cell-period">{sub}</span> : null;
        })()}
        </td>;
    },
    pb: row => multipleCell(row, valuationOf(row).pb, 2),
    ps: row => multipleCell(row, multipleOf(row, "ps"), 2),
    roe: row => multipleCell(row, multipleOf(row, "roe"), 1, "%"),
    roa: row => multipleCell(row, multipleOf(row, "roa"), 1, "%"),
    netMargin: row => multipleCell(row, multipleOf(row, "net_margin"), 1, "%"),
    eqAssets: row => multipleCell(row, multipleOf(row, "equity_assets"), 1, "%"),
    currentRatio: row => ratioCell(row, "current_ratio"),
    quickRatio: row => ratioCell(row, "quick_ratio"),
    debtAssets: row => ratioCell(row, "debt_ratio", {
      digits: 1,
      suffix: "%"
    }),
    assetTurnover: row => ratioCell(row, "total_asset_turnover"),
    roce: row => ratioCell(row, "return_to_capital_employed"),
    date: row => <td>
        {/* The live feed reports last_trade_date=null for some securities
            that did trade — the backfilled day stats carry the real date. */}
        <strong>{row.last_trade_date || tsDate(row) || mt(lang, "noTrade")}</strong>
        {row.close_date && <span>{mt(lang, "closeDate")} {row.close_date}</span>}
      </td>,
    source: row => <td>
        {row.url ? <a className="market-source-link" href={row.url} target="_blank" rel="noreferrer">{mt(lang, "source")}</a> : "—"}
      </td>
  };
  return {
    LABEL_OF,
    NUM_COLS,
    CELL_OF
  };
}
