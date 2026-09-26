import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon, IconSprite } from "./icons.jsx";
import { NAVIGATION, LEGACY, RULE_TYPES, COLLECTION, COLUMNS, DEFAULT_RULES, FIELD_LABELS } from "./controlConfig.js";
import "./admin.css";
import "./control.css";

const LegacyPanel = React.lazy(() => import("./AdminPanel.jsx"));
const DocumentViewer = React.lazy(() => import("./DocumentViewer.jsx"));
const BASE = "/api/admin/control";
const langIndex = language => ({ ru: 0, uz: 1, en: 2 }[language] ?? 0);
const textValue = value => value === null || value === undefined || value === "" ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
const fieldLabel = (key, t) => FIELD_LABELS[key] ? t(...FIELD_LABELS[key]) : key.replaceAll("_", " ");
const INCIDENT_TITLES = {
  ANNUAL_BEFORE_YEAR_END: ["Годовой отчёт заканчивается до конца года", "Yillik hisobot yil tugashidan oldin yakunlangan", "Annual report ends before year-end"],
  BALANCE_COMPONENTS_MISSING: ["Не хватает компонентов баланса", "Balans tarkibiy qismlari yetishmayapti", "Balance components are missing"],
  BALANCE_IDENTITY_FAILED: ["Баланс не сходится", "Balans tengligi buzilgan", "Balance does not reconcile"],
  CAPITAL_COMPONENTS_MISMATCH: ["Изменение капитала не сходится", "Kapitaldagi o‘zgarish tarkibiy qismlarga mos emas", "Equity movement does not reconcile"],
  FOUND_NOT_INGESTED: ["Исходный файл найден, но ещё не загружен", "Manba fayli topildi, ammo hali yuklanmadi", "Source file found but not yet ingested"],
  IMPOSSIBLE_PERIOD: ["Некорректный отчётный период", "Hisobot davri noto‘g‘ri", "Reporting period is invalid"],
  INSURANCE_RESERVES_OMITTED: ["Не учтены страховые резервы", "Sug‘urta zaxiralari hisobga olinmagan", "Insurance reserves are missing"],
  PERIOD_CLASSIFICATION_ERROR: ["Неверно определён отчётный период", "Hisobot davri noto‘g‘ri tasniflangan", "Reporting period is classified incorrectly"],
  SOURCE_MAPPING_FAILED: ["Не удалось сопоставить данные источника", "Manba ma’lumotlarini moslashtirib bo‘lmadi", "Source data could not be mapped"],
  SOURCE_NOT_VERIFIED: ["Исходный документ не подтверждён", "Asl hujjat tasdiqlanmagan", "Source document has not been verified"],
  UZNF_2026H1_SOURCE_UNCONFIRMED: ["Отчёт UZNF за 2026H1 не подтверждён", "UZNFning 2026H1 hisoboti tasdiqlanmagan", "UZNF’s 2026H1 report is unconfirmed"],
  blocked_unit_mismatch: ["Единицы измерения не совпадают", "O‘lchov birliklari mos kelmaydi", "Units do not match"],
};
const incidentTitle = (code, t) => INCIDENT_TITLES[code] ? t(...INCIDENT_TITLES[code]) : String(code || "").replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
const incidentStage = (stage, t) => ({ analysis: t("Анализ", "Tahlil", "Analysis"), classification: t("Классификация", "Tasniflash", "Classification"), coverage: t("Полнота каталога", "Katalog qamrovi", "Catalog coverage") }[stage] || textValue(stage));
const incidentPriority = (severity, t) => ({ P0: t("Приоритет 0", "0-darajali ustuvorlik", "Priority 0"), P1: t("Приоритет 1", "1-darajali ustuvorlik", "Priority 1"), P2: t("Приоритет 2", "2-darajali ustuvorlik", "Priority 2"), P3: t("Приоритет 3", "3-darajali ustuvorlik", "Priority 3") }[severity] || textValue(severity));

export function StatusBadge({ value, label }) {
  const state = String(value || "unavailable");
  const tone = /blocked|failed|P0|P1|suspicious|denied|conflict/i.test(state) ? "danger"
    : /warning|stale|partial|not_|P2|draft|insufficient/i.test(state) ? "warning"
      : /complete|verified|validated|published|active|passed|success|resolved/i.test(state) ? "success"
        : /running|queued|retry|processing|rolling/i.test(state) ? "processing" : "neutral";
  return <span className={`control-status ${tone}`} title={state}><span aria-hidden="true" />{label || state.replaceAll("_", " ")}</span>;
}

function Loading({ t }) {
  return <div className="control-loading" role="status" aria-label={t("Загрузка", "Yuklanmoqda", "Loading")}>
    {[0, 1, 2, 3].map(i => <div key={i} />)}
  </div>;
}

