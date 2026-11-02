import React from "react";
import { suggestCommands } from "../../../lib/terminalCommands.js";
import { terminalCopy } from "./terminalCopy.js";

// The terminal's one input. Suggestions follow the word being typed: tickers
// (and company names) first, then function codes once a ticker is on the line.
// ↑/↓ choose a result; Enter or a click opens it. Tab completes a suggestion
// so experienced users can continue typing a command.
function CommandBar({ terminal, companies, lang, screenLabel, text, onTextChange }) {
  const copy = terminalCopy(lang);
  const [open, setOpen] = React.useState(false);
  const [active, setActive] = React.useState(-1);
  const listId = "terminal-command-suggestions";
  const suggestions = React.useMemo(
    () => (open && text.trim() ? suggestCommands(text, companies, lang) : []),
    [open, text, companies, lang]);

  const complete = (suggestion) => {
    onTextChange(suggestion.value);
    setActive(-1);
    terminal.inputRef.current?.focus();
  };

  const run = (value) => {
    if (terminal.run(value)) {
      onTextChange("");
      setActive(-1);
      setOpen(false);
    }
  };

  const select = (suggestion) => {
    run(suggestion.value);
    terminal.inputRef.current?.focus();
  };

  const submit = (event) => {
    event.preventDefault();
    if (active >= 0 && suggestions[active]) {
      select(suggestions[active]);
      return;
    }
    if (!text.trim()) return;
    const normalized = value => value.trim().replace(/\s+/g, " ").toLowerCase();
    const company = companies.find(company => normalized(company.company_name || "") === normalized(text));
    run(company?.ticker || text);
  };

  const onKeyDown = (event) => {
    if (event.key === "ArrowDown" && suggestions.length) {
      event.preventDefault();
      setActive((i) => (i + 1) % suggestions.length);
    } else if (event.key === "ArrowUp" && suggestions.length) {
      event.preventDefault();
      setActive((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
    } else if (event.key === "Tab" && suggestions.length && !event.shiftKey) {
      event.preventDefault();
      complete(suggestions[active >= 0 ? active : 0]);
    } else if (event.key === "Escape") {
      // Close suggestions without the native search input also clearing text.
      event.preventDefault();
      if (open && suggestions.length) {
        event.stopPropagation();
        setOpen(false);
      } else {
        event.currentTarget.blur();
      }
    }
  };

  return (
    <form className="terminal-command" onSubmit={submit} role="search" aria-label={copy.commandLabel}>
      <div className="terminal-command-row">
        <label className="catalog-search-field terminal-command-field">
          <svg className="terminal-search-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden="true">
            <circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4.5 4.5" />
          </svg>
          <input
            ref={terminal.inputRef}
            type="search"
            value={text}
            onChange={(event) => { onTextChange(event.target.value); setOpen(true); setActive(-1); }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 120)}
            onKeyDown={onKeyDown}
            placeholder={copy.placeholder}
            aria-label={copy.commandLabel}
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={suggestions.length > 0}
            aria-controls={listId}
            aria-activedescendant={suggestions[active] ? `${listId}-${active}` : undefined}
            aria-invalid={terminal.message?.tone === "error" || undefined}
            aria-describedby={terminal.message ? "terminal-search-message" : undefined}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
          />
          {screenLabel && <span className="terminal-screen-label">{screenLabel}</span>}
        </label>
        <button className="primary-btn terminal-run" type="submit">{copy.run}</button>
      </div>
      {suggestions.length > 0 && (
        <ul className="terminal-suggestions" id={listId} role="listbox">
          {suggestions.map((s, i) => (
            <li
              key={`${s.kind}:${s.code}`}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseDown={event => event.preventDefault()}
              onClick={() => select(s)}
            >
              <strong>{s.code}</strong>
              <span>{s.label}</span>
            </li>
          ))}
        </ul>
      )}
      {terminal.message && (
        <p id="terminal-search-message" className={`terminal-message tone-${terminal.message.tone}`} role="status">{terminal.message.text}</p>
      )}
    </form>
  );
}

export { CommandBar };
