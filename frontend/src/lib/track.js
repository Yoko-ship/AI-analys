/**
 * track.js — the visit beacon.
 *
 * One POST to /api/track per page view. The server stores it in web_events and
 * the admin panel's «Аудитория» reads it — before this file existed, nothing in
 * the project recorded that a human opened the site.
 *
 * The visitor id is a random first-party token in localStorage — not a cookie,
 * so nothing is attached to API requests, and not tied to the auth token: the
 * audience is mostly anonymous. The session id rotates after 30 idle minutes,
 * which is what turns "events" into "visits". Everything is fire-and-forget:
 * a failed beacon is silently lost, never a console error, never a slow page.
 */

const VISITOR_KEY = "uz_track_visitor";
const SESSION_KEY = "uz_track_session";
const SEEN_KEY = "uz_track_seen";
const LANGUAGE_KEY = "uz_stock_analyzer_language";
const AUTH_TOKEN_KEY = "uz_stock_analyzer_token";
const INTERNAL_KEY = "uz_track_internal";
const IDLE_MS = 30 * 60 * 1000;
// One page left open in a background tab must not read as an hour of reading.
const MAX_PAGE_MS = 30 * 60 * 1000;

let currentAuthToken = "";
let lastSent = { path: "", at: 0 };
// The page being read: its visible time and how far down it was scrolled are
// reported by a `leave` event when the reader moves on, hides the tab or
// closes it — that is what answers "how long did they stay, and where did
// they give up".
let page = null;
let listening = false;

// Campaign tags are read once, at load: the app rewrites the address as it
// routes, and by the first page view the query string may already be gone.
const landingTags = (() => {
  try {
    const q = new URLSearchParams(window.location.search);
    const tags = { us: q.get("utm_source"), um: q.get("utm_medium"), uc: q.get("utm_campaign") };
    return tags.us || tags.um || tags.uc ? tags : null;
  } catch {
    return null;
  }
})();
let tagsPending = Boolean(landingTags);

/** «Не считать этот браузер»: the team's own devices stay out of the audience. */
export function isBrowserExcluded() {
  try {
    return localStorage.getItem(INTERNAL_KEY) === "1";
  } catch {
    return false;
  }
}

export function setBrowserExcluded(excluded) {
  try {
    if (excluded) localStorage.setItem(INTERNAL_KEY, "1");
    else localStorage.removeItem(INTERNAL_KEY);
  } catch { /* private mode: nothing to remember */ }
}

/** A token lets the server derive the user. The public payload never claims an id. */
export function setTrackedUser(id) {
  if (!id) {
    currentAuthToken = "";
    return;
  }
  try {
    currentAuthToken = localStorage.getItem(AUTH_TOKEN_KEY)
      || sessionStorage.getItem(AUTH_TOKEN_KEY) || "";
  } catch {
    currentAuthToken = "";
  }
}

function randomId() {
  try {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return `f${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
  }
}

function storage() {
  try {
    const probe = "__uz_track_probe__";
    localStorage.setItem(probe, "1");
    localStorage.removeItem(probe);
    return localStorage;
  } catch {
    return null;
  }
}

function visitorId(store) {
  let id = store.getItem(VISITOR_KEY);
  if (!id || !/^[a-z0-9_-]{8,64}$/i.test(id)) {
    id = randomId();
    store.setItem(VISITOR_KEY, id);
  }
  return id;
}

/** The current visit's id; rotating it after idle is what defines a visit. */
function sessionId(store) {
  const now = Date.now();
  const seen = Number(store.getItem(SEEN_KEY) || 0);
  let sid = store.getItem(SESSION_KEY);
  let fresh = false;
  if (!sid || !/^[a-z0-9_-]{8,64}$/i.test(sid) || !seen || now - seen > IDLE_MS) {
    sid = randomId();
    store.setItem(SESSION_KEY, sid);
    fresh = true;
  }
  store.setItem(SEEN_KEY, String(now));
  return { sid, fresh };
}

function send(payload) {
  const body = JSON.stringify(payload);
  // sendBeacon cannot attach an Authorization header. Signed-in page views use
  // fetch so the server can derive (and verify) the user from the session token.
  if (currentAuthToken) {
    try {
      fetch("/api/track", {
        method: "POST",
        body,
        keepalive: true,
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${currentAuthToken}`,
        },
      }).catch(() => {});
    } catch { /* a lost beacon is fine */ }
    return;
  }
  try {
    if (navigator.sendBeacon
        && navigator.sendBeacon("/api/track", new Blob([body], { type: "application/json" }))) {
      return;
    }
  } catch { /* fall through to fetch */ }
  try {
    fetch("/api/track", {
      method: "POST",
      body,
      keepalive: true,
      headers: { "Content-Type": "application/json" },
    }).catch(() => {});
  } catch { /* a lost beacon is fine */ }
}

