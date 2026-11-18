import React from 'react';
import { CompanyLogo } from '../../shared/CompanyLogo.jsx';
import { safeHref } from '../../lib/safeHref.js';
import { addDays, eventTitle, formatDay, viewWindow } from './calendarEvents.js';

const DAY_CAP = 20;

function TileDay({ iso, events, today, ctx, securitiesMap }) {
  const [expanded, setExpanded] = React.useState(false);
  const { tx, locale, lang, forms, open } = ctx;
  const label = formatDay(iso, locale, { weekday:'long', day:'numeric', month:'short' });
  return <section className={`newscal-tile-day${iso === today ? ' today' : ''}`} data-date={iso} aria-label={label}>
    <header className="newscal-tile-dayhead">
      <time dateTime={iso}>{label}</time>
      {events.length > 0 && <span aria-label={tx.dayEvents(events.length)}>{events.length}</span>}
    </header>
    <div className="newscal-day-tiles">
      {(expanded ? events : events.slice(0, DAY_CAP)).map(ev => {
        const ticker = ev.ticker || ev.tickers?.[0] || '';
        const name = ev.organization || securitiesMap[ticker]?.name || ticker;
        const logo = safeHref(securitiesMap[ticker]?.logo_url);
        const title = `${name} · ${tx.typeOne[ev.type]} · ${eventTitle(ev,lang,tx,locale,forms)}${ev.time ? ` · ${ev.time}` : ''}`;
        return <button type="button" key={ev.id} className={`newscal-event-tile ev-${ev.type}`}
          title={title} aria-label={title} onClick={()=>open(ev)}>
          <span className="newscal-tile-logo" aria-hidden="true">
            <CompanyLogo key={`${ticker}-${logo || ''}`} logo={logo} name={name} ticker={ticker} />
          </span>
          <span className="newscal-tile-symbol">{ticker || name}</span>
          <span className={`newscal-dot ev-${ev.type}`} aria-hidden="true" />
        </button>;
      })}
      {!expanded && events.length > DAY_CAP && <button type="button" className="newscal-tile-more"
        onClick={()=>setExpanded(true)} aria-label={tx.more(events.length-DAY_CAP)} aria-expanded="false">+{tx.more(events.length-DAY_CAP)}</button>}
    </div>
    {!events.length && <span className="newscal-tile-empty" aria-label={tx.dayEvents(0)}>—</span>}
  </section>;
}

export function CalendarTiles({ cal, ctx, securitiesMap = {} }) {
  const { start } = viewWindow('tiles',cal.anchor);
  const weeks = Array.from({length:4},(_,i)=>Array.from({length:7},(_,j)=>addDays(start,i*7+j)));
  return <div className="newscal-tiles" aria-label={ctx.monthLabel}>
    {!cal.visible.length && <p className="led-empty">{cal.filtered ? ctx.tx.emptyFiltered : ctx.tx.empty}</p>}
    {weeks.map(days => <section key={days[0]} className="newscal-tile-week" data-week={days[0]}>
      <h3>{ctx.tx.weekOf(formatDay(days[0],ctx.locale,{day:'numeric',month:'long'}))}</h3>
      <div className="newscal-tile-days">
        {days.filter((iso,i)=>i < 5 || cal.byDay.has(iso)).map(iso =>
          <TileDay key={iso} iso={iso} events={cal.byDay.get(iso) || []} today={cal.today} ctx={ctx} securitiesMap={securitiesMap} />)}
      </div>
    </section>)}
  </div>;
}
