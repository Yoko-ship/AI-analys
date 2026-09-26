import { ct } from "./copy.jsx";
import { ProFeatureGate } from "../../shared/ProFeatureGate.jsx";
import { Icons } from "../../shared/Icons.jsx";
import { CompareChartCard, CompareLeaderCards, CompareRanking, CompareSummaryText, CompareTable, compareTableTitle } from "./Comparison.jsx";
export function ComparisonWorkspace({
  activeView,
  hasProAccess,
  language,
  token,
  setActiveView,
  compareLoading,
  handleCompareSubmit,
  compareCompanies,
  updateCompareCompany,
  companies,
  compareAiSummary,
  setCompareAiSummary,
  compareQuickCompanies,
  addQuickCompareCompany,
  compareResult,
  compareMessage,
  handleCompareExport,
  exportingCompare,
  comparison,
  compareSummary,
  comparePrimaryChart,
  compareAi,
  compareErrors,
  compareSecondaryCharts,
  compareTables
}) {
  return <>
{activeView === "compare" && !hasProAccess && <ProFeatureGate
  language={language}
  signedIn={Boolean(token)}
  title={language === "en" ? "Issuer comparison" : language === "uz" ? "Emitentlarni taqqoslash" : "Сравнение эмитентов"}
  description={language === "en" ? "The PRO workspace compares two to five issuers and includes methodology, sources and export." : language === "uz" ? "PRO ish maydoni ikki-beshta emitentni metodologiya, manbalar va eksport bilan taqqoslaydi." : "PRO-рабочее пространство сравнивает от двух до пяти эмитентов, показывает методологию, источники и экспорт."}
  onUpgrade={() => setActiveView(token ? "profile" : "auth")}
/>}
{activeView === "compare" && hasProAccess && <section className="compare-layout">
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
                      {compareCompanies.map((value, index) => <div className="analysis-input-group" key={index}>
                          <label>
                            {ct(language, `company${index + 1}`)}
                            {index >= 2 && <span className="optional-tag">{ct(language, "optional")}</span>}
                          </label>
                          <div className="analysis-input-wrapper">
                            <span className="analysis-input-icon">{Icons.target}</span>
                            <input
                              list="compareCompaniesList"
                              value={value}
                              onChange={event => updateCompareCompany(index, event.target.value)}
                              placeholder={ct(language, "placeholder")}
                              autoComplete="off"
                              required={index < 2}
                            />
                          </div>
                        </div>)}
                    </div>
                    <datalist id="compareCompaniesList">
                      {companies.map(company => <option key={company.ticker} value={company.ticker}>
                          {company.company_name}
                        </option>)}
                    </datalist>

                    <div className="analysis-options-row">
                      <label className="analysis-checkbox">
                        <input type="checkbox" checked={compareAiSummary} onChange={event => setCompareAiSummary(event.target.checked)} />
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
                      {compareQuickCompanies.map(company => <button key={company.ticker} className="analysis-company-chip" type="button" onClick={() => addQuickCompareCompany(company.ticker)}>
                          <span className="chip-ticker">{company.ticker}</span>
                          <span className="chip-name">{company.company_name}</span>
                        </button>)}
                    </div>
                  </div>
                </article>

                {(compareResult || compareLoading) && <article className={`panel compare-overview-panel ${compareLoading ? "is-loading" : ""}`}>
                    <div className="panel-head">
                      <div>
                        <div className="panel-label">{ct(language, "overview")}</div>
                        <h2>{compareResult ? ct(language, "ready") : ct(language, "empty")}</h2>
                      </div>
                      {compareMessage ? <span className="status-badge muted">{compareMessage}</span> : null}
                      {compareResult && !compareLoading && <div className="compare-export-actions no-print">
                          <button className="ghost-btn result-export-btn" type="button" onClick={() => handleCompareExport("excel")} disabled={!!exportingCompare}>
                            {exportingCompare === "excel" ? language === "en" ? "Preparing…" : language === "uz" ? "Tayyorlanmoqda…" : "Готовим…" : language === "en" ? "⤓ Download Excel" : language === "uz" ? "⤓ Excel yuklab olish" : "⤓ Скачать Excel"}
                          </button>
                          <button className="ghost-btn result-export-btn" type="button" onClick={() => handleCompareExport("pdf")} disabled={!!exportingCompare}>
                            {exportingCompare === "pdf" ? language === "en" ? "Preparing…" : language === "uz" ? "Tayyorlanmoqda…" : "Готовим…" : language === "en" ? "⤓ Download PDF" : language === "uz" ? "⤓ PDF yuklab olish" : "⤓ Скачать PDF"}
                          </button>
                        </div>}
                    </div>

                    {compareLoading ? <div className="compare-loading-grid">
                        <div />
                        <div />
                        <div />
                      </div> : comparison ? <>
                        <div className="compare-summary-card">
                          <p>{compareSummary.short || ct(language, "noData")}</p>
                          <span>{ct(language, "normalizedNote")}</span>
                        </div>
                        <CompareLeaderCards leaders={comparison.leaders} language={language} />
                        <div className="compare-ranking-grid">
                          <CompareRanking title={ct(language, "ranking")} rows={comparison.ranking} scoreKey="score" language={language} />
                          <CompareRanking title={ct(language, "normalizedRanking")} rows={comparison.normalized_ranking} scoreKey="composite_score" language={language} />
                        </div>
                      </> : <div className="empty-state">
                        <p className="empty-copy">{ct(language, "empty")}</p>
                      </div>}
                  </article>}
              </section>}
{activeView === "compare" && hasProAccess && (compareResult || compareLoading) && <section className="compare-results-grid">
                <article className="panel compare-chart-main">
                  {comparePrimaryChart ? <CompareChartCard chart={comparePrimaryChart} language={language} /> : <div className="empty-state">
                      <p className="empty-copy">{compareLoading ? ct(language, "loading") : ct(language, "noData")}</p>
                    </div>}
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
                  {compareSummary.methodology ? <div className="compare-methodology">
                      <strong>{ct(language, "methodology")}</strong>
                      <p>{compareSummary.methodology}</p>
                    </div> : null}
                  {compareErrors.length ? <div className="compare-errors">
                      <strong>{ct(language, "errors")}</strong>
                      {compareErrors.map(error => <p key={`${error.company}-${error.error}`}>{error.company}: {error.error}</p>)}
                    </div> : null}
                </article>

                {compareSecondaryCharts.length ? <article className="panel compare-charts-panel">
                    <div className="panel-head">
                      <div>
                        <div className="panel-label">{ct(language, "charts")}</div>
                        <h2>{ct(language, "charts")}</h2>
                      </div>
                    </div>
                    <div className="compare-chart-grid">
                      {compareSecondaryCharts.map(chart => <CompareChartCard key={chart.id || chart.title} chart={chart} language={language} />)}
                    </div>
                  </article> : null}

                {Object.keys(compareTables).length ? <article className="panel compare-tables-panel">
                    <div className="panel-head">
                      <div>
                        <div className="panel-label">{ct(language, "tables")}</div>
                        <h2>{ct(language, "tables")}</h2>
                      </div>
                    </div>
                    <div className="compare-tables-grid">
                      {Object.entries(compareTables).map(([key, table]) => <CompareTable key={key} table={table} title={compareTableTitle(language, key)} language={language} />)}
                    </div>
                  </article> : null}
              </section>}
</>;
}
