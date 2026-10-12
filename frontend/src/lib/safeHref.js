// safeHref.js — the one gate for links built from server, scraped or model-written data.
//
// React 18 renders a `javascript:` href as written, so a news item or filing whose
// URL was planted with a script scheme would run in the reader's session — and the
// session token lives in web storage. Only web links and same-site paths pass; any
// other scheme (javascript:, data:, vbscript:, …) yields no href at all.

const WEB_PROTOCOLS = new Set(["http:", "https:"]);

// Resolves relative paths ("/api/…") without depending on `window`, so the
// helper behaves the same in the browser and under `node --test`.
const BASE = "https://same-site.invalid/";

export function safeHref(value) {
  if (typeof value !== "string") return undefined;
  const text = value.trim();
  if (!text) return undefined;
  let parsed;
  try {
    // The URL parser strips the tabs, newlines and leading control characters a
    // browser also ignores, so "java\tscript:" is judged by the scheme it becomes.
    parsed = new URL(text, BASE);
  } catch {
    return undefined;
  }
  return WEB_PROTOCOLS.has(parsed.protocol) ? text : undefined;
}
