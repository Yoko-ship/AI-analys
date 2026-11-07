import { useCallback, useEffect, useRef, useState } from "react";

export function useCollectionOperations(apiFetch) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const alive = useRef(false);
  const read = useCallback(async (path, options) => {
    const response = await apiFetch("/api/admin/collections" + path, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = body.detail;
      throw new Error(typeof detail === "string" ? detail : detail?.message || `HTTP ${response.status}`);
    }
    return body;
  }, [apiFetch]);
  const refresh = useCallback(async () => {
    try {
      const result = await read("");
      if (alive.current) { setData(result); setError(""); }
    } catch (failure) {
      if (alive.current) setError(failure.message);
    }
  }, [read]);
  useEffect(() => {
    alive.current = true;
    refresh();
    const timer = setInterval(refresh, 15000);
    return () => { alive.current = false; clearInterval(timer); };
  }, [refresh]);
  const act = async (job, release = false) => {
    if (busy) return;
    setBusy(job.id);
    try {
      await read(release ? `/requests/${job.request.id}/release` : `/${job.id}/run`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      await refresh();
    } catch (failure) {
      if (alive.current) setError(failure.message);
    } finally {
      if (alive.current) setBusy("");
    }
  };
  return { data, error, busy, refresh, act, read };
}
