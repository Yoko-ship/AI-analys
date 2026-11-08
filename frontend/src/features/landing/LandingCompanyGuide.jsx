import { CompanyPreviewLogo } from '../market/index.js';
import { marketDisplayPrice } from '../../shared/marketModel.jsx';
import { compact, price } from '../../lib/format.js';
import { issuerDisplayName } from '../../lib/issuerDisplayName.js';
import { prepareMarketRows } from '../../lib/marketData.js';
import { SECTOR_ORDER } from '../../lib/sectors.js';
import { LandingArrow } from './LandingHero.jsx';
import { selectSectorLeaders } from './sectorLeaders.js';

export function LandingCompanyGuide({ copy, lang, market, onNavigate, onOpenCompany }) {
  const example = selectSectorLeaders(market, SECTOR_ORDER).sort((a, b) => b.turnover - a.turnover)[0];
  const row = example && prepareMarketRows(market.marketRows, market.marketTradeStats).find(item => item.ticker === example.ticker);
  const security = market.securitiesMap[example?.ticker] || {};
  const company = market.companies.find(item => item.ticker === example?.ticker) || {};
  const name = example && issuerDisplayName({ ...row, ...company, ...security }, example.ticker);
  const day = example?.tradeDate;
  const isoDate = day && `${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6)}`;
  return <section className={`landing-about${example ? '' : ' landing-about--intro-only'}`} aria-labelledby="landing-about-title">
    <div className="landing-about-intro">
      <p className="landing-eyebrow">{copy.aboutEyebrow}</p>
      <h2 id="landing-about-title">{copy.aboutTitle}</h2>
      <p className="landing-about-description">{copy.aboutDescription}</p>
      <button className="landing-button landing-primary" type="button" onClick={() => onNavigate('market')}>{copy.explore}<LandingArrow /></button>
    </div>
    {example && <article className="landing-company-example" aria-labelledby="landing-example-name">
      <p className="landing-example-caption">{copy.aboutExample}</p>
      <div className="landing-example-identity">
        <span className="landing-company-mark"><CompanyPreviewLogo row={row} security={{ ...row, ...security, logo_url: security.logo_url || row.logo_url }} /></span>
        <div><span className="landing-example-ticker">{example.ticker}</span><h3 id="landing-example-name">{name}</h3></div>
      </div>
      <dl className="landing-example-figures">
        <div><dt>{copy.price}</dt><dd className="landing-example-price">{price(marketDisplayPrice(row), lang)}</dd></div>
        <div><dt>{copy.turnover}</dt><dd className="landing-example-turnover">{compact(example.turnover, lang)}</dd></div>
      </dl>
      <div className="landing-example-footer">
        <p>{copy.aboutSession} <time dateTime={isoDate}>{new Date(`${isoDate}T00:00:00`).toLocaleDateString(lang === 'en' ? 'en-GB' : 'ru-RU')}</time></p>
        <button className="landing-example-open" type="button" onClick={() => onOpenCompany(example.ticker)}>{copy.aboutOpen}<LandingArrow /></button>
      </div>
    </article>}
  </section>;
}
