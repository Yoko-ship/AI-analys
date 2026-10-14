import { normalizeLanguage, t } from "../shared/i18n.jsx";
import { LANGUAGE_KEY } from "./preferences.jsx";
import { DEFAULT_URL_LANGUAGE, splitLanguagePath } from "./routing.jsx";

// The server writes each URL's own title into the shell (server/seo/routes.py)
// for search engines, in the language the URL is in: Uzbek for /uz/..., Russian
// for a bare path. Keep it while the reader is still on that URL in that
// language; any other page or language falls back to the app's generic title,
// so a page reached in-app never inherits the landing page's company name.
const serverTitle = document.title;
const landingPath = window.location.pathname;
const landingLanguage = splitLanguagePath(landingPath).language || DEFAULT_URL_LANGUAGE;

export function applyPageTitle(language) {
  let saved = null;
  try { saved = localStorage.getItem(LANGUAGE_KEY); } catch (e) { /* ignore */ }
  const lang = normalizeLanguage(language || saved || "ru");
  document.title = lang === landingLanguage && window.location.pathname === landingPath
    ? serverTitle
    : t(lang, "pageTitle");
}
