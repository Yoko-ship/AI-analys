import { roundedDisplayValue } from "../../lib/format.js";
import { nearestPointIndex } from "../../lib/geometry.js";
import React from "react";
import { formatCompactVolume } from "../../shared/marketModel.jsx";
import { formatRatio } from "../../shared/format.jsx";
import { finLabel } from "../../shared/financialLabels.jsx";
import { createPortal } from "react-dom";
import { TermInfo } from "../../shared/TermInfo.jsx";
import { dividendSummary } from "./keyStats.jsx";
import { signedFixed } from "../../shared/format.jsx";

// The Финансы tab, on the reference page's shape: sub-tabs across the statement,
// a multi-series chart of the section's headline lines, then a table with one
// column per YEAR and a growth row under each absolute figure.
//
// The series comes from /api/company/{t}/financials — the fact store, which has
// held nine to eleven annual periods per issuer all along and was serving
// nobody. This tab used to show ONE period's five ratios out of the reports
// cache, and «не кешированы» for every issuer whose cache was cold.
//
// No Cash Flow sub-tab: NSBU form 4 is not parsed, so there is no cash-flow
// series to put behind it. An empty fourth tab would look like a loading bug.
const FIN_SECTIONS = [
  {
    key: "income",
    label: ["Прибыли и убытки", "Foyda va zarar", "Income Statement"],
    // The reference page's income statement, in its order: what came in, what
    // the goods cost, what running the business cost, what was left.
    rows: ["net_revenue", "gross_profit", "operating_expenses", "operating_income", "net_profit"],
    // Percentages get their own block, as on the reference: mixing a margin
    // into a column of sums invites reading 5.62 as five sums.
    // Only the margin this platform computes itself — see the note on
    // FACT_PERCENT_FIELDS for the ones the feed publishes and we do not trust.
    margins: ["net_margin"],
    chart: ["net_revenue", "operating_expenses", "operating_income"],
  },
  {
    key: "balance",
    label: ["Баланс", "Balans", "Balance Sheet"],
    rows: ["total_assets", "total_liabilities", "total_equity"],
    chart: ["total_assets", "total_liabilities", "total_equity"],
  },
  {
    key: "ratios",
    label: ["Коэффициенты", "Koeffitsiyentlar", "Key Ratios"],
    margins: ["roe", "roa", "current_ratio", "quick_ratio", "debt_ratio",
              "debt_to_equity", "total_asset_turnover", "return_to_capital_employed"],
    chart: ["roe", "roa"],
  },
];

// The quarterly view carries only what the quarterly FILINGS carry: the income
// statement plus the balance snapshots the parse keeps. Its Баланс sub-tab
// shows the SAME three lines as the annual one — Активы, Обязательства,
// Капитал (customer, 2026-08-16: the two views must read alike; cash came off
// the display, though the endpoint still serves it).
// No Коэффициенты sub-tab — quarterly ROE/ROA off a cumulative income against a
// point-in-time balance is a figure that needs annualising to mean anything,
// and a wrong ratio beside a right one discredits both.
const FIN_SECTIONS_QUARTER = [
  {
    key: "income",
    label: ["Прибыли и убытки", "Foyda va zarar", "Income Statement"],
    rows: ["net_revenue", "gross_profit", "operating_expenses", "operating_income", "net_profit"],
    margins: ["net_margin"],
    chart: ["net_revenue", "operating_expenses", "operating_income"],
  },
  {
    key: "balance",
    label: ["Баланс", "Balans", "Balance Sheet"],
    rows: ["total_assets", "total_liabilities", "total_equity"],
    chart: ["total_assets", "total_liabilities", "total_equity"],
  },
];

// "2024Q2" → {y: 2024, q: 2}; anything else → null.
const parseQPeriod = (p) => {
  const m = /^(\d{4})Q([1-4])$/.exec(String(p));
  return m ? { y: +m[1], q: +m[2] } : null;
};

const finPeriodLabel = (p, compact) => {
  const pq = parseQPeriod(p);
  return pq ? (compact ? `Q${pq.q}'${String(pq.y).slice(2)}` : `Q${pq.q} ${pq.y}`) : String(p);
};

// Which glossary entry explains a row of the Финансы table (lib/glossary.js is
// the one definition store; `id` matches the market board's column key, so most
// of these are the field's own name and the map only bridges the two that are
// not). A ratio is where the reader actually needs the explanation: «Выручка»
// says what it is, «ROCE» and «Долг/Активы» do not, and a coefficient printed
// bare — 0,07 — says least of all. Only the fields listed here get an ⓘ; the
// marker renders nothing for a term that has no entry, so an unmapped row
// simply stays plain.
const FIN_FIELD_TERMS = {
  net_margin: "netMargin",
  roe: "roe",
  roa: "roa",
  current_ratio: "currentRatio",
  quick_ratio: "quickRatio",
  debt_ratio: "debtAssets",
  debt_to_equity: "debtEq",
  total_asset_turnover: "assetTurnover",
  return_to_capital_employed: "roce",
};

// One palette for the chart, the legend and the table's row dots. A field's
// colour comes from its position in the SECTION's row list, not in the current
// selection — toggling a line on or off must not repaint the others.
const FIN_CHART_COLORS = ["#38bdf8", "#f59e0b", "#a855f7", "#34d399", "#f472b6",
                          "#facc15", "#60a5fa", "#fb7185", "#4ade80", "#c084fc"];

const FIN_CHART_COMPACT_MEDIA = "(max-width: 620px)";

