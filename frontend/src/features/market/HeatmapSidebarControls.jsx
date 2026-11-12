import {useRef, useState} from 'react';
import {CompanyLogo} from '../../shared/CompanyLogo.jsx';
import './heatmapSidebar.css';

const copy = {
  ru: {size: 'Площадь плитки', movement: 'Движение', capitalization: 'Капитализация', equal: 'Равные', turnover: 'Оборот', search: 'Найти тикер', clear: 'Очистить поиск тикера', empty: 'Ничего не найдено', securities: 'Бумаги'},
  en: {size: 'Tile area', movement: 'Movement', capitalization: 'Market cap', equal: 'Equal', turnover: 'Turnover', search: 'Search ticker', clear: 'Clear ticker search', empty: 'No matches found', securities: 'Securities'},
  uz: {size: 'Katak maydoni', movement: 'O‘zgarish', capitalization: 'Kapitalizatsiya', equal: 'Teng', turnover: 'Aylanma', search: 'Tikerni qidirish', clear: 'Tiker qidiruvini tozalash', empty: 'Hech narsa topilmadi', securities: 'Qog‘ozlar'},
};

function SizeIcon({mode}) {
  return <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
    {mode === 'movement' ? <path d="m2 12 4-5 3 2 5-6M10 3h4v4" />
      : mode === 'turnover' ? <path d="M2 5h11M10 2l3 3-3 3M14 11H3M6 8l-3 3 3 3" />
      : mode === 'equal' ? <><rect x="2" y="2" width="5" height="5"/><rect x="9" y="2" width="5" height="5"/><rect x="2" y="9" width="5" height="5"/><rect x="9" y="9" width="5" height="5"/></>
      : <><rect x="2" y="2" width="6" height="12"/><rect x="10" y="2" width="4" height="5"/><rect x="10" y="9" width="4" height="5"/></>}
  </svg>;
}

export function HeatmapSizeControl({lang, value, onChange}) {
  const t = copy[lang] || copy.ru;
  return <div className="heatmap-size-control">
    <span className="heatmap-sidebar-label">{t.size}</span>
    <div className="heatmap-size-options" role="group" aria-label={t.size}>
      {['capitalization', 'equal', 'movement', 'turnover'].map(mode => <button key={mode} type="button"
        data-area={mode} title={t[mode]} aria-pressed={value === mode} onClick={() => onChange(mode)}>
        <SizeIcon mode={mode}/><span>{t[mode]}</span>
      </button>)}
    </div>
  </div>;
}

export function HeatmapTickerSearch({lang, rows, companyMap, securitiesMap, value, onChange}) {
  const [query, setQuery] = useState('');
  const input = useRef(null);
  const t = copy[lang] || copy.ru;
  const needle = query.trim().toLocaleLowerCase();
  const nameOf = row => row.name || companyMap[row.ticker]?.company_name || row.ticker;
  const matches = rows.filter(row => `${row.ticker} ${nameOf(row)}`.toLocaleLowerCase().includes(needle));
  return <section className="heatmap-ticker-search" aria-label={t.securities}>
    <div className="heatmap-ticker-input">
      <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5"/><path d="m13 13 4 4"/></svg>
      <input ref={input} type="search" aria-label={t.search} placeholder={t.search} value={query}
        onChange={event => setQuery(event.target.value)} autoComplete="off" />
      {query && <button type="button" aria-label={t.clear} onClick={() => {setQuery(''); input.current?.focus();}}>×</button>}
    </div>
    <div className="heatmap-ticker-list" role="group" aria-label={t.securities}>
      {matches.map(row => <button key={row.ticker} type="button" data-ticker={row.ticker}
        aria-pressed={value === row.ticker} onClick={() => onChange(row.ticker)} title={`${row.ticker} · ${nameOf(row)}`}>
        <span className="heatmap-ticker-logo" aria-hidden="true"><CompanyLogo ticker={row.ticker} name={nameOf(row)} logo={securitiesMap?.[row.ticker]?.logo_url || row.logo_url}/></span>
        <strong>{row.ticker}</strong><span className="heatmap-ticker-name">{nameOf(row)}</span>
      </button>)}
      {!matches.length && <p className="heatmap-ticker-empty" role="status">{t.empty}</p>}
    </div>
  </section>;
}
