import artwork from '../../assets/landing/tashkent-economy.webp';
import { localizedPath } from '../../lib/languagePath.js';

export function LandingArrow() {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M4 12h15m-6-6 6 6-6 6" /></svg>;
}

export function LandingHero({ copy, onNavigate, lang = 'ru', staticPage = false }) {
  const Action = staticPage ? 'a' : 'button';
  const action = staticPage ? { href: localizedPath('/market', lang) }
    : { type: 'button', onClick: () => onNavigate('market') };
  return <section className="landing-hero" aria-labelledby="landing-headline">
    <div className="landing-hero-copy">
      <p className="landing-eyebrow">{copy.eyebrow}</p>
      <h1 className="lv-h1" id="landing-headline">{copy.title.map((line, i) => <span key={line}>{i > 0 && ' '}{line}</span>)}</h1>
      <p className="landing-hero-description">{copy.description}</p>
      <div className="landing-actions">
        <Action className="landing-button landing-hero-primary" {...action}>{copy.explore}<LandingArrow /></Action>
        <Action className="landing-button landing-hero-secondary" {...action}>{copy.market}</Action>
      </div>
    </div>
    <div className="landing-hero-art">
      <img src={artwork} width="1536" height="1024" alt={copy.artAlt} fetchPriority="high" />
      <div className="landing-art-chart" aria-hidden="true">
        <span>{copy.artCard}</span>
        <svg viewBox="0 0 160 52" fill="none"><path d="M2 44 13 36 22 40 33 25 43 30 55 16 66 28 77 23 89 31 100 14 111 20 123 8 135 16 145 5 158 11" /></svg>
      </div>
      <span className="landing-art-caption">{copy.artCaption}</span>
    </div>
  </section>;
}
