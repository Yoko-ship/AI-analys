import { formatCompactNumber, formatRatio, formatSignedPercent, safeNumber } from "../../shared/format.jsx";
import { clampPercent } from "../../shared/chartModel.jsx";
import { TermInfo } from "../../shared/TermInfo.jsx";
import { normalizeLanguage, t, vt } from "../../shared/i18n.jsx";

function SignalCard({ label, value, sub, tone = "neutral" }) {
  return (
    <article className={`mini-market-card tone-${tone}`} data-tone={tone}>
      <span className="mini-market-label">{label}</span>
      <strong>{value}</strong>
      <p>{sub}</p>
    </article>
  );
}

const HERO_LABELS = {
  ru: { revenue: "Выручка", profit: "Чистая прибыль", roe: "Доходность капитала (ROE)", noData: "Нет данных" },
  en: { revenue: "Revenue", profit: "Net income", roe: "Return on equity (ROE)", noData: "No data" },
  uz: { revenue: "Daromad", profit: "Sof foyda", roe: "Kapital rentabelligi (ROE)", noData: "Maʼlumot yoʻq" },
};

function HeroKpiTile({ label, value, year, change, tone = "neutral", hint }) {
  const arrow = change == null ? null : change > 0 ? "▲" : change < 0 ? "▼" : "→";
  const yoyText = change == null ? null : `${arrow} ${formatSignedPercent(change)}`;
  return (
    <article className={`hero-kpi-tile tone-${tone}`}>
      <span className="hero-kpi-label">{label}</span>
      <strong className="hero-kpi-value">{value}</strong>
      <div className="hero-kpi-foot">
        {yoyText && <span className={`hero-kpi-yoy tone-${tone}`}>{yoyText}</span>}
        {year && <span className="hero-kpi-year">{year}</span>}
        {hint && !year && <span className="hero-kpi-year">{hint}</span>}
      </div>
    </article>
  );
}

const BANK_METRIC_LABELS = {
  ru: {
    title: "Банковские коэффициенты",
    car: "Достаточность капитала",
    nim: "Чистая процентная маржа",
    ldr: "Кредиты / депозиты",
    cir: "Cost-to-Income",
  },
  en: {
    title: "Banking ratios",
    car: "Capital adequacy",
    nim: "Net interest margin",
    ldr: "Loan-to-deposit",
    cir: "Cost-to-Income",
  },
  uz: {
    title: "Bank koeffitsientlari",
    car: "Kapital yetarliligi",
    nim: "Sof foiz marjasi",
    ldr: "Kreditlar / depozitlar",
    cir: "Cost-to-Income",
  },
};

function BankMetricCell({ label, value, tone = "neutral", note, language }) {
  return (
    <article className={`bank-metric-cell tone-${tone}`}>
      <span className="bank-metric-label">{label}</span>
      <strong className="bank-metric-value">{value ?? "—"}</strong>
      {note && <p className="bank-metric-note">{note}</p>}
    </article>
  );
}

function BankMetricsPanel({ analysisResult, language }) {
  const bank = analysisResult?.ifrs_snapshot?.bank;
  if (!bank || !bank.is_bank) return null;
  const lbl = BANK_METRIC_LABELS[language] || BANK_METRIC_LABELS.ru;
  const tones = bank.tones || {};
  const notes = bank.notes || {};
  const fmt = (v) => v == null ? "—" : `${formatRatio(v, 1, language)}%`;
  return (
    <article className="panel bank-metrics-panel">
      <div className="panel-head">
        <div>
          <div className="panel-label">{lbl.title}</div>
          <h3>{lbl.title}</h3>
        </div>
      </div>
      <div className="bank-metrics-grid">
        <BankMetricCell label={lbl.car} value={fmt(bank.car_simple_pct)} tone={tones.car_simple_pct} note={notes.car_simple_pct} language={language} />
        <BankMetricCell label={lbl.nim} value={fmt(bank.nim_pct)} tone={tones.nim_pct} note={notes.nim_pct} language={language} />
        <BankMetricCell label={lbl.ldr} value={fmt(bank.ldr_pct)} tone={tones.ldr_pct} note={notes.ldr_pct} language={language} />
        <BankMetricCell label={lbl.cir} value={fmt(bank.cir_pct)} tone={tones.cir_pct} note={notes.cir_pct} language={language} />
      </div>
    </article>
  );
}

