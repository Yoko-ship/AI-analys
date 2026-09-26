import { useAdminQuality } from "./useAdminQuality.js";
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
  const [rules, setRules] = useState([]);
  const [findings, setFindings] = useState([]);
  const [filters, setFilters] = useState({
    severity: "blocking",
    status: "new"
  });
  const [intake, setIntake] = useState(null);
  const [intakeState, setIntakeState] = useState("ineligible");
  const [ledger, setLedger] = useState(null);
  const [ledgerTicker, setLedgerTicker] = useState("");
  const [ruleBook, setRuleBook] = useState(null);
  const [source, setSource] = useState(null);
  const [selected, setSelected] = useState(() => new Set());
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
  const qualityState = useAdminQuality({ readJson, alive, setError, t, onSectionChange, previewCompany });
  const { loadQuality } = qualityState;
  const loadOverview = useCallback(async () => {
    const data = await readJson("/api/admin/overview");
    if (alive.current) setOverview(data);
  }, [readJson]);
  const loadIntake = useCallback(async () => {
    const data = await readJson("/api/admin/reports");
    if (!alive.current) return;
    setIntake(data);
    // A clean intake is the normal state, and opening on an empty «не допущена»
    // reads as a broken screen rather than as good news. The filter still holds
    // whatever the operator picks afterwards.
    setIntakeState(s => s === "ineligible" && !data.ineligible ? "used" : s);
  }, [readJson]);
  const loadRuleBook = useCallback(async () => {
    const data = await readJson("/api/admin/rules");
    if (alive.current) setRuleBook(data);
  }, [readJson]);
  const loadSource = useCallback(async () => {
    const data = await readJson("/api/admin/source");
    if (alive.current) setSource(data);
  }, [readJson]);
  const loadLedger = useCallback(async ticker => {
    const one = String(ticker || "").trim().toUpperCase();
    if (!one) return;
    const data = await readJson(`/api/admin/issuer/${encodeURIComponent(one)}`);
    if (alive.current) setLedger(data);
  }, [readJson]);
  const loadFindings = useCallback(async () => {
    const params = new URLSearchParams({
      limit: "300"
    });
    if (filters.severity) params.set("severity", filters.severity);
    if (filters.status) params.set("status", filters.status);
    const data = await readJson(`/api/audit/findings?${params}`);
    if (alive.current) setFindings(data.items || []);
  }, [filters, readJson]);
  useEffect(() => {
    fetch("/api/audit/rules").then(r => r.json()).then(d => {
      if (alive.current && d && d.ok) setRules(d.items || []);
    }).catch(() => {});
  }, []);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const jobs = [];
    if (isSystem) {
      if (section !== "railway") jobs.push(loadOverview());
      if (section === "companies") jobs.push(loadCompanyImports(companyFilter));else if (section === "findings") jobs.push(loadFindings());else if (section === "intake") jobs.push(loadIntake());else if (section === "rules") jobs.push(loadRuleBook());else if (section === "source") jobs.push(loadSource());
      else if (section === "quality") jobs.push(loadQuality());
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
  }, [section, rangeDays, usersOnly, isSystem, loadOverview, loadFindings, loadIntake, loadRuleBook, loadSource, loadQuality, loadCompanyImports, companyFilter, loadMetrics, loadAudience, loadEngagement, loadAnalysis, loadFeedback, feedbackFilter]);
  const runAudit = async () => {
    setBusy(true);
    setError("");
    try {
      await readJson("/api/audit/run", {
        method: "POST",
        body: JSON.stringify({
          trigger: "manual",
          with_history: 8
        })
      });
      await Promise.all([loadOverview(), section === "findings" ? loadFindings() : null]);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  const acceptFindings = async ids => {
    if (!ids.length) return;
    setBusy(true);
    setError("");
    try {
      for (const id of ids) {
        await readJson(`/api/audit/findings/${id}`, {
          method: "PATCH",
          body: JSON.stringify({
            status: "accepted",
            note: "принято в админ-панели"
          })
        });
      }
      setSelected(current => {
        const next = new Set(current);
        ids.forEach(id => next.delete(id));
        return next;
      });
      await Promise.all([loadOverview(), loadFindings()]);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  const toggleSelected = id => setSelected(current => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id);else next.add(id);
    return next;
  });
  const audit = overview && overview.audit;
  const catalog = overview && overview.catalog;
  const news = overview && overview.news;
  const streams = useMemo(() => overview?.streams || [], [overview?.streams]);
  const latest = audit && audit.latest;
  const openCounts = audit && audit.open || {};
  const history = audit && audit.history || [];
  const queue = audit && audit.queue || [];
  const staleStreams = useMemo(() => streams.filter(s => s.state === "stale").length, [streams]);
  const activeTab = isSystem ? "system" : section;
  useEffect(() => {
    if (section === "overview" && !overview) {
      loadOverview().catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section]);
  return {
    qualityState,
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
    rules,
    findings,
    filters,
    setFilters,
    intake,
    intakeState,
    setIntakeState,
    ledger,
    ledgerTicker,
    setLedgerTicker,
    ruleBook,
    source,
    companyImports,
    companyLookup,
    setCompanyLookup,
    companyFilter,
    setCompanyFilter,
    companyDraft,
    setCompanyDraft,
    companyNotice,
    companyBusy,
    selected,
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
    runAudit,
    acceptFindings,
    toggleSelected,
    catalog,
    news,
    streams,
    latest,
    openCounts,
    history,
    queue,
    staleStreams,
    activeTab
  };
}
