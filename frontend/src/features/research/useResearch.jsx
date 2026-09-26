import { useEffect, useState } from "react";
import { disclosureText, t } from "../../shared/i18n.jsx";
import { ct } from "./copy.jsx";
import { buildSeriesChart } from "./model.jsx";
import { formatCompactNumber, formatRatio } from "../../shared/format.jsx";
import { ProFeatureGate } from "../../shared/ProFeatureGate.jsx";
import { WorkspacePageHeader } from "../../shared/Cards.jsx";
import { Icons } from "../../shared/Icons.jsx";
import { sectorLabel } from "../../shared/marketCopy.jsx";
import { CompanyLogo } from "../../shared/CompanyLogo.jsx";
import { ResultSkeleton } from "../../shared/ResultSkeleton.jsx";
import { AnalysisChart, BankMetricsPanel, FinancialVisuals, HeroKpiStrip, ObservationsPanel, RiskProfilePanel, StructureCharts } from "./Visuals.jsx";
import { HeroVerdictBlock, ReportArticleView, SUPPLEMENTARY_LABELS, SectionCard, getSectionTitle, splitSections } from "../../shared/ReportDocument.jsx";
import { MetricCard } from "./Metrics.jsx";
import { DisclaimerNote } from "../../shared/DisclaimerNote.jsx";
import { CompareChartCard, CompareLeaderCards, CompareRanking, CompareSummaryText, CompareTable, compareTableTitle } from "./Comparison.jsx";

