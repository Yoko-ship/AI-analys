import { interceptNav } from "./editorial.jsx";
import React from "react";
import { localizedCalendarTitle } from "../../lib/calendarTitle.js";
import { calendarAnnouncementPath } from "./calendarCopy.js";
import { useNewsCalendar } from "./useNewsCalendar.js";
export function NewsCalPager({
  p,
  pages,
  total,
  from,
  to,
  size,
  onPage,
  onSize,
  tx
}) {
  if (!total) return null;
  const nums = [];
  for (const n of [1, p - 1, p, p + 1, pages]) {
    if (n >= 1 && n <= pages && !nums.includes(n)) nums.push(n);
  }
  nums.sort((a, b) => a - b);
  return <div className="newscal-pager">
      <span className="muted">{tx.pager.shown} {from}–{to} {tx.pager.of} {total}</span>
      <label className="newscal-psize muted">
        {tx.pager.perPage}
        <select className="newscal-select" value={size} onChange={e => onSize(Number(e.target.value))}>
          {[10, 25, 50].map(n => <option key={n} value={n}>{n}</option>)}
        </select>
      </label>
      <div className="newscal-pnums">
        <button type="button" className="newscal-arrow" disabled={p <= 1} aria-label="prev" onClick={() => onPage(p - 1)}>‹</button>
        {nums.map((n, i) => <React.Fragment key={n}>
            {i > 0 && nums[i - 1] < n - 1 && <span className="muted">…</span>}
            <button type="button" className={`newscal-pnum ${n === p ? "active" : ""}`} onClick={() => onPage(n)}>{n}</button>
          </React.Fragment>)}
        <button type="button" className="newscal-arrow" disabled={p >= pages} aria-label="next" onClick={() => onPage(p + 1)}>›</button>
      </div>
    </div>;
}
export function NewsCalendarView({
  language,
  onOpenCompany,
  onOpenAnnouncement
}) {
  const {
    lang,
    tx,
    locale,
    today,
    view,
    setView,
    mode,
    setMode,
    cursor,
    setCursor,
    day,
    setDay,
    search,
    setSearch,
    events,
    anns,
    divs,
    divType,
    setDivType,
    divSort,
    setDivSort,
    pageSize,
    setPageSize,
    page,
    setPage,
    q,
    filteredEvents,
    byDay,
    byMonth
  } = useNewsCalendar({
    language
  });

  // «Месяц» | «Год» — the source's own toggle

  // null = not asked for yet
  // null = not asked for yet

  // Year view: the same rows grouped by month, because a 12-month grid answers
  // no question a dated list does not.

  const monthLabel = new Date(cursor.y, cursor.m - 1, 1).toLocaleDateString(locale, {
    month: "long",
    year: "numeric"
  });
  const daysInMonth = new Date(cursor.y, cursor.m, 0).getDate();
  const lead = (new Date(cursor.y, cursor.m - 1, 1).getDay() + 6) % 7; // Monday-first
  const isThisMonth = today.getFullYear() === cursor.y && today.getMonth() + 1 === cursor.m;
  const move = delta => setCursor(({
    y,
    m
  }) => {
    const next = m + delta;
    return next < 1 ? {
      y: y - 1,
      m: 12
    } : next > 12 ? {
      y: y + 1,
      m: 1
    } : {
      y,
      m: next
    };
  });
  const fmtDay = iso => iso ? new Date(iso).toLocaleDateString(locale, {
    day: "numeric",
    month: "short"
  }) : "";
  const fmtTime = iso => {
    // The meeting hour is only trustworthy when the issuer filed one: a real
    // agenda starts on a round minute, while a date copied from the filing
    // timestamp carries its seconds (16:21:48). Those render date-only.
    const m = /T(\d\d):(\d\d):(\d\d)/.exec(String(iso || ""));
    if (!m || m[3] !== "00" || m[1] === "00" && m[2] === "00") return "";
    return `${m[1]}:${m[2]}`;
  };
  const listItems = day == null ? filteredEvents : byDay.get(day) || [];
  const fmtNum = v => v == null ? "—" : Number(v).toLocaleString(locale, {
    maximumFractionDigits: 2
  });
  const fmtDate = d => d ? new Date(d).toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric"
  }) : "—";
  // The chip picks the share class, the columns follow it — the same three-way
  // split the source's table offers. Decisions that declared nothing for the
  // chosen class stay on the company pages, where they are the issuer's record.
  const amountOf = React.useCallback(r => divType === "preferred" ? r.preferred_amount : divType === "bond" ? r.bond_amount : r.ordinary_amount, [divType]);
  const pctOf = React.useCallback(r => divType === "preferred" ? r.preferred_percent : divType === "bond" ? r.bond_percent : r.ordinary_percent, [divType]);
  const startOf = r => divType === "preferred" ? r.preferred_start : divType === "bond" ? r.bond_start : r.ordinary_start;
  const endOf = r => divType === "preferred" ? r.preferred_end : divType === "bond" ? r.bond_end : r.ordinary_end;
  const divItems = React.useMemo(() => {
    const rows = (divs && divs.items || []).filter(r => (amountOf(r) || 0) > 0);
    if (!q) return rows;
    return rows.filter(r => String(r.organization || "").toLowerCase().includes(q) || (r.tickers || []).some(t => String(t).toLowerCase().includes(q)));
  }, [divs, amountOf, q]);
  const downloadCsv = () => {
    const esc = v => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
    const lines = [[tx.th.issuer, "Ticker", tx.th.decision, tx.th.amount, "%", tx.th.window, "Link"].map(esc).join(";")];
    for (const r of divItems) {
      lines.push([r.organization, (r.tickers || []).join(", "), r.decision_date, amountOf(r), pctOf(r), [startOf(r), endOf(r)].filter(Boolean).join(" – "), r.link].map(esc).join(";"));
    }
    // BOM so Excel reads the Cyrillic as UTF-8; semicolons for the RU locale.
    const blob = new Blob(["﻿" + lines.join("\r\n")], {
      type: "text/csv;charset=utf-8"
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `dividends_${divType}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const annItems = React.useMemo(() => {
    const rows = anns && anns.items || [];
    if (!q) return rows;
    return rows.filter(it => String(it.organization || "").toLowerCase().includes(q) || String(it.ticker || "").toLowerCase().includes(q) || String(it.title || "").toLowerCase().includes(q));
  }, [anns, q]);
  const sortedDivs = React.useMemo(() => {
    const val = r => divSort.key === "amount" ? amountOf(r) || 0 : divSort.key === "percent" ? pctOf(r) || 0 : divSort.key === "decision" ? String(r.decision_date || "") : String(r.pub_date || "");
    return [...divItems].sort((a, b) => {
      const x = val(a);
      const y = val(b);
      return (x < y ? -1 : x > y ? 1 : 0) * divSort.dir;
    });
  }, [divItems, divSort, amountOf, pctOf]);
  const paginate = rows => {
    const total = rows.length;
    const pages = Math.max(1, Math.ceil(total / pageSize));
    const p = Math.min(page, pages);
    const from = total === 0 ? 0 : (p - 1) * pageSize + 1;
    const slice = rows.slice((p - 1) * pageSize, (p - 1) * pageSize + pageSize);
    return {
      slice,
      total,
      pages,
      p,
      from,
      to: total === 0 ? 0 : from + slice.length - 1
    };
  };
  const annPage = paginate(annItems);
  const divPage = paginate(sortedDivs);
  const sortTh = (key, label, num) => <th className={`newscal-sortth${num ? " dividend-num" : ""}`} aria-sort={divSort.key === key ? divSort.dir < 0 ? "descending" : "ascending" : undefined} onClick={() => setDivSort(s => ({
    key,
    dir: s.key === key ? -s.dir : -1
  }))}>
      {label}{divSort.key === key ? divSort.dir < 0 ? " ↓" : " ↑" : ""}
    </th>;
  const orgCell = it => it.ticker && onOpenCompany ? <button type="button" className="newscal-org-btn" onClick={() => onOpenCompany(it.ticker)}>
        {it.organization} <span className="newscal-tk">{it.ticker}</span>
      </button> : <span className="newscal-row-org">{it.organization}</span>;
  const renderRow = (it, i) => {
    const href = calendarAnnouncementPath(it);
    const contents = <>
        <span className="newscal-row-date">
          {fmtDay(it.meeting_date)}{fmtTime(it.meeting_date) ? ` · ${fmtTime(it.meeting_date)}` : ""}
        </span>
        <div className="newscal-row-body">
          <span className="newscal-row-org">{it.organization}</span>
          {it.title && <span className="newscal-row-title" title={it.title}>
              {localizedCalendarTitle(it, lang)}
            </span>}
        </div>
      </>;
    return href ? <a key={it.announcement_id || i} className="newscal-row newscal-news-row" href={href} {...onOpenAnnouncement ? {
      onClick: interceptNav(() => onOpenAnnouncement(it))
    } : {}} aria-label={`${it.organization || ""}: ${localizedCalendarTitle(it, lang)}`}>
        {contents}
      </a> : <div key={it.announcement_id || i} className="newscal-row">{contents}</div>;
  };
  return <div className="newscal">
      <div className="news-subtabs" role="group" aria-label={tx.views.events}>
        {["events", "announcements", "dividends"].map(key => <button key={key} type="button" className={`news-subtab ${view === key ? "active" : ""}`} aria-pressed={view === key} onClick={() => setView(key)}>
            {tx.views[key]}
          </button>)}
      </div>
      <p className="muted newscal-hint">{tx.viewHint[view]}</p>

      {view === "events" ? <>
          <div className="newscal-bar">
            <div className="newscal-nav">
              <button type="button" className="newscal-arrow" aria-label="prev" onClick={() => mode === "year" ? setCursor(c => ({
            ...c,
            y: c.y - 1
          })) : move(-1)}>‹</button>
              <select className="newscal-select" value={cursor.y} aria-label="year" onChange={e => setCursor(c => ({
            ...c,
            y: Number(e.target.value)
          }))}>
                {[today.getFullYear() - 1, today.getFullYear(), today.getFullYear() + 1].map(y => <option key={y} value={y}>{y}</option>)}
              </select>
              {mode === "month" && <select className="newscal-select" value={cursor.m} aria-label="month" onChange={e => setCursor(c => ({
            ...c,
            m: Number(e.target.value)
          }))}>
                  {Array.from({
              length: 12
            }).map((_, i) => <option key={i + 1} value={i + 1}>
                      {new Date(2000, i, 1).toLocaleDateString(locale, {
                month: "long"
              })}
                    </option>)}
                </select>}
              <button type="button" className="newscal-arrow" aria-label="next" onClick={() => mode === "year" ? setCursor(c => ({
            ...c,
            y: c.y + 1
          })) : move(1)}>›</button>
            </div>
            <div className="newscal-toggle" role="group">
              {["month", "year"].map(k => <button key={k} type="button" className={`newscal-toggle-btn ${mode === k ? "active" : ""}`} aria-pressed={mode === k} onClick={() => {
            setMode(k);
            setDay(null);
          }}>
                  {tx.mode[k]}
                </button>)}
            </div>
            <input className="newscal-search" type="search" value={search} placeholder={tx.searchPh} onChange={e => setSearch(e.target.value)} />
            {day != null && <button type="button" className="ghost-btn" style={{
          fontSize: 12
        }} onClick={() => setDay(null)}>
                {tx.wholeMonth}
              </button>}
          </div>

          {events.loading ? <div className="led-empty">{tx.loading}</div> : events.error ? <div className="led-empty">{tx.error}</div> : <>
              {mode === "month" && <div className="newscal-grid">
                {tx.weekdays.map(w => <div key={w} className="newscal-dow">{w}</div>)}
                {Array.from({
            length: lead
          }).map((_, i) => <div key={`b${i}`} className="newscal-cell blank" />)}
                {Array.from({
            length: daysInMonth
          }).map((_, i) => {
            const n = i + 1;
            const evs = byDay.get(n) || [];
            const isToday = isThisMonth && today.getDate() === n;
            return <button
              key={n}
              type="button"
              className={`newscal-cell${evs.length ? " has-events" : ""}${day === n ? " selected" : ""}${isToday ? " today" : ""}`}
              disabled={!evs.length}
              onClick={() => setDay(day === n ? null : n)}
            >
                      <span className="newscal-daynum">{n}</span>
                      {evs.length > 0 && <span className="newscal-count">{evs.length}</span>}
                      {evs.slice(0, 2).map((e, j) => <span key={j} className="newscal-chip">{e.organization}</span>)}
                      {evs.length > 2 && <span className="newscal-more">+{evs.length - 2}</span>}
                    </button>;
          })}
                {/* Fill the last row: an unrendered remainder exposes the grid's
                    border-colored background as a grey slab in the light theme. */}
                {Array.from({
            length: (7 - (lead + daysInMonth) % 7) % 7
          }).map((_, i) => <div key={`t${i}`} className="newscal-cell blank" />)}
              </div>}

              {listItems.length === 0 ? <div className="led-empty">{tx.emptyMonth}</div> : mode === "year" ? <div className="newscal-list">
                  {byMonth.map(([key, items]) => <React.Fragment key={key}>
                      <div className="newscal-mh">
                        {new Date(`${key}-01T00:00:00`).toLocaleDateString(locale, {
                month: "long",
                year: "numeric"
              })}
                      </div>
                      {items.map(renderRow)}
                    </React.Fragment>)}
                </div> : <div className="newscal-list">{listItems.map(renderRow)}</div>}
            </>}
        </> : view === "announcements" ? <>
          <div className="newscal-bar">
            <input className="newscal-search" type="search" value={search} placeholder={tx.searchPh} onChange={e => setSearch(e.target.value)} />
          </div>
          {!anns ? <div className="led-empty">{tx.loading}</div> : anns.error ? <div className="led-empty">{tx.error}</div> : annPage.total === 0 ? <div className="led-empty">{tx.annEmpty}</div> : <>
              <div className="dividend-table-wrap panel">
                <table className="dividend-table">
                  <thead>
                    <tr>
                      <th>{tx.th.org}</th>
                      <th>{tx.th.title}</th>
                      <th>{tx.th.pub}</th>
                      <th>{tx.th.meeting}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {annPage.slice.map((it, i) => {
                const localizedTitle = localizedCalendarTitle(it, lang);
                return <tr key={it.announcement_id || i}>
                          <td>{orgCell(it)}</td>
                          <td className="newscal-anntitle" title={it.title || undefined}>
                            {calendarAnnouncementPath(it) ? <a className="newscal-news-link" href={calendarAnnouncementPath(it)} {...onOpenAnnouncement ? {
                      onClick: interceptNav(() => onOpenAnnouncement(it))
                    } : {}}>
                                {localizedTitle || "—"}
                              </a> : localizedTitle || "—"}
                          </td>
                          <td className="muted" style={{
                    whiteSpace: "nowrap"
                  }}>{fmtDate(it.pub_date)}</td>
                          <td style={{
                    whiteSpace: "nowrap"
                  }}>
                            {fmtDate(it.meeting_date)}{fmtTime(it.meeting_date) ? ` · ${fmtTime(it.meeting_date)}` : ""}
                          </td>
                        </tr>;
              })}
                  </tbody>
                </table>
              </div>
              <NewsCalPager {...annPage} size={pageSize} onPage={setPage} onSize={setPageSize} tx={tx} />
            </>}
        </> : <>
          <div className="newscal-bar">
            <div className="news-subtabs" role="group" aria-label={tx.views.dividends} style={{
          margin: 0
        }}>
              {["common", "preferred", "bond"].map(key => <button
                key={key}
                type="button"
                className={`news-subtab ${divType === key ? "active" : ""}`}
                aria-pressed={divType === key}
                onClick={() => setDivType(key)}
              >
                  {tx.divTypes[key]}
                </button>)}
            </div>
            <input className="newscal-search" type="search" value={search} placeholder={tx.searchPh} onChange={e => setSearch(e.target.value)} />
            {divItems.length > 0 && <button type="button" className="ghost-btn" style={{
          fontSize: 12
        }} onClick={downloadCsv}>
                {tx.download}
              </button>}
          </div>
          {!divs ? <div className="led-empty">{tx.loading}</div> : divs.error ? <div className="led-empty">{tx.error}</div> : divItems.length === 0 ? <div className="led-empty">{tx.divEmpty}</div> : <>
              <div className="dividend-table-wrap panel">
                <table className="dividend-table">
                  <thead>
                    <tr>
                      <th>{tx.th.issuer}</th>
                      {sortTh("decision", tx.th.decision, false)}
                      {sortTh("amount", tx.th.amount, true)}
                      {sortTh("percent", "%", true)}
                      <th>{tx.th.window}</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {divPage.slice.map((r, i) => {
                const start = startOf(r);
                const end = endOf(r);
                return <tr key={r.filing_id || i}>
                          <td>{orgCell(r)}</td>
                          <td style={{
                    whiteSpace: "nowrap"
                  }}>{fmtDate(r.decision_date)}</td>
                          <td className="dividend-num">{amountOf(r) ? fmtNum(amountOf(r)) : "—"}</td>
                          <td className="dividend-num muted">{pctOf(r) ? `${fmtNum(pctOf(r))}%` : "—"}</td>
                          <td className="muted" style={{
                    fontSize: 12,
                    whiteSpace: "nowrap"
                  }}>
                            {start || end ? `${fmtDate(start)} – ${fmtDate(end)}` : "—"}
                          </td>
                          <td>{r.link && <a href={r.link} target="_blank" rel="noreferrer" className="ghost-btn" style={{
                      fontSize: 12
                    }}>→</a>}</td>
                        </tr>;
              })}
                  </tbody>
                </table>
              </div>
              <NewsCalPager {...divPage} size={pageSize} onPage={setPage} onSize={setPageSize} tx={tx} />
              <p className="muted" style={{
          fontSize: 11,
          marginTop: 10
        }}>{tx.divNote}</p>
            </>}
        </>}
      <p className="muted" style={{
      fontSize: 11,
      marginTop: 14
    }}>{tx.source}</p>
    </div>;
}
