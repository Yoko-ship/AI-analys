import React, { useEffect, useState } from "react";
import { HIDDEN_VIEWS, pathToView, viewToPath } from "./routing.jsx";
import { endPageview, trackPageview } from "../lib/track.js";
import { applyPageTitle } from "./pageTitle.js";

export function useNavigation() {

  const [activeView, setActiveViewState] = useState(() => pathToView(window.location.pathname).view);

  const setActiveView = React.useCallback((nextView) => {
    setActiveViewState(HIDDEN_VIEWS.has(nextView) ? "main" : nextView);
  }, []);

  const [companyTicker, setCompanyTicker] = useState(() => pathToView(window.location.pathname).ticker);

  const [newsId, setNewsId] = useState(() => pathToView(window.location.pathname).newsId);

  const [chartState, setChartState] = useState(() => {
    const q = new URLSearchParams(window.location.search);
    const list = (k) => (q.get(k) || "").split(",").map((s) => s.trim()).filter(Boolean);
    return {
      range: q.get("range") || "1y",
      from: q.get("from") || "",
      to: q.get("to") || "",
      type: q.get("type") || "line",
      interval: ["W", "M"].includes(q.get("iv")) ? q.get("iv") : "D",
      indicators: list("ind"),
      fin: list("fin"),
      compare: list("cmp").map((s) => s.toUpperCase()),
    };
  });

  const [adminSection, setAdminSection] = useState(
    () => pathToView(window.location.pathname).adminSection || "overview");

  const [prevView, setPrevView] = useState("market");

  useEffect(() => {
    const target = viewToPath(activeView, companyTicker, newsId, adminSection);
    if (window.location.pathname !== target) {
      window.history.pushState({ view: activeView }, "", target);
    }
    applyPageTitle();
    // Count the view once the URL settles. The admin's own walks through the
    // panel are not audience and would only pollute its numbers.
    if (activeView !== "admin") {
      trackPageview({
        path: target,
        view: activeView,
        ticker: ["company", "chart", "bond"].includes(activeView) ? companyTicker : "",
      });
    } else {
      endPageview();
    }
  }, [activeView, companyTicker, newsId, adminSection]);

  useEffect(() => {
    const onPop = () => {
      const { view, ticker, newsId: popNewsId, adminSection: popSection } = pathToView(window.location.pathname);
      if (ticker) setCompanyTicker(ticker);
      if (popNewsId) setNewsId(popNewsId);
      if (popSection) setAdminSection(popSection);
      setActiveView(view);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [setActiveView]);

  const openCompanyPage = (ticker) => {
    setPrevView(activeView);
    setCompanyTicker(ticker);
    setActiveView("company");
  };

  const openBondPage = (ticker) => {
    if (!ticker) return;
    setPrevView(activeView);
    setCompanyTicker(ticker);
    setActiveView("bond");
  };

  const openChartPage = (ticker, state) => {
    if (!ticker) return;
    setPrevView(activeView);
    setCompanyTicker(ticker);
    setChartState(state || null);
    setActiveView("chart");
  };

  const openNewsArticle = (item) => {
    const id = item && (item.id != null ? item.id : item);
    if (id == null || id === "") return;
    setNewsId(String(id));
    setActiveView("newsArticle");
  };

  const openAnnouncementArticle = (item) => {
    const id = item && (item.announcement_id != null ? item.announcement_id : item);
    if (id == null || id === "") return;
    setNewsId(String(id));
    setActiveView("announcementArticle");
  };

  const backToNewsCalendar = () => {
    // Replace the detail URL before mounting NewsView so its first render reads
    // the calendar tab from the query string instead of flashing the main feed.
    try { window.history.replaceState({}, "", "/news?tab=calendar"); } catch { /* noop */ }
    setActiveView("news");
  };
  // A section of /news, from the topbar's drop-down. The tab lives in the query
  // string, which the page reads on mount and on popstate — so when the page is
  // already open, the same event switches it.
  const openNewsTab = (tab) => {
    const target = tab === "all" ? "/news" : `/news?tab=${tab}`;
    try {
      if (window.location.pathname + window.location.search !== target) window.history.pushState({ view: "news" }, "", target);
    } catch { /* noop */ }
    if (activeView === "news") window.dispatchEvent(new PopStateEvent("popstate"));
    else setActiveView("news");
  };
  return { activeView, adminSection, backToNewsCalendar, openNewsTab, chartState, companyTicker, newsId, openAnnouncementArticle, openBondPage, openChartPage, openCompanyPage, openNewsArticle, prevView, setActiveView, setAdminSection };
}
