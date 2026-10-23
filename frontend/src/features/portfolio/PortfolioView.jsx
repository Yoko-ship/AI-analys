import React from 'react';
import { normalizeLanguage } from '../../shared/i18n.jsx';
import { formatMarketNumber, formatRatio, formatChangePercent } from '../../lib/numberFormat.js';
import { portfolioCopy, portfolioError } from './copy.js';
import { usePortfolio } from './usePortfolio.js';
import { TransactionForm } from './TransactionForm.jsx';

export function PortfolioView({ language, apiFetch, signedIn, onSignIn, onOpenCompany }) {
  const lang = normalizeLanguage(language);
  const text = portfolioCopy(lang);
  const { data, loading, refreshError, refresh, beginMutation, endMutation } = usePortfolio(apiFetch, signedIn);
  const [editor, setEditor] = React.useState(null);
  const [deleting, setDeleting] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  const [notice, setNotice] = React.useState('');
  const [visibleCount, setVisibleCount] = React.useState(20);
  const addButton = React.useRef(null);
  const money = value => value == null ? '—' : `${formatMarketNumber(value, lang)} UZS`;
  const tone = value => value == null || Number(value) === 0 ? '' : Number(value) > 0 ? 'pos' : 'neg';
  const closeEditor = () => { setEditor(null); addButton.current?.focus(); };
  const saved = async () => { closeEditor(); setNotice(text('saved')); await refresh(); };
  const edit = transaction => {
    setEditor({ transaction }); setDeleting(null); setError(''); setNotice('');
    requestAnimationFrame(() => document.getElementById('portfolio-form-title')?.scrollIntoView({ behavior: 'instant', block: 'center' }));
  };
  const remove = async transaction => {
    if (busy) return;
    setBusy(true); setError(''); beginMutation();
    try {
      const response = await apiFetch(`/api/portfolio/transactions/${encodeURIComponent(transaction.id)}?version=${transaction.version}`, { method: 'DELETE' });
      const body = await response.json().catch(() => null);
      if (!response.ok || !body?.ok) throw new Error(portfolioError(response, body, text));
      setDeleting(null); setNotice(text('deleted')); await refresh();
    } catch (err) { setError(err.message || text('failed')); }
    finally { setBusy(false); endMutation(); }
  };
  if (!signedIn) return <section className="pro-gate panel" aria-label={text('title')}>
    <h1>{text('title')}</h1>
    <p>{text('gate')}</p>
    <p className="muted">{text('signInHelp')}</p>
    <button type="button" className="primary-btn" onClick={onSignIn}>{text('signIn')}</button>
  </section>;
  const records = [...(data?.transactions || [])].reverse();
  const checked = data?.checked_at ? new Date(data.checked_at).toLocaleTimeString(lang === 'uz' ? 'uz-UZ' : lang, { hour: '2-digit', minute: '2-digit' }) : null;
  return <section className="portfolio-view stack">
    <header className="portfolio-heading">
      <div><span className="portfolio-eyebrow">{text('manual')}</span><h1>{text('title')}</h1><p>{text('intro')}</p></div>
      <button ref={addButton} type="button" className="primary-btn" onClick={() => edit(null)} disabled={Boolean(editor) || busy || !data}>{text('record')}</button>
    </header>
    <div className="portfolio-refresh"><span>{text('auto')}{checked ? ` · ${text('checked')} ${checked}` : ''}</span><button type="button" className="secondary-btn" onClick={refresh} disabled={busy}>{text('refresh')}</button></div>
    {refreshError && <div className="portfolio-warning" role="alert"><span>{text('refreshError')}</span><button type="button" className="secondary-btn" onClick={refresh}>{text('retry')}</button></div>}
    {error && <p className="portfolio-error" role="alert">{error}</p>}
    {notice && <p className="portfolio-notice" role="status">{notice}</p>}
    {editor && <TransactionForm key={editor.transaction?.id || 'new'} transaction={editor.transaction}
      instruments={data?.instruments || []} apiFetch={apiFetch} text={text} onCancel={closeEditor} onSaved={saved}
      beginMutation={beginMutation} endMutation={endMutation} />}
    {loading && !data ? <p className="portfolio-loading" role="status">{text('loading')}</p> : data && <>
      <article className="portfolio-summary panel">
        <div className="portfolio-value"><span className="portfolio-eyebrow">{text('value')}</span><strong data-testid="portfolio-market-value">{money(data.market_value)}</strong><span className="muted">{data.priced_count} / {data.count} {text('priced')}</span></div>
        <dl className="portfolio-metrics">
          {[['basis', data.cost_value], ['unrealized', data.unrealized_pnl], ['realized', data.realized_pnl], ['dividends', data.dividend_income]].map(([label, value]) => <div key={label}><dt>{text(label)}</dt><dd className={label === 'basis' ? '' : tone(value)}>{money(value)}</dd></div>)}
        </dl>
        <div className="portfolio-summary-foot"><p>{text('cadence')}</p><span>{text('total')} <b className={tone(data.total_pnl)}>{money(data.total_pnl)}</b></span></div>
      </article>
      {!data.valuation_complete && <p className="portfolio-warning">{text('incomplete')}</p>}
      <article className="panel portfolio-holdings">
        <div className="panel-head"><h2>{text('holdings')}</h2><span className="muted">{data.count}</span></div>
        {!data.items.length ? <div className="portfolio-empty"><span className="portfolio-empty-mark" aria-hidden="true">＋</span><h3>{text(records.length ? 'closed' : 'empty')}</h3><p>{text(records.length ? 'closedHelp' : 'emptyHelp')}</p></div> : <div className="table-wrap"><table aria-label={text('holdings')}>
          <thead><tr>{['security', 'quantity', 'average', 'lastPrice', 'positionValue'].map(key => <th key={key}>{text(key)}</th>)}<th>P/L</th><th>{text('allocation')}</th></tr></thead>
          <tbody>{data.items.map(item => <tr key={item.ticker}>
            <td><button type="button" className="rowlink" onClick={() => onOpenCompany?.(item.ticker)}><b>{item.ticker}</b><span className="meta">{item.company_name}</span></button></td>
            <td>{formatRatio(item.quantity, 6, lang)}</td><td>{money(item.average_cost)}</td>
            <td>{item.last_price == null ? <span className="muted">{text('missing')}</span> : <><b>{money(item.last_price)}</b><time className="meta" dateTime={item.price_date}>{item.price_date}</time></>}</td>
            <td>{money(item.market_value)}</td><td className={tone(item.unrealized_pnl)}>{money(item.unrealized_pnl)}<span className="meta">{formatChangePercent(item.unrealized_pnl_pct, lang)}</span></td>
            <td>{item.allocation_pct == null ? '—' : <div className="portfolio-weight"><span>{formatRatio(item.allocation_pct, 1, lang)}%</span><meter min="0" max="100" value={Number(item.allocation_pct)} aria-label={`${item.ticker} ${text('allocation')}`} /></div>}</td>
          </tr>)}</tbody>
        </table></div>}
      </article>
      <article className="panel portfolio-history"><div className="panel-head"><h2>{text('history')}</h2><span className="muted">{records.length}</span></div>
        {!records.length ? <p className="portfolio-no-history muted">{text('noHistory')}</p> : <div className="table-wrap"><table aria-label={text('history')}>
          <thead><tr>{['date', 'kind', 'security', 'quantity', 'price', 'fees', 'actions'].map(key => <th key={key}>{text(key)}</th>)}</tr></thead>
          <tbody>{records.slice(0, visibleCount).map(row => <React.Fragment key={row.id}><tr>
            <td>{row.trade_date || '—'}</td><td><span className={`portfolio-kind kind-${row.kind}`}>{text(row.kind)}</span></td>
            <td><b>{row.ticker}</b>{row.note && <span className="meta portfolio-record-note">{row.note}</span>}</td>
            <td>{row.kind === 'dividend' ? '—' : formatRatio(row.quantity, 6, lang)}</td><td>{money(row.kind === 'dividend' ? row.amount : row.price)}{row.kind === 'dividend' && <span className="meta">{text('amount')}</span>}</td><td>{money(row.fees)}</td>
            <td><div className="portfolio-row-actions"><button type="button" className="secondary-btn" disabled={busy || Boolean(editor)} onClick={() => edit(row)} aria-label={`${text('edit')} ${row.ticker} ${lang === 'en' ? 'transaction' : text('kind').toLowerCase()}`}>{text('edit')}</button><button type="button" className="secondary-btn" disabled={busy || Boolean(editor)} onClick={() => { setDeleting(row.id); setError(''); }} aria-label={`${text('delete')} ${row.ticker} ${lang === 'en' ? 'transaction' : text('kind').toLowerCase()}`}>{text('delete')}</button></div></td>
          </tr>{deleting === row.id && <tr><td colSpan={7}><div className="portfolio-delete-confirm"><span>{text('deleteHelp')}</span><button className="secondary-btn" type="button" disabled={busy} onClick={() => remove(row)}>{text('confirmDelete')}</button><button className="secondary-btn" type="button" disabled={busy} onClick={() => setDeleting(null)}>{text('cancel')}</button></div></td></tr>}</React.Fragment>)}</tbody>
        </table></div>}
        {records.length > visibleCount && <button type="button" className="secondary-btn portfolio-more" onClick={() => setVisibleCount(n => n + 20)}>{text('more')}</button>}
      </article>
      <p className="portfolio-method muted">{text('method')}</p>
    </>}
  </section>;
}