const RISK_PANEL_TITLE = { ru: "Профиль риска", en: "Risk profile", uz: "Risk profili" };

// ТЗ §3.4 — structured 3-axis risk profile (financial / market / informational),
// each Low/Medium/High with the concrete drivers behind it. Data comes from the
// backend `risk_profile` field; purely factual, no recommendation.
function RiskProfilePanel({ analysisResult, language }) {
  const rp = analysisResult?.risk_profile;
  if (!rp || !Array.isArray(rp.axes) || !rp.axes.length) return null;
  const title = RISK_PANEL_TITLE[language] || RISK_PANEL_TITLE.ru;
  const toneOf = (lvl) => (lvl === "high" ? "danger" : lvl === "medium" ? "warning" : lvl === "low" ? "good" : "neutral");
  const dl = rp.debt_load;
  const dlLabel = language === "en" ? "Debt load" : language === "uz" ? "Qarz yuki" : "Долговая нагрузка";
  return (
    <article className="panel bank-metrics-panel risk-profile-panel">
      <div className="panel-head">
        <div>
          <div className="panel-label">{title}</div>
          <h3>{title}</h3>
        </div>
        {dl && (
          <span className={`debt-load-badge tone-${dl.tone}`}>
            {dlLabel}: <strong>{dl.label}</strong>
            {dl.debt_to_ebitda != null ? ` · Долг/EBITDA ${dl.debt_to_ebitda}×` : dl.debt_to_equity != null ? ` · D/E ${dl.debt_to_equity}×` : ""}
          </span>
        )}
      </div>
      <div className="bank-metrics-grid risk-profile-grid">
        {rp.axes.map((ax) => (
          <div key={ax.key} className={`bank-metric-cell tone-${toneOf(ax.level)}`}>
            <div className="bank-metric-label">{ax.label}</div>
            <div className="bank-metric-value">{ax.level_label}</div>
            {Array.isArray(ax.drivers) && ax.drivers.length > 0 && (
              <ul className="risk-drivers">
                {ax.drivers.map((d, i) => <li key={i}>{d}</li>)}
              </ul>
            )}
          </div>
        ))}
      </div>
    </article>
  );
}

const OBS_TITLE = { ru: "Статистические наблюдения", en: "Statistical observations", uz: "Statistik kuzatuvlar" };

// ТЗ §3.5 — factual statistical observations (anomaly vs own history, joint
// multi-metric shift, sector deviation). Facts, not diagnoses. Hidden if empty.
function ObservationsPanel({ analysisResult, language }) {
  const obs = analysisResult?.observations;
  if (!Array.isArray(obs) || !obs.length) return null;
  const title = OBS_TITLE[language] || OBS_TITLE.ru;
  return (
    <article className="panel observations-panel">
      <div className="panel-head">
        <div>
          <div className="panel-label">{title}</div>
          <h3>{title}</h3>
        </div>
      </div>
      <ul className="observations-list">
        {obs.map((o, i) => (
          <li key={i} className={`observation-item tone-${o.tone || "neutral"}`}>{o.text}</li>
        ))}
      </ul>
    </article>
  );
}

const STRUCT_TITLE = { ru: "Структура баланса по годам", en: "Balance structure by year", uz: "Balans tuzilmasi (yillar bo'yicha)" };

const STRUCT_LEGEND = {
  ru: { equity: "Капитал", liabilities: "Обязательства" },
  en: { equity: "Equity", liabilities: "Liabilities" },
  uz: { equity: "Kapital", liabilities: "Majburiyatlar" },
};

