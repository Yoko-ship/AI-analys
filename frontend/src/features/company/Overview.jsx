import { formatMarketNumber, safeNumber } from "../../shared/format.jsx";
import { CompanyPriceChart } from "../../shared/CompanyPriceChart.jsx";
import { QuickCompareStrip } from "../../shared/QuickCompareStrip.jsx";
import { QC_COLORS } from "../../shared/priceChartModel.jsx";
import { CompanyRegistryCard } from "./Registry.jsx";
import { CompanyKeyStats } from "./keyStats.jsx";
import { sectorLabel } from "../../shared/marketCopy.jsx";
import React from "react";
import { companyReportPresentation, reportFormLabel } from "../../lib/reportPresentation.js";

function CompanyOverviewTab({ sec, ticker, priceHistory, priceLoading, priceAdjustments, intraday, priceRange, onRangeChange, lang, infoLoading, registryData, registryLoading, registryError, onRegistryRetry, securityType, isPreferred, industry, marketRow, priceMetrics, metrics12, mult, dividends, lastPrice, watchRail, compare, onExpandChart }) {
  const nominalVal = safeNumber(marketRow?.nominal) || null;

  return (
    <div className="company-overview-layout">
      {/* Three columns at full width, MSN's shape: the watchlist on the left,
          the security in the middle, its numbers on the right. Valuation,
          profitability and the session all come from /api/market/multiples and
          the board row, so nothing here is recomputed and nothing can disagree
          with the market table. */}
      <div className="company-hero-grid">
        <div className="company-hero-watch">{watchRail}</div>
        <div className="company-hero-main">
          <div className="company-chart-panel panel">
            {/* The metrics response still decides whether candles mean anything
                here (`quality`) and how long a moving average is (`ma_windows`);
                only its numbers stopped being printed. */}
            <CompanyPriceChart history={priceHistory} loading={priceLoading} range={priceRange} onRangeChange={onRangeChange} adjustments={priceAdjustments} lang={lang}
              intraday={intraday} quality={priceMetrics?.quality} metricsWindows={priceMetrics?.ma_windows}
              ticker={ticker} compare={compare?.series} compareLoading={compare?.loading} compareTools={compare}
              onExpand={onExpandChart} />
            {/* Inside the chart panel, as on the reference page: the strip is a
                control for the chart above it, not a section of its own. */}
            {compare && (
              <QuickCompareStrip peers={compare.peers} securitiesMap={compare.securitiesMap}
                selected={compare.selected} colors={QC_COLORS} onToggle={compare.onToggle}
                lang={lang} loading={compare.loading} />
            )}
          </div>
          <div className="company-overview-main">
            <h3 className="co-heading">{lang === "ru" ? "О компании" : lang === "uz" ? "Kompaniya haqida" : "About the company"}</h3>
            {sec.company_description ? (
              <>
                <p className="company-description-text">{sec.company_description}</p>
                {sec.source_url && (
                  <a href={sec.source_url} target="_blank" rel="noreferrer" className="wiki-link">
                    {sec.info_source === "wikipedia"
                      ? (lang === "ru" ? "Читать на Википедии →" : lang === "uz" ? "Vikipediyada o'qish →" : "Read on Wikipedia →")
                      : (lang === "ru" ? "Официальный сайт →" : lang === "uz" ? "Rasmiy sayt →" : "Official website →")}
                  </a>
                )}
              </>
            ) : infoLoading ? (
              <div className="company-desc-skeleton" aria-hidden="true">
                <span /><span /><span /><span style={{ width: "62%" }} />
              </div>
            ) : (
              <p className="muted" style={{ fontSize: 14 }}>{lang === "ru" ? "Информация о компании недоступна." : lang === "uz" ? "Kompaniya haqida ma'lumot mavjud emas." : "Company information is currently unavailable."}</p>
            )}
            <CompanyRegistryCard data={registryData} loading={registryLoading} error={registryError} onRetry={onRegistryRetry} lang={lang} />
          </div>
        </div>

        {/* Everything the page states ABOUT THIS SECURITY, in one column: the
            session, the year's range, the multiples, the returns — and under
            them the two reference blocks. They belong here by subject. The left
            rail is other people's securities, and an issuer's own dividend
            history read oddly in a column of peers.
            The 2026-08-08 note under this comment recorded the cost of a long
            rail: six blocks ran to 1521px against a 1029px main column. It is
            back, smaller — measured after this change at 1920px, the rail ends
            below the main column rather than level with it. That is the trade
            the customer chose: subject over balance. */}
        <div className="company-overview-sidebar">
          <CompanyKeyStats row={marketRow} sec={sec} metrics12={metrics12} mult={mult}
            metricsWindow={priceMetrics} range={priceRange}
            dividends={dividends} lastPrice={lastPrice} securityType={securityType} lang={lang}
            placement="rail" />
          <CompanyKeyStats row={marketRow} sec={sec} metrics12={metrics12} mult={mult}
            dividends={dividends} lastPrice={lastPrice} securityType={securityType} lang={lang}
            placement="lower" />
          <div className="co-sidebar-block">
            <h3 className="co-heading">{lang === "ru" ? "Детали" : lang === "uz" ? "Tafsilotlar" : "Details"}</h3>
            <div className="company-metrics-list">
              {sec.isin && <div className="company-metric-row"><span className="panel-label">ISIN</span><span className="isin-mono">{sec.isin}</span></div>}
              {nominalVal && <div className="company-metric-row"><span className="panel-label">{lang === "ru" ? "Номинал" : lang === "uz" ? "Nominal" : "Nominal"}</span><span>{formatMarketNumber(nominalVal, lang)} UZS</span></div>}
              {industry && <div className="company-metric-row"><span className="panel-label">{lang === "ru" ? "Отрасль" : lang === "uz" ? "Soha" : "Sector"}</span><span>{sectorLabel(lang, industry)}</span></div>}
              {securityType && <div className="company-metric-row"><span className="panel-label">{lang === "ru" ? "Тип" : lang === "uz" ? "Turi" : "Type"}</span><span>{securityType === "bond" ? (lang === "ru" ? "Облигация" : lang === "uz" ? "Obligatsiya" : "Bond") : (lang === "ru" ? "Акция" : lang === "uz" ? "Aksiya" : "Stock")}</span></div>}
              {securityType !== "bond" && (
                <div className="company-metric-row">
                  <span className="panel-label">{lang === "ru" ? "Класс" : lang === "uz" ? "Sinf" : "Class"}</span>
                  <span>{isPreferred ? (lang === "ru" ? "Привилегированная" : lang === "uz" ? "Imtiyozli" : "Preferred") : (lang === "ru" ? "Обыкновенная" : lang === "uz" ? "Oddiy" : "Common")}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

    </div>
  );
}

function CompanyReportsTab({ reports, lang }) {
  const forms = [...new Set((reports || []).map((r) => r.report_form))];
  const [form, setForm] = React.useState(forms[0] || null);
  // Keyed on the actual form set, not reports.length: two companies with the
  // same report count but different form types used to keep a stale filter
  // and show "no reports" even though reports existed.
  const formsKey = forms.join("|");
  React.useEffect(() => {
    if (forms.length > 0 && !forms.includes(form)) setForm(forms[0]);
  }, [formsKey]);
  const visible = form ? reports.filter((r) => r.report_form === form) : reports;
  return (
    <div>
      {forms.length > 1 && (
        <div className="company-chart-ranges" style={{ marginBottom: 12 }}>
          {forms.map((f) => (
            <button key={f} type="button" className={`range-btn ${form === f ? "active" : ""}`} onClick={() => setForm(f)}>{reportFormLabel(f, lang)}</button>
          ))}
        </div>
      )}
      {visible.length === 0 ? (
        <div className="panel" style={{ padding: 32, textAlign: "center" }}>
          <p className="muted">{lang === "ru" ? "Отчётов не найдено" : "No reports found"}</p>
        </div>
      ) : (
        <div className="company-reports-list">
          {visible.map((r, i) => {
            const presentation = companyReportPresentation(r, lang);
            return (
              <div key={i} className="company-report-row panel">
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{presentation.title}</div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {presentation.periodType} · {r.year}{r.quarter ? ` Q${r.quarter}` : ""} · {presentation.formLabel}
                  </div>
                  {presentation.description && <div className="company-report-description">{presentation.description}</div>}
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  {r.excel_url && <a href={r.excel_url} target="_blank" rel="noreferrer" className="ghost-btn" style={{ fontSize: 12 }}>Excel →</a>}
                  {r.excel_url_form1 && r.excel_url_form1 !== r.excel_url && <a href={r.excel_url_form1} target="_blank" rel="noreferrer" className="ghost-btn" style={{ fontSize: 12 }}>{lang === "ru" ? "Баланс →" : lang === "uz" ? "Balans →" : "Balance →"}</a>}
                  {r.pdf_url && !r.pdf_url.includes("/reports/to_pdf") && <a href={r.pdf_url} target="_blank" rel="noreferrer" className="ghost-btn" style={{ fontSize: 12 }}>PDF →</a>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export { CompanyOverviewTab, CompanyReportsTab };
