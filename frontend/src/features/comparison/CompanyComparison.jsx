import { Fragment, useEffect, useRef, useState } from 'react';
import { CompanyLogo } from '../../shared/CompanyLogo.jsx';
import { num } from '../../lib/format.js';
import { comparisonText, translatedLabel } from './copy.js';
import { safeHref } from '../../lib/safeHref.js';
import { useComparisonData } from './useComparisonData.js';
import { useSavedComparisons } from './useSavedComparisons.js';
import { useComparisonUpdates } from './useComparisonUpdates.js';
import { ComparisonUpdates } from './ComparisonUpdates.jsx';
import {
  comparisonCsv, comparisonQuery, comparisonValue, formatComparisonValue,
  MAX_COMPANIES, METRICS, readComparison,
  apiQuery, comparisonMatches, periodLabel,
} from './model.js';
import './comparison.css';

function Icon({ name, size = 18 }) {
  const paths = {
    plus: 'M12 5v14M5 12h14',
    close: 'm6 6 12 12M6 18 18 6',
    search: 'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
    save: 'M6 3h12v18l-6-4-6 4z',
    download: 'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',
    compare: 'M4 4h6v16H4zM14 4h6v16h-6z',
    info: 'M12 11v6m0-10v.1M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
    arrow: 'M4 12h16m-5-5 5 5-5 5',
    trash: 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7',
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}

// Native dialogs supply keyboard containment, Escape and focus restoration.
function Dialog({ title, language, onClose, children, className = '' }) {
  const ref = useRef(null);
  const opener = useRef(document.activeElement);
  const titleId = 'cc-dialog-title';
  useEffect(() => {
    const dialog = ref.current;
    const trigger = opener.current;
    if (!dialog.open) dialog.showModal();
    return () => {
      if (dialog.open) dialog.close();
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);
  return <dialog ref={ref} className={'cc-dialog ' + className} aria-labelledby={titleId}
    onCancel={event => { event.preventDefault(); onClose(); }}
    onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); onClose(); } }}
    onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <header className="cc-dialog-head">
      <h2 id={titleId}>{title}</h2>
      <button className="cc-icon-button" type="button" onClick={onClose} aria-label={comparisonText(language, 'close')}><Icon name="close" /></button>
    </header>
    {children}
  </dialog>;
}

