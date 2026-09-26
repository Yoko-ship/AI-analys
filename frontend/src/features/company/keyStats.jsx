import { signedFixed } from "../../shared/format.jsx";
import { formatMarketNumber, formatRatio, safeNumber } from "../../shared/format.jsx";
import { avgSharePrice, formatCompactVolume } from "../../shared/marketModel.jsx";
import { RangeHelpIcon, incompleteIssuerCapAvailability, lossLabel, lossTitle, multipleStatusText, notApplicableTitle, outlierLabel, outlierTitle } from "../../shared/valuationLabels.jsx";
import { chartRange } from "../../shared/priceChartModel.jsx";

// The key-stats rail — what the session did, what the issuer is worth, and on
// what basis. It sits beside the chart instead of below it because the numbers
// a reader opens a company page for were previously two screens down, behind a
// chart that filled the first one.
//
// Every valuation figure here comes from /api/market/multiples — the same
// issuer-level envelope the market board reads, audit suppression included. The
// page used to recompute P/E and P/B on the client at CLASS level, which is the
// wrong denominator for a two-class issuer and, worse, bypassed the auditor: a
// figure the board withheld as «снято аудитом» still printed here.
/**
 * «5 сессий», «61 сессия», «113 сессий».
 *
 * A fixed «сессий» is right for 5 and wrong for 61, and this number is printed
 * under every period the reader picks — 21, 61 and 209 all occur on one page's
 * worth of buttons. Russian agrees on the LAST digit, except in the teens.
 */
/**
 * A signed change, rounded FIRST: -0.004 must print «0.00», not «-0.00».
 * UZIR's header read «-0.41 (-0.00%)» because the sign came from the raw
 * value while the digits came from the rounded one.
 */
/**
 * Relative volume: the day's turnover against the average of its previous
 * 20 TRADED sessions. A carried-forward row holds a zero turnover — that is
 * the absence of a session, not a small one, and averaging zeros in would
 * call every trade on an illiquid name «×40». Fewer than 3 prior traded
 * sessions and nothing is claimed.
 */


/**
 * A peer's session volume and its «к среднему» multiple at one date — or null
 * when the peer did not trade that day. A carried-forward close has no volume,
 * and «0 сум» would claim it traded nothing rather than not at all.
 */


/** «×3,1» — the one way a volume is comparable ACROSS securities. */




function sessionsWord(n, lang) {
  if (lang === "en") return n === 1 ? "session" : "sessions";
  if (lang === "uz") return "sessiya";
  const last = n % 10, teens = n % 100;
  if (teens >= 11 && teens <= 14) return "сессий";
  if (last === 1) return "сессия";
  if (last >= 2 && last <= 4) return "сессии";
  return "сессий";
}