// ТЗ §3.4 — stacked structural chart: equity + liabilities = assets, per year,
// so the capital structure's evolution is visible at a glance. Data from the
// annual series (segment revenue is not collected, so segments are omitted).
function StructureCharts({ analysisResult, language }) {
  const annual = analysisResult?.ifrs_snapshot?.series?.annual;
  if (!Array.isArray(annual) || annual.length < 2) return null;
  const rows = annual
    .map((r) => {
      const assets = safeNumber(r.total_assets ?? r.assets);
      const equity = safeNumber(r.equity);
      let liab = safeNumber(r.total_liabilities);
      if (liab === null && assets !== null && equity !== null) liab = Math.max(0, assets - equity);
      const total = assets ?? ((equity || 0) + (liab || 0));
      return { year: r.year, equity: equity || 0, liabilities: liab || 0, total };
    })
    .filter((r) => r.total && r.total > 0);
  if (rows.length < 2) return null;
  const maxA = Math.max(...rows.map((r) => r.total));
  const leg = STRUCT_LEGEND[language] || STRUCT_LEGEND.ru;
  const title = STRUCT_TITLE[language] || STRUCT_TITLE.ru;
  const W = 640, H = 240, PAD_B = 26, PAD_T = 12;
  const slot = (W - 20) / rows.length;
  const bw = Math.min(64, slot - 16);
  const scale = (H - PAD_B - PAD_T) / maxA;
  return (
    <article className="panel structure-panel">
      <div className="panel-head">
        <div>
          <div className="panel-label">{title}</div>
          <h3>{title}</h3>
        </div>
        <div className="structure-legend">
          <span className="structure-legend-item"><i className="structure-swatch structure-swatch--equity" />{leg.equity}</span>
          <span className="structure-legend-item"><i className="structure-swatch structure-swatch--liab" />{leg.liabilities}</span>
        </div>
      </div>
      <div className="structure-chart-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} className="structure-svg" preserveAspectRatio="xMidYMid meet" role="img" aria-label={title}>
          {rows.map((r, i) => {
            const x = 10 + i * slot + (slot - bw) / 2;
            const eqH = Math.max(0, r.equity * scale);
            const liH = Math.max(0, r.liabilities * scale);
            return (
              <g key={r.year}>
                <rect x={x} y={H - PAD_B - eqH} width={bw} height={eqH} className="structure-bar-equity" rx="2" />
                <rect x={x} y={H - PAD_B - eqH - liH} width={bw} height={liH} className="structure-bar-liab" rx="2" />
                <text x={x + bw / 2} y={H - PAD_B + 15} className="structure-year">{r.year}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </article>
  );
}

function HeroKpiStrip({ analysisResult, chartData, language }) {
  const lbl = HERO_LABELS[language] || HERO_LABELS.ru;
  const ifrs = analysisResult?.ifrs_snapshot || {};
  const quality = ifrs.quality || {};
  const latest = chartData?.latest;
  const noData = lbl.noData;

  // Revenue
  const revenue = latest && Number.isFinite(latest.revenue) ? latest.revenue : null;
  const revenueChange = chartData?.revenueChange;
  const revenueTone = revenueChange == null ? "neutral" : revenueChange >= 10 ? "good" : revenueChange >= 0 ? "warning" : "danger";

  // Net income
  const profit = latest && Number.isFinite(latest.profit) ? latest.profit : null;
  const profitChange = chartData?.profitChange;
  const profitTone = profitChange == null ? "neutral" : profitChange >= 10 ? "good" : profitChange >= 0 ? "warning" : "danger";

  // ROE
  const roe = Number(quality.roe_pct);
  const haveRoe = Number.isFinite(roe);
  const roeTone = !haveRoe ? "neutral" : roe >= 15 ? "good" : roe >= 5 ? "warning" : "danger";

  return (
    <div className="hero-kpi-strip">
      <HeroKpiTile
        label={lbl.revenue}
        value={revenue != null ? formatCompactNumber(revenue, language) : noData}
        year={latest?.year ?? null}
        change={revenueChange}
        tone={revenueTone}
      />
      <HeroKpiTile
        label={lbl.profit}
        value={profit != null ? formatCompactNumber(profit, language) : noData}
        year={latest?.year ?? null}
        change={profitChange}
        tone={profitTone}
      />
      <HeroKpiTile
        label={lbl.roe}
        value={haveRoe ? `${formatRatio(roe, 1, language)}%` : noData}
        year={null}
        change={null}
        tone={roeTone}
      />
    </div>
  );
}

function MetricRing({ label, percent, display, tone = "neutral", termId, lang }) {
  const value = clampPercent(percent);
  const radius = 38;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - ((value ?? 0) / 100) * circumference;

  return (
    <div className={`metric-ring tone-${tone}`}>
      <svg viewBox="0 0 104 104" role="img" aria-label={label}>
        <circle className="metric-ring-track" cx="52" cy="52" r={radius} />
        <circle
          className="metric-ring-progress"
          cx="52"
          cy="52"
          r={radius}
          style={{ strokeDasharray: circumference, strokeDashoffset: dashOffset }}
        />
      </svg>
      <div className="metric-ring-center">
        <strong>{display}</strong>
      </div>
      <span>{label}{termId && <TermInfo termId={termId} lang={lang} label={label} />}</span>
    </div>
  );
}

function FinancialVisuals({ result, language, score }) {
  if (!result) return null;

  const snapshot = result?.ifrs_snapshot || {};
  const metrics = result?.metrics || {};
  const annualSeries = Array.isArray(snapshot?.series?.annual) ? snapshot.series.annual : [];
  const latestAnnual = annualSeries.at(-1) || {};
  const income = snapshot?.income_statement || {};
  const balance = snapshot?.balance_sheet || {};
  const pickNumber = (...values) => {
    for (const value of values) {
      const number = safeNumber(value);
      if (number !== null) return number;
    }
    return null;
  };
  const makeRow = (key, value, tone = "neutral") => ({
    key,
    label: vt(language, key),
    value,
    tone,
  });

  const revenue = pickNumber(latestAnnual.revenue, income.revenue, income.sales);
  const ebitda = pickNumber(income.ebitda);
  const netIncome = pickNumber(latestAnnual.net_income, income.net_income, income.profit);
  const assets = pickNumber(latestAnnual.assets, latestAnnual.total_assets, balance.assets, balance.total_assets);
  const equity = pickNumber(latestAnnual.equity, latestAnnual.total_equity, balance.equity, balance.total_equity);
  const debt = pickNumber(latestAnnual.debt, latestAnnual.total_debt, latestAnnual.total_liabilities, balance.debt, balance.total_debt, balance.total_liabilities);
  const rows = [
    makeRow("revenue", revenue, "good"),
    makeRow("ebitda", ebitda, "good"),
    makeRow("netIncome", netIncome, netIncome === null ? "neutral" : netIncome >= 0 ? "good" : "danger"),
    makeRow("assets", assets, "neutral"),
    makeRow("equity", equity, "good"),
    makeRow("debt", debt, "warning"),
  ].filter((row) => row.value !== null);
  const maxAbs = Math.max(1, ...rows.map((row) => Math.abs(row.value)));

  const roePct = pickNumber(result?.ifrs_snapshot?.quality?.roe_pct, latestAnnual?.roe_pct);
  const netMarginPct = pickNumber(result?.ifrs_snapshot?.income_statement?.net_margin_pct, latestAnnual?.net_margin_pct);
  const debtToEquity = pickNumber(balance?.debt_to_equity, latestAnnual?.debt_to_equity);
  const ebitdaMarginPct = pickNumber(income?.ebitda_margin_pct);
  const debtToEbitda = pickNumber(income?.debt_to_ebitda);
  // ТЗ compliance: the composite total_score ring is dropped (it's an
  // attractiveness verdict). Rings show only factual ratios. EBITDA-margin and
  // Debt/EBITDA appear only when the filing disclosed D&A (§3.3).
  const rings = [
    {
      label: language === "en" ? "ROE" : language === "uz" ? "ROE" : "ROE",
      termId: "roe",
      percent: roePct === null ? null : Math.min(100, Math.max(0, roePct / 30 * 100)),
      display: roePct === null ? "—" : `${formatRatio(roePct, 1, language)}%`,
      tone: roePct === null ? "neutral" : roePct >= 15 ? "good" : roePct >= 5 ? "warning" : "danger",
    },
    {
      label: language === "en" ? "Net margin" : language === "uz" ? "Sof marja" : "Чистая маржа",
      termId: "netMargin",
      percent: netMarginPct === null ? null : Math.min(100, Math.max(0, netMarginPct / 25 * 100)),
      display: netMarginPct === null ? "—" : `${formatRatio(netMarginPct, 1, language)}%`,
      tone: netMarginPct === null ? "neutral" : netMarginPct >= 10 ? "good" : netMarginPct >= 3 ? "warning" : "danger",
    },
    ebitdaMarginPct === null ? null : {
      label: language === "en" ? "EBITDA margin" : language === "uz" ? "EBITDA marjasi" : "Маржа EBITDA",
      termId: "ebitda",
      percent: Math.min(100, Math.max(0, ebitdaMarginPct / 40 * 100)),
      display: `${formatRatio(ebitdaMarginPct, 1, language)}%`,
      tone: ebitdaMarginPct >= 15 ? "good" : ebitdaMarginPct >= 5 ? "warning" : "danger",
    },
    {
      label: vt(language, "leverage"),
      termId: "debtEq",
      percent: debtToEquity === null ? null : 100 / (1 + Math.max(0, debtToEquity)),
      display: debtToEquity === null ? "—" : `D/E ${formatRatio(debtToEquity, 2, language)}`,
      tone: debtToEquity === null ? "neutral" : debtToEquity <= 1 ? "good" : debtToEquity <= 2 ? "warning" : "danger",
    },
    debtToEbitda === null ? null : {
      label: language === "en" ? "Debt/EBITDA" : language === "uz" ? "Qarz/EBITDA" : "Долг/EBITDA",
      termId: "debtEbitda",
      percent: Math.min(100, Math.max(0, 100 - debtToEbitda / 6 * 100)),
      display: `${formatRatio(debtToEbitda, 2, language)}×`,
      tone: debtToEbitda <= 2 ? "good" : debtToEbitda <= 4 ? "warning" : "danger",
    },
  ].filter(Boolean);

  return (
    <div className="financial-visual-grid">
      <article className="visual-panel financial-bars-panel">
        <div className="visual-panel-head">
          <div>
            <div className="panel-label">{vt(language, "latestPeriod")}</div>
            <h3>{vt(language, "financialStructure")}</h3>
          </div>
          <span>{vt(language, "financialStructureCopy")}</span>
        </div>
        {rows.length ? (
          <div className="financial-bars">
            {rows.map((row) => (
              <div key={row.key} className={`financial-bar-row tone-${row.tone}`}>
                <div className="financial-bar-label">
                  <span>{row.label}</span>
                  <strong>{formatCompactNumber(row.value, language)}</strong>
                </div>
                <div className="financial-bar-track">
                  <span className={row.value < 0 ? "is-negative" : ""} style={{ width: `${Math.max(4, (Math.abs(row.value) / maxAbs) * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="visual-empty">{vt(language, "noVisualData")}</div>
        )}
      </article>

      <article className="visual-panel metric-rings-panel">
        <div className="visual-panel-head">
          <div>
            <div className="panel-label">{vt(language, "latestPeriod")}</div>
            <h3>{vt(language, "scoreAndRisk")}</h3>
          </div>
          <span>{vt(language, "scoreAndRiskCopy")}</span>
        </div>
        <div className="metric-rings-grid">
          {rings.map((ring) => (
            <MetricRing key={ring.label} {...ring} lang={normalizeLanguage(language)} />
          ))}
        </div>
      </article>
    </div>
  );
}

function AnalysisChart({ chartData, language }) {
  if (!chartData) {
    return (
      <div className="analysis-chart empty-state">
        <p className="empty-copy">{t(language, "analysis.chartEmpty")}</p>
      </div>
    );
  }

  const { width, height, filtered, areaPath, revenuePath, profitPath, debtPath, yTicks, x, y, revenueChange, profitChange, debtChange, latest } = chartData;

  return (
    <div className="analysis-chart">
      <svg className="result-chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t(language, "analysis.chartTitle")}>
        <defs>
          <linearGradient id="revenueAreaGradient" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#6ef0c1" stopOpacity="0.42" />
            <stop offset="100%" stopColor="#6ef0c1" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {yTicks.map((tick, index) => (
          <g key={index}>
            <line x1="74" y1={tick.y} x2={width - 24} y2={tick.y} className="chart-grid-line" />
            <text x="64" y={tick.y + 4} className="chart-axis-label chart-axis-label-y" textAnchor="end">
              {formatCompactNumber(tick.value, language)}
            </text>
          </g>
        ))}
        <path d={areaPath} className="chart-area" />
        <path d={revenuePath} className="chart-line chart-line-revenue" />
        <path d={profitPath} className="chart-line chart-line-profit" />
        <path d={debtPath} className="chart-line chart-line-debt" />
        {filtered.map((point, index) => (
          <g key={`${point.year}-${index}`}>
            <circle cx={x(index)} cy={y(point.revenue ?? 0)} r="4.8" className="chart-dot chart-dot-revenue" />
            <circle cx={x(index)} cy={y(point.profit ?? 0)} r="4.8" className="chart-dot chart-dot-profit" />
            <circle cx={x(index)} cy={y(point.debt ?? 0)} r="4.8" className="chart-dot chart-dot-debt" />
          </g>
        ))}
        {filtered.map((point, index) => (
          <text key={`${point.year}-label`} x={x(index)} y={height - 16} className="chart-axis-label chart-axis-label-x" textAnchor="middle">
            {point.year}
          </text>
        ))}
      </svg>

      <div className="chart-legend">
        <div className="legend-chip">
          <span className="legend-swatch legend-swatch-revenue" />
          <span className="legend-label">{t(language, "analysis.signalRevenue")}</span>
          <strong className="legend-value">{formatCompactNumber(latest.revenue, language)}</strong>
          <span className={`legend-delta ${revenueChange === null ? "" : revenueChange >= 0 ? "is-up" : "is-down"}`}>
            {revenueChange === null ? "—" : formatSignedPercent(revenueChange)}
          </span>
        </div>
        <div className="legend-chip">
          <span className="legend-swatch legend-swatch-profit" />
          <span className="legend-label">{t(language, "analysis.signalLatest")}</span>
          <strong className="legend-value">{latest.profit != null ? formatCompactNumber(latest.profit, language) : "—"}</strong>
          <span className={`legend-delta ${profitChange === null ? "" : profitChange >= 0 ? "is-up" : "is-down"}`}>
            {profitChange === null ? "—" : formatSignedPercent(profitChange)}
          </span>
        </div>
        <div className="legend-chip">
          <span className="legend-swatch legend-swatch-debt" />
          <span className="legend-label">{t(language, "analysis.signalDebt")}</span>
          <strong className="legend-value">{latest.debt != null ? formatCompactNumber(latest.debt, language) : "—"}</strong>
          <span className={`legend-delta ${debtChange === null ? "" : debtChange >= 0 ? "is-down" : "is-up"}`}>
            {debtChange === null ? "—" : formatSignedPercent(debtChange)}
          </span>
        </div>
      </div>

      <div className="chart-axis-note">
        <span>{filtered[0]?.year || ""}</span>
        <span>{filtered.at(-1)?.year || ""}</span>
      </div>
    </div>
  );
}

export { AnalysisChart, BankMetricsPanel, FinancialVisuals, HeroKpiStrip, ObservationsPanel, RiskProfilePanel, StructureCharts };
