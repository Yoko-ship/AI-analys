import { changePeriodLabel } from "../../shared/marketPeriods.jsx";
import { formatCompactVolume, sessionCountLabel } from "../../shared/marketModel.jsx";
import { mt } from "../../shared/marketCopy.jsx";
import { formatRatio } from "../../shared/format.jsx";
import { CompanyLogo } from "../../shared/CompanyLogo.jsx";
export function MarketMovers({
  viewMode,
  periodMovers,
  lang,
  changePeriod,
  onOpenCompany,
  onAnalyze,
  smap
}) {
  return <>{viewMode === "table" && (periodMovers.topGainers.length > 0 || periodMovers.topLosers.length > 0 || periodMovers.topVolume.length > 0) && <div className="market-top-movers">
          {[
      // The two change panels carry the selected period in their heading:
      // «Топ роста» over a month and over a session are different claims,
      // and the strip is read at a glance without the control in view.
      {
        key: "up",
        title: `${mt(lang, "topGainers")}${changePeriod === "1d" ? "" : ` · ${changePeriodLabel(changePeriod, lang, "short")}`}`,
        rows: periodMovers.topGainers,
        value: r => `+${formatRatio(changePeriod === "1d" ? r.changePercent : r.periodPct, 2, lang)}%`
      }, {
        key: "down",
        title: `${mt(lang, "topLosers")}${changePeriod === "1d" ? "" : ` · ${changePeriodLabel(changePeriod, lang, "short")}`}`,
        rows: periodMovers.topLosers,
        value: r => `${formatRatio(changePeriod === "1d" ? r.changePercent : r.periodPct, 2, lang)}%`
      },
      // Ликвидность carries the period too, and over a window it says how
      // many sessions it added up and from which one: «5,6 млрд» over six
      // months means one thing across 80 sessions and quite another across
      // three, and the panel is read without the control in view.
      {
        key: "vol",
        title: `${mt(lang, "topLiquidity")}${changePeriod === "1d" ? "" : ` · ${changePeriodLabel(changePeriod, lang, "short")}`}`,
        rows: periodMovers.topVolume,
        value: r => formatCompactVolume(changePeriod === "1d" ? r.stockVolume : r.periodVolume, lang),
        hint: r => {
          if (changePeriod === "1d" || !r.periodSessions) return undefined;
          const from = String(r.periodFrom || "");
          const pretty = from.length === 8 ? `${from.slice(6)}.${from.slice(4, 6)}.${from.slice(0, 4)}` : from;
          const sessions = `${formatRatio(r.periodSessions, 0, lang)} ${sessionCountLabel(r.periodSessions, lang)}`;
          return pretty ? `${sessions} ${lang === "en" ? "since" : lang === "uz" ? "boshlab" : "с"} ${pretty}` : sessions;
        }
      }].map(col => <article className={`market-movers-col ${col.key}`} key={col.key}>
              <div className="market-movers-head">
                <span className={`market-movers-dot ${col.key}`} />
                <h3>{col.title}</h3>
              </div>
              <ul className="market-movers-list">
                {col.rows.length ? col.rows.map((r, index) => <li key={r.ticker}>
                    <button type="button" className="market-movers-item" title={col.hint ? col.hint(r) : undefined} onClick={() => onOpenCompany ? onOpenCompany(r.ticker) : onAnalyze(r.ticker)}>
                      <span className="market-movers-rank" aria-hidden="true">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <span className="market-movers-tk">
                        <CompanyLogo logo={smap[r.ticker]?.logo_url} name={r.name || r.ticker} ticker={r.ticker} />
                        <span className="market-movers-name">{r.ticker}</span>
                      </span>
                      <span className={`market-movers-chg ${col.key}`}>{col.value(r)}</span>
                    </button>
                  </li>) : <li className="market-movers-empty">—</li>}
              </ul>
            </article>)}
        </div>}</>;
}
