import React from "react";
import { NEWS_TABS, newsInstrumentFromLocation, newsTabFromLocation } from "./newsRouting.js";
import { localizedPath, locationLanguage } from "../../lib/languagePath.js";
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
    if (nextTab !== "general") p.set("tab", nextTab);
    if (nextTab === "corporate" && nextInstrument !== "all") p.set("instrument", nextInstrument);
    const q = p.toString();
    try {
      window.history.replaceState({}, "", localizedPath(q ? `/news?${q}` : "/news", locationLanguage()));
    } catch {/* history is unavailable in some embedded views */}
  }, []);
  const selectTab = React.useCallback(key => {
    setTab(key);
    // The instrument filter applies only to issuer disclosures.
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
    // Corporate news and the calendar fetch their own endpoints.
    if (tab !== "general") {
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
    const section = NEWS_TABS.find(t => t.key === tab).section;
    fetch(`/api/news/feed?limit=60&days=30&section=${section}`).then(r => r.json()).then(d => {
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