function CompanyPicker({ selected, replacing, language, onSelect, onClose, availableCompanies }) {
  const [query, setQuery] = useState('');
  const tx = key => comparisonText(language, key);
  const matches = availableCompanies.filter(company =>
    (company.name + ' ' + company.ticker).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return <Dialog title={tx('choose')} language={language} onClose={onClose} className="cc-picker">
    <label className="cc-search cc-picker-search">
      <Icon name="search" />
      <input type="search" autoFocus value={query} onChange={event => setQuery(event.target.value)}
        placeholder={tx('findCompany')} aria-label={tx('findCompany')} />
    </label>
    <div className="cc-picker-list">
      {['bank', 'corporate'].map(family => {
        const companies = matches.filter(company => company.family === family);
        return companies.length > 0 && <section key={family}>
          <h3>{tx(family === 'bank' ? 'banks' : 'corporate')}</h3>
          {companies.map(company => {
            const disabled = selected.includes(company.ticker) && company.ticker !== replacing;
            return <button className="cc-picker-option" type="button" key={company.ticker} disabled={disabled}
              onClick={() => onSelect(company.ticker)}>
              <CompanyLogo logo={company.logo} name={company.name} ticker={company.ticker} />
              <span><strong>{company.name}</strong><small>{company.ticker} · {tx(company.share_type === 'preferred' ? 'preferred' : 'ordinary')}</small></span>
              {disabled ? <small>{tx('alreadyAdded')}</small> : <Icon name="plus" />}
            </button>;
          })}
        </section>;
      })}
      {matches.length === 0 && <p className="cc-picker-empty">{tx('noCompanies')}</p>}
    </div>
    <p className="cc-dialog-foot">{tx('reported')}</p>
  </Dialog>;
}

function SaveDialog({ state, language, onSave, onClose, account, busy, error }) {
  const [name, setName] = useState(state.tickers.join(' / ') + ' · ' + state.period);
  const tx = key => comparisonText(language, key);
  return <Dialog title={tx('save')} language={language} onClose={onClose}>
    <form className="cc-save-form" onSubmit={event => { event.preventDefault(); if (name.trim()) onSave(name.trim()); }}>
      <label>{tx('name')}<input autoFocus maxLength={80} value={name} required
        onChange={event => setName(event.target.value)} /></label>
      <p>{tx(account ? 'account' : 'local')}</p>
      {error && <p role="alert">{tx(error === 'limit' ? 'saveLimit' : 'saveError')}</p>}
      <button type="submit" className="cc-button cc-button-primary" disabled={!name.trim() || busy}>{tx(busy ? 'saving' : 'saveAction')}</button>
    </form>
  </Dialog>;
}

function MetricTable({ state, companies, metrics, changes, language, onAdd, onReplace, onRemove, data }) {
  const tx = key => comparisonText(language, key);
  const canAdd = companies.length < MAX_COMPANIES;
  const columns = companies.length + (canAdd ? 1 : 0);
  const groups = ['income', 'balance', 'ratios'].filter(group => metrics.some(metric => metric.group === group));
  return <div className="cc-table-wrap" role="region" aria-label={tx('table')} tabIndex={0}>
    <table className="cc-table" style={{ '--cc-columns': columns }}>
      <caption className="sr-only">{tx('table')} · {periodLabel(data?.period || state.period, language)}</caption>
      <colgroup><col className="cc-metric-col" /><col span={columns} /></colgroup>
      <thead><tr>
        <th scope="col" className="cc-corner">
          <span className="cc-table-eyebrow">{tx('selected')}</span>
          <strong>{companies.length}<span> / {MAX_COMPANIES}</span></strong>
          <small>{tx(state.unit)}</small>
        </th>
        {companies.map(company => <th scope="col" key={company.ticker} className="cc-company-column">
          <div className="cc-company-top">
            <CompanyLogo logo={company.logo} name={company.name} ticker={company.ticker} />
            <span className="cc-ticker">{company.ticker}</span>
            <button type="button" className="cc-icon-button" aria-label={tx('remove') + ' ' + company.ticker}
              onClick={() => onRemove(company.ticker)}><Icon name="close" size={16} /></button>
          </div>
          <button type="button" className="cc-company-name" onClick={() => onReplace(company.ticker)}
            aria-label={tx('change') + ' ' + company.ticker}>{company.name}<span aria-hidden="true">⌄</span></button>
          <span className="cc-company-detail">{tx(company.family === 'bank' ? 'banks' : 'corporate')} · {tx(company.share_type === 'preferred' ? 'preferred' : 'ordinary')}</span>
        </th>)}
        {canAdd && <th scope="col" className="cc-add-column">
          <button className="cc-add-company" type="button" onClick={onAdd}><Icon name="plus" size={22} /><span>{tx('add')}</span></button>
        </th>}
      </tr></thead>
      <tbody>
        {groups.map(group => <Fragment key={group}>
          <tr className="cc-section"><th colSpan={columns + 1} scope="colgroup">
            <span>{tx(group)}</span>
          </th></tr>
          {metrics.filter(metric => metric.group === group).map(metric => {
            const label = translatedLabel(metric.label, language);
            return <tr key={metric.key} className={metric.key === 'net_profit' ? 'cc-key-row' : undefined}>
              <th scope="row" aria-label={label}>{label}
                <small>{metric.type === 'amount' ? tx(state.unit) : metric.type === 'price' ? tx('uzs') : metric.type === 'percent' ? '%' : '×'}</small>
              </th>
              {companies.map(company => {
                const cell = comparisonValue(company.ticker, metric.key, state, data);
                return <td key={company.ticker}>
                  {cell.value === null ? <span className="cc-missing" title={tx(cell.status === 'not_applicable' ? 'notApplicable' : 'notAvailable')}
                    aria-label={tx(cell.status === 'not_applicable' ? 'notApplicable' : 'notAvailable')}>—</span>
                    : <span className="cc-value" title={[cell.formula, cell.as_of, cell.note].filter(Boolean).join(" · ")}>{formatComparisonValue(cell.value, metric, state, language)}</span>}
                  {cell.base_period && <small className="cc-cell-basis">{cell.base_period}</small>}
                  {changes && cell.change !== null && <span className={'cc-change ' + (cell.change < 0 ? 'is-negative' : 'is-positive')}
                    title={tx('yoy')}><span aria-hidden="true">{cell.change < 0 ? '↘' : '↗'}</span> {cell.change > 0 ? '+' : ''}{num(cell.change, language, 1)}% <small>{language === 'ru' ? 'г/г' : language === 'uz' ? 'y/y' : 'YoY'}</small></span>}
                </td>;
              })}
              {canAdd && <td className="cc-empty-cell" aria-hidden="true" />}
            </tr>;
          })}
        </Fragment>)}
        {metrics.length === 0 && <tr><td colSpan={columns + 1} className="cc-no-metrics">{tx('noMetrics')}</td></tr>}
      </tbody>
    </table>
  </div>;
}

export function CompanyComparison({ language = 'ru', apiFetch = fetch, user, onSignIn }) {
  const tx = key => comparisonText(language, key);
  const [state, setState] = useState(() => readComparison(window.location.search));
  const [category, setCategory] = useState('all');
  const [query, setQuery] = useState('');
  const [changes, setChanges] = useState(true);
  const [picker, setPicker] = useState(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const saves = useSavedComparisons(user?.id, apiFetch);
  const { saved } = saves;
  const [message, setMessage] = useState('');
  const [savedMenuOpen, setSavedMenuOpen] = useState(false);
  const savedMenu = useRef(null);
  const financial = useComparisonData(state, apiFetch);
  const { options, loading, error, retry } = financial;
  const updates = useComparisonUpdates({userId:user?.id,apiFetch,saved,selection:state,menuOpen:savedMenuOpen});
  const data = comparisonMatches(updates.detail?.comparison,state) ? updates.detail.comparison : financial.data;
  const ready = comparisonMatches(data, state);
  const periodChoices = [...new Set([state.period, ...options.periods])].filter(p => p !== 'latest');

  useEffect(() => {
    window.history.replaceState(window.history.state, '', window.location.pathname + comparisonQuery(state) + window.location.hash);
  }, [state]);
  useEffect(() => {
    const restore = () => setState(readComparison(window.location.search));
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);

  const companies = state.tickers.map(ticker => (ready && data.companies.find(company => company.ticker === ticker))
    || options.companies.find(company => company.ticker === ticker) || { ticker, name: ticker, family: 'corporate' });
  const families = new Set(companies.map(company => company.family));
  const unavailable = ready && data.companies.some(company => company.status === 'unavailable');
  const metrics = METRICS.filter(metric =>
    metric.group !== 'market' && (!metric.family || families.has(metric.family))
    && (category === 'all' || (category === 'financial' ? ['income', 'balance'].includes(metric.group) : metric.group === category))
    && translatedLabel(metric.label, language).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const update = patch => { setState(current => ({ ...current, ...patch })); setMessage(''); };
  const selectCompany = ticker => {
    const tickers = picker.replacing ? state.tickers.map(item => item === picker.replacing ? ticker : item)
      : [...state.tickers, ticker];
    update({ tickers: [...new Set(tickers)].slice(0, MAX_COMPANIES) });
    setPicker(null);
  };
  const save = async name => {
    if (await saves.save(name, state)) { setSaveOpen(false); setMessage(tx(user ? 'accountSaved' : 'savedMessage')); }
  };
  const exportCsv = () => {
    const url = URL.createObjectURL(new Blob([comparisonCsv(state, language, data)], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'uzstock-comparison-' + (data?.period || state.period) + '.csv';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return <section className="cc-page" data-testid="company-comparison" aria-labelledby="cc-title">
    <header className="cc-page-head">
      <div><p className="cc-eyebrow"><Icon name="compare" size={14} />{tx('eyebrow')}</p>
        <h1 id="cc-title">{tx('title')}</h1><p className="cc-subtitle">{tx('subtitle')}</p></div>
      <div className="cc-page-actions">
        <details className="cc-saved" ref={savedMenu} onToggle={event => setSavedMenuOpen(event.currentTarget.open)}>
          <summary className="cc-button"><Icon name="save" /><span>{tx('saved')}</span><span className="cc-count">{saved.length}</span></summary>
          <div className="cc-saved-menu"><small>{tx(user ? 'account' : 'local')}</small>
            {saves.loading && <p>{tx('loadingSaved')}</p>}
            {!saves.loading && !saves.loadError && saved.length === 0 && <p>{tx('savedEmpty')}</p>}
            {saved.map(item => <div key={item.id}>
              <button type="button" aria-label={item.name} onClick={() => { setState(readComparison(item.query)); setMessage(''); savedMenu.current.open = false; }}>{item.name}
                {updates.checks[item.id]?.updated && <span className="cc-update-badge">{tx('updatedBadge')}</span>}
                {updates.checks[item.id]?.failed && <small className="cc-update-check-error">{tx('checkUnavailable')}</small>}</button>
              <button type="button" className="cc-icon-button" disabled={saves.busy || saves.loading} aria-label={tx('delete') + ' ' + item.name}
                onClick={() => saves.remove(item.id)}><Icon name="trash" size={16} /></button>
            </div>)}
            {user && saves.browserSaved.length > 0 && <button className="cc-button" type="button" disabled={saves.busy || saves.loading || saves.loadError}
              onClick={saves.importBrowser}>{tx('importBrowser')} ({saves.browserSaved.length})</button>}
            {!user && onSignIn && <button type="button" className="cc-button" onClick={onSignIn}>{tx('signInSave')}</button>}
          </div>
        </details>
        <button className="cc-button" type="button" disabled={!ready} onClick={exportCsv} aria-label={tx('export')}>
          <Icon name="download" />{tx('exportShort')}</button>
        <button className="cc-button" type="button" disabled={!ready}
          onClick={() => window.location.assign('/api/company-comparison/export.xlsx' + apiQuery(state))}>
          <Icon name="download" />{tx('exportExcel')}</button>
        <button className="cc-button cc-button-primary" type="button" disabled={companies.length < 2 || saves.loading || saves.busy}
          onClick={() => { saves.clearError();setSaveOpen(true); }}>
          <Icon name="plus" />{tx('save')}</button>
      </div>
    </header>

    <div className="cc-preview-note"><span><span className="cc-preview-dot" />{tx('reported')}</span>
      <p>{tx('periodContext')}: {periodLabel(ready ? data.period : state.period, language)} · {state.standard} · {tx(state.scope)}</p><button type="button" onClick={() => setSourcesOpen(true)} aria-label={tx('source')}><Icon name="info" size={16} /></button></div>

    <div className="cc-controls">
      <label><span>{tx('period')}</span><select aria-label={tx('period')} value={state.period} onChange={event => update({ period: event.target.value })}>
        <option value="latest">{tx('latest')}</option>
        {periodChoices.map(period => <option key={period} value={period}>{periodLabel(period, language)}</option>)}
      </select></label>
      <label><span>{tx('standard')}</span><select aria-label={tx('standard')} value={state.standard} onChange={event => update({ standard: event.target.value })}>
        <option value="NSBU">{language === 'ru' ? 'НСБУ' : 'NSBU'}</option><option value="IFRS">{language === 'ru' ? 'МСФО' : 'IFRS'}</option>
      </select></label>
      <label><span>{tx('scope')}</span><select aria-label={tx('scope')} value={state.scope} onChange={event => update({ scope: event.target.value })}>
        <option value="separate">{tx('separate')}</option><option value="consolidated">{tx('consolidated')}</option>
      </select></label>
      <label><span>{tx('unit')}</span><select aria-label={tx('unit')} value={state.unit} onChange={event => update({ unit: event.target.value })}>
        <option value="billion">{tx('billion')}</option><option value="million">{tx('million')}</option>
      </select></label>
    </div>

    {user && <p className="cc-message">{tx('account')}</p>}
    {saves.loadError && <div className="cc-notice" role="alert"><span>{tx('savedLoadError')}</span>
      <button type="button" className="cc-button" onClick={saves.retry}>{tx('retrySaved')}</button></div>}
    {saves.writeError && !saveOpen && <p className="cc-notice" role="alert">{tx(saves.writeError === 'limit' ? 'saveLimit' : saves.writeError === 'delete' ? 'deleteError' : 'saveError')}</p>}
    {message && <p className="cc-message" role="status">{message}</p>}
    {loading && <p className="cc-notice" role="status">{tx("loading")}</p>}
    {error && <div className="cc-notice" role="alert"><span>{tx("error")}</span><button type="button" className="cc-button" onClick={retry}>{tx("retry")}</button></div>}
    <ComparisonUpdates key={updates.id || 'none'} updates={updates} state={state} language={language} />
    {companies.length === 0 ? <div className="cc-empty">
      <span className="cc-empty-icon"><Icon name="compare" size={28} /></span><h2>{tx('emptyTitle')}</h2><p>{tx('emptyText')}</p>
      <button type="button" className="cc-button cc-button-primary" onClick={() => setPicker({ replacing: null })}><Icon name="plus" />{tx('add')}</button>
    </div> : <>
      {unavailable && <p className="cc-notice" role="status"><Icon name="info" />{tx('noStatements')}</p>}
      {families.size > 1 && <p className="cc-notice" role="note"><Icon name="info" />{tx('mixed')}</p>}
      {companies.length === 1 && <p className="cc-notice"><Icon name="info" />{tx('addAnother')}</p>}
      <div className="cc-table-tools">
        <div className="cc-categories" role="group" aria-label={tx('metric')}>
          {['all', 'financial', 'ratios'].map(key => <button key={key} type="button" aria-pressed={category === key}
            onClick={() => setCategory(key)}>{tx(key)}</button>)}
        </div>
        <div className="cc-table-options">
          <label className="cc-changes"><input type="checkbox" checked={changes} onChange={event => setChanges(event.target.checked)} />{tx('changes')}</label>
          <label className="cc-search"><Icon name="search" size={16} /><input type="search" value={query}
            onChange={event => setQuery(event.target.value)} placeholder={tx('searchMetrics')} aria-label={tx('searchMetrics')} /></label>
        </div>
      </div>
      <p className="cc-scroll-hint"><Icon name="arrow" size={14} />{tx('scroll')}</p>
      <MetricTable data={ready ? data : null} state={state} companies={companies} metrics={metrics} language={language} changes={changes}
        onAdd={() => setPicker({ replacing: null })} onReplace={ticker => setPicker({ replacing: ticker })}
        onRemove={ticker => update({ tickers: state.tickers.filter(item => item !== ticker) })} />
      <footer className="cc-table-foot"><p>{tx('tableNote')}</p>
        <button type="button" onClick={() => setSourcesOpen(true)}><Icon name="info" size={15} />{tx('source')}</button></footer>
    </>}

    {picker && <CompanyPicker availableCompanies={options.companies} selected={state.tickers} replacing={picker.replacing} language={language}
      onSelect={selectCompany} onClose={() => setPicker(null)} />}
    {saveOpen && <SaveDialog state={state} language={language} onSave={save} account={Boolean(user)} busy={saves.busy}
      error={saves.writeError} onClose={() => setSaveOpen(false)} />}
    {sourcesOpen && <Dialog title={tx('sourceTitle')} language={language} onClose={() => setSourcesOpen(false)}>
      <div className="cc-source-body"><span className="cc-source-badge">{tx('reported')}</span><p>{tx('sourceText')}</p>
        <dl><div><dt>{tx('standard')}</dt><dd>{state.standard}</dd></div>
          <div><dt>{tx('period')}</dt><dd>{periodLabel(ready ? data.period : state.period, language)}</dd></div>
          <div><dt>{tx('scope')}</dt><dd>{tx(state.scope)}</dd></div></dl>
        {(ready ? data.companies : []).map(company => <section className="cc-source-company" key={company.ticker}>
          <h3>{company.ticker} · {company.name}</h3>
          {[...new Map(Object.values(company.metrics).filter(cell => safeHref(cell.source?.url)).map(cell => [cell.source.url, cell.source])).values()].map(source =>
            <p key={source.url}><a href={safeHref(source.url)} target="_blank" rel="noreferrer">{tx('filing')} ↗</a>
              <small>{source.period || ''} {source.publication_date || source.as_of || ''}</small></p>)}
          {!company.source?.url && <p>{tx('notAvailable')}</p>}
        </section>)}
        <button type="button" className="cc-button" onClick={() => setSourcesOpen(false)}>{tx('close')}</button></div>
    </Dialog>}
  </section>;
}
