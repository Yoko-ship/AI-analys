import React from "react";
import {
  ISSUER_FUNCTIONS, MARKET_FUNCTIONS, TAB_KEYS, commandText, functionLabel,
} from "../../../lib/terminalCommands.js";
import { reportScreenLoad } from "../../../lib/terminalJournal.js";
import { edHeadline, newsArticlePath, newsRelTime } from "../../news/index.js";
import { READY_FUNCTIONS } from "./useTerminal.js";
import { terminalCopy } from "./terminalCopy.js";

const READY_MARKET = new Set(["CAT", "HELP", "LAST"]);

// The issuer's functions as tabs: the same registry as the command line and
// the number keys, so a reader who never types still finds every screen.
function FunctionTabs({ terminal, lang }) {
  const copy = terminalCopy(lang);
  const keyOf = Object.fromEntries(TAB_KEYS.map((t) => [t.code, t.key]));
  return (
    <div className="terminal-tabs-row">
    <nav className="terminal-tabs" aria-label={copy.tabsLabel}>
      {ISSUER_FUNCTIONS.map((fn) => {
        const ready = READY_FUNCTIONS.has(fn.code);
        return (
          <button
            key={fn.code}
            type="button"
            className={`terminal-tab ${terminal.func === fn.code ? "active" : ""} ${ready ? "" : "is-pending"}`}
            aria-current={terminal.func === fn.code ? "page" : undefined}
            title={ready ? functionLabel(fn.code, lang) : `${functionLabel(fn.code, lang)} — ${copy.soon}`}
            onClick={() => terminal.go({ func: fn.code })}
          >
            {keyOf[fn.code] && <kbd>{keyOf[fn.code]}</kbd>}
            <strong>{fn.code}</strong>
            <span>{functionLabel(fn.code, lang)}</span>
          </button>
        );
      })}
    </nav>
    <div className="fin-freq terminal-history" role="group" aria-label={copy.historyLabel}>
      {[[false, copy.historyRecent], [true, copy.historyAll]].map(([all, label]) => (
        <button key={label} type="button" className={`fin-freq-btn ${terminal.fullHistory === all ? "active" : ""}`}
          aria-pressed={terminal.fullHistory === all} onClick={() => terminal.setFullHistory(all)}>{label}</button>
      ))}
    </div>
    </div>
  );
}

function Dialog({ title, onClose, lang, children }) {
  const copy = terminalCopy(lang);
  return (
    <section className="terminal-overlay panel" role="dialog" aria-label={title}>
      <header>
        <h3>{title}</h3>
        <button type="button" className="ghost-btn" onClick={onClose}>{copy.close} · Esc</button>
      </header>
      {children}
    </section>
  );
}

function HelpPanel({ lang, onClose, onRun }) {
  const copy = terminalCopy(lang);
  const row = (fn, ready) => (
    <tr key={fn.code}>
      <td><button type="button" className="terminal-code" onClick={() => onRun(fn.code)}>{fn.code}</button></td>
      <td>{fn[lang] || fn.ru}{!ready && <em className="terminal-soon"> · {copy.soon}</em>}</td>
      <td className="num">{TAB_KEYS.find((t) => t.code === fn.code)?.key || ""}</td>
    </tr>
  );
  return (
    <Dialog title={copy.helpTitle} onClose={onClose} lang={lang}>
      <p className="muted">{copy.helpIntro}</p>
      <div className="terminal-help-grid">
        <table className="terminal-table">
          <caption>{copy.issuerFunctions}</caption>
          <tbody>{ISSUER_FUNCTIONS.map((fn) => row(fn, READY_FUNCTIONS.has(fn.code)))}</tbody>
        </table>
        <div>
          <table className="terminal-table">
            <caption>{copy.marketFunctions}</caption>
            <tbody>{MARKET_FUNCTIONS.map((fn) => row(fn, READY_MARKET.has(fn.code)))}</tbody>
          </table>
          <table className="terminal-table">
            <caption>{copy.keys}</caption>
            <tbody>{copy.keyRows.map(([key, text]) => <tr key={key}><td><kbd>{key}</kbd></td><td>{text}</td></tr>)}</tbody>
          </table>
          <p className="muted terminal-examples">
            {copy.examples}: <code>SQBN PL</code> · <code>AGBA MSFO BS</code> · <code>KVTS DQ</code> · {copy.aliases}
          </p>
        </div>
      </div>
    </Dialog>
  );
}

function LastPanel({ terminal, lang }) {
  const copy = terminalCopy(lang);
  return (
    <Dialog title={copy.lastTitle} onClose={() => terminal.setOverlay(null)} lang={lang}>
      {terminal.last.length ? (
        <ol className="terminal-last">
          {terminal.last.map((screen) => (
            <li key={screen.text}>
              <button type="button" onClick={() => terminal.go({ ticker: screen.ticker, func: screen.func, form: screen.form })}>
                <strong>{commandText(screen)}</strong>
                <span>{functionLabel(screen.func, lang)}</span>
              </button>
            </li>
          ))}
        </ol>
      ) : <p className="muted">{copy.lastEmpty}</p>}
    </Dialog>
  );
}

