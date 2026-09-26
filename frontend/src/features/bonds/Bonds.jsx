import { compact as fmtCompact, metric as fmtMetric, num as fmtNumber, pct as fmtPct, price as fmtPrice } from "../../lib/format.js";
import { normalizeLanguage } from "../../shared/i18n.jsx";
import React, { Suspense } from "react";
import { TermInfo } from "../../shared/TermInfo.jsx";

import { marketTone } from "../../lib/marketData.js";
import { VerifiedReport } from "../../shared/VerifiedReport.jsx";

// ---------------------------------------------------------------------------
// Company detail page components
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// /admin/audit — the auditor's own screen (ТЗ v1.3 §12.6)
//
// The market tab shows the auditor without its vocabulary: a withheld metric is
// a dash with a reason. This page is the other audience — it shows the run, the
// rule, the security, the expected and actual values, and the INPUT that
// produced the finding, so the calculation can be reproduced locally instead of
// argued about. The admin secret is held in the field, never persisted: this is
// a machine-to-machine credential and the browser is not a machine.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// The bond section: screener → issue card → yield map (ТЗ Дополнение 1 §А +
// прототип UZ Bonds). Reads /api/bonds (rows with the three-stage reference
// gate), /api/bonds/{ticker} (row + filed coupons) and /api/bonds/curve (the
// ГЦБ primary market). Everything a metric cannot honestly compute stays a
// dash that names its reason — the section never invents a term.
// ---------------------------------------------------------------------------

const BOND_COVERAGE_FIELDS = [
  ["isin", (b) => b.isin],
  ["price", (b) => b.price],
  ["nominal", (b) => b.reference?.nominal],
  ["coupon_rate", (b) => b.reference?.coupon_rate],
  ["coupon_freq", (b) => b.reference?.coupon_freq],
  ["maturity_date", (b) => b.reference?.maturity_date],
  ["issue_volume", (b) => b.reference?.issue_volume],
];

function bondCoverage(b) {
  const filled = BOND_COVERAGE_FIELDS.filter(([, get]) => get(b) != null && get(b) !== "").length;
  return filled / BOND_COVERAGE_FIELDS.length;
}

function bondYearsLeft(b, asOf) {
  const mat = b.reference?.maturity_date;
  if (!mat) return null;
  const days = (new Date(mat) - (asOf ? new Date(asOf) : new Date())) / 864e5;
  return days > 0 ? days / 365 : 0;
}

/** Days since this issue last printed — null when it never has.
 * Sorted as a very large number so «нет сделок» lands at the illiquid end
 * rather than at the top of an ascending sort. */
function bondStaleDays(b, asOf) {
  if (!b.last_trade_date) return null;
  const days = Math.round(((asOf ? new Date(asOf) : new Date()) - new Date(b.last_trade_date)) / 864e5);
  return days >= 0 ? days : 0;
}

/** Clamped linear interpolation on the auctioned tenors — mirrors the server's
 * rule: no market evidence beyond the last tenor, so no extrapolation. */
function govCurveAt(years, points) {
  const usable = (points || [])
    .filter((p) => Number.isFinite(Number(p.term_days)) && Number.isFinite(Number(p.rate)))
    .map((p) => [Number(p.term_days), Number(p.rate)])
    .sort((a, b) => a[0] - b[0]);
  if (years == null || !usable.length) return null;
  const days = years * 365;
  if (days <= usable[0][0]) return usable[0][1];
  if (days >= usable[usable.length - 1][0]) return usable[usable.length - 1][1];
  for (let i = 0; i < usable.length - 1; i += 1) {
    const [t0, r0] = usable[i]; const [t1, r1] = usable[i + 1];
    if (days >= t0 && days <= t1) return t1 > t0 ? r0 + ((r1 - r0) * (days - t0)) / (t1 - t0) : r0;
  }
  return null;
}

const fmtBondDay = (iso) => (iso && iso.length >= 10 ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : "—");

/** Spreads read best in basis points: +194 б.п., not +1,94%. */
function fmtBp(pp, lang) {
  if (pp == null || !Number.isFinite(Number(pp))) return "—";
  const bp = Number(pp) * 100;
  const body = fmtNumber(Math.abs(bp), lang, 0);
  return `${bp >= 0 ? "+" : "−"}${body} ${lang === "en" ? "bp" : "б.п."}`;
}

function bondSortCompare(a, b, dir) {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (typeof a === "string" || typeof b === "string") {
    return dir * String(a).localeCompare(String(b), "ru");
  }
  return dir * (a - b);
}

/** The coverage cell: how much of the issue's reference the sources publish. */
function BondCoverageCell({ share, lang }) {
  const pctVal = fmtNumber(share * 100, lang, 0);
  const tone = share >= 0.7 ? "pos" : share >= 0.4 ? "warn" : "neg";
  return (
    <span className="bondsec-cov" title={lang === "en"
      ? `${pctVal}% of the reference fields are published by a source`
      : lang === "uz" ? `Ma'lumot maydonlarining ${pctVal}% manbada e'lon qilingan`
      : `${pctVal}% справочных полей раскрыто источниками`}>
      <span className="bondsec-cov-track"><i className={`bondsec-cov-fill tone-${tone}`} style={{ width: `${Math.max(share * 100, 4)}%` }} /></span>
      <span className="bondsec-cov-num">{pctVal}%</span>
    </span>
  );
}

