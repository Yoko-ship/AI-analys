import bank from '../../assets/landing/sector-bank.webp';
import factory from '../../assets/landing/sector-factory.webp';
import telecom from '../../assets/landing/sector-telecom.webp';
import { LandingArrow } from './LandingHero.jsx';
import { compact } from '../../lib/format.js';
import { selectSectorLeaders } from './sectorLeaders.js';

const sectors = [
  { key: 'finance', image: bank },
  { key: 'manufacturing', image: factory },
  { key: 'telecom', image: telecom },
];

export function LandingSectors({ copy, lang, market, onSector, onOpenCompany }) {
  const leaders = selectSectorLeaders(market, sectors.map(({ key }) => key));
  const leaderDescription = ({ sector, turnover, tradeDate }) => {
    const date = new Date(`${tradeDate.slice(0, 4)}-${tradeDate.slice(4, 6)}-${tradeDate.slice(6)}T00:00:00`)
      .toLocaleDateString(lang === 'en' ? 'en-GB' : 'ru-RU');
    return `${copy.sectors[sector]} · ${copy.turnover}: ${compact(turnover, lang)} · ${date}`;
  };
  return <section id="landing-companies" className="landing-sectors" aria-labelledby="landing-sectors-title">
    <div className="landing-sector-intro">
      <h2 id="landing-sectors-title">{copy.sectorsTitle}</h2>
      <p>{copy.sectorsDescription}</p>
      {leaders.length > 0 && <>
        <p className="landing-ticker-note" id="landing-ticker-note">{copy.sectorLeaders}</p>
        <div className="landing-ticker-links" role="group" aria-labelledby="landing-ticker-note">
          {leaders.map(leader => <button type="button" key={leader.sector} title={leaderDescription(leader)} onClick={() => onOpenCompany(leader.ticker)}>{leader.ticker}<LandingArrow /></button>)}
        </div>
      </>}
    </div>
    <div className="landing-sector-cards">
      {sectors.map(({ key, image }) => <button type="button" className="landing-sector-card" key={key} onClick={() => onSector(key)}>
        <img src={image} alt="" width="1536" height="1024" loading="lazy" />
        <span><strong>{copy.sectors[key]}</strong><LandingArrow /></span>
      </button>)}
    </div>
  </section>;
}
