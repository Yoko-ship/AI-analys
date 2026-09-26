import { useEffect, useState } from "react";
import { normalizeLanguage, t } from "../shared/i18n.jsx";
import { LANGUAGE_KEY, TEXT_SCALES, TEXT_SCALE_KEY, THEME_KEY } from "./preferences.jsx";

export function usePreferences() {

  const [language, setLanguage] = useState(() => normalizeLanguage(localStorage.getItem(LANGUAGE_KEY) || "ru"));

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
    localStorage.setItem(LANGUAGE_KEY, lang);
    document.documentElement.lang = lang;
    document.title = t(lang, "pageTitle");
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
