import { t } from "../../shared/i18n.jsx";

function ActivityChart({ series, language }) {
  const hasData = Boolean(series?.days?.some((day) => day.count > 0));

  if (!hasData) {
    return (
      <div className="activity-chart empty-state">
        <p className="empty-copy">{t(language, "dashboard.activityEmpty")}</p>
      </div>
    );
  }

  const width = 1000;
  const height = 280;
  const padding = { left: 20, right: 20, top: 20, bottom: 44 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const barGap = 12;
  const barWidth = (innerWidth - barGap * (series.days.length - 1)) / series.days.length;

  return (
    <div className="activity-chart">
      <svg className="activity-chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t(language, "dashboard.activityTitle")}>
        <defs>
          <linearGradient id="activityBarGradient" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.92" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.22" />
          </linearGradient>
        </defs>
        {series.days.map((day, index) => {
          const barHeight = ((day.count || 0) / series.maxCount) * innerHeight;
          const x = padding.left + index * (barWidth + barGap);
          const y = padding.top + innerHeight - barHeight;
          const hasActivity = day.count > 0;
          return (
            <g key={day.key}>
              <rect x={x} y={padding.top} width={barWidth} height={innerHeight} rx="16" className={`activity-bar-track ${hasActivity ? "has-activity" : ""}`} />
              {hasActivity && <rect x={x} y={y} width={barWidth} height={barHeight} rx="16" className="activity-bar" />}
              <text x={x + barWidth / 2} y={height - 16} textAnchor="middle" className={`activity-axis-label ${hasActivity ? "has-activity" : ""}`}>
                {day.shortLabel}
              </text>
              <text x={x + barWidth / 2} y={Math.max(y - 10, 16)} textAnchor="middle" className={`activity-value ${hasActivity ? "has-activity" : ""}`}>
                {day.count}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="activity-footer">
        <div>
          <span className="activity-footer-label">{t(language, "dashboard.activityCopy")}</span>
          <strong>{series.total}</strong>
        </div>
        <div>
          <span className="activity-footer-label">{t(language, "dashboard.peak")}</span>
          <strong>{series.peak ? series.peak.label : "—"}</strong>
        </div>
      </div>
    </div>
  );
}

export {  };
