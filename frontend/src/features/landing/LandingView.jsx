import { normalizeLanguage } from "../../shared/i18n.jsx";
import { LandingHero } from "./LandingHero.jsx";

export function LandingView({ language, theme, onNavigate, onOpenCompany }) {
  return <div className="landing-view">
    <LandingHero lang={normalizeLanguage(language)} theme={theme} onNavigate={onNavigate} onOpenCompany={onOpenCompany} />
  </div>;
}