function CompanyKeyStats({ row, sec, metrics12, metricsWindow, range, mult, dividends, lastPrice, securityType, lang, placement = "rail" }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const num = (v) => (Number.isFinite(v) ? formatMarketNumber(v, lang) : null);
  const compact = (v) => (Number.isFinite(v) ? formatCompactVolume(v, lang) : null);
  const count = (v) => (Number.isFinite(v) ? formatRatio(v, 0, lang) : null);

  // A plain row: rendered only when there is something to put in it. An empty
  // label with a dash tells the reader nothing they did not already know.
  const rows = [];
  const put = (label, value, hint) => {
    if (value == null || value === "") return;
    rows.push(
      <div className="company-metric-row" key={label}>
        <span className="panel-label">{label}</span>
        <span className="company-metric-val" title={hint || undefined}>{value}</span>
      </div>,
    );
  };

  // A multiple keeps the server's verdict: a value, or the reason it is absent.
  const putMultiple = (label, metric, digits = 2, suffix = "×", caption) => {
    if (!metric) return;
    let node;
    if (metric.computed != null && metric.status === "loss_making") {
      node = <span className="cell-status" title={lossTitle(metric, digits, suffix, lang)}>{lossLabel(lang)}</span>;
    } else if (metric.computed != null && metric.status === "unverified") {
      // Statement consistency findings remain available to the internal audit,
      // while the storefront publishes the calculated value.
      node = <>{formatRatio(metric.computed, digits, lang)}{suffix}</>;
    } else if (metric.value != null && metric.status === "out_of_range") {
      const help = outlierTitle(metric, digits, suffix, lang);
      node = (
        <span>
          {formatRatio(metric.value, digits, lang)}{suffix}
          <span className="company-metric-warning"> · {outlierLabel(lang)} <RangeHelpIcon title={help} /></span>
        </span>
      );
    } else if (metric.value != null) {
      node = <>{formatRatio(metric.value, digits, lang)}{suffix}</>;
    } else {
      const issuerCapGap = incompleteIssuerCapAvailability(
        metric, mult?.market_cap_issuer, row?.ticker, lang,
      );
      const words = issuerCapGap?.label || multipleStatusText(metric.status, lang);
      if (!words) return;
      const why = issuerCapGap?.title || (metric.reasons || []).join("; ") || metric.note || "";
      node = metric.status === "not_applicable"
        ? <span className="cell-status">{words} <RangeHelpIcon title={notApplicableTitle(lang)} /></span>
        : <span className="cell-status" title={why || undefined}>{words}</span>;
    }
    rows.push(
      <div className="company-metric-row" key={label}>
        <span className="panel-label">
          {label}{caption ? <span className="co-metric-period"> · {caption}</span> : null}
        </span>
        <span className="company-metric-val">{node}</span>
      </div>,
    );
  };

  const low = row?.lowPrice, high = row?.highPrice;
  const win = metrics12?.window;
  const yearLow = win?.min_close?.value, yearHigh = win?.max_close?.value;

  // A range reads faster as a picture than as two numbers, and the marker is
  // the only thing on this page that says where today sits inside the year.
  const rangeBar = (lo, hi, at) => {
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return null;
    const pos = Number.isFinite(at) ? Math.min(100, Math.max(0, ((at - lo) / (hi - lo)) * 100)) : null;
    return (
      <div className="keystat-range">
        <div className="keystat-range-track">
          {pos != null && <span className="keystat-range-dot" style={{ left: `${pos}%` }} />}
        </div>
        <div className="keystat-range-ends">
          <span>{num(lo)}</span><span>{num(hi)}</span>
        </div>
      </div>
    );
  };

  const blocks = [];
  const pushBlock = (key, title, body, note) => {
    if (!body || (Array.isArray(body) && body.length === 0)) return;
    blocks.push(
      <div className="co-sidebar-block" data-block={key} key={key}>
        <h3 className="co-heading">{title}</h3>
        <div className="company-metrics-list">{body}</div>
        {note && <div className="keystat-note muted">{note}</div>}
      </div>,
    );
  };

  // --- Session -------------------------------------------------------------
  // Prices only: a 0 here is the board mirror's filler for a never-traded
  // listing, not a close anybody paid.
  const price = (v) => (Number.isFinite(v) && v > 0 ? num(v) : null);
  put(t("Пред. закрытие", "Oldingi yopilish", "Previous close"), price(row?.closePrice));
  put(t("Открытие", "Ochilish", "Open"), price(row?.openPrice));
  if (Number.isFinite(low) && Number.isFinite(high) && high > low) {
    put(t("Диапазон дня", "Kunlik diapazon", "Day range"), `${num(low)} – ${num(high)}`);
  }
  put(t("Оборот", "Aylanma", "Turnover"), compact(row?.stockVolume) ? `${compact(row.stockVolume)} UZS` : null);
  put(t("Бумаг", "Qog'ozlar", "Shares traded"), count(row?.stockQuantity));
  put(t("Сделок", "Bitimlar", "Trades"), count(row?.stockTradeCount));
  put(t("Средняя цена", "O'rtacha narx", "Average price"),
      price(Number.isFinite(row?.avgPrice) ? row.avgPrice : avgSharePrice(row)));
  // A negotiated deal is real money at a bilaterally agreed price — not a
  // session number. Its own line, never summed into the turnover above
  // (HMKB 14.08: 2,2 млрд бумаг по 55 при рынке 95,5–99,99).
  // Read off `nego`, which carries the deal whatever the session guard decided:
  // every negotiated deal on this market in August 2026 was older than its
  // security's last auction session, so the guard hid all of them from this line.
  // The DATE travels with the figure — a negotiated deal is a dated event, not a
  // running total, and «2,2 млрд» with no date reads as today's.
  const nego = row?.nego || (Number.isFinite(row?.ts?.block_value) && row.ts.block_value > 0
    ? { value: row.ts.block_value, date: null } : null);
  if (Number.isFinite(nego?.value) && nego.value > 0) {
    const day = String(nego.date || "");
    const shown = /^\d{8}$/.test(day) ? `${day.slice(6)}.${day.slice(4, 6)}.${day.slice(0, 4)}` : null;
    put(t("Пакетные сделки, вне сессии", "Paket bitimlar, sessiyadan tashqari", "Block trades, off-session"),
        <>{compact(nego.value)} UZS
          {shown ? <span className="co-metric-period"> · {shown}</span> : null}
        </>,
        t("переговорная сделка: цена согласована вне стакана и в оборот сессии не входит",
          "kelishilgan bitim: narx stakandan tashqari kelishilgan",
          "a negotiated deal: the price was agreed off-book and is not part of the session's turnover"));
  }
  const sessionRows = rows.splice(0, rows.length);
  // The date is not decoration: the board carries a close forward through
  // sessions with no executions, so a rail with no date invites reading an old
  // session as today's.
  const sessionDate = row?.last_trade_date || row?.close_date || sec?.last_trade_date || null;
  pushBlock("session", t("Торги", "Savdolar", "Session"), sessionRows,
    sessionDate ? `${t("сессия", "sessiya", "session")} ${sessionDate}` : null);

  // --- The selected period ---------------------------------------------------
  // This block follows the chart's period buttons. Press «1М» and it answers for
  // the month: the closes it ranged over, what changed hands, the average paid.
  // It used to be pinned to twelve months and titled «Диапазон 52 недели», which
  // was correct but deaf — a reader looking at a week was shown the year.
  //
  // Every figure is the SERVER's (/api/company/{t}/metrics?months=N, ТЗ §3: one
  // calc layer, and the screen is not one of its implementations). The client
  // picks the window and renders what comes back; it computes nothing.
  //
  // ONE average, not two. The strip removed on 2026-08-08 showed VWAP and the
  // mean of closes side by side — two different averages of the same window, six
  // percent apart, with nothing on screen to separate them. This is the VWAP,
  // because it is the price actually paid, and the label says how it is made.
  const pWin = (metricsWindow || metrics12)?.window;
  const periodBar = rangeBar(pWin?.min_close?.value, pWin?.max_close?.value, lastPrice);
  if (periodBar) {
    put(t("Оборот", "Aylanma", "Turnover"),
        compact(pWin?.turnover?.value) ? `${compact(pWin.turnover.value)} UZS` : null);
    put(t("Бумаг", "Qog'ozlar", "Shares traded"), count(pWin?.volume?.value));
    put(t("Средняя цена", "O'rtacha narx", "Average price"), num(pWin?.vwap?.value),
        t("оборот ÷ объём за период", "davr aylanmasi ÷ hajmi", "turnover ÷ volume over the period"));
    const periodRows = rows.splice(0, rows.length);
    const rangeLabel = (chartRange(range).label || [])[lang === "uz" ? 1 : lang === "en" ? 2 : 0];
    // The 52-week band still gets said, because it is the one comparison a
    // shorter window cannot make — but as a footnote now, not as the headline.
    // Compared by VALUE, not by identity: the window and the twelve-month pin are
    // two separate fetches, so at «1Г» they are different objects holding the
    // same band, and an identity test printed the year twice.
    const sameAsYear = pWin?.min_close?.value === yearLow && pWin?.max_close?.value === yearHigh;
    const yearNote = Number.isFinite(yearLow) && Number.isFinite(yearHigh) && !sameAsYear
      ? `${t("52 недели", "52 hafta", "52 weeks")}: ${num(yearLow)} – ${num(yearHigh)}` : "";
    blocks.push(
      <div className="co-sidebar-block" data-block="range" key="range">
        <h3 className="co-heading">
          {t("За период", "Davr uchun", "Over the period")}
          {rangeLabel ? <span className="co-metric-period"> · {rangeLabel}</span> : null}
        </h3>
        {periodBar}
        {periodRows.length > 0 && <div className="company-metrics-list">{periodRows}</div>}
        <div className="keystat-note muted">
          {t("по ценам закрытия", "yopilish narxlari bo'yicha", "on closing prices")}
          {pWin?.points ? ` · ${pWin.points} ${sessionsWord(pWin.points, lang)}` : ""}
          {pWin?.first_date && pWin?.last_date ? ` · ${pWin.first_date} — ${pWin.last_date}` : ""}
          {yearNote ? <><br />{yearNote}</> : null}
        </div>
      </div>,
    );
  }

  // --- Valuation -----------------------------------------------------------
  // Капитализация is THIS class — the same figure the market board's column
  // shows, and the only one that divides by the share count on the next line.
  // The issuer total is a different quantity and gets its own row when the
  // issuer has more than one class; printing the issuer figure above a class
  // share count invites a division that means nothing (UZTLP: 9 945,8B over
  // 29,6M shares).
  const capClass = safeNumber(row?.marketCap);
  const capIssuer = mult?.market_cap_issuer?.value;
  put(t("Капитализация", "Kapitalizatsiya", "Market cap"),
      capClass != null && capClass > 0 ? `${compact(capClass)} UZS` : null);
  put(t("Акций в обращении", "Muomaladagi aksiyalar", "Shares outstanding"), count(row?.sharesOutstanding));
  // «Номинальная стоимость» — the par the exchange's own card states (`parval`),
  // beside what the market pays for it. A par is only informative next to a
  // price, so the two travel together: UZTL at 60× its par and a bond at 1.00×
  // are the same statement in the same units.
  const par = Number.isFinite(row?.nominal) && row.nominal > 0 ? row.nominal : null;
  if (par) {
    const paid = Number.isFinite(lastPrice) && lastPrice > 0 ? lastPrice / par : null;
    put(t("Номинал", "Nominal", "Par value"),
        <>{num(par)}
          {paid ? <span className="co-metric-period"> · {formatRatio(paid, 2, lang)}×</span> : null}
        </>,
        paid ? `${t("цена к номиналу", "narx nominalga", "price to par")}: ${formatRatio(paid, 2, lang)}×` : undefined);
  }
  if ((mult?.issuer_classes?.length || 0) > 1 && Number.isFinite(capIssuer)
      && (!Number.isFinite(capClass) || Math.abs(capIssuer - capClass) > 1)) {
    put(t("Капитализация эмитента", "Emitent kapitalizatsiyasi", "Issuer market cap"),
        `${compact(capIssuer)} UZS`,
        `${t("все классы", "barcha sinflar", "all classes")}: ${mult.issuer_classes.join(", ")}`);
  }
  const valuationRows = rows.splice(0, rows.length);
  putMultiple("P/E", mult?.pe, 2, "×", mult?.pe?.base_period || mult?.base_period || undefined);
  putMultiple("P/B", mult?.pb, 2, "×", mult?.pb?.base_period || mult?.balance_period || undefined);
  putMultiple("P/S", mult?.ps, 2, "×", mult?.ps?.base_period || mult?.base_period || undefined);
  putMultiple("BVPS", mult?.bvps, 2, "", mult?.bvps?.base_period || mult?.balance_period || undefined);
  pushBlock("valuation", t("Оценка", "Baholash", "Valuation"), [...valuationRows, ...rows.splice(0, rows.length)]);

  // --- Profitability -------------------------------------------------------
  // Долг/Капитал ушёл из витрины по ТЗ мультипликаторов (лист 06); его место
  // занимает Капитал/Активы — та же информация о долговой нагрузке, но в
  // шкале 0…100 %, где разы и проценты перепутать невозможно.
  putMultiple("ROE", mult?.roe, 2, "", mult?.roe?.base_period || undefined);
  putMultiple("ROA", mult?.roa, 2, "", mult?.roa?.base_period || undefined);
  putMultiple(t("Чистая маржа", "Sof marja", "Net margin"), mult?.net_margin, 2, "", mult?.net_margin?.base_period || undefined);
  putMultiple(t("Капитал/Активы", "Kapital/Aktivlar", "Equity/Assets"), mult?.equity_assets, 2, "", mult?.equity_assets?.base_period || mult?.balance_period || undefined);
  pushBlock("profitability", t("Рентабельность", "Rentabellik", "Profitability"), rows.splice(0, rows.length));

  // --- Dividends -----------------------------------------------------------
  // Bonds pay coupons, not dividends; the tab is hidden for them and so is this.
  if (securityType !== "bond" && Array.isArray(dividends) && dividends.length) {
    const d = dividendSummary(dividends, { isPreferred: isPreferredRow(sec), lastPrice });
    put(t("Последний дивиденд", "Oxirgi dividend", "Last dividend"),
        d.latestAmt != null ? `${num(safeNumber(d.latestAmt))} ${t("сум/акц.", "so'm/aksiya", "UZS/share")}` : null);
    if (d.yieldPct != null) {
      put(t("Дивидендная доходность", "Dividend daromadliligi", "Dividend yield"),
          `${formatRatio(d.yieldPct, 2, lang)}%`,
          d.latestYear && !d.latestIsRecent
            ? t(`по выплате ${d.latestYear} г. к текущей цене`,
                `${d.latestYear}-yil to'lovi bo'yicha`,
                `on the ${d.latestYear} payout, at the current price`)
            : t("к текущей цене", "joriy narxga", "to current price"));
    }
    put(t("Выплат в истории", "Tarixdagi to'lovlar", "Payouts on record"), count(d.payouts));
    // A yield built on an old payout has to say so ON the block, not only in a
    // tooltip: KSCM's last declaration was 2020 and against today's price it
    // reads 64 %, which nobody would take as historical unless told.
    const divNote = d.latestYear && !d.latestIsRecent
      ? t(`доходность по выплате ${d.latestYear} г. к текущей цене`,
          `daromadlilik ${d.latestYear}-yil to'lovi bo'yicha`,
          `yield on the ${d.latestYear} payout, at the current price`)
      : d.latest?.decision_date ? `${t("решение", "qaror", "declared")} ${d.latest.decision_date}` : null;
    pushBlock("dividends", t("Дивиденды", "Dividendlar", "Dividends"), rows.splice(0, rows.length), divNote);
  }

  // Which of these sit beside the chart and which drop to the row underneath.
  // The split is not cosmetic: the four that stay are what a reader checks
  // AGAINST the chart — the session, the year's range, the multiples and the
  // returns on capital. Дивиденды and Детали are reference, read once, and they
  // were the 436px that made this rail 1521px tall against a 1029px column.
  const wanted = placement === "lower"
    ? new Set(["dividends"])
    : new Set(["session", "range", "valuation", "profitability"]);
  const shown = blocks.filter((b) => wanted.has(b.props["data-block"]));
  if (!shown.length) return null;
  return <div className="company-keystats">{shown}</div>;
}

