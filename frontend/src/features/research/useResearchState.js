import { useEffect, useState } from "react";
import { disclosureText, t } from "../../shared/i18n.jsx";
import { ct } from "./copy.jsx";
import { buildSeriesChart } from "./model.jsx";
import { formatCompactNumber, formatRatio } from "../../shared/format.jsx";
export function useResearchState({
  sessionModule,
  toastsModule,
  preferencesModule,
  navigationModule,
  marketModule,
  favoritesModule
}) {
  const {
    token,
    apiFetch,
    loadProfile,
    hasProAccess,
    favoriteTickers
  } = sessionModule;
  const {
    addToast
  } = toastsModule;
  const {
    language
  } = preferencesModule;
  const {
    setActiveView,
    activeView
  } = navigationModule;
  const {
    companies,
    resolveTicker
  } = marketModule;
  const {
    handleToggleFavorite
  } = favoritesModule;
  const defaultReportYear = Math.max(2000, new Date().getFullYear() - 1);
  const reportYearOptions = Array.from({
    length: 12
  }, (_, index) => String(defaultReportYear + 1 - index));
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
  const quarterlyYearOptions = availablePeriods ? [...new Set(availablePeriods.quarterly.map(q => q.year))].sort((a, b) => b - a).map(String) : reportYearOptions;
  const availableQuartersForYear = availablePeriods ? availablePeriods.quarterly.filter(q => String(q.year) === reportCurrentYear).map(q => q.quarter).sort((a, b) => a - b) : [1, 2, 3];
  useEffect(() => {
    if (!token) {
      setAnalysisResult(null);
      setCompareResult(null);
    }
  }, [token]);
  useEffect(() => {
    const query = analysisCompany.trim();
    if (!query) {
      setAvailablePeriods(null);
      return;
    }
    let cancelled = false;
    setPeriodsLoading(true);
    setAvailablePeriods(null);
    fetch(`/api/periods?company=${encodeURIComponent(query)}`).then(res => res.json()).then(data => {
      if (cancelled || !data.ok || !data.periods) return;
      setAvailablePeriods(data.periods);
    }).catch(() => {}) // fail silently — static fallback remains active
    .finally(() => {
      if (!cancelled) setPeriodsLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [analysisCompany]);
  useEffect(() => {
    if (!availablePeriods) return;
    if (reportAnalysisType === "quarterly" && availablePeriods.latest_quarterly) {
      const {
        year,
        quarter
      } = availablePeriods.latest_quarterly;
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
            report_previous_year: Number(reportPreviousYear)
          } : {}),
          ...(reportAnalysisType === "quarterly" ? {
            report_quarter: Number(reportQuarter)
          } : {}),
          ...(includeAllExcelReports && excelReportLimit.trim() ? {
            excel_report_limit: Number(excelReportLimit)
          } : {})
        })
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
        body: JSON.stringify({
          result: analysisResult,
          language
        })
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
        body: JSON.stringify({
          result: analysisResult,
          language
        })
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
  const handleRepeatAnalysis = item => {
    const company = (item?.ticker || item?.company_input || item?.company_name || "").trim();
    if (!company) return;
    setAnalysisCompany(company);
    setActiveView("analysis");
    handleAnalysisSubmit(null, company);
  };
  const updateCompareCompany = (index, value) => {
    setCompareCompanies(current => current.map((item, itemIndex) => itemIndex === index ? value : item));
  };
  const addQuickCompareCompany = ticker => {
    setCompareCompanies(current => {
      const normalized = String(ticker || "").trim();
      if (!normalized) return current;
      if (current.some(item => item.trim().toLowerCase() === normalized.toLowerCase())) return current;
      const next = [...current];
      const emptyIndex = next.findIndex(item => !item.trim());
      if (emptyIndex >= 0) {
        next[emptyIndex] = normalized;
      } else {
        next[2] = normalized;
      }
      return next;
    });
  };
  const [exportingCompare, setExportingCompare] = useState("");
  const handleCompareExport = async kind => {
    if (!compareResult) return;
    setExportingCompare(kind);
    try {
      const res = await apiFetch(`/api/compare/export/${kind}`, {
        method: "POST",
        body: JSON.stringify({
          result: compareResult,
          language
        })
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
  const handleCompareSubmit = async event => {
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
          include_ai_summary: compareAiSummary
        })
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
  const availableSectors = [...new Set(companies.map(c => c.sector).filter(Boolean))];
  const filteredCompanies = companies.filter(item => {
    const q = analysisCompany.trim().toLowerCase();
    const matchSearch = !q || item.ticker.toLowerCase().includes(q) || item.company_name.toLowerCase().includes(q);
    const matchSector = !selectedSector || item.sector === selectedSector;
    return matchSearch && matchSector;
  }).slice(0, 48);
  const chartData = buildSeriesChart(analysisResult?.ifrs_snapshot?.series?.annual || [], language);
  const analysisLabel = analysisResult?.company_name || analysisResult?.input || t(language, "analysis.resultEmpty");
  const analysisTicker = analysisResult?.ticker || resolveTicker(analysisResult?.input || analysisCompany || analysisResult?.company_name);
  const resultScore = analysisResult?.summary?.score ?? analysisResult?.metrics?.total_score?.score ?? null;
  const resultGrade = analysisResult?.summary?.grade ?? analysisResult?.metrics?.total_score?.grade ?? "—";
  const resultCacheText = analysisResult ? analysisResult.from_cache ? t(language, "analysis.resultCacheHit") : t(language, "analysis.resultFresh") : t(language, "analysis.resultCacheWaiting");
  const metricCards = (() => {
    if (!analysisResult?.metrics) return [];
    const metrics = analysisResult.metrics;
    const cards = [];
    const push = (label, value, sub, tone = "warning") => {
      if (value === undefined || value === null || value === "") return;
      cards.push({
        label,
        value,
        sub,
        tone
      });
    };

    // Composite total_score / attractiveness grade and the DCF valuation card
    // removed for ТЗ compliance: no directional/forecast signals, no DCF model
    // in the served UI. Replaced with the factual EBITDA-margin metric (§3.3).
    const inc = analysisResult?.ifrs_snapshot?.income_statement || {};
    if (inc.ebitda_margin_pct !== undefined && inc.ebitda_margin_pct !== null) {
      push(language === "en" ? "EBITDA margin" : language === "uz" ? "EBITDA marjasi" : "Маржа EBITDA", `${formatRatio(inc.ebitda_margin_pct, 1, language)}%`, inc.debt_to_ebitda != null ? `${language === "en" ? "Debt/EBITDA" : "Долг/EBITDA"}: ${formatRatio(inc.debt_to_ebitda, 2, language)}×` : "", inc.ebitda_margin_pct >= 15 ? "good" : inc.ebitda_margin_pct >= 5 ? "warning" : "danger");
    }
    const industry = metrics.industry || {};
    push(t(language, "metrics.industry"), industry.sector_name ?? "—", [industry.verdict || "", `${industry.good_count ?? 0} / ${industry.weak_count ?? 0}`].filter(Boolean).join(" · "), industry.good_count > industry.weak_count ? "good" : "warning");
    const debtEq = industry.debt_equity || {};
    if (debtEq.value !== undefined && debtEq.value !== null) {
      const burden = debtEq.burden || {};
      push(t(language, "metrics.debt_burden"), burden[language] || burden.ru || "—", `D/E: ${debtEq.value}×`, debtEq.rating === "good" ? "good" : debtEq.rating === "ok" ? "warning" : "danger");
    }
    const liquidity = metrics.market_liquidity || {};
    push(t(language, "metrics.market_liquidity"), liquidity.liquidity_label ?? "—", [`${t(language, "analysis.signalLatest")}: ${liquidity.trade_days ?? "—"}/30`, liquidity.avg_trade_value ? formatCompactNumber(liquidity.avg_trade_value, language) : ""].filter(Boolean).join(" · "), liquidity.liquidity_label === "high" ? "good" : "warning");
    return cards;
  })();
  const disclosure = disclosureText(language);
  const comparison = compareResult?.comparison || null;
  const compareCharts = Array.isArray(comparison?.charts) ? comparison.charts : [];
  const compareTables = comparison?.tables || {};
  const compareSummary = comparison?.summary || {};
  const compareAi = comparison?.comparative_ai_summary || {};
  const compareErrors = Array.isArray(comparison?.errors) ? comparison.errors : [];
  const comparePrimaryChart = compareCharts.find(chart => chart.id === "normalized_radar") || compareCharts[0];
  const compareSecondaryCharts = compareCharts.filter(chart => chart !== comparePrimaryChart);
  const compareQuickCompanies = companies.slice(0, 18);
  return {
    token,
    hasProAccess,
    favoriteTickers,
    language,
    setActiveView,
    activeView,
    companies,
    handleToggleFavorite,
    analysisCompany,
    setAnalysisCompany,
    selectedSector,
    setSelectedSector,
    includeAllExcelReports,
    setIncludeAllExcelReports,
    forceRefresh,
    setForceRefresh,
    excelReportLimit,
    setExcelReportLimit,
    reportAnalysisType,
    setReportAnalysisType,
    reportQuarter,
    setReportQuarter,
    reportCurrentYear,
    setReportCurrentYear,
    reportPreviousYear,
    setReportPreviousYear,
    reportForm,
    setReportForm,
    periodsLoading,
    analysisResult,
    analysisLoading,
    compareCompanies,
    compareResult,
    compareLoading,
    compareMessage,
    compareAiSummary,
    setCompareAiSummary,
    annualYearOptions,
    quarterlyYearOptions,
    availableQuartersForYear,
    handleAnalysisSubmit,
    exportingExcel,
    handleExportExcel,
    exportingPdf,
    handleExportPdf,
    handleRepeatAnalysis,
    updateCompareCompany,
    addQuickCompareCompany,
    exportingCompare,
    handleCompareExport,
    handleCompareSubmit,
    availableSectors,
    filteredCompanies,
    chartData,
    analysisLabel,
    analysisTicker,
    resultScore,
    resultCacheText,
    metricCards,
    comparison,
    compareTables,
    compareSummary,
    compareAi,
    compareErrors,
    comparePrimaryChart,
    compareSecondaryCharts,
    compareQuickCompanies
  };
}
