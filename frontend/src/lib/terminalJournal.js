/**
 * terminalJournal.js — the terminal's half of the event journal.
 *
 * The server keeps one append-only journal (server/terminal/journal.py). The
 * browser reports only what the server cannot see: commands run, unknown
 * commands, exports, and screens that failed or took longer than 3 s to
 * build. Events are batched and sent fire-and-forget: a lost beacon is never
 * a console error and never a slower screen.
 */

const ENDPOINT = "/api/terminal/events";
const AUTH_TOKEN_KEY = "uz_stock_analyzer_token";
const FLUSH_MS = 2000;
const MAX_BATCH = 20;
export const SLOW_SCREEN_MS = 3000;

let queue = [];
let timer = null;
let listening = false;

function authHeader() {
  try {
    const token = localStorage.getItem(AUTH_TOKEN_KEY) || sessionStorage.getItem(AUTH_TOKEN_KEY) || "";
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

function send(events) {
  try {
    fetch(ENDPOINT, {
      method: "POST",
      // keepalive lets the last batch leave with a closing tab.
      keepalive: true,
      headers: { "Content-Type": "application/json", ...authHeader() },
      body: JSON.stringify({ events }),
    }).catch(() => {});
  } catch { /* fire-and-forget */ }
}

export function flushTerminalEvents() {
  if (timer) { clearTimeout(timer); timer = null; }
  while (queue.length) send(queue.splice(0, MAX_BATCH));
}

/** Queue one event: cmd_run, cmd_unknown, export, screen_error or screen_slow. */
export function logTerminalEvent(event, fields = {}) {
  if (typeof window === "undefined") return;
  queue.push({ event, ...fields });
  if (!listening) {
    listening = true;
    window.addEventListener("pagehide", flushTerminalEvents);
  }
  if (queue.length >= MAX_BATCH) flushTerminalEvents();
  else if (!timer) timer = setTimeout(flushTerminalEvents, FLUSH_MS);
}

/**
 * Report how a screen's data load ended: an error is screen_error, a load
 * slower than 3 s is screen_slow, anything else is silence.
 */
export function reportScreenLoad({ ticker, func, form, startedAt, error = null, errorId = null }) {
  // The server rounds; the duration is a measurement, not a display value.
  const ms = performance.now() - startedAt;
  const base = { ticker, function: func, standard: form, duration_ms: ms };
  if (error) logTerminalEvent("screen_error", { ...base, error_id: errorId, message: String(error).slice(0, 200) });
  else if (ms > SLOW_SCREEN_MS) logTerminalEvent("screen_slow", base);
}