function BondsView({ language, onOpenBond, embedded = false }) {
  const lang = normalizeLanguage(language);
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState(false);
  const [mode, setMode] = React.useState("screener");
  const [q, setQ] = React.useState("");
  const [term, setTerm] = React.useState("");
  const [freqFilter, setFreqFilter] = React.useState("");
  const [coverFilter, setCoverFilter] = React.useState("");
  // Ordered by the RUNNING yield, not by YTM. A yield to maturity needs a
  // redemption date, and only the issuer's material fact #31 publishes one —
  // filed for 1 of the 18 issues on the board (measured 2026-08-17), so sorting
  // by it left seventeen rows in whatever order they arrived and called it
  // «по доходности». The running yield (annual coupon over price) needs no
  // maturity and is computed for every issue that has filed a coupon.
  const [sort, setSort] = React.useState({ key: "running", dir: -1 });

  React.useEffect(() => {
    let alive = true;
    fetch("/api/bonds")
      .then((r) => r.json())
      .then((d) => { if (alive) { if (d && d.ok) setData(d); else setError(true); } })
      .catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, []);

  // Inside the market page's «Облигации» segment the panel chrome is the market
  // page's own; standalone (the /bond/{T} card's neighbours) it brings its own.
  const Wrap = embedded ? "div" : "section";
  const wrapClass = embedded ? "bondsec bondsec-embedded" : "panel bondsec";
  if (error) return <Wrap className={wrapClass}><p className="muted">{t("Раздел облигаций недоступен", "Obligatsiyalar bo'limi mavjud emas", "Bonds section unavailable")}</p></Wrap>;
  if (!data) return <Wrap className={wrapClass}><p className="muted">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</p></Wrap>;

  const money = (v) => fmtCompact(v, lang);
  const val = (m) => (m && m.value != null ? m.value : null);
  const govPoints = data.gov_curve || [];
  const keyRate = data.key_rate || null;

  const missingLabel = {
    nominal: t("номинал", "nominal", "the par value"),
    coupon_rate: t("купонная ставка", "kupon stavkasi", "the coupon rate"),
    maturity_date: t("дата погашения", "to'lov sanasi", "the maturity date"),
  };
  const metricCell = (m, formatter) => {
    if (m?.value != null) return <span title={m.calculation_status || m.status}>
      {["indicative", "stale_indicative"].includes(m.status) && "≈ "}{formatter ? formatter(m.value) : fmtMetric(m, lang)}
      {m.status === "stale_indicative" && <small className="bondsec-issuer">{t("устар.", "eskirgan", "stale")}</small>}
    </span>;
    if (m?.status === "matured") return <span className="cell-status" title={m.note || ""}>{t("погашен", "so‘ndirilgan", "redeemed")}</span>;
    const miss = (m?.missing || []).map((f) => missingLabel[f] || f).join(", ");
    const title = [m?.note, miss && `${t("эмитент не подал", "emitent topshirmagan", "the issuer has not filed")}: ${miss}`]
      .filter(Boolean).join(" · ");
    return <span className="cell-status" title={m?.blocked_reason || title || m?.status || ""}>—</span>;
  };

  const rows = (data.items || []).map((b) => ({
    b,
    ticker: b.ticker,
    issuer: b.issuer || b.name || "",
    price: b.price,
    pricePct: val(b.price_pct),
    change: b.change_pct,
    session: b.last_trade_date,
    turnover: b.turnover,
    trades: b.trades,
    years: bondYearsLeft(b, data.board_day),
    coupon: b.reference?.coupon_rate ?? null,
    // What the coupon returns at par, compounded at the issue's own frequency:
    // the only yield an issue that has never traded has, and forty-odd of the
    // sixty-five have never traded. A 27% coupon paid monthly is 30,6%.
    effPar: val(b.effective_at_par),
    freq: b.reference?.coupon_freq ?? null,
    // One coupon in money, and what the whole issue is worth at par. Both are
    // register figures and neither needs a trade, so they are the two columns
    // an issue that has never printed can still fill.
    couponSum: b.schedule?.amount ?? null,
    issueValue: b.issue_value
      ?? (((b.reference?.nominal ?? 0) * (b.reference?.placed_volume ?? b.reference?.issue_volume ?? 0)) || null),
    next: b.schedule?.next_date || null,
    // Days since this issue last printed. A price four months old is not a
    // wrong number, but it is not this morning's either.
    liq: b.days_since_trade ?? bondStaleDays(b),
    running: val(b.simple_yield),
    ytm: val(b.ytm),
    gspread: val(b.g_spread),
    dur: val(b.duration),
    accrued: val(b.accrued),
    cov: bondCoverage(b),
  }));

  const needle = q.trim().toLowerCase();
  let filtered = rows;
  if (needle) {
    filtered = filtered.filter((r) =>
      `${r.ticker} ${r.issuer} ${r.b.isin || ""} ${r.b.name || ""}`.toLowerCase().includes(needle));
  }
  if (term !== "") {
    filtered = filtered.filter((r) => {
      if (r.years == null) return false;
      if (term === "1") return r.years < 1;
      if (term === "3") return r.years >= 1 && r.years <= 3;
      return r.years > 3;
    });
  }
  if (freqFilter !== "") filtered = filtered.filter((r) => String(r.freq) === freqFilter);
  if (coverFilter === "ytm") filtered = filtered.filter((r) => r.ytm != null);
  if (coverFilter === "full") filtered = filtered.filter((r) => r.cov >= 0.7);
  // A redeemed issue is history, not an offer. It stays reachable — the filter
  // shows it — but it does not sit in the list of what one can buy today.
  if (coverFilter === "matured") filtered = filtered.filter((r) => r.b.state === "matured");
  else filtered = filtered.filter((r) => r.b.state !== "matured");

  const sorted = filtered.slice().sort((a, b) => bondSortCompare(a[sort.key], b[sort.key], sort.dir));
  const onSort = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: key === "ticker" || key === "issuer" || key === "session" ? 1 : -1 }));

  const columns = [
    { key: "issuer", label: t("Выпуск", "Chiqarilish", "Issue"), left: true },
    { key: "price", label: t("Цена", "Narx", "Price"), termId: "par" },
    { key: "pricePct", label: `% ${t("ном.", "nom.", "par")}`, termId: "parPercent" },
    { key: "change", label: t("Изм.", "O'zg.", "Chg"), termId: "change" },
    { key: "session", label: t("Сессия", "Sessiya", "Session") },
    { key: "turnover", label: t("Оборот", "Aylanma", "Turnover"), termId: "volume" },
    { key: "years", label: t("Лет до погаш.", "Yil qoldi", "Yrs to mat.") },
    { key: "coupon", label: t("Купон", "Kupon", "Coupon"), termId: "coupon" },
    { key: "couponSum", label: t("Купон, сум", "Kupon, so'm", "Coupon, UZS") },
    { key: "issueValue", label: t("Объём выпуска", "Chiqarilish hajmi", "Issue size") },
    { key: "effPar", label: t("Эфф. при 100%", "100%da samarali", "Eff. at par"), termId: "effectiveAtPar" },
    { key: "freq", label: t("Частота", "Chastota", "Freq") },
    { key: "running", label: t("Тек. дох.", "Joriy dar.", "Running"), termId: "runningYield" },
    { key: "ytm", label: t("Доходность", "Daromadlilik", "YTM"), termId: "ytm" },
    { key: "gspread", label: t("G-спред", "G-spred", "G-spread"), termId: "gSpread" },
    { key: "dur", label: t("Дюрация", "Dyuratsiya", "Duration"), termId: "duration" },
    { key: "accrued", label: t("НКД", "TKD", "Accrued"), termId: "accrued" },
    { key: "next", label: t("След. купон", "Keyingi kupon", "Next coupon") },
    { key: "liq", label: t("Ликвидность", "Likvidlik", "Liquidity") },
    { key: "cov", label: t("Данные", "Ma'lumot", "Data") },
  ];

  return (
    <Wrap className={wrapClass}>
      <div className="bonds-head muted">
        <span>{t("Последняя сессия", "Oxirgi sessiya", "Latest session")}: {data.board_day || "—"}</span>
        <span>{data.traded_today ?? "—"} {t("в сессии", "sessiyada", "in session")}</span>
        <span>{t("Всего выпусков", "Jami chiqarilishlar", "All issues")}: {data.count ?? rows.length}</span>
        <span>{t("С расчётом доходности", "Daromadlilik hisoblangan", "With calculable yield")}: {data.with_calculable_yield ?? rows.filter((r) => r.ytm != null).length}</span>
      </div>
      <div className="bondsec-header">
        <div className="segmented-control bondsec-mode" role="tablist">
          <button type="button" className={mode === "screener" ? "active" : ""} onClick={() => setMode("screener")}>
            {t("Скринер", "Skriner", "Screener")}
          </button>
          <button type="button" className={mode === "map" ? "active" : ""} onClick={() => setMode("map")}>
            {t("Карта доходности", "Daromadlilik xaritasi", "Yield map")}
          </button>
          <button type="button" className={mode === "calendar" ? "active" : ""} onClick={() => setMode("calendar")}>
            {t("Календарь выплат", "To'lovlar taqvimi", "Payment calendar")}
          </button>
          <button type="button" className={mode === "coverage" ? "active" : ""} onClick={() => setMode("coverage")}>
            {t("Покрытие данных", "Ma'lumot qamrovi", "Data coverage")}
          </button>
        </div>
      </div>

      {mode === "screener" ? (
        <>
          <div className="bondsec-toolbar">
            <input
              type="search"
              className="bondsec-search"
              placeholder={t("Поиск: тикер, эмитент, ISIN", "Qidiruv: ticker, emitent, ISIN", "Search: ticker, issuer, ISIN")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <select value={term} onChange={(e) => setTerm(e.target.value)} aria-label={t("Срок до погашения", "Muddat", "Term")}>
              <option value="">{t("Срок: любой", "Muddat: istalgan", "Term: any")}</option>
              <option value="1">{t("до 1 года", "1 yilgacha", "under 1y")}</option>
              <option value="3">{t("1–3 года", "1–3 yil", "1–3y")}</option>
              <option value="99">{t("более 3 лет", "3 yildan ortiq", "over 3y")}</option>
            </select>
            <select value={freqFilter} onChange={(e) => setFreqFilter(e.target.value)} aria-label={t("Периодичность купона", "Kupon chastotasi", "Coupon frequency")}>
              <option value="">{t("Купон: любой", "Kupon: istalgan", "Coupon: any")}</option>
              <option value="12">{t("ежемесячно", "har oyda", "monthly")}</option>
              <option value="4">{t("ежеквартально", "har chorakda", "quarterly")}</option>
              <option value="2">{t("раз в полгода", "yarim yillik", "semi-annual")}</option>
              <option value="1">{t("раз в год", "yillik", "annual")}</option>
            </select>
            <select value={coverFilter} onChange={(e) => setCoverFilter(e.target.value)} aria-label={t("Полнота данных", "Ma'lumot to'liqligi", "Data completeness")}>
              <option value="">{t("Все выпуски", "Barcha chiqarilishlar", "All issues")}</option>
              <option value="ytm">{t("Только с доходностью", "Faqat daromadlilik bilan", "With yield only")}</option>
              <option value="full">{t("Покрытие ≥ 70%", "Qamrov ≥ 70%", "Coverage ≥ 70%")}</option>
              <option value="matured">{t("Погашенные", "So'ndirilgan", "Redeemed")}</option>
            </select>
            {(q || term || freqFilter || coverFilter) && (
              <button type="button" className="ghost-btn" onClick={() => { setQ(""); setTerm(""); setFreqFilter(""); setCoverFilter(""); }}>
                {t("Сбросить", "Tiklash", "Reset")}
              </button>
            )}
            <span className="muted bondsec-shown">
              {t("Показано", "Ko'rsatildi", "Shown")} {sorted.length} / {rows.length}
            </span>
          </div>

          <div className="market-table-scroll">
            <table className="market-table bonds-table bondsec-table">
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th
                      key={c.key}
                      className={c.left ? "" : "num"}
                      onClick={() => onSort(c.key)}
                      data-sorted={sort.key === c.key ? "1" : undefined}
                      title={t("Клик — сортировка", "Bosish — saralash", "Click to sort")}
                    >
                      {c.label}
                      {c.termId ? <TermInfo termId={c.termId} lang={lang} /> : null}
                      {sort.key === c.key ? (sort.dir < 0 ? " ↓" : " ↑") : ""}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => (
                  <tr key={r.ticker} className="bond-row" onClick={() => onOpenBond && onOpenBond(r.ticker)}>
                    <td>
                      {/* The full legal name leads; the ticker is the small
                          print. Four series can share one issuer, so the
                          ticker+ISIN line is what tells them apart. */}
                      <strong className="bondsec-name" title={r.issuer || r.ticker}>{r.issuer || r.ticker}</strong>
                      <span className="bondsec-issuer">
                        {r.ticker}{r.b.isin ? ` · ${r.b.isin}` : ""}
                      </span>
                    </td>
                    <td className="num">{fmtPrice(r.price, lang)}</td>
                    <td className="num">{metricCell(r.b.price_pct, (v) => `${fmtNumber(v, lang, 2)}%`)}</td>
                    <td className={`num tone-${marketTone(r.change)}`}>{fmtPct(r.change, lang)}</td>
                    <td className={`num bond-session${r.b.is_current === false ? " bond-stale" : ""}`}
                        title={r.b.is_current === false
                          ? t("Последняя сессия этого выпуска — не сегодняшняя.", "Oxirgi sessiya bugungi emas.", "This issue's last session is not today's.")
                          : ""}>
                      {fmtBondDay(r.session)}
                    </td>
                    <td className="num">
                      {money(r.turnover)}
                      {r.b.block_value > 0 && (
                        <span
                          className="bondsec-block-mark"
                          title={`${t("Пакетная сделка вне сессии", "Sessiyadan tashqari paket bitim", "Off-session block trade")}${r.b.block_date ? ` (${fmtBondDay(r.b.block_date)})` : ""}: ${money(r.b.block_value)}. ${t("В оборот сессии не входит: цена согласована вне стакана.", "Sessiya aylanmasiga kirmaydi.", "Not part of the session's turnover: the price was agreed off-book.")}`}
                        >†</span>
                      )}
                    </td>
                    <td className="num">{r.years == null
                      ? <span className="cell-status" title={t("дата погашения не подана эмитентом", "to'lov sanasi topshirilmagan", "no maturity filed")}>—</span>
                      : fmtNumber(r.years, lang, 1)}</td>
                    <td className="num">
                      {r.coupon != null
                        ? `${fmtNumber(r.coupon, lang, 2)}%`
                        : r.b.reference?.coupon_type === "floating"
                          ? <span className="cell-status" title={t("ставка не фиксированная", "stavka qat'iy emas", "the rate is not fixed")}>{t("плав.", "suzuv.", "float")}</span>
                          : <span className="cell-status" title={t("эмитент не подавал начислений", "hisoblash topshirilmagan", "no accrual filed")}>—</span>}
                    </td>
                    <td className="num">{r.couponSum == null
                      ? <span className="cell-status" title={t("нужны номинал, ставка и цикл купона", "nominal, stavka va sikl kerak", "needs par, rate and cycle")}>—</span>
                      : fmtNumber(r.couponSum, lang, 0)}</td>
                    <td className="num">{r.issueValue == null
                      ? <span className="cell-status" title={t("количество размещённых бумаг не раскрыто", "joylashtirilgan soni e'lon qilinmagan", "the placed count is not disclosed")}>—</span>
                      : money(r.issueValue)}</td>
                    <td className="num">{metricCell(r.b.effective_at_par, (v) => `${fmtNumber(v, lang, 2)}%`)}</td>
                    <td className="num">{r.freq != null ? fmtNumber(r.freq, lang, 0)
                      : <span className="cell-status" title={t("цикл купона не раскрыт", "kupon sikli e'lon qilinmagan", "the coupon cycle is not disclosed")}>—</span>}</td>
                    <td className="num">{metricCell(r.b.simple_yield, (v) => `${fmtNumber(v, lang, 2)}%`)}</td>
                    <td className="num bondsec-strong">{metricCell(r.b.ytm, (v) => `${fmtNumber(v, lang, 2)}%`)}</td>
                    <td className="num">{metricCell(r.b.g_spread, (v) => fmtBp(v, lang))}</td>
                    <td className="num">{metricCell(r.b.duration, (v) => fmtNumber(v, lang, 2))}</td>
                    <td className="num">{metricCell(r.b.accrued, (v) => fmtNumber(v, lang, 0))}</td>
                    <td className="num" title={["reconstructed", "inferred"].includes(r.b.schedule?.source)
                      ? t("Дата рассчитана из цикла купона и дат размещения и погашения — эмитент подаёт каждую выплату отдельно и заранее их не публикует.",
                          "Sana kupon sikli va sanalardan hisoblangan.",
                          "Reconstructed from the coupon cycle and the placement and redemption dates — the issuer files each payment separately and does not publish them in advance.")
                      : ""}>
                      {r.next ? <>{fmtBondDay(r.next)}{["reconstructed", "inferred"].includes(r.b.schedule?.source) && <span className="bondsec-recon">*</span>}</>
                        : <span className="cell-status" title={t("график выплат не восстановим", "to'lov jadvali tiklanmaydi", "no schedule can be built")}>—</span>}
                    </td>
                    <td className="num">
                      {r.liq == null
                        ? <span className="cell-status" title={t("выпуск ни разу не печатался на бирже", "hech qachon savdo bo'lmagan", "the issue has never printed a trade")}>{t("нет сделок", "bitim yo'q", "no trades")}</span>
                        : <span className={`bondsec-liq tone-${r.liq <= 7 ? "pos" : r.liq <= 30 ? "warn" : "neg"}`}>
                            {r.liq} {t("дн.", "kun", "d")}
                          </span>}
                    </td>
                    <td className="num"><BondCoverageCell share={r.cov} lang={lang} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted bondsec-note">
            {t("Клик по строке открывает карточку выпуска. Прочерк означает, что поле не раскрыто ни одним публичным источником — наведите курсор, чтобы увидеть причину.",
               "Qator ustiga bosish chiqarilish kartochkasini ochadi. Chiziq — maydon hech bir ochiq manbada e'lon qilinmagan.",
               "Clicking a row opens the issue card. A dash means no public source discloses the field — hover to see the reason.")}
          </p>
        </>
      ) : mode === "calendar" ? (
        <BondPaymentCalendar lang={lang} onOpenBond={onOpenBond} />
      ) : mode === "coverage" ? (
        <BondCoveragePanel items={data.items || []} lang={lang} />
      ) : (
        <BondYieldMap rows={rows} govPoints={govPoints} keyRate={keyRate} lang={lang} onOpenBond={onOpenBond} />
      )}
    </Wrap>
  );
}

/** How much of each issue's reference the sources actually publish, and which
 * source each field comes from.
 *
 * The screen is a statement about the SOURCES, not about the issues: a field
 * nobody publishes is not a gap in the collection, and one that is published
 * but unread is. Both are named, so «прочерк» never has to be guessed at. */
function BondCoveragePanel({ items, lang }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const total = items.length;
  const FIELDS = [
    { key: "isin", get: (b) => b.isin,
      title: t("ISIN", "ISIN", "ISIN"),
      src: t("Реестр РФБ, колонка «QQ kodi»", "RFB reestri, «QQ kodi»", "RFB register, «QQ kodi» column") },
    { key: "nominal", get: (b) => b.reference?.nominal,
      title: t("Номинал", "Nominal", "Par value"),
      src: t("Карточка бумаги на бирже, поле parval", "Birja kartochkasi, parval", "The exchange's security card, parval") },
    { key: "coupon_rate", get: (b) => b.reference?.coupon_rate,
      title: t("Ставка купона", "Kupon stavkasi", "Coupon rate"),
      src: t("Реестр РФБ «Foiz stavkasi»; где эмитент подал начисления — существенный факт № 32",
             "RFB reestri «Foiz stavkasi»; 32-son muhim fakt",
             "RFB register «Foiz stavkasi»; where filed, material fact #32") },
    { key: "coupon_freq", get: (b) => b.reference?.coupon_freq,
      title: t("Периодичность купона", "Kupon davriyligi", "Coupon frequency"),
      src: t("Реестр РФБ, «Kupon to'lovi davri (sikli)» — календарный месяц и «каждые 30 дней» различаются",
             "RFB reestri, «Kupon to'lovi davri (sikli)»",
             "RFB register, «Kupon to'lovi davri (sikli)» — a calendar month and «every 30 days» are kept apart") },
    { key: "issue_date", get: (b) => b.reference?.issue_date,
      title: t("Дата размещения", "Joylashtirish sanasi", "Placement date"),
      src: t("Реестр РФБ", "RFB reestri", "RFB register") },
    { key: "maturity_date", get: (b) => b.reference?.maturity_date,
      title: t("Дата погашения", "So'ndirish sanasi", "Redemption date"),
      src: t("Реестр РФБ; исполненный выкуп — существенный факт № 31",
             "RFB reestri; 31-son muhim fakt", "RFB register; an executed redemption is material fact #31") },
    { key: "issue_volume", get: (b) => b.reference?.issue_volume,
      title: t("Количество бумаг", "Qog'ozlar soni", "Securities issued"),
      src: t("Реестр РФБ, «QQ soni»", "RFB reestri, «QQ soni»", "RFB register, «QQ soni»") },
    { key: "placed_volume", get: (b) => b.reference?.placed_volume,
      title: t("Размещено бумаг", "Joylashtirilgan", "Securities placed"),
      src: t("Реестр РФБ, «Joylashtirilgan QQ soni»", "RFB reestri", "RFB register, «Joylashtirilgan QQ soni»") },
    { key: "schedule", get: (b) => b.schedule?.total,
      title: t("График выплат", "To'lov jadvali", "Payment schedule"),
      src: t("Восстанавливается из цикла и двух дат; поданные факты № 32 задают число месяца",
             "Sikl va ikkala sanadan tiklanadi",
             "Reconstructed from the cycle and the two dates; filed facts #32 set the day of the month") },
    { key: "price", get: (b) => b.price,
      title: t("Цена сделки", "Bitim narxi", "Traded price"),
      src: t("Торговая лента биржи — только у выпусков, которые печатались",
             "Birja savdo lentasi", "The exchange's trade feed — only for issues that have printed") },
    { key: "ytm", get: (b) => (b.ytm || {}).value,
      title: t("Доходность к погашению", "So'ndirishgacha daromadlilik", "Yield to maturity"),
      src: t("Расчётное: нужны цена, купон и дата погашения одновременно",
             "Hisoblanadi: narx, kupon va sana kerak",
             "Computed: needs a price, a coupon and a redemption date at once") },
    { key: "listing", get: () => null,
      title: t("Уровень листинга", "Listing darajasi", "Listing tier"),
      src: t("Есть в разделе листинга биржи, в реестр выпусков не выносится — не собирается",
             "Birjaning listing bo'limida bor, reestrga chiqarilmaydi",
             "Exists in the exchange's listing section, not in the issue register — not collected") },
    { key: "rating", get: () => null,
      title: t("Рейтинг выпуска", "Chiqarilish reytingi", "Issue rating"),
      src: t("Локальных рейтингов выпусков в стране не присваивают — закрыть сбором данных нельзя",
             "Mahalliy chiqarilish reytinglari berilmaydi",
             "No local issue ratings are assigned in the country — no collection can close this") },
  ];
  const rows = FIELDS.map((f) => {
    const n = items.filter((b) => {
      const v = f.get(b);
      return v !== null && v !== undefined && v !== "";
    }).length;
    return { ...f, n, share: total ? n / total : 0 };
  }).sort((a, b) => b.n - a.n);

  const W = 1060; const H = Math.max(260, rows.length * 34 + 60);
  const L = 250; const R = 130; const T = 10; const B = 34;
  const pw = W - L - R; const ph = H - T - B;
  const band = ph / Math.max(rows.length, 1);
  const bh = Math.min(20, band * 0.6);

  return (
    <div className="bondsec-coverage">
      <svg className="bondsec-chart" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={t("Покрытие полей", "Maydonlar qamrovi", "Field coverage")}>
        {Array.from({ length: 6 }, (_, i) => {
          const v = (total * i) / 5; const x = L + (pw * i) / 5;
          return (
            <g key={i}>
              <line x1={x} x2={x} y1={T} y2={T + ph} className="bondsec-grid" />
              <text x={x} y={T + ph + 18} textAnchor="middle" className="bondsec-tick">{Math.round(v)}</text>
            </g>
          );
        })}
        <line x1={L} x2={L} y1={T} y2={T + ph} className="bondsec-axis" />
        {rows.map((f, i) => {
          const cy = T + band * (i + 0.5);
          const w = total ? (pw * f.n) / total : 0;
          const tone = f.share >= 0.7 ? "pos" : f.share >= 0.4 ? "warn" : "neg";
          return (
            <g key={f.key}>
              <rect x={L} y={cy - bh / 2} width={Math.max(w, 1)} height={bh} rx="3"
                    className={`bondsec-covbar tone-${tone}`} />
              <text x={L - 12} y={cy + 4} textAnchor="end" className="bondsec-label">{f.title}</text>
              <text x={L + Math.max(w, 1) + 8} y={cy + 4} className="bondsec-label bondsec-label-strong">
                {f.n} {t("из", "dan", "of")} {total} · {fmtNumber(f.share * 100, lang, 0)}%
              </text>
            </g>
          );
        })}
      </svg>

      <h3 className="bondsec-h3">{t("Матрица источников", "Manbalar matritsasi", "The source matrix")}</h3>
      <div className="market-table-scroll">
        <table className="market-table bondsec-spread-table">
          <thead>
            <tr>
              <th>{t("Поле", "Maydon", "Field")}</th>
              <th>{t("Откуда берётся", "Manba", "Where it comes from")}</th>
              <th className="num">{t("Заполнено", "To'ldirilgan", "Filled")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.key}>
                <td><strong>{f.title}</strong></td>
                <td className="muted">{f.src}</td>
                <td className="num">{f.n} / {total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted bondsec-note">
        {t("Экран говорит про ИСТОЧНИКИ, а не про выпуски. Поле, которого нет ни у одного источника, — не пробел в сборе: рейтингов выпусков в Узбекистане не присваивают, и никакой сбор этого не закроет. Поле, которое публикуется, но не читается, — как раз пробел, и его видно здесь же.",
           "Ekran manbalar haqida, chiqarilishlar haqida emas.",
           "The screen is a statement about the SOURCES, not about the issues. A field no source publishes is not a gap in collection — no local issue ratings are assigned in Uzbekistan, and no collector can close that. A field that IS published but goes unread is a gap, and it shows up here too.")}
      </p>
    </div>
  );
}

const MONTH_SHORT = {
  ru: ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"],
  uz: ["yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avg", "sen", "okt", "noy", "dek"],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};

const MONTH_FULL = {
  ru: ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"],
  uz: ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"],
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
};

/** What the bond market owes, and when. Reads /api/bonds/calendar.
 *
 * The screen exists because the exchange's register does: before it, the only
 * future payment anyone could name was the one an issuer had already announced,
 * so a calendar would have held one coupon of one issue. The dates between
 * placement and redemption are reconstructed from the coupon cycle, and the
 * screen says so rather than letting a plan read as a diary. */
function BondPaymentCalendar({ lang, onOpenBond }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    fetch("/api/bonds/calendar")
      .then((r) => r.json())
      .then((d) => { if (alive) { if (d && d.ok) setData(d); else setError(true); } })
      .catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, []);

  if (error) return <p className="muted">{t("Календарь недоступен", "Taqvim mavjud emas", "Calendar unavailable")}</p>;
  if (!data) return <p className="muted">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</p>;

  const months = data.months || [];
  const flows = data.flows || [];
  if (!flows.length) {
    return (
      <div className="bondsec-empty">
        <b>{t("Будущих выплат не видно", "Kelgusi to'lovlar ko'rinmaydi", "No future payments visible")}</b>
        {t("Ни у одного выпуска нет одновременно ставки купона, цикла и обеих дат — без них график выплат не восстановить.",
           "Hech bir chiqarilishda kupon stavkasi, sikli va ikkala sana birga yo'q.",
           "No issue has a coupon rate, a cycle and both dates at once — without them no schedule can be built.")}
      </div>
    );
  }

  const short = MONTH_SHORT[lang] || MONTH_SHORT.ru;
  const full = MONTH_FULL[lang] || MONTH_FULL.ru;
  const today = data.today ? new Date(data.today) : new Date();
  const horizon = new Date(today.getTime() + 30 * 864e5).toISOString().slice(0, 10);
  const soon = flows.filter((f) => f.date <= horizon);

  // ---- the monthly bar chart -----------------------------------------------
  const W = 1060; const H = 300; const L = 74; const R = 18; const T = 22; const B = 46;
  const pw = W - L - R; const ph = H - T - B;
  const peak = Math.max(...months.map((m) => (m.coupon || 0) + (m.principal || 0)), 1);
  const step = Math.pow(10, Math.floor(Math.log10(peak)));
  const top = Math.ceil((peak * 1.1) / step) * step;
  const ticks = 4;
  const band = pw / Math.max(months.length, 1);
  const bw = Math.min(26, band * 0.55);

  // ---- the day grid of the next month --------------------------------------
  const gridMonth = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() + 1, 1));
  const gridYear = gridMonth.getUTCFullYear(); const gridIdx = gridMonth.getUTCMonth();
  const daysInMonth = new Date(Date.UTC(gridYear, gridIdx + 1, 0)).getUTCDate();
  const leading = (gridMonth.getUTCDay() + 6) % 7; // Monday-first
  const byDay = {};
  flows.forEach((f) => {
    if (Number(f.date.slice(0, 4)) !== gridYear || Number(f.date.slice(5, 7)) - 1 !== gridIdx) return;
    const day = Number(f.date.slice(8, 10));
    byDay[day] = byDay[day] || { total: 0, count: 0, items: [] };
    byDay[day].total += (f.coupon || 0) + (f.principal || 0);
    byDay[day].count += 1;
    byDay[day].items.push(f);
  });
  const dayPeak = Math.max(...Object.values(byDay).map((d) => d.total), 1);

  // ---- the 30-day feed, grouped by day -------------------------------------
  const feedDays = [];
  soon.forEach((f) => {
    const last = feedDays[feedDays.length - 1];
    if (last && last.date === f.date) last.items.push(f);
    else feedDays.push({ date: f.date, items: [f] });
  });

  const money = (v) => fmtCompact(v, lang);
  const tile = (label, value, note) => (
    <div className="bondsec-tile" key={label}>
      <div className="bondsec-tile-k">{label}</div>
      <div className="bondsec-tile-v">{value}</div>
      <div className="bondsec-tile-d muted">{note}</div>
    </div>
  );

  return (
    <div className="bondsec-calendar">
      <div className="bondsec-tiles">
        {tile(t("Ближайшая выплата", "Eng yaqin to'lov", "Next payment"),
              fmtBondDay(data.next?.date),
              `${data.next?.ticker || ""} · ${money((data.next?.coupon || 0) + (data.next?.principal || 0))}`)}
        {tile(t("Выплат за 30 дней", "30 kunda to'lovlar", "Payments in 30 days"),
              data.payments_30d,
              `${money(data.coupon_30d)} ${t("купонами", "kupon bilan", "in coupons")}`)}
        {tile(t("Погашения за 30 дней", "30 kunda so'ndirish", "Redemptions in 30 days"),
              money(data.principal_30d),
              t("возврат номинала", "nominal qaytarish", "principal returned"))}
        {tile(t("Купонный поток за год", "Yillik kupon oqimi", "Coupon flow in a year"),
              money(data.coupon_365d),
              `${data.payments_365d} ${t("выплат", "to'lov", "payments")} · ${data.issues} ${t("выпусков", "chiqarilish", "issues")}`)}
      </div>

      <h3 className="bondsec-h3">{t("Денежный поток рынка по месяцам", "Bozorning oylik pul oqimi", "The market's monthly cash flow")}</h3>
      <div className="bondsec-legend muted">
        <span><i className="bondsec-sq bondsec-sq-coupon" />{t("Купоны", "Kuponlar", "Coupons")}</span>
        <span><i className="bondsec-sq bondsec-sq-principal" />{t("Погашение номинала", "Nominalni so'ndirish", "Principal")}</span>
      </div>
      <svg className="bondsec-chart" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={t("Выплаты по месяцам", "Oylar bo'yicha to'lovlar", "Payments by month")}>
        {Array.from({ length: ticks + 1 }, (_, i) => {
          const v = (top * i) / ticks; const y = T + ph - (ph * i) / ticks;
          return (
            <g key={i}>
              <line x1={L} x2={W - R} y1={y} y2={y} className="bondsec-grid" />
              <text x={L - 8} y={y + 4} textAnchor="end" className="bondsec-tick">{fmtCompact(v, lang)}</text>
            </g>
          );
        })}
        <line x1={L} x2={W - R} y1={T + ph} y2={T + ph} className="bondsec-axis" />
        {months.map((m, i) => {
          const cx = L + band * (i + 0.5);
          const hC = (ph * (m.coupon || 0)) / top;
          const hP = (ph * (m.principal || 0)) / top;
          return (
            <g key={`${m.year}-${m.month}`}>
              {hP > 0 && <rect x={cx - bw / 2} y={T + ph - hC - hP} width={bw} height={Math.max(hP - 1, 0)} className="bondsec-bar-principal" rx="2" />}
              <rect x={cx - bw / 2} y={T + ph - hC} width={bw} height={hC} className="bondsec-bar-coupon" rx={hP > 0 ? 0 : 2} />
              <text x={cx} y={T + ph + 17} textAnchor="middle" className="bondsec-tick">
                {short[m.month - 1]}{(m.month === 1 || i === 0) ? ` ${String(m.year).slice(2)}` : ""}
              </text>
              <rect x={cx - band / 2} y={T} width={band} height={ph} fill="transparent">
                <title>
                  {`${full[m.month - 1]} ${m.year}\n`}
                  {`${t("Купоны", "Kuponlar", "Coupons")}: ${money(m.coupon)}\n`}
                  {`${t("Погашения", "So'ndirish", "Redemptions")}: ${money(m.principal)}\n`}
                  {`${t("Выпусков платит", "Chiqarilish to'laydi", "Issues paying")}: ${m.issues}`}
                </title>
              </rect>
            </g>
          );
        })}
      </svg>

      <div className="bondsec-calendar-cols">
        <div className="bondsec-calendar-feed">
          <h3 className="bondsec-h3">{t("Ближайшие 30 дней", "Yaqin 30 kun", "The next 30 days")}</h3>
          <p className="muted bondsec-sub">
            {soon.length} {t("выплат", "to'lov", "payments")} · {money(data.coupon_30d)} {t("купонами", "kupon bilan", "in coupons")}
          </p>
          <div className="bondsec-days">
            {feedDays.map((day) => {
              const total = day.items.reduce((s, f) => s + (f.coupon || 0) + (f.principal || 0), 0);
              const inDays = Math.round((new Date(day.date) - today) / 864e5);
              return (
                <div className="bondsec-day" key={day.date}>
                  <div className="bondsec-day-when">
                    <b>{fmtBondDay(day.date)}</b>
                    <span className="muted">{t("через", "keyin", "in")} {inDays} {t("дн.", "kun", "d")} · {money(total)}</span>
                  </div>
                  <div className="bondsec-day-items">
                    {day.items.map((f, i) => (
                      <button type="button" className="bondsec-pay" key={`${f.ticker}-${i}`}
                              onClick={() => onOpenBond && onOpenBond(f.ticker)}>
                        <span className="bondsec-pay-tk">{f.ticker}</span>
                        {f.principal ? <span className="bondsec-pill-red">{t("погашение", "so'ndirish", "redemption")}</span> : null}
                        <span className="bondsec-pay-amt">
                          {f.coupon ? money(f.coupon) : "—"}
                          {f.principal ? ` + ${money(f.principal)}` : ""}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
            {!feedDays.length && <p className="muted">{t("В ближайшие 30 дней выплат нет.", "Yaqin 30 kunda to'lov yo'q.", "No payments in the next 30 days.")}</p>}
          </div>
        </div>

        <div className="bondsec-calendar-grid">
          <h3 className="bondsec-h3">{full[gridIdx]} {gridYear}</h3>
          <p className="muted bondsec-sub">{t("Насыщенность клетки — размер выплат дня", "Katak to'yinganligi — kun to'lovlari hajmi", "Cell intensity is the size of the day's payments")}</p>
          <div className="bondsec-dow">
            {(lang === "en" ? ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] : ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]).map((d) => (
              <span key={d}>{d}</span>
            ))}
          </div>
          <div className="bondsec-cells">
            {Array.from({ length: leading }, (_, i) => <span key={`pad${i}`} />)}
            {Array.from({ length: daysInMonth }, (_, i) => {
              const day = i + 1; const cell = byDay[day];
              const share = cell ? cell.total / dayPeak : 0;
              const level = !cell ? 0 : share > 0.66 ? 4 : share > 0.33 ? 3 : share > 0.1 ? 2 : 1;
              const tip = !cell ? "" : [
                `${day} ${full[gridIdx]} · ${money(cell.total)} · ${cell.count} ${t("выпусков", "chiqarilish", "issues")}`,
                ...cell.items.map((f) => {
                  const parts = [];
                  if (f.coupon) parts.push(`${t("купон", "kupon", "coupon")} ${money(f.coupon)}`);
                  if (f.principal) parts.push(`${t("погашение", "so'ndirish", "redemption")} ${money(f.principal)}`);
                  return `${f.ticker}${f.issuer ? ` — ${f.issuer}` : ""}: ${parts.join(" + ")}`;
                }),
              ].join("\n");
              return (
                <span key={day} className={`bondsec-cell level-${level}`} title={tip}>
                  <i className="bondsec-cell-n">{day}</i>
                  {cell && (
                    <span className="bondsec-cell-tks">
                      {cell.items.slice(0, 2).map((f) => f.ticker).join(" ")}
                      {cell.items.length > 2 ? ` +${cell.items.length - 2}` : ""}
                    </span>
                  )}
                  {cell && <b className="bondsec-cell-v">{money(cell.total)}</b>}
                </span>
              );
            })}
          </div>
        </div>
      </div>

      <p className="muted bondsec-note">
        {t("Источник условий — реестр обращающихся выпусков РФБ «Тошкент». Реестр публикует ставку, цикл купона и даты размещения и погашения; сами даты платежей между ними раскладываются равномерно по циклу, поэтому это план, а не подтверждённые выплаты. Купон считается по размещённому количеству бумаг.",
           "Shartlar manbai — RFB «Toshkent» muomaladagi chiqarilishlar reestri. To'lov sanalari sikl bo'yicha teng taqsimlanadi.",
           "The terms come from the RFB Tashkent register of circulating issues. The register publishes the rate, the coupon cycle and the placement and redemption dates; the payment dates between them are laid evenly across the cycle, so this is a plan and not confirmed payments. A coupon is computed on the number of securities placed.")}
        {data.reconstructed ? ` ${t("Восстановлено", "Tiklandi", "Reconstructed")}: ${data.reconstructed} / ${flows.length}.` : ""}
      </p>
    </div>
  );
}

/** YTM against duration, bubble area = issue value, with the ГЦБ base curve.
 * Only bonds whose yield IS computed appear — the map never plots a guess. */
// Issuer groups on the yield map (bonds.issuer_segment). Colour carries the
// group, and the legend chips double as filters.
const BOND_SEGMENTS = [
  { key: "bank", color: "#3b82f6", label: ["Банки", "Banklar", "Banks"] },
  { key: "mortgage", color: "#f97316", label: ["Ипотека и SPV", "Ipoteka va SPV", "Mortgage & SPV"] },
  { key: "mfo", color: "#10b981", label: ["МФО и финкомпании", "MMT va moliya kompaniyalari", "Microfinance & finance cos"] },
  { key: "leasing", color: "#a855f7", label: ["Лизинг", "Lizing", "Leasing"] },
  { key: "corporate", color: "#eab308", label: ["Корпоративные", "Korporativ", "Corporates"] },
];

const bondSegment = (key) => BOND_SEGMENTS.find((sg) => sg.key === key) || BOND_SEGMENTS[4];

const BOND_BLOCK_TEXT = {
  NO_VERIFIED_TRADE: ["нет сделок", "bitim yo'q", "no trades"],
  COUPON_RATE_IMPLAUSIBLE: ["купон вне правдоподобных границ — проверяется", "kupon ishonchli chegaradan tashqarida", "coupon outside plausible bounds — under review"],
  YIELD_OUT_OF_RANGE: ["доходность вне правдоподобных границ — вероятна ошибка данных", "daromadlilik ishonchli chegaradan tashqarida", "yield outside plausible bounds — likely a data fault"],
  UNKNOWN_FUTURE_COUPONS: ["плавающий купон без будущих ставок", "suzuvchi kupon", "floating coupon, future rates unknown"],
  AMORTIZATION_OR_OPTIONS_NOT_VERIFIED: ["амортизация или оферта не подтверждены", "amortizatsiya yoki oferta tasdiqlanmagan", "amortisation or option not verified"],
};

const PRICE_METHOD_TEXT = {
  vwap: ["средневзвешенная по объёму", "hajm bo'yicha o'rtacha", "volume-weighted"],
  median_close: ["медиана закрытий", "yopilishlar medianasi", "median close"],
  last_trade: ["последняя сделка", "oxirgi bitim", "last trade"],
};

/** Median of a list of numbers (null for none). */
function medianOf(values) {
  const v = values.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

/** A round step for an axis spanning `span` in about `count` ticks. */
function niceAxisStep(span, count) {
  const raw = span / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const norm = (raw || 1) / mag;
  return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
}

/**
 * Карта доходности: every priced issue at its duration and yield, beside the
 * ГЦБ curve. The standard picture of a bond market — how much each issuer
 * pays over the sovereign for the same interest-rate exposure.
 *
 * Every number comes from the server on one basis (bonds.py / bond_quality):
 * effective annual YTM struck on the volume-weighted price of the last
 * sessions, Macaulay duration, the ГЦБ curve with each auction placed at its
 * own duration and effective yield, and the G-spread read at the bond's
 * duration. All of it «indicative»: a thin market and inferred terms make it
 * an estimate, and the page says so rather than hiding the map.
 *
 * `compact` draws the small version for a bond card, with `highlight` marked
 * and every other dot faded.
 */
function BondYieldMap({ rows, govPoints, keyRate, lang, onOpenBond, compact = false, highlight = null }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const li = lang === "uz" ? 1 : lang === "en" ? 2 : 0;
  const [hidden, setHidden] = React.useState(() => new Set());
  const [showStale, setShowStale] = React.useState(true);
  const [hover, setHover] = React.useState(null);
  const [sortKey, setSortKey] = React.useState("spread");
  const boxRef = React.useRef(null);

  const priced = rows
    .map((r) => ({
      ...r,
      x: r.dur,
      y: r.ytm,
      size: r.issueValue || r.b.issue_value || 0,
      seg: r.b.segment || "corporate",
      stale: (r.b.ytm?.status || "") === "stale_indicative",
      g: r.b.g_spread || {},
    }))
    .filter((p) => p.x != null && p.y != null);
  const pts = priced.filter((p) => !hidden.has(p.seg) && (showStale || !p.stale || p.ticker === highlight));

  // What is NOT on the map, and why — counted, and the data faults named.
  const live = rows.filter((r) => ["live", "last"].includes(r.b.state));
  const noTrade = live.filter((r) => r.ytm == null && (r.b.data_quality || []).some((q) => q.code === "NO_VERIFIED_TRADE")).length;
  const faults = live.filter((r) => r.ytm == null && (r.b.data_quality || [])
    .some((q) => ["COUPON_RATE_IMPLAUSIBLE", "YIELD_OUT_OF_RANGE"].includes(q.code)));

  if (!priced.length) {
    return (
      <div className="bondsec-empty">
        <b>{t("Карта пуста", "Xarita bo'sh", "The map is empty")}</b>
        {t("Ни у одного выпуска сейчас нет цены, по которой можно посчитать доходность.",
           "Hozircha hech bir chiqarilishda daromadlilik hisoblash uchun narx yo'q.",
           "No issue currently has a price a yield can be computed from.")}
      </div>
    );
  }

  // Curve on the server's basis: (duration, effective yield) per auction.
  const curvePts = (govPoints || [])
    .map((p) => ({ x: Number(p.duration_years ?? (p.term_days / 365)), y: Number(p.rate_effective ?? p.rate), p }))
    .filter((c) => Number.isFinite(c.x) && Number.isFinite(c.y))
    .sort((a, b) => a.x - b.x);

  const W = compact ? 560 : 1060;
  const H = compact ? 250 : 470;
  const L = compact ? 44 : 58; const R = compact ? 16 : 150; const T = 18; const B = compact ? 34 : 50;
  const pw = W - L - R; const ph = H - T - B;
  const xMaxData = Math.max(...priced.map((p) => p.x), ...curvePts.map((c) => c.x), 1);
  const xStep = niceAxisStep(xMaxData, compact ? 4 : 6);
  const maxX = Math.ceil((xMaxData * 1.06) / xStep) * xStep;
  const yVals = priced.map((p) => p.y).concat(curvePts.map((c) => c.y), keyRate?.rate != null ? [Number(keyRate.rate)] : []);
  const yStep = niceAxisStep(Math.max(...yVals) - Math.min(...yVals) || 5, compact ? 4 : 6);
  const minY = Math.floor((Math.min(...yVals) - yStep * 0.3) / yStep) * yStep;
  const maxY = Math.ceil((Math.max(...yVals) + yStep * 0.3) / yStep) * yStep;
  const X = (v) => L + (pw * Math.max(0, Math.min(v, maxX))) / maxX;
  const Y = (v) => T + ph - (ph * (v - minY)) / (maxY - minY || 1);
  const maxSize = Math.max(...priced.map((p) => p.size), 1);
  const radius = (p) => (compact ? 4 : 5) + (compact ? 5 : 11) * Math.sqrt((p.size || 0) / maxSize);

  const gridY = [];
  for (let v = minY; v <= maxY + 1e-9; v += yStep) gridY.push(Number(v.toFixed(6)));
  const gridX = [];
  for (let v = 0; v <= maxX + 1e-9; v += xStep) gridX.push(Number(v.toFixed(6)));
  const fmtAxis = (v, d) => Number(v).toLocaleString(lang === "en" ? "en-US" : "ru-RU", { maximumFractionDigits: d });

  // Solid where the curve has auctions on both sides, dashed where it is only
  // held flat past the first and last of them.
  const curveSolid = curvePts.length >= 2
    ? curvePts.map((c, i) => `${i ? "L" : "M"}${X(c.x).toFixed(1)},${Y(c.y).toFixed(1)}`).join(" ") : null;
  const curveFlat = curvePts.length
    ? [`M${X(0).toFixed(1)},${Y(curvePts[0].y).toFixed(1)} L${X(curvePts[0].x).toFixed(1)},${Y(curvePts[0].y).toFixed(1)}`,
       `M${X(curvePts.at(-1).x).toFixed(1)},${Y(curvePts.at(-1).y).toFixed(1)} L${X(maxX).toFixed(1)},${Y(curvePts.at(-1).y).toFixed(1)}`].join(" ")
    : null;

  // Labels: largest issues first, each tried right, left, above, below of its
  // dot and dropped (hover still names it) when all four collide.
  const placed = [];
  const labels = new Map();
  if (!compact) {
    pts.slice().sort((a, b) => b.size - a.size).forEach((p) => {
      const r = radius(p); const cx = X(p.x); const cy = Y(p.y);
      const w = p.ticker.length * 6.6 + 4; const h = 13;
      const tries = [[cx + r + 4, cy - h / 2, "start"], [cx - r - 4 - w, cy - h / 2, "end"],
                     [cx - w / 2, cy - r - 4 - h, "middle"], [cx - w / 2, cy + r + 4, "middle"]];
      for (const [x0, y0, anchor] of tries) {
        const box = { x0, y0, x1: x0 + w, y1: y0 + h };
        const clash = box.x0 < L || box.x1 > L + pw + R - 4 || box.y0 < T - 6 || box.y1 > T + ph
          || placed.some((q) => !(box.x1 < q.x0 || box.x0 > q.x1 || box.y1 < q.y0 || box.y0 > q.y1))
          || pts.some((o) => o !== p && Math.hypot(X(o.x) - Math.min(Math.max(X(o.x), box.x0), box.x1),
                                                   Y(o.y) - Math.min(Math.max(Y(o.y), box.y0), box.y1)) < radius(o) - 1);
        if (!clash) {
          placed.push(box);
          labels.set(p.ticker, { x: anchor === "start" ? x0 : anchor === "end" ? x0 + w : x0 + w / 2, y: y0 + h - 3, anchor });
          break;
        }
      }
    });
  }

  const onPointerMove = (e, p) => {
    const rect = boxRef.current?.getBoundingClientRect();
    if (!rect) return;
    setHover({ ticker: p.ticker, x: e.clientX - rect.left, y: e.clientY - rect.top, fromMap: true });
  };
  const hp = hover?.fromMap ? priced.find((p) => p.ticker === hover.ticker) : null;
  const priceBasis = (p) => {
    const pr = p.b.pricing || {};
    const how = (PRICE_METHOD_TEXT[pr.method] || [pr.method, pr.method, pr.method])[li];
    const span = pr.from && pr.to && pr.from !== pr.to ? `${fmtBondDay(pr.from)} — ${fmtBondDay(pr.to)}` : fmtBondDay(pr.to || pr.from);
    return `${how}${pr.sessions > 1 ? `, ${pr.sessions} ${t("сесс.", "sess.", "sess.")}` : ""} · ${span}`;
  };

  // The market's own read, group by group: median spread and how many issues.
  // Fresh prices only, unless a group has none — then its stale ones, marked.
  const segSummary = BOND_SEGMENTS.map((sg) => {
    const all = priced.filter((p) => p.seg === sg.key && p.g.bps != null);
    const fresh = all.filter((p) => !p.stale);
    return { ...sg, n: priced.filter((p) => p.seg === sg.key).length,
             median: medianOf((fresh.length ? fresh : all).map((p) => p.g.bps)), staleOnly: !fresh.length && all.length > 0 };
  }).filter((sg) => sg.n > 0);

  const sorters = {
    spread: (a, b) => (b.g.bps ?? -1e9) - (a.g.bps ?? -1e9),
    duration: (a, b) => a.x - b.x,
    ytm: (a, b) => b.y - a.y,
  };
  const tableRows = pts.slice().sort(sorters[sortKey]);
  const maxAbsBp = Math.max(1, ...tableRows.map((p) => Math.abs(p.g.bps || 0)));
  const hl = highlight ? priced.find((p) => p.ticker === highlight) : null;

  const chart = (
    <div className="bondmap-plot" ref={boxRef}>
      <svg className="bondsec-chart" viewBox={`0 0 ${W} ${H}`} role="img" data-testid="bond-yield-map"
           data-points={pts.length}
           aria-label={t("Карта доходности: доходность к погашению против дюрации, с кривой ГЦБ",
                         "Daromadlilik xaritasi: dyuratsiyaga nisbatan daromadlilik, DQQ egri chizig'i bilan",
                         "Yield map: yield to maturity against duration, with the government curve")}>
        {gridY.map((v) => (
          <g key={`y${v}`}>
            <line x1={L} x2={L + pw} y1={Y(v)} y2={Y(v)} className="bondsec-grid" />
            <text x={L - 8} y={Y(v) + 4} textAnchor="end" className="bondsec-tick">{fmtAxis(v, 1)}%</text>
          </g>
        ))}
        {gridX.map((v) => (
          <g key={`x${v}`}>
            <line x1={X(v)} x2={X(v)} y1={T} y2={T + ph} className="bondsec-grid" />
            <text x={X(v)} y={T + ph + 16} textAnchor="middle" className="bondsec-tick">{fmtAxis(v, 2)}</text>
          </g>
        ))}
        <line x1={L} x2={L + pw} y1={T + ph} y2={T + ph} className="bondsec-axis" />
        <line x1={L} x2={L} y1={T} y2={T + ph} className="bondsec-axis" />
        {!compact && (
          <text x={L + pw / 2} y={H - 10} textAnchor="middle" className="bondsec-tick">
            {t("Дюрация Маколея, лет", "Makoley dyuratsiyasi, yil", "Macaulay duration, years")}
          </text>
        )}
        {keyRate?.rate != null && (
          <g>
            <line x1={L} x2={L + pw} y1={Y(keyRate.rate)} y2={Y(keyRate.rate)} className="bondsec-keyrate" />
            {!compact && (
              <text x={L + pw + 6} y={Y(keyRate.rate) + 4} className="bondsec-tick">
                {t("ставка ЦБ", "MB stavkasi", "key rate")} {fmtNumber(keyRate.rate, lang, 2)}%
              </text>
            )}
          </g>
        )}
        {curveFlat && <path d={curveFlat} className="bondsec-curve bondsec-curve-flat" fill="none" />}
        {curveSolid && <path d={curveSolid} className="bondsec-curve" fill="none" />}
        {curvePts.map((c) => (
          <g key={`gov${c.p.term_days}`}>
            <rect x={X(c.x) - 4} y={Y(c.y) - 4} width="8" height="8" className="bondsec-govpt">
              <title>{`${t("ГЦБ", "DQQ", "Gov")} ${fmtNumber(c.p.term_days / 365, lang, 1)} ${t("г.", "y.", "y")} · ${fmtNumber(c.y, lang, 2)}% · ${t("аукцион", "auksion", "auction")} ${fmtBondDay(c.p.auction_date)}`}</title>
            </rect>
            {!compact && (
              <text x={X(c.x)} y={Y(c.y) + 18} textAnchor="middle" className="bondsec-govlabel">
                {t("ГЦБ", "DQQ", "Gov")} {fmtNumber(c.p.term_days / 365, lang, 0)}{t("г", "y", "y")}
              </text>
            )}
          </g>
        ))}
        {!compact && curvePts.length > 0 && (
          <text x={L + pw + 6} y={Y(curvePts.at(-1).y) + 4} className="bondsec-tick">{t("кривая ГЦБ", "DQQ egri chizig'i", "gov curve")}</text>
        )}
        {pts.slice().sort((a, b) => b.size - a.size).map((p) => {
          const r = radius(p);
          const sg = bondSegment(p.seg);
          const faded = (hl && p.ticker !== highlight) || (hover && hover.ticker !== p.ticker);
          const lab = labels.get(p.ticker);
          return (
            <g key={p.ticker} className={`bondsec-map-pt ${faded ? "is-faded" : ""} ${p.ticker === highlight ? "is-highlight" : ""}`}
               data-ticker={p.ticker} data-segment={p.seg}
               onPointerMove={(e) => onPointerMove(e, p)} onPointerLeave={() => setHover(null)}
               onClick={() => onOpenBond && onOpenBond(p.ticker)}>
              <circle cx={X(p.x)} cy={Y(p.y)} r={r}
                style={{ fill: p.stale ? "transparent" : sg.color, stroke: sg.color }}
                className={`bondsec-bubble ${p.stale ? "is-stale" : ""}`} />
              {lab && <text x={lab.x} y={lab.y} textAnchor={lab.anchor} className="bondsec-label">{p.ticker}</text>}
              {compact && p.ticker === highlight && (
                <text x={X(p.x) + r + 5} y={Y(p.y) + 4} className="bondsec-label bondsec-label-strong">{p.ticker}</text>
              )}
            </g>
          );
        })}
      </svg>
      {hp && (
        <div className="bondmap-tip" style={{ left: Math.max(4, Math.min(hover.x + 14, (boxRef.current?.clientWidth || 600) - 260)), top: Math.max(4, hover.y - 20) }}>
          <div className="bondmap-tip-head">
            <i style={{ background: bondSegment(hp.seg).color }} /> <b>{hp.ticker}</b>
            <span className="muted">{bondSegment(hp.seg).label[li]}</span>
          </div>
          <div className="muted bondmap-tip-issuer">{hp.issuer}</div>
          <dl>
            <div><dt>{t("Доходность к погашению", "So'ndirishgacha daromadlilik", "Yield to maturity")}</dt><dd>{fmtNumber(hp.y, lang, 2)}%</dd></div>
            <div><dt>{t("Дюрация", "Dyuratsiya", "Duration")}</dt><dd>{fmtNumber(hp.x, lang, 2)} {t("г.", "y.", "y")}</dd></div>
            {hp.g.curve_rate != null && <div><dt>{t("Кривая ГЦБ", "DQQ egri chizig'i", "Gov curve")}</dt><dd>{hp.g.extrapolated ? "≈" : ""}{fmtNumber(hp.g.curve_rate, lang, 2)}%</dd></div>}
            {hp.g.bps != null && <div><dt>{t("G-спред", "G-spred", "G-spread")}</dt><dd>{fmtBp(hp.g.value, lang)}</dd></div>}
            {hp.b.pricing?.value != null && hp.b.reference?.nominal ? (
              <div><dt>{t("Цена для расчёта", "Hisob narxi", "Price used")}</dt><dd>{fmtNumber(hp.b.pricing.value / hp.b.reference.nominal * 100, lang, 2)}%</dd></div>
            ) : null}
          </dl>
          <div className="muted bondmap-tip-foot">
            {priceBasis(hp)}
            {hp.stale ? ` · ${t("цена устарела", "narx eskirgan", "stale price")}` : ""}
            {hp.g.extrapolated ? ` · ${t("кривая за пределами аукционных сроков", "egri chiziq auksion muddatlaridan tashqarida", "curve beyond auctioned terms")}` : ""}
          </div>
        </div>
      )}
    </div>
  );

  if (compact) {
    return (
      <div className="bondmap bondmap-compact">
        {chart}
        <p className="muted bondsec-note">
          {t("Точки — другие выпуски в обращении, линия — кривая ГЦБ. Доходность индикативная.",
             "Nuqtalar — boshqa chiqarilishlar, chiziq — DQQ egri chizig'i. Daromadlilik indikativ.",
             "Dots are other live issues, the line is the government curve. Yields are indicative.")}
        </p>
      </div>
    );
  }

  const head = (key, label, cls = "num") => (
    <th className={`${cls} ${sortKey === key ? "is-sorted" : ""}`} aria-sort={sortKey === key ? "descending" : "none"}>
      <button type="button" className="bondmap-sort" onClick={() => setSortKey(key)}>{label}</button>
    </th>
  );

  return (
    <div className="bondsec-map bondmap">
      <div className="bondmap-controls">
        <div className="bondmap-legend" role="group" aria-label={t("Группы эмитентов", "Emitent guruhlari", "Issuer groups")}>
          {BOND_SEGMENTS.filter((sg) => priced.some((p) => p.seg === sg.key)).map((sg) => (
            <button key={sg.key} type="button" aria-pressed={!hidden.has(sg.key)}
              className={`bondmap-chip ${hidden.has(sg.key) ? "is-off" : ""}`}
              onClick={() => setHidden((cur) => { const n = new Set(cur); if (n.has(sg.key)) n.delete(sg.key); else n.add(sg.key); return n; })}>
              <i style={{ background: sg.color }} />{sg.label[li]}
              <span className="muted">{priced.filter((p) => p.seg === sg.key).length}</span>
            </button>
          ))}
        </div>
        <label className="bondmap-toggle">
          <input type="checkbox" checked={showStale} onChange={(e) => setShowStale(e.target.checked)} />
          <span>{t("Показывать устаревшие цены", "Eskirgan narxlarni ko'rsatish", "Show stale prices")}</span>
        </label>
      </div>
      <div className="bondsec-legend muted">
        <span><i className="bondsec-line" />{t("кривая ГЦБ", "DQQ egri chizig'i", "gov curve")}<TermInfo termId="govCurve" lang={lang} /></span>
        <span><i className="bondsec-line bondsec-line-flat" />{t("за пределами аукционных сроков — удерживается ровной", "auksion muddatlaridan tashqarida", "beyond auctioned terms — held flat")}</span>
        {keyRate?.rate != null && <span><i className="bondsec-line bondsec-line-dash" />{t("ставка ЦБ", "MB stavkasi", "key rate")}</span>}
        <span><i className="bondsec-ring" />{t("цена старше 30 дней", "narx 30 kundan eski", "price older than 30 days")}</span>
        <span>{t("размер точки — объём выпуска", "nuqta o'lchami — chiqarilish hajmi", "dot size = issue value")}</span>
      </div>

      {chart}

      <p className="bondmap-coverage" data-testid="bond-map-coverage">
        {t(`На карте ${pts.length} из ${live.length} выпусков в обращении.`,
           `Xaritada muomaladagi ${live.length} tadan ${pts.length} ta chiqarilish.`,
           `${pts.length} of ${live.length} live issues on the map.`)}{" "}
        {noTrade > 0 && t(`${noTrade} без сделок — без цены доходность не считается. `,
                          `${noTrade} tasida bitim yo'q. `, `${noTrade} have never traded — no price, no yield. `)}
        {faults.length > 0 && (
          <>
            {t("Исключены проверкой данных: ", "Ma'lumotlar tekshiruvi bilan chiqarilgan: ", "Excluded by data checks: ")}
            {faults.map((f, i) => {
              const code = (f.b.data_quality || []).find((q) => ["COUPON_RATE_IMPLAUSIBLE", "YIELD_OUT_OF_RANGE"].includes(q.code))?.code;
              return <React.Fragment key={f.ticker}>{i > 0 && "; "}<b>{f.ticker}</b> — {(BOND_BLOCK_TEXT[code] || [code, code, code])[li]}</React.Fragment>;
            })}.
          </>
        )}
      </p>

      {segSummary.length > 0 && (
        <div className="bondmap-segments" data-testid="bond-segment-summary">
          {segSummary.map((sg) => (
            <div key={sg.key} className="bondmap-seg">
              <span><i style={{ background: sg.color }} />{sg.label[li]}</span>
              <b>{sg.median != null ? fmtBp(sg.median / 100, lang) : "—"}</b>
              <small className="muted">{t("медианный спред", "median spred", "median spread")} · {sg.n}{sg.staleOnly ? ` · ${t("по устаревшим ценам", "eskirgan narxlar bo'yicha", "on stale prices")}` : ""}</small>
            </div>
          ))}
        </div>
      )}

      <h3 className="bondsec-h3">{t("Спреды к кривой ГЦБ", "DQQ egri chizig'iga spredlar", "Spreads to the government curve")}<TermInfo termId="gSpread" lang={lang} /></h3>
      <div className="market-table-scroll">
        <table className="market-table bondsec-spread-table" data-testid="bond-spread-table">
          <thead>
            <tr>
              <th>{t("Выпуск", "Chiqarilish", "Issue")}</th>
              <th>{t("Группа", "Guruh", "Group")}</th>
              {head("duration", t("Дюрация, лет", "Dyuratsiya, yil", "Duration, yrs"))}
              {head("ytm", t("Доходность", "Daromadlilik", "Yield"))}
              <th className="num">{t("Кривая ГЦБ", "DQQ egri chizig'i", "Gov curve")}</th>
              {head("spread", t("G-спред", "G-spred", "G-spread"))}
              <th>{t("Цена для расчёта", "Hisob narxi", "Price used")}</th>
            </tr>
          </thead>
          <tbody>
            {tableRows.map((p) => {
              const sg = bondSegment(p.seg);
              const bp = p.g.bps;
              return (
                <tr key={p.ticker} className={`bond-row ${hover?.ticker === p.ticker ? "is-hover" : ""}`}
                    onPointerEnter={() => setHover({ ticker: p.ticker, fromMap: false })}
                    onPointerLeave={() => setHover(null)}
                    onClick={() => onOpenBond && onOpenBond(p.ticker)}>
                  <td><strong>{p.ticker}</strong> <span className="muted bondmap-issuer">{p.issuer}</span></td>
                  <td><span className="bondmap-segtag"><i style={{ background: sg.color }} />{sg.label[li]}</span></td>
                  <td className="num">{fmtNumber(p.x, lang, 2)}</td>
                  <td className="num">{fmtNumber(p.y, lang, 2)}%{p.stale ? <small className="bondsec-issuer"> {t("устар.", "eskirgan", "stale")}</small> : null}</td>
                  <td className="num">{p.g.curve_rate != null ? `${p.g.extrapolated ? "≈" : ""}${fmtNumber(p.g.curve_rate, lang, 2)}%` : "—"}</td>
                  <td className="num bondmap-spread">
                    {bp != null && (
                      <span className={`bondmap-bar ${bp >= 0 ? "pos" : "neg"}`}
                        style={{ width: `${Math.max(2, (Math.abs(bp) / maxAbsBp) * 46)}%` }} aria-hidden="true" />
                    )}
                    <span>{bp != null ? fmtBp(p.g.value, lang) : "—"}</span>
                  </td>
                  <td className="muted bondmap-basis">{priceBasis(p)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted bondsec-note">
        {t("Как считается. Доходность к погашению — эффективная годовая, по всем оставшимся купонам и номиналу, от средневзвешенной по объёму цены последних сессий (до 10 сессий за 30 дней; если объёма нет — медиана закрытий). База начисления ACT/365 подтверждена суммами выплаченных купонов (N × C × d / 365), где их нет — принята по рыночной практике. Кривая ГЦБ — последние аукционы Минфина (фискальный агент — ЦБ) за 200 дней: доходность дисконтных бумаг приведена к эффективной годовой, каждая точка поставлена на свою дюрацию; между точками — линейно, за их пределами кривая удерживается ровной и помечена «≈». G-спред — доходность выпуска минус кривая на его дюрации. Все значения индикативные: рынок тонкий, часть условий восстановлена по раскрытиям.",
           "Qanday hisoblanadi. So'ndirishgacha daromadlilik — samarali yillik, so'nggi sessiyalarning hajm bo'yicha o'rtacha narxidan. ACT/365 bazasi to'langan kuponlar summalari bilan tasdiqlangan. DQQ egri chizig'i — so'nggi auksionlar, har bir nuqta o'z dyuratsiyasida. G-spred — chiqarilish daromadliligi minus uning dyuratsiyasidagi egri chiziq. Barcha qiymatlar indikativ.",
           "How it is computed. Yield to maturity is effective annual, over every remaining coupon and the principal, struck on the volume-weighted price of the latest sessions (up to 10 within 30 days; the median close where no volume is published). The ACT/365 basis is confirmed by the amounts of the coupons paid (N × C × d / 365), and taken as market practice where none is filed yet. The government curve is the latest Ministry of Finance auctions within 200 days: discount yields converted to effective annual, each point placed at its own duration, linear between points and held flat (marked «≈») beyond them. The G-spread is the issue's yield minus the curve at its duration. All values are indicative: the market is thin and some terms are reconstructed from disclosures.")}
      </p>
    </div>
  );
}

/** Four states, and each one changes which blocks are worth drawing.
 * A redeemed issue has no yield to show but does have a result; an issue still
 * in placement has terms and no history. */
function BondStateBadge({ state, lang }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const map = {
    placing: ["pos", t("размещается", "joylashtirilmoqda", "placing")],
    live: ["pos", t("в обращении", "muomalada", "circulating")],
    last: ["warn", t("последний купон", "oxirgi kupon", "last coupon")],
    matured: ["muted", t("погашена", "so'ndirilgan", "redeemed")],
  };
  const one = map[state];
  if (!one) return null;
  return <span className={`bondsec-state tone-${one[0]}`}>{one[1]}</span>;
}

/** The issue's life on one line: placement, every coupon period, today, and
 * redemption. Ticks behind today are periods that fell due, ahead of it are
 * periods still owed — which is the one picture that says at a glance whether
 * a bond is a year old or nearly over. */
function BondLifeLine({ bond, flows, lang }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const issue = bond.schedule?.issue_date || bond.reference?.issue_date;
  const maturity = bond.reference?.maturity_date;
  if (!issue || !maturity || !flows.length) return null;
  const t0 = new Date(issue).getTime();
  const t1 = new Date(maturity).getTime();
  const span = Math.max(t1 - t0, 1);
  const now = Date.now();
  const W = 1060; const H = 96; const L = 40; const R = 40; const Y = 58;
  const pw = W - L - R;
  const X = (ms) => L + pw * Math.min(Math.max((ms - t0) / span, 0), 1);
  const nowX = X(Math.min(now, t1));
  // Sixty-odd monthly ticks on a five-year issue collide into a smear; thinning
  // keeps the shape and the count is printed underneath either way.
  const stride = Math.max(1, Math.ceil(flows.length / 44));

  return (
    <>
      <h3 className="bondsec-h3">{t("Линия жизни выпуска", "Chiqarilish hayot chizig'i", "The issue's life line")}</h3>
      <svg className="bondsec-chart bondsec-lifeline" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={t("Линия жизни выпуска", "Hayot chizig'i", "Life line")}>
        <line x1={L} x2={L + pw} y1={Y} y2={Y} className="bondsec-axis" strokeWidth="2" strokeLinecap="round" />
        <line x1={L} x2={nowX} y1={Y} y2={Y} className="bondsec-life-done" strokeWidth="2" strokeLinecap="round" />
        {flows.map((f, i) => {
          const last = i === flows.length - 1;
          if (!last && i % stride !== 0) return null;
          const x = X(new Date(f.date).getTime());
          const h = last ? 22 : 11;
          return (
            <g key={f.date} className={f.paid ? "bondsec-life-tick done" : "bondsec-life-tick"}>
              <line x1={x} x2={x} y1={Y - h} y2={Y} strokeWidth={last ? 3 : 2} strokeLinecap="round" />
              <circle cx={x} cy={Y - h} r={last ? 4.5 : 2.8} />
              <title>{`${fmtBondDay(f.date)}${f.principal > 0 ? ` · ${t("погашение номинала", "nominal so'ndirish", "principal")}` : ""}`}</title>
            </g>
          );
        })}
        <text x={L} y={Y + 22} className="bondsec-tick">{t("размещение", "joylashtirish", "placed")} · {fmtBondDay(issue)}</text>
        <text x={L + pw} y={Y + 22} textAnchor="end" className="bondsec-tick">{t("погашение", "so'ndirish", "redemption")} · {fmtBondDay(maturity)}</text>
        {now <= t1 && (
          <>
            <line x1={nowX} x2={nowX} y1={Y - 40} y2={Y + 6} className="bondsec-life-now" />
            <text x={nowX} y={Y - 46} textAnchor="middle" className="bondsec-tick bondsec-tick-strong">{t("сегодня", "bugun", "today")}</text>
          </>
        )}
      </svg>
      <p className="muted bondsec-note" style={{ marginTop: 0 }}>
        {stride > 1 ? `${t("Засечки прорежены.", "Chiziqchalar siyraklashtirilgan.", "Ticks are thinned.")} ` : ""}
        {bond.schedule?.partial
          ? `${t("Дата размещения не раскрыта, поэтому периоды отсчитаны назад от погашения:", "Joylashtirish sanasi ochilmagan, davrlar so'ndirishdan orqaga sanalgan:", "No placement date is published, so the periods are counted back from redemption:")} ${flows.length} ${t("предстоящих", "kelgusi", "upcoming")}`
          : `${t("Всего", "Jami", "In all")} ${flows.length} ${t("купонных периодов", "kupon davri", "coupon periods")}`}
        {(!bond.schedule?.partial && bond.schedule?.paid != null) ? `, ${t("срок наступил у", "muddati kelgan", "fallen due")} ${bond.schedule.paid}` : ""}
        {"; "}{t("высокая засечка — возврат номинала.", "baland chiziqcha — nominal qaytishi.", "the tall tick is the return of principal.")}
      </p>
    </>
  );
}

/**
 * Where one issue stands in the market: its G-spread, its rank among issuers
 * of the same kind, that group's median, and the small yield map with the
 * issue marked. Built from the same board payload as the market's map, so
 * the card and the map can never disagree about a number.
 */
function BondMarketPosition({ bond, board, keyRate, lang }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const li = lang === "uz" ? 1 : lang === "en" ? 2 : 0;
  const val = (m) => (m && typeof m === "object" ? m.value : m);
  const items = board?.items || [];
  const me = items.find((b) => b.ticker === bond.ticker);
  if (!me || val(me.ytm) == null || val(me.duration) == null) return null;
  const rows = items.map((b) => ({
    b, ticker: b.ticker, issuer: b.issuer || b.name || "",
    ytm: val(b.ytm), dur: val(b.duration),
    issueValue: b.issue_value ?? (((b.reference?.nominal ?? 0) * (b.reference?.placed_volume ?? b.reference?.issue_volume ?? 0)) || null),
  }));
  const sg = bondSegment(me.segment);
  const peers = items.filter((b) => b.segment === me.segment && b.g_spread?.bps != null)
    .sort((a, b) => b.g_spread.bps - a.g_spread.bps);
  const rank = peers.findIndex((b) => b.ticker === me.ticker) + 1;
  const median = medianOf(peers.map((b) => b.g_spread.bps));
  return (
    <section className="panel pad bond-market-position" data-testid="bond-market-position">
      <div className="section-title" style={{ marginTop: 0 }}>
        <h2>{t("Место на рынке", "Bozordagi o'rni", "Place in the market")}</h2>
      </div>
      <p className="bond-spread-badge">
        {me.g_spread?.bps != null && (
          <>
            <span>{t("G-спред", "G-spred", "G-spread")}</span>
            <b>{fmtBp(me.g_spread.value, lang)}</b>
          </>
        )}
        {rank > 0 && peers.length > 1 && (
          <span className="muted">
            {t(`${rank}-й по спреду из ${peers.length} в группе «${sg.label[0]}»`,
               `«${sg.label[1]}» guruhidagi ${peers.length} tadan ${rank}-o'rin`,
               `${rank} of ${peers.length} by spread among ${sg.label[2]}`)}
            {median != null && ` · ${t("медиана группы", "guruh medianasi", "group median")} ${fmtBp(median / 100, lang)}`}
          </span>
        )}
        {me.g_spread?.extrapolated && (
          <span className="muted">{t("кривая ГЦБ за пределами аукционных сроков", "DQQ egri chizig'i auksion muddatlaridan tashqarida", "government curve beyond auctioned terms")}</span>
        )}
      </p>
      <BondYieldMap rows={rows} govPoints={board.gov_curve || []} keyRate={keyRate} lang={lang}
        compact highlight={me.ticker} />
      <p className="muted bondsec-note">
        {(me.pricing && (PRICE_METHOD_TEXT[me.pricing.method] || [])[li])
          ? `${t("Цена для расчёта", "Hisob narxi", "Price used")}: ${(PRICE_METHOD_TEXT[me.pricing.method] || [])[li]}${me.pricing.sessions > 1 ? `, ${t("сессий", "sessiya", "sessions")}: ${me.pricing.sessions}` : ""}. `
          : ""}
        {me.day_count_source === "filed_coupons"
          ? t("База ACT/365 подтверждена суммами выплаченных купонов.", "ACT/365 bazasi to'langan kuponlar bilan tasdiqlangan.", "The ACT/365 basis is confirmed by the coupons paid.")
          : me.day_count_source === "market_convention"
            ? t("База ACT/365 принята по рыночной практике — эмитент её не раскрыл.", "ACT/365 bazasi bozor amaliyoti bo'yicha qabul qilingan.", "ACT/365 is taken as market practice — the issuer has not disclosed it.")
            : ""}
      </p>
    </section>
  );
}

function BondCard({ ticker, language, onBack, onOpenChart }) {
  const lang = normalizeLanguage(language);
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const [bond, setBond] = React.useState(null);
  const [board, setBoard] = React.useState(null);
  const [curveData, setCurveData] = React.useState(null);
  const [error, setError] = React.useState(false);
  const [tab, setTab] = React.useState("overview");

  React.useEffect(() => {
    let alive = true;
    setBond(null); setError(false); setTab("overview");
    fetch(`/api/bonds/${encodeURIComponent(ticker)}`)
      .then((r) => r.json())
      .then((d) => { if (alive) { if (d && d.ok) setBond(d); else setError(true); } })
      .catch(() => { if (alive) setError(true); });
    fetch("/api/bonds").then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setBoard(d); }).catch(() => {});
    fetch("/api/bonds/curve").then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setCurveData(d); }).catch(() => {});
    return () => { alive = false; };
  }, [ticker]);

  if (error) return <section className="panel"><p className="muted">{t("Выпуск не найден", "Chiqarilish topilmadi", "Issue not found")}</p></section>;
  if (!bond) return <section className="panel"><p className="muted">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</p></section>;

  const val = (m) => (m && m.value != null ? m.value : null);
  const ref = bond.reference || {};
  const govPoints = bond.gov_curve || [];
  const keyRate = bond.key_rate || null;
  const years = bondYearsLeft(bond, bond.board_day);
  const coupons = bond.coupons || [];
  const today = new Date().toISOString().slice(0, 10);
  const futureCoupons = coupons.filter((c) => c.pay_date && c.pay_date.slice(0, 10) > today);
  const nextCoupon = futureCoupons[0] || null;

  const dash = (reason) => <span className="cell-status" title={reason || ""}>—</span>;
  const num2 = (v, d = 2) => fmtNumber(v, lang, d);
  const m = (mm, formatter) => (mm?.value != null
    ? (formatter ? formatter(mm.value) : num2(mm.value))
    : dash(mm?.note || (mm?.missing || []).join(", ") || mm?.status));
  const assessmentStatus = (status) => ({
    verified: t("проверено", "tekshirilgan", "verified"),
    limited: t("ограничено данными", "ma’lumotlar bilan cheklangan", "data-limited"),
    calculation_verified: t("расчёт проверен", "hisob tekshirilgan", "calculation verified"),
    insufficient_data: t("недостаточно данных", "ma’lumot yetarli emas", "insufficient data"),
    fresh: t("актуальная котировка", "dolzarb kotirovka", "current quote"),
    stale: t("устаревающая котировка", "eskirayotgan kotirovka", "aging quote"),
    very_stale: t("устаревшая котировка", "eskirgan kotirovka", "stale quote"),
    never_traded: t("нет подтверждённой сделки", "tasdiqlangan bitim yo‘q", "no verified trade"),
  }[status] || status || "—");
  const monitorCopy = (point, field) => {
    const market = point.metric_code === "market_liquidity";
    const copy = market ? {
      improvement_signal: t("новые проверенные сделки расширяют свежую историю цены и объёма", "yangi tekshirilgan bitimlar narx va hajmning yangi tarixini kengaytiradi", "new verified trades broaden the recent price and volume history"),
      risk_signal: t("котировка стареет или не подтверждается сделками и объёмом", "kotirovka eskiradi yoki bitimlar va hajm bilan tasdiqlanmaydi", "the quote ages or remains unsupported by trades and volume"),
      required_disclosure: t("датированные сделки за 30/90 дней, объём и доступные заявки", "30/90 kunlik sanalangan bitimlar, hajm va mavjud buyurtmalar", "dated 30/90-day trading activity, volume and available bid/ask data"),
    } : {
      improvement_signal: t("исполнение выплаты подтверждено официальным источником", "to‘lov ijrosi rasmiy manba bilan tasdiqlangan", "payment execution is confirmed by an official source"),
      risk_signal: t("срок выплаты прошёл без подтверждения исполнения", "to‘lov muddati ijro tasdig‘isiz o‘tdi", "the due date passes without verified execution"),
      required_disclosure: t("официальное подтверждение выплаты и договорный срок устранения нарушения", "to‘lovning rasmiy tasdig‘i va buzilishni bartaraf etish shartnoma muddati", "official payment confirmation and any contractual cure period"),
    };
    return copy[field] || point[field] || "—";
  };

  return (
    <section className="panel bondsec bondsec-card">
      <div className="bondsec-card-head">
        <div>
          <button type="button" className="ghost-btn" onClick={onBack}>← {t("К списку облигаций", "Obligatsiyalar ro'yxatiga", "Back to bonds")}</button>
          <h2 className="panel-title bondsec-card-title">
            {bond.issuer || bond.name || bond.ticker}
          </h2>
          <p className="muted bondsec-sub">
            {bond.ticker}
            {bond.isin ? ` · ${bond.isin}` : ""} · UZS
            {bond.state && <> · <BondStateBadge state={bond.state} lang={lang} /></>}
          </p>
        </div>
        <div className="bondsec-card-actions">
          <button type="button" className="ghost-btn" onClick={() => onOpenChart && onOpenChart(bond.ticker)}>
            {t("Открыть график цены", "Narx grafigini ochish", "Open price chart")}
          </button>
        </div>
      </div>

      {bond.issuer_report && <details className="verified-block">
        <summary>{t("Финансовый профиль эмитента", "Emitentning moliyaviy profili", "Issuer financial profile")} · {bond.financial_as_of || "—"}</summary>
        <div className="verified-note"><Suspense fallback={null}><VerifiedReport report={bond.issuer_report} lang={lang} narrative /></Suspense></div>
      </details>}
      {!bond.issuer_report && bond.issuer_link_status && <p className="verified-note">{t("Финансовый профиль эмитента пока не подтверждён.", "Emitent moliyaviy profili hali tasdiqlanmagan.", "Issuer fundamentals are not yet verified.")} ({bond.issuer_link_status})</p>}
      <div className="bondsec-summary">
        {bond.freshness && <p className="verified-note">
          {t("Последняя сделка", "So‘nggi bitim", "Last trade")}: {bond.quote_as_of || "—"}
          {bond.days_since_trade != null && <> · {bond.days_since_trade} {t("дней назад", "kun oldin", "days ago")}</>}
          {". "}{["stale", "very_stale"].includes(bond.freshness.status) && t("Цена устарела; текущего рыночного вердикта нет. ", "Narx eskirgan; joriy bozor xulosasi yo‘q. ", "The price is stale; no current market verdict is available. ")}
          {bond.freshness.status === "never_traded" && t("Нет подтверждённой сделки. ", "Tasdiqlangan bitim yo‘q. ", "No verified trade. ")}
          {bond.schedule?.source === "inferred" && t("График восстановлен; расчёты индикативные.", "Jadval tiklangan; hisoblar indikativ.", "The schedule is inferred; calculations are indicative.")}
          {bond.yield?.blocked_reason && <> {t("Причина недоступности", "Mavjud emasligi sababi", "Unavailable reason")}: {bond.yield.blocked_reason}.</>}
        </p>}
        {bond.price != null && ref.nominal != null ? (
          <>
            {t("Цена последней сделки", "So‘nggi bitim narxi", "Last traded price")}{" "}
            <b>{fmtPrice(bond.price, lang)} {t("сум", "so'm", "UZS")}</b>
            {val(bond.price_pct) != null && <> ({t("или", "yoki", "or")} <b>{num2(val(bond.price_pct))}%</b> {t("от номинала", "nominaldan", "of par")})</>}
            {". "}
            {ref.maturity_date
              ? <>{t("Погашение по номиналу", "Nominal bo'yicha so'ndirish", "Redeemed at par on")} {fmtBondDay(ref.maturity_date)}. </>
              : <>{t("Дату погашения эмитент ещё не подал — она появляется в раскрытии только с началом выкупа. ", "To'lov sanasi hali topshirilmagan. ", "The issuer has not yet filed a maturity date — it appears in disclosure only once redemption begins. ")}</>}
            {val(bond.accrued) != null && nextCoupon && (
              <>
                {t("НКД на дату расчёта", "Hisoblash sanasidagi TKD", "Accrued interest at the calculation date")}{" "}
                <b>{num2(val(bond.accrued), 0)} {t("сум", "so'm", "UZS")}</b>
                {nextCoupon.amount != null && <>, {t("а следующий купон", "keyingi kupon esa", "and the next coupon of")} {num2(nextCoupon.amount, 0)} {t("сум получите", "so'mni olasiz", "UZS arrives")} {fmtBondDay(nextCoupon.pay_date)}</>}
                {". "}
              </>
            )}
            {val(bond.ytm) != null && (
              <>
                {bond.ytm?.calculation_status !== "exact" && <strong>{t("Индикативно: ", "Indikativ: ", "Indicative: ")}</strong>}
                {t("Доходность к погашению —", "So'ndirishgacha daromadlilik —", "Yield to maturity is")}{" "}
                <b>{num2(val(bond.ytm))}%</b> {t("годовых", "yillik", "p.a.")}
                {val(bond.g_spread) != null && <>, {t("спред к кривой ГЦБ —", "DQQ egri chizig'iga spred —", "spread to the government curve —")} <b>{fmtBp(val(bond.g_spread), lang)}</b></>}
                {"."}
              </>
            )}
          </>
        ) : (
          <>
            <b>{t("Расчёт доходности недоступен.", "Daromadlilik hisoblab bo'lmaydi.", "Yield cannot be computed.")}</b>{" "}
            {t("Публично раскрыта только часть параметров выпуска", "Chiqarilish parametrlarining faqat bir qismi ochiq", "Only part of the issue's parameters is publicly disclosed")}
            {ref.coupon_rate != null && <> — {t("ставка купона", "kupon stavkasi", "the coupon rate of")} {num2(ref.coupon_rate)}%</>}
            {". "}
            {t("Отсутствуют:", "Yo'q:", "Missing:")}{" "}
            {(bond.ytm?.missing || ref.missing || []).map((f) => ({
              nominal: t("номинал", "nominal", "par"),
              coupon_rate: t("ставка купона", "kupon stavkasi", "coupon rate"),
              maturity_date: t("дата погашения", "to'lov sanasi", "maturity date"),
            }[f] || f)).join(", ") || t("цена сделки", "bitim narxi", "a traded price")}
            {". "}
            {t("Метрики появятся сами, как только источники раскроют недостающее.", "Manbalar yetishmayotganini e'lon qilishi bilan ko'rsatkichlar o'zi paydo bo'ladi.", "The metrics appear by themselves once the sources disclose what is missing.")}
          </>
        )}
      </div>

      {bond.assessments && <section className="verified-watch" aria-label={t("Три независимые оценки", "Uchta mustaqil baho", "Three independent assessments")}>
        <h3>{t("Три независимые оценки", "Uchta mustaqil baho", "Three independent assessments")}</h3>
        <div className="verified-watch-grid">
          <article><h4>{t("Финансы эмитента", "Emitent moliyasi", "Issuer financials")}</h4><p>{assessmentStatus(bond.assessments.issuer_financials?.status)} · {bond.assessments.issuer_financials?.financial_as_of || "—"}</p></article>
          <article><h4>{t("Условия и исполнение выпуска", "Chiqarilish shartlari va ijrosi", "Issue terms and execution")}</h4><p>{assessmentStatus(bond.assessments.issue_terms_and_execution?.status)}</p><p>{t("Выплат с наступившим сроком без подтверждения", "Tasdiqsiz muddati kelgan to‘lovlar", "Due payments without confirmation")}: {bond.assessments.issue_terms_and_execution?.unconfirmed_due_payments ?? "—"}</p></article>
          <article><h4>{t("Цена и возможность продажи", "Narx va sotish imkoniyati", "Price and saleability")}</h4><p>{assessmentStatus(bond.assessments.market_price_and_liquidity?.status)} · {bond.assessments.market_price_and_liquidity?.quote_as_of || "—"}</p></article>
        </div>
      </section>}

      <div className="bondsec-cols">
        <div className="bondsec-kv-card">
          <table className="bondsec-kv">
            <tbody>
              <tr><td>{t("Котировка", "Kotirovka", "Quote")}<TermInfo termId="parPercent" lang={lang} /></td><td>{m(bond.price_pct, (v) => `${num2(v)}%`)}</td></tr>
              <tr><td>{t("Цена", "Narx", "Price")}</td><td>{bond.price != null ? fmtPrice(bond.price, lang) : dash(bond.reason)}</td></tr>
              <tr><td>{t("Изменение за сессию", "Sessiya o'zgarishi", "Session change")}</td><td className={`tone-${marketTone(bond.change_pct)}`}>{fmtPct(bond.change_pct, lang)}</td></tr>
              <tr><td>{t("Сессия", "Sessiya", "Session")}</td><td>{fmtBondDay(bond.last_trade_date)}</td></tr>
              <tr><td>{t("Оборот за сессию", "Sessiya aylanmasi", "Session turnover")}</td><td>{fmtCompact(bond.turnover, lang)}</td></tr>
              <tr><td>{t("Сделки", "Bitimlar", "Trades")}</td><td>{Number.isFinite(bond.trades) ? bond.trades : "—"}</td></tr>
              <tr><td>{t("Лет до погашения", "So'ndirishgacha yil", "Years to maturity")}</td><td>{years != null ? num2(years) : dash(t("дата погашения не подана", "to'lov sanasi topshirilmagan", "no maturity filed"))}</td></tr>
              <tr>
                <td>{t("Дата погашения", "To'lov sanasi", "Maturity")}</td>
                <td>{ref.maturity_date
                  ? <span title={t("из факта выкупа, поданного эмитентом на openinfo.uz", "emitentning openinfo.uz'dagi so'ndirish faktidan", "from the issuer's redemption filing on openinfo.uz")}>{fmtBondDay(ref.maturity_date)}</span>
                  : dash(t("эмитент публикует дату только с началом выкупа", "sana faqat so'ndirish boshlanganda e'lon qilinadi", "filed only once redemption begins"))}</td>
              </tr>
              <tr><td>{t("Валюта", "Valyuta", "Currency")}</td><td>UZS</td></tr>
            </tbody>
          </table>
        </div>
        <div className="bondsec-kv-card">
          <table className="bondsec-kv">
            <tbody>
              <tr>
                <td>{t("Ставка купона", "Kupon stavkasi", "Coupon rate")}<TermInfo termId="coupon" lang={lang} /></td>
                <td>{ref.coupon_rate != null ? `${num2(ref.coupon_rate)}%`
                  : ref.coupon_type === "floating" ? t("плавающая", "suzuvchi", "floating")
                  : dash(t("эмитент не подавал начислений", "hisoblash topshirilmagan", "no accrual filed"))}</td>
              </tr>
              <tr><td>{t("Номинал", "Nominal", "Par")}<TermInfo termId="par" lang={lang} /></td><td>{ref.nominal != null ? num2(ref.nominal, 0) : dash()}</td></tr>
              <tr><td>{t("Частота купона, раз в год", "Kupon chastotasi", "Coupon frequency")}</td><td>{ref.coupon_freq != null ? num2(ref.coupon_freq, 0) : dash(t("не раскрыта", "e'lon qilinmagan", "not disclosed"))}</td></tr>
              <tr><td>{t("НКД", "TKD", "Accrued")}<TermInfo termId="accrued" lang={lang} /></td><td>{m(bond.accrued, (v) => `${num2(v, 0)} ${t("сум", "so'm", "UZS")}`)}</td></tr>
              <tr><td>{t("«Грязная» цена", "«Iflos» narx", "Dirty price")}</td><td>{m(bond.dirty, (v) => fmtPrice(v, lang))}</td></tr>
              <tr>
                <td>{t("Следующий купон", "Keyingi kupon", "Next coupon")}</td>
                <td title={!nextCoupon && bond.schedule?.next_date
                  ? t("Дата рассчитана из цикла купона и дат размещения и погашения — эмитент подаёт каждую выплату отдельно и заранее их не публикует.",
                      "Sana kupon sikli va sanalardan hisoblangan.",
                      "Computed from the coupon cycle and the placement and redemption dates — the issuer files each payment separately.")
                  : ""}>
                  {nextCoupon
                    ? `${fmtBondDay(nextCoupon.pay_date)}${nextCoupon.amount != null ? ` · ${num2(nextCoupon.amount, 0)} ${t("сум", "so'm", "UZS")}` : ""}`
                    : bond.schedule?.next_date
                      ? <>{fmtBondDay(bond.schedule.next_date)}
                          {bond.schedule.amount != null && ` · ${num2(bond.schedule.amount, 0)} ${t("сум", "so'm", "UZS")}`}
                          <span className="bondsec-recon">*</span></>
                      : dash(t("будущих выплат нет — выпуск погашен либо график не восстановим",
                               "kelgusi to'lovlar yo'q", "no future payments — redeemed, or no schedule can be built"))}
                </td>
              </tr>
              <tr>
                <td>{t("Купонов всего / прошло срок", "Kuponlar jami / muddati o'tgan", "Coupons in all / fallen due")}</td>
                <td>{bond.schedule?.total != null
                  ? `${bond.schedule.total} / ${bond.schedule.paid ?? 0}`
                  : dash(t("график не восстановим", "jadval tiklanmaydi", "no schedule"))}</td>
              </tr>
              <tr>
                <td>{t("Начислений подано эмитентом", "Emitent topshirgan hisoblashlar", "Accruals filed by the issuer")}</td>
                <td title={t("Существенный факт № 32 подтверждает начисление дохода, но не фактическую выплату денег.", "32-son muhim fakt daromad hisoblanishini tasdiqlaydi, lekin haqiqiy to‘lovni emas.", "Material fact #32 confirms accrual, not actual cash payment.")}>
                  {coupons.length || <span className="cell-status">0</span>}
                </td>
              </tr>
              <tr><td>{t("Текущая доходность", "Joriy daromadlilik", "Running yield")}<TermInfo termId="runningYield" lang={lang} /></td><td>{m(bond.simple_yield, (v) => `${num2(v)}%`)}</td></tr>
              <tr><td>{t("Базис дней", "Kun bazisi", "Day count")}</td><td>{bond.day_count_basis || "—"}</td></tr>
            </tbody>
          </table>
        </div>
        <div className="bondsec-kv-card">
          <table className="bondsec-kv">
            <tbody>
              {bond.state === "matured" && bond.realized && (
                <tr>
                  <td>{t("Реализованная доходность", "Amalga oshgan daromadlilik", "Realised return")}</td>
                  <td className="bondsec-strong" title={bond.realized.note || ""}>
                    {bond.realized.value != null ? `${num2(bond.realized.value)}%` : dash(bond.realized.note)}
                  </td>
                </tr>
              )}
              <tr><td>{t("Доходность к погашению", "So'ndirishgacha daromadlilik", "YTM")}<TermInfo termId="ytm" lang={lang} /></td><td className="bondsec-strong">{m(bond.ytm, (v) => `${num2(v)}%`)}</td></tr>
              <tr><td>{t("Доходность к отзыву", "Qaytarib olishgacha daromadlilik", "YTC")}</td><td>{m(bond.ytc, (v) => `${num2(v)}%`)}</td></tr>
              <tr><td>{t("Худшая доходность для владельца", "Egasi uchun eng past daromadlilik", "Yield to worst")}</td><td>{m(bond.ytw, (v) => `${num2(v)}%`)}</td></tr>
              <tr>
                <td>{t("Доходность при цене номинала", "Nominal narxdagi daromadlilik", "Yield at par")}<TermInfo termId="effectiveAtPar" lang={lang} /></td>
                <td>{m(bond.effective_at_par, (v) => `${num2(v)}%`)}</td>
              </tr>
              <tr><td>{t("G-спред", "G-spred", "G-spread")}<TermInfo termId="gSpread" lang={lang} /></td><td>{m(bond.g_spread, (v) => fmtBp(v, lang))}</td></tr>
              <tr><td>{t("Премия к ставке ЦБ", "MB stavkasiga mukofot", "Premium to key rate")}<TermInfo termId="keyRatePremium" lang={lang} /></td><td>{m(bond.spread, (v) => fmtBp(v, lang))}</td></tr>
              <tr><td>{t("Дюрация Маколея, лет", "Makoley dyuratsiyasi", "Macaulay duration")}<TermInfo termId="duration" lang={lang} /></td><td>{m(bond.duration)}</td></tr>
              <tr><td>{t("Модифицированная дюрация", "Modifikatsiyalangan dyuratsiya", "Modified duration")}</td><td>{m(bond.modified_duration)}</td></tr>
              <tr><td>{t("Выпуклость", "Qavariqlik", "Convexity")}<TermInfo termId="convexity" lang={lang} /></td><td>{m(bond.convexity)}</td></tr>
              <tr><td>{t("DV01 (BPV)", "DV01 (BPV)", "DV01 (BPV)")}<TermInfo termId="bpv" lang={lang} /></td><td>{m(bond.dv01 || bond.bpv, (v) => `${num2(v, 2)} ${t("сум", "so'm", "UZS")}`)}</td></tr>
              <tr><td>{t("Стоимость выпуска", "Chiqarilish qiymati", "Issue value")}</td><td>{fmtCompact(bond.issue_value, lang)}</td></tr>
              <tr><td>{t("Качество истории", "Tarix sifati", "History quality")}</td><td>{bond.quality?.data_tier || "—"}</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      {bond.rate_scenarios?.items?.length > 0 && <details className="verified-block">
        <summary>{t("Сценарии ставки ±1/±2 п.п.", "Stavka ssenariylari ±1/±2 f.p.", "Rate scenarios ±1/±2 pp")}</summary>
        <div className="verified-scroll" tabIndex={0} role="region" aria-label={t("Сценарии ставки", "Stavka ssenariylari", "Rate scenarios")}>
          <table><thead><tr><th>{t("Сдвиг", "Siljish", "Shift")}</th><th>{t("Расчётная полная цена", "Hisoblangan to‘liq narx", "Repriced dirty price")}</th><th>{t("Изменение цены", "Narx o‘zgarishi", "Price change")}</th></tr></thead>
            <tbody>{bond.rate_scenarios.items.map((item) => <tr key={item.shift_bps}><td>{item.shift_bps > 0 ? "+" : ""}{num2(item.shift_bps / 100, 0)} {t("п.п.", "f.p.", "pp")}</td><td>{item.price != null ? fmtPrice(item.price, lang) : "—"}</td><td>{item.change_pct != null ? `${num2(item.change_pct)}%` : "—"}</td></tr>)}</tbody>
          </table>
        </div>
      </details>}

      {bond.monitoring_points?.length > 0 && <section className="verified-watch">
        <h3>{t("Два пункта наблюдения", "Ikki kuzatuv bandi", "Two monitoring points")}</h3>
        <div className="verified-watch-grid">{bond.monitoring_points.slice(0, 2).map((point) => <article key={point.metric_code}>
          <h4>{point.metric_code === "market_liquidity" ? t("Ликвидность рынка", "Bozor likvidligi", "Market liquidity") : t("Ближайшая или неподтверждённая выплата", "Yaqin yoki tasdiqlanmagan to‘lov", "Next or unconfirmed payment")}</h4>
          {point.date && <p><strong>{t("Текущая база", "Joriy baza", "Current baseline")}:</strong> {fmtBondDay(point.date)} · {point.current_baseline}</p>}
          {point.metric_code === "market_liquidity" && <p><strong>{t("Текущая база", "Joriy baza", "Current baseline")}:</strong> {point.current_baseline?.quote_as_of || "—"} · {t("сделки", "bitimlar", "trades")}: {point.current_baseline?.trades ?? "—"} · {t("оборот", "aylanma", "turnover")}: {fmtCompact(point.current_baseline?.turnover, lang)}</p>}
          <p><strong>{t("Признак улучшения", "Yaxshilanish belgisi", "Improvement signal")}:</strong> {monitorCopy(point, "improvement_signal")}</p>
          <p><strong>{t("Признак риска", "Xavf belgisi", "Risk signal")}:</strong> {monitorCopy(point, "risk_signal")}</p>
          <p><strong>{t("Нужно раскрыть", "Oshkor qilish kerak", "Disclosure needed")}:</strong> {monitorCopy(point, "required_disclosure")}</p>
        </article>)}</div>
      </section>}

      <BondMarketPosition bond={bond} board={board} keyRate={keyRate} lang={lang} />

      <BondLifeLine bond={bond} flows={(bond.schedule_flows || []).map((f) => ({
        date: f.date, paid: f.paid, due: f.due, executionStatus: f.execution_status, principal: f.principal || 0,
      }))} lang={lang} />

      <div className="bondsec-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "overview"} onClick={() => setTab("overview")}>
          {t("Кривая ГЦБ", "DQQ egri chizig'i", "Gov curve")}
        </button>
        <button type="button" role="tab" aria-selected={tab === "coupons"} onClick={() => setTab("coupons")}>
          {t("Купоны", "Kuponlar", "Coupons")}
        </button>
        <button type="button" role="tab" aria-selected={tab === "ladder"} onClick={() => setTab("ladder")}>
          {t("Лестница доходностей", "Daromadlilik zinasi", "Yield ladder")}
        </button>
      </div>

      {tab === "overview" && <BondGovCurvePanel curveData={curveData} keyRate={keyRate} lang={lang} />}
      {tab === "coupons" && <BondCouponsPanel bond={bond} coupons={coupons} lang={lang} />}
      {tab === "ladder" && <BondLadderPanel board={board} current={bond.ticker} lang={lang} />}
    </section>
  );
}

/** Auction history per tenor plus the key rate — the market the spread is
 * measured against, drawn from the auctions actually held. */
function BondGovCurvePanel({ curveData, keyRate, lang }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  if (!curveData) return <p className="muted">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</p>;
  const auctions = (curveData.auctions || []).filter((a) => a.wavg_rate != null && a.auction_date);
  if (!auctions.length) {
    return (
      <div className="bondsec-empty">
        <b>{t("Аукционы ещё не собраны", "Auksionlar hali yig'ilmagan", "No auctions collected yet")}</b>
        {t("Коллектор читает страницу фискального агента ЦБ РУз; данные появятся после его первого запуска.",
           "Kollektor MB fiskal agenti sahifasini o'qiydi; ma'lumot birinchi ishga tushirishdan keyin paydo bo'ladi.",
           "The collector reads the Central Bank fiscal-agent page; data appears after its first run.")}
      </div>
    );
  }
  // The two (or more) tenors the Ministry actually places, newest 14 auctions each.
  const byTerm = new Map();
  auctions.forEach((a) => {
    const term = Number(a.term_days);
    if (!Number.isFinite(term)) return;
    if (!byTerm.has(term)) byTerm.set(term, []);
    byTerm.get(term).push(a);
  });
  const tenors = [...byTerm.entries()]
    .sort((a, b) => b[1].length - a[1].length)
    .slice(0, 3)
    .map(([term, list]) => [term, list.slice().sort((x, y) => x.auction_date.localeCompare(y.auction_date)).slice(-14)])
    .sort((a, b) => a[0] - b[0]);

  const allDates = [...new Set(tenors.flatMap(([, list]) => list.map((a) => a.auction_date)))].sort();
  const rates = tenors.flatMap(([, list]) => list.map((a) => a.wavg_rate))
    .concat(keyRate?.rate != null ? [keyRate.rate] : []);
  const lo = Math.floor(Math.min(...rates)) - 0.5;
  const hi = Math.ceil(Math.max(...rates)) + 0.5;

  const W = 1060; const H = 300; const L = 50; const R = 170; const T = 20; const B = 44;
  const pw = W - L - R; const ph = H - T - B;
  const X = (d) => L + (pw * Math.max(allDates.indexOf(d), 0)) / Math.max(allDates.length - 1, 1);
  const Y = (v) => T + ph - (ph * (v - lo)) / (hi - lo || 1);
  const tenorClass = ["a", "b", "c"];

  return (
    <div className="bondsec-panel">
      <div className="bondsec-legend muted">
        {tenors.map(([term], i) => (
          <span key={term}><i className={`bondsec-line bondsec-line-${tenorClass[i]}`} />
            {term} {t("дней", "kun", "days")}
          </span>
        ))}
        {keyRate?.rate != null && <span><i className="bondsec-line bondsec-line-dash" />{t("ставка ЦБ", "MB stavkasi", "key rate")}</span>}
      </div>
      <svg className="bondsec-chart" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={t("Аукционы ГЦБ по датам", "DQQ auksionlari", "Government auctions over time")}>
        {Array.from({ length: Math.floor(hi) - Math.ceil(lo) + 1 }, (_, i) => Math.ceil(lo) + i).map((v) => (
          <g key={v}>
            <line x1={L} x2={L + pw} y1={Y(v)} y2={Y(v)} className="bondsec-grid" />
            <text x={L - 8} y={Y(v) + 4} textAnchor="end" className="bondsec-tick">{v}%</text>
          </g>
        ))}
        <line x1={L} x2={L + pw} y1={T + ph} y2={T + ph} className="bondsec-axis" />
        {keyRate?.rate != null && (
          <>
            <line x1={L} x2={L + pw} y1={Y(keyRate.rate)} y2={Y(keyRate.rate)} className="bondsec-keyrate" />
            <text x={L + pw + 8} y={Y(keyRate.rate) + 4} className="bondsec-label">
              {t("ставка ЦБ", "MB stavkasi", "key rate")} {fmtNumber(keyRate.rate, lang, 2)}%
            </text>
          </>
        )}
        {tenors.map(([term, list], i) => {
          const path = list.map((a, j) => `${j === 0 ? "M" : "L"}${X(a.auction_date).toFixed(1)},${Y(a.wavg_rate).toFixed(1)}`).join(" ");
          const last = list[list.length - 1];
          return (
            <g key={term}>
              <path d={path} className={`bondsec-series bondsec-series-${tenorClass[i]}`} fill="none" />
              {list.map((a) => (
                <circle key={a.sec_id + a.auction_date} cx={X(a.auction_date)} cy={Y(a.wavg_rate)} r={3.5}
                        className={`bondsec-seriesdot bondsec-series-${tenorClass[i]}`}>
                  <title>
                    {`${t("Аукцион", "Auksion", "Auction")} ${fmtBondDay(a.auction_date)} · ${term} ${t("дней", "kun", "days")}\n`}
                    {`${t("Ставка (средневзв.)", "Stavka (o'rtacha)", "Rate (w.avg)")}: ${fmtNumber(a.wavg_rate, lang, 2)}%`}
                    {a.min_rate != null && a.max_rate != null ? ` (${fmtNumber(a.min_rate, lang, 2)}–${fmtNumber(a.max_rate, lang, 2)}%)` : ""}
                    {a.placed_value != null ? `\n${t("Размещено", "Joylashtirildi", "Placed")}: ${fmtNumber(a.placed_value, lang, 2)} ${t("млрд сум", "mlrd so'm", "bn UZS")}` : ""}
                    {a.isin ? `\nISIN: ${a.isin}` : ""}
                  </title>
                </circle>
              ))}
              <text x={X(last.auction_date) + 10} y={Y(last.wavg_rate) + 4} className="bondsec-label bondsec-label-strong">
                {fmtNumber(last.wavg_rate, lang, 2)}%
              </text>
            </g>
          );
        })}
        {allDates.map((d, i) => (
          (allDates.length <= 8 || i % Math.ceil(allDates.length / 8) === 0) && (
            <text key={d} x={X(d)} y={T + ph + 18} textAnchor="middle" className="bondsec-tick">{fmtBondDay(d).slice(0, 5)}</text>
          )
        ))}
      </svg>
      <p className="muted bondsec-note">
        {t("Средневзвешенная доходность размещения по каждому аукциону; наведите на точку — объём и коридор ставок. Источник: cbu.uz, операции фискального агента.",
           "Har auksion bo'yicha o'rtacha tortilgan joylashtirish daromadliligi. Manba: cbu.uz.",
           "The weighted-average placement yield of each auction; hover a dot for the volume and the rate band. Source: cbu.uz, fiscal-agent operations.")}
      </p>
    </div>
  );
}

function BondCouponsPanel({ bond, coupons, lang }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const today = new Date().toISOString().slice(0, 10);
  const nominal = bond.reference?.nominal;
  const maturity = bond.reference?.maturity_date;
  // The schedule the server built: filed payments where the issuer filed them,
  // and the register's cycle everywhere else. Before the register existed this
  // panel could only draw the two or three coupons an issuer had announced, so
  // a five-year bond's «календарь выплат» was three bars.
  const served = bond.schedule_flows || [];
  const flows = served.length
    ? served.map((f) => ({
        date: f.date, coupon: f.coupon, principal: f.principal || 0,
        due: f.due, paid: f.paid, executionStatus: f.execution_status,
        no: f.no, filed: f.filed,
      }))
    : coupons
        .filter((c) => c.pay_date)
        .map((c) => ({
          date: c.pay_date.slice(0, 10),
          coupon: c.amount,
          principal: maturity && c.pay_date.slice(0, 10) === maturity.slice(0, 10) && nominal != null ? nominal : 0,
          due: c.pay_date.slice(0, 10) <= today,
          paid: c.payment_confirmed === true || ["paid", "confirmed", "executed"].includes(String(c.execution_status || "").toLowerCase()),
          no: c.coupon_no,
          filed: true,
        }))
        .sort((a, b) => a.date.localeCompare(b.date));
  if (!served.length && maturity && nominal != null && !flows.some((f) => f.principal)) {
    flows.push({ date: maturity.slice(0, 10), coupon: null, principal: nominal, due: maturity.slice(0, 10) <= today, paid: false, no: null, filed: false });
  }
  if (!flows.length) {
    return (
      <div className="bondsec-empty">
        <b>{t("График выплат не восстановим", "To'lov jadvali tiklanmaydi", "No payment schedule can be built")}</b>
        {t("Для графика нужны ставка купона, цикл выплат и обе даты — размещения и погашения. Реестр обращающихся выпусков биржи не даёт по этому выпуску всех четырёх, а эмитент не подавал начислений на openinfo.uz.",
           "Jadval uchun kupon stavkasi, sikl va ikkala sana kerak.",
           "A schedule needs the coupon rate, the payment cycle and both dates — placement and redemption. The exchange's register does not carry all four for this issue, and the issuer has filed no accruals on openinfo.uz.")}
      </div>
    );
  }
  const reconstructed = flows.filter((f) => f.filed === false).length;

  const known = flows.filter((f) => (f.coupon || 0) + (f.principal || 0) > 0);
  const maxV = Math.max(...known.map((f) => (f.coupon || 0) + (f.principal || 0)), 1);
  const W = 1060; const H = 280; const L = 70; const R = 16; const T = 20; const B = 46;
  const pw = W - L - R; const ph = H - T - B;
  const band = pw / Math.max(flows.length, 1);
  const bw = Math.min(26, band * 0.55);

  return (
    <div className="bondsec-panel">
      <div className="bondsec-legend muted">
        <span><i className="bondsec-dot" style={{ background: "var(--accent)" }} />{t("купон", "kupon", "coupon")}</span>
        {flows.some((f) => f.principal > 0) && <span><i className="bondsec-dot bondsec-dot-principal" />{t("погашение номинала", "nominal qaytishi", "principal")}</span>}
        <span>{t("бледное — исполнение подтверждено", "xira — ijro tasdiqlangan", "faded = execution confirmed")}</span>
      </div>
      <svg className="bondsec-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("Календарь выплат", "To'lovlar kalendari", "Payment calendar")}>
        <line x1={L} x2={W - R} y1={T + ph} y2={T + ph} className="bondsec-axis" />
        {flows.map((f, i) => {
          const cx = L + band * (i + 0.5);
          const hC = f.coupon ? (ph * f.coupon) / maxV : 0;
          const hP = f.principal ? (ph * f.principal) / maxV : 0;
          return (
            <g key={`${f.date}-${i}`} opacity={f.paid ? 0.38 : 1}>
              {hP > 0 && <rect x={cx - bw / 2} y={T + ph - hC - hP} width={bw} height={hP} className="bondsec-bar-principal" rx="3" />}
              {hC > 0 && <rect x={cx - bw / 2} y={T + ph - hC} width={bw} height={hC} className="bondsec-bar" rx="3" />}
              {hC === 0 && hP === 0 && (
                <text x={cx} y={T + ph - 6} textAnchor="middle" className="bondsec-tick">?</text>
              )}
              {flows.length <= 16 && (
                <text x={cx} y={T + ph + 16} textAnchor="middle" className="bondsec-tick">{fmtBondDay(f.date).slice(0, 5)}</text>
              )}
              <rect x={cx - band / 2} y={T} width={band} height={ph} fill="transparent">
                <title>
                  {`${fmtBondDay(f.date)}${f.no != null ? ` · ${t("купон №", "kupon №", "coupon #")}${f.no}` : ""}\n`}
                  {f.coupon != null ? `${t("Купон", "Kupon", "Coupon")}: ${fmtNumber(f.coupon, lang, 2)} ${t("сум", "so'm", "UZS")}\n` : `${t("Сумма купона не подана", "Kupon summasi topshirilmagan", "Coupon amount not filed")}\n`}
                  {f.principal > 0 ? `${t("Номинал", "Nominal", "Principal")}: ${fmtNumber(f.principal, lang, 0)} ${t("сум", "so'm", "UZS")}\n` : ""}
                  {f.paid ? t("выплата подтверждена", "to‘lov tasdiqlangan", "payment confirmed") : f.due ? t("срок наступил, выплата не подтверждена", "muddat keldi, to‘lov tasdiqlanmagan", "due; payment not confirmed") : t("предстоит", "kutilmoqda", "upcoming")}
                </title>
              </rect>
            </g>
          );
        })}
      </svg>
      <div className="market-table-scroll">
        <table className="market-table bondsec-spread-table">
          <thead>
            <tr>
              <th>№</th>
              <th>{t("Дата выплаты", "To'lov sanasi", "Pay date")}</th>
              <th className="num">{t("Купон, сум", "Kupon, so'm", "Coupon, UZS")}</th>
              <th className="num">{t("Номинал, сум", "Nominal, so'm", "Principal, UZS")}</th>
              <th>{t("Статус", "Holat", "Status")}</th>
            </tr>
          </thead>
          <tbody>
            {flows.map((f, i) => (
              <tr key={`${f.date}-r${i}`}>
                <td>{f.no != null ? f.no : "—"}</td>
                <td>{fmtBondDay(f.date)}</td>
                <td className="num">{f.coupon != null ? fmtNumber(f.coupon, lang, 2) : "—"}</td>
                <td className="num">{f.principal > 0 ? fmtNumber(f.principal, lang, 0) : "—"}</td>
                <td className="muted">
                  {f.paid ? t("выплата подтверждена", "to‘lov tasdiqlangan", "payment confirmed") : f.due ? t("срок наступил, выплата не подтверждена", "muddat keldi, to‘lov tasdiqlanmagan", "due; payment not confirmed") : t("предстоит", "kutilmoqda", "upcoming")}
                  {f.filed === false && <span className="bondsec-recon" title={t("Дата и сумма рассчитаны из условий выпуска, эмитент этот платёж не подавал.", "Sana va summa chiqarilish shartlaridan hisoblangan.", "Date and amount computed from the issue's terms; the issuer has not filed this payment.")}> *</span>}
                  {f.filed === true && <span className="tone-pos" title={t("Эмитент подал начисление; это не подтверждает фактическую выплату.", "Emitent hisoblashni topshirgan; bu haqiqiy to‘lovni tasdiqlamaydi.", "The issuer filed the accrual; this does not confirm cash payment.")}> ✓</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted bondsec-note">
        {reconstructed
          ? t(`График собран из условий выпуска: реестр обращающихся выпусков биржи публикует ставку, цикл купона и даты размещения и погашения, а сами даты платежей между ними раскладываются равномерно. Из ${flows.length} выплат эмитент подал ${flows.length - reconstructed} — они отмечены галочкой; остальные ${reconstructed} рассчитаны и отмечены звёздочкой. «Срок прошёл» означает, что платёж наступил по календарю, а не что он подтверждён исполненным.`,
             `Jadval chiqarilish shartlaridan yig'ilgan. ${flows.length} to'lovdan ${flows.length - reconstructed} tasini emitent topshirgan, qolgan ${reconstructed} tasi hisoblangan.`,
             `The schedule is assembled from the issue's terms: the exchange's register of circulating issues publishes the rate, the coupon cycle and the placement and redemption dates, and the payment dates between them are laid evenly. Of ${flows.length} payments the issuer has filed ${flows.length - reconstructed} — marked with a tick; the other ${reconstructed} are computed and marked with a star. "Fell due" means the date has passed, not that the payment is confirmed met.`)
          : t("Каждое начисление в графике подано эмитентом; фактическая выплата считается подтверждённой только при отдельном источнике исполнения.",
             "Jadvaldagi har bir hisoblash emitent tomonidan topshirilgan; haqiqiy to‘lov faqat alohida ijro manbasi bilan tasdiqlanadi.",
             "Every accrual in the schedule was filed by the issuer; actual payment is confirmed only by a separate execution source.")}
      </p>
    </div>
  );
}

/** Every issue's yield on one ruler, the current one highlighted. Issues whose
 * yield is not computable show their coupon, marked as such — a different
 * number, never passed off as a yield. */
function BondLadderPanel({ board, current, lang }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  if (!board) return <p className="muted">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</p>;
  const rows = (board.items || [])
    .map((b) => {
      const ytm = b.ytm?.value;
      const coupon = b.reference?.coupon_rate;
      return { ticker: b.ticker, v: ytm != null ? ytm : coupon, isYtm: ytm != null };
    })
    .filter((r) => r.v != null)
    .sort((a, b) => a.v - b.v);
  if (!rows.length) return <div className="bondsec-empty"><b>{t("Нет данных", "Ma'lumot yo'q", "No data")}</b></div>;

  const maxV = Math.max(...rows.map((r) => r.v)) * 1.15;
  const keyRateVal = board.key_rate?.rate;
  const W = 1060; const L = 120; const R = 90; const T = 28; const B = 34;
  const rowH = 26;
  const H = T + B + rows.length * rowH;
  const pw = W - L - R;
  const X = (v) => L + (pw * v) / maxV;

  return (
    <div className="bondsec-panel">
      <svg className="bondsec-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("Лестница доходностей", "Daromadlilik zinasi", "Yield ladder")}>
        {[0, 5, 10, 15, 20, 25, 30].filter((v) => v <= maxV).map((v) => (
          <g key={v}>
            <line x1={X(v)} x2={X(v)} y1={T} y2={H - B} className="bondsec-grid" />
            <text x={X(v)} y={H - B + 16} textAnchor="middle" className="bondsec-tick">{v}%</text>
          </g>
        ))}
        {keyRateVal != null && keyRateVal <= maxV && (
          <>
            <line x1={X(keyRateVal)} x2={X(keyRateVal)} y1={T - 12} y2={H - B} className="bondsec-keyrate" />
            <text x={X(keyRateVal) + 5} y={T - 14} className="bondsec-label">{t("ставка ЦБ", "MB stavkasi", "key rate")} {fmtNumber(keyRateVal, lang, 2)}%</text>
          </>
        )}
        {rows.map((r, i) => {
          const y = T + i * rowH + rowH / 2;
          const me = r.ticker === current;
          return (
            <g key={r.ticker} opacity={me ? 1 : 0.68}>
              <rect x={L} y={y - 8} width={Math.max(X(r.v) - L, 2)} height={16} rx="4"
                    className={me ? "bondsec-bar bondsec-bar-me" : "bondsec-bar"} />
              <text x={L - 8} y={y + 4} textAnchor="end" className={`bondsec-label${me ? " bondsec-label-strong" : ""}`}>{r.ticker}</text>
              <text x={X(r.v) + 6} y={y + 4} className={`bondsec-label${me ? " bondsec-label-strong" : ""}`}>
                {fmtNumber(r.v, lang, 2)}%{r.isYtm ? "" : ` ${t("к", "k", "c")}`}
              </text>
              <title>{r.isYtm ? t("доходность к погашению", "so'ndirishgacha daromadlilik", "yield to maturity") : t("ставка купона — доходность не вычислима", "kupon stavkasi — daromadlilik hisoblanmaydi", "coupon rate — yield not computable")}</title>
            </g>
          );
        })}
      </svg>
      <p className="muted bondsec-note">
        {t("«к» — показана ставка купона: у выпуска нет цены или даты погашения, и доходность к погашению не вычислима.",
           "«k» — kupon stavkasi ko'rsatilgan: chiqarilishning narxi yoki to'lov sanasi yo'q.",
           "\"c\" marks a coupon rate: the issue lacks a price or a maturity, so a true yield cannot be computed.")}
      </p>
    </div>
  );
}

export { BondCard, BondsView };
