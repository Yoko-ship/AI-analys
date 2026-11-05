import React from 'react';
import {CompanyLogo} from '../../shared/CompanyLogo.jsx';
import {sectorLabel} from '../../shared/marketCopy.jsx';

const PAGE_SIZE = 50;
const labels = {
  ru:['Предыдущие эмитенты', 'Следующие эмитенты'],
  uz:['Oldingi emitentlar', 'Keyingi emitentlar'],
  en:['Previous issuers', 'Next issuers'],
};

export const CatalogIssuerList = React.memo(function CatalogIssuerList({companies, ticker, lang, onSelect}) {
  const [page, setPage] = React.useState(0);
  const list = React.useRef(null);
  const current = Math.min(page, Math.max(0, Math.ceil(companies.length / PAGE_SIZE) - 1));
  const start = current * PAGE_SIZE, end = Math.min(start + PAGE_SIZE, companies.length);
  React.useEffect(() => {if (list.current) list.current.scrollTop = 0;}, [current]);
  const copy = labels[lang] || labels.ru;
  return <>
    <div className="catalog-company-list" ref={list}>
      {companies.slice(start, end).map(c => <button key={c.ticker} type="button"
        className={`catalog-company-item ${ticker === c.ticker ? 'active' : ''}`}
        onClick={() => onSelect(c.ticker)} aria-pressed={ticker === c.ticker}>
        <CompanyLogo logo={c.logo} name={c.company_name} ticker={c.ticker}/>
        <div className="catalog-company-item-body">
          <strong className="catalog-company-title">{c.company_name || c.ticker}</strong>
          <span className="catalog-company-ticker">{(c.tickers?.length ? c.tickers : [c.ticker]).join(' · ')} · {sectorLabel(lang, c.sector || 'other')}</span>
        </div>
        <span className="catalog-company-count">{c.total_count || 0}</span>
      </button>)}
    </div>
    {companies.length > PAGE_SIZE && <div className="catalog-issuer-pages">
      <button type="button" className="ghost-btn" aria-label={copy[0]} disabled={!current} onClick={() => setPage(current - 1)}>←</button>
      <span aria-live="polite">{start + 1}–{end} / {companies.length}</span>
      <button type="button" className="ghost-btn" aria-label={copy[1]} disabled={end >= companies.length} onClick={() => setPage(current + 1)}>→</button>
    </div>}
  </>;
});
