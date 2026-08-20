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
const IDLE_MS = 30 * 60 * 1000;

let currentUserId = null;
let lastSent = { path: "", at: 0 };

/** The signed-in user's id rides along when known; analytics only, not auth. */
export function setTrackedUser(id) {
  currentUserId = id || null;
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

    const { sid, fresh } = sessionId(store);
    send({
      vid: visitorId(store),
      sid,
      uid: currentUserId,
      path,
      view,
      ticker: ticker || "",
      // The referrer only means "where the visit came from" on the visit's
      // first view; afterwards it would just echo our own pages.
      ref: fresh ? document.referrer || "" : "",
      lang: store.getItem(LANGUAGE_KEY) || "",
      w: window.innerWidth || null,
    });
  } catch { /* tracking must never break the page */ }
}
