import { useState } from 'react';
import { normalizeLanguage } from '../../shared/i18n.jsx';
import { LANDING_COPY } from './landingCopy.js';
import { LandingHero } from './LandingHero.jsx';
import { LandingSectors } from './LandingSectors.jsx';
import { LandingMarket } from './LandingMarket.jsx';
import { LandingNews } from './LandingNews.jsx';
import { LandingCompanyGuide } from './LandingCompanyGuide.jsx';
import { CompanyPreviewProvider } from '../market/index.js';

export function LandingView({ language, onNavigate, onOpenCompany, market, onOpenNews, onCalendar }) {
  const lang = normalizeLanguage(language);
  const copy = LANDING_COPY[lang];
  const [sector, setSector] = useState('');
  const pickSector = value => {
    setSector(value);
    document.getElementById('landing-market')?.scrollIntoView({ block: 'start' });
  };
  return <CompanyPreviewProvider lang={lang} changePeriod="1d" onOpenCompany={onOpenCompany}><div className="landing-view" id="landing-top">
    <div className="landing-container">
      <LandingHero copy={copy} onNavigate={onNavigate} />
      <nav className="landing-steps" aria-label={copy.explore}>
        {copy.steps.map(([title, description], index) => {
          const content = <><span className="landing-step-number">0{index + 1}</span><h2>{title}</h2><p>{description}</p></>;
          return index === 0 ? <a key={title} href="#landing-companies">{content}</a>
            : <button key={title} type="button" onClick={index === 3 ? onCalendar : () => onNavigate('issuers')}>{content}</button>;
        })}
      </nav>
      <LandingSectors copy={copy} lang={lang} market={market} onSector={pickSector} onOpenCompany={onOpenCompany} />
      <LandingMarket copy={copy} lang={lang} market={market} sector={sector} onSector={setSector} onNavigate={onNavigate} onOpenCompany={onOpenCompany} />
      <LandingNews copy={copy} lang={lang} onOpenNews={onOpenNews} onNavigate={onNavigate} />
      <LandingCompanyGuide copy={copy} lang={lang} market={market} onNavigate={onNavigate} onOpenCompany={onOpenCompany} />
      <footer className="landing-footer"><strong>UZStock</strong><p>{copy.footer}</p><a href="#landing-top">{copy.backTop} ↑</a></footer>
    </div>
  </div></CompanyPreviewProvider>;
}
