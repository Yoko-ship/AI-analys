import {useRef, useState} from 'react';
import * as Popover from '@radix-ui/react-popover';
import {industrySections} from '../../lib/companyIndustries.js';
import {marketIndustryLabel} from '../../shared/industryCopy.js';
import './industryFilter.css';

const labels = {
  ru: {all: 'Все отрасли', search: 'Найти отрасль', clear: 'Очистить поиск', empty: 'Ничего не найдено'},
  en: {all: 'All sectors', search: 'Find a sector', clear: 'Clear search', empty: 'No matches found'},
  uz: {all: 'Barcha tarmoqlar', search: 'Tarmoqni qidirish', clear: 'Qidiruvni tozalash', empty: 'Hech narsa topilmadi'},
};

function Check() {
  return <svg className="industry-check" width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m4 10 4 4 8-8" /></svg>;
}

export function IndustryFilter({lang, label, options, value, onChange}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const searchRef = useRef(null);
  const copy = labels[lang] || labels.ru;
  const selectedLabel = marketIndustryLabel(lang, value);
  const needle = query.trim().toLocaleLowerCase();
  const visible = options.flatMap(section => {
    const title = marketIndustryLabel(lang, section.sector);
    const code = industrySections[section.sector]?.code;
    const parentMatches = !needle || title.toLocaleLowerCase().includes(needle) || code?.toLowerCase() === needle;
    const groups = section.groups.filter(group => group.id && (parentMatches || marketIndustryLabel(lang, `group:${group.id}`).toLocaleLowerCase().includes(needle)));
    return parentMatches || groups.length ? [{...section, title, code, groups}] : [];
  });
  const changeOpen = next => {
    setOpen(next);
    if (!next) setQuery('');
  };
  const choose = next => {
    onChange(next || null);
    changeOpen(false);
  };
  return <Popover.Root open={open} onOpenChange={changeOpen}>
    <div className="market-sector-select">
      <Popover.Trigger asChild>
        <button type="button" className="market-industry-trigger" data-value={value || ''} data-active={value ? 'true' : undefined}
          title={`${label}: ${selectedLabel}`}>
          <span className="industry-trigger-caption">{label}:</span>
          <span className="industry-trigger-value">{selectedLabel}</span>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
        </button>
      </Popover.Trigger>
    </div>
    <Popover.Portal>
      <Popover.Content className="industry-menu" aria-label={label} align="start" side="bottom" sideOffset={6} collisionPadding={12}>
        <div className="industry-search">
          <svg width="17" height="17" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="m13 13 4 4" /></svg>
          <input ref={searchRef} type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={copy.search} aria-label={copy.search} autoComplete="off" />
          {query && <button type="button" className="industry-search-clear" aria-label={copy.clear} onClick={() => { setQuery(''); searchRef.current?.focus(); }}>
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m4 4 8 8M12 4l-8 8" /></svg>
          </button>}
        </div>
        <button type="button" className="industry-option industry-all" data-value="" aria-pressed={!value} onClick={() => choose('')}>
          <svg className="industry-all-icon" width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><rect x="3" y="3" width="5" height="5" rx="1"/><rect x="12" y="3" width="5" height="5" rx="1"/><rect x="3" y="12" width="5" height="5" rx="1"/><rect x="12" y="12" width="5" height="5" rx="1"/></svg>
          <span>{copy.all}</span>{!value && <Check />}
        </button>
        <div className="industry-results">
          {visible.length ? <ul className="industry-menu-sections">
            {visible.map(section => <li key={section.sector} className="industry-menu-section">
              <button type="button" className="industry-option industry-menu-section-title" data-value={section.sector}
                aria-pressed={value === section.sector} onClick={() => choose(section.sector)}>
                <span className="industry-menu-section-code" aria-hidden="true">{section.code || '·'}</span>
                <span>{section.title}</span>{value === section.sector && <Check />}
              </button>
              {section.groups.length > 0 && <ul className="industry-subgroups">
                {section.groups.map(group => <li key={group.id}>
                  <button type="button" className="industry-option" data-value={`group:${group.id}`} aria-pressed={value === `group:${group.id}`}
                    onClick={() => choose(`group:${group.id}`)}>
                    <span>{marketIndustryLabel(lang, `group:${group.id}`)}</span>{value === `group:${group.id}` && <Check />}
                  </button>
                </li>)}
              </ul>}
            </li>)}
          </ul> : <p className="industry-empty" role="status">{copy.empty}</p>}
        </div>
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>;
}