// The section's headline lines over time. Deliberately not the price chart: no
// range buttons, no hover — this is a shape, and the table underneath is the data.
function useFinancialChartFrame() {
  const [compact, setCompact] = React.useState(() => (
    typeof window !== "undefined" && window.matchMedia(FIN_CHART_COMPACT_MEDIA).matches
  ));

  React.useEffect(() => {
    const media = window.matchMedia(FIN_CHART_COMPACT_MEDIA);
    const update = () => setCompact(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  // A desktop-shaped 820×210 viewBox is only ~90px tall on a phone.  Give the
  // compact plot its own frame so a reader can see the actual series, rather
  // than a flattened strip of axis labels.
  return compact
    ? { W: 380, H: 230, PAD: { t: 12, r: 10, b: 30, l: 52 } }
    : { W: 820, H: 210, PAD: { t: 12, r: 14, b: 26, l: 70 } };
}

function FinancialsChart({ fields, series, periods, lang, colorOf, onToggle }) {
  // A chart nobody can interrogate is a picture. This one had no hover at all:
  // pointing at a year gave nothing, which is what «no info» meant.
  const [hover, setHover] = React.useState(null);
  const [hoverY, setHoverY] = React.useState(0);
  const { W, H, PAD } = useFinancialChartFrame();
  const cols = periods;               // already oldest → newest, left → right
  const drawn = fields
    .map((f, i) => ({ f, color: colorOf ? colorOf(f) : FIN_CHART_COLORS[i % FIN_CHART_COLORS.length], s: series[f] }))
    .filter((d) => d.s && cols.some((c) => Number.isFinite(d.s.values[c])));
  if (drawn.length === 0 || cols.length < 2) return null;

  const all = drawn.flatMap((d) => cols.map((c) => d.s.values[c]).filter(Number.isFinite));
  // Zero-based, as on the reference: an axis that starts at its own minimum
  // turns a three-percent move into a cliff.
  const max = Math.max(...all, 0), min = Math.min(...all, 0);
  const span = max - min || 1;
  const x = (i) => PAD.l + (i / Math.max(1, cols.length - 1)) * (W - PAD.l - PAD.r);
  const y = (v) => PAD.t + (1 - (v - min) / span) * (H - PAD.t - PAD.b);
  const money = drawn[0].s.money;
  // The axis carries the % sign only when EVERY drawn line is a percentage:
  // ROE beside Долг/Капитал shares a numeric scale, not a unit, and the
  // per-row unit lives in the tooltip.
  const pct = drawn.every((d) => d.s.unit === "%");
  const axis = (v) => (money ? formatCompactVolume(v, lang)
    : `${formatRatio(v, 1, lang)}${pct ? "%" : ""}`);
  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (!r.width) return;
    const relX = ((e.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(cols.length - 1,
      nearestPointIndex((relX - PAD.l) / (W - PAD.l - PAD.r), cols.length)));
    setHover(i);
    const wrap = e.currentTarget.parentElement;
    setHoverY(e.clientY - (wrap ? wrap.getBoundingClientRect().top : r.top));
  };

  return (
    <div className="fin-chart">
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {[0, 0.5, 1].map((f, i) => (
          <line key={i} x1={PAD.l} y1={y(min + f * span)} x2={W - PAD.r} y2={y(min + f * span)}
            stroke="currentColor" strokeOpacity="0.16" strokeDasharray="4 6" strokeWidth="0.8" />
        ))}
        {[0, 0.5, 1].map((f, i) => (
          <text key={`l${i}`} x={PAD.l - 8} y={y(min + f * span) + 3.5} textAnchor="end"
            fontSize="10" fill="currentColor" opacity="0.5">{axis(min + f * span)}</text>
        ))}
        {drawn.map((d) => {
          const pts = cols.map((c, i) => ({ i, v: d.s.values[c] })).filter((pt) => Number.isFinite(pt.v));
          if (pts.length < 2) return null;
          const path = pts.map((pt, k) => `${k ? "L" : "M"}${x(pt.i).toFixed(1)},${y(pt.v).toFixed(1)}`).join(" ");
          return <path key={d.f} d={path} fill="none" stroke={d.color} strokeWidth="2"
            strokeLinejoin="round" vectorEffect="non-scaling-stroke" />;
        })}
        {cols.map((c, i) => {
          // A quarterly series can put 15+ columns here; labels every ~60px at
          // most, the ends always named.
          const step = Math.max(1, Math.ceil(cols.length / 13));
          if (i % step !== 0 && i !== cols.length - 1) return null;
          return (
            <text key={c} x={x(i)} y={H - 8} fontSize="10" fill="currentColor" opacity="0.5"
              textAnchor={i === 0 ? "start" : i === cols.length - 1 ? "end" : "middle"}>
              {finPeriodLabel(c, true)}
            </text>
          );
        })}
        {hover != null && (
          <>
            <line x1={x(hover)} y1={PAD.t} x2={x(hover)} y2={H - PAD.b}
              stroke="currentColor" strokeOpacity="0.38" strokeDasharray="3 3" />
            {drawn.map((d) => (Number.isFinite(d.s.values[cols[hover]]) ? (
              <circle key={d.f} cx={x(hover)} cy={y(d.s.values[cols[hover]])} r="3.6"
                fill={d.color} stroke="var(--panel, #0b0f1a)" strokeWidth="1.5" />
            ) : null))}
          </>
        )}
      </svg>
      {hover != null && (
        <div className={`cpc-tooltip ${x(hover) > W * 0.62 ? "" : ""}`}
          style={{
            top: `${Math.max(6, hoverY - 40)}px`,
            ...(x(hover) > W * 0.62
              ? { right: `calc(${((W - x(hover)) / W) * 100}% + 12px)` }
              : { left: `calc(${(x(hover) / W) * 100}% + 12px)` }),
          }}>
          <div className="cpc-tt-date">{finPeriodLabel(cols[hover])}</div>
          {drawn.map((d) => {
            const v = d.s.values[cols[hover]];
            return (
              <div className="cpc-tt-row" key={d.f}>
                <span><i className="fin-tt-dot" style={{ background: d.color }} />{finLabel(d.f, lang)}</span>
                <b>{!Number.isFinite(v) ? "—"
                  : d.s.money ? formatCompactVolume(v, lang)
                  : `${formatRatio(v, 2, lang)}${d.s.unit === "%" ? "%" : ""}`}</b>
              </div>
            );
          })}
        </div>
      )}
      <div className="fin-legend">
        {drawn.map((d) => (onToggle ? (
          <button key={d.f} type="button" className="fin-legend-item clickable"
            onClick={() => onToggle(d.f)}>
            <i style={{ background: d.color }} />{finLabel(d.f, lang)}
          </button>
        ) : (
          <span key={d.f} className="fin-legend-item">
            <i style={{ background: d.color }} />{finLabel(d.f, lang)}
          </span>
        )))}
      </div>
    </div>
  );
}

// The same series as columns of bars. A line says "this is the shape of a
// trend"; a bar says "this is how big each period was" — for revenue or profit,
// which is what most readers open this tab for, the second is the honest picture,
// and a line between two annual points implies twelve months of movement nobody
// measured.
//
// Deliberately the same frame as FinancialsChart — same viewBox, padding, axis
// formatter, palette and tooltip — so switching the view does not re-teach the
// reader where to look. The zero line is drawn, not implied: on this market a
// year of losses is common, and a bar hanging below the axis has to hang from
// something.
function FinancialsBars({ fields, series, periods, lang, colorOf, onToggle }) {
  const [hover, setHover] = React.useState(null);
  const [hoverY, setHoverY] = React.useState(0);
  const { W, H, PAD } = useFinancialChartFrame();
  const cols = periods;
  const drawn = fields
    .map((f, i) => ({ f, color: colorOf ? colorOf(f) : FIN_CHART_COLORS[i % FIN_CHART_COLORS.length], s: series[f] }))
    .filter((d) => d.s && cols.some((c) => Number.isFinite(d.s.values[c])));
  if (drawn.length === 0 || cols.length === 0) return null;

  const all = drawn.flatMap((d) => cols.map((c) => d.s.values[c]).filter(Number.isFinite));
  const max = Math.max(...all, 0), min = Math.min(...all, 0);
  const span = max - min || 1;
  const plot = W - PAD.l - PAD.r;
  const y = (v) => PAD.t + (1 - (v - min) / span) * (H - PAD.t - PAD.b);
  const zero = y(0);
  const money = drawn[0].s.money;
  const pct = drawn.every((d) => d.s.unit === "%");
  const axis = (v) => (money ? formatCompactVolume(v, lang)
    : `${formatRatio(v, 1, lang)}${pct ? "%" : ""}`);
  // One slot per period, the bars of a period sharing it. A tenth of the slot
  // stays empty on each side so neighbouring periods do not touch.
  const slot = plot / cols.length;
  const groupW = slot * 0.8;
  const barW = Math.max(1.5, groupW / drawn.length);
  const slotX = (i) => PAD.l + i * slot;
  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (!r.width) return;
    const relX = ((e.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(cols.length - 1, Math.floor((relX - PAD.l) / slot)));
    setHover(i);
    const wrap = e.currentTarget.parentElement;
    setHoverY(e.clientY - (wrap ? wrap.getBoundingClientRect().top : r.top));
  };

  return (
    <div className="fin-chart">
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {[0, 0.5, 1].map((f, i) => (
          <line key={i} x1={PAD.l} y1={y(min + f * span)} x2={W - PAD.r} y2={y(min + f * span)}
            stroke="currentColor" strokeOpacity="0.16" strokeDasharray="4 6" strokeWidth="0.8" />
        ))}
        {[0, 0.5, 1].map((f, i) => (
          <text key={`l${i}`} x={PAD.l - 8} y={y(min + f * span) + 3.5} textAnchor="end"
            fontSize="10" fill="currentColor" opacity="0.5">{axis(min + f * span)}</text>
        ))}
        {min < 0 && (
          <line x1={PAD.l} y1={zero} x2={W - PAD.r} y2={zero}
            stroke="currentColor" strokeOpacity="0.45" strokeWidth="1" />
        )}
        {hover != null && (
          <rect x={slotX(hover)} y={PAD.t} width={slot} height={H - PAD.t - PAD.b}
            fill="currentColor" opacity="0.06" />
        )}
        {cols.map((c, i) => drawn.map((d, k) => {
          const v = d.s.values[c];
          if (!Number.isFinite(v)) return null;
          const top = Math.min(y(v), zero);
          // A period whose value rounds to nothing still gets a visible sliver:
          // «0» and «not filed» are different statements and the chart must not
          // render them the same way.
          const height = Math.max(1, Math.abs(zero - y(v)));
          const x = slotX(i) + (slot - groupW) / 2 + k * barW;
          return <rect key={`${c}-${d.f}`} x={x.toFixed(1)} y={top.toFixed(1)}
            width={Math.max(1, barW - 1.5).toFixed(1)} height={height.toFixed(1)}
            fill={d.color} rx={Math.min(2, barW / 3)} />;
        }))}
        {cols.map((c, i) => {
          const step = Math.max(1, Math.ceil(cols.length / 13));
          if (i % step !== 0 && i !== cols.length - 1) return null;
          return (
            <text key={c} x={slotX(i) + slot / 2} y={H - 8} fontSize="10" fill="currentColor"
              opacity="0.5" textAnchor="middle">{finPeriodLabel(c, true)}</text>
          );
        })}
      </svg>
      {hover != null && (
        <div className="cpc-tooltip"
          style={{
            top: `${Math.max(6, hoverY - 40)}px`,
            ...((slotX(hover) + slot / 2) > W * 0.62
              ? { right: `calc(${((W - slotX(hover)) / W) * 100}% + 12px)` }
              : { left: `calc(${((slotX(hover) + slot) / W) * 100}% + 12px)` }),
          }}>
          <div className="cpc-tt-date">{finPeriodLabel(cols[hover])}</div>
          {drawn.map((d) => {
            const v = d.s.values[cols[hover]];
            return (
              <div className="cpc-tt-row" key={d.f}>
                <span><i className="fin-tt-dot" style={{ background: d.color }} />{finLabel(d.f, lang)}</span>
                <b>{!Number.isFinite(v) ? "—"
                  : d.s.money ? formatCompactVolume(v, lang)
                  : `${formatRatio(v, 2, lang)}${d.s.unit === "%" ? "%" : ""}`}</b>
              </div>
            );
          })}
        </div>
      )}
      <div className="fin-legend">
        {drawn.map((d) => (onToggle ? (
          <button key={d.f} type="button" className="fin-legend-item clickable"
            onClick={() => onToggle(d.f)}>
            <i style={{ background: d.color }} />{finLabel(d.f, lang)}
          </button>
        ) : (
          <span key={d.f} className="fin-legend-item">
            <i style={{ background: d.color }} />{finLabel(d.f, lang)}
          </span>
        )))}
      </div>
    </div>
  );
}

// How the financial section is drawn. Three, because that is what the customer
// asked for and because they answer three different questions: a line for the
// trend, bars for the size of each period, the table for the figures themselves.
const FIN_DASHBOARDS = [
  { key: "line", label: ["Линейный", "Chizmali", "Line"] },
  { key: "bar", label: ["Столбчатый", "Ustunli", "Bars"] },
  { key: "table", label: ["Таблица", "Jadval", "Table"] },
];

// v2 resets the old table-first preference after historical series were
// restored. The financial page should open with its trend visible; a reader's
// later choice of bars or table is still remembered under this new key.
const FIN_DASHBOARD_KEY = "uz_fin_dashboard_v2";

// The «Сплиты» sub-tab: the corporate-actions register every price series on
// the site is back-adjusted by, shown as its own record. uzse.uz keeps the
// same thing behind «Посмотреть сплиты» on the quote page, but lists only the
// redenominations — this table also carries the free issues out of own funds,
// because a holder's 3× on ALSM is the two together. For most securities the
// honest content is «не зафиксировано», and that renders as a sentence, not
// as an empty table.
function CompanySplitsTable({ items, lang }) {
  const t = React.useCallback((ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru), [lang]);
  const locale = lang === "en" ? "en-US" : "ru-RU";
  if (items === null) return <div className="chart-loading muted">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</div>;
  const rows = items || [];
  if (rows.length === 0) return (
    <div className="panel" style={{ padding: 32, textAlign: "center" }}>
      <p className="muted">{t("Сплитов и бонусных эмиссий по этой бумаге не зафиксировано",
                              "Bu qog'oz bo'yicha splitlar va bonus emissiyalar qayd etilmagan",
                              "No splits or bonus issues on record for this security")}</p>
    </div>
  );
  const fmtDate = (d) => (d ? new Date(d).toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" }) : "—");
  const fmtN = (v) => Number(v).toLocaleString(locale, { maximumFractionDigits: 2 });
  const kindLabel = (k) => (k === "bonus"
    ? t("Бонусная эмиссия", "Bonus emissiya", "Bonus issue")
    : t("Сплит", "Split", "Split"));
  // «1 → 1,69» on its own is a riddle; the sentence beside it is the row.
  const effectLabel = (r) => {
    const n = Number(r.ratio) || 1;
    if (r.kind === "bonus") {
      const per100 = roundedDisplayValue((n - 1) * 100);
      return t(`держателю начислено ${fmtN(per100)} новых акций на каждые 100`,
               `har 100 aksiyaga ${fmtN(per100)} ta yangi aksiya qo'shildi`,
               `${fmtN(per100)} new shares credited for every 100 held`);
    }
    return t(`каждая акция раздроблена на ${fmtN(n)}`,
             `har bir aksiya ${fmtN(n)} taga bo'lindi`,
             `each share was split into ${fmtN(n)}`);
  };
  // The events compound: one pre-2024 ALKB share is 121 × 205/121 = 205 of
  // today's, and that product — not either row alone — is what explains the
  // step a reader remembers seeing in an unadjusted price.
  const total = rows.reduce((acc, r) => acc * (Number(r.ratio) || 1), 1);
  return (
    <div className="panel fin-panel">
      <div className="fin-table-wrap">
        <table className="fin-table splits-table">
          <thead>
            <tr>
              <th scope="col" className="splits-col-date">{t("Дата", "Sana", "Date")}</th>
              <th scope="col" className="splits-col-kind">{t("Событие", "Hodisa", "Event")}</th>
              <th scope="col" className="num splits-col-ratio">{t("Коэффициент", "Koeffitsiyent", "Ratio")}</th>
              <th scope="col">{t("Что произошло", "Nima bo'ldi", "What happened")}</th>
              <th scope="col" className="splits-col-src">{t("Раскрытие", "Oshkor qilish", "Disclosure")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>{fmtDate(r.ex_date)}</td>
                <td><span className={`splits-kind splits-kind--${r.kind === "bonus" ? "bonus" : "split"}`}>{kindLabel(r.kind)}</span></td>
                <td className="num">{`1 → ${fmtN(r.ratio)}`}</td>
                <td className="splits-effect">{effectLabel(r)}</td>
                <td className="splits-src">{r.source
                  ? <a href={r.source} target="_blank" rel="noreferrer">openinfo ↗</a>
                  : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="fin-note muted">
        {rows.length > 1 && (
          <>{t("Итого одна акция до всех событий — это ", "Jami: barcha hodisalargacha bitta aksiya — bugungi ", "In total one pre-event share is ")}
            <strong>{fmtN(total)}</strong>
            {t(" сегодняшних. ", " ta aksiya. ", " of today's. ")}</>
        )}
        {t("Дата — первая торговая сессия на новом количестве акций. Цены на графиках и в истории до этой даты уже пересчитаны на сегодняшнюю акцию; объёмы торгов не пересчитываются.",
           "Sana — yangi aksiyalar sonidagi birinchi savdo sessiyasi. Grafiklardagi narxlar bugungi aksiyaga qayta hisoblangan; savdo hajmlari qayta hisoblanmaydi.",
           "The date is the first session traded on the new share count. Prices on the charts and in the history before it are already restated onto today's share; traded volumes are not restated.")}
      </p>
    </div>
  );
}

function FinancialPassportDialog({ passport, loading, field, period, lang, onClose }) {
  const dialogRef = React.useRef(null);
  const closeRef = React.useRef(null);
  const t = React.useCallback((ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru), [lang]);
  const titleId = `financial-passport-${String(field || "value").replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const source = passport?.source;

  React.useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const onKey = (event) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener("keydown", onKey); };
  }, [onClose]);

  const label = finLabel(field, lang);
  const stateLabel = passport?.status === "SOURCED"
    ? t("Источник подтверждён", "Manba tasdiqlangan", "Source linked")
    : passport?.status === "DERIVED"
      ? t("Рассчитано платформой", "Platforma hisoblagan", "Calculated by the platform")
      : t("Паспорт источника недоступен", "Manba pasporti mavjud emas", "Source passport unavailable");

  return createPortal((
    <div className="company-insight-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <article ref={dialogRef} className="company-insight-dialog financial-passport-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header className="company-insight-dialog-head">
          <button ref={closeRef} className="company-insight-close" type="button" onClick={onClose}
            aria-label={t("Закрыть паспорт источника", "Manba pasportini yopish", "Close source passport")}>×</button>
          <div>
            <div className="company-insight-eyebrow">{t("Паспорт значения", "Qiymat pasporti", "Value passport")}</div>
            <h2 id={titleId}>{label}</h2>
            <p>{period}</p>
          </div>
        </header>
        {loading ? <div className="chart-loading muted" style={{ padding: "28px 0" }}>{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</div> : (
          <div className="financial-passport-copy">
            <div className={`financial-passport-status ${passport?.status || "unknown"}`}>{stateLabel}</div>
            {passport?.status === "SOURCED" && source && (
              <dl className="financial-passport-grid">
                <div><dt>{t("Отчёт", "Hisobot", "Report")}</dt><dd>{source.title || `${source.report_form || "—"} ${source.period_year || ""}`}</dd></div>
                <div><dt>{t("Период отчёта", "Hisobot davri", "Report period")}</dt><dd>{source.period_quarter ? `${source.period_year} Q${source.period_quarter}` : source.period_year || "—"}</dd></div>
                {source.role && <div><dt>{t("Колонка / роль", "Ustun / rol", "Column / role")}</dt><dd>{source.stated_period} · {source.role}</dd></div>}
                <div><dt>{t("Стандарт", "Standart", "Standard")}</dt><dd>{source.standard || passport.standard || "—"}</dd></div>
                <div><dt>{t("Периметр", "Qamrov", "Perimeter")}</dt><dd>{source.perimeter || source.source_ticker || "—"}</dd></div>
                <div><dt>{t("Статус проверки", "Tekshiruv holati", "Review status")}</dt><dd>{source.state || "—"}{source.state_reason ? ` — ${source.state_reason}` : ""}</dd></div>
                <div><dt>{t("Строка источника", "Manba satri", "Source line")}</dt><dd>{source.raw_label || "—"}</dd></div>
                {source.components?.length > 0 && <div><dt>{t("Расчёт из строк отчёта", "Hisobot satrlaridan hisob", "Calculated from report lines")}</dt><dd>{source.components.map((c) => `${c.coefficient === -1 ? "−1 × " : ""}${c.raw_label}: (${c.raw_value}) (p. ${c.page})`).join(" + ")}</dd></div>}
                <div><dt>{t("Исходная сумма", "Asl summa", "Raw value")}</dt><dd>{source.raw_value ?? "—"}</dd></div>
                <div><dt>{t("Нормализованное значение", "Normallashtirilgan qiymat", "Normalized value")}</dt><dd>{source.normalized_value ?? "—"}{source.normalization_formula ? ` (${source.normalization_formula})` : ""}</dd></div>
                <div><dt>{t("Знак", "Belgi", "Sign")}</dt><dd>{source.sign || "—"}</dd></div>
                <div><dt>{t("Страница", "Sahifa", "Page")}</dt><dd>{source.page || "—"}</dd></div>
                <div><dt>{t("Единица / масштаб", "Birlik / masshtab", "Unit / scale")}</dt><dd>{source.unit_scale ? `×${source.unit_scale}` : "—"}</dd></div>
                <div><dt>{t("Дата публикации источника", "Manba e’lon qilingan sana", "Source publication date")}</dt><dd>{source.source_published_at || "—"}</dd></div>
                <div><dt>{t("Получен платформой", "Platforma olgan vaqt", "Received by platform")}</dt><dd>{source.received_at || "—"}</dd></div>
                <div><dt>{t("Версия извлечения", "Ajratib olish versiyasi", "Extraction version")}</dt><dd>{source.extraction_version || "—"}</dd></div>
                <div><dt>{t("Хеш файла", "Fayl xeshi", "File hash")}</dt><dd className="financial-passport-hash">{source.file_hash || "—"}</dd></div>
              </dl>
            )}
            {passport?.status === "DERIVED" && (
              <section className="financial-passport-formula">
                <span>{t("Формула", "Formula", "Formula")}</span>
                <code>{passport.formula}</code>
                <p>{t("Это расчёт платформы. Откройте входные значения в таблице, чтобы увидеть их источники.", "Bu platforma hisobi. Manbalarni ko‘rish uchun jadvaldagi kirish qiymatlarini oching.", "This is a platform calculation. Open its input values in the table to inspect their filing sources.")}</p>
              </section>
            )}
            {passport?.status !== "SOURCED" && passport?.status !== "DERIVED" && (
              <p className="financial-passport-reason">{passport?.reason || t("Для этого значения нет проверяемой связи с исходным документом.", "Bu qiymat uchun asl hujjat bilan tekshiriladigan bog‘lanish yo‘q.", "This value has no verifiable link to a source document.")}</p>
            )}
            {passport?.reason && passport?.status === "SOURCED" && <p className="financial-passport-reason">{passport.reason}</p>}
            {source?.excel_url && <a className="company-insight-action" href={source.excel_url} target="_blank" rel="noreferrer">{t("Открыть Excel-отчёт ↗", "Excel hisobotni ochish ↗", "Open Excel report ↗")}</a>}
            {!source?.excel_url && (source?.archived_url || source?.pdf_url) && <a className="company-insight-action" href={source.archived_url || source.pdf_url} target="_blank" rel="noreferrer">{t("Открыть PDF-отчёт ↗", "PDF hisobotni ochish ↗", "Open PDF report ↗")}</a>}
          </div>
        )}
      </article>
    </div>
  ), document.body);
}

function CompanyFinancialsTab({ ticker, ratios, series, periods, loading, lang, standard = "NSBU", onStandardChange, freq = "annual", onFreqChange, splits, dataGaps = [], periodBasis, scope, onScopeChange }) {
  const t = React.useCallback((ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru), [lang]);
  const [section, setSection] = React.useState("income");
  // Which lines the chart draws, per section (annual and quarterly sections
  // share a key space, which is fine — «income» means the same lines in both).
  // Unset = the section's default; from the first click the reader owns it.
  const [chartSel, setChartSel] = React.useState({});
  const [passport, setPassport] = React.useState(null);
  const [passportTarget, setPassportTarget] = React.useState(null);
  const [passportLoading, setPassportLoading] = React.useState(false);
  // Line | Bars | Table — the reader's choice, remembered. Exclusive on purpose:
  // «TABLE» is one of the three, so it cannot also be permanently underneath the
  // other two, and a chart with the whole table below it is what this tab was.
  const [dashboard, setDashboard] = React.useState(() => {
    try {
      const saved = localStorage.getItem(FIN_DASHBOARD_KEY);
      if (FIN_DASHBOARDS.some((d) => d.key === saved)) return saved;
    } catch (e) { /* ignore */ }
    return "line";
  });
  React.useEffect(() => {
    try { localStorage.setItem(FIN_DASHBOARD_KEY, dashboard); } catch (e) { /* ignore */ }
  }, [dashboard]);
  const quarterly = freq === "quarterly";
  const gapReason = (code) => {
    if (code === "EMPTY_SOURCE_FILING") return t("В источнике опубликован пустой баланс.", "Manbada bo‘sh balans e'lon qilingan.", "The source filing contains an empty balance sheet.");
    if (code === "INCONSISTENT_CUMULATIVE_INCOME") return t("Показатели дохода в отчётах противоречат друг другу.", "Hisobotlardagi daromad ko‘rsatkichlari bir-biriga zid.", "Income figures conflict between source filings.");
    if (code === "MISSING_COMPARATIVE_INPUT") return t("Для расчёта квартала не хватает данных предыдущего периода.", "Chorakni hisoblash uchun oldingi davr ma'lumotlari yetishmaydi.", "A required prior-period figure is unavailable for this quarter.");
    if (code === "UNDER_REVIEW") return t("Данные находятся на проверке.", "Ma'lumotlar tekshirilmoqda.", "These figures are under review.");
    if (code === "UNSUPPORTED_DUPLICATE_PERIOD") return t("Дубликат периода не подтверждён отдельным отчётом.", "Takrorlangan davr alohida hisobot bilan tasdiqlanmagan.", "The duplicate period has no supporting filing.");
    return t("Данные отчёта ещё не получены полностью.", "Hisobot ma'lumotlari hali to‘liq olinmagan.", "The filing's figures have not been fully collected.");
  };
  const gapRows = [...new Map(dataGaps.map((gap) => [`${gap.period}:${gap.code}`, gap])).values()];
  const gapNotice = gapRows.length > 0 ? (
    <details className="panel" style={{ padding: "12px 16px", marginBottom: 12 }}>
      <summary>{t("Некоторые финансовые данные недоступны", "Ayrim moliyaviy ma'lumotlar mavjud emas", "Some financial figures are unavailable")}</summary>
      <ul>{gapRows.map((gap) => <li key={`${gap.period}:${gap.code}`}>{gap.period}: {gapReason(gap.code)}</li>)}</ul>
    </details>
  ) : null;

  const openPassport = React.useCallback((field, period) => {
    if (!ticker) return;
    setPassportTarget({ field, period });
    setPassport(null);
    setPassportLoading(true);
    const params = new URLSearchParams({ period, field, form: standard });
    if (standard === "MSFO" && scope) params.set("scope", scope);
    fetch(`/api/company/${encodeURIComponent(ticker)}/financials/passport?${params.toString()}`)
      .then((response) => response.json())
      .then((body) => setPassport(body?.ok ? body : { status: "NO_SOURCE_PASSPORT" }))
      .catch(() => setPassport({ status: "NO_SOURCE_PASSPORT", reason: t("Не удалось загрузить паспорт источника.", "Manba pasportini yuklab bo‘lmadi.", "The source passport could not be loaded.") }))
      .finally(() => setPassportLoading(false));
  }, [ticker, standard, scope, t]);

  const standardToggle = onStandardChange ? (
    <div className="fin-freq" role="group" aria-label={t("Стандарт", "Standart", "Standard")}>
      {[["NSBU", "НСБУ"], ["MSFO", "МСФО"]].map(([code, label]) => (
        <button key={code} type="button" className={`fin-freq-btn ${standard === code ? "active" : ""}`}
          aria-pressed={standard === code} onClick={() => onStandardChange(code)}>{label}</button>
      ))}
    </div>
  ) : null;

  const scopeToggle = standard === "MSFO" && onScopeChange ? (
    <div className="fin-freq" role="group" aria-label={t("Периметр отчётности", "Hisobot qamrovi", "Accounting scope")}>
      {[["consolidated", t("Группа", "Guruh", "Consolidated group")],
        ["separate", t("Отдельная компания", "Alohida kompaniya", "Separate entity")]].map(([code, label]) => (
        <button key={code} type="button" className={`fin-freq-btn ${scope === code ? "active" : ""}`}
          aria-pressed={scope === code} onClick={() => onScopeChange(code)}>{label}</button>
      ))}
    </div>
  ) : null;

  // Годовые | Квартальные. The switch stays on screen in every state —
  // including "this issuer files no quarterlies" — or there is no way back.
  const freqToggle = onFreqChange ? (
    <div className="fin-freq" role="group" aria-label={t("Период", "Davr", "Period")}>
      {[["annual", t("Годовые", "Yillik", "Annual")],
        ["quarterly", t("Квартальные", "Choraklik", "Quarterly")]].map(([k, label]) => (
        <button key={k} type="button"
          className={`fin-freq-btn ${freq === k ? "active" : ""}`}
          onClick={() => onFreqChange(k)}>{label}</button>
      ))}
    </div>
  ) : null;

  if (loading) return (
    <div className="company-financials">
      <div className="fin-subtabs">{standardToggle}{scopeToggle}{freqToggle}</div>
      <div className="chart-loading muted">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</div>
    </div>
  );

  // The server sends newest-first; the table reads oldest → newest, left → right.
  const cols = [...(periods || [])].reverse();
  const has = (f) => series?.[f] && cols.some((p) => Number.isFinite(series[f].values[p]));
  const sections = standard === "MSFO" && has("interest_income")
    ? FIN_SECTIONS.map((sec) => sec.key === "income" ? { ...sec,
      rows: ["interest_income", "interest_expense", "operating_income", "operating_expenses", "net_profit"],
      margins: [], chart: ["interest_income", "operating_income", "net_profit"],
    } : sec) : (quarterly ? FIN_SECTIONS_QUARTER : FIN_SECTIONS);
  const available = sections
    .map((sec) => ({ ...sec, rows: (sec.rows || []).filter(has), margins: (sec.margins || []).filter(has) }))
    .filter((sec) => sec.rows.length + sec.margins.length > 0);

  // 66 of ~110 issuers file quarterlies; for the rest this view is honestly
  // empty. The annual fallback below must not answer for it — a reader who
  // asked for quarters and got a single year's ratios would take them for one.
  if (available.length === 0 && quarterly) {
    return (
      <div className="company-financials">
        <div className="fin-subtabs">{standardToggle}{scopeToggle}{freqToggle}</div>
        <div className="panel" style={{ padding: 32, textAlign: "center" }}>
          <p className="muted">{t("Квартальные финансовые данные пока недоступны. Опубликованные документы можно проверить во вкладке «Отчётность».",
                                  "Choraklik moliyaviy ma'lumotlar hozircha mavjud emas. E'lon qilingan hujjatlarni Hisobotlar bo‘limida tekshiring.",
                                  "Quarterly figures are not available yet. Check the Reports tab for published documents.")}</p>
          {gapNotice}
        </div>
      </div>
    );
  }

  // Nothing in the fact store.  The legacy ratios cache has no reliable
  // accounting-standard dimension, so it is a NSBU-only fallback.  Reusing it
  // while the reader selected IFRS would put a familiar number under a false
  // label — the exact cross-standard substitution the product prohibits.
  if (available.length === 0) {
    if (standard !== "NSBU") return (
      <div className="company-financials">
        <div className="fin-subtabs">{standardToggle}{scopeToggle}{freqToggle}</div>
        <div className="panel" style={{ padding: 32, textAlign: "center" }}>
          <p className="muted">{t("Для выбранного периметра проверенные показатели по МСФО пока недоступны. Опубликованные документы можно открыть во вкладке «Отчётность».",
                                  "Tanlangan qamrov uchun tekshirilgan MHXS ko‘rsatkichlari hali mavjud emas. E'lon qilingan hujjatlarni Hisobotlar bo‘limida oching.",
                                  "Reviewed IFRS figures are not yet available for this accounting scope. Published documents can be opened in the Reports tab.")}</p>
          {gapNotice}
        </div>
      </div>
    );
    const m = ratios?.metrics || {};
    const legacy = [["ROA", "ROA"], ["ROE", "ROE"],
                    ["net_margin", finLabel("net_profit_margin", lang)],
                    ["debt_ratio", finLabel("debt_ratio", lang)],
                    ["debt_to_equity", finLabel("debt_to_equity", lang)]]
      .filter(([k]) => m[k] != null);
    if (legacy.length === 0) return (
      <div className="company-financials">
        <div className="fin-subtabs">{standardToggle}{scopeToggle}{freqToggle}</div>
        <div className="panel" style={{ padding: 32, textAlign: "center" }}>
          <p className="muted">{t("Финансовые показатели пока недоступны",
                                  "Moliyaviy ko‘rsatkichlar hozircha mavjud emas",
                                  "Financial figures are not available yet")}</p>
        </div>
      </div>
    );
    return (
      <div className="company-financials">
        <div className="fin-subtabs">{standardToggle}{scopeToggle}{freqToggle}</div>
        <div className="panel" style={{ padding: "16px 20px" }}>
          {ratios?.year && (
            <div className="muted" style={{ marginBottom: 12, fontSize: 13 }}>
              {t("Последние данные", "Songgi malumotlar", "Latest")}: {ratios.year}
              {ratios.quarter ? ` Q${ratios.quarter}` : ""}
            </div>
          )}
          <div className="company-metrics-list">
            {legacy.map(([k, l]) => (
              <div key={k} className="company-metric-row">
                <span className="panel-label">{l}</span>
                <span className="company-metric-val">{formatRatio(m[k], 2, lang)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  const active = available.find((sec) => sec.key === section) || available[0];

  // Every row of the active section is a candidate line — the list is built
  // from the section's rows, so a field added to FIN_SECTIONS later is
  // clickable with no further wiring. Colours are keyed to this canonical
  // order: toggling one line must not repaint the rest.
  const sectionFields = [...(active.rows || []), ...(active.margins || [])];
  const colorOf = (f) =>
    FIN_CHART_COLORS[Math.max(0, sectionFields.indexOf(f)) % FIN_CHART_COLORS.length];
  const defaultChart = (active.chart || []).filter(has);
  const selected = (chartSel[active.key] || defaultChart)
    .filter((f) => sectionFields.includes(f) && has(f));
  const chartFields = sectionFields.filter((f) => selected.includes(f));
  const toggleChartField = (f) => {
    if (!has(f)) return;
    setChartSel((prev) => {
      const cur = prev[active.key] || defaultChart;
      // Sums and coefficients cannot share an axis — a billion-сум revenue
      // line flattens ROE into the baseline. Adding a line from the other
      // register keeps only the rows it can honestly be drawn beside.
      const next = cur.includes(f)
        ? cur.filter((x) => x !== f)
        : [...cur.filter((x) => !!series[x]?.money === !!series[f]?.money), f];
      return { ...prev, [active.key]: next };
    });
  };

  // Years the issuer filed nothing for, between the oldest and newest it did.
  const yearNums = cols.map((p) => Number(p)).filter((n) => Number.isFinite(n));
  const missingYears = yearNums.length > 1
    ? Array.from({ length: Math.max(...yearNums) - Math.min(...yearNums) + 1 },
                 (_, i) => Math.min(...yearNums) + i)
        .filter((y) => !yearNums.includes(y))
    : [];

  // «Рост г/г» has to be year OVER YEAR, and on this market the column to the
  // left is often not last year. 53 of 100 issuers have a hole in their annual
  // series — AGBA is missing 2019, BECM is missing 2019, 2021 AND 2023 — and the
  // row happily compared 2020 with 2018 and called it a year. A two-year change
  // labelled as one is the kind of figure a reader takes to a valuation.
  //
  // So a gap yields a dash, and the dash says which year is missing. The value
  // is not lost: both columns are on screen, and a reader who wants the two-year
  // change can see both numbers. What is gone is the wrong label.
  const yearOf = (p) => (/^\d{4}$/.test(String(p)) ? Number(p) : null);
  const growth = (f, i) => {
    // Quarters compare with the SAME quarter a year earlier — the standard
    // comparison, because Q4 against Q3 measures the season, not the business.
    // The base is looked up by key, not by the column to the left, so a hole
    // in the filings yields a dash instead of a mislabelled change.
    if (quarterly) {
      const pq = parseQPeriod(cols[i]);
      if (!pq) return null;
      const v = series[f].values[cols[i]];
      const prev = series[f].values[`${pq.y - 1}Q${pq.q}`];
      if (!Number.isFinite(v) || !Number.isFinite(prev) || prev === 0) return null;
      return { value: ((v - prev) / Math.abs(prev)) * 100 };
    }
    const v = series[f].values[cols[i]], prev = series[f].values[cols[i - 1]];
    const y = yearOf(cols[i]), yPrev = yearOf(cols[i - 1]);
    if (y != null && yPrev != null && y - yPrev !== 1) {
      return { gap: true, missing: y - yPrev === 2 ? `${y - 1}` : `${yPrev + 1}–${y - 1}` };
    }
    if (!Number.isFinite(v) || !Number.isFinite(prev) || prev === 0) return null;
    return { value: ((v - prev) / Math.abs(prev)) * 100 };
  };
  // The secondary convention, quarterly only: against the PREVIOUS quarter
  // (Q1's predecessor is last year's Q4). Also keyed, never the neighbouring
  // column, for the same reason as above.
  const growthQoQ = (f, i) => {
    const pq = parseQPeriod(cols[i]);
    if (!pq) return null;
    const prevKey = pq.q === 1 ? `${pq.y - 1}Q4` : `${pq.y}Q${pq.q - 1}`;
    const v = series[f].values[cols[i]], prev = series[f].values[prevKey];
    if (!Number.isFinite(v) || !Number.isFinite(prev) || prev === 0) return null;
    return { value: ((v - prev) / Math.abs(prev)) * 100 };
  };
  // The unit comes from the server, which owns the scale contract: money in
  // full UZS, every margin already converted to percent, plain coefficients
  // left alone. Nothing here decides what a number means.
  //
  // Sums print in full, not «3,1B»: the wrap scrolls sideways, so a long number
  // cannot break the layout — a bank's trillions just make the table wider.
  // The chart keeps compact figures: its axis has 70px, not a column.
  const fmtFull = new Intl.NumberFormat(lang === "en" ? "en-US" : "ru-RU",
                                        { maximumFractionDigits: 0 });
  const cell = (f, p) => {
    const v = series[f].values[p];
    if (!Number.isFinite(v)) return "—";
    if (series[f].money) return fmtFull.format(v);
    const suffix = series[f].unit === "%" ? "%" : "";
    return `${formatRatio(v, 2, lang)}${suffix}`;
  };

  const rowsBlock = (fields, withGrowth) => fields.map((f) => (
    <React.Fragment key={f}>
      <tr>
        <th scope="row">
          <button type="button"
            className={`fin-row-toggle ${selected.includes(f) ? "on" : ""}`}
            aria-pressed={selected.includes(f)}
            onClick={() => toggleChartField(f)}
            title={selected.includes(f)
              ? t("Убрать с графика", "Grafikdan olib tashlash", "Remove from chart")
              : t("Показать на графике", "Grafikda korsatish", "Show on chart")}>
            <i className="fin-row-dot"
              style={selected.includes(f) ? { background: colorOf(f) } : undefined} />
            {finLabel(f, lang)}
          </button>
          {/* Beside the label, not inside the toggle: the row header is already
              a button (it draws the line on the chart), and a button inside a
              button is invalid markup — the ⓘ would put a line on the chart
              instead of explaining the term. */}
          <TermInfo termId={FIN_FIELD_TERMS[f]} lang={lang} label={finLabel(f, lang)} />
        </th>
        {cols.map((p) => {
          const value = series[f].values[p];
          if (!Number.isFinite(value)) {
            const gap = dataGaps.find((item) => item.period === p && (!item.field || item.field === f));
            return <td key={p} className="num" title={gapReason(gap?.code)}>—</td>;
          }
          return (
            <td key={p} className="num fin-passport-cell">
              <button type="button" onClick={() => openPassport(f, p)}
                title={t("Открыть паспорт источника", "Manba pasportini ochish", "Open source passport")}>
                {cell(f, p)}
              </button>
            </td>
          );
        })}
      </tr>
      {/* Only when there is a year to compare against: on a single-period
          issuer (ACMT1B2, UZNF and seven more) this row was a line of dashes
          under a heading promising growth. */}
      {withGrowth && cols.length > 1 && (
        <tr className="fin-growth">
          <th scope="row">{t("Рост г/г", "Osish y/y", "Growth YoY")}</th>
          {cols.map((p, i) => {
            const g = growth(f, i);
            const v = g && !g.gap ? g.value : null;
            return (
              <td key={p} className={`num ${v == null ? "" : v >= 0 ? "pos" : "neg"}`}
                title={g && g.gap
                  ? t(`Нет отчёта за ${g.missing} — рост за год не посчитать`,
                      `${g.missing} uchun hisobot yo'q`,
                      `No filing for ${g.missing} — a year-on-year change cannot be formed`)
                  : undefined}>
                {v == null ? "—" : `${signedFixed(v)}%`}
              </td>
            );
          })}
        </tr>
      )}
      {withGrowth && quarterly && periodBasis !== "cumulative_ytd" && cols.length > 1 && (
        <tr className="fin-growth">
          <th scope="row">{t("Рост кв/кв", "Osish ch/ch", "Growth QoQ")}</th>
          {cols.map((p, i) => {
            const g = growthQoQ(f, i);
            const v = g ? g.value : null;
            return (
              <td key={p} className={`num ${v == null ? "" : v >= 0 ? "pos" : "neg"}`}>
                {v == null ? "—" : `${signedFixed(v)}%`}
              </td>
            );
          })}
        </tr>
      )}
    </React.Fragment>
  ));

  return (
    <div className="company-financials">
      {periodBasis === "cumulative_ytd" && <p className="muted">{t("МСФО: доходы и расходы — нарастающим итогом с января, не за отдельные три месяца.", "MHXS: daromad va xarajatlar yanvardan jamlangan, alohida uch oy uchun emas.", "IFRS: income and expenses are cumulative from January, not standalone three-month figures.")}</p>}
      <div className="fin-subtabs">
        {available.map((sec) => (
          <button key={sec.key} type="button"
            className={`fin-subtab ${section !== "splits" && active.key === sec.key ? "active" : ""}`}
            onClick={() => setSection(sec.key)}>
            {sec.label[lang === "uz" ? 1 : lang === "en" ? 2 : 0]}
          </button>
        ))}
        {/* «Сплиты» is always on the bar, as uzse.uz always shows the link:
            for most securities its content is honestly «не зафиксировано»,
            and hiding the tab would make the seven that DID split look like
            the only ones anyone checked. */}
        <button type="button"
          className={`fin-subtab ${section === "splits" ? "active" : ""}`}
          onClick={() => setSection("splits")}>
          {t("Сплиты", "Splitlar", "Splits")}
        </button>
        {section !== "splits" && (
          <>
        {standardToggle}
        {scopeToggle}
        {freqToggle}
            {/* Line | Bars | Table. Sits with the period switch because it answers
                the same kind of question — how to READ this section, not which
                section — and the two are the only controls this tab has. Neither
                applies to the splits register, so both leave the bar with it. */}
            <div className="fin-freq fin-dash" role="group"
              aria-label={t("Вид", "Ko'rinish", "View")}>
              {FIN_DASHBOARDS.map((d) => (
                <button key={d.key} type="button"
                  className={`fin-freq-btn ${dashboard === d.key ? "active" : ""}`}
                  aria-pressed={dashboard === d.key}
                  onClick={() => setDashboard(d.key)}>
                  {d.label[lang === "uz" ? 1 : lang === "en" ? 2 : 0]}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      {section !== "splits" && gapNotice}
      {section === "splits" ? (
        <CompanySplitsTable items={splits === undefined ? null : splits} lang={lang} />
      ) : (
      <div className="panel fin-panel">
        {dashboard !== "table" && (
          <>
            {/* In a chart view the table is not on screen, so its row headers
                cannot be what picks the lines. Every row of the section is a
                chip here: the legend below the chart can only take a line away,
                and a reader who has switched them all off would otherwise be
                looking at an empty frame with no way back. */}
            <div className="fin-picker">
              {sectionFields.filter(has).map((f) => (
                <button key={f} type="button"
                  className={`fin-picker-chip ${selected.includes(f) ? "on" : ""}`}
                  aria-pressed={selected.includes(f)}
                  onClick={() => toggleChartField(f)}>
                  <i style={selected.includes(f) ? { background: colorOf(f) } : undefined} />
                  {finLabel(f, lang)}
                </button>
              ))}
            </div>
            {dashboard === "bar"
              ? <FinancialsBars fields={chartFields} series={series} periods={cols} lang={lang}
                  colorOf={colorOf} onToggle={toggleChartField} />
              : <FinancialsChart fields={chartFields} series={series} periods={cols} lang={lang}
                  colorOf={colorOf} onToggle={toggleChartField} />}
            {dashboard === "line" && cols.length === 1 && chartFields.length > 0 && (
              <p className="fin-note muted" style={{ textAlign: "center" }}>
                {t("Линейный график появится, когда будет как минимум два отчётных периода. Сейчас доступен 1 период — его можно посмотреть в таблице или на столбчатом графике.",
                   "Chiziqli grafik kamida ikki hisobot davri bo'lganda paydo bo'ladi. Hozir 1 davr mavjud — uni jadvalda yoki ustunli grafikda ko'ring.",
                   "A line chart needs at least two reporting periods. One period is currently available; view it in the table or bar chart.")}
              </p>
            )}
            {chartFields.length === 0 && (
              <p className="fin-note muted" style={{ textAlign: "center" }}>
                {t("Выберите показатель выше, чтобы построить график",
                   "Grafik uchun yuqoridan ko'rsatkich tanlang",
                   "Pick an indicator above to draw the chart")}
              </p>
            )}
          </>
        )}

        {dashboard === "table" && (
        <div className="fin-table-wrap">
          <table className="fin-table">
            <thead>
              <tr>
                <th scope="col">{quarterly
                  ? t("Квартальные данные", "Choraklik malumotlar", "Fiscal quarter")
                  : t("Годовые данные", "Yillik malumotlar", "Fiscal year")}</th>
                {cols.map((p) => <th key={p} scope="col" className="num">{finPeriodLabel(p)}</th>)}
              </tr>
            </thead>
            <tbody>
              {rowsBlock(active.rows || [], true)}
              {(active.margins || []).length > 0 && (active.rows || []).length > 0 && (
                <tr className="fin-section-row">
                  <th scope="row" colSpan={cols.length + 1}>
                    {t("Маржинальность", "Marjinallik", "Margin Analysis")}
                  </th>
                </tr>
              )}
              {rowsBlock(active.margins || [], false)}
            </tbody>
          </table>
        </div>
        )}

        <p className="fin-note muted">
          {periodBasis === "cumulative_ytd"
            ? t("Суммы в сумах по промежуточной отчётности МСФО. Доходы и расходы — с начала года; активы, обязательства и капитал — на отчётную дату. Рост г/г сравнивает одинаковую длительность периода.",
                "Summalar so‘mda, MHXS oraliq hisobotlaridan. Daromad va xarajatlar yil boshidan jamlangan; aktivlar, majburiyatlar va kapital hisobot sanasiga. Yillik o‘sish bir xil davomiylikdagi davrlarni taqqoslaydi.",
                "Sums in UZS from interim IFRS filings. Income and expenses are year-to-date; assets, liabilities and equity are at the reporting date. YoY growth compares periods of equal duration.")
            : quarterly
            ? t("Суммы в сумах, за отдельный квартал (3 месяца) — рассчитаны из накопительных квартальных отчётов НСБУ; IV квартал — разница годового и девятимесячного отчётов. Рост г/г — к тому же кварталу прошлого года, кв/кв — к предыдущему кварталу. Активы, обязательства и капитал — на конец квартала.",
                "Summalar somda, alohida chorak (3 oy) uchun — NSBU choraklik hisobotlaridan hisoblangan; IV chorak — yillik va 9 oylik hisobotlar farqi. Osish y/y — otgan yilning shu chorogiga, ch/ch — oldingi chorakka nisbatan. Aktivlar, majburiyatlar va kapital — chorak oxiriga.",
                "Sums in UZS per discrete quarter (3 months), derived from the cumulative NSBU filings; Q4 is the annual less the nine-month filing. Growth YoY compares the same quarter a year earlier, QoQ the preceding quarter. Assets, liabilities and equity are quarter-end snapshots.")
            : t("Суммы в сумах, по годовым отчётам эмитента. Коэффициенты — в тех единицах, в которых они опубликованы.",
                "Summalar somda, emitentning yillik hisobotlari boyicha.",
                "Sums in UZS, from the issuer's annual filings. Ratios in the units they were published in.")}
          {/* Said once, under the table, rather than left for the reader to
              notice that 2019 is simply not there. Half the issuers on this
              market have at least one such hole. */}
          {!quarterly && missingYears.length > 0 && (
            <> {t(`За ${missingYears.join(", ")} годовые данные недоступны — рост к этим годам не рассчитывается.`,
                  `${missingYears.join(", ")} uchun yillik ma'lumotlar mavjud emas; bu yillarga nisbatan o‘sish hisoblanmaydi.`,
                  `Annual figures are unavailable for ${missingYears.join(", ")} — growth against those years is not calculated.`)}</>
          )}
        </p>
      </div>
      )}
      {passportTarget && (
        <FinancialPassportDialog passport={passport} loading={passportLoading}
          field={passportTarget.field} period={passportTarget.period} lang={lang}
          onClose={() => { setPassportTarget(null); setPassport(null); }} />
      )}
    </div>
  );
}

function CompanyDividendsTab({ items, loading, lang, isPreferred, lastPrice }) {
  // openinfo's calendar also carries decisions that declared nothing — Aloqabank
  // files four of them dated 11.06.2013 alone, and they render as rows of dashes
  // that read like a broken table. They stay available behind the toggle, because
  // "the meeting resolved to pay nothing" is an answer to the question the tab asks.
  const [showSilent, setShowSilent] = React.useState(false);
  const t = React.useCallback((ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru), [lang]);
  const locale = lang === "en" ? "en-US" : "ru-RU";
  const fmt = (v) => v == null ? "—" : Number(v).toLocaleString(locale, { maximumFractionDigits: 2 });
  const fmtDate = (d) => d ? new Date(d).toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" }) : "—";

  if (loading) return <div className="chart-loading muted">{t("Загрузка...", "Yuklanmoqda...", "Loading...")}</div>;
  const rows = items || [];
  if (rows.length === 0) return (
    <div className="panel" style={{ padding: 32, textAlign: "center" }}>
      <p className="muted">{t("Дивиденды не объявлялись", "Dividendlar e'lon qilinmagan", "No dividends on record")}</p>
    </div>
  );

  // Same rule as the key-stats rail — see dividendSummary().
  const { latest, latestAmt, yieldPct, declared, payouts, latestYear, latestIsRecent } =
    dividendSummary(rows, { isPreferred, lastPrice });
  // O'zsanoatqurilishbank files 92 calendar entries and declared a payout in 9 of
  // them. When an issuer declared nothing at all there is nothing to fold away —
  // the silent filings ARE the record, so they stay on screen.
  const silent = payouts === 0 ? 0 : rows.length - payouts;
  const visible = (showSilent || payouts === 0) ? rows : declared;

  return (
    <div className="company-dividends">
      <div className="dividend-cards">
        <div className="dividend-card panel">
          <div className="dividend-card-label">{t("Последний дивиденд", "Oxirgi dividend", "Latest dividend")}</div>
          <div className="dividend-card-val">{fmt(latestAmt)} <span className="dividend-card-unit">{t("сум/акц.", "so'm/aksiya", "UZS/sh")}</span></div>
          {latest && <div className="muted" style={{ fontSize: 12 }}>{fmtDate(latest.decision_date)}</div>}
        </div>
        {yieldPct != null && (
          <div className="dividend-card panel">
            <div className="dividend-card-label">{t("Дивидендная доходность", "Dividend daromadliligi", "Dividend yield")}</div>
            <div className="dividend-card-val">{yieldPct.toFixed(2)}%</div>
            {/* The last payout is not always a recent one: SQBN's ordinary line was
                last paid in 2019 while its preferred line still pays every year. A
                bare "к текущей цене" then reads as this year's yield, so the caption
                names the year the figure actually comes from. */}
            <div className="muted" style={{ fontSize: 12 }}>
              {latestYear && !latestIsRecent
                ? t(`по выплате ${latestYear} г. к текущей цене`, `${latestYear}-yil to'lovi bo'yicha`, `on the ${latestYear} payout, at the current price`)
                : t("к текущей цене", "joriy narxga", "to current price")}
            </div>
          </div>
        )}
        <div className="dividend-card panel">
          <div className="dividend-card-label">{t("Выплат в истории", "Tarixdagi to'lovlar", "Payouts on record")}</div>
          <div className="dividend-card-val">{payouts}</div>
        </div>
      </div>
      <div className="dividend-table-wrap panel">
        <table className="dividend-table">
          <thead>
            <tr>
              <th>{t("Дата решения", "Qaror sanasi", "Decision date")}</th>
              <th className="dividend-num">{t("Обыкн., сум", "Oddiy, so'm", "Ordinary, UZS")}</th>
              <th className="dividend-num">%</th>
              <th className="dividend-num">{t("Прив., сум", "Imtiyozli, so'm", "Preferred, UZS")}</th>
              <th className="dividend-num">%</th>
              <th>{t("Реестр / выплата", "Reyestr / to'lov", "Record / payment")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r, i) => (
              <tr key={i}>
                <td>{fmtDate(r.decision_date)}</td>
                <td className="dividend-num">{r.ordinary_amount ? fmt(r.ordinary_amount) : "—"}</td>
                <td className="dividend-num muted">{r.ordinary_percent ? `${fmt(r.ordinary_percent)}%` : "—"}</td>
                <td className="dividend-num">{r.preferred_amount ? fmt(r.preferred_amount) : "—"}</td>
                <td className="dividend-num muted">{r.preferred_percent ? `${fmt(r.preferred_percent)}%` : "—"}</td>
                {/* The payment window belongs to the share class being viewed: a
                    filing declares a separate one for the preferred line, and a
                    preferred page showing the ordinary window dates the wrong payout. */}
                <td className="muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>{(() => {
                  const start = isPreferred ? (r.preferred_start || r.ordinary_start) : r.ordinary_start;
                  const end = isPreferred ? (r.preferred_end || r.ordinary_end) : r.ordinary_end;
                  return (start || end) ? `${fmtDate(start)} – ${fmtDate(end)}` : "—";
                })()}</td>
                <td>{r.link && <a href={r.link} target="_blank" rel="noreferrer" className="ghost-btn" style={{ fontSize: 12 }}>→</a>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {silent > 0 && (
        <button type="button" className="ghost-btn" style={{ fontSize: 12, marginTop: 10 }}
                onClick={() => setShowSilent((v) => !v)}>
          {showSilent
            ? t("Скрыть решения без выплаты", "To'lovsiz qarorlarni yashirish", "Hide no-payout decisions")
            : t(`Показать ещё ${silent} решений без выплаты`, `Yana ${silent} ta to'lovsiz qaror`, `Show ${silent} more no-payout decisions`)}
        </button>
      )}
      {yieldPct != null && (
        <p className="muted" style={{ fontSize: 11, marginTop: 10 }}>
          {t("Доходность рассчитана по последней цене и без учёта даты закрытия реестра.", "Daromadlilik oxirgi narx bo'yicha hisoblangan.", "Yield is computed against the latest price, before the record date.")}
        </p>
      )}
    </div>
  );
}

export { CompanyDividendsTab, CompanyFinancialsTab };
