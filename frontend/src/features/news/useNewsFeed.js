import React from "react";
import { NEWS_TABS, newsInstrumentFromLocation, newsTabFromLocation } from "./newsRouting.js";
export function useNewsFeed({}) {
  const [state, setState] = React.useState({
    loading: true,
    error: false,
    items: []
  });
  const [reloadKey, setReloadKey] = React.useState(0);
  const [tab, setTab] = React.useState(newsTabFromLocation);
  const [instrument, setInstrument] = React.useState(newsInstrumentFromLocation);
  React.useEffect(() => {
    const onPop = () => {
      setTab(newsTabFromLocation());
      setInstrument(newsInstrumentFromLocation());
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const pushQuery = React.useCallback((nextTab, nextInstrument) => {
    const p = new URLSearchParams();
    if (nextTab !== "all") p.set("tab", nextTab);
    if (nextTab === "corporate" && nextInstrument !== "all") p.set("instrument", nextInstrument);
    const q = p.toString();
    try {
      window.history.replaceState({}, "", q ? `/news?${q}` : "/news");
    } catch {/* history is unavailable in some embedded views */}
  }, []);
  const selectTab = React.useCallback(key => {
    setTab(key);
    // Leaving Корпоративные drops the instrument: it is a filter on issuer
    // filings, and carrying it onto Экономика would ask macro copy which bonds
    // it names.
    const nextInstrument = key === "corporate" ? instrument : "all";
    setInstrument(nextInstrument);
    pushQuery(key, nextInstrument);
  }, [instrument, pushQuery]);
  const selectInstrument = React.useCallback(key => {
    setInstrument(key);
    pushQuery("corporate", key);
  }, [pushQuery]);
  React.useEffect(() => {
    let alive = true;
    // «Календарь» is not a reading mode over the feed — it renders its own
    // component below and fetches its own endpoints; asking the feed for it
    // would flash a skeleton over a page that never uses the answer.
    if (tab === "calendar") {
      setState({
        loading: false,
        error: false,
        items: []
      });
      return undefined;
    }
    setState({
      loading: true,
      error: false,
      items: []
    });
    const group = (NEWS_TABS.find(t => t.key === tab) || {}).type;
    const inst = tab === "corporate" && instrument !== "all" ? `&instrument=${instrument}` : "";
    fetch(`/api/news/feed?limit=60&days=30${group ? `&type=${group}` : ""}${inst}`).then(r => r.json()).then(d => {
      if (alive) setState({
        loading: false,
        error: !d || !d.ok,
        items: d && d.items || []
      });
    }).catch(() => {
      if (alive) setState({
        loading: false,
        error: true,
        items: []
      });
    });
    return () => {
      alive = false;
    };
  }, [reloadKey, tab, instrument]);
  return {
    state,
    tab,
    instrument,
    selectTab,
    selectInstrument,
    setReloadKey
  };
}
