import React from "react";
export function useNewsAgent({
  apiFetch,
  tx,
  onStored
}) {
  const [q, setQ] = React.useState("");
  const [days, setDays] = React.useState(7);
  const [store, setStore] = React.useState(true);
  const [loading, setLoading] = React.useState(false);
  const [res, setRes] = React.useState(null);
  const [err, setErr] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const run = async () => {
    const query = q.trim();
    if (!query || loading) return;
    setLoading(true);
    setErr("");
    setRes(null);
    try {
      const params = new URLSearchParams({
        q: query,
        days: String(days || 7),
        store: String(!!store)
      });
      const r = await apiFetch(`/api/news/agent-search?${params.toString()}`);
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d || !d.ok) setErr(d && d.detail || tx.err);else {
        setRes(d);
        if (store && d.stored > 0 && onStored) onStored();
      }
    } catch (e) {
      setErr(tx.err);
    } finally {
      setLoading(false);
    }
  };
  return {
    q,
    setQ,
    days,
    setDays,
    store,
    setStore,
    loading,
    res,
    err,
    open,
    setOpen,
    run
  };
}