function DetailDialog({ title, onClose, children, wide = false, t }) {
  const ref = useRef(null);
  useEffect(() => {
    const before = document.activeElement;
    const element = ref.current;
    element?.focus();
    const key = event => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab") {
        const nodes = [...element.querySelectorAll('button:not(:disabled),input,select,textarea,a[href],[tabindex="0"]')].filter(e => e.getClientRects().length);
        if (!nodes.length) { event.preventDefault(); return; }
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === element)) { last.focus(); event.preventDefault(); }
        else if (!event.shiftKey && document.activeElement === last) { first.focus(); event.preventDefault(); }
      }
    };
    element?.addEventListener("keydown", key);
    return () => { element?.removeEventListener("keydown", key); before?.focus?.(); };
  }, [onClose]);
  return <div className="control-scrim" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <aside className={`control-drawer ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
      <header><div><span className="control-eyebrow">AI ANALYS / CONTROL</span><h2>{title}</h2></div>
        <button className="control-icon-button" aria-label={t("Закрыть", "Yopish", "Close")} onClick={onClose}>×</button></header>
      <div className="control-drawer-content">{children}</div>
    </aside>
  </div>;
}

function KeyValues({ item, fields, t }) {
  const displayValue = key => {
    if (item.blocker_code && key === "severity") return incidentPriority(item[key], t);
    if (item.blocker_code && key === "stage") return incidentStage(item[key], t);
    return typeof item[key] === "boolean" ? (item[key] ? t("Да", "Ha", "Yes") : t("Нет", "Yo‘q", "No")) : textValue(item[key]);
  };
  return <dl className="control-key-values">{fields.filter(key => item[key] !== undefined).map(key => <React.Fragment key={key}>
    <dt>{fieldLabel(key, t)}</dt><dd>{displayValue(key)}</dd>
  </React.Fragment>)}</dl>;
}

function JobProgress({ job, t }) {
  return <div className="control-job-progress"><div><StatusBadge value={job.status} /><span>{job.processed ?? 0} / {job.total ?? "—"}</span></div>
    <progress max={job.total || 1} value={job.processed || 0} aria-label={t("Прогресс задания", "Vazifa jarayoni", "Job progress")} />
    <small>{t("Контрольная точка", "Nazorat nuqtasi", "Checkpoint")} {job.checkpoint ?? 0} · {t("Попытка", "Urinish", "Attempt")} {job.attempt}</small></div>;
}

function Overview({ data, navigate, t }) {
  const k = data.kpis || {};
  const ingestion = data.financial_ingestion;
  const percent = v => v == null ? "—" : `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(v * 100)}%`;
  const cards = [
    [t("Автопубликация · 24 ч", "Avtonashr · 24 soat", "Auto-publication · 24h"), percent(k.auto_publication), "publications", t("Цель ≥ 95%", "Maqsad ≥ 95%", "Target ≥ 95%"), "success"],
    [t("Активные блокеры", "Faol bloklovchilar", "Active blockers"), textValue(k.active_blockers), "incidents", t("Системные причины P0 / P1", "P0 / P1 tizimli sabablar", "P0 / P1 root causes"), k.active_blockers ? "danger" : ""],
    [t("Полнота каталога", "Katalog qamrovi", "Catalog completeness"), `${k.coverage_complete ?? 0} / ${k.coverage_total ?? 0}`, "catalog-coverage", t("Связь от файла до анализа", "Fayldan tahlilgacha bog‘lanish", "Document through to analysis"), ""],
    [t("В очереди", "Navbatda", "In the queue"), textValue(k.queued), "jobs", t("Ожидание и обработка", "Kutish va qayta ishlash", "Queued, running & retrying"), "processing"],
  ];
  return <>
    <div className="control-kpis">{cards.map(([label, value, route, hint, tone]) => <button key={route} className={`control-kpi ${tone}`} onClick={() => navigate(route)}>
      <span>{label}<Icon name="external" /></span><strong>{value}</strong><small>{hint}</small>
    </button>)}</div>
    <div className="control-overview-grid">
      <section className="control-card" aria-label={t("Данные банков", "Bank ma’lumotlari", "Bank data pipeline")}>
        <div className="control-card-title"><h2>{t("Данные банков", "Bank ma’lumotlari", "Bank data pipeline")}</h2>
          <StatusBadge value={!ingestion?.available || ingestion.monitor_stale ? "stale" : ingestion.incidents?.length ? "failed" : ingestion.status === "PARTIAL" ? "partial" : "active"} /></div>
        {!ingestion?.available ? <p role="alert" className="control-muted control-pad">{t("Статус недоступен. Проверьте мониторинг.", "Holat mavjud emas. Monitoringni tekshiring.", "Status unavailable. Check the monitor.")}</p> : <>
          {ingestion.monitor_stale && <p role="alert" className="control-muted control-pad">{t("Мониторинг давно не запускался — состояние не подтверждено.", "Monitoring eskirgan — holat tasdiqlanmagan.", "Monitor is overdue — pipeline health is unconfirmed.")}</p>}
          <p className="control-muted control-pad">{t("Опубликовано периодов", "Nashr qilingan davrlar", "Published periods")}: {ingestion.published_periods ?? 0} · {t("Заданий в очереди", "Navbatdagi vazifalar", "Pending jobs")}: {ingestion.pending_jobs ?? 0} · {t("Ожидают проверки источника", "Manba tekshiruvini kutmoqda", "Sources awaiting review")}: {ingestion.unreviewed_sources ?? 0} · {t("Одобрено, не опубликовано", "Tasdiqlangan, nashr qilinmagan", "Approved, unpublished")}: {ingestion.approved_unpublished ?? 0}</p>
          {ingestion.incidents?.map(item => <div className="control-attention" key={item.code} role="alert">
            <StatusBadge value="failed" /><div><strong>{incidentTitle(item.code, t)}</strong><span>{item.detail}</span><small>{item.first_seen}</small></div>
          </div>)}
          {!ingestion.incidents?.length && !ingestion.monitor_stale && <p className="control-muted control-pad">{t("Активных сбоев нет. Непроверенные данные не публикуются автоматически.", "Faol nosozliklar yo‘q. Tekshirilmagan ma’lumotlar avtomatik nashr qilinmaydi.", "No active failures. Unreviewed figures are not published automatically.")}</p>}
        </>}
      </section>
      <section className="control-card"><div className="control-card-title"><h2>{t("Требует внимания", "E’tibor talab qiladi", "Needs attention")}</h2><span className="control-count">{data.attention?.length || 0}</span></div>
        <p className="control-muted">{t("Исключения, сгруппированные по системной причине", "Tizimli sabablar bo‘yicha guruhlangan istisnolar", "Exceptions grouped by their underlying cause")}</p>
        {data.attention?.length ? data.attention.map(item => <button className="control-attention" key={item.id} onClick={() => navigate("incidents", { object: item.id })}>
          <StatusBadge value={item.severity} /><div><strong>{item.blocker_code}</strong><span>{item.ticker || item.stage} · {item.impact_count} {t("объектов", "obyekt", "affected objects")}</span></div><Icon name="external" />
        </button>) : <div className="control-empty"><Icon name="check" /><h3>{t("Открытых блокеров нет", "Ochiq bloklovchilar yo‘q", "No open blockers")}</h3><p>{t("Проверки новых документов появятся здесь.", "Yangi hujjat tekshiruvlari shu yerda ko‘rinadi.", "New document checks will appear here.")}</p></div>}
      </section>
      <section className="control-card"><div className="control-card-title"><h2>{t("Путь документа", "Hujjat yo‘li", "Document pipeline")}</h2><Icon name="sliders" /></div>
        <p className="control-muted">{t("Каждый этап сохраняет историю и источник", "Har bosqich tarix va manbani saqlaydi", "Every stage retains its history and source")}</p>
        <div className="control-pipeline">{[
          ["documents", t("Документы", "Hujjatlar", "Documents")], ["parsers", t("Распознавание", "Aniqlash", "Parsing")],
          ["facts", t("Финансовые факты", "Moliyaviy faktlar", "Financial facts")], ["calculations", t("Расчёты", "Hisob-kitoblar", "Calculations")],
          ["analyses", t("Анализ", "Tahlil", "Analysis")], ["publications", t("Публикации", "Nashrlar", "Publications")],
        ].map(([key, label], i) => <button key={key} onClick={() => navigate(key)}><span>{String(i + 1).padStart(2, "0")}</span><strong>{label}</strong><em>{Object.values(data.counts?.[key] || {}).reduce((a, b) => a + b, 0)}</em></button>)}</div>
      </section>
      <section className="control-card"><div className="control-card-title"><h2>{t("Последние публикации", "So‘nggi nashrlar", "Recent publications")}</h2><button onClick={() => navigate("publications")}>{t("Все", "Barchasi", "View all")} →</button></div>
        {data.publications?.length ? data.publications.map(item => <button className="control-feed" key={item.id} onClick={() => navigate("publications", { object: item.id })}><strong>{item.ticker}</strong><span>{item.period} · {item.standard}</span><StatusBadge value={item.status} /></button>) : <p className="control-muted control-pad">{t("Проверенных публикаций пока нет.", "Tekshirilgan nashrlar hozircha yo‘q.", "No verified publications have been indexed yet.")}</p>}
      </section>
      <section className="control-card"><div className="control-card-title"><h2>{t("Фоновые задания", "Fon vazifalari", "Background jobs")}</h2><button onClick={() => navigate("jobs")}>{t("Все", "Barchasi", "View all")} →</button></div>
        {data.jobs?.length ? data.jobs.slice(0, 3).map(job => <button key={job.id} className="control-job-link" onClick={() => navigate("jobs", { object: job.id })}><strong>{job.category}</strong><JobProgress job={job} t={t} /></button>) : <p className="control-muted control-pad">{t("Очередь пуста. Синхронизируйте каталог для первого запуска.", "Navbat bo‘sh. Avval katalogni sinxronlang.", "The queue is empty. Sync the catalog to index existing records.")}</p>}
      </section>
    </div>
  </>;
}

export default function ControlPanel({ apiFetch, language = "ru", section = "overview", onSectionChange, user }) {
  const li = langIndex(language);
  const t = useCallback((ru, uz, en) => [ru, uz, en][li], [li]);
  const [session, setSession] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState(window.location.search);
  const [refresh, setRefresh] = useState(0);
  const [detail, setDetail] = useState(null);
  const [related, setRelated] = useState({});
  const [detailError, setDetailError] = useState("");
  const [history, setHistory] = useState(null);
  const [action, setAction] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [globalSearch, setGlobalSearch] = useState("");
  const [searchResults, setSearchResults] = useState(null);
  const [hiddenColumns, setHiddenColumns] = useState([]);
  const [savedViews, setSavedViews] = useState([]);
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem(`admin-sidebar:${user?.id || "user"}`) === "collapsed"; } catch { return false; } });
  const params = useMemo(() => new URLSearchParams(query), [query]);
  const collection = COLLECTION[section] || section;
  const listQuery = useMemo(() => {
    const filters = new URLSearchParams(query);
    for (const key of ["object", "sheet", "page", "cell", "line", "row"]) filters.delete(key);
    if (RULE_TYPES[section]) filters.set("category", RULE_TYPES[section]);
    return filters.toString();
  }, [query, section]);
  const selected = params.get("object");
  const isLegacy = LEGACY.includes(section) || section === "system";
  const read = useCallback(async (path, options) => {
    const response = await apiFetch(BASE + path, options);
    let result;
    try { result = await response.json(); } catch (exc) { if (exc.name === "AbortError") throw exc; throw new Error(`HTTP ${response.status}`); }
    if (!response.ok) throw new Error(`${result.error?.code || response.status}: ${result.error?.message || result.detail || "Request failed"}`);
    return result;
  }, [apiFetch]);
  const can = capability => session?.capabilities?.includes(capability);

  useEffect(() => {
    const pop = () => setQuery(window.location.search);
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => { setQuery(window.location.search); setHiddenColumns([]); }, [section]);
  useEffect(() => {
    if (section !== "overview") return undefined;
    const timer = setInterval(() => { if (!document.hidden) setRefresh(v => v + 1); }, 60000);
    return () => clearInterval(timer);
  }, [section]);
  useEffect(() => {
    let live = true;
    read("/session").then(result => { if (live) setSession(result); }).catch(exc => { if (live) setError(exc.message); });
    return () => { live = false; };
  }, [read, refresh, user?.id, user?.admin_role]);
  useEffect(() => {
    if (!session || isLegacy) return;
    const controller = new AbortController();
    setLoading(true); setError("");
    read(section === "overview" ? "/overview" : `/${collection}?${listQuery}`, { signal: controller.signal })
      .then(result => { setData(result); setLoading(false); }).catch(exc => { if (exc.name !== "AbortError") { setError(exc.message); setLoading(false); } });
    return () => controller.abort();
  }, [section, collection, listQuery, read, refresh, session, isLegacy]);
  useEffect(() => {
    if (!selected || isLegacy) { setDetail(null); return; }
    const controller = new AbortController();
    setDetail(null); setHistory(null); setDetailError("");
    if (collection === "audit") { setDetail(data?.items?.find(r => r.id === selected) || null); return; }
    read(`/${collection}/${encodeURIComponent(selected)}`, { signal: controller.signal }).then(result => { setDetail(result.item); setRelated(result.related || {}); })
      .catch(exc => { if (exc.name !== "AbortError") setDetailError(exc.message); });
    return () => controller.abort();
  }, [selected, collection, read, refresh, isLegacy, data]);
  useEffect(() => {
    if (!globalSearch.trim()) { setSearchResults(null); return; }
    const controller = new AbortController();
    const timeout = setTimeout(() => read(`/search?q=${encodeURIComponent(globalSearch)}`, { signal: controller.signal }).then(result => setSearchResults(result.items)).catch(exc => { if (exc.name !== "AbortError") setError(exc.message); }), 250);
    return () => { clearTimeout(timeout); controller.abort(); };
  }, [globalSearch, read]);
  useEffect(() => {
    if (section !== "jobs" && !action?.waitingJob) return;
    const timer = setInterval(() => setRefresh(n => n + 1), 5000);
    return () => clearInterval(timer);
  }, [section, action?.waitingJob]);
  const savedKey = `admin-views:${user?.id}:${session?.environment}:${section}`;
  useEffect(() => { try { setSavedViews(JSON.parse(localStorage.getItem(savedKey) || "[]")); } catch { setSavedViews([]); } }, [savedKey]);

  const navigate = useCallback((nextSection, filters = {}) => {
    const search = new URLSearchParams(filters).toString();
    const path = nextSection === "overview" ? "/admin" : `/admin/${nextSection}`;
    window.history.pushState({ view: "admin" }, "", path + (search ? "?" + search : ""));
    setQuery(search ? "?" + search : "");
    onSectionChange(nextSection);
    setSearchResults(null); setGlobalSearch(""); setNotice("");
  }, [onSectionChange]);
  const updateFilters = useCallback(changes => {
    const p = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(changes)) { if (value) p.set(key, value); else p.delete(key); }
    if (!Object.hasOwn(changes, "cursor") && !Object.hasOwn(changes, "object")) p.delete("cursor");
    const search = p.toString();
    window.history.pushState({ view: "admin" }, "", window.location.pathname + (search ? "?" + search : ""));
    setQuery(search ? "?" + search : "");
  }, []);
  const closeDetail = useCallback(() => updateFilters({ object: "", sheet: "", page: "", cell: "", line: "", row: "" }), [updateFilters]);
  const closeAction = useCallback(() => { if (!busy) setAction(null); }, [busy]);
  const requestAction = (name, item = detail, extra = {}, targetCollection = collection) => {
    setNotice("");
    setAction({ name, item, collection: targetCollection, extra, key: crypto.randomUUID() });
  };
  const submit = async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const input = { reason: form.get("reason"), ...action.extra };
    if (action.item?.version) input.version = action.item.version;
    let entity = action.item?.id || "new";
    if (action.name === "draft") {
      input.category = form.get("category"); input.title = form.get("title");
      try { input.config = JSON.parse(form.get("config")); } catch { setNotice(t("Некорректный JSON правила.", "Qoida JSON formati noto‘g‘ri.", "The rule configuration is not valid JSON.")); return; }
    }
    if (action.name === "grant") { entity = form.get("email"); input.role = form.get("role"); }
    if (action.name === "rollback") input.incident_id = form.get("incident_id");
    setBusy(true); setNotice("");
    try {
      const result = await read(`/${action.collection}/${encodeURIComponent(entity)}/${action.name}`, { method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": action.key, "X-Admin-OTP": String(form.get("otp") || "") }, body: JSON.stringify(input) });
      setAction(null); setRefresh(n => n + 1);
      if (result.job_id) navigate("jobs", { object: result.job_id });
      else if (result.item && action.name === "draft") navigate(RULE_TYPES[section] ? section : "rules-workspace", { object: result.item.id });
      setNotice(t("Действие сохранено в журнале аудита.", "Amal audit jurnalida saqlandi.", "The action was recorded in the audit trail."));
    } catch (exc) { setNotice(exc.message); } finally { setBusy(false); }
  };
  const exportRows = async format => {
    try {
      const p = new URLSearchParams(query); p.delete("cursor"); p.delete("object"); p.set("format", format);
      if (RULE_TYPES[section]) p.set("category", RULE_TYPES[section]);
      const response = await apiFetch(`${BASE}/${collection}/export?${p}`);
      if (!response.ok) { const error = await response.json(); throw new Error(error.error?.message || "Export failed"); }
      const url = URL.createObjectURL(await response.blob()); const link = document.createElement("a");
      link.href = url; link.download = `admin-${collection}.${format}`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (exc) { setError(exc.message); }
  };
  const allNav = NAVIGATION.flatMap(g => g.items);
  const title = allNav.find(n => n[0] === section)?.[li + 2] || (section === "rules-workspace" ? t("Правила", "Qoidalar", "Rules") : t("Продуктовая аналитика", "Mahsulot tahlili", "Product analytics"));
  const columns = COLUMNS[collection] || COLUMNS.rules;
  const displayColumns = columns.filter(c => !hiddenColumns.includes(c));
  const selectedIncidentTitle = collection === "incidents" && detail ? incidentTitle(detail.blocker_code || detail.title, t) : null;
  const statusOptions = [...new Set(["OPEN", "INVESTIGATING", "RESOLVED", "PUBLISHED", "BLOCKED", "QUALITY_BLOCKED", "DRAFT", "TESTED", "APPROVED", "ACTIVE", "QUEUED", "RUNNING", "COMPLETED", "FAILED", "verified", "blocked", "stale", "COMPLETE", "FOUND_NOT_INGESTED", "CLASSIFIED_SUSPICIOUS", ...(data?.items || []).map(r => r.status).filter(Boolean)])];
  const actionButton = (name, label, capability, item = detail, extra = {}, coll = collection) => can(capability) && <button className="control-button" onClick={() => requestAction(name, item, extra, coll)}>{label}</button>;

  return <div className={`control-shell ${collapsed ? "is-collapsed" : ""}`}>
    <IconSprite />
    <aside className="control-sidebar"><div className="control-sidebar-brand"><span className="control-mark">A<span>•</span></span><div><strong>AI Analys</strong><small>CONTROL CENTER</small></div></div>
      <button className="control-collapse" onClick={() => { setCollapsed(v => !v); try { localStorage.setItem(`admin-sidebar:${user?.id || "user"}`, collapsed ? "expanded" : "collapsed"); } catch { /* optional preference */ } }} aria-label={t("Свернуть меню", "Menyuni yig‘ish", "Toggle sidebar")}><Icon name="panel" /><span>{t("Свернуть меню", "Menyuni yig‘ish", "Collapse navigation")}</span></button>
      <nav aria-label={t("Разделы администрирования", "Boshqaruv bo‘limlari", "Administration sections")}>{NAVIGATION.map(group => <div className="control-nav-group" key={group.title[2]}><p>{group.title[li]}</p>{group.items.filter(n => n[0] !== "access" || can("access")).map(([key, icon, ...names]) => <button title={names[li]} key={key} onClick={() => navigate(key)} aria-current={key === section ? "page" : undefined} className={key === section ? "active" : ""}><Icon name={icon} /><span>{names[li]}</span>{key === "incidents" && data?.kpis?.active_blockers > 0 && <b>{data.kpis.active_blockers}</b>}</button>)}</div>)}</nav>
      <div className="control-sidebar-footer"><Icon name="lock" /><span>{t("Защищённая рабочая область", "Himoyalangan ish maydoni", "Protected workspace")}</span></div>
    </aside>
    <div className="control-workspace">
      <label className="control-mobile-navigation">{t("Раздел", "Bo‘lim", "Section")}<select aria-label={t("Раздел", "Bo‘lim", "Section")} value={section} onChange={event => navigate(event.target.value)}>{NAVIGATION.map(group => <optgroup label={group.title[li]} key={group.title[2]}>{group.items.filter(item => item[0] !== "access" || can("access")).map(([key, , ...names]) => <option key={key} value={key}>{names[li]}</option>)}</optgroup>)}</select></label>
      <header className="control-topbar"><div className="control-search"><Icon name="search" /><input aria-label={t("Глобальный поиск", "Umumiy qidiruv", "Global search")} placeholder={t("Тикер, ИНН, ISIN, документ или run…", "Tiker, STIR, ISIN, hujjat yoki run…", "Ticker, tax ID, ISIN, document or run…")} value={globalSearch} onChange={e => setGlobalSearch(e.target.value)} />
        {searchResults && <div className="control-search-results">{searchResults.length ? searchResults.map(item => <button key={`${item.collection}:${item.id}`} onClick={() => navigate(item.collection, { object: item.id })}><span>{item.collection} · {item.ticker}</span><strong>{item.title || item.id}</strong></button>) : <p>{t("Ничего не найдено", "Hech narsa topilmadi", "No matches")}</p>}</div>}
      </div><span className={`control-environment ${session?.environment === "production" ? "production" : ""}`}><i />{session?.environment || "…"}</span><div className="control-actor"><span>{session?.actor?.email || user?.email}</span><small>{session?.actor?.role || "—"}</small></div></header>
      <main className="control-main"><div className="control-page-head"><div><span className="control-eyebrow">{t("Администрирование", "Boshqaruv", "Administration")} / {t("Рабочая область", "Ish maydoni", "Workspace")}</span><h1>{title}</h1><p>{t("От источника до публикации — с проверкой каждого шага.", "Manbadan nashrgacha — har bir bosqich tekshiriladi.", "From source to publication, with every step accounted for.")}</p></div><div className="control-head-actions"><button className="control-button" onClick={() => setRefresh(n => n + 1)}><Icon name="refresh" />{t("Обновить", "Yangilash", "Refresh")}</button>
        {(section === "overview" || section === "catalog-coverage" || section === "documents") && actionButton("sync", t("Синхронизировать каталог", "Katalogni sinxronlash", "Sync catalog"), "retry", { id: "catalog" }, {}, "catalog")}
        {(RULE_TYPES[section] || section === "parsers" || section === "rules-workspace") && actionButton("draft", t("Новое правило", "Yangi qoida", "New rule"), "draft", null, {}, "rules")}
        {section === "calculations" && actionButton("recalculate", t("Пересчитать выборку", "Tanlovni qayta hisoblash", "Recalculate selection"), "retry", { id: "all" }, { filters: Object.fromEntries(params) }, "calculations")}
        {section === "access" && actionButton("grant", t("Назначить роль", "Rol berish", "Assign role"), "access", null, {}, "access")}
      </div></div>
      {notice && <div className="control-notice" role="status">{notice}</div>}
      {error && <div className="control-error" role="alert"><Icon name="alert" />{error}<button onClick={() => setRefresh(n => n + 1)}>{t("Повторить", "Takrorlash", "Retry")}</button></div>}
      {isLegacy ? <><div className="control-legacy-links">{[["product-overview", "Product overview"], ["audience", "Audience"], ["companies", "Company intake"], ["analysis", "Analysis monitor"], ["railway", "Railway"]].map(([key, label]) => <button key={key} className="control-button" onClick={() => navigate(key)}>{label}</button>)}</div><Suspense fallback={<Loading t={t} />}><LegacyPanel apiFetch={apiFetch} language={language} section={section === "product-overview" ? "overview" : section} onSectionChange={navigate} /></Suspense></>
        : loading ? <Loading t={t} /> : section === "overview" && data ? <Overview data={data} navigate={navigate} t={t} /> : <>
          <section className="control-card control-registry">
            <form className="control-filters" onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); updateFilters({ q: f.get("q"), ticker: f.get("ticker"), status: f.get("status"), standard: f.get("standard"), period: f.get("period"), object: "" }); }} key={`${section}:${listQuery}`}>
              <label>{t("Поиск", "Qidiruv", "Search")}<input name="q" defaultValue={params.get("q") || ""} placeholder={t("По всему реестру", "Barcha yozuvlar", "Search all records")} /></label>
              <label>{t("Эмитент", "Emitent", "Issuer")}<input name="ticker" defaultValue={params.get("ticker") || ""} placeholder="UZNF, HMKB" /></label>
              <label>{t("Статус", "Holat", "Status")}<select name="status" defaultValue={params.get("status") || ""}><option value="">{t("Все статусы", "Barcha holatlar", "All statuses")}</option>{statusOptions.map(status => <option key={status}>{status}</option>)}</select></label>
              <label>{t("Стандарт", "Standart", "Standard")}<select name="standard" defaultValue={params.get("standard") || ""}><option value="">{t("Все", "Barchasi", "All")}</option><option>NSBU</option><option>IFRS</option><option value="NSBU,IFRS">NSBU + IFRS</option></select></label>
              <label>{t("Период", "Davr", "Period")}<input name="period" defaultValue={params.get("period") || ""} placeholder="2026H1" /></label>
              <button type="submit" className="control-button primary">{t("Применить", "Qo‘llash", "Apply filters")}</button>
            </form>
            <div className="control-table-tools"><span><strong>{data?.total ?? 0}</strong> {t("записей", "yozuv", "records")} <span className="control-muted">· {t("фильтрация на сервере", "serverda saralash", "filtered on the server")}</span></span><div>
              <button onClick={() => updateFilters({ q: "", ticker: "", status: "", standard: "", period: "", cursor: "", object: "" })}>{t("Сбросить", "Tozalash", "Reset")}</button>
              <details><summary>{t("Столбцы", "Ustunlar", "Columns")}</summary><div className="control-popover">{columns.map(col => <label key={col}><input type="checkbox" checked={!hiddenColumns.includes(col)} onChange={() => setHiddenColumns(old => old.includes(col) ? old.filter(c => c !== col) : [...old, col])} />{fieldLabel(col, t)}</label>)}</div></details>
              <details><summary>{t("Представления", "Ko‘rinishlar", "Saved views")}</summary><div className="control-popover">{savedViews.map(view => <button key={view.name} onClick={() => navigate(section, view.filters)}>{view.name}</button>)}<form onSubmit={event => { event.preventDefault(); const name = new FormData(event.currentTarget).get("name").trim(); if (!name) return; const views = [...savedViews.filter(v => v.name !== name), { name, filters: Object.fromEntries(params) }].slice(-15); setSavedViews(views); try { localStorage.setItem(savedKey, JSON.stringify(views)); } catch { setNotice("Local preferences are unavailable."); } }}><input name="name" aria-label={t("Название представления", "Ko‘rinish nomi", "View name")} required placeholder={t("Название", "Nomi", "View name")} /><button>{t("Сохранить", "Saqlash", "Save")}</button></form></div></details>
              {can("export") && <><button onClick={() => exportRows("csv")}>CSV ↓</button><button onClick={() => exportRows("json")}>JSON ↓</button></>}
            </div></div>
            {data?.items?.length ? <div className="control-table-scroll"><table><thead><tr>{displayColumns.map(col => <th key={col} scope="col"><button disabled={!["ticker", "status", "standard", "period", "severity", "source", "category", "updated_at", "id", "created_at", "actor", "action"].includes(col)} onClick={() => updateFilters({ sort: col, direction: params.get("sort") === col && params.get("direction") === "asc" ? "desc" : "asc" })}>{fieldLabel(col, t)}{params.get("sort") === col ? params.get("direction") === "asc" ? " ↑" : " ↓" : ""}</button></th>)}</tr></thead><tbody>{data.items.map(item => <tr key={item.id} className={selected === item.id ? "selected" : ""}>{displayColumns.map((col, i) => <td key={col}>{i === 0 ? <button className="control-row-link" onClick={() => updateFilters({ object: item.id })}>{collection === "incidents" && col === "severity" ? incidentPriority(item[col], t) : textValue(item[col])}<Icon name="external" /></button> : collection === "incidents" && col === "blocker_code" ? <span className="control-incident-code" title={textValue(item[col])}><strong>{incidentTitle(item[col], t)}</strong><small>{textValue(item[col])}</small></span> : collection === "incidents" && col === "stage" ? <span title={textValue(item[col])}>{incidentStage(item[col], t)}</span> : ["status", "result", "severity"].includes(col) ? <StatusBadge value={item[col]} label={collection === "incidents" && col === "severity" ? incidentPriority(item[col], t) : undefined} /> : typeof item[col] === "boolean" ? <span className={`control-bool ${item[col] ? "yes" : ""}`}>{item[col] ? t("Да", "Ha", "Yes") : "—"}</span> : <span title={textValue(item[col])}>{textValue(item[col])}</span>}</td>)}</tr>)}</tbody></table></div>
              : <div className="control-empty"><Icon name="search" /><h3>{t("Нет записей для этой выборки", "Tanlov bo‘yicha yozuvlar yo‘q", "No records in this view")}</h3><p>{t("Измените фильтры или синхронизируйте каталог. Неполученные данные не считаются проверенными.", "Filtrlarni o‘zgartiring yoki katalogni sinxronlang. Olinmagan ma’lumotlar tekshirilgan hisoblanmaydi.", "Adjust the filters or sync the catalog. Missing data is never marked as verified.")}</p></div>}
            <footer className="control-pagination"><span>{data?.items?.length || 0} / {data?.total || 0}</span><div><button className="control-button" disabled={!params.get("cursor")} onClick={() => updateFilters({ cursor: "" })}>{t("Первая страница", "Birinchi sahifa", "First page")}</button><button className="control-button" disabled={!data?.next_cursor} onClick={() => updateFilters({ cursor: data.next_cursor, object: "" })}>{t("Следующая", "Keyingi", "Next page")} →</button></div></footer>
          </section>
        </>}
      <footer className="control-footnote"><Icon name="lock" />{t("Исходные данные неизменяемы. Исправления проходят через версионируемые правила.", "Asl ma’lumotlar o‘zgarmaydi. Tuzatishlar versiyali qoidalar orqali bajariladi.", "Source data stays immutable. Corrections go through versioned rules.")}</footer>
      </main>
    </div>
    {selected && !isLegacy && <DetailDialog title={selectedIncidentTitle ? `${detail?.ticker || "—"} · ${selectedIncidentTitle}` : detail?.ticker ? `${detail.ticker} · ${detail.metric_code || detail.period || title}` : title} onClose={closeDetail} wide={collection === "documents"} t={t}>
      {detailError ? <div className="control-error" role="alert">{detailError}</div> : !detail ? <Loading t={t} /> : <>
        <div className="control-detail-meta"><StatusBadge value={detail.status || detail.result} /><span>v{detail.version || 1}</span><code>{detail.id}</code></div>
        {selectedIncidentTitle && <div className="control-incident-explainer"><strong>{selectedIncidentTitle}</strong><p>{t("Проверка остановила публикацию или пометила данные для проверки. Машинный код сохранён ниже для поиска и аудита.", "Tekshiruv nashrni to‘xtatdi yoki ma’lumotlarni tekshirish uchun belgiladi. Qidiruv va audit uchun mashina kodi quyida saqlanadi.", "The check stopped publication or flagged the data for review. Its machine code is retained below for search and audit.")}</p><code>{detail.blocker_code || detail.title}</code></div>}
        {detail.blockers?.length > 0 && <div className="control-blockers"><strong>{t("Блокеры", "Bloklovchilar", "Blockers")}</strong>{detail.blockers.map(code => <p key={code}><Icon name="alert" />{code}</p>)}</div>}
        <div className="control-detail-actions">
          {collection === "documents" && actionButton("reprocess", t("Повторить обработку", "Qayta ishlash", "Reprocess"), "retry")}
          {collection === "jobs" && (["COMPLETED", "FAILED", "BLOCKED", "CANCELLED"].includes(detail.status) ? actionButton("retry", t("Новая попытка", "Yangi urinish", "New attempt"), "retry") : actionButton("cancel", t("Остановить безопасно", "Xavfsiz to‘xtatish", "Cancel safely"), "retry"))}
          {collection === "incidents" && <>{actionButton("investigate", t("Взять в работу", "Tekshirishni boshlash", "Investigate"), "comment")}{actionButton("comment", t("Комментарий", "Izoh", "Comment"), "comment")}{actionButton("resolve", t("Проверить и закрыть", "Tekshirish va yopish", "Verify & resolve"), "comment")}</>}
          {collection === "rules" && <>{["DRAFT", "TESTED"].includes(detail.status) && actionButton("test", t("Тесты и влияние", "Testlar va ta’sir", "Test & assess impact"), "test")}{detail.status === "TESTED" && actionButton("approve", t("Подтвердить", "Tasdiqlash", "Approve"), "approve")}{detail.status === "APPROVED" && actionButton("activate", t("Запустить активацию", "Faollashtirish", "Start activation"), "activate")}{actionButton("draft", t("Новая версия", "Yangi versiya", "New version"), "draft")}</>}
          {collection === "publications" && actionButton("rollback", detail.rollback_request ? t("Подтвердить откат", "Qaytarishni tasdiqlash", "Confirm rollback") : t("Запросить откат", "Qaytarishni so‘rash", "Request rollback"), "rollback")}
          {collection !== "audit" && <button className="control-button" onClick={() => read(`/${collection}/${encodeURIComponent(detail.id)}/history`).then(result => setHistory(result.items)).catch(exc => setDetailError(exc.message))}>{t("История версий", "Versiyalar tarixi", "Version history")}</button>}
        </div>
        {collection === "documents" && <Suspense fallback={<Loading t={t} />}><DocumentViewer document={detail} apiFetch={apiFetch} read={read} params={params} updateFilters={updateFilters} navigate={navigate} t={t} /></Suspense>}
        {collection === "jobs" && <JobProgress job={detail} t={t} />}
        {collection === "calculations" && <section className="control-trace"><span className="control-eyebrow">CALCULATION TRACE</span><h3>{detail.metric_code} <strong>{textValue(detail.display_result ?? detail.value)} {detail.unit === "percent" ? "%" : detail.unit === "ratio" ? "×" : detail.unit}</strong></h3><pre>{detail.expression || detail.formula || "—"}</pre><KeyValues item={detail} fields={["formula_version", "raw_result", "report_period_end", "market_price_at", "shares_at", "sector_template"]} t={t} />
          <h4>{t("Входные факты и источник", "Kirish faktlari va manba", "Inputs & source lineage")}</h4>{detail.inputs?.length ? detail.inputs.map(input => <button className="control-source-link" key={input.id} onClick={() => navigate(input.document_id ? "documents" : "facts", { object: input.document_id || input.id, ...(input.source_location || {}) })}><strong>{input.title || input.metric_code}</strong><span>{textValue(input.value)} {input.unit}</span><small>{input.source_line_id || input.source_location?.cell || "SOURCE_LOCATION_MISSING"}</small><Icon name="external" /></button>) : <div className="control-error">SOURCE_LOCATION_MISSING</div>}
        </section>}
        {collection === "rules" && <><div className="control-rule-diff"><div><h4>{t("Текущая версия", "Joriy versiya", "Current version")}</h4><pre>{JSON.stringify(detail.previous_config || {}, null, 2)}</pre></div><div><h4>{t("Новая версия", "Yangi versiya", "Draft version")}</h4><pre>{JSON.stringify(detail.config, null, 2)}</pre></div></div>{detail.tests && <div className="control-card control-pad"><StatusBadge value={detail.tests.passed ? "PASSED" : "FAILED"} /><p>{detail.tests.cases?.length} {t("контрольных примеров", "nazorat misoli", "regression cases")}</p></div>}{detail.impact && <><h3>{t("Область влияния", "Ta’sir doirasi", "Impact set")}</h3><KeyValues item={detail.impact.counts} fields={Object.keys(detail.impact.counts)} t={t} /></>}</>}
        {["analyses", "publications"].includes(collection) && <><div className="control-analysis-headline">{detail.headline}</div>{detail.paragraphs?.map((p, i) => <p className="control-prose" key={i}>{p}</p>)}{detail.issues?.map((issue, i) => <div className="control-card control-pad" key={i}><h4>{issue.title || issue.code}</h4><KeyValues item={issue} fields={["cause", "impact", "solution_text", "verdict_text"]} t={t} /></div>)}<h3>{t("Доказательная база", "Dalillar", "Evidence")}</h3>{detail.facts?.map(f => <button key={f.id} className="control-source-link" onClick={() => navigate("facts", { object: f.id })}><strong>{f.title || f.metric_code}</strong><span>{textValue(f.value)} {f.unit}</span><Icon name="external" /></button>)}</>}
        {collection === "issuers" && Object.entries(related).map(([kind, rows]) => <section key={kind}><h3>{kind}</h3>{rows.map(row => <button key={row.id} className="control-source-link" onClick={() => navigate(kind, { ticker: detail.ticker, object: row.id })}><strong>{row.title || row.period || row.id}</strong><StatusBadge value={row.status} /></button>)}</section>)}
        {detail.document_id && collection !== "documents" && <button className="control-button" onClick={() => navigate("documents", { object: detail.document_id, ...(detail.source_location || {}) })}><Icon name="file" />{t("Открыть документ", "Hujjatni ochish", "Open source document")}</button>}
        <KeyValues item={detail} fields={Object.keys(detail).filter(key => !["id", "version", "headline", "paragraphs", "inputs", "facts", "config", "previous_config", "tests", "impact", "expression", "formula"].includes(key) && typeof detail[key] !== "object")} t={t} />
        {detail.comments?.map((comment, i) => <div className="control-comment" key={i}><strong>{comment.actor}</strong><small>{comment.at}</small><p>{comment.text}</p></div>)}
        {history && <section><h3>{t("История версий", "Versiyalar tarixi", "Version history")}</h3>{history.map(revision => <details className="control-history" key={revision.version}><summary>v{revision.version} · {revision.updated_at} · {revision.status}</summary><pre>{JSON.stringify(revision, null, 2)}</pre></details>)}</section>}
        <details className="control-history"><summary>{t("Все сохранённые поля", "Barcha saqlangan maydonlar", "All recorded fields")}</summary><pre>{JSON.stringify(detail, null, 2)}</pre></details>
      </>}
    </DetailDialog>}
    {action && <DetailDialog title={t("Подтвердите действие", "Amalni tasdiqlang", "Review this action")} onClose={closeAction} t={t}><form className="control-action-form" onSubmit={submit}>
      <p><strong>{action.collection} / {action.name}</strong></p><p className="control-muted">{action.item?.id || t("Новый объект", "Yangi obyekt", "New object")} · {session?.environment}</p>
      {action.name === "draft" && <RuleFields category={action.item?.category || RULE_TYPES[section] || "parser"} config={action.item?.config} title={action.item?.title} t={t} />}
      {action.name === "grant" && <><label>Email<input name="email" type="email" required defaultValue={action.item?.email} /></label><label>{t("Роль", "Rol", "Role")}<select name="role">{["viewer", "analyst", "rule_editor", "administrator", "disabled"].map(role => <option key={role}>{role}</option>)}</select></label></>}
      {action.name === "rollback" && <label>Incident ID<input name="incident_id" required defaultValue={action.item?.rollback_request?.incident_id} /></label>}
      <label>{t("Причина", "Sabab", "Reason")}<textarea name="reason" required minLength={3} maxLength={2000} rows={3} placeholder={t("Что исправляем и почему?", "Nima va nega tuzatiladi?", "What needs to change, and why?")} /></label>
      {session?.mfa_required_for_mutations && <label>{t("Код аутентификатора", "Autentifikator kodi", "Authenticator code")}<input name="otp" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required autoComplete="one-time-code" placeholder="000000" /><small>{t("Для действий требуется двухфакторная проверка.", "Amallar uchun ikki bosqichli tekshiruv kerak.", "Changes require two-factor verification.")}</small></label>}
      {notice && <div className="control-error" role="alert">{notice}</div>}
      <div className="control-detail-actions"><button type="button" className="control-button" disabled={busy} onClick={closeAction}>{t("Отмена", "Bekor qilish", "Cancel")}</button><button className="control-button primary" disabled={busy}>{busy ? t("Выполняется…", "Bajarilmoqda…", "Submitting…") : t("Подтвердить", "Tasdiqlash", "Confirm")}</button></div>
    </form></DetailDialog>}
  </div>;
}

function RuleFields({ category, config, title, t }) {
  const [kind, setKind] = useState(category);
  const [value, setValue] = useState(JSON.stringify(config || DEFAULT_RULES[category], null, 2));
  return <><label>{t("Название", "Nomi", "Title")}<input name="title" required defaultValue={title} /></label><label>{t("Тип правила", "Qoida turi", "Rule type")}<select name="category" value={kind} onChange={e => { setKind(e.target.value); setValue(JSON.stringify(DEFAULT_RULES[e.target.value], null, 2)); }}>{Object.keys(DEFAULT_RULES).map(k => <option key={k}>{k}</option>)}</select></label><label>{t("Правило и контрольные примеры", "Qoida va nazorat misollari", "Rule & regression cases")}<textarea name="config" className="control-code-input" rows={16} value={value} onChange={e => setValue(e.target.value)} required spellCheck={false} /></label><p className="control-muted">{t("Только декларативные правила. Исходные числа и опубликованные версии не редактируются.", "Faqat deklarativ qoidalar. Asl raqamlar va nashrlar tahrirlanmaydi.", "Declarative rules only. Source values and published versions cannot be edited.")}</p></>;
}
