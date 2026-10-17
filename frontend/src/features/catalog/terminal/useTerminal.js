import React from "react";
import {
  TAB_KEYS, commandText, isEmptyCommand, isIssuerFunction, parseCommand, tickerIndex,
} from "../../../lib/terminalCommands.js";
import { logTerminalEvent } from "../../../lib/terminalJournal.js";
import { terminalCopy } from "./terminalCopy.js";

// Functions with a screen today. The rest are recognised (HELP lists them,
// marked «скоро») and open a "coming" panel instead of failing as unknown.
export const READY_FUNCTIONS = new Set(["SUM", "PL", "BS", "RAT", "DVD", "CF", "CN", "DQ"]);
const OVERLAYS = new Set(["HELP", "LAST"]);
const LAST_KEY = "uz_terminal_last";
const LAST_SIZE = 8;
// Customer decision 2026-10-17: the terminal opens on history from 2020, and
// the reader can extend it back to 2015 (?h=all). The stored data is unchanged.
export const DEFAULT_FROM_YEAR = 2020;

// The screen lives in the address bar (/catalog?t=SQBN&f=PL&std=MSFO), so
// every screen is linkable and the browser's Back and Forward walk the
// terminal's history like Esc does.
function readUrl() {
  const q = new URLSearchParams(window.location.search);
  const func = (q.get("f") || "").toUpperCase();
  return {
    ticker: (q.get("t") || "").toUpperCase() || null,
    func: isIssuerFunction(func) ? func : "SUM",
    form: (q.get("std") || "").toUpperCase() === "MSFO" ? "MSFO" : "NSBU",
    fullHistory: q.get("h") === "all",
  };
}

function writeUrl({ ticker, func, form, fullHistory }, push) {
  const q = new URLSearchParams(window.location.search);
  for (const key of ["t", "f", "std", "h"]) q.delete(key);
  if (ticker) q.set("t", ticker);
  if (func && func !== "SUM") q.set("f", func);
  if (form === "MSFO") q.set("std", "MSFO");
  if (fullHistory) q.set("h", "all");
  const search = q.toString();
  const url = `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`;
  if (url === `${window.location.pathname}${window.location.search}${window.location.hash}`) return false;
  window.history[push ? "pushState" : "replaceState"](window.history.state, "", url);
  return true;
}

function readLast() {
  try {
    const items = JSON.parse(sessionStorage.getItem(LAST_KEY) || "[]");
    return Array.isArray(items) ? items : [];
  } catch {
    return [];
  }
}

function rememberScreen(screen) {
  const text = commandText(screen);
  const items = [{ ...screen, text, at: Date.now() }, ...readLast().filter((s) => s.text !== text)].slice(0, LAST_SIZE);
  try { sessionStorage.setItem(LAST_KEY, JSON.stringify(items)); } catch { /* private mode */ }
  return items;
}

function isTyping(target) {
  return target && (/^(input|select|textarea)$/i.test(target.tagName) || target.isContentEditable);
}

