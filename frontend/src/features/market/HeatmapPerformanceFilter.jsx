import {useEffect, useId, useRef, useState} from 'react';
import * as Popover from '@radix-ui/react-popover';
import {CHANGE_PERIODS, changePeriodLabel} from '../../shared/marketPeriods.jsx';
import './heatmapPerformanceFilter.css';

const labels = {
  ru: {title: 'Период изменения', search: 'Найти период', clear: 'Очистить поиск', group: 'Изменение цены', empty: 'Ничего не найдено'},
  uz: {title: 'O‘zgarish davri', search: 'Davrni qidirish', clear: 'Qidiruvni tozalash', group: 'Narx o‘zgarishi', empty: 'Hech narsa topilmadi'},
  en: {title: 'Change period', search: 'Find a period', clear: 'Clear search', group: 'Performance', empty: 'No matches found'},
};

export function HeatmapPerformanceFilter({lang, value, onChange}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const searchRef = useRef(null);
  const triggerRef = useRef(null);
  const headingId = useId();
  const copy = labels[lang] || labels.ru;
  useEffect(() => {
    if (!open) return;
    // A shorter viewport (including the phone keyboard) can leave a sidebar
    // trigger below the screen. Keep the anchor visible so its menu can flip.
    const keepAnchorVisible = () => {
      const bounds = triggerRef.current?.getBoundingClientRect();
      const viewport = window.visualViewport;
      const top = viewport?.offsetTop || 0;
      const bottom = top + (viewport?.height || window.innerHeight);
      if (bounds && (bounds.top < top || bounds.bottom > bottom)) {
        triggerRef.current.scrollIntoView({block: 'nearest', inline: 'nearest', behavior: 'instant'});
      }
    };
    window.addEventListener('resize', keepAnchorVisible);
    window.visualViewport?.addEventListener('resize', keepAnchorVisible);
    return () => {
      window.removeEventListener('resize', keepAnchorVisible);
      window.visualViewport?.removeEventListener('resize', keepAnchorVisible);
    };
  }, [open]);
  const needle = query.trim().toLocaleLowerCase();
  const title = code => changePeriodLabel(code, lang, 'performance');
  // Read the board's supported periods, so the menu cannot offer a timeframe
  // whose numbers would silently fall back to the session's values.
  const periods = CHANGE_PERIODS.filter(({code}) => [code, title(code), changePeriodLabel(code, lang), changePeriodLabel(code, lang, 'short')]
    .some(label => label.toLocaleLowerCase().includes(needle)));
  const changeOpen = next => { setOpen(next); if (!next) setQuery(''); };
  const choose = code => { onChange(code); changeOpen(false); };
  const navigate = event => {
    const options = [...event.currentTarget.querySelectorAll('[data-period]')];
    const index = options.indexOf(event.target);
    const searching = event.target === searchRef.current;
    if (event.key === 'Enter' && searching && periods.length) {
      event.preventDefault(); choose(periods[0].code);
    } else if (event.key === 'ArrowDown' && (searching || index >= 0) && options.length) {
      event.preventDefault(); options[Math.min(index + 1, options.length - 1)].focus();
    } else if (event.key === 'ArrowUp' && index >= 0) {
      event.preventDefault(); (options[index - 1] || searchRef.current)?.focus();
    } else if ((event.key === 'Home' || event.key === 'End') && index >= 0) {
      event.preventDefault(); options[event.key === 'Home' ? 0 : options.length - 1].focus();
    }
  };
  return <Popover.Root open={open} onOpenChange={changeOpen}>
    <Popover.Trigger asChild>
      <button ref={triggerRef} type="button" className="heatmap-performance-trigger" aria-label={`${copy.title}: ${title(value)}`}>
        <span>{title(value)}</span>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
      </button>
    </Popover.Trigger>
    <Popover.Portal>
      <Popover.Content className="heatmap-performance-menu" aria-label={copy.title} align="start" side="bottom"
        sideOffset={6} collisionPadding={10} onKeyDown={navigate}>
        <div className="heatmap-performance-search">
          <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="m13 13 4 4" /></svg>
          <input ref={searchRef} type="search" value={query} onChange={event => setQuery(event.target.value)}
            placeholder={copy.search} aria-label={copy.search} autoComplete="off" spellCheck={false} />
          {query && <button type="button" aria-label={copy.clear} onClick={() => { setQuery(''); searchRef.current?.focus(); }}>×</button>}
        </div>
        <div className="heatmap-performance-results" role="group" aria-labelledby={headingId}>
          <p id={headingId}>{copy.group}</p>
          {periods.length ? periods.map(({code}) => <button key={code} type="button" data-period={code}
            aria-pressed={value === code} onClick={() => choose(code)}>
            <span>{title(code)}</span>
            {value === code && <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m4 10 4 4 8-8" /></svg>}
          </button>) : <p className="heatmap-performance-empty" role="status">{copy.empty}</p>}
        </div>
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>;
}
