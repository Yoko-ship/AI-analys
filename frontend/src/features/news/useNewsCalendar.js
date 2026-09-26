import React from "react";
import { normalizeLanguage } from "../../shared/i18n.jsx";
import { NEWSCAL_TX, NEWS_CALENDAR_POLL_MS } from "./calendarCopy.js";
export function useNewsCalendar({
  language
}) {
  const lang = normalizeLanguage(language);
  const tx = NEWSCAL_TX[lang] || NEWSCAL_TX.ru;
  const locale = lang === "en" ? "en-US" : lang === "uz" ? "uz" : "ru-RU";
  const today = new Date();
  const [view, setView] = React.useState("events");
  const [mode, setMode] = React.useState("month");
  const [cursor, setCursor] = React.useState({
    y: today.getFullYear(),
    m: today.getMonth() + 1
  });
  const [day, setDay] = React.useState(null);
  const [search, setSearch] = React.useState("");
  const [events, setEvents] = React.useState({
    loading: true,
    error: false,
    items: []
  });
  const [anns, setAnns] = React.useState(null);
  const [divs, setDivs] = React.useState(null);
  const [divType, setDivType] = React.useState("common");
  const [divSort, setDivSort] = React.useState({
    key: "pub",
    dir: -1
  });
  const [pageSize, setPageSize] = React.useState(10);
  const [page, setPage] = React.useState(1);
  const [refreshTick, setRefreshTick] = React.useState(0);
  React.useEffect(() => {
    setPage(1);
  }, [view, divType, search, pageSize, divSort]);
  React.useEffect(() => {
    const refresh = () => {
      if (!document.hidden) setRefreshTick(n => n + 1);
    };
    const timer = window.setInterval(refresh, NEWS_CALENDAR_POLL_MS);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);
  React.useEffect(() => {
    let alive = true;
    setEvents({
      loading: true,
      error: false,
      items: []
    });
    setDay(null);
    fetch(mode === "year" ? `/api/news/calendar/meetings?year=${cursor.y}` : `/api/news/calendar/meetings?year=${cursor.y}&month=${cursor.m}`).then(r => r.json()).then(d => {
      if (alive) setEvents({
        loading: false,
        error: !d || !d.ok,
        items: d && d.items || []
      });
    }).catch(() => {
      if (alive) setEvents({
        loading: false,
        error: true,
        items: []
      });
    });
    return () => {
      alive = false;
    };
  }, [cursor.y, cursor.m, mode, refreshTick]);
  React.useEffect(() => {
    if (view !== "dividends") return undefined;
    let alive = true;
    fetch("/api/news/calendar/dividends?limit=1000").then(r => r.json()).then(d => {
      if (alive) setDivs({
        error: !d || !d.ok,
        items: d && d.items || []
      });
    }).catch(() => {
      if (alive) setDivs({
        error: true,
        items: []
      });
    });
    return () => {
      alive = false;
    };
  }, [view, refreshTick]);
  React.useEffect(() => {
    if (view !== "announcements") return undefined;
    let alive = true;
    fetch("/api/news/calendar/announcements?limit=2000").then(r => r.json()).then(d => {
      if (alive) setAnns({
        error: !d || !d.ok,
        items: d && d.items || []
      });
    }).catch(() => {
      if (alive) setAnns({
        error: true,
        items: []
      });
    });
    return () => {
      alive = false;
    };
  }, [view, refreshTick]);
  const q = search.trim().toLowerCase();
  const filteredEvents = React.useMemo(() => q ? events.items.filter(it => String(it.organization || "").toLowerCase().includes(q) || String(it.ticker || "").toLowerCase().includes(q)) : events.items, [events.items, q]);
  const byDay = React.useMemo(() => {
    const map = new Map();
    for (const it of filteredEvents) {
      const n = parseInt(String(it.meeting_date || "").slice(8, 10), 10);
      if (!n) continue;
      if (!map.has(n)) map.set(n, []);
      map.get(n).push(it);
    }
    return map;
  }, [filteredEvents]);
  const byMonth = React.useMemo(() => {
    const map = new Map();
    for (const it of filteredEvents) {
      const key = String(it.meeting_date || "").slice(0, 7);
      if (!key) continue;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(it);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [filteredEvents]);
  return {
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
  };
}
