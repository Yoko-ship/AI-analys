// Rendered at build time only. The hero and its assets/CSS are shared with React;
// the fallback navigation uses ordinary links and needs no client JavaScript.
import { BrandIcon } from '../../shared/BrandIcon.jsx';
import { t } from '../../shared/i18n.jsx';
import { mt } from '../../shared/marketCopy.jsx';
import { localizedPath } from '../../lib/languagePath.js';
import { LandingHero } from './LandingHero.jsx';
import { LANDING_COPY } from './landingCopy.js';

export function StaticLanding({ language }) {
  const copy = {
    ru: { feedback: 'Обратная связь', signIn: 'Войти', menu: 'Меню' },
    uz: { feedback: 'Fikr-mulohaza', signIn: 'Kirish', menu: 'Menyu' },
    en: { feedback: 'Feedback', signIn: 'Sign in', menu: 'Menu' },
  }[language];
  const labels = [t(language, 'nav.main'), mt(language, 'nav'), t(language, 'nav.news'), copy.feedback];
  const paths = ['/', '/market', '/news', '/feedback'];
  const links = paths.map((path, i) => <a key={path} className={`topbar-nav-btn${i === 0 ? ' active' : ''}`} href={localizedPath(path, language)}>
    {labels[i]}{(i === 1 || i === 2) && <span className="nav-dd-caret" aria-hidden="true">▾</span>}
  </a>);
  return <div className="app-shell-wrap view-main landing-static" lang={language}>
    <div className="app-shell">
      <header className="topbar">
        <details className="landing-static-menu">
          <summary className="topbar-burger" aria-label={copy.menu}>
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M3 6h18M3 12h18M3 18h18" /></svg>
          </summary>
          <nav>{links}</nav>
        </details>
        <a className="topbar-brand" href={localizedPath('/', language)} aria-label={`UZStock — ${labels[0]}`}>
          <BrandIcon decorative />
          <div className="brand-copy"><div className="brand-title">{t(language, 'brand')}</div></div>
        </a>
        <nav className="topbar-nav">{links}</nav>
        <div className="topbar-actions">
          <a className="account-signin" href={localizedPath('/auth', language)}>{copy.signIn}</a>
          <div className="topbar-meta"><div className="topbar-controls">
            <div className="topbar-language">
              <a className="language-trigger" href={language === 'uz' ? '/' : '/uz'} aria-label={language === 'uz' ? 'Русский' : 'O‘zbekcha'}>
                <svg className="language-globe" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" /><ellipse cx="12" cy="12" rx="4" ry="9" /><path d="M3 12h18" />
                </svg>
                {language.toUpperCase()}
                <span className="language-chevron"><svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg></span>
              </a>
            </div>
            <span className="theme-toggle" aria-hidden="true"><strong>☀</strong></span>
          </div></div>
        </div>
      </header>
      <main className="content"><div className="landing-view"><div className="landing-container">
        <LandingHero copy={LANDING_COPY[language]} lang={language} staticPage />
      </div>
      </div></main>
    </div>
  </div>;
}
