import React, { useEffect, useState } from "react";
import { formatCatalogDate } from "../../shared/format.jsx";
import { TEXTS, clg, normalizeLanguage } from "../../shared/i18n.jsx";
import { TermInfo } from "../../shared/TermInfo.jsx";
import { STORAGE_KEY } from "../../shared/sessionKeys.jsx";
import { orderSectors } from "../../lib/sectors.js";
import { sectorLabel } from "../../shared/marketCopy.jsx";
import { SectionCard, StructuredReportBlocks, getSectionTitle } from "../../shared/ReportDocument.jsx";
import { formatMarketTimestamp } from "../../shared/marketModel.jsx";
import { CompanyLogo } from "../../shared/CompanyLogo.jsx";

// ---------------------------------------------------------------------------
// CatalogView helpers
// ---------------------------------------------------------------------------

function PriceSparkline({ points, language }) {
  const [activeIndex, setActiveIndex] = useState(null);
  if (!points || points.length < 2) return null;
  // The stored endpoint can contain rows in either query order. A chart must
  // always read from the earlier session to the later one; otherwise both the
  // line and its date caption tell the story backwards.
  const ordered = points
    .filter((p) => p?.close != null && p.close > 0)
    .slice()
    .sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")));
  const closes = ordered.map((p) => Number(p.close));
  if (closes.length < 2) return null;
  const W = 360, H = 82, PAD = 5;
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const xs = closes.map((_, i) => PAD + (i / (closes.length - 1)) * (W - PAD * 2));
  const ys = closes.map((v) => PAD + (1 - (v - min) / range) * (H - PAD * 2));
  const polyline = xs.map((x, i) => `${x},${ys[i]}`).join(" ");
  const areaPath = `M${xs[0]},${H} ` + xs.map((x, i) => `L${x},${ys[i]}`).join(" ") + ` L${xs[xs.length - 1]},${H} Z`;
  const first = closes[0], last = closes[closes.length - 1];
  const pct = ((last - first) / first * 100).toFixed(1);
  const tone = last >= first ? "pos" : "neg";
  const firstDate = ordered[0]?.date;
  const lastDate = ordered[ordered.length - 1]?.date;
  const inspectedIndex = activeIndex == null
    ? null
    : Math.max(0, Math.min(activeIndex, ordered.length - 1));
  const inspectedPoint = inspectedIndex == null ? null : ordered[inspectedIndex];
  const inspectedClose = inspectedIndex == null ? null : closes[inspectedIndex];
  const previousClose = inspectedIndex > 0 ? closes[inspectedIndex - 1] : null;
  const sessionChange = previousClose
    ? ((inspectedClose - previousClose) / previousClose) * 100
    : null;
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-UZ" : "ru-RU";
  const chartLabel = language === "en"
    ? "Interactive price chart. Use the left and right arrow keys to inspect trading sessions."
    : language === "uz"
      ? "Interaktiv narx grafigi. Savdo sessiyalarini ko‘rish uchun chap va o‘ng tugmalardan foydalaning."
      : "Интерактивный график цены. Используйте стрелки влево и вправо для просмотра торговых сессий.";
  const sessionLabel = language === "en"
    ? "vs previous session"
    : language === "uz"
      ? "oldingi sessiyaga nisbatan"
      : "к предыдущей сессии";

  const inspectAtPointer = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    if (!bounds.width) return;
    const ratio = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
    setActiveIndex(Math.floor((ratio * (ordered.length - 1)) + 0.5));
  };

  const inspectWithKeyboard = (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    setActiveIndex((current) => {
      if (event.key === "Home") return 0;
      if (event.key === "End") return ordered.length - 1;
      const start = current == null ? ordered.length - 1 : current;
      return Math.max(0, Math.min(
        ordered.length - 1,
        start + (event.key === "ArrowLeft" ? -1 : 1),
      ));
    });
  };

  return (
    <div className="catalog-sparkline">
      <div className="catalog-sparkline-meta">
        <span className="catalog-sparkline-price">{last.toLocaleString(language === "en" ? "en-US" : "ru-RU")} сум</span>
        <span className={`catalog-sparkline-change ${tone}`}>{tone === "pos" ? "+" : ""}{pct}%</span>
        <span className="catalog-sparkline-period muted">{firstDate} – {lastDate}</span>
      </div>
      <div
        className="catalog-sparkline-chart"
        role="group"
        tabIndex={0}
        aria-label={chartLabel}
        onPointerMove={inspectAtPointer}
        onPointerDown={inspectAtPointer}
        onPointerLeave={() => setActiveIndex(null)}
        onPointerCancel={() => setActiveIndex(null)}
        onFocus={() => setActiveIndex((current) => current ?? ordered.length - 1)}
        onBlur={() => setActiveIndex(null)}
        onKeyDown={inspectWithKeyboard}
      >
        <svg viewBox={`0 0 ${W} ${H}`} className="catalog-sparkline-svg" preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <linearGradient id="catalog-spk-grad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--catalog-accent)" stopOpacity="0.3" />
              <stop offset="100%" stopColor="var(--catalog-accent)" stopOpacity="0.01" />
            </linearGradient>
          </defs>
          <path d={areaPath} fill="url(#catalog-spk-grad)" />
          <polyline points={polyline} fill="none" stroke="var(--catalog-accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          {inspectedIndex != null && (
            <>
              <line
                className="catalog-sparkline-guide"
                x1={xs[inspectedIndex]}
                y1={PAD}
                x2={xs[inspectedIndex]}
                y2={H}
              />
              <circle
                className="catalog-sparkline-active-dot"
                cx={xs[inspectedIndex]}
                cy={ys[inspectedIndex]}
                r="4"
              />
            </>
          )}
        </svg>
        {inspectedPoint && (
          <div
            className="catalog-sparkline-tooltip"
            role="tooltip"
            style={{ "--catalog-hover-x": `${(xs[inspectedIndex] / W) * 100}%` }}
          >
            <span>{formatCatalogDate(inspectedPoint.date, language)}</span>
            <strong>{inspectedClose.toLocaleString(locale)} сум</strong>
            {sessionChange != null && (
              <em className={sessionChange >= 0 ? "pos" : "neg"}>
                {sessionChange >= 0 ? "+" : ""}{sessionChange.toFixed(2)}% {sessionLabel}
              </em>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function CatalogFilterSelect({ value, onChange, options, label, className = "" }) {
  const [open, setOpen] = useState(false);
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));
  const [activeIndex, setActiveIndex] = useState(selectedIndex);
  const listboxId = React.useId();
  const selectedOption = options[selectedIndex] || options[0];

  useEffect(() => {
    setActiveIndex(selectedIndex);
  }, [selectedIndex]);

  const choose = (index) => {
    const option = options[index];
    if (!option) return;
    onChange(option.value);
    setActiveIndex(index);
    setOpen(false);
  };

  const handleKeyDown = (event) => {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) => {
        if (event.key === "Home") return 0;
        if (event.key === "End") return options.length - 1;
        const direction = event.key === "ArrowDown" ? 1 : -1;
        return Math.max(0, Math.min(options.length - 1, current + direction));
      });
      return;
    }
    if ((event.key === "Enter" || event.key === " ") && open) {
      event.preventDefault();
      choose(activeIndex);
    }
  };

  return (
    <div
      className={`catalog-filter-control ${open ? "is-open" : ""} ${className}`.trim()}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <button
        className="catalog-filter-trigger"
        type="button"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={handleKeyDown}
      >
        <span>{selectedOption?.label || label}</span>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
      </button>
      {open && (
        <div className="catalog-filter-menu" id={listboxId} role="listbox" aria-label={label}>
          {options.map((option, index) => (
            <button
              key={option.value}
              className={`${index === activeIndex ? "is-highlighted" : ""} ${option.value === value ? "is-selected" : ""}`.trim()}
              type="button"
              role="option"
              aria-selected={option.value === value}
              onMouseEnter={() => setActiveIndex(index)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(index)}
            >
              <span>{option.label}</span>
              {option.value === value && (
                <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7" /></svg>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const CATALOG_TERMINAL_TEXT = {
  ru: {
    eyebrow: "Раскрытие и финансовая отчётность",
    heading: "Каталог эмитентов",
    allSectors: "Все отрасли",
    allForms: "Все типы отчётов",
    allYears: "Все годы",
    results: "результатов",
    issuers: "Эмитенты",
    reports: "Финансовые отчёты",
    newest: "Сначала новые",
    period: "Период",
    type: "Тип",
    status: "Статус",
    published: "Опубликован",
    source: "Источник",
    file: "Файл",
    available: "Доступен",
    selected: "Выбранный отчёт",
    analyze: "Анализировать отчёт",
    latest: "Последний отчёт",
    tickers: "Тикеры",
    chart: "Динамика цены",
    noChart: "Для этой бумаги пока нет истории торгов",
    noFilteredReports: "По выбранным фильтрам отчётов нет",
    annualDetail: "12 месяцев",
    quarterDetail: (q) => `${q * 3} месяцев`,
  },
  en: {
    eyebrow: "Disclosures and financial reporting",
    heading: "Issuer catalog",
    allSectors: "All sectors",
    allForms: "All report types",
    allYears: "All years",
    results: "results",
    issuers: "Issuers",
    reports: "Financial reports",
    newest: "Newest first",
    period: "Period",
    type: "Type",
    status: "Status",
    published: "Published",
    source: "Source",
    file: "File",
    available: "Available",
    selected: "Selected report",
    analyze: "Analyze report",
    latest: "Latest report",
    tickers: "Tickers",
    chart: "Price history",
    noChart: "No trading history is available for this security yet",
    noFilteredReports: "No reports match the selected filters",
    annualDetail: "12 months",
    quarterDetail: (q) => `${q * 3} months`,
  },
  uz: {
    eyebrow: "Oshkorotlar va moliyaviy hisobotlar",
    heading: "Emitentlar katalogi",
    allSectors: "Barcha tarmoqlar",
    allForms: "Barcha hisobot turlari",
    allYears: "Barcha yillar",
    results: "natija",
    issuers: "Emitentlar",
    reports: "Moliyaviy hisobotlar",
    newest: "Yangilari avval",
    period: "Davr",
    type: "Turi",
    status: "Holati",
    published: "E'lon qilingan",
    source: "Manba",
    file: "Fayl",
    available: "Mavjud",
    selected: "Tanlangan hisobot",
    analyze: "Hisobotni tahlil qilish",
    latest: "So'nggi hisobot",
    tickers: "Tikerlar",
    chart: "Narx dinamikasi",
    noChart: "Bu qimmatli qog'oz uchun savdo tarixi hali mavjud emas",
    noFilteredReports: "Tanlangan filtrlarga mos hisobot yo'q",
    annualDetail: "12 oy",
    quarterDetail: (q) => `${q * 3} oy`,
  },
};

function catalogTerminalText(language, key, ...args) {
  const value = (CATALOG_TERMINAL_TEXT[language] || CATALOG_TERMINAL_TEXT.ru)[key];
  return typeof value === "function" ? value(...args) : value;
}

function catalogReportRows(index) {
  if (!index?.availability) return [];
  const rows = [];
  const formOrder = { NSBU: 0, MSFO: 1, Audition: 2 };
  Object.entries(index.availability).forEach(([reportForm, buckets]) => {
    ["annual", "quarter"].forEach((periodType) => {
      (buckets?.[periodType] || []).forEach((report) => {
        if (!report?.year) return;
        rows.push({ ...report, form: reportForm, periodType });
      });
    });
  });
  return rows.sort((a, b) => {
    if (b.year !== a.year) return b.year - a.year;
    const aRank = a.periodType === "annual" ? 4 : Number(a.quarter || 0);
    const bRank = b.periodType === "annual" ? 4 : Number(b.quarter || 0);
    if (bRank !== aRank) return bRank - aRank;
    return (formOrder[a.form] ?? 9) - (formOrder[b.form] ?? 9);
  });
}

function catalogReportKey(report) {
  return report ? `${report.form}:${report.year}:${report.quarter || 0}` : "";
}

// The catalog tables label their rows with the filing's own field names; the
// glossary keys them by term. One map, used by both tables.
const FIN_TERM_OF = {
  revenue: "finRevenue",
  net_income: "finNet",
  total_assets: "totalAssets",
  equity: "equity",
  total_liabilities: "finLiab",
};

function CatalogRatioTable({ result, language }) {
  const lang = language;
  const metrics = result.metrics || {};
  const prevMetrics = result.prev_metrics || {};
  const vals = result.source_values || {};
  const labelMap = (TEXTS[lang] || TEXTS.ru).catalog.ratioLabels;
  const valLabels = (TEXTS[lang] || TEXTS.ru).catalog.dynamicsLabels;
  const fmt = (v) => (v === null || v === undefined ? clg(lang, "noValue") : `${Number(v).toFixed(1)}%`);
  const fmtDE = (v) => (v === null || v === undefined ? clg(lang, "noValue") : Number(v).toFixed(2));
  const fmtRaw = (v) => {
    if (v === null || v === undefined) return clg(lang, "noValue");
    return new Intl.NumberFormat(lang === "en" ? "en-US" : "ru-RU", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  };

  const renderCard = (k, v) => {
    const prev = prevMetrics[k];
    const hasDelta = prev !== null && prev !== undefined && v !== null && v !== undefined;
    const delta = hasDelta ? (Number(v) - Number(prev)).toFixed(1) : null;
    const up = delta !== null && Number(delta) > 0;
    const down = delta !== null && Number(delta) < 0;
    const sectorVal = result.sector_avg?.[k];
    return (
      <div key={k} className="catalog-ratio-card">
        <span className="ratio-name">{labelMap[k] || k}</span>
        <strong className="ratio-value">{k === "debt_to_equity" ? fmtDE(v) : fmt(v)}</strong>
        {delta !== null && (
          <div className={`ratio-delta ${up ? "pos" : down ? "neg" : "neutral"}`}>
            {up ? "↑" : down ? "↓" : "→"} {up ? "+" : ""}{delta}{k !== "debt_to_equity" ? "%" : ""}
            <span className="ratio-delta-label"> vs {result.prev_year}</span>
          </div>
        )}
        {sectorVal !== undefined && sectorVal !== null && (
          <div className="ratio-sector-avg">
            ∅ {k === "debt_to_equity" ? fmtDE(sectorVal) : fmt(sectorVal)}
            {result.sector_avg?.n ? <span className="ratio-delta-label"> ({result.sector_avg.n})</span> : null}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="catalog-result-body">
      <div className="catalog-ratio-grid">
        {Object.entries(metrics)
          .filter(([, v]) => result.data_source !== "verified_cache" || (v !== null && v !== undefined))
          .map(([k, v]) => renderCard(k, v))}
      </div>
      <table className="catalog-source-table">
        <tbody>
          {Object.entries(vals).filter(([, v]) => v !== null).map(([k, v]) => (
            <tr key={k}><td>{valLabels[k] || k}<TermInfo termId={FIN_TERM_OF[k]} lang={lang} label={valLabels[k]} /></td><td className="num">{fmtRaw(v)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CatalogDynamicsTable({ result, language }) {
  const years = result.years || [];
  const series = result.series || {};
  const quarterly = result.quarterly || [];
  const labels = (TEXTS[language] || TEXTS.ru).catalog.dynamicsLabels;
  const metricKeys = Object.keys(labels);
  const fmtN = (v) => {
    if (v === null || v === undefined) return "—";
    return new Intl.NumberFormat(language === "en" ? "en-US" : "ru-RU", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  };
  if (!years.length && !quarterly.length) return <p className="muted">{clg(language, "noReports")}</p>;
  return (
    <div className="catalog-result-body">
      {years.length > 0 && (
        <div className="catalog-table-wrap">
          <table className="market-table">
            <thead>
              <tr>
                <th>{language === "ru" ? "Показатель" : language === "uz" ? "Ko'rsatkich" : "Metric"}</th>
                {years.map((y) => <th key={y} className="num">{y}</th>)}
              </tr>
            </thead>
            <tbody>
              {Object.entries(series).map(([key, vals]) => (
                <tr key={key}>
                  <td>{labels[key] || key}</td>
                  {vals.map((v, i) => <td key={i} className="num">{fmtN(v)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {quarterly.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div className="panel-label" style={{ marginBottom: 8 }}>
            {language === "ru" ? "Поквартальная динамика" : language === "uz" ? "Choraklik dinamika" : "Quarterly dynamics"}
          </div>
          <div className="catalog-table-wrap">
            <table className="market-table">
              <thead>
                <tr>
                  <th>{language === "ru" ? "Период" : "Period"}</th>
                  {metricKeys.map((m) => <th key={m} className="num">{labels[m] || m}</th>)}
                </tr>
              </thead>
              <tbody>
                {quarterly.map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    {metricKeys.map((m) => <td key={m} className="num">{fmtN(row[m])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {result.seasonality && (
        <div style={{ marginTop: 20 }}>
          <div className="panel-label" style={{ marginBottom: 8 }}>
            {language === "ru" ? "Сезонность (выручка по кварталам)" : language === "uz" ? "Mavsumiylik (choraklar bo'yicha daromad)" : "Seasonality (revenue by quarter)"}
          </div>
          {result.seasonality.insufficient ? (
            <p className="muted">
              {language === "ru"
                ? "Недостаточно данных для сезонного анализа (требуется ≥3 лет истории)."
                : language === "uz"
                ? "Mavsumiy tahlil uchun ma'lumot yetarli emas (≥3 yil tarix kerak)."
                : "Insufficient data for seasonal analysis (≥3 years of history required)."}
            </p>
          ) : (
            <div className="catalog-table-wrap">
              <table className="market-table">
                <thead>
                  <tr>{[1, 2, 3, 4].map((q) => <th key={q} className="num">Q{q}</th>)}</tr>
                </thead>
                <tbody>
                  <tr>{[1, 2, 3, 4].map((q) => <td key={q} className="num">{fmtN(result.seasonality.quarter_avg?.[q])}</td>)}</tr>
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CatalogCompareTable({ result, language }) {
  const p1 = result.period1 || {};
  const p2 = result.period2 || {};
  const m1 = p1.metrics || {};
  const m2 = p2.metrics || {};
  const v1 = p1.source_values || {};
  const v2 = p2.source_values || {};
  const ratioLabels = (TEXTS[language] || TEXTS.ru).catalog.ratioLabels;
  const valLabels = (TEXTS[language] || TEXTS.ru).catalog.dynamicsLabels;
  const periodLabel = (p) => p.quarter > 0 ? `Q${p.quarter} ${p.year}` : `${p.year}`;
  const fmt = (v, isPercent = true) => (v === null || v === undefined ? "—" : isPercent ? `${v}%` : String(v));
  const fmtN = (v) => {
    if (v === null || v === undefined) return "—";
    return new Intl.NumberFormat(language === "en" ? "en-US" : "ru-RU", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  };
  const diff = (a, b) => {
    if (a === null || b === null || a === undefined || b === undefined) return null;
    return Math.round((a - b) * 100) / 100;
  };
  const valueKeys = Object.keys({ ...v1, ...v2 }).filter((key) => (
    result.data_source !== "verified_cache"
    || v1[key] !== null && v1[key] !== undefined
    || v2[key] !== null && v2[key] !== undefined
  ));
  const metricKeys = result.data_source === "verified_cache"
    ? Object.keys({ ...m1, ...m2 }).filter((key) => (
      m1[key] !== null && m1[key] !== undefined
      || m2[key] !== null && m2[key] !== undefined
    ))
    : Object.keys(ratioLabels);
  return (
    <div className="catalog-result-body">
      <div className="catalog-table-wrap">
        <table className="market-table">
          <thead>
            <tr>
              <th>{language === "ru" ? "Показатель" : "Metric"}</th>
              <th className="num">{periodLabel(p1)}</th>
              <th className="num">{periodLabel(p2)}</th>
              <th className="num">{language === "ru" ? "Изменение" : "Change"}</th>
            </tr>
          </thead>
          <tbody>
            {valueKeys.map((k) => (
              <tr key={k}>
                <td>{valLabels[k] || k}<TermInfo termId={FIN_TERM_OF[k]} lang={normalizeLanguage(language)} label={valLabels[k]} /></td>
                <td className="num">{fmtN(v1[k])}</td>
                <td className="num">{fmtN(v2[k])}</td>
                <td className={`num ${diff(v1[k], v2[k]) > 0 ? "tone-good" : diff(v1[k], v2[k]) < 0 ? "tone-danger" : ""}`}>
                  {diff(v1[k], v2[k]) !== null ? fmtN(diff(v1[k], v2[k])) : "—"}
                </td>
              </tr>
            ))}
            {metricKeys.map((k) => (
              <tr key={`r-${k}`}>
                <td>{ratioLabels[k]}</td>
                <td className="num">{fmt(m1[k], k !== "debt_to_equity")}</td>
                <td className="num">{fmt(m2[k], k !== "debt_to_equity")}</td>
                <td className={`num ${diff(m1[k], m2[k]) > 0 ? "tone-good" : diff(m1[k], m2[k]) < 0 ? "tone-danger" : ""}`}>
                  {diff(m1[k], m2[k]) !== null ? `${diff(m1[k], m2[k])}${k !== "debt_to_equity" ? "%" : ""}` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CatalogView({ language, companies, token, addToast, onNavigateToAnalysis, initialStatus, user }) {
  const lang = normalizeLanguage(language);
  const [status, setStatus] = useState(initialStatus || null);
  const [catalogComps, setCatalogComps] = useState([]);
  const [compsLoading, setCompsLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [ticker, setTicker] = useState("");
  const [index, setIndex] = useState(null);
  const [indexLoading, setIndexLoading] = useState(false);
  const [form, setForm] = useState("NSBU");
  const [year, setYear] = useState("");
  const [quarter, setQuarter] = useState(0);
  const [analysisType, setAnalysisType] = useState("financial");
  const [compareTicker, setCompareTicker] = useState("");
  const [compareYear, setCompareYear] = useState("");
  const [compareQuarter, setCompareQuarter] = useState(0);
  const [result, setResult] = useState(null);
  const [resultLoading, setResultLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [sparkline, setSparkline] = useState(null);
  const [sparklineLoading, setSparklineLoading] = useState(false);
  const [sectorFilter, setSectorFilter] = useState("all");
  const [reportFilter, setReportFilter] = useState("all");
  const [yearFilter, setYearFilter] = useState("all");
  const [chartMonths, setChartMonths] = useState(3);
  const [reportPage, setReportPage] = useState(0);

  const apiFetch = (path, options = {}) => {
    const stored = localStorage.getItem(STORAGE_KEY) || sessionStorage.getItem(STORAGE_KEY) || "";
    return fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(stored ? { Authorization: `Bearer ${stored}` } : {}), ...(options.headers || {}) } });
  };

  const loadStatus = async () => {
    try {
      const res = await apiFetch("/api/catalog/status");
      const data = await res.json();
      if (res.ok) setStatus(data);
    } catch { /* optional */ }
  };

  const loadCatalogComps = async () => {
    setCompsLoading(true);
    try {
      const res = await apiFetch("/api/catalog/companies");
      const data = await res.json();
      if (res.ok) setCatalogComps(data.companies || []);
    } catch { /* ignore */ }
    finally { setCompsLoading(false); }
  };

  const loadIndex = async (t) => {
    setIndexLoading(true);
    setIndex(null);
    setYear("");
    setQuarter(0);
    setResult(null);
    try {
      const res = await apiFetch(`/api/catalog/index/${t}`);
      const data = await res.json();
      if (res.ok) setIndex(data);
    } catch { /* ignore */ }
    finally { setIndexLoading(false); }
  };

  useEffect(() => { loadStatus(); loadCatalogComps(); }, []);
  useEffect(() => {
    if (ticker || !catalogComps.length) return;
    // Open on a useful, data-rich issuer instead of an empty instruction panel.
    const first = catalogComps.slice().sort((a, b) => (b.total_count || 0) - (a.total_count || 0))[0];
    if (first?.ticker) setTicker(first.ticker);
  }, [catalogComps, ticker]);
  useEffect(() => { if (ticker) loadIndex(ticker); else { setIndex(null); setYear(""); setQuarter(0); setResult(null); } }, [ticker]);
  useEffect(() => {
    if (!ticker) { setSparkline(null); return; }
    setSparklineLoading(true);
    setSparkline(null);
    apiFetch(`/api/price-history/${ticker}?months=${chartMonths}`)
      .then((r) => r.json())
      .then((d) => { if (d.ok && d.points?.length >= 2) setSparkline(d.points); })
      .catch(() => {})
      .finally(() => setSparklineLoading(false));
  }, [ticker, chartMonths]);

  const handleSync = async (specificTicker = null) => {
    if (!token) { addToast(lang === "ru" ? "Войдите для синхронизации" : "Sign in to sync", "error"); return; }
    setSyncing(true);
    try {
      const body = { force: true, ...(specificTicker ? { ticker: specificTicker } : {}) };
      const res = await apiFetch("/api/catalog/sync", { method: "POST", body: JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Sync failed");
      addToast(clg(lang, "syncDone"), "success");
      loadStatus();
      loadCatalogComps();
      if (ticker) loadIndex(ticker);
    } catch (err) { addToast(err.message, "error"); }
    finally { setSyncing(false); }
  };

  const handleRunAnalysis = async () => {
    if (!token) { addToast(lang === "ru" ? "Войдите для анализа" : "Sign in to analyze", "error"); return; }
    if (!ticker || !year) return;
    setResultLoading(true);
    setResult(null);
    try {
      const body = {
        ticker, year: parseInt(year), quarter, form, analysis_type: analysisType, language: lang,
        ...(compareTicker ? { compare_ticker: compareTicker } : {}),
        ...(compareYear ? { compare_year: parseInt(compareYear), compare_quarter: compareQuarter } : {}),
      };
      const res = await apiFetch("/api/catalog/analyze", { method: "POST", body: JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Analysis failed");
      setResult(data);
    } catch (err) { addToast(err.message, "error"); }
    finally { setResultLoading(false); }
  };

  const handleSelectReport = (report) => {
    setForm(report.form);
    setYear(String(report.year));
    setQuarter(Number(report.quarter || 0));
    setResult(null);
    // The report table now follows the analysis controls. After choosing a row near the
    // bottom of the page, return the reader to the controls that changed above it.
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        document.getElementById("catalog-selected-report")?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      });
    });
  };

  // Derived availability helpers
  const allReportRows = catalogReportRows(index);
  const reportYears = [...new Set(allReportRows.map((r) => r.year))].sort((a, b) => b - a);
  const visibleReportRows = allReportRows.filter((report) => (
    (reportFilter === "all" || report.form === reportFilter)
    && (yearFilter === "all" || report.year === Number(yearFilter))
  ));
  const reportsPerPage = 10;
  const reportPageCount = Math.max(1, Math.ceil(visibleReportRows.length / reportsPerPage));
  const safeReportPage = Math.min(reportPage, reportPageCount - 1);
  const pagedReportRows = visibleReportRows.slice(safeReportPage * reportsPerPage, (safeReportPage + 1) * reportsPerPage);
  const avail = index?.availability || {};
  const formAvail = avail[form] || { annual: [], quarter: [] };
  const availYears = [...new Set([...(formAvail.annual || []), ...(formAvail.quarter || [])].map((r) => r.year))].filter(Boolean).sort((a, b) => b - a);
  const availQuarters = year ? (formAvail.quarter || []).filter((r) => r.year === parseInt(year)).map((r) => r.quarter).sort() : [];
  const isAnnualAvail = year ? (formAvail.annual || []).some((r) => r.year === parseInt(year)) : false;
  const isCurrentAvail = year ? (quarter === 0 ? isAnnualAvail : (formAvail.quarter || []).some((r) => r.year === parseInt(year) && r.quarter === quarter)) : false;
  const currentReport = year ? (quarter === 0
    ? (formAvail.annual || []).find((r) => r.year === parseInt(year))
    : (formAvail.quarter || []).find((r) => r.year === parseInt(year) && r.quarter === quarter)
  ) : null;

  useEffect(() => {
    if (!index) return;
    const rows = catalogReportRows(index).filter((report) => (
      (reportFilter === "all" || report.form === reportFilter)
      && (yearFilter === "all" || report.year === Number(yearFilter))
    ));
    if (!rows.length) {
      if (year) {
        setYear("");
        setQuarter(0);
        setResult(null);
      }
      return;
    }
    const currentKey = `${form}:${year}:${quarter || 0}`;
    if (!rows.some((report) => catalogReportKey(report) === currentKey)) {
      const latest = rows[0];
      setForm(latest.form);
      setYear(String(latest.year));
      setQuarter(Number(latest.quarter || 0));
      setResult(null);
    }
  }, [index, reportFilter, yearFilter, form, year, quarter]);
  useEffect(() => { setReportPage(0); }, [index, reportFilter, yearFilter]);

  const needsComparePeriod = ["quarter_compare", "annual_compare"].includes(analysisType);
  const needsCompareTicker = analysisType === "multi_company";

  const catalogSectors = orderSectors(new Set(catalogComps.map((c) => c.sector || "other")))
    .sort((a, b) => sectorLabel(lang, a).localeCompare(sectorLabel(lang, b), lang));
  const filteredComps = catalogComps.filter((c) => {
    const q = search.toLowerCase();
    const matchesSector = sectorFilter === "all" || (c.sector || "other") === sectorFilter;
    const matchesReport = reportFilter === "all"
      || (reportFilter === "NSBU" && c.nsbu_count > 0)
      || (reportFilter === "MSFO" && c.msfo_count > 0)
      || (reportFilter === "Audition" && c.audit_count > 0);
    // An entry stands for every ticker of its issuer, so searching for a bond
    // series (ACMT2B4) has to reach the company it belongs to.
    const matchesSearch = !q || (c.company_name || "").toLowerCase().includes(q)
      || (c.tickers?.length ? c.tickers : [c.ticker]).some((t) => t.toLowerCase().includes(q));
    return matchesSearch && matchesSector && matchesReport;
  }).sort((a, b) => (b.total_count || 0) - (a.total_count || 0)
    || String(a.company_name || a.ticker).localeCompare(String(b.company_name || b.ticker), lang));

  const selectedCompany = catalogComps.find((c) => c.ticker === ticker);
  const latestReport = allReportRows[0] || null;

  const analysisTypesObj = (TEXTS[lang] || TEXTS.ru).catalog.analysisTypes;
  const formsObj = (TEXTS[lang] || TEXTS.ru).catalog.forms;
  const periodsObj = (TEXTS[lang] || TEXTS.ru).catalog.periods;

  const renderResult = () => {
    if (!result) return null;
    const type = result.analysis_type;

    if (type === "ratio") return <CatalogRatioTable result={result} language={lang} />;
    if (type === "dynamics") return <CatalogDynamicsTable result={result} language={lang} />;
    if (type === "quarter_compare" || type === "annual_compare") return <CatalogCompareTable result={result} language={lang} />;

    // AI analysis — three distinct lenses on one computed report:
    //   financial      → полный финансовый разбор (статья с таблицами)
    //   swot           → сильные/слабые стороны и катализаторы
    //   recommendation → скоринг, оценка цены и итоговый вердикт
    const sections = result.sections || {};
    const TYPE_SECTIONS = {
      financial: ["ДОСЬЕ", "ЧТО_С_ДЕНЬГАМИ", "ТРЕНД", "ЭФФЕКТИВНОСТЬ", "ОЦЕНКА_ЦЕНЫ", "РЫНОЧНЫЕ_ДАННЫЕ"],
      swot: ["СИЛЬНЫЕ_СТОРОНЫ", "СЛАБЫЕ_СТОРОНЫ", "КАТАЛИЗАТОРЫ"],
      recommendation: ["СКОРИНГ", "ОЦЕНКА_ЦЕНЫ", "ВЕРДИКТ", "ИТОГ"],
    };
    const wanted = TYPE_SECTIONS[type] || null;

    // SWOT & recommendation: curated raw sections rendered as expandable cards.
    if (wanted && type !== "financial") {
      const picked = wanted.filter((k) => typeof sections[k] === "string" && sections[k].trim());
      if (picked.length) {
        return (
          <div className="catalog-result-body">
            {picked.map((k, i) => (
              <SectionCard key={k} title={getSectionTitle(lang, k)} body={sections[k]} index={i} open language={lang} />
            ))}
          </div>
        );
      }
    }

    // financial (and fallback): article report with tables, filtered to the lens.
    const allArticle = result.article_report?.sections || [];
    const articleSections = wanted ? allArticle.filter((s) => wanted.includes(s.id)) : allArticle;
    const hasArticle = articleSections.length > 0;
    const allEntries = Object.entries(sections).filter(([, v]) => v && typeof v === "string");
    const sectionEntries = wanted ? allEntries.filter(([k]) => wanted.includes(k)) : allEntries;
    return (
      <div className="catalog-result-body">
        {hasArticle ? articleSections.map((section, i) => (
          <div key={section.id || i} className="catalog-section">
            <div className="panel-label">{section.title || getSectionTitle(lang, section.id)}</div>
            <div className="catalog-section-text">
              <StructuredReportBlocks blocks={section.blocks || []} keyPrefix={`cat-${i}`} />
            </div>
          </div>
        )) : sectionEntries.map(([key, text], i) => (
          <SectionCard key={key} title={getSectionTitle(lang, key)} body={text} index={i} open language={lang} />
        ))}
        {!hasArticle && !sectionEntries.length && (
          <p className="muted">{lang === "ru" ? "Нет данных для отображения" : "No data to display"}</p>
        )}
      </div>
    );
  };

  return (
    <section className="catalog-layout">
      <header className="catalog-terminal-head">
        <div>
          <div className="catalog-eyebrow">{catalogTerminalText(lang, "eyebrow")}</div>
          <h1>{catalogTerminalText(lang, "heading")}</h1>
          <p>
            {status
              ? `${status.companies_synced} ${clg(lang, "companies")} · ${status.total_reports} ${clg(lang, "reports")}${status.last_sync ? ` · ${clg(lang, "lastSync")}: ${formatMarketTimestamp(status.last_sync, lang)}` : ""}`
              : clg(lang, "loading")}
          </p>
        </div>
        {user?.is_admin && (
          <button className="ghost-btn catalog-sync-all" type="button" onClick={() => handleSync()} disabled={syncing}>
            {syncing ? clg(lang, "syncing") : clg(lang, "syncAll")}
          </button>
        )}
      </header>

      <div className="catalog-toolbar" aria-label={catalogTerminalText(lang, "heading")}>
        <label className="catalog-search-field">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={clg(lang, "searchPlaceholder")}
            aria-label={clg(lang, "searchPlaceholder")}
          />
        </label>
        <CatalogFilterSelect
          value={sectorFilter}
          onChange={setSectorFilter}
          label={catalogTerminalText(lang, "allSectors")}
          options={[
            { value: "all", label: catalogTerminalText(lang, "allSectors") },
            ...catalogSectors.map((sector) => ({ value: sector, label: sectorLabel(lang, sector) })),
          ]}
        />
        <CatalogFilterSelect
          value={reportFilter}
          onChange={setReportFilter}
          label={catalogTerminalText(lang, "allForms")}
          options={[
            { value: "all", label: catalogTerminalText(lang, "allForms") },
            ...Object.entries(formsObj).map(([key, optionLabel]) => ({ value: key, label: optionLabel })),
          ]}
        />
        <CatalogFilterSelect
          className="catalog-filter-control-year"
          value={yearFilter}
          onChange={setYearFilter}
          label={catalogTerminalText(lang, "allYears")}
          options={[
            { value: "all", label: catalogTerminalText(lang, "allYears") },
            ...reportYears.map((reportYear) => ({ value: reportYear, label: reportYear })),
          ]}
        />
        <span className="catalog-toolbar-count">{filteredComps.length} {catalogTerminalText(lang, "results")}</span>
      </div>

      <div className="catalog-body">
        <aside className="catalog-sidebar">
          <div className="catalog-sidebar-head">
            <span>{catalogTerminalText(lang, "issuers")}</span>
            <span>{filteredComps.length}</span>
          </div>
          {compsLoading ? (
            <div className="catalog-list-loading">{clg(lang, "loading")}</div>
          ) : filteredComps.length === 0 ? (
            <div className="catalog-list-empty">
              {catalogComps.length === 0 ? clg(lang, "empty") : clg(lang, "noReports")}
            </div>
          ) : (
            <div className="catalog-company-list">
              {filteredComps.map((c) => (
                <button
                  key={c.ticker}
                  type="button"
                  className={`catalog-company-item ${ticker === c.ticker ? "active" : ""}`}
                  onClick={() => setTicker(c.ticker)}
                  aria-pressed={ticker === c.ticker}
                >
                  <CompanyLogo logo={c.logo} name={c.company_name} ticker={c.ticker} />
                  <div className="catalog-company-item-body">
                    <strong className="catalog-company-title">{c.company_name || c.ticker}</strong>
                    <span className="catalog-company-ticker">
                      {(c.tickers?.length ? c.tickers : [c.ticker]).join(" · ")} · {sectorLabel(lang, c.sector || "other")}
                    </span>
                  </div>
                  <span className="catalog-company-count">{c.total_count || 0}</span>
                </button>
              ))}
            </div>
          )}
        </aside>

        <main className="catalog-main">
          {!ticker ? (
            <div className="empty-state"><p className="empty-copy">{clg(lang, "selectCompany")}</p></div>
          ) : indexLoading ? (
            <div className="catalog-loading">{clg(lang, "loading")}</div>
          ) : (
            <>
              <section className="catalog-company-overview">
                <div className="catalog-company-summary">
                  <div className="catalog-company-header">
                    <div className="catalog-company-identity">
                      <CompanyLogo logo={selectedCompany?.logo} name={index?.company_name || ticker} ticker={ticker} />
                      <div>
                        <div className="catalog-eyebrow">{index?.sector ? sectorLabel(lang, index.sector) : sectorLabel(lang, selectedCompany?.sector || "other")}</div>
                        <h2>{index?.company_name || ticker}</h2>
                        <p>{(index?.tickers?.length ? index.tickers : [ticker]).join(" · ")}</p>
                      </div>
                    </div>
                    <div className="catalog-company-actions">
                      <button className="ghost-btn" type="button" onClick={() => handleSync(ticker)} disabled={syncing}>
                        {syncing ? clg(lang, "syncing") : clg(lang, "syncCompany")}
                      </button>
                      {onNavigateToAnalysis && (
                        <button className="primary-btn" type="button" onClick={() => onNavigateToAnalysis(ticker)}>
                          {lang === "ru" ? "Открыть в Анализе" : lang === "uz" ? "Tahlilda ochish" : "Open in Analysis"}
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="catalog-report-stats">
                    <span><small>{catalogTerminalText(lang, "tickers")}</small><strong>{(index?.tickers?.length ? index.tickers : [ticker]).join(" · ")}</strong></span>
                    <span><small>{formsObj.NSBU}</small><strong>{selectedCompany?.nsbu_count || 0}</strong></span>
                    <span><small>{formsObj.MSFO}</small><strong>{selectedCompany?.msfo_count || 0}</strong></span>
                    <span><small>{formsObj.Audition}</small><strong>{selectedCompany?.audit_count || 0}</strong></span>
                    <span>
                      <small>{catalogTerminalText(lang, "latest")}</small>
                      <strong>{latestReport ? `${latestReport.year} · ${latestReport.quarter ? `Q${latestReport.quarter}` : periodsObj.annual}` : "—"}</strong>
                    </span>
                  </div>
                </div>
                <div className="catalog-price-card">
                  <div className="catalog-price-head">
                    <span>{catalogTerminalText(lang, "chart")}</span>
                    <div className="catalog-range-switch" aria-label={catalogTerminalText(lang, "chart")}>
                      {[1, 3, 12].map((months) => (
                        <button key={months} type="button" className={chartMonths === months ? "active" : ""} onClick={() => setChartMonths(months)}>
                          {months === 12 ? (lang === "ru" ? "1Г" : "1Y") : `${months}${lang === "ru" ? "М" : "M"}`}
                        </button>
                      ))}
                    </div>
                  </div>
                  {sparklineLoading ? (
                    <div className="catalog-chart-loading">{clg(lang, "loading")}</div>
                  ) : sparkline ? (
                    <PriceSparkline points={sparkline} language={lang} />
                  ) : (
                    <div className="catalog-chart-empty">{catalogTerminalText(lang, "noChart")}</div>
                  )}
                </div>
              </section>

              {year && isCurrentAvail && currentReport && (
                <section className="catalog-selected-report" id="catalog-selected-report">
                  <div className="catalog-selected-summary">
                    <div>
                      <span>{catalogTerminalText(lang, "selected")}</span>
                      <strong>{formsObj[form]} · {year}{quarter > 0 ? ` Q${quarter}` : ` · ${periodsObj.annual}`}</strong>
                      <small>{formatCatalogDate(currentReport.published_at, lang)} · openinfo.uz</small>
                    </div>
                    <div className="catalog-selected-files">
                      {currentReport.excel_url && <a className="ghost-btn" href={currentReport.excel_url} target="_blank" rel="noreferrer">{clg(lang, "excelReport")}</a>}
                      {currentReport.pdf_url && !currentReport.pdf_url.includes("/reports/to_pdf") && <a className="ghost-btn" href={currentReport.pdf_url} target="_blank" rel="noreferrer">{clg(lang, "pdfReport")}</a>}
                    </div>
                  </div>

                  <div className="catalog-analysis-heading">{catalogTerminalText(lang, "analyze")}</div>
                <div className="catalog-analysis-controls">
                  <label className="catalog-field">
                    <span>{clg(lang, "analysisLabel")}</span>
                    <select value={analysisType} onChange={(e) => { setAnalysisType(e.target.value); setResult(null); }}>
                      {Object.entries(analysisTypesObj).map(([k, v]) => (
                        <option key={k} value={k}>{v}</option>
                      ))}
                    </select>
                  </label>

                  {needsCompareTicker && (
                    <label className="catalog-field">
                      <span>{clg(lang, "compareWith")}</span>
                      <select value={compareTicker} onChange={(e) => setCompareTicker(e.target.value)}>
                        <option value="">—</option>
                        {filteredComps.filter((c) => (
                          c.ticker !== ticker
                          && ((index?.sector || selectedCompany?.sector) === "finance" || c.sector !== "finance")
                        )).map((c) => (
                          <option key={c.ticker} value={c.ticker}>{c.ticker} — {c.company_name}</option>
                        ))}
                      </select>
                    </label>
                  )}

                  {needsComparePeriod && (
                    <div className="catalog-compare-period">
                      <span>{clg(lang, "comparePeriod")}</span>
                      <div className="catalog-compare-period-row">
                        <select value={compareYear} onChange={(e) => setCompareYear(e.target.value)}>
                          <option value="">—</option>
                          {availYears.map((y) => <option key={y} value={y}>{y}</option>)}
                        </select>
                        {form === "NSBU" && (
                          <select value={compareQuarter} onChange={(e) => setCompareQuarter(parseInt(e.target.value))}>
                            <option value={0}>{periodsObj.annual}</option>
                            {[1, 2, 3].map((q) => <option key={q} value={q}>{periodsObj[`q${q}`]}</option>)}
                          </select>
                        )}
                      </div>
                    </div>
                  )}

                  <button className="primary-btn" type="button" onClick={handleRunAnalysis} disabled={resultLoading}>
                    {resultLoading ? clg(lang, "analysisLoading") : clg(lang, "runAnalysis")}
                  </button>
                </div>
                </section>
              )}

              {result && (
                <article className="panel catalog-result-panel" id="catalog-print-target">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{analysisTypesObj[result.analysis_type] || result.analysis_type}</div>
                      <h3>{result.company_name || ticker} · {result.year}{result.quarter > 0 ? ` Q${result.quarter}` : ""}</h3>
                      {result.sector && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{result.sector}</div>}
                    </div>
                    <button className="ghost-btn catalog-export-btn no-print" type="button" onClick={() => window.print()}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="15" height="15"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
                      {clg(lang, "exportPdf")}
                    </button>
                  </div>
                  {renderResult()}
                </article>
              )}

              <section className="catalog-report-section">
                <div className="catalog-report-head">
                  <div>
                    <h3>{catalogTerminalText(lang, "reports")}</h3>
                    <span>{visibleReportRows.length} {clg(lang, "reports")} · {catalogTerminalText(lang, "newest")}</span>
                  </div>
                </div>

                {visibleReportRows.length ? (
                  <>
                    <div className="catalog-report-table-wrap">
                      <table className="catalog-report-table">
                      <thead>
                        <tr>
                          <th>{catalogTerminalText(lang, "period")}</th>
                          <th>{catalogTerminalText(lang, "type")}</th>
                          <th>{catalogTerminalText(lang, "status")}</th>
                          <th>{catalogTerminalText(lang, "published")}</th>
                          <th>{catalogTerminalText(lang, "source")}</th>
                          <th>{catalogTerminalText(lang, "file")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pagedReportRows.map((report) => {
                          const reportKey = catalogReportKey(report);
                          const selected = reportKey === `${form}:${year}:${quarter || 0}`;
                          const safePdf = report.pdf_url && !report.pdf_url.includes("/reports/to_pdf");
                          return (
                            <tr key={reportKey} className={selected ? "is-selected" : ""}>
                              <td>
                                <button
                                  className="catalog-report-select"
                                  type="button"
                                  aria-pressed={selected}
                                  onClick={() => handleSelectReport(report)}
                                >
                                  <strong>{report.year} · {report.quarter ? `Q${report.quarter}` : periodsObj.annual}</strong>
                                  <small>{report.quarter ? catalogTerminalText(lang, "quarterDetail", report.quarter) : catalogTerminalText(lang, "annualDetail")}</small>
                                </button>
                              </td>
                              <td><span className={`catalog-report-type type-${report.form.toLowerCase()}`}>{formsObj[report.form] || report.form}</span></td>
                              <td><span className="catalog-report-status"><i />{catalogTerminalText(lang, "available")}</span></td>
                              <td>{formatCatalogDate(report.published_at, lang)}</td>
                              <td><a className="catalog-source-link" href="https://openinfo.uz" target="_blank" rel="noreferrer">openinfo.uz</a></td>
                              <td>
                                <div className="catalog-file-actions">
                                  {report.excel_url && <a href={report.excel_url} target="_blank" rel="noreferrer">XLSX</a>}
                                  {safePdf && <a href={report.pdf_url} target="_blank" rel="noreferrer">PDF</a>}
                                  {!report.excel_url && !safePdf && <span>—</span>}
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                      </table>
                    </div>
                    {reportPageCount > 1 && (
                      <div className="catalog-report-pagination">
                        <span>{safeReportPage * reportsPerPage + 1}–{Math.min((safeReportPage + 1) * reportsPerPage, visibleReportRows.length)} / {visibleReportRows.length}</span>
                        <div>
                          <button type="button" onClick={() => setReportPage((page) => Math.max(0, page - 1))} disabled={safeReportPage === 0} aria-label="Previous">←</button>
                          <span>{safeReportPage + 1} / {reportPageCount}</span>
                          <button type="button" onClick={() => setReportPage((page) => Math.min(reportPageCount - 1, page + 1))} disabled={safeReportPage >= reportPageCount - 1} aria-label="Next">→</button>
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="catalog-report-empty">{catalogTerminalText(lang, "noFilteredReports")}</div>
                )}
              </section>
            </>
          )}
        </main>
      </div>
    </section>
  );
}

export { CatalogView };
