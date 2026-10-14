import { useEffect, useState } from "react";
import { normalizeLanguage } from "../shared/i18n.jsx";
import { LANGUAGE_KEY, TEXT_SCALES, TEXT_SCALE_KEY, THEME_KEY } from "./preferences.jsx";
import { applyPageTitle } from "./pageTitle.js";
import { localizedPath, splitLanguagePath } from "./routing.jsx";

// A URL that names a language (/uz/...) decides it: that is the page a search
// engine indexed and a link was shared as, so it opens in that language and the
// choice is kept. A bare URL opens in the reader's saved language.
function initialLanguage() {
  const fromUrl = splitLanguagePath(window.location.pathname).language;
  if (fromUrl) return normalizeLanguage(fromUrl);
  let saved = null;
  try { saved = localStorage.getItem(LANGUAGE_KEY); } catch (e) { /* ignore */ }
  return normalizeLanguage(saved || "ru");
}

export function usePreferences() {

  const [language, setLanguage] = useState(initialLanguage);

  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
    return "dark"; // Default to dark theme (Finam AI style)
  });

  const [textScale, setTextScale] = useState(() => {
    const saved = Number(localStorage.getItem(TEXT_SCALE_KEY));
    return TEXT_SCALES.includes(saved) ? saved : 100;
  });

  useEffect(() => {
    // 100 % clears the property rather than writing "1": a stylesheet that never
    // sees `zoom` is the one the design was drawn against, and an explicit 1 on
    // the root element creates a containing block that a `position: fixed`
    // overlay would resolve against instead of the viewport.
    const root = document.documentElement;
    if (textScale === 100) root.style.removeProperty("zoom");
    else root.style.zoom = String(textScale / 100);
    try { localStorage.setItem(TEXT_SCALE_KEY, String(textScale)); } catch (e) { /* ignore */ }
  }, [textScale]);

  const stepTextScale = (delta) => setTextScale((current) => {
    const at = TEXT_SCALES.indexOf(current);
    const next = TEXT_SCALES[Math.min(TEXT_SCALES.length - 1, Math.max(0, (at < 0 ? 1 : at) + delta))];
    return next;
  });

  useEffect(() => {
    const lang = normalizeLanguage(language);
    try { localStorage.setItem(LANGUAGE_KEY, lang); } catch (e) { /* ignore */ }
    document.documentElement.lang = lang;
    // The address bar follows the language — on load (a saved Uzbek reader who
    // opened /market lands on /uz/market) and on every switch — by replacing the
    // current entry: the page has not changed, only the language it is shown in.
    // This runs before useNavigation's effect (App calls this hook first), so
    // navigation always finds the URL already in the reader's language.
    const { pathname, search, hash } = window.location;
    const target = localizedPath(pathname, lang);
    if (target !== pathname) {
      try { window.history.replaceState(window.history.state, "", `${target}${search}${hash}`); } catch (e) { /* ignore */ }
    }
    applyPageTitle(lang);
  }, [language]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.body.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    const themeMeta = document.querySelector('meta[name="theme-color"]');
    if (themeMeta) {
      themeMeta.setAttribute("content", theme === "dark" ? "#0a0f1a" : "#f8fafc");
    }
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  };
  return { language, setLanguage, setTextScale, setTheme, stepTextScale, textScale, theme, toggleTheme };
}