// Preferred detection, matching the shapes the securities map and the board use.
function isPreferredRow(sec) {
  return sec?.stock_type === "preferred" || sec?.share_type === "preferred" || sec?.is_preferred === true;
}

/**
 * The dividend headline: latest declared payout, its yield, and how many are on
 * record. ONE rule, because the tab and the key-stats rail both state it and a
 * page that answers "последний дивиденд" twice with two numbers is worse than a
 * page that does not answer it at all.
 *
 * `latest` is the newest filing that declared something for THIS share class —
 * openinfo's calendar also carries decisions that declared nothing (Aloqabank
 * files four dated 11.06.2013 alone), and those are not the latest dividend.
 * `payouts` counts filings that declared for EITHER class, which is what the
 * issuer's payout history means.
 */
function dividendSummary(items, { isPreferred, lastPrice } = {}) {
  const rows = Array.isArray(items) ? items : [];
  const amtKey = isPreferred ? "preferred_amount" : "ordinary_amount";
  const latest = rows.find((r) => (r[amtKey] || 0) > 0) || rows[0] || null;
  const latestAmt = latest ? latest[amtKey] : null;
  const yieldPct = (latestAmt && lastPrice) ? (latestAmt / lastPrice) * 100 : null;
  const declared = rows.filter((r) => (r.ordinary_amount || 0) > 0 || (r.preferred_amount || 0) > 0);
  const latestYear = latestAmt && latest?.decision_date ? String(latest.decision_date).slice(0, 4) : null;
  return {
    rows, latest, latestAmt, yieldPct, declared,
    payouts: declared.length,
    latestYear,
    // The last payout is not always a recent one: SQBN's ordinary line was last
    // paid in 2019 while its preferred line still pays every year, so a bare
    // "к текущей цене" would read as this year's yield.
    latestIsRecent: !!latestYear && (new Date().getFullYear() - Number(latestYear)) <= 1,
  };
}

export { CompanyKeyStats, dividendSummary };
