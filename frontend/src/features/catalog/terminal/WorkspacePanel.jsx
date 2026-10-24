import React from 'react';
import { words } from '../../../shared/TerminalTables.jsx';

export function WorkspacePanel({ panel, lang, children, onRemove, saving }) {
  const element = React.useRef(null);
  const button = React.useRef(null);
  const native = React.useRef(false);
  const [expanded, setExpanded] = React.useState(false);
  const revealControl = React.useCallback(() => {
    requestAnimationFrame(() => button.current?.scrollIntoView({ block: 'start', behavior: 'instant' }));
  }, []);
  const restore = React.useCallback(() => {
    setExpanded(false);
    if (document.fullscreenElement === element.current) document.exitFullscreen?.().catch(() => {});
  }, []);

  React.useEffect(() => {
    const changed = () => {
      if (document.fullscreenElement === element.current) native.current = true;
      else if (native.current) { native.current = false; setExpanded(false); revealControl(); }
    };
    document.addEventListener('fullscreenchange', changed);
    return () => document.removeEventListener('fullscreenchange', changed);
  }, [revealControl]);

  React.useEffect(() => {
    if (!expanded) return undefined;
    const previousOverflow = document.body.style.overflow;
    const toggleButton = button.current;
    const keydown = event => {
      // Let a source passport close itself before leaving the report.
      if (event.key === 'Escape') {
        event.stopImmediatePropagation(); // Do not also close the PNL workspace.
        if (!element.current?.querySelector('dialog[open]')) { event.preventDefault(); restore(); }
        return;
      }
      if (element.current?.querySelector('dialog[open]')) return;
      if (event.key !== 'Tab') return;
      const controls = [...element.current.querySelectorAll('button, a[href], input, select, textarea, [tabindex]')]
        .filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length);
      const target = event.shiftKey ? controls.at(-1) : controls[0];
      if (document.activeElement === (event.shiftKey ? controls[0] : controls.at(-1))) {
        event.preventDefault(); target?.focus();
      }
    };
    document.body.style.overflow = 'hidden';
    document.body.classList.add('terminal-panel-fullscreen');
    document.addEventListener('keydown', keydown, true);
    toggleButton?.focus({ preventScroll: true });
    return () => {
      document.body.style.overflow = previousOverflow;
      document.body.classList.remove('terminal-panel-fullscreen');
      document.removeEventListener('keydown', keydown, true);
      toggleButton?.focus({ preventScroll: true });
      if (!document.fullscreenElement) revealControl();
    };
  }, [expanded, restore, revealControl]);

  const toggle = () => {
    if (expanded) { restore(); return; }
    setExpanded(true);
    // Embedded/mobile browsers can reject or omit the native API. The CSS
    // viewport layout takes effect immediately and preserves the mounted report.
    try { element.current?.requestFullscreen?.()?.catch?.(() => {}); } catch { /* use viewport layout */ }
  };

  return <section ref={element} className={`panel terminal-work-panel${expanded ? ' is-expanded' : ''}`}
    data-terminal-ticker={panel.ticker} data-terminal-function={panel.func}
    data-terminal-standard={panel.form} data-terminal-scope={panel.scope}>
    <div className="terminal-panel-actions"><strong>{panel.ticker} · {panel.func}</strong><div>
      <button ref={button} type="button" className="ghost-btn" aria-pressed={expanded} onClick={toggle}>
        {expanded ? words(lang, 'Свернуть', 'Kichraytirish', 'Restore') : words(lang, 'На весь экран', 'To‘liq ekran', 'Full screen')}
      </button>
      <button type="button" className="ghost-btn" disabled={saving} aria-label={words(lang, 'Удалить панель', 'Panelni o‘chirish', 'Remove panel')}
        onClick={() => { restore(); onRemove(); }}>×</button>
    </div></div>
    {children}
  </section>;
}
