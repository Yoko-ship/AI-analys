// --- Which language a URL is in ------------------------------------------------
// Russian, the site's default, owns the bare paths (/, /market, /company/AGBA).
// Each language listed in URL_LANGUAGES owns the same paths under "/{code}"
// (/uz, /uz/market, /uz/company/AGBA), so search engines can index it as pages
// of its own; the server answers that prefix with the language's own meta and
// snapshots. A language not listed here (English, for now) is chosen in the UI
// only and keeps the bare paths. Giving another language its URLs is a change
// to this list (and to the server's), nothing else.
//
// Every internal path the app writes — pushState, replaceState, an <a href>, a
// shared link — goes through localizedPath, and every path it reads goes
// through splitLanguagePath, so no caller concatenates or strips a prefix.
const URL_LANGUAGES = ["uz"];

// The language of a URL that carries no prefix, as the server renders it.
const DEFAULT_URL_LANGUAGE = "ru";

// Split a pathname into the language its prefix names (null when it names none)
// and the bare path the router matches. Only a whole segment counts: "/uz" and
// "/uz/..." are Uzbek, "/uzbek-bonds" is an ordinary path.
function splitLanguagePath(pathname) {
  const raw = pathname || "/";
  for (const language of URL_LANGUAGES) {
    const prefix = `/${language}`;
    if (raw === prefix || raw.startsWith(`${prefix}/`)) {
      return { language, path: raw.slice(prefix.length) || "/" };
    }
  }
  return { language: null, path: raw };
}

// The same page in `language`: a bare or already-prefixed path, optionally with
// a query string or hash, rewritten to that language's form. Languages without
// URLs of their own get the bare path, so this also strips a prefix.
function localizedPath(path, language) {
  const value = path || "/";
  const cut = value.search(/[?#]/);
  const pathname = cut < 0 ? value : value.slice(0, cut);
  const suffix = cut < 0 ? "" : value.slice(cut);
  const bare = splitLanguagePath(pathname || "/").path;
  if (!URL_LANGUAGES.includes(language)) return `${bare}${suffix}`;
  return `${bare === "/" ? `/${language}` : `/${language}${bare}`}${suffix}`;
}

// The language the address bar is in right now — for code that rewrites the
// current URL (a toolbar mirrored into the query string) and must keep its prefix.
function locationLanguage() {
  if (typeof window === "undefined" || !window.location) return null;
  return splitLanguagePath(window.location.pathname).language;
}

export { DEFAULT_URL_LANGUAGE, URL_LANGUAGES, localizedPath, locationLanguage, splitLanguagePath };
