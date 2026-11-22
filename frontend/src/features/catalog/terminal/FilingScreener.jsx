import React from 'react';
import {localizedPath} from '../../../lib/languagePath.js';
import {words} from '../../../shared/TerminalTables.jsx';
import {reportRatioReason} from '../../../lib/reportRatioDisplay.js';
import {reportScopeLabel} from '../../../lib/reportingLabels.js';
import {useScreenData} from './TerminalPanels.jsx';

export function FilingScreener({lang, onClose}) {
  const [search, setSearch] = React.useState('');
  const [query, setQuery] = React.useState('');
  const [scope, setScope] = React.useState('separate');
  const [offset, setOffset] = React.useState(0);
  const limit = 10;
  const params = new URLSearchParams({scope, search:query, offset, limit});
  const {data, error} = useScreenData('/api/terminal/filing-metrics?' + params, {func:'EQS',form:'NSBU'});
  const columns = [
    ['eps_basic','EPS · UZS'], ['eps_closing_estimate',words(lang,'EPS прибл. · UZS','Taxminiy EPS · UZS','Estimated EPS · UZS')],
    ['book_value_per_share','BVPS · UZS'], ['price_to_book','P/BV · ×'],
    ['ebit',words(lang,'EBIT · тыс. UZS','EBIT · ming UZS','EBIT · thousand UZS')],
  ];
  const format = new Intl.NumberFormat(lang === 'en' ? 'en-US' : 'ru-RU', {maximumFractionDigits:2});
  return <section className="panel terminal-market-screen" data-terminal-standard="NSBU" data-terminal-scope={scope} data-terminal-function="EQS" data-terminal-ticker="market">
    <header className="terminal-section-head"><h2>EPS · P/BV · EBIT</h2><button className="ghost-btn" onClick={onClose}>{words(lang,'Все показатели','Barcha ko‘rsatkichlar','All indicators')}</button></header>
    <form className="terminal-controls" onSubmit={e=>{e.preventDefault();setOffset(0);setQuery(search.trim());}}>
      <input type="search" aria-label={words(lang,'Компания или тикер','Kompaniya yoki tiker','Company or ticker')} value={search} onChange={e=>setSearch(e.target.value)} />
      <button className="ghost-btn" type="submit">{words(lang,'Найти','Qidirish','Search')}</button>
      <select aria-label={words(lang,'Периметр','Qamrov','Scope')} value={scope} onChange={e=>{setOffset(0);setScope(e.target.value);}}>
        {['separate','consolidated'].map(s=><option key={s} value={s}>{reportScopeLabel(s,lang)}</option>)}
      </select>
    </form>
    {error ? <p role="alert">{words(lang,'Не удалось загрузить отчёты','Hisobotlar yuklanmadi','Could not load filings')}</p> : !data ? <p role="status">{words(lang,'Загрузка…','Yuklanmoqda…','Loading…')}</p> :
      <><div className="terminal-table-wrap"><table className="terminal-table"><thead><tr>
        <th>{words(lang,'Тикер','Tiker','Ticker')}</th><th>{words(lang,'Период','Davr','Period')}</th>{columns.map(([k,l])=><th key={k}>{l}</th>)}
      </tr></thead><tbody>{(data.rows||[]).map(row=><tr key={row.ticker}>
        <th><a href={localizedPath('/catalog?' + new URLSearchParams({t:row.ticker,f:'RAT',filingScope:scope}),lang)}>{row.ticker}</a></th><td>{row.period||'—'}</td>
        {columns.map(([k])=>{const r=row.metrics?.[k];const reason=r?.reason_code ? reportRatioReason(r,lang) : '';
          return <td key={k} title={reason || r?.market_as_of} data-export-value={r?.value == null ? reason || '—' : r.raw_result || String(r.value)}>
            {r?.value == null ? '—' : format.format(r.value)}
          </td>;})}
      </tr>)}</tbody></table></div>
      <div className="terminal-controls"><button className="ghost-btn" disabled={!offset} onClick={()=>setOffset(offset-limit)}>←</button>
        <span>{data.total ? Math.min(offset+1,data.total) : 0}–{offset+data.rows.length} / {data.total??data.rows.length}</span>
        <button className="ghost-btn" disabled={offset+limit >= (data.total??data.rows.length)} onClick={()=>setOffset(offset+limit)}>→</button></div></>}
  </section>;
}
