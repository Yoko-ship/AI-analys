import { TermInfo } from "../../shared/TermInfo.jsx";
import { normalizeLanguage } from "../../shared/i18n.jsx";
import { mt } from "../../shared/marketCopy.jsx";
import { formatRatio } from "../../shared/format.jsx";

function MarketStatIcon({ kind }) {
  if (kind === "turnover") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 7h11M13 4l3 3-3 3M19 17H8M11 14l-3 3 3 3" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 18V11M12 18V7M19 18V4M3 20h18" />
    </svg>
  );
}

function MarketStatCard({ label, value, sub, tone = "neutral", termId, lang, kind = "capitalization" }) {
  return (
    <article className={`market-stat-card tone-${tone} is-${kind}`}>
      <div className="market-stat-card-head">
        <span className="market-stat-icon"><MarketStatIcon kind={kind} /></span>
        <span className="market-stat-label">{label}{termId && <TermInfo termId={termId} lang={lang} label={label} />}</span>
      </div>
      <strong>{value}</strong>
      {sub ? <em>{sub}</em> : null}
    </article>
  );
}

function MarketBreadthCard({ language, advancers, decliners, topGrowth, topDrop }) {
  const lang = normalizeLanguage(language);
  const up = Math.max(0, Number(advancers) || 0);
  const down = Math.max(0, Number(decliners) || 0);
  const movers = up + down;
  const upShare = movers > 0 ? (up / movers) * 100 : 50;
  const downShare = 100 - upShare;
  const title = lang === "en" ? "Market breadth" : lang === "uz" ? "Bozor yo‘nalishi" : "Движение рынка";
  const shareLabel = lang === "en" ? "Share of moving securities" : lang === "uz" ? "O‘zgargan qimmatli qog‘ozlar ulushi" : "Доля среди изменившихся бумаг";
  return (
    <article className="market-breadth-card">
      <div className="market-stat-card-head">
        <span className="market-stat-icon is-breadth" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M4 15l5-5 4 3 7-8M16 5h4v4" /></svg>
        </span>
        <span className="market-stat-label">{title}</span>
      </div>
      <div className="market-breadth-metrics">
        <div className="market-breadth-metric is-up">
          <div className="market-breadth-value">
            <span><i aria-hidden="true">↗</i>{mt(lang, "advancers")}</span>
            <strong>{formatRatio(up, 0, lang)}</strong>
          </div>
          {topGrowth ? <em>{topGrowth}</em> : null}
        </div>
        <div className="market-breadth-metric is-down">
          <div className="market-breadth-value">
            <span><i aria-hidden="true">↘</i>{mt(lang, "decliners")}</span>
            <strong>{formatRatio(down, 0, lang)}</strong>
          </div>
          {topDrop ? <em>{topDrop}</em> : null}
        </div>
      </div>
      <div
        className="market-breadth-track"
        role="img"
        aria-label={`${shareLabel}: ${formatRatio(upShare, 0, lang)}% / ${formatRatio(downShare, 0, lang)}%`}
      >
        <span className="is-up" style={{ width: `${upShare}%` }} />
        <span className="is-down" style={{ width: `${downShare}%` }} />
      </div>
      <div className="market-breadth-legend" aria-hidden="true">
        <span>{formatRatio(upShare, 0, lang)}%</span>
        <span>{formatRatio(downShare, 0, lang)}%</span>
      </div>
    </article>
  );
}

export { MarketBreadthCard, MarketStatCard };
