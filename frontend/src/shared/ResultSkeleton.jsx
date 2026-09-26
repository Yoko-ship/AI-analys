import { t } from "./i18n.jsx";

function ResultSkeleton({ language }) {
  return (
    <>
      <div className="score-strip">
        <div className="score-card skeleton-card">
          <div className="skeleton-line skeleton-line-lg" />
          <div className="skeleton-line skeleton-line-sm" />
        </div>
        <div className="score-meta">
          <div className="grade-pill skeleton-pill" />
          <div className="skeleton-line skeleton-line-lg" />
          <div className="skeleton-line skeleton-line-md" />
        </div>
      </div>
      <div className="chart-card">
        <div className="chart-head">
          <div>
            <div className="panel-label">{t(language, "analysis.chartTitle")}</div>
            <div className="skeleton-line skeleton-line-md" />
          </div>
          <div className="skeleton-pill" />
        </div>
        <div className="chart-skeleton">
          <div className="chart-skeleton-grid">
            <span />
            <span />
            <span />
            <span />
          </div>
          <div className="chart-skeleton-wave">
            <span />
            <span />
            <span />
          </div>
        </div>
      </div>
      <div className="market-strip">
        <div className="mini-market-card skeleton-card" />
        <div className="mini-market-card skeleton-card" />
        <div className="mini-market-card skeleton-card" />
      </div>
    </>
  );
}

export { ResultSkeleton };