export function useResearch({ session: sessionModule, toasts: toastsModule, preferences: preferencesModule, navigation: navigationModule, market: marketModule, favorites: favoritesModule }) {
  const { token, apiFetch, loadProfile, hasProAccess, favoriteTickers } = sessionModule;
  const { addToast } = toastsModule;
  const { language } = preferencesModule;
  const { setActiveView, activeView } = navigationModule;
  const { companies, resolveTicker } = marketModule;
  const { handleToggleFavorite } = favoritesModule;
  const defaultReportYear = Math.max(2000, new Date().getFullYear() - 1);

  const reportYearOptions = Array.from({ length: 12 }, (_, index) => String(defaultReportYear + 1 - index));

  const [analysisCompany, setAnalysisCompany] = useState("");

  const [selectedSector, setSelectedSector] = useState(null);

  const [includeAllExcelReports, setIncludeAllExcelReports] = useState(false);

  const [forceRefresh, setForceRefresh] = useState(false);

  const [excelReportLimit, setExcelReportLimit] = useState("");

  const [reportAnalysisType, setReportAnalysisType] = useState("latest");

  const [reportQuarter, setReportQuarter] = useState("1");

  const [reportCurrentYear, setReportCurrentYear] = useState(String(defaultReportYear));

  const [reportPreviousYear, setReportPreviousYear] = useState(String(defaultReportYear - 1));

  const [reportForm, setReportForm] = useState("NAS");

  const [availablePeriods, setAvailablePeriods] = useState(null);

  const [periodsLoading, setPeriodsLoading] = useState(false);

  const [analysisResult, setAnalysisResult] = useState(null);

  const [analysisLoading, setAnalysisLoading] = useState(false);

  const [analysisMessage, setAnalysisMessage] = useState("");

  const [compareCompanies, setCompareCompanies] = useState(["", "", "", "", ""]);

  const [compareResult, setCompareResult] = useState(null);

  const [compareLoading, setCompareLoading] = useState(false);

  const [compareMessage, setCompareMessage] = useState("");

  const [compareAiSummary, setCompareAiSummary] = useState(true);

  const annualYearOptions = availablePeriods?.annual_years?.map(String) || reportYearOptions;

  const quarterlyYearOptions = availablePeriods
    ? [...new Set(availablePeriods.quarterly.map((q) => q.year))].sort((a, b) => b - a).map(String)
    : reportYearOptions;

  const availableQuartersForYear = availablePeriods
    ? availablePeriods.quarterly.filter((q) => String(q.year) === reportCurrentYear).map((q) => q.quarter).sort((a, b) => a - b)
    : [1, 2, 3];

  useEffect(() => {
    const query = analysisCompany.trim();
    if (!query) {
      setAvailablePeriods(null);
      return;
    }
    let cancelled = false;
    setPeriodsLoading(true);
    setAvailablePeriods(null);
    fetch(`/api/periods?company=${encodeURIComponent(query)}`)
      .then((res) => res.json())
      .then((data) => {
        if (cancelled || !data.ok || !data.periods) return;
        setAvailablePeriods(data.periods);
      })
      .catch(() => {}) // fail silently — static fallback remains active
      .finally(() => { if (!cancelled) setPeriodsLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisCompany]);

  useEffect(() => {
    if (!availablePeriods) return;
    if (reportAnalysisType === "quarterly" && availablePeriods.latest_quarterly) {
      const { year, quarter } = availablePeriods.latest_quarterly;
      setReportCurrentYear(String(year));
      setReportQuarter(String(quarter));
      setReportPreviousYear(String(year - 1));
    } else if (reportAnalysisType !== "latest" && availablePeriods.latest_annual_year) {
      const yr = availablePeriods.latest_annual_year;
      setReportCurrentYear(String(yr));
      setReportPreviousYear(String(yr - 1));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availablePeriods]);

  const handleAnalysisSubmit = async (event, companyOverride) => {
    if (event && event.preventDefault) event.preventDefault();
    const company = (typeof companyOverride === "string" ? companyOverride : analysisCompany).trim();
    if (!token) {
      addToast(t(language, "auth.messages.authRequired"), "error");
      setActiveView("auth");
      return;
    }
    if (!company) {
      addToast(t(language, "analysis.resultEmpty"), "error");
      return;
    }
    if (reportAnalysisType !== "latest" && reportCurrentYear === reportPreviousYear) {
      addToast(language === "en" ? "Choose two different years" : language === "uz" ? "Ikki xil yilni tanlang" : "Выберите два разных года", "error");
      return;
    }

    setAnalysisLoading(true);
    setAnalysisMessage(t(language, "analysis.resultLoading"));
    try {
      const res = await apiFetch("/api/analyze", {
        method: "POST",
        body: JSON.stringify({
          company,
          language,
          include_raw: false,
          force_refresh: forceRefresh,
          include_all_excel_reports: includeAllExcelReports,
          report_analysis_type: reportAnalysisType,
          report_form: reportForm,
          ...(reportAnalysisType !== "latest" ? {
            report_current_year: Number(reportCurrentYear),
            report_previous_year: Number(reportPreviousYear),
          } : {}),
          ...(reportAnalysisType === "quarterly" ? { report_quarter: Number(reportQuarter) } : {}),
          ...(includeAllExcelReports && excelReportLimit.trim() ? { excel_report_limit: Number(excelReportLimit) } : {}),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not complete the analysis");
      setAnalysisResult(data);
      setAnalysisMessage(t(language, "analysis.completed"));
      addToast(`${t(language, "analysis.completed")}: ${data.company_name || company}`, "success");
      setActiveView("analysis");
      await loadProfile();
    } catch (error) {
      addToast(error.message, "error");
      setAnalysisMessage(error.message);
      setAnalysisResult(null);
    } finally {
      setAnalysisLoading(false);
    }
  };

  const [exportingExcel, setExportingExcel] = useState(false);

  const handleExportExcel = async () => {
    if (!analysisResult) return;
    setExportingExcel(true);
    try {
      const res = await apiFetch("/api/analyze/export/excel", {
        method: "POST",
        body: JSON.stringify({ result: analysisResult, language }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Export failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const name = (analysisResult.company_name || analysisResult.input || "analysis").replace(/[^\w-]/g, "_").slice(0, 40);
      link.download = `${name}_analysis.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      addToast(error.message, "error");
    } finally {
      setExportingExcel(false);
    }
  };

  const [exportingPdf, setExportingPdf] = useState(false);

  const handleExportPdf = async () => {
    if (!analysisResult) return;
    setExportingPdf(true);
    try {
      const res = await apiFetch("/api/analyze/export/pdf", {
        method: "POST",
        body: JSON.stringify({ result: analysisResult, language }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Export failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const name = (analysisResult.company_name || analysisResult.input || "analysis").replace(/[^\w-]/g, "_").slice(0, 40);
      link.download = `${name}_analysis.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      addToast(error.message, "error");
    } finally {
      setExportingPdf(false);
    }
  };

  const updateCompareCompany = (index, value) => {
    setCompareCompanies((current) => current.map((item, itemIndex) => (itemIndex === index ? value : item)));
  };

  const addQuickCompareCompany = (ticker) => {
    setCompareCompanies((current) => {
      const normalized = String(ticker || "").trim();
      if (!normalized) return current;
      if (current.some((item) => item.trim().toLowerCase() === normalized.toLowerCase())) return current;
      const next = [...current];
      const emptyIndex = next.findIndex((item) => !item.trim());
      if (emptyIndex >= 0) {
        next[emptyIndex] = normalized;
      } else {
        next[2] = normalized;
      }
      return next;
    });
  };

  const [exportingCompare, setExportingCompare] = useState("");

  const handleCompareExport = async (kind) => {
    if (!compareResult) return;
    setExportingCompare(kind);
    try {
      const res = await apiFetch(`/api/compare/export/${kind}`, {
        method: "POST",
        body: JSON.stringify({ result: compareResult, language }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Export failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `comparison.${kind === "excel" ? "xlsx" : "pdf"}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      addToast(error.message, "error");
    } finally {
      setExportingCompare("");
    }
  };

  const handleCompareSubmit = async (event) => {
    event.preventDefault();
    if (!token) {
      addToast(ct(language, "authRequired"), "error");
      setActiveView("auth");
      return;
    }

    const cleaned = [];
    const seen = new Set();
    for (const item of compareCompanies) {
      const value = String(item || "").trim();
      const key = value.toLowerCase();
      if (value && !seen.has(key)) {
        cleaned.push(value);
        seen.add(key);
      }
    }

    if (cleaned.length < 2) {
      addToast(ct(language, "minRequired"), "error");
      return;
    }

    setCompareLoading(true);
    setCompareMessage(ct(language, "loading"));
    try {
      const res = await apiFetch("/api/compare", {
        method: "POST",
        body: JSON.stringify({
          companies: cleaned.slice(0, 5),
          language,
          include_market_context: false,
          include_ai_summary: compareAiSummary,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not complete the comparison");
      setCompareResult(data);
      setCompareMessage(ct(language, "ready"));
      addToast(`${ct(language, "ready")}: ${cleaned.join(" / ")}`, "success");
      setActiveView("compare");
      await loadProfile();
    } catch (error) {
      addToast(error.message, "error");
      setCompareMessage(error.message);
      setCompareResult(null);
    } finally {
      setCompareLoading(false);
    }
  };

  const availableSectors = [...new Set(companies.map((c) => c.sector).filter(Boolean))];

  const filteredCompanies = companies
    .filter((item) => {
      const q = analysisCompany.trim().toLowerCase();
      const matchSearch = !q || item.ticker.toLowerCase().includes(q) || item.company_name.toLowerCase().includes(q);
      const matchSector = !selectedSector || item.sector === selectedSector;
      return matchSearch && matchSector;
    })
    .slice(0, 48);

  const chartData = buildSeriesChart(analysisResult?.ifrs_snapshot?.series?.annual || [], language);

  const analysisLabel = analysisResult?.company_name || analysisResult?.input || t(language, "analysis.resultEmpty");

  const analysisTicker = analysisResult?.ticker || resolveTicker(analysisResult?.input || analysisCompany || analysisResult?.company_name);

  const resultScore = analysisResult?.summary?.score ?? analysisResult?.metrics?.total_score?.score ?? null;

  const resultGrade = analysisResult?.summary?.grade ?? analysisResult?.metrics?.total_score?.grade ?? "—";

  const resultCacheText = analysisResult ? (analysisResult.from_cache ? t(language, "analysis.resultCacheHit") : t(language, "analysis.resultFresh")) : t(language, "analysis.resultCacheWaiting");

  const metricCards = (() => {
    if (!analysisResult?.metrics) return [];
    const metrics = analysisResult.metrics;
    const cards = [];
    const push = (label, value, sub, tone = "warning") => {
      if (value === undefined || value === null || value === "") return;
      cards.push({ label, value, sub, tone });
    };

    // Composite total_score / attractiveness grade and the DCF valuation card
    // removed for ТЗ compliance: no directional/forecast signals, no DCF model
    // in the served UI. Replaced with the factual EBITDA-margin metric (§3.3).
    const inc = analysisResult?.ifrs_snapshot?.income_statement || {};
    if (inc.ebitda_margin_pct !== undefined && inc.ebitda_margin_pct !== null) {
      push(
        language === "en" ? "EBITDA margin" : language === "uz" ? "EBITDA marjasi" : "Маржа EBITDA",
        `${formatRatio(inc.ebitda_margin_pct, 1, language)}%`,
        inc.debt_to_ebitda != null ? `${language === "en" ? "Debt/EBITDA" : "Долг/EBITDA"}: ${formatRatio(inc.debt_to_ebitda, 2, language)}×` : "",
        inc.ebitda_margin_pct >= 15 ? "good" : inc.ebitda_margin_pct >= 5 ? "warning" : "danger"
      );
    }
    const industry = metrics.industry || {};
    push(
      t(language, "metrics.industry"),
      industry.sector_name ?? "—",
      [industry.verdict || "", `${industry.good_count ?? 0} / ${industry.weak_count ?? 0}`].filter(Boolean).join(" · "),
      industry.good_count > industry.weak_count ? "good" : "warning"
    );
    const debtEq = industry.debt_equity || {};
    if (debtEq.value !== undefined && debtEq.value !== null) {
      const burden = debtEq.burden || {};
      push(
        t(language, "metrics.debt_burden"),
        burden[language] || burden.ru || "—",
        `D/E: ${debtEq.value}×`,
        debtEq.rating === "good" ? "good" : debtEq.rating === "ok" ? "warning" : "danger"
      );
    }
    const liquidity = metrics.market_liquidity || {};
    push(
      t(language, "metrics.market_liquidity"),
      liquidity.liquidity_label ?? "—",
      [`${t(language, "analysis.signalLatest")}: ${liquidity.trade_days ?? "—"}/30`, liquidity.avg_trade_value ? formatCompactNumber(liquidity.avg_trade_value, language) : ""].filter(Boolean).join(" · "),
      liquidity.liquidity_label === "high" ? "good" : "warning"
    );
    return cards;
  })();

  const disclosure = disclosureText(language);

  const comparison = compareResult?.comparison || null;

  const compareCharts = Array.isArray(comparison?.charts) ? comparison.charts : [];

  const compareTables = comparison?.tables || {};

  const compareSummary = comparison?.summary || {};

  const compareAi = comparison?.comparative_ai_summary || {};

  const compareErrors = Array.isArray(comparison?.errors) ? comparison.errors : [];

  const comparePrimaryChart = compareCharts.find((chart) => chart.id === "normalized_radar") || compareCharts[0];

  const compareSecondaryCharts = compareCharts.filter((chart) => chart !== comparePrimaryChart);

  const compareQuickCompanies = companies.slice(0, 18);
  useEffect(() => { if (!token) { setAnalysisResult(null); setCompareResult(null); } }, [token]);

  const view = <>
  {activeView === "analysis" && !hasProAccess && (
              <ProFeatureGate
                language={language}
                signedIn={Boolean(token)}
                title={language === "en" ? "Professional company analysis" : language === "uz" ? "Professional kompaniya tahlili" : "Профессиональный анализ компании"}
                description={language === "en" ? "Forecast context, risk analysis, verified comparisons and export are available with PRO access." : language === "uz" ? "Prognoz konteksti, risk tahlili, tekshirilgan taqqoslash va eksport PRO kirishida mavjud." : "Прогнозный контекст, анализ рисков, проверенные сравнения и экспорт доступны с PRO-доступом."}
                onUpgrade={() => setActiveView(token ? "profile" : "auth")}
              />
            )}
  {activeView === "analysis" && hasProAccess && (
              <section className="workspace-page analysis-page" aria-labelledby="analysis-page-title">
                <WorkspacePageHeader
                  id="analysis-page-title"
                  eyebrow={t(language, "analysis.workspaceLabel")}
                  title={t(language, "analysis.title")}
                  description={t(language, "analysis.subtitle")}
                  icon={Icons.chart}
                  actions={token ? (
                    <button className="primary-btn" type="button" onClick={() => document.getElementById("analysis-company-input")?.focus()}>
                      {t(language, "analysis.setupLabel")}
                    </button>
                  ) : (
                    <button className="ghost-btn" type="button" onClick={() => setActiveView("auth")}>
                      {t(language, "profile.signIn")}
                    </button>
                  )}
                >
                  <div className="workspace-snapshot analysis-workspace-snapshot" aria-label={t(language, "analysis.snapshotLabel")}>
                    <span className="workspace-snapshot-label">{t(language, "analysis.snapshotLabel")}</span>
                    <div className="workspace-snapshot-grid">
                      <div>
                        <strong>{companies.length}</strong>
                        <span>{t(language, "analysis.companiesStat")}</span>
                      </div>
                      <div>
                        <strong>3</strong>
                        <span>{t(language, "analysis.languagesStat")}</span>
                      </div>
                      <div>
                        <strong>2</strong>
                        <span>{t(language, "analysis.formatsStat")}</span>
                      </div>
                    </div>
                  </div>
                </WorkspacePageHeader>

                <nav className="workspace-section-nav" aria-label={t(language, "analysis.sectionNav")}>
                  <a href="#analysis-setup">{t(language, "analysis.sections.setup")}</a>
                  <a href="#analysis-companies">{t(language, "analysis.sections.companies")}</a>
                  {(analysisResult || analysisLoading) ? <a href="#analysis-results">{t(language, "analysis.sections.results")}</a> : null}
                </nav>

                <div className="analysis-layout">
                <article id="analysis-setup" className="panel analysis-panel analysis-hero" aria-labelledby="analysis-setup-title">
                  <div className="analysis-form-card-header">
                    <span className="analysis-form-card-icon" aria-hidden="true">{Icons.target}</span>
                    <div>
                      <div className="panel-label">{t(language, "analysis.setupLabel")}</div>
                      <h2 id="analysis-setup-title">{t(language, "analysis.setupTitle")}</h2>
                      <p>{t(language, "analysis.setupDescription")}</p>
                    </div>
                    {analysisLoading && <span className="status-badge analysis-loading-badge" role="status">{t(language, "analysis.loadingChart")}</span>}
                  </div>

                  {!token ? (
                    <div className="analysis-auth-callout" role="note">
                      <span aria-hidden="true">{Icons.lock}</span>
                      <div>
                        <strong>{t(language, "analysis.signInTitle")}</strong>
                        <p>{t(language, "analysis.signInBody")}</p>
                      </div>
                      <button className="ghost-btn" type="button" onClick={() => setActiveView("auth")}>
                        {t(language, "profile.signIn")}
                      </button>
                    </div>
                  ) : null}

                  <div className="analysis-builder-grid">
                  <form className="analysis-form-modern" onSubmit={handleAnalysisSubmit}>
                    <div className="analysis-input-group">
                      <label htmlFor="analysis-company-input">{t(language, "analysis.company")}</label>
                      <div className="analysis-input-wrapper">
                        <span className="analysis-input-icon">{Icons.target}</span>
                        <input
                          id="analysis-company-input"
                          list="companiesList"
                          value={analysisCompany}
                          onChange={(event) => setAnalysisCompany(event.target.value)}
                          placeholder={language === "en" ? "Enter company name or ticker..." : language === "uz" ? "Kompaniya nomi yoki ticker kiriting..." : "Введите название компании или тикер..."}
                          autoComplete="off"
                          aria-describedby="analysis-company-hint"
                          required
                        />
                        {analysisCompany ? (
                          <button
                            type="button"
                            className="analysis-input-clear"
                            onClick={() => setAnalysisCompany("")}
                            aria-label={t(language, "analysis.clearCompany")}
                          >
                            ×
                          </button>
                        ) : null}
                      </div>
                      <span id="analysis-company-hint" className="analysis-field-hint">{t(language, "analysis.browseHint")}</span>
                      <datalist id="companiesList">
                        {companies.map((company) => (
                          <option key={company.ticker} value={company.ticker}>
                            {company.company_name}
                          </option>
                        ))}
                      </datalist>
                    </div>

                    <fieldset className="analysis-period-picker">
                      <legend className="sr-only">{t(language, "analysis.setupTitle")}</legend>
                      <div className="analysis-input-group">
                        <label htmlFor="analysis-report-type">{t(language, "analysis.reportType")}</label>
                        <select id="analysis-report-type" value={reportAnalysisType} onChange={(event) => setReportAnalysisType(event.target.value)}>
                          <option value="latest">{t(language, "analysis.fullAnalysis")}</option>
                          <option value="quarterly">{t(language, "analysis.quarterlyReport")}</option>
                          <option value="annual">{t(language, "analysis.annualReport")}</option>
                        </select>
                      </div>
                      {reportAnalysisType !== "latest" ? (
                        <div className="analysis-input-group">
                          <label htmlFor="analysis-report-form">{t(language, "analysis.reportingForm")}</label>
                          <select
                            id="analysis-report-form"
                            value={reportForm}
                            onChange={(event) => {
                              setReportForm(event.target.value);
                              if (event.target.value === "IFRS" && reportAnalysisType === "quarterly") {
                                setReportAnalysisType("annual");
                              }
                            }}
                          >
                            <option value="NAS">{t(language, "analysis.reportFormNAS")}</option>
                            <option value="IFRS">{t(language, "analysis.reportFormIFRS")}</option>
                          </select>
                          <span className="analysis-form-hint">{t(language, "analysis.reportFormHint")}</span>
                        </div>
                      ) : (
                        <div className="analysis-input-group analysis-source-note">
                          <span className="analysis-source-badge">
                            {language === "en" ? "Data source" : language === "uz" ? "Ma'lumot manbai" : "Источник данных"}:
                            {" "}<strong>{language === "en" ? "NAS structured reports" : language === "uz" ? "MHBS tizimli hisobotlar" : "НСБУ структурированная отчётность"}</strong>
                          </span>
                          <span className="analysis-form-hint">{t(language, "analysis.reportFormLatestNote")}</span>
                        </div>
                      )}
                      {reportAnalysisType === "quarterly" ? (
                        <div className="analysis-input-group">
                          <label htmlFor="analysis-report-quarter">{t(language, "analysis.quarter")}</label>
                          <select id="analysis-report-quarter" value={reportQuarter} onChange={(event) => setReportQuarter(event.target.value)} disabled={periodsLoading}>
                            {availableQuartersForYear.length > 0
                              ? availableQuartersForYear.map((q) => (
                                  <option key={q} value={String(q)}>
                                    {language === "en" ? `Q${q}` : language === "uz" ? `${q}-chorak` : `${q} квартал`}
                                  </option>
                                ))
                              : [1, 2, 3].map((q) => (
                                  <option key={q} value={String(q)}>
                                    {language === "en" ? `Q${q}` : language === "uz" ? `${q}-chorak` : `${q} квартал`}
                                  </option>
                                ))}
                          </select>
                          {periodsLoading && <span className="analysis-periods-loading">{language === "en" ? "Loading periods…" : language === "uz" ? "Davrlar yuklanmoqda…" : "Загрузка периодов…"}</span>}
                        </div>
                      ) : null}
                      {reportAnalysisType !== "latest" ? (
                        <>
                          <div className="analysis-input-group">
                            <label htmlFor="analysis-current-year">{t(language, "analysis.currentYear")}</label>
                            <select id="analysis-current-year" value={reportCurrentYear} onChange={(event) => setReportCurrentYear(event.target.value)} disabled={periodsLoading}>
                              {(reportAnalysisType === "quarterly" ? quarterlyYearOptions : annualYearOptions).map((year) => (
                                <option key={`current-${year}`} value={year}>{year}</option>
                              ))}
                            </select>
                            {periodsLoading && <span className="analysis-periods-loading">{language === "en" ? "Loading periods…" : language === "uz" ? "Davrlar yuklanmoqda…" : "Загрузка периодов…"}</span>}
                          </div>
                          <div className="analysis-input-group">
                            <label htmlFor="analysis-previous-year">{t(language, "analysis.previousYear")}</label>
                            <select id="analysis-previous-year" value={reportPreviousYear} onChange={(event) => setReportPreviousYear(event.target.value)} disabled={periodsLoading}>
                              {annualYearOptions.map((year) => (
                                <option key={`previous-${year}`} value={year}>{year}</option>
                              ))}
                            </select>
                          </div>
                        </>
                      ) : null}
                    </fieldset>

                    <details className="analysis-advanced">
                      <summary>
                        <span>
                          <strong>{t(language, "analysis.advancedTitle")}</strong>
                          <small>{t(language, "analysis.advancedHint")}</small>
                        </span>
                      </summary>
                      <div className="analysis-advanced-body">
                        <label className="analysis-checkbox" htmlFor="analysis-force-refresh">
                          <input id="analysis-force-refresh" type="checkbox" checked={forceRefresh} onChange={(event) => setForceRefresh(event.target.checked)} />
                          <span>{t(language, "analysis.forceRefresh")}</span>
                        </label>

                        <div className={`analysis-deep-excel ${includeAllExcelReports ? "is-active" : ""}`}>
                          <label className="analysis-checkbox analysis-deep-checkbox" htmlFor="analysis-deep-excel">
                            <input id="analysis-deep-excel" type="checkbox" checked={includeAllExcelReports} onChange={(event) => setIncludeAllExcelReports(event.target.checked)} />
                            <span>{language === "en" ? "Deep Excel analysis: use all available XLSX reports" : language === "uz" ? "Deep Excel tahlil: barcha mavjud XLSX hisobotlardan foydalanish" : "Глубокий Excel-анализ: использовать все доступные XLSX-отчеты"}</span>
                          </label>
                          {includeAllExcelReports ? (
                            <div className="analysis-input-group analysis-excel-limit">
                              <label htmlFor="analysis-excel-limit">{language === "en" ? "Optional XLSX cap" : language === "uz" ? "Ixtiyoriy XLSX chegarasi" : "Ограничение XLSX, необязательно"}</label>
                              <input
                                id="analysis-excel-limit"
                                type="number"
                                min="1"
                                max="100"
                                value={excelReportLimit}
                                onChange={(event) => setExcelReportLimit(event.target.value)}
                                placeholder={language === "en" ? "Leave empty = all found" : language === "uz" ? "Bo'sh qoldiring = hammasi" : "Пусто = все найденные"}
                              />
                            </div>
                          ) : null}
                          <p>
                            {language === "en"
                              ? "Leave the limit empty to parse every found XLSX report. This mode is slower on first run, then snapshots are cached."
                              : language === "uz"
                                ? "Barcha topilgan XLSX hisobotlarni olish uchun limitni bo'sh qoldiring. Bu rejim birinchi ishga tushishda sekinroq, keyin snapshot keshdan olinadi."
                                : "Оставьте лимит пустым, чтобы разобрать все найденные XLSX-отчёты. Этот режим медленнее при первом запуске, после парсинга snapshot берется из кэша."}
                          </p>
                        </div>
                      </div>
                    </details>

                    <button className="primary-btn analysis-submit-btn" type="submit" disabled={analysisLoading} aria-busy={analysisLoading}>
                      {Icons.zap}
                      <span>{analysisLoading ? (language === "en" ? "Analyzing..." : language === "uz" ? "Tahlil qilinmoqda..." : "Анализируем...") : token ? t(language, "analysis.submit") : t(language, "analysis.signInAction")}</span>
                    </button>
                  </form>

                  <div id="analysis-companies" className="analysis-companies-section">
                    <div className="analysis-companies-header">
                      <h3>{t(language, "analysis.availableTitle")}</h3>
                      <span className="analysis-companies-count">{filteredCompanies.length} {language === "en" ? "companies" : language === "uz" ? "kompaniya" : "компаний"}</span>
                    </div>
                    <div className="sector-filter">
                      <button
                        className={`sector-chip${!selectedSector ? " active" : ""}`}
                        type="button"
                        aria-pressed={!selectedSector}
                        onClick={() => setSelectedSector(null)}
                      >
                        {sectorLabel(language, "all")}
                      </button>
                      {availableSectors.map((sector) => (
                        <button
                          key={sector}
                          className={`sector-chip${selectedSector === sector ? " active" : ""}`}
                          type="button"
                          aria-pressed={selectedSector === sector}
                          onClick={() => setSelectedSector(selectedSector === sector ? null : sector)}
                        >
                          {sectorLabel(language, sector)}
                        </button>
                      ))}
                    </div>
                    <div className="analysis-companies-grid">
                      {filteredCompanies.map((company) => (
                        <button
                          key={company.ticker}
                          className={`analysis-company-chip${analysisCompany.trim().toUpperCase() === company.ticker.toUpperCase() ? " is-selected" : ""}`}
                          type="button"
                          aria-pressed={analysisCompany.trim().toUpperCase() === company.ticker.toUpperCase()}
                          onClick={() => setAnalysisCompany(company.ticker)}
                        >
                          <CompanyLogo logo={company.logo} name={company.company_name} ticker={company.ticker} />
                          <span className="chip-ticker">{company.ticker}</span>
                          <span className="chip-name">{company.company_name}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                  </div>
                </article>

                {(analysisResult || analysisLoading) && (
                  <article id="analysis-results" className={`panel result-hero ${analysisLoading ? "is-loading" : ""}`}>
                    <div className="panel-head">
                      <div>
                        <div className="panel-label">{t(language, "analysis.resultTitle")}</div>
                        <h2>{analysisLabel}</h2>
                      </div>
                      {analysisResult ? <span className="status-badge muted">{resultCacheText}</span> : null}
                    </div>

                    {analysisLoading ? (
                      <ResultSkeleton language={language} />
                    ) : (
                    <>
                      <HeroKpiStrip
                        analysisResult={analysisResult}
                        chartData={chartData}
                        language={language}
                      />
                      <div className="chart-card">
                        <div className="chart-head">
                          <div>
                            <div className="panel-label">{t(language, "analysis.chartTitle")}</div>
                            <h3>{t(language, "analysis.chartTitle")}</h3>
                          </div>
                          <span className="status-badge muted">{chartData ? `${chartData.filtered[0].year}–${chartData.filtered.at(-1).year}` : t(language, "analysis.chartMetaEmpty")}</span>
                        </div>
                        <AnalysisChart chartData={chartData} language={language} />
                      </div>

                      <BankMetricsPanel analysisResult={analysisResult} language={language} />

                      <FinancialVisuals result={analysisResult} language={language} score={resultScore} />

                      <RiskProfilePanel analysisResult={analysisResult} language={language} />

                      <ObservationsPanel analysisResult={analysisResult} language={language} />

                      <StructureCharts analysisResult={analysisResult} language={language} />

                      <div className="meta-grid">
                        <button
                          id="resultFavoriteBtn"
                          className={`ghost-btn result-favorite-btn ${analysisTicker && favoriteTickers.has(String(analysisTicker).trim().toUpperCase()) ? "is-active" : ""}`}
                          type="button"
                          onClick={() => analysisResult && handleToggleFavorite(analysisTicker, analysisResult.company_name || analysisResult.input || "")}
                        >
                          {analysisTicker && favoriteTickers.has(String(analysisTicker).trim().toUpperCase()) ? t(language, "analysis.favoriteRemove") : t(language, "analysis.favoriteAdd")}
                        </button>
                        <button
                          className="ghost-btn result-export-btn no-print"
                          type="button"
                          onClick={handleExportExcel}
                          disabled={exportingExcel || !analysisResult}
                        >
                          {exportingExcel
                            ? (language === "en" ? "Preparing…" : language === "uz" ? "Tayyorlanmoqda…" : "Готовим…")
                            : (language === "en" ? "⤓ Download Excel" : language === "uz" ? "⤓ Excel yuklab olish" : "⤓ Скачать Excel")}
                        </button>
                        <button
                          className="ghost-btn result-export-btn no-print"
                          type="button"
                          onClick={handleExportPdf}
                          disabled={exportingPdf || !analysisResult}
                        >
                          {exportingPdf
                            ? (language === "en" ? "Preparing…" : language === "uz" ? "Tayyorlanmoqda…" : "Готовим…")
                            : (language === "en" ? "⤓ Download PDF" : language === "uz" ? "⤓ PDF yuklab olish" : "⤓ Скачать PDF")}
                        </button>
                      </div>
                    </>
                  )}
                  </article>
                )}
                </div>
              </section>
            )}
  {activeView === "analysis" && hasProAccess && (analysisResult || analysisLoading) && (
              <section className="results-grid">
                {!analysisResult?.sector_report && <HeroVerdictBlock analysisResult={analysisResult} language={language} />}
                {!analysisResult?.sector_report && <article className="panel metrics-panel">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{t(language, "analysis.metricsTitle")}</div>
                      <h2>{t(language, "analysis.metricsTitle")}</h2>
                    </div>
                  </div>
                  {metricCards.length ? (
                    <div className="metrics-grid">
                      {metricCards.map((item) => (
                        <MetricCard key={item.label} {...item} />
                      ))}
                    </div>
                  ) : (
                    <div className="empty-state">
                      <p className="empty-copy">{analysisLoading ? t(language, "analysis.loadingMetrics") : t(language, "analysis.resultEmpty")}</p>
                    </div>
                  )}
                </article>}

                {analysisResult?.sections && <ReportArticleView analysisResult={analysisResult} language={language} />}

                {!analysisResult?.sector_report && <article className="panel sections-panel">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{t(language, "analysis.sectionsTitle")}</div>
                      <h2>{t(language, "analysis.sectionsTitle")}</h2>
                    </div>
                  </div>
                  {analysisResult?.sections ? (() => {
                    const { primary, supplementary } = splitSections(analysisResult.sections);
                    return (
                      <div className="sections-wrap">
                        {primary.map(([key, value], index) => (
                          <SectionCard
                            key={key}
                            title={getSectionTitle(language, key)}
                            body={value || t(language, "analysis.noData")}
                            index={index}
                            open={index === 0}
                            language={language}
                          />
                        ))}
                        {supplementary.length > 0 && (
                          <details className="section-card section-card--supplementary fade-in">
                            <summary>
                              <span className="section-number">{SUPPLEMENTARY_LABELS[language] || SUPPLEMENTARY_LABELS.ru}</span>
                              <span className="section-title-text">
                                {language === "en"
                                  ? "Additional analysis blocks"
                                  : language === "uz"
                                  ? "Qo'shimcha tahlil bloklari"
                                  : "Дополнительные блоки анализа"}
                              </span>
                            </summary>
                            <div className="section-content">
                              <div className="sections-wrap sections-wrap--nested">
                                {supplementary.map(([key, value], idx) => (
                                  <SectionCard
                                    key={key}
                                    title={getSectionTitle(language, key)}
                                    body={value || t(language, "analysis.noData")}
                                    index={primary.length + idx}
                                    language={language}
                                  />
                                ))}
                              </div>
                            </div>
                          </details>
                        )}
                      </div>
                    );
                  })() : (
                    <div className="empty-state">
                      <p className="empty-copy">{analysisLoading ? t(language, "analysis.loadingSections") : t(language, "analysis.resultEmpty")}</p>
                    </div>
                  )}
                </article>}

                {analysisResult && <DisclaimerNote language={language} variant="report" />}
              </section>
            )}
  {activeView === "compare" && !hasProAccess && (
              <ProFeatureGate
                language={language}
                signedIn={Boolean(token)}
                title={language === "en" ? "Issuer comparison" : language === "uz" ? "Emitentlarni taqqoslash" : "Сравнение эмитентов"}
                description={language === "en" ? "The PRO workspace compares two to five issuers and includes methodology, sources and export." : language === "uz" ? "PRO ish maydoni ikki-beshta emitentni metodologiya, manbalar va eksport bilan taqqoslaydi." : "PRO-рабочее пространство сравнивает от двух до пяти эмитентов, показывает методологию, источники и экспорт."}
                onUpgrade={() => setActiveView(token ? "profile" : "auth")}
              />
            )}
  {activeView === "compare" && hasProAccess && (
              <section className="compare-layout">
                <article className="panel analysis-panel analysis-hero">
                  <div className="analysis-hero-header">
                    <div className="analysis-hero-icon">
                      {Icons.users}
                    </div>
                    <div className="analysis-hero-text">
                      <h1>{ct(language, "title")}</h1>
                      <p>{ct(language, "subtitle")}</p>
                    </div>
                    {compareLoading && <span className="status-badge analysis-loading-badge">{ct(language, "loading")}</span>}
                  </div>

                  <form className="analysis-form-modern" onSubmit={handleCompareSubmit}>
                    <div className="compare-inputs-grid">
                      {compareCompanies.map((value, index) => (
                        <div className="analysis-input-group" key={index}>
                          <label>
                            {ct(language, `company${index + 1}`)}
                            {index >= 2 && <span className="optional-tag">{ct(language, "optional")}</span>}
                          </label>
                          <div className="analysis-input-wrapper">
                            <span className="analysis-input-icon">{Icons.target}</span>
                            <input
                              list="compareCompaniesList"
                              value={value}
                              onChange={(event) => updateCompareCompany(index, event.target.value)}
                              placeholder={ct(language, "placeholder")}
                              autoComplete="off"
                              required={index < 2}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                    <datalist id="compareCompaniesList">
                      {companies.map((company) => (
                        <option key={company.ticker} value={company.ticker}>
                          {company.company_name}
                        </option>
                      ))}
                    </datalist>

                    <div className="analysis-options-row">
                      <label className="analysis-checkbox">
                        <input type="checkbox" checked={compareAiSummary} onChange={(event) => setCompareAiSummary(event.target.checked)} />
                        <span>{ct(language, "includeAi")}</span>
                      </label>
                    </div>

                    <button className="primary-btn analysis-submit-btn" type="submit" disabled={compareLoading}>
                      {Icons.zap}
                      <span>{compareLoading ? ct(language, "loading") : ct(language, "submit")}</span>
                    </button>
                  </form>

                  <div className="analysis-companies-section">
                    <div className="analysis-companies-header">
                      <h3>{ct(language, "quick")}</h3>
                      <span className="analysis-companies-count">{companies.length} {language === "en" ? "companies" : language === "uz" ? "kompaniya" : "компаний"}</span>
                    </div>
                    <div className="analysis-companies-grid">
                      {compareQuickCompanies.map((company) => (
                        <button
                          key={company.ticker}
                          className="analysis-company-chip"
                          type="button"
                          onClick={() => addQuickCompareCompany(company.ticker)}
                        >
                          <span className="chip-ticker">{company.ticker}</span>
                          <span className="chip-name">{company.company_name}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </article>

                {(compareResult || compareLoading) && (
                  <article className={`panel compare-overview-panel ${compareLoading ? "is-loading" : ""}`}>
                    <div className="panel-head">
                      <div>
                        <div className="panel-label">{ct(language, "overview")}</div>
                        <h2>{compareResult ? ct(language, "ready") : ct(language, "empty")}</h2>
                      </div>
                      {compareMessage ? <span className="status-badge muted">{compareMessage}</span> : null}
                      {compareResult && !compareLoading && (
                        <div className="compare-export-actions no-print">
                          <button className="ghost-btn result-export-btn" type="button" onClick={() => handleCompareExport("excel")} disabled={!!exportingCompare}>
                            {exportingCompare === "excel"
                              ? (language === "en" ? "Preparing…" : language === "uz" ? "Tayyorlanmoqda…" : "Готовим…")
                              : (language === "en" ? "⤓ Download Excel" : language === "uz" ? "⤓ Excel yuklab olish" : "⤓ Скачать Excel")}
                          </button>
                          <button className="ghost-btn result-export-btn" type="button" onClick={() => handleCompareExport("pdf")} disabled={!!exportingCompare}>
                            {exportingCompare === "pdf"
                              ? (language === "en" ? "Preparing…" : language === "uz" ? "Tayyorlanmoqda…" : "Готовим…")
                              : (language === "en" ? "⤓ Download PDF" : language === "uz" ? "⤓ PDF yuklab olish" : "⤓ Скачать PDF")}
                          </button>
                        </div>
                      )}
                    </div>

                    {compareLoading ? (
                      <div className="compare-loading-grid">
                        <div />
                        <div />
                        <div />
                      </div>
                    ) : comparison ? (
                      <>
                        <div className="compare-summary-card">
                          <p>{compareSummary.short || ct(language, "noData")}</p>
                          <span>{ct(language, "normalizedNote")}</span>
                        </div>
                        <CompareLeaderCards leaders={comparison.leaders} language={language} />
                        <div className="compare-ranking-grid">
                          <CompareRanking title={ct(language, "ranking")} rows={comparison.ranking} scoreKey="score" language={language} />
                          <CompareRanking title={ct(language, "normalizedRanking")} rows={comparison.normalized_ranking} scoreKey="composite_score" language={language} />
                        </div>
                      </>
                    ) : (
                      <div className="empty-state">
                        <p className="empty-copy">{ct(language, "empty")}</p>
                      </div>
                    )}
                  </article>
                )}
              </section>
            )}
  {activeView === "compare" && hasProAccess && (compareResult || compareLoading) && (
              <section className="compare-results-grid">
                <article className="panel compare-chart-main">
                  {comparePrimaryChart ? <CompareChartCard chart={comparePrimaryChart} language={language} /> : (
                    <div className="empty-state">
                      <p className="empty-copy">{compareLoading ? ct(language, "loading") : ct(language, "noData")}</p>
                    </div>
                  )}
                </article>

                <article className="panel compare-ai-panel">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{ct(language, "aiSummary")}</div>
                      <h2>{ct(language, "aiSummary")}</h2>
                    </div>
                    {compareAi?.model ? <span className="status-badge muted">{compareAi.model}</span> : null}
                  </div>
                  <CompareSummaryText summary={compareAi} language={language} />
                  {compareSummary.methodology ? (
                    <div className="compare-methodology">
                      <strong>{ct(language, "methodology")}</strong>
                      <p>{compareSummary.methodology}</p>
                    </div>
                  ) : null}
                  {compareErrors.length ? (
                    <div className="compare-errors">
                      <strong>{ct(language, "errors")}</strong>
                      {compareErrors.map((error) => (
                        <p key={`${error.company}-${error.error}`}>{error.company}: {error.error}</p>
                      ))}
                    </div>
                  ) : null}
                </article>

                {compareSecondaryCharts.length ? (
                  <article className="panel compare-charts-panel">
                    <div className="panel-head">
                      <div>
                        <div className="panel-label">{ct(language, "charts")}</div>
                        <h2>{ct(language, "charts")}</h2>
                      </div>
                    </div>
                    <div className="compare-chart-grid">
                      {compareSecondaryCharts.map((chart) => (
                        <CompareChartCard key={chart.id || chart.title} chart={chart} language={language} />
                      ))}
                    </div>
                  </article>
                ) : null}

                {Object.keys(compareTables).length ? (
                  <article className="panel compare-tables-panel">
                    <div className="panel-head">
                      <div>
                        <div className="panel-label">{ct(language, "tables")}</div>
                        <h2>{ct(language, "tables")}</h2>
                      </div>
                    </div>
                    <div className="compare-tables-grid">
                      {Object.entries(compareTables).map(([key, table]) => (
                        <CompareTable key={key} table={table} title={compareTableTitle(language, key)} language={language} />
                      ))}
                    </div>
                  </article>
                ) : null}
              </section>
            )}
  </>;
  return { setAnalysisCompany, view };
}
