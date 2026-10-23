import { useEffect, useRef, useState } from 'react';
import { comparisonText, translatedLabel } from './copy.js';
import { formatComparisonValue, METRICS, periodLabel } from './model.js';
import { num } from '../../lib/format.js';
import { safeHref } from '../../lib/safeHref.js';

export function ComparisonUpdates({updates, state, language}) {
  const ref = useRef(null);
  const [expanded, setExpanded] = useState(false);
  const tx = key => comparisonText(language, key);
  const {detail, markSeen} = updates;
  useEffect(() => {
    if (!detail || !ref.current) return;
    let sent = false;
    const observe = new IntersectionObserver(entries => {
      if (!sent && document.visibilityState === 'visible' && entries.some(entry => entry.isIntersecting)) {
        sent = true;markSeen();
      }
    }, {threshold: 0.1});
    const element = ref.current;observe.observe(element);
    const visible = () => { if (document.visibilityState === 'visible') {observe.unobserve(element);observe.observe(element);} };
    document.addEventListener('visibilitychange', visible);
    return () => {observe.disconnect();document.removeEventListener('visibilitychange', visible);};
  }, [detail, markSeen]);
  if (!updates.id) return null;
  const changes = detail?.changes || [];
  const stamp = detail?.last_seen_at ? new Date(detail.last_seen_at) : null;
  const date = stamp && !Number.isNaN(stamp.getTime()) ? stamp.toLocaleString(language === 'en' ? 'en-GB' : language === 'uz' ? 'uz-UZ' : 'ru-RU', {timeZone:'Asia/Tashkent',dateStyle:'medium',timeStyle:'short'}) : '';
  return <section ref={ref} className="cc-updates" role="region" aria-label={tx('updatesTitle')}>
    <header><h2>{tx('updatesTitle')}</h2>{date && <small>{tx('lastViewed')}: {date} · {tx('tashkentTime')}</small>}</header>
    {updates.loading && <p role="status">{tx('checkingUpdates')}</p>}
    {(updates.error || updates.seenError) && <div className="cc-update-error" role="alert"><span>{tx(updates.seenError ? 'seenError' : 'updatesError')}</span>
      <button type="button" className="cc-button" onClick={updates.retry}>{tx('refreshUpdates')}</button></div>}
    {detail && <>
      {changes.length === 0 && <p>{tx(detail.tracking_started ? 'trackingStarted' : 'nothingChanged')}</p>}
      <ul>{(expanded ? changes : changes.slice(0,6)).map((change,index) => {
        const metric = METRICS.find(item => item.key === change.metric);
        const label = metric ? translatedLabel(metric.label,language) : tx(change.kind);
        const link = safeHref(change.source?.url);
        return <li key={change.ticker + ':' + (change.metric || change.kind) + ':' + index}>
          <div className="cc-update-heading"><strong>{change.ticker}</strong><span>{label}</span>
            {metric && <small>{tx(change.kind)}</small>}</div>
          <div className="cc-update-values">
            {['new_period','period_changed'].includes(change.kind) ? <span>{periodLabel(change.before_period,language)} → {periodLabel(change.after_period,language)}</span>
              : change.kind === 'basis_changed' ? <span>{change.before_basis || '—'} → {change.after_basis || '—'}</span>
              : metric ? <span>{formatComparisonValue(change.before,metric,state,language)} → {formatComparisonValue(change.after,metric,state,language)}</span> : null}
            {metric && Number.isFinite(change.percent_change) && metric.type !== 'percent' && <strong>{change.percent_change > 0 ? '+' : ''}{num(change.percent_change,language,2)}%</strong>}
            {metric?.type === 'percent' && Number.isFinite(change.delta) && <strong>{change.delta > 0 ? '+' : ''}{num(change.delta,language,2)} {tx('percentagePoints')}</strong>}
          </div>
          <small className="cc-update-evidence">{change.before_date && change.after_date ? change.before_date + ' → ' + change.after_date : change.after_period ? periodLabel(change.after_period,language) : ''}
            {link && <> · <a href={link} target="_blank" rel="noreferrer">{tx('updateSource')} ↗</a></>}</small>
        </li>;
      })}</ul>
      {changes.length > 6 && <button className="cc-button" type="button" onClick={() => setExpanded(value => !value)}>{tx(expanded ? 'fewerUpdates' : 'allUpdates')} ({changes.length})</button>}
    </>}
  </section>;
}
