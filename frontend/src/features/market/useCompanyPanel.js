import { useState } from "react";
export function useCompanyPanel({
  lang
}) {
  const [panelTicker, setPanelTicker] = useState(null);
  const [panelWiki, setPanelWiki] = useState(null);
  const [panelWikiLoading, setPanelWikiLoading] = useState(false);
  const openPanel = ticker => {
    setPanelTicker(ticker);
    setPanelWiki(null);
    setPanelWikiLoading(true);
    fetch(`/api/securities/${encodeURIComponent(ticker)}/info?language=${lang}`).then(r => r.json()).then(d => {
      if (d.ok) setPanelWiki(d.wiki);
    }).catch(() => {}).finally(() => setPanelWikiLoading(false));
  };
  return {
    panelTicker,
    setPanelTicker,
    panelWiki,
    setPanelWiki,
    panelWikiLoading,
    openPanel
  };
}