function PendingPanel({ code, lang, onClose }) {
  const copy = terminalCopy(lang);
  return (
    <Dialog title={copy.pendingTitle(`${code} · ${functionLabel(code, lang)}`)} onClose={onClose} lang={lang}>
      <p className="muted">{copy.pendingBody}</p>
    </Dialog>
  );
}

// One request, its journal report, and the three states every screen has.
function useScreenData(url, { ticker, func, form }) {
  const [state, setState] = React.useState({ data: null, error: false });
  React.useEffect(() => {
    if (!url) return undefined;
    let alive = true;
    const startedAt = performance.now();
    setState({ data: null, error: false });
    fetch(url)
      .then(async (r) => {
        const d = await r.json().catch(() => null);
        if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status}`), { errorId: d?.error_id });
        return d;
      })
      .then((d) => {
        if (!alive) return;
        setState({ data: d, error: false });
        reportScreenLoad({ ticker, func, form, startedAt });
      })
      .catch((error) => {
        if (!alive) return;
        setState({ data: null, error: true });
        reportScreenLoad({ ticker, func, form, startedAt, error: error.message, errorId: error.errorId });
      });
    return () => { alive = false; };
  }, [url, ticker, func, form]);
  return state;
}

function NewsScreen({ ticker, lang }) {
  const copy = terminalCopy(lang);
  const { data, error } = useScreenData(`/api/news/ticker/${encodeURIComponent(ticker)}?limit=30&days=90`,
    { ticker, func: "CN" });
  if (error) return <p className="terminal-empty tone-error">{copy.newsError}</p>;
  if (!data) return <p className="terminal-empty">{copy.loading}</p>;
  const items = data.items || [];
  if (!items.length) return <p className="terminal-empty">{copy.newsEmpty}</p>;
  return (
    <ul className="terminal-news">
      {items.map((item) => {
        const headline = edHeadline(item, lang);
        return (
          <li key={item.id || item.url}>
            <a href={newsArticlePath(item, lang)}>{headline.text}</a>
            <span className="muted">{[newsRelTime(item.published_at || item.collected_at, lang), item.source_name || item.source_id].filter(Boolean).join(" · ")}</span>
          </li>
        );
      })}
    </ul>
  );
}

function QualityScreen({ ticker, form, lang, fromYear = null }) {
  const copy = terminalCopy(lang);
  const badge = useScreenData(`/api/audit/badge/${encodeURIComponent(ticker)}`, { ticker, func: "DQ", form });
  const annual = useScreenData(`/api/company/${encodeURIComponent(ticker)}/financials?form=${form}`, { ticker, func: "DQ", form });
  const quarterly = useScreenData(`/api/company/${encodeURIComponent(ticker)}/financials?form=${form}&freq=quarterly`, { ticker, func: "DQ", form });
  if (badge.error) return <p className="terminal-empty tone-error">{copy.dqError}</p>;
  if (!badge.data) return <p className="terminal-empty">{copy.loading}</p>;
  const b = badge.data;
  const verdict = b.status === "blocking" ? copy.dqBlocking : b.status === "warning" ? copy.dqWarning : copy.dqOk;
  const gaps = [
    ...(annual.data?.data_gaps || []).map((g) => ({ ...g, freq: copy.annual })),
    ...(quarterly.data?.data_gaps || []).map((g) => ({ ...g, freq: copy.quarterly })),
  ];
  const uniqueGaps = [...new Map(gaps
    .filter((g) => !fromYear || Number(String(g.period).slice(0, 4)) >= fromYear)
    .map((g) => [`${g.freq}:${g.period}:${g.code}`, g])).values()];
  return (
    <div className="terminal-dq">
      <div className={`terminal-dq-status status-${b.status}`}>
        <strong>{verdict}</strong>
        <span>{copy.dqBlockingCount}: {b.blocking} · {copy.dqWarningsCount}: {b.warnings}</span>
        {b.last_run_at && <small>{copy.dqLastRun}: {String(b.last_run_at).slice(0, 16).replace("T", " ")}</small>}
      </div>
      {b.metrics_withheld?.length > 0 && (
        <p><strong>{copy.dqWithheld}:</strong> {b.metrics_withheld.join(", ")}</p>
      )}
      {b.reasons?.length > 0 && (
        <>
          <h4>{copy.dqReasons}</h4>
          <ul>{b.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </>
      )}
      <h4>{copy.dqGaps} · {form === "MSFO" ? "МСФО" : "НСБУ"}</h4>
      {annual.data || quarterly.data ? (
        uniqueGaps.length ? (
          <table className="terminal-table">
            <tbody>
              {uniqueGaps.map((g) => (
                <tr key={`${g.freq}:${g.period}:${g.code}`}>
                  <td>{g.freq}</td><td>{g.period}</td><td><code>{g.code}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted">{copy.dqNoGaps}</p>
      ) : <p className="muted">{copy.loading}</p>}
      <p className="muted">{copy.dqSource}</p>
    </div>
  );
}

export { FunctionTabs, HelpPanel, LastPanel, NewsScreen, PendingPanel, QualityScreen };
