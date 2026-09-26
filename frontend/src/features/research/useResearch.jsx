import { useResearchState } from "./useResearchState.js";
import { lazy } from "react";
const AnalysisWorkspace = lazy(() => import("./AnalysisWorkspace.jsx").then(module => ({
  default: module.AnalysisWorkspace
})));
const ComparisonWorkspace = lazy(() => import("./ComparisonWorkspace.jsx").then(module => ({
  default: module.ComparisonWorkspace
})));
export function useResearch({
  session: sessionModule,
  toasts: toastsModule,
  preferences: preferencesModule,
  navigation: navigationModule,
  market: marketModule,
  favorites: favoritesModule
}) {
  const {
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
  } = useResearchState({
    sessionModule,
    toastsModule,
    preferencesModule,
    navigationModule,
    marketModule,
    favoritesModule
  });
  const view = <>
{activeView === "analysis" && <AnalysisWorkspace
  activeView={activeView}
  hasProAccess={hasProAccess}
  language={language}
  token={token}
  setActiveView={setActiveView}
  companies={companies}
  analysisResult={analysisResult}
  analysisLoading={analysisLoading}
  handleAnalysisSubmit={handleAnalysisSubmit}
  analysisCompany={analysisCompany}
  setAnalysisCompany={setAnalysisCompany}
  reportAnalysisType={reportAnalysisType}
  setReportAnalysisType={setReportAnalysisType}
  reportForm={reportForm}
  setReportForm={setReportForm}
  reportQuarter={reportQuarter}
  setReportQuarter={setReportQuarter}
  periodsLoading={periodsLoading}
  availableQuartersForYear={availableQuartersForYear}
  reportCurrentYear={reportCurrentYear}
  setReportCurrentYear={setReportCurrentYear}
  quarterlyYearOptions={quarterlyYearOptions}
  annualYearOptions={annualYearOptions}
  reportPreviousYear={reportPreviousYear}
  setReportPreviousYear={setReportPreviousYear}
  forceRefresh={forceRefresh}
  setForceRefresh={setForceRefresh}
  includeAllExcelReports={includeAllExcelReports}
  setIncludeAllExcelReports={setIncludeAllExcelReports}
  excelReportLimit={excelReportLimit}
  setExcelReportLimit={setExcelReportLimit}
  filteredCompanies={filteredCompanies}
  selectedSector={selectedSector}
  setSelectedSector={setSelectedSector}
  availableSectors={availableSectors}
  analysisLabel={analysisLabel}
  resultCacheText={resultCacheText}
  chartData={chartData}
  resultScore={resultScore}
  analysisTicker={analysisTicker}
  favoriteTickers={favoriteTickers}
  handleToggleFavorite={handleToggleFavorite}
  handleExportExcel={handleExportExcel}
  exportingExcel={exportingExcel}
  handleExportPdf={handleExportPdf}
  exportingPdf={exportingPdf}
  metricCards={metricCards}
/>}
{activeView === "compare" && <ComparisonWorkspace
  activeView={activeView}
  hasProAccess={hasProAccess}
  language={language}
  token={token}
  setActiveView={setActiveView}
  compareLoading={compareLoading}
  handleCompareSubmit={handleCompareSubmit}
  compareCompanies={compareCompanies}
  updateCompareCompany={updateCompareCompany}
  companies={companies}
  compareAiSummary={compareAiSummary}
  setCompareAiSummary={setCompareAiSummary}
  compareQuickCompanies={compareQuickCompanies}
  addQuickCompareCompany={addQuickCompareCompany}
  compareResult={compareResult}
  compareMessage={compareMessage}
  handleCompareExport={handleCompareExport}
  exportingCompare={exportingCompare}
  comparison={comparison}
  compareSummary={compareSummary}
  comparePrimaryChart={comparePrimaryChart}
  compareAi={compareAi}
  compareErrors={compareErrors}
  compareSecondaryCharts={compareSecondaryCharts}
  compareTables={compareTables}
/>}
</>;
  return {
    analysisLoading,
    handleRepeatAnalysis,
    setAnalysisCompany,
    view
  };
}
