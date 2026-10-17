import React from "react";
import { suggestCommands } from "../../../lib/terminalCommands.js";
import { terminalCopy } from "./terminalCopy.js";

// The terminal's one input. Suggestions follow the word being typed: tickers
// (and company names) first, then function codes once a ticker is on the line.
// ↑/↓ pick a suggestion, Tab or Enter on a picked one completes it, and Enter
// on the line itself runs it.
function CommandBar({ terminal, companies, lang, screenLabel }) {
  const copy = terminalCopy(lang);
  const [text, setText] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const [active, setActive] = React.useState(-1);
  const listId = "terminal-command-suggestions";
  const suggestions = React.useMemo(
    () => (open && text.trim() ? suggestCommands(text, companies, lang) : []),
    [open, text, companies, lang]);

  const complete = (suggestion) => {
    setText(suggestion.value);
    setActive(-1);
    terminal.inputRef.current?.focus();
  };

  const submit = (event) => {
    event.preventDefault();
    if (active >= 0 && suggestions[active]) {
      complete(suggestions[active]);
      return;
    }
    if (!text.trim()) return;
    if (terminal.run(text)) {
      setText("");
      setOpen(false);
    }
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
          <span className="terminal-prompt" aria-hidden="true">&gt;</span>
          <input
            ref={terminal.inputRef}
            type="text"
            value={text}
            onChange={(event) => { setText(event.target.value); setOpen(true); setActive(-1); }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 120)}
            onKeyDown={onKeyDown}
            placeholder={copy.placeholder}
            aria-label={copy.commandLabel}
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={suggestions.length > 0}
            aria-controls={listId}
            aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
            autoComplete="off"
            autoCapitalize="characters"
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
              onMouseDown={(event) => { event.preventDefault(); complete(s); }}
            >
              <strong>{s.code}</strong>
              <span>{s.label}</span>
            </li>
          ))}
        </ul>
      )}
      {terminal.message && (
        <p className={`terminal-message tone-${terminal.message.tone}`} role="status">{terminal.message.text}</p>
      )}
    </form>
  );
}

export { CommandBar };
