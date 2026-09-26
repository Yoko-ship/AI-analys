import { useEffect, useState } from "react";

export function useMarketExport({ type, prepareExport, exportCsv }) {
  const [request, setRequest] = useState(null);
  useEffect(() => {
    if (!request) return;
    if (request.type !== type) {
      setRequest(null);
    } else if (request.status === "ready") {
      // Run after React has committed enrichment, so selectors use the loaded
      // financials instead of the snapshot captured when the button was clicked.
      setRequest(null);
      exportCsv();
    }
  }, [request, type, exportCsv]);
  const startExport = () => {
    if (request?.status === "loading" || request?.status === "ready") return;
    const next = { type, status: "loading" };
    setRequest(next);
    prepareExport().then(() => {
      setRequest(current => current === next ? { ...next, status: "ready" } : current);
    }).catch(() => {
      setRequest(current => current === next ? { ...next, status: "error" } : current);
    });
  };
  return { startExport, exporting: request?.status === "loading" || request?.status === "ready", exportError: request?.status === "error" };
}
