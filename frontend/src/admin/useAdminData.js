import { useAdminFeedback } from "./useAdminFeedback.js";
import { useAdminUsers } from "./useAdminUsers.js";
import { useCompanyImports } from "./useCompanyImports.js";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useT, SYSTEM_KEYS } from "./adminModel.js";
export function useAdminData({
  language,
  section,
  apiFetch,
  onSectionChange
}) {
  const t = useT(language);
  const isSystem = SYSTEM_KEYS.includes(section);
  const [metrics, setMetrics] = useState(null);
  const [audienceData, setAudienceData] = useState(null);
  const [engagementData, setEngagementData] = useState(null);
  const [analysisData, setAnalysisData] = useState(null);
  const [rangeDays, setRangeDays] = useState(30);
  const [overview, setOverview] = useState(null);
  const [ledger, setLedger] = useState(null);
  const [ledgerTicker, setLedgerTicker] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const readJson = useCallback(async (path, options) => {
    const res = await apiFetch(path, options);
    let data = null;
    try {
      data = await res.json();
    } catch {/* a 500 may not be JSON */}
    if (!res.ok) {
      const detail = data && (data.detail || data.message) || `HTTP ${res.status}`;
      throw new Error(res.status === 403 ? t("Нужны права администратора", "Administrator huquqi kerak", "Admin access required") : String(detail));
    }
    return data || {};
  }, [apiFetch, t]);
  const {
    feedbackData,
    feedbackFilter,
    setFeedbackFilter,
    feedbackBusy,
    loadFeedback,
    updateFeedbackStatus
  } = useAdminFeedback({
    readJson,
    alive,
    setError
  });
  const {
    usersData,
    funnel,
    adminLog,
    usersQuery,
    setUsersQuery,
    usersOnly,
    setUsersOnly,
    userDetail,
    setUserDetail,
    confirmAction,
    setConfirmAction,
    loadUsers,
    openUser,
    runUserAction
  } = useAdminUsers({
    readJson,
    alive,
    setBusy,
    setError
  });
  const {
    companyImports,
    companyLookup,
    setCompanyLookup,
    companyFilter,
    setCompanyFilter,
    companyDraft,
    setCompanyDraft,
    companyNotice,
    companyBusy,
    loadCompanyImports,
    discoverCompanies,
    previewCompany,
    approveCompany,
    rejectCompany,
    syncCompany,
    setCompanyVisibility
  } = useCompanyImports({
    readJson,
    alive,
    setError,
    t
  });
  const loadMetrics = useCallback(async () => {
    const data = await readJson("/api/admin/metrics/overview");
    if (alive.current) setMetrics(data);
  }, [readJson]);
  const loadAudience = useCallback(async days => {
    const data = await readJson(`/api/admin/metrics/audience?days=${days}`);
    if (alive.current) setAudienceData(data);
  }, [readJson]);
  const loadEngagement = useCallback(async days => {
    const data = await readJson(`/api/admin/metrics/engagement?days=${days}`);
    if (alive.current) setEngagementData(data);
  }, [readJson]);
  const loadAnalysis = useCallback(async days => {
    const data = await readJson(`/api/admin/metrics/analysis?days=${days}`);
    if (alive.current) setAnalysisData(data);
  }, [readJson]);
  const loadOverview = useCallback(async () => {
    const data = await readJson("/api/admin/overview");
    if (alive.current) setOverview(data);
  }, [readJson]);
  const loadLedger = useCallback(async ticker => {
    const one = String(ticker || "").trim().toUpperCase();
    if (!one) return;
    const data = await readJson(`/api/admin/issuer/${encodeURIComponent(one)}`);
    if (alive.current) setLedger(data);
  }, [readJson]);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const jobs = [];
    if (isSystem) {
      if (section === "companies") jobs.push(loadCompanyImports(companyFilter));
      else if (section === "streams") jobs.push(loadOverview());
    } else if (section === "overview") {
      jobs.push(loadMetrics());
    } else if (section === "audience") {
      jobs.push(loadAudience(rangeDays));
    } else if (section === "engagement") {
      jobs.push(loadEngagement(rangeDays));
    } else if (section === "analysis") {
      jobs.push(loadAnalysis(rangeDays));
    } else if (section === "users") {
      jobs.push(loadUsers(usersQuery, usersOnly));
    } else if (section === "feedback") {
      jobs.push(loadFeedback(feedbackFilter));
    }
    Promise.all(jobs).catch(e => {
      if (!cancelled) setError(String(e.message || e));
    }).finally(() => {
      if (!cancelled && alive.current) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
    // usersQuery deliberately not a dependency: the list reloads on Enter or a
    // filter click, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, rangeDays, usersOnly, isSystem, loadOverview, loadCompanyImports, companyFilter, loadMetrics, loadAudience, loadEngagement, loadAnalysis, loadFeedback, feedbackFilter]);
  const streams = useMemo(() => overview?.streams || [], [overview?.streams]);
  const staleStreams = useMemo(() => streams.filter(s => s.state === "stale").length, [streams]);
  const activeTab = isSystem ? "system" : section;
  useEffect(() => {
    if (section === "overview" && !overview) {
      loadOverview().catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section]);
  return {
    t,
    isSystem,
    metrics,
    audienceData,
    engagementData,
    analysisData,
    rangeDays,
    setRangeDays,
    usersData,
    funnel,
    adminLog,
    usersQuery,
    setUsersQuery,
    usersOnly,
    setUsersOnly,
    userDetail,
    setUserDetail,
    confirmAction,
    setConfirmAction,
    feedbackData,
    feedbackFilter,
    setFeedbackFilter,
    feedbackBusy,
    overview,
    ledger,
    ledgerTicker,
    setLedgerTicker,
    companyImports,
    companyLookup,
    setCompanyLookup,
    companyFilter,
    setCompanyFilter,
    companyDraft,
    setCompanyDraft,
    companyNotice,
    companyBusy,
    error,
    loading,
    busy,
    readJson,
    loadUsers,
    updateFeedbackStatus,
    openUser,
    runUserAction,
    loadCompanyImports,
    discoverCompanies,
    previewCompany,
    approveCompany,
    rejectCompany,
    syncCompany,
    setCompanyVisibility,
    loadLedger,
    streams,
    staleStreams,
    activeTab
  };
}
