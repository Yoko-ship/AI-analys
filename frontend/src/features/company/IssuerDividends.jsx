import React from "react";
import { CompanyDividendsTab } from "./Financials.jsx";

// The Дивиденды tab with its own request, for hosts that do not already hold
// the issuer's dividends (the catalog terminal's DVD screen). The company page
// keeps its own copy because its key-stats rail needs the same list.
function IssuerDividends({ ticker, lang, lastPrice = null, isPreferred = false, onLoad }) {
  const [items, setItems] = React.useState(null);
  const onLoadRef = React.useRef(onLoad);
  onLoadRef.current = onLoad;

  React.useEffect(() => {
    if (!ticker) return undefined;
    let alive = true;
    const startedAt = performance.now();
    setItems(null);
    fetch(`/api/dividends/${encodeURIComponent(ticker)}`)
      .then(async (r) => {
        const d = await r.json().catch(() => null);
        if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status}`), { errorId: d?.error_id });
        return d;
      })
      .then((d) => {
        if (!alive) return;
        setItems(d?.ok ? (d.items || []) : []);
        onLoadRef.current?.({ startedAt });
      })
      .catch((error) => {
        if (!alive) return;
        setItems([]);
        onLoadRef.current?.({ startedAt, error: error.message, errorId: error.errorId });
      });
    return () => { alive = false; };
  }, [ticker]);

  return <CompanyDividendsTab items={items} loading={items === null} lang={lang}
    isPreferred={isPreferred} lastPrice={lastPrice} />;
}

export { IssuerDividends };
