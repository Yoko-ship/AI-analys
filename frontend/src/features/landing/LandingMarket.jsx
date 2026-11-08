import { useState } from 'react';
import { prepareMarketRows } from '../../lib/marketData.js';
import { sectorOf } from '../../lib/sectors.js';
import { marketDisplayPrice } from '../../shared/marketModel.jsx';
import { marketRowDay } from '../../lib/valuation.js';
import { compact, price, pct } from '../../lib/format.js';
import { CompanyPreviewLogo } from '../market/index.js';
import { LandingArrow } from './LandingHero.jsx';

function tradingDate(row, lang) {
  const day = marketRowDay(row);
  if (!day) return '—';
  const iso = day.length === 8 ? `${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6, 8)}` : day;
  const date = new Date(iso + 'T00:00:00');
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString(lang === 'en' ? 'en-GB' : 'ru-RU');
}

export function LandingMarket({ copy, lang, market, sector, onSector, onNavigate, onOpenCompany }) {
  const [query, setQuery] = useState('');
  const companyMap = Object.fromEntries(market.companies.map(company => [company.ticker, company]));
  const rows = prepareMarketRows(market.marketRows, market.marketTradeStats).filter(row => row.type !== 'bond');
  const filtered = rows.filter(row => (!sector || sectorOf(row.ticker, market.securitiesMap, companyMap) === sector)
    && `${row.ticker} ${row.name || ''} ${companyMap[row.ticker]?.company_name || ''}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
    // A historic block-sized trade must not lead a preview of the current market.
    // Keep older securities searchable, ordered after the most recent sessions.
    .sort((a, b) => (marketRowDay(b) || '').localeCompare(marketRowDay(a) || '')
      || (b.stockVolume || 0) - (a.stockVolume || 0));
  const reset = () => { setQuery(''); onSector(''); };
  const retry = () => { market.loadMarketStocks('stock').catch(() => {}); };
  return <section id="landing-market" className="landing-market" aria-labelledby="landing-market-title">
    <div className="landing-section-heading">
      <div><h2 id="landing-market-title">{copy.marketTitle}</h2><p>{copy.marketDescription}</p></div>
      <button className="landing-text-link" type="button" onClick={() => onNavigate('market')}>{copy.fullMarket}<LandingArrow /></button>
    </div>
    <div className="landing-market-toolbar">
      <div className="landing-filters" role="group" aria-label={copy.sectorsTitle}>
        {[['', copy.all], ...Object.entries(copy.sectors)].map(([key, label]) => <button type="button" key={key} aria-pressed={sector === key} onClick={() => onSector(key)}>{label}</button>)}
      </div>
      <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={copy.placeholder} aria-label={copy.search} />
    </div>
    {market.marketError && <div className="landing-data-notice" role="alert"><p>{copy.marketError}</p><button type="button" onClick={retry} disabled={market.marketLoading}>{copy.retry}</button></div>}
    {market.marketLoading && !rows.length ? <div className="landing-loading" role="status">{copy.loading}</div>
      : !rows.length ? !market.marketError && <div className="landing-data-notice" role="status"><p>{copy.empty}</p><button type="button" onClick={retry}>{copy.retry}</button></div>
      : !filtered.length ? <div className="landing-data-notice" role="status"><p>{copy.noMatch}</p><button type="button" onClick={reset}>{copy.reset}</button></div>
      : <div className="landing-table-wrap"><table>
        <thead><tr><th scope="col">{copy.company}</th><th scope="col">{copy.price}</th><th scope="col">{copy.change}</th><th scope="col" className="landing-turnover">{copy.turnover}</th></tr></thead>
        <tbody>{filtered.slice(0, 6).map(row => <tr key={row.ticker}>
          <td><div className="landing-company-cell">
            <span className="landing-company-mark">
              <CompanyPreviewLogo row={row} security={{ ...row, ...market.securitiesMap[row.ticker], logo_url: market.securitiesMap[row.ticker]?.logo_url || row.logo_url }} />
            </span>
            <button className="landing-company" type="button" onClick={() => onOpenCompany(row.ticker)}>
            <span><strong>{row.ticker}</strong><small>{companyMap[row.ticker]?.company_name || row.name}</small></span>
            </button>
          </div></td>
          <td>{price(marketDisplayPrice(row), lang)}<small>{tradingDate(row, lang)}</small></td>
          <td className={row.changePercent > 0 ? 'landing-positive' : row.changePercent < 0 ? 'landing-negative' : ''}>{pct(row.changePercent, lang)}</td>
          <td className="landing-turnover">{compact(row.stockVolume, lang)}</td>
        </tr>)}</tbody>
      </table></div>}
    <p className="landing-quote-note">{copy.quoteNote}</p>
  </section>;
}
