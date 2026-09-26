import { buildSparkline } from "./chartModel.jsx";
import { vt } from "./i18n.jsx";

function StatCard({ label, value, sub }) {
  return (
    <article className="profile-stat-card">
      <div className="profile-stat-label">{label}</div>
      <div className="profile-stat-value">{value}</div>
      <div className="profile-stat-sub">{sub}</div>
    </article>
  );
}

function DisclosureCard({ label, title, intro, items, tone = "neutral" }) {
  return (
    <article className={`panel disclosure-card tone-${tone}`}>
      <div className="panel-head">
        <div>
          <div className="panel-label">{label}</div>
          <h2>{title}</h2>
        </div>
      </div>
      <p className="panel-intro">{intro}</p>
      <ul className="disclosure-list">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </article>
  );
}

function WorkspacePageHeader({ id, eyebrow, title, description, icon, actions, children }) {
  return (
    <header className="workspace-page-header">
      <div className="workspace-page-heading-row">
        <div className="workspace-page-title-group">
          {icon ? <span className="workspace-page-icon" aria-hidden="true">{icon}</span> : null}
          <div>
            <div className="workspace-page-eyebrow">{eyebrow}</div>
            <h1 id={id}>{title}</h1>
            {description ? <p>{description}</p> : null}
          </div>
        </div>
        {actions ? <div className="workspace-page-actions">{actions}</div> : null}
      </div>
      {children}
    </header>
  );
}

function MiniSparkline({ values, tone = "neutral", language }) {
  const data = buildSparkline(values);

  if (!data) {
    return <div className="mini-sparkline-empty" aria-label={vt(language, "sparklineEmpty")} />;
  }

  return (
    <svg className={`mini-sparkline tone-${tone}`} viewBox={`0 0 ${data.width} ${data.height}`} role="img" aria-label={vt(language, "dashboardPeriod")}>
      <path d={data.areaPath} className="mini-sparkline-area" />
      <path d={data.path} className="mini-sparkline-line" />
      {data.points.map((point, index) => {
        if (index !== data.points.length - 1) return null;
        const x = data.points.length <= 1 ? data.width / 2 : 8 + (index / (data.points.length - 1)) * (data.width - 16);
        const y = 10 + ((data.max - point) / (data.max - data.min || 1)) * (data.height - 22);
        return <circle key={index} cx={x} cy={y} r="4" className="mini-sparkline-dot" />;
      })}
    </svg>
  );
}

function DashboardMetricCard({ label, value, sub, tone = "neutral", sparkline, language }) {
  return (
    <article className={`dashboard-metric-card tone-${tone}`}>
      <div className="dashboard-metric-top">
        <div>
          <div className="profile-stat-label">{label}</div>
          <div className="profile-stat-value">{value}</div>
        </div>
        <span className="metric-pulse" />
      </div>
      <MiniSparkline values={sparkline} tone={tone} language={language} />
      <div className="profile-stat-sub">{sub}</div>
    </article>
  );
}

export { WorkspacePageHeader };
