import React from "react";
import { normalizeLanguage } from "../../shared/i18n.jsx";
import { EVENT_TYPES, NEWSCAL_TX, NEWS_CALENDAR_POLL_MS } from "./calendarCopy.js";
import { addDays, addMonths, daysBetween, filterEvents, groupByDay, tashkentToday, viewWindow } from "./calendarEvents.js";

const UPCOMING_DAYS = 60;
const VIEW_KEY = "uzstock:newscal:view";

function readView() {
  try {
    const v = window.localStorage.getItem(VIEW_KEY);
    return v === "week" || v === "list" ? v : "month";
  } catch {
    return "month";
  }
}

/** One fetch of /api/news/calendar/events, refetched whenever `tick` moves. */
function useEvents(start, end, tick) {
  const [state, setState] = React.useState({ loading: true, error: false, partial: false, items: [] });
  React.useEffect(() => {
    if (!start || !end) return undefined;
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    fetch(`/api/news/calendar/events?start=${start}&end=${end}`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return;
        const sources = Object.values((d && d.sources) || {});
        setState({
          loading: false,
          error: !d || !d.ok,
          partial: sources.some((s) => s && s.ok === false),
          items: (d && d.items) || [],
        });
      })
      .catch(() => {
        if (alive) setState({ loading: false, error: true, partial: false, items: [] });
      });
    return () => {
      alive = false;
    };
  }, [start, end, tick]);
  return state;
}

export function useNewsCalendar({ language }) {
  const lang = normalizeLanguage(language);
  const tx = NEWSCAL_TX[lang] || NEWSCAL_TX.ru;
  const locale = lang === "en" ? "en-US" : lang === "uz" ? "uz" : "ru-RU";
  const today = tashkentToday();

  const [view, setViewState] = React.useState(readView);
  const [anchor, setAnchor] = React.useState(today);
  const [range, setRangeState] = React.useState({ from: addDays(today, -7), to: addDays(today, 60) });
  const [types, setTypes] = React.useState(() => new Set(EVENT_TYPES));
  const [company, setCompany] = React.useState("");
  const [day, setDay] = React.useState(null);
  const [selected, setSelected] = React.useState(null);
  const [tick, setTick] = React.useState(0);

  const setView = React.useCallback((v) => {
    setViewState(v);
    setDay(null);
    try {
      window.localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* a private window keeps the default */
    }
  }, []);

  // Editing the range is asking for a list of that range.
  const setRange = React.useCallback((next) => {
    setRangeState((r) => {
      const merged = { ...r, ...next };
      if (merged.from && merged.to && merged.to < merged.from) {
        return next.from ? { from: merged.from, to: merged.from } : { from: merged.to, to: merged.to };
      }
      return merged;
    });
    setViewState("list");
  }, []);

  React.useEffect(() => {
    const refresh = () => {
      if (!document.hidden) setTick((n) => n + 1);
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

  const win = viewWindow(view, anchor, range);
  const events = useEvents(win.start, win.end, tick);
  const ahead = useEvents(today, addDays(today, UPCOMING_DAYS), tick);

  const move = React.useCallback((dir) => {
    setDay(null);
    if (view === "week") setAnchor((a) => addDays(a, 7 * dir));
    else if (view === "list") {
      setRangeState((r) => {
        const span = Math.max(1, daysBetween(r.from, r.to) + 1);
        return { from: addDays(r.from, span * dir), to: addDays(r.to, span * dir) };
      });
    } else setAnchor((a) => addMonths(a, dir));
  }, [view]);

  const goToday = React.useCallback(() => {
    setDay(null);
    setAnchor(today);
    if (view === "list") setRangeState({ from: addDays(today, -7), to: addDays(today, 60) });
  }, [today, view]);

  const toggleType = React.useCallback((t) => {
    setTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  }, []);

  const resetFilters = React.useCallback(() => {
    setTypes(new Set(EVENT_TYPES));
    setCompany("");
  }, []);

  const filters = { types, company };
  const visible = React.useMemo(() => filterEvents(events.items, filters), [events.items, types, company]); // eslint-disable-line react-hooks/exhaustive-deps
  const upcoming = React.useMemo(() => filterEvents(ahead.items, filters), [ahead.items, types, company]); // eslint-disable-line react-hooks/exhaustive-deps
  const byDay = React.useMemo(() => groupByDay(visible), [visible]);
  const filtered = types.size !== EVENT_TYPES.length || company.trim() !== "";

  return {
    lang, tx, locale, today,
    view, setView, anchor, setAnchor, range, setRange, move, goToday,
    types, toggleType, setTypes, company, setCompany, resetFilters, filtered,
    day, setDay, selected, setSelected,
    events, visible, byDay, upcoming, upcomingLoading: ahead.loading,
  };
}