export function useTerminal({ companies, ticker, setTicker, lang, onCatalogSearch }) {
  const copy = terminalCopy(lang);
  const initial = React.useRef(readUrl()).current;
  const [func, setFunc] = React.useState(initial.func);
  const [form, setFormState] = React.useState(initial.form);
  const [fullHistory, setFullHistoryState] = React.useState(initial.fullHistory);
  const [overlay, setOverlay] = React.useState(null);
  const [message, setMessage] = React.useState(null);
  const [last, setLast] = React.useState(readLast);
  const inputRef = React.useRef(null);
  const depth = React.useRef(0);
  const index = React.useMemo(() => tickerIndex(companies), [companies]);
  const state = React.useRef({ ticker, func, form, fullHistory });
  state.current = { ticker, func, form, fullHistory };

  // A ticker named in the URL opens before the catalog's default issuer does.
  // Opening a screen by link is opening it, for the journal as for the reader.
  React.useEffect(() => {
    if (!initial.ticker) return;
    setTicker(initial.ticker);
    logTerminalEvent("cmd_run", { ticker: initial.ticker, function: initial.func, standard: initial.form });
  }, [initial, setTicker]);

  // The page's own choices (an issuer clicked in the list, the first issuer
  // opened by default) keep the address in step without adding history.
  React.useEffect(() => {
    if (ticker) writeUrl({ ticker, func, form, fullHistory }, false);
  }, [ticker, func, form, fullHistory]);

  const go = React.useCallback((next, { push = true } = {}) => {
    const screen = { ...state.current, ...next };
    if (!screen.ticker) return;
    setOverlay(null);
    setMessage(null);
    if (screen.ticker !== state.current.ticker) setTicker(screen.ticker);
    setFunc(screen.func);
    setFormState(screen.form);
    if (writeUrl(screen, push) && push) depth.current += 1;
    setLast(rememberScreen(screen));
    logTerminalEvent("cmd_run", { ticker: screen.ticker, function: screen.func, standard: screen.form });
  }, [setTicker]);

  const run = React.useCallback((text) => {
    const parsed = parseCommand(text, index);
    // A line with a word the terminal does not know runs nothing: «SQBX FA»
    // is a mistyped ticker, and opening FA for whatever issuer is on screen
    // would answer a question nobody asked.
    if (parsed.unknown.length) {
      setMessage({ tone: "error", text: copy.unknown(parsed.unknown.join(" ")) });
      logTerminalEvent("cmd_unknown", { message: String(text).trim().slice(0, 200) });
      return false;
    }
    if (parsed.market) {
      if (OVERLAYS.has(parsed.market)) {
        setOverlay(parsed.market);
        setMessage(null);
      } else if (parsed.market === "CAT") {
        setOverlay(null);
        onCatalogSearch?.();
      } else {
        setOverlay(`PENDING:${parsed.market}`);
      }
      logTerminalEvent("cmd_run", { function: parsed.market });
      return true;
    }
    const target = parsed.ticker || state.current.ticker;
    if (!target) {
      if (parsed.func) setMessage({ tone: "error", text: copy.needTicker });
      return false;
    }
    if (isEmptyCommand(parsed)) return false;
    go({
      ticker: target,
      func: parsed.func || state.current.func || "SUM",
      form: parsed.form || state.current.form,
    });
    return true;
  }, [index, go, copy, onCatalogSearch]);

  // A standard chosen inside a screen (the НСБУ/МСФО switch) is part of the
  // address, but not a new step back.
  const setForm = React.useCallback((value) => {
    setFormState(value);
    writeUrl({ ...state.current, form: value }, false);
  }, []);

  const setFullHistory = React.useCallback((value) => {
    setFullHistoryState(value);
    writeUrl({ ...state.current, fullHistory: value }, false);
  }, []);

  const back = React.useCallback(() => {
    if (depth.current > 0) {
      depth.current -= 1;
      window.history.back();
    }
  }, []);

  React.useEffect(() => {
    const onPop = () => {
      const screen = readUrl();
      if (screen.ticker && screen.ticker !== state.current.ticker) setTicker(screen.ticker);
      setFunc(screen.func);
      setFormState(screen.form);
      setFullHistoryState(screen.fullHistory);
      setOverlay(null);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [setTicker]);

  React.useEffect(() => {
    const onKey = (event) => {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const typing = isTyping(event.target);
      if (event.key === "/" && !typing) {
        event.preventDefault();
        inputRef.current?.focus();
      } else if (event.key === "Escape") {
        if (overlay) setOverlay(null);
        else if (!typing) back();
      } else if (!typing && state.current.ticker) {
        const tab = TAB_KEYS.find((t) => t.key === event.key);
        if (tab) go({ func: tab.code });
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [overlay, back, go]);

  const fromYear = fullHistory ? null : DEFAULT_FROM_YEAR;
  return { func, form, setForm, fullHistory, setFullHistory, fromYear, overlay, setOverlay, message, setMessage, last, run, go, back, inputRef, index };
}
