import { t } from "../../shared/i18n.jsx";
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
export function AnalysisWorkspace({
  activeView,
  hasProAccess,
  language,
  token,
  setActiveView,
  companies,
  analysisResult,
  analysisLoading,
  handleAnalysisSubmit,
  analysisCompany,
  setAnalysisCompany,
  reportAnalysisType,
  setReportAnalysisType,
  reportForm,
  setReportForm,
  reportQuarter,
  setReportQuarter,
  periodsLoading,
  availableQuartersForYear,
  reportCurrentYear,
  setReportCurrentYear,
  quarterlyYearOptions,
  annualYearOptions,
  reportPreviousYear,
  setReportPreviousYear,
  forceRefresh,
  setForceRefresh,
  includeAllExcelReports,
  setIncludeAllExcelReports,
  excelReportLimit,
  setExcelReportLimit,
  filteredCompanies,
  selectedSector,
  setSelectedSector,
  availableSectors,
  analysisLabel,
  resultCacheText,
  chartData,
  resultScore,
  analysisTicker,
  favoriteTickers,
  handleToggleFavorite,
  handleExportExcel,
  exportingExcel,
  handleExportPdf,
  exportingPdf,
  metricCards
}) {
  return <>
{activeView === "analysis" && !hasProAccess && <ProFeatureGate
  language={language}
  signedIn={Boolean(token)}
  title={language === "en" ? "Professional company analysis" : language === "uz" ? "Professional kompaniya tahlili" : "Профессиональный анализ компании"}
  description={language === "en" ? "Forecast context, risk analysis, verified comparisons and export are available with PRO access." : language === "uz" ? "Prognoz konteksti, risk tahlili, tekshirilgan taqqoslash va eksport PRO kirishida mavjud." : "Прогнозный контекст, анализ рисков, проверенные сравнения и экспорт доступны с PRO-доступом."}
  onUpgrade={() => setActiveView(token ? "profile" : "auth")}
/>}
{activeView === "analysis" && hasProAccess && <section className="workspace-page analysis-page" aria-labelledby="analysis-page-title">
                <WorkspacePageHeader id="analysis-page-title" eyebrow={t(language, "analysis.workspaceLabel")} title={t(language, "analysis.title")} description={t(language, "analysis.subtitle")} icon={Icons.chart} actions={token ? <button className="primary-btn" type="button" onClick={() => document.getElementById("analysis-company-input")?.focus()}>
                      {t(language, "analysis.setupLabel")}
                    </button> : <button className="ghost-btn" type="button" onClick={() => setActiveView("auth")}>
                      {t(language, "profile.signIn")}
                    </button>}>
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
                  {analysisResult || analysisLoading ? <a href="#analysis-results">{t(language, "analysis.sections.results")}</a> : null}
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

                  {!token ? <div className="analysis-auth-callout" role="note">
                      <span aria-hidden="true">{Icons.lock}</span>
                      <div>
                        <strong>{t(language, "analysis.signInTitle")}</strong>
                        <p>{t(language, "analysis.signInBody")}</p>
                      </div>
                      <button className="ghost-btn" type="button" onClick={() => setActiveView("auth")}>
                        {t(language, "profile.signIn")}
                      </button>
                    </div> : null}

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
                          onChange={event => setAnalysisCompany(event.target.value)}
                          placeholder={language === "en" ? "Enter company name or ticker..." : language === "uz" ? "Kompaniya nomi yoki ticker kiriting..." : "Введите название компании или тикер..."}
                          autoComplete="off"
                          aria-describedby="analysis-company-hint"
                          required
                        />
                        {analysisCompany ? <button type="button" className="analysis-input-clear" onClick={() => setAnalysisCompany("")} aria-label={t(language, "analysis.clearCompany")}>
                            ×
                          </button> : null}
                      </div>
                      <span id="analysis-company-hint" className="analysis-field-hint">{t(language, "analysis.browseHint")}</span>
                      <datalist id="companiesList">
                        {companies.map(company => <option key={company.ticker} value={company.ticker}>
                            {company.company_name}
                          </option>)}
                      </datalist>
                    </div>

                    <fieldset className="analysis-period-picker">
                      <legend className="sr-only">{t(language, "analysis.setupTitle")}</legend>
                      <div className="analysis-input-group">
                        <label htmlFor="analysis-report-type">{t(language, "analysis.reportType")}</label>
                        <select id="analysis-report-type" value={reportAnalysisType} onChange={event => setReportAnalysisType(event.target.value)}>
                          <option value="latest">{t(language, "analysis.fullAnalysis")}</option>
                          <option value="quarterly">{t(language, "analysis.quarterlyReport")}</option>
                          <option value="annual">{t(language, "analysis.annualReport")}</option>
                        </select>
                      </div>
                      {reportAnalysisType !== "latest" ? <div className="analysis-input-group">
                          <label htmlFor="analysis-report-form">{t(language, "analysis.reportingForm")}</label>
                          <select id="analysis-report-form" value={reportForm} onChange={event => {
                    setReportForm(event.target.value);
                    if (event.target.value === "IFRS" && reportAnalysisType === "quarterly") {
                      setReportAnalysisType("annual");
                    }
                  }}>
                            <option value="NAS">{t(language, "analysis.reportFormNAS")}</option>
                            <option value="IFRS">{t(language, "analysis.reportFormIFRS")}</option>
                          </select>
                          <span className="analysis-form-hint">{t(language, "analysis.reportFormHint")}</span>
                        </div> : <div className="analysis-input-group analysis-source-note">
                          <span className="analysis-source-badge">
                            {language === "en" ? "Data source" : language === "uz" ? "Ma'lumot manbai" : "Источник данных"}:
                            {" "}<strong>{language === "en" ? "NAS structured reports" : language === "uz" ? "MHBS tizimli hisobotlar" : "НСБУ структурированная отчётность"}</strong>
                          </span>
                          <span className="analysis-form-hint">{t(language, "analysis.reportFormLatestNote")}</span>
                        </div>}
                      {reportAnalysisType === "quarterly" ? <div className="analysis-input-group">
                          <label htmlFor="analysis-report-quarter">{t(language, "analysis.quarter")}</label>
                          <select id="analysis-report-quarter" value={reportQuarter} onChange={event => setReportQuarter(event.target.value)} disabled={periodsLoading}>
                            {availableQuartersForYear.length > 0 ? availableQuartersForYear.map(q => <option key={q} value={String(q)}>
                                    {language === "en" ? `Q${q}` : language === "uz" ? `${q}-chorak` : `${q} квартал`}
                                  </option>) : [1, 2, 3].map(q => <option key={q} value={String(q)}>
                                    {language === "en" ? `Q${q}` : language === "uz" ? `${q}-chorak` : `${q} квартал`}
                                  </option>)}
                          </select>
                          {periodsLoading && <span className="analysis-periods-loading">{language === "en" ? "Loading periods…" : language === "uz" ? "Davrlar yuklanmoqda…" : "Загрузка периодов…"}</span>}
                        </div> : null}
                      {reportAnalysisType !== "latest" ? <>
                          <div className="analysis-input-group">
                            <label htmlFor="analysis-current-year">{t(language, "analysis.currentYear")}</label>
                            <select id="analysis-current-year" value={reportCurrentYear} onChange={event => setReportCurrentYear(event.target.value)} disabled={periodsLoading}>
                              {(reportAnalysisType === "quarterly" ? quarterlyYearOptions : annualYearOptions).map(year => <option key={`current-${year}`} value={year}>{year}</option>)}
                            </select>
                            {periodsLoading && <span className="analysis-periods-loading">{language === "en" ? "Loading periods…" : language === "uz" ? "Davrlar yuklanmoqda…" : "Загрузка периодов…"}</span>}
                          </div>
                          <div className="analysis-input-group">
                            <label htmlFor="analysis-previous-year">{t(language, "analysis.previousYear")}</label>
                            <select id="analysis-previous-year" value={reportPreviousYear} onChange={event => setReportPreviousYear(event.target.value)} disabled={periodsLoading}>
                              {annualYearOptions.map(year => <option key={`previous-${year}`} value={year}>{year}</option>)}
                            </select>
                          </div>
                        </> : null}
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
                          <input id="analysis-force-refresh" type="checkbox" checked={forceRefresh} onChange={event => setForceRefresh(event.target.checked)} />
                          <span>{t(language, "analysis.forceRefresh")}</span>
                        </label>

                        <div className={`analysis-deep-excel ${includeAllExcelReports ? "is-active" : ""}`}>
                          <label className="analysis-checkbox analysis-deep-checkbox" htmlFor="analysis-deep-excel">
                            <input id="analysis-deep-excel" type="checkbox" checked={includeAllExcelReports} onChange={event => setIncludeAllExcelReports(event.target.checked)} />
                            <span>{language === "en" ? "Deep Excel analysis: use all available XLSX reports" : language === "uz" ? "Deep Excel tahlil: barcha mavjud XLSX hisobotlardan foydalanish" : "Глубокий Excel-анализ: использовать все доступные XLSX-отчеты"}</span>
                          </label>
                          {includeAllExcelReports ? <div className="analysis-input-group analysis-excel-limit">
                              <label htmlFor="analysis-excel-limit">{language === "en" ? "Optional XLSX cap" : language === "uz" ? "Ixtiyoriy XLSX chegarasi" : "Ограничение XLSX, необязательно"}</label>
                              <input
                                id="analysis-excel-limit"
                                type="number"
                                min="1"
                                max="100"
                                value={excelReportLimit}
                                onChange={event => setExcelReportLimit(event.target.value)}
                                placeholder={language === "en" ? "Leave empty = all found" : language === "uz" ? "Bo'sh qoldiring = hammasi" : "Пусто = все найденные"}
                              />
                            </div> : null}
                          <p>
                            {language === "en" ? "Leave the limit empty to parse every found XLSX report. This mode is slower on first run, then snapshots are cached." : language === "uz" ? "Barcha topilgan XLSX hisobotlarni olish uchun limitni bo'sh qoldiring. Bu rejim birinchi ishga tushishda sekinroq, keyin snapshot keshdan olinadi." : "Оставьте лимит пустым, чтобы разобрать все найденные XLSX-отчёты. Этот режим медленнее при первом запуске, после парсинга snapshot берется из кэша."}
                          </p>
                        </div>
                      </div>
                    </details>

                    <button className="primary-btn analysis-submit-btn" type="submit" disabled={analysisLoading} aria-busy={analysisLoading}>
                      {Icons.zap}
                      <span>{analysisLoading ? language === "en" ? "Analyzing..." : language === "uz" ? "Tahlil qilinmoqda..." : "Анализируем..." : token ? t(language, "analysis.submit") : t(language, "analysis.signInAction")}</span>
                    </button>
                  </form>

                  <div id="analysis-companies" className="analysis-companies-section">
                    <div className="analysis-companies-header">
                      <h3>{t(language, "analysis.availableTitle")}</h3>
                      <span className="analysis-companies-count">{filteredCompanies.length} {language === "en" ? "companies" : language === "uz" ? "kompaniya" : "компаний"}</span>
                    </div>
                    <div className="sector-filter">
                      <button className={`sector-chip${!selectedSector ? " active" : ""}`} type="button" aria-pressed={!selectedSector} onClick={() => setSelectedSector(null)}>
                        {sectorLabel(language, "all")}
                      </button>
                      {availableSectors.map(sector => <button
                        key={sector}
                        className={`sector-chip${selectedSector === sector ? " active" : ""}`}
                        type="button"
                        aria-pressed={selectedSector === sector}
                        onClick={() => setSelectedSector(selectedSector === sector ? null : sector)}
                      >
                          {sectorLabel(language, sector)}
                        </button>)}
                    </div>
                    <div className="analysis-companies-grid">
                      {filteredCompanies.map(company => <button
                        key={company.ticker}
                        className={`analysis-company-chip${analysisCompany.trim().toUpperCase() === company.ticker.toUpperCase() ? " is-selected" : ""}`}
                        type="button"
                        aria-pressed={analysisCompany.trim().toUpperCase() === company.ticker.toUpperCase()}
                        onClick={() => setAnalysisCompany(company.ticker)}
                      >
                          <CompanyLogo logo={company.logo} name={company.company_name} ticker={company.ticker} />
                          <span className="chip-ticker">{company.ticker}</span>
                          <span className="chip-name">{company.company_name}</span>
                        </button>)}
                    </div>
                  </div>
                  </div>
                </article>

                {(analysisResult || analysisLoading) && <article id="analysis-results" className={`panel result-hero ${analysisLoading ? "is-loading" : ""}`}>
                    <div className="panel-head">
                      <div>
                        <div className="panel-label">{t(language, "analysis.resultTitle")}</div>
                        <h2>{analysisLabel}</h2>
                      </div>
                      {analysisResult ? <span className="status-badge muted">{resultCacheText}</span> : null}
                    </div>

                    {analysisLoading ? <ResultSkeleton language={language} /> : <>
                      <HeroKpiStrip analysisResult={analysisResult} chartData={chartData} language={language} />
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
                        <button id="resultFavoriteBtn" className={`ghost-btn result-favorite-btn ${analysisTicker && favoriteTickers.has(String(analysisTicker).trim().toUpperCase()) ? "is-active" : ""}`} type="button" onClick={() => analysisResult && handleToggleFavorite(analysisTicker, analysisResult.company_name || analysisResult.input || "")}>
                          {analysisTicker && favoriteTickers.has(String(analysisTicker).trim().toUpperCase()) ? t(language, "analysis.favoriteRemove") : t(language, "analysis.favoriteAdd")}
                        </button>
                        <button className="ghost-btn result-export-btn no-print" type="button" onClick={handleExportExcel} disabled={exportingExcel || !analysisResult}>
                          {exportingExcel ? language === "en" ? "Preparing…" : language === "uz" ? "Tayyorlanmoqda…" : "Готовим…" : language === "en" ? "⤓ Download Excel" : language === "uz" ? "⤓ Excel yuklab olish" : "⤓ Скачать Excel"}
                        </button>
                        <button className="ghost-btn result-export-btn no-print" type="button" onClick={handleExportPdf} disabled={exportingPdf || !analysisResult}>
                          {exportingPdf ? language === "en" ? "Preparing…" : language === "uz" ? "Tayyorlanmoqda…" : "Готовим…" : language === "en" ? "⤓ Download PDF" : language === "uz" ? "⤓ PDF yuklab olish" : "⤓ Скачать PDF"}
                        </button>
                      </div>
                    </>}
                  </article>}
                </div>
              </section>}
{activeView === "analysis" && hasProAccess && (analysisResult || analysisLoading) && <section className="results-grid">
                {!analysisResult?.sector_report && <HeroVerdictBlock analysisResult={analysisResult} language={language} />}
                {!analysisResult?.sector_report && <article className="panel metrics-panel">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{t(language, "analysis.metricsTitle")}</div>
                      <h2>{t(language, "analysis.metricsTitle")}</h2>
                    </div>
                  </div>
                  {metricCards.length ? <div className="metrics-grid">
                      {metricCards.map(item => <MetricCard key={item.label} {...item} />)}
                    </div> : <div className="empty-state">
                      <p className="empty-copy">{analysisLoading ? t(language, "analysis.loadingMetrics") : t(language, "analysis.resultEmpty")}</p>
                    </div>}
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
          const {
            primary,
            supplementary
          } = splitSections(analysisResult.sections);
          return <div className="sections-wrap">
                        {primary.map(([key, value], index) => <SectionCard
                          key={key}
                          title={getSectionTitle(language, key)}
                          body={value || t(language, "analysis.noData")}
                          index={index}
                          open={index === 0}
                          language={language}
                        />)}
                        {supplementary.length > 0 && <details className="section-card section-card--supplementary fade-in">
                            <summary>
                              <span className="section-number">{SUPPLEMENTARY_LABELS[language] || SUPPLEMENTARY_LABELS.ru}</span>
                              <span className="section-title-text">
                                {language === "en" ? "Additional analysis blocks" : language === "uz" ? "Qo'shimcha tahlil bloklari" : "Дополнительные блоки анализа"}
                              </span>
                            </summary>
                            <div className="section-content">
                              <div className="sections-wrap sections-wrap--nested">
                                {supplementary.map(([key, value], idx) => <SectionCard
                                  key={key}
                                  title={getSectionTitle(language, key)}
                                  body={value || t(language, "analysis.noData")}
                                  index={primary.length + idx}
                                  language={language}
                                />)}
                              </div>
                            </div>
                          </details>}
                      </div>;
        })() : <div className="empty-state">
                      <p className="empty-copy">{analysisLoading ? t(language, "analysis.loadingSections") : t(language, "analysis.resultEmpty")}</p>
                    </div>}
                </article>}

                {analysisResult && <DisclaimerNote language={language} variant="report" />}
              </section>}
</>;
}
