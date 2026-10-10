import { normalizeLanguage, t } from "../shared/i18n.jsx";
import { LANGUAGE_KEY } from "./preferences.jsx";

// The server writes each URL's own Russian title into the shell (server/seo/routes.py)
// for search engines. Keep it while the reader is still on that URL in Russian;
// any other page or language falls back to the app's generic title, so a page
// reached in-app never inherits the landing page's company name.
const serverTitle = document.title;
const landingPath = window.location.pathname;

export function applyPageTitle(language) {
  let saved = null;
  try { saved = localStorage.getItem(LANGUAGE_KEY); } catch (e) { /* ignore */ }
  const lang = normalizeLanguage(language || saved || "ru");
  document.title = lang === "ru" && window.location.pathname === landingPath
    ? serverTitle
    : t(lang, "pageTitle");
}
