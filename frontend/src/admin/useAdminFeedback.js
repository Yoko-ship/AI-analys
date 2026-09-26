import { useCallback, useState } from "react";
export function useAdminFeedback({
  readJson,
  alive,
  setError
}) {
  const [feedbackData, setFeedbackData] = useState(null);
  const [feedbackFilter, setFeedbackFilter] = useState("");
  const [feedbackBusy, setFeedbackBusy] = useState(0);
  const loadFeedback = useCallback(async (status = feedbackFilter) => {
    const suffix = status ? `?status=${encodeURIComponent(status)}` : "";
    const data = await readJson(`/api/admin/feedback${suffix}`);
    if (alive.current) setFeedbackData(data);
  }, [feedbackFilter, readJson, alive]);
  const updateFeedbackStatus = useCallback(async (id, status) => {
    setFeedbackBusy(id);
    setError("");
    try {
      await readJson(`/api/admin/feedback/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status
        })
      });
      await loadFeedback(feedbackFilter);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setFeedbackBusy(0);
    }
  }, [feedbackFilter, loadFeedback, readJson, setError, alive]);
  return {
    feedbackData,
    feedbackFilter,
    setFeedbackFilter,
    feedbackBusy,
    loadFeedback,
    updateFeedbackStatus
  };
}
