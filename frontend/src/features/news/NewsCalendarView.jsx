import React from "react";
import { createPortal } from "react-dom";
import { NEWS_TX, interceptNav, newsArticlePath } from "./editorial.jsx";
import { EVENT_TYPES, calendarAnnouncementPath } from "./calendarCopy.js";
import {
  companyOptions, countByType, daysBetween, dividendKind, eventTitle, isBondIncome, eventsToCsv, formatAmount, formatDay,
  monthGrid, splitDay, upcomingEvents, weekRange,
} from "./calendarEvents.js";
import { useNewsCalendar } from "./useNewsCalendar.js";

// A month list stops here and offers the rest: a busy reporting week files
// hundreds of material facts, and nobody reads them as one scroll.
const LIST_STEP = 40;
// A reporting day files dozens of facts; a week column shows the first few.
const WEEK_DAY_CAP = 8;

// «"Navoiypaxtasanoat" AJ» → «Navoiypaxtasanoat»: a 120-pixel pill has room
// for the name, not for its quotes and legal form.
const LEGAL_FORM = /^(?:АО|AO|AJ|АЖ|ATB|АТБ|AITB|ATIB|XATB|ХАТБ|ЧАКБ|MCHJ|МЧЖ|OOO|ООО|QK|ҚК|AK|АК|HAJ|ХАЖ|MMT|ММТ|AJ\.)$/i;
function shortName(name) {
  const words = String(name || "").replace(/["«»“”„'`]/g, " ").split(/\s+/).filter(Boolean);
  const kept = words.filter((w) => !LEGAL_FORM.test(w));
  return (kept.length ? kept : words).join(" ");
}

function TypeDot({ type }) {
  return <span className={`newscal-dot ev-${type}`} aria-hidden="true" />;
}

/** «через 3 дня» / «вчера» against today on the exchange's clock. */
function relDay(iso, today, tx) {
  const n = daysBetween(today, iso);
  return n >= 0 ? tx.inDays(n) : tx.daysAgo(-n);
}

function EventRow({ ev, today, ctx, showDate = true }) {
  const { tx, locale, lang, forms, open } = ctx;
  const title = eventTitle(ev, lang, tx, locale, forms);
  const when = ev.date < today ? "past" : ev.date === today ? "today" : "future";
  return (
    <button type="button" className={`newscal-row ev-${ev.type} is-${when}`} onClick={() => open(ev)}
      aria-label={`${tx.typeOne[ev.type]}: ${ev.organization || ""} — ${title}`}>
      {showDate && (
        <span className="newscal-row-date">
          {formatDay(ev.date, locale, { day: "numeric", month: "short" })}
          {ev.time ? ` · ${ev.time}` : ""}
        </span>
      )}
      <span className="newscal-row-type"><TypeDot type={ev.type} />{tx.typeOne[ev.type]}</span>
      <span className="newscal-row-body">
        <span className="newscal-row-org">
          {ev.organization || ev.ticker}
          {ev.ticker && <span className="newscal-tk">{ev.ticker}</span>}
        </span>
        <span className="newscal-row-title" title={ev.title || undefined}>{title}</span>
      </span>
    </button>
  );
}

function EventList({ items, today, ctx, grouped }) {
  const [shown, setShown] = React.useState(LIST_STEP);
  React.useEffect(() => setShown(LIST_STEP), [items]);
  const { tx, locale } = ctx;
  const slice = items.slice(0, shown);
  let lastDay = null;
  let todayMarked = false;
  return (
    <div className="newscal-list">
      {slice.map((ev) => {
        const head = grouped && ev.date !== lastDay;
        // One rule across the list where the past ends — the reader's «now».
        const marker = grouped && !todayMarked && ev.date >= today && items[0].date < today;
        if (marker) todayMarked = true;
        lastDay = ev.date;
        return (
          <React.Fragment key={ev.id}>
            {marker && <div className="newscal-now" role="separator"><span>{tx.todayTag}</span></div>}
            {head && (
              <div className={`newscal-mh${ev.date === today ? " is-today" : ""}`}>
                <span>{formatDay(ev.date, locale, { weekday: "long", day: "numeric", month: "long" })}</span>
                <span className="newscal-mh-rel">{relDay(ev.date, today, tx)}</span>
              </div>
            )}
            <EventRow ev={ev} today={today} ctx={ctx} showDate={!grouped} />
          </React.Fragment>
        );
      })}
      {items.length > shown && (
        <button type="button" className="ghost-btn newscal-more-btn" onClick={() => setShown((n) => n + LIST_STEP)}>
          {tx.more(items.length - shown)}
        </button>
      )}
    </div>
  );
}

function MonthView({ cal, ctx }) {
  const { anchor, byDay, today, day, setDay, visible } = cal;
  const { tx, open } = ctx;
  const grid = monthGrid(anchor);
  const inMonth = (iso) => iso >= grid.first && iso <= grid.last;
  const listItems = day ? byDay.get(day) || [] : visible.filter((ev) => inMonth(ev.date));
  return (
    <>
      <div className="newscal-grid" role="grid">
        {tx.weekdays.map((w) => <div key={w} className="newscal-dow" role="columnheader">{w}</div>)}
        {grid.days.map((iso) => {
          const evs = byDay.get(iso) || [];
          const types = EVENT_TYPES.filter((t) => evs.some((ev) => ev.type === t));
          const cls = ["newscal-cell", inMonth(iso) ? "" : "out", iso < today ? "past" : "",
            iso === today ? "today" : "", day === iso ? "selected" : "", evs.length ? "has-events" : ""]
            .filter(Boolean).join(" ");
          return (
            <div key={iso} className={cls} role="gridcell" aria-selected={day === iso}
              onClick={() => evs.length && setDay(day === iso ? null : iso)}>
              <button type="button" className="newscal-daynum" disabled={!evs.length}
                aria-label={`${ctx.fmtLong(iso)}${evs.length ? ` — ${tx.dayEvents(evs.length)}` : ""}`}
                onClick={(e) => { e.stopPropagation(); setDay(day === iso ? null : iso); }}>
                {splitDay(iso).d}
              </button>
              {evs.length > 0 && <span className="newscal-count">{evs.length}</span>}
              <span className="newscal-dots" aria-hidden="true">
                {types.map((t) => <TypeDot key={t} type={t} />)}
              </span>
              {evs.slice(0, 3).map((ev) => (
                <button key={ev.id} type="button" className={`newscal-pill ev-${ev.type}`}
                  title={`${tx.typeOne[ev.type]} · ${ev.organization || ""}`}
                  onClick={(e) => { e.stopPropagation(); open(ev); }}>
                  {ev.ticker || shortName(ev.organization)}
                </button>
              ))}
              {evs.length > 3 && (
                <button type="button" className="newscal-more"
                  onClick={(e) => { e.stopPropagation(); setDay(iso); }}>+{evs.length - 3}</button>
              )}
            </div>
          );
        })}
      </div>
      <div className="newscal-listhead">
        <h3>{day ? ctx.fmtLong(day) : ctx.monthLabel}</h3>
        <span className="muted">{tx.dayEvents(listItems.length)}</span>
        {day && <button type="button" className="ghost-btn" onClick={() => setDay(null)}>{tx.wholePeriod}</button>}
      </div>
      {listItems.length
        ? <EventList items={listItems} today={today} ctx={ctx} grouped={!day} />
        : <div className="led-empty">{cal.filtered ? tx.emptyFiltered : tx.empty}</div>}
    </>
  );
}

function WeekView({ cal, ctx }) {
  const { anchor, byDay, today } = cal;
  const { tx, locale, lang, forms, open } = ctx;
  const week = weekRange(anchor);
  const [open_, setOpen] = React.useState({});
  return (
    <div className="newscal-week">
      {week.days.map((iso, i) => {
        const evs = byDay.get(iso) || [];
        return (
          <section key={iso} className={`newscal-wday${iso === today ? " today" : ""}${iso < today ? " past" : ""}`}>
            <header>
              <span className="newscal-wday-name">{tx.weekdays[i]}</span>
              <span className="newscal-wday-date">{formatDay(iso, locale, { day: "numeric", month: "short" })}</span>
            </header>
            {evs.length === 0 && <span className="newscal-wday-empty">—</span>}
            {(open_[iso] ? evs : evs.slice(0, WEEK_DAY_CAP)).map((ev) => (
              <button key={ev.id} type="button" className={`newscal-wev ev-${ev.type}`} onClick={() => open(ev)}>
                <span className="newscal-wev-type"><TypeDot type={ev.type} />{tx.typeOne[ev.type]}{ev.time ? ` · ${ev.time}` : ""}</span>
                <span className="newscal-wev-org">{ev.organization || ev.ticker}</span>
                <span className="newscal-wev-title">{eventTitle(ev, lang, tx, locale, forms)}</span>
              </button>
            ))}
            {!open_[iso] && evs.length > WEEK_DAY_CAP && (
              <button type="button" className="newscal-wday-more" onClick={() => setOpen((o) => ({ ...o, [iso]: true }))}>
                {tx.more(evs.length - WEEK_DAY_CAP)}
              </button>
            )}
          </section>
        );
      })}
    </div>
  );
}

function Upcoming({ cal, ctx }) {
  const { tx, locale, lang, forms, open } = ctx;
  const items = upcomingEvents(cal.upcoming, cal.today, 8);
  if (cal.upcomingLoading && !items.length) return null;
  return (
    <section className="newscal-upcoming" aria-label={tx.upcoming}>
      <h3>{tx.upcoming}</h3>
      {items.length === 0
        ? <p className="muted newscal-upcoming-empty">{tx.upcomingEmpty}</p>
        : (
          <div className="newscal-up-track">
            {items.map((ev) => (
              <button key={ev.id} type="button" className={`newscal-up-card ev-${ev.type}`} onClick={() => open(ev)}>
                <span className="newscal-up-when">
                  <strong>{formatDay(ev.date, locale, { day: "numeric", month: "short" })}</strong>
                  <span>{relDay(ev.date, cal.today, tx)}</span>
                </span>
                <span className="newscal-up-type"><TypeDot type={ev.type} />{tx.typeOne[ev.type]}</span>
                <span className="newscal-up-org">{ev.organization || ev.ticker}</span>
                <span className="newscal-up-title">{eventTitle(ev, lang, tx, locale, forms)}</span>
              </button>
            ))}
          </div>
        )}
    </section>
  );
}

function Detail({ ev, cal, ctx, onOpenCompany, onOpenAnnouncement, onOpenNews }) {
  const { tx, locale, lang, forms } = ctx;
  const closeRef = React.useRef(null);
  const { setSelected } = cal;
  const close = () => setSelected(null);
  React.useEffect(() => {
    const before = document.activeElement;
    closeRef.current?.focus();
    const onKey = (e) => { if (e.key === "Escape") setSelected(null); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      // Back to the event the reader opened, not the top of the page.
      if (before && typeof before.focus === "function") before.focus();
    };
  }, [setSelected]);
  const d = ev.details || {};
  const n = daysBetween(cal.today, ev.date);
  const status = n > 0 ? tx.upcomingTag : n === 0 ? tx.todayTag : tx.pastTag;
  const fmt = (iso) => (iso ? formatDay(iso, locale) : "—");
  const rows = [];
  const add = (label, value) => { if (value != null && value !== "") rows.push([label, value]); };
  add(tx.d.date, `${ctx.fmtLong(ev.date)}${ev.time ? `, ${ev.time}` : ""}`);
  if (ev.type === "notice") add(tx.d.meeting, d.meeting_date ? `${fmt(d.meeting_date)}${d.meeting_time ? `, ${d.meeting_time}` : ""}` : null);
  if (ev.type === "meeting") add(tx.d.published, d.pub_date ? fmt(d.pub_date.slice(0, 10)) : null);
  if (ev.type === "dividend") {
    add(tx.d.decision, d.decision_date ? fmt(d.decision_date) : null);
    add(tx.d.published, d.pub_date ? fmt(d.pub_date) : null);
  }
  if (ev.type === "report") {
    add(tx.d.form, forms[d.report_form] || d.report_form);
    add(tx.d.period, eventTitle(ev, lang, tx, locale, forms));
  }
  if (ev.type === "listing") {
    add(tx.d.cls, tx.shareTypes[d.share_type] || d.share_type);
    add(tx.d.isin, d.isin);
    add(tx.d.nominal, d.nominal ? `${formatAmount(d.nominal, locale)} ${tx.d.sum}` : null);
  }
  const about = ev.type === "dividend" ? (isBondIncome(ev) ? tx.about.bond : tx.about.dividend)[ev.kind] : tx.about[ev.type];
  const announcement = (ev.type === "meeting" || ev.type === "notice") ? calendarAnnouncementPath(ev) : "";
  const newsPath = ev.type === "fact" && ev.news_id ? newsArticlePath({ id: ev.news_id }) : "";
  const external = d.link || null;
  return createPortal(
    <div className="newscal-modal" role="presentation" onClick={close}>
      <div className={`newscal-detail ev-${ev.type}`} role="dialog" aria-modal="true" aria-labelledby="newscal-detail-title"
        onClick={(e) => e.stopPropagation()}>
        <div className="newscal-detail-top">
          <span className="newscal-badge"><TypeDot type={ev.type} />{ev.type === "dividend" ? dividendKind(ev, tx) : tx.typeOne[ev.type]}</span>
          <span className={`newscal-status is-${n > 0 ? "future" : n === 0 ? "today" : "past"}`}>{status} · {relDay(ev.date, cal.today, tx)}</span>
          <button ref={closeRef} type="button" className="newscal-close" aria-label={tx.close} onClick={close}>×</button>
        </div>
        <h2 id="newscal-detail-title">{eventTitle(ev, lang, tx, locale, forms)}</h2>
        <div className="newscal-detail-co">
          <span className="newscal-detail-org">{ev.organization || ev.ticker}</span>
          {[...new Set([ev.ticker, ...(ev.tickers || [])].filter(Boolean))].map((t) => (
            <button key={t} type="button" className="newscal-tk-btn" onClick={() => { close(); onOpenCompany && onOpenCompany(t); }}>{t}</button>
          ))}
        </div>
        {about && <p className="newscal-detail-about">{about}</p>}
        {ev.type === "fact" && ev.title && <p className="newscal-detail-fact">{ev.title}</p>}
        <dl className="newscal-detail-facts">
          {rows.map(([k, v]) => <React.Fragment key={k}><dt>{k}</dt><dd>{v}</dd></React.Fragment>)}
        </dl>
        {ev.type === "dividend" && (d.classes || []).length > 0 && (
          <div className="dividend-table-wrap panel newscal-detail-table">
            <table className="dividend-table">
              <thead>
                <tr><th>{tx.d.cls}</th><th className="dividend-num">{tx.d.amount}</th><th className="dividend-num">{tx.d.percent}</th><th>{tx.d.window}</th></tr>
              </thead>
              <tbody>
                {d.classes.map((c) => (
                  <tr key={c.class} className={(ev.classes || []).includes(c.class) ? "is-hit" : ""}>
                    <td>{tx.divClasses[c.class] || c.class}</td>
                    <td className="dividend-num">{formatAmount(c.amount, locale)} {tx.d.sum}</td>
                    <td className="dividend-num muted">{c.percent ? `${formatAmount(c.percent, locale)}%` : "—"}</td>
                    <td className="muted">{c.start || c.end ? `${fmt(c.start)} – ${fmt(c.end)}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="newscal-detail-actions">
          {ev.ticker && onOpenCompany && (
            <button type="button" className="newscal-act primary" onClick={() => { close(); onOpenCompany(ev.ticker); }}>{tx.d.openCompany}</button>
          )}
          {announcement && (
            <a className="newscal-act" href={announcement}
              {...(onOpenAnnouncement ? { onClick: interceptNav(() => { close(); onOpenAnnouncement(ev); }) } : {})}>
              {tx.d.openAnnouncement}
            </a>
          )}
          {newsPath && (
            <a className="newscal-act" href={newsPath}
              {...(onOpenNews ? { onClick: interceptNav(() => { close(); onOpenNews({ id: ev.news_id }); }) } : {})}>
              {tx.d.openNews}
            </a>
          )}
          {d.pdf_url && <a className="newscal-act" href={d.pdf_url} target="_blank" rel="noreferrer">{tx.d.pdf}</a>}
          {d.excel_url && <a className="newscal-act" href={d.excel_url} target="_blank" rel="noreferrer">{tx.d.excel}</a>}
          {external && <a className="newscal-act" href={external} target="_blank" rel="noreferrer">{tx.d.openSource} ↗</a>}
        </div>
      </div>
    </div>,
    document.body,
  );
}

export function NewsCalendarView({ language, onOpenCompany, onOpenAnnouncement, onOpenNews }) {
  const cal = useNewsCalendar({ language });
  const { lang, tx, locale, view, setView, range, setRange, move, goToday, types, toggleType, setTypes,
    company, setCompany, resetFilters, filtered, events, visible, selected, setSelected, anchor, today } = cal;
  const forms = (NEWS_TX[lang] || NEWS_TX.ru).forms || {};
  const monthLabel = formatDay(anchor, locale, { month: "long", year: "numeric" });
  const fmtLong = (iso) => formatDay(iso, locale, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const ctx = { tx, locale, lang, forms, open: setSelected, fmtLong, monthLabel };
  const counts = countByType(events.items);
  const options = React.useMemo(() => companyOptions(events.items), [events.items]);

  let title = monthLabel;
  if (view === "week") {
    const w = weekRange(anchor);
    title = `${formatDay(w.start, locale, { day: "numeric", month: "short" })} – ${formatDay(w.end, locale)}`;
  } else if (view === "list") {
    title = `${formatDay(range.from, locale)} – ${formatDay(range.to, locale)}`;
  }

  const downloadCsv = () => {
    const blob = new Blob([eventsToCsv(visible, lang, tx, locale, forms)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `calendar_${range.from}_${range.to}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="newscal">
      <Upcoming cal={cal} ctx={ctx} />

      <div className="newscal-bar">
        <div className="newscal-nav">
          <button type="button" className="newscal-arrow" aria-label={tx.prev} onClick={() => move(-1)}>‹</button>
          <button type="button" className="newscal-today" onClick={goToday}>{tx.today}</button>
          <button type="button" className="newscal-arrow" aria-label={tx.next} onClick={() => move(1)}>›</button>
          <h3 className="newscal-month">{title}</h3>
        </div>
        <div className="newscal-toggle" role="group" aria-label={tx.views.month}>
          {["month", "week", "list"].map((k) => (
            <button key={k} type="button" className={`newscal-toggle-btn ${view === k ? "active" : ""}`}
              aria-pressed={view === k} onClick={() => setView(k)}>{tx.views[k]}</button>
          ))}
        </div>
      </div>

      <div className="newscal-filters">
        <div className="newscal-types" role="group" aria-label={tx.d.type}>
          <button type="button" className={`newscal-type all${types.size === EVENT_TYPES.length ? " on" : ""}`}
            aria-pressed={types.size === EVENT_TYPES.length} onClick={() => setTypes(new Set(EVENT_TYPES))}>
            {tx.allTypes}
          </button>
          {EVENT_TYPES.map((t) => (
            <button key={t} type="button" className={`newscal-type ev-${t}${types.has(t) ? " on" : ""}`}
              aria-pressed={types.has(t)} onClick={() => toggleType(t)}>
              <TypeDot type={t} />{tx.types[t]}
              <span className="newscal-type-n">{counts[t] || 0}</span>
            </button>
          ))}
        </div>
        <div className="newscal-filter-row">
          <input className="newscal-search" type="search" value={company} list="newscal-companies"
            placeholder={tx.companyPh} aria-label={tx.d.company} onChange={(e) => setCompany(e.target.value)} />
          <datalist id="newscal-companies">
            {options.map((o) => <option key={o.ticker || o.name} value={o.ticker || o.name}>{o.name}</option>)}
          </datalist>
          <label className="newscal-range">
            <span>{tx.from}</span>
            <input type="date" value={range.from} aria-label={tx.from}
              onChange={(e) => e.target.value && setRange({ from: e.target.value })} />
          </label>
          <label className="newscal-range">
            <span>{tx.to}</span>
            <input type="date" value={range.to} aria-label={tx.to}
              onChange={(e) => e.target.value && setRange({ to: e.target.value })} />
          </label>
          {filtered && <button type="button" className="ghost-btn" onClick={resetFilters}>{tx.resetFilters}</button>}
          {view === "list" && visible.length > 0 && (
            <button type="button" className="ghost-btn" onClick={downloadCsv}>{tx.download}</button>
          )}
        </div>
      </div>

      {events.partial && !events.error && <p className="newscal-warn">{tx.partial}</p>}

      {events.loading && !events.items.length ? <div className="led-empty">{tx.loading}</div>
        : events.error ? <div className="led-empty">{tx.error}</div>
          : view === "week" ? <WeekView cal={cal} ctx={ctx} />
            : view === "list" ? (visible.length
              ? <EventList items={visible} today={today} ctx={ctx} grouped />
              : <div className="led-empty">{filtered ? tx.emptyFiltered : tx.empty}</div>)
              : <MonthView cal={cal} ctx={ctx} />}

      <p className="muted newscal-note">{tx.note}</p>
      <p className="muted newscal-note">{tx.source}</p>

      {selected && (
        <Detail ev={selected} cal={cal} ctx={ctx} onOpenCompany={onOpenCompany}
          onOpenAnnouncement={onOpenAnnouncement} onOpenNews={onOpenNews} />
      )}
    </div>
  );
}
