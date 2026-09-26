import React from "react";
import { useTranslationTick } from "./newsTranslation.js";
export function useNewsIssuerContext({
  currentId,
  securitiesMap,
  tickers
}) {
  const [byTicker, setByTicker] = React.useState({});
  useTranslationTick();
  const keys = React.useMemo(() => {
    const known = t => securitiesMap && securitiesMap[t] ? 0 : 1;
    return [...tickers].sort((a, b) => known(a) - known(b)).slice(0, 3);
  }, [tickers, securitiesMap]);
  const keyList = keys.join(",");
  React.useEffect(() => {
    let alive = true;
    setByTicker({});
    if (!keys.length) return undefined;
    Promise.all(keys.map(t => fetch(`/api/news/ticker/${encodeURIComponent(t)}?limit=6&days=90&exclude_news_id=${encodeURIComponent(currentId)}`).then(r => r.json()).then(d => [t, d && d.ok ? d : null]).catch(() => [t, null]))).then(pairs => {
      if (alive) setByTicker(Object.fromEntries(pairs));
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyList, currentId]);
  return {
    byTicker,
    keys
  };
}
