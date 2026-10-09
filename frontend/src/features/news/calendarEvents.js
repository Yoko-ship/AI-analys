// Pure helpers of the news «Календарь»: day arithmetic on ISO dates, the
// windows each view reads, filtering, and the text an event is shown with.
//
// Days are "YYYY-MM-DD" strings throughout. Comparing them as strings is
// comparing them as dates, and no Date ever crosses a time zone: an event filed
// for 1 October is on 1 October for a reader in New York too.
import { localizedCalendarTitle } from "../../lib/calendarTitle.js";

const pad = (n) => String(n).padStart(2, "0");

// The same wording newsText.jsx gives a report's period, kept here so this
// module stays plain JavaScript the unit tests can import.
function reportPeriod(r, lang) {
  if (r.year == null) return "";
  if (r.quarter && r.quarter > 0) {
    return lang === "en" ? `Q${r.quarter} ${r.year}` : lang === "uz" ? `${r.year} ${r.quarter}-chorak` : `${r.quarter} кв. ${r.year}`;
  }
  return lang === "en" ? `FY ${r.year}` : lang === "uz" ? `${r.year}-yil` : `${r.year} год`;
}

export function isoDay(y, m, d) {
  const t = new Date(Date.UTC(y, m - 1, d));
  return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}`;
}

export function splitDay(iso) {
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return { y, m, d };
}

export function addDays(iso, n) {
  const { y, m, d } = splitDay(iso);
  return isoDay(y, m, d + n);
}

export function addMonths(iso, n) {
  const { y, m } = splitDay(iso);
  return isoDay(y, m + n, 1);
}

/** 0 = Monday … 6 = Sunday. */
export function weekdayIndex(iso) {
  const { y, m, d } = splitDay(iso);
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

export function daysBetween(fromIso, toIso) {
  const a = splitDay(fromIso);
  const b = splitDay(toIso);
  // Exact: UTC has no daylight saving, so two midnights differ by whole days.
  return (Date.UTC(b.y, b.m - 1, b.d) - Date.UTC(a.y, a.m - 1, a.d)) / 864e5;
}

/** Today in Tashkent — the exchange's calendar, whatever the reader's clock. */
export function tashkentToday(now = new Date()) {
  return new Date(now.getTime() + 5 * 3600e3).toISOString().slice(0, 10);
}

/** The Monday-first weeks that cover a month: what the month grid draws. */
export function monthGrid(anchor) {
  const { y, m } = splitDay(anchor);
  const first = isoDay(y, m, 1);
  const last = isoDay(y, m + 1, 0);
  const start = addDays(first, -weekdayIndex(first));
  const end = addDays(last, 6 - weekdayIndex(last));
  const days = [];
  for (let d = start; d <= end; d = addDays(d, 1)) days.push(d);
  return { start, end, first, last, days };
}

export function weekRange(anchor) {
  const start = addDays(anchor, -weekdayIndex(anchor));
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  return { start, end: days[6], days };
}

/** The [start, end] a view has to fetch. */
export function viewWindow(view, anchor, range) {
  if (view === "week") {
    const w = weekRange(anchor);
    return { start: w.start, end: w.end };
  }
  if (view === "list") return { start: range.from, end: range.to };
  const g = monthGrid(anchor);
  return { start: g.start, end: g.end };
}

export function matchesCompany(ev, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return true;
  if (String(ev.organization || "").toLowerCase().includes(q)) return true;
  return [ev.ticker, ...(ev.tickers || [])].some((t) => t && String(t).toLowerCase().includes(q));
}

export function filterEvents(items, { types, company }) {
  return (items || []).filter((ev) => (!types || types.has(ev.type)) && matchesCompany(ev, company));
}

export function groupByDay(items) {
  const map = new Map();
  for (const ev of items || []) {
    if (!map.has(ev.date)) map.set(ev.date, []);
    map.get(ev.date).push(ev);
  }
  return map;
}

export function countByType(items) {
  const counts = {};
  for (const ev of items || []) counts[ev.type] = (counts[ev.type] || 0) + 1;
  return counts;
}

/** Events on or after today, soonest first — the «coming up» strip. */
export function upcomingEvents(items, today, limit = 8) {
  return (items || []).filter((ev) => ev.date >= today).slice(0, limit);
}

/** Every company that has an event in the loaded window, for the filter's suggestions. */
export function companyOptions(items) {
  const seen = new Map();
  for (const ev of items || []) {
    const name = String(ev.organization || "").trim();
    if (!name) continue;
    const key = ev.ticker || name;
    if (!seen.has(key)) seen.set(key, { name, ticker: ev.ticker || null });
  }
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name, "ru"));
}

export { reportPeriod };

export function formatDay(iso, locale, opts = { day: "numeric", month: "short", year: "numeric" }) {
  if (!iso) return "";
  const { y, m, d } = splitDay(iso);
  if (!y) return "";
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(locale, { timeZone: "UTC", ...opts });
}

export function formatAmount(v, locale) {
  if (v == null || v === "") return "—";
  return Number(v).toLocaleString(locale, { maximumFractionDigits: 2 });
}

/** A bond line in openinfo's dividend feed is interest on the bond, not a
 *  dividend — its steps are named as bond income. */
export function isBondIncome(ev) {
  const cls = ev.classes || [];
  return cls.length > 0 && cls.every((c) => c === "bond");
}

export function dividendKind(ev, tx) {
  const kinds = isBondIncome(ev) ? tx.bondKinds : tx.divKinds;
  return kinds[ev.kind] || tx.typeOne.dividend;
}

/** The headline an event is listed under, in the interface language. */
export function eventTitle(ev, lang, tx, locale, forms = {}) {
  switch (ev.type) {
    case "meeting":
      return localizedCalendarTitle(ev, lang) || tx.typeOne.meeting;
    case "notice":
      return ev.details?.meeting_date
        ? tx.noticeFor(formatDay(ev.details.meeting_date, locale, { day: "numeric", month: "long" }))
        : tx.typeOne.notice;
    case "dividend": {
      const kind = dividendKind(ev, tx);
      const classes = ev.details?.classes || [];
      const shown = classes.filter((c) => (ev.classes || []).includes(c.class));
      const lead = shown[0] || classes[0];
      return lead ? `${kind} · ${formatAmount(lead.amount, locale)} ${tx.d.sum}` : kind;
    }
    case "report": {
      const form = forms[ev.details?.report_form] || ev.details?.report_form || "";
      return tx.reportTitle(form, reportPeriod(ev.details || {}, lang));
    }
    case "listing":
      return tx.listingTitle(tx.shareTypes[ev.details?.share_type] || ev.details?.share_type || "");
    default:
      return ev.title || tx.typeOne[ev.type] || "";
  }
}

/** The filtered events as a spreadsheet: semicolons and a BOM, as Excel in RU reads it. */
export function eventsToCsv(items, lang, tx, locale, forms) {
  const esc = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
  const head = [tx.d.date, tx.d.type, tx.d.company, tx.d.ticker, "", tx.d.amount, tx.d.window, "Link"];
  const lines = [head.map(esc).join(";")];
  for (const ev of items) {
    const cls = (ev.details?.classes || []).filter((c) => (ev.classes || []).includes(c.class));
    lines.push([
      ev.date,
      tx.typeOne[ev.type],
      ev.organization,
      [ev.ticker, ...(ev.tickers || [])].filter((t, i, all) => t && all.indexOf(t) === i).join(", "),
      eventTitle(ev, lang, tx, locale, forms),
      cls.map((c) => c.amount).join(" / "),
      cls.map((c) => [c.start, c.end].filter(Boolean).join(" – ")).join(" / "),
      ev.details?.link || ev.details?.pdf_url || "",
    ].map(esc).join(";"));
  }
  return "﻿" + lines.join("\r\n");
}