/**
 * Record one page view. `view` is the app's logical view name and `ticker`
 * accompanies company/chart/bond pages — the panel's «Топ бумаг» is built
 * from it. Same path twice within a second is one view (double-fired effects).
 */
export function trackPageview({ path, view = "", ticker = "" } = {}) {
  try {
    const store = storage();
    if (!store || !path) return;
    const now = Date.now();
    if (path === lastSent.path && now - lastSent.at < 1000) return;
    lastSent = { path, at: now };

    reportLeave();
    const { sid, fresh } = sessionId(store);
    const vid = visitorId(store);
    const tags = fresh && tagsPending ? landingTags : null;
    if (fresh) tagsPending = false;
    send({
      vid,
      sid,
      path,
      view,
      ticker: ticker || "",
      // The referrer only means "where the visit came from" on the visit's
      // first view; afterwards it would just echo our own pages.
      ref: fresh ? document.referrer || "" : "",
      lang: store.getItem(LANGUAGE_KEY) || "",
      w: window.innerWidth || null,
      ...(tags || {}),
      ...(isBrowserExcluded() ? { int: 1 } : {}),
    });
    page = { vid, sid, path, view, ticker: ticker || "", shownAt: visible() ? now : null, ms: 0, scroll: 0 };
    measureScroll();
    listen();
  } catch { /* tracking must never break the page */ }
}

/** The reader moved to a view that is not counted (the admin panel): close the page. */
export function endPageview() {
  try {
    reportLeave();
    page = null;
  } catch { /* tracking must never break the page */ }
}

function visible() {
  return typeof document === "undefined" || document.visibilityState !== "hidden";
}

function measureScroll() {
  if (!page) return;
  try {
    const doc = document.documentElement;
    const height = Math.max(doc.scrollHeight, document.body ? document.body.scrollHeight : 0);
    const seen = (window.scrollY || doc.scrollTop || 0) + window.innerHeight;
    // A page shorter than the screen was read to its end by being shown.
    const pct = height <= window.innerHeight ? 100 : Math.min(100, Math.trunc(seen / height * 100));
    if (pct > page.scroll) page.scroll = pct;
  } catch { /* measurement is best-effort */ }
}

/** Bank the visible time so far; the page stays current. */
function pause() {
  if (page && page.shownAt !== null) {
    page.ms += Date.now() - page.shownAt;
    page.shownAt = null;
  }
}

/**
 * Report the time read since the last report, as a delta: a tab hidden and
 * shown again reports twice and the server sums them.
 */
function reportLeave() {
  if (!page) return;
  pause();
  const ms = Math.min(MAX_PAGE_MS, page.ms);
  if (ms >= 500) {
    send({
      vid: page.vid,
      sid: page.sid,
      event: "leave",
      path: page.path,
      view: page.view,
      ticker: page.ticker,
      ms,
      sp: page.scroll,
      ...(isBrowserExcluded() ? { int: 1 } : {}),
    });
  }
  page.ms = 0;
}

function listen() {
  if (listening) return;
  listening = true;
  let pending = false;
  window.addEventListener("scroll", () => {
    if (pending) return;
    pending = true;
    window.requestAnimationFrame(() => { pending = false; measureScroll(); });
  }, { passive: true });
  document.addEventListener("visibilitychange", () => {
    try {
      if (!page) return;
      if (visible()) {
        page.shownAt = Date.now();
      } else {
        // On a phone, hiding the tab is often the last moment the page is
        // alive; report now rather than hope for a later unload.
        reportLeave();
      }
    } catch { /* tracking must never break the page */ }
  });
  window.addEventListener("pagehide", () => {
    try {
      reportLeave();
      page = null;
    } catch { /* tracking must never break the page */ }
  });
}
