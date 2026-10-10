import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon, IconSprite } from "./icons.jsx";
import { NAVIGATION, LEGACY, COLUMNS, FIELD_LABELS } from "./controlConfig.js";
import "./admin.css";
import "./control.css";

const LegacyPanel = React.lazy(() => import("./AdminPanel.jsx"));
const BASE = "/api/admin/control";
const langIndex = language => ({ ru: 0, uz: 1, en: 2 }[language] ?? 0);
const textValue = value => value === null || value === undefined || value === "" ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
const fieldLabel = (key, t) => FIELD_LABELS[key] ? t(...FIELD_LABELS[key]) : key.replaceAll("_", " ");

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
    return typeof item[key] === "boolean" ? (item[key] ? t("Да", "Ha", "Yes") : t("Нет", "Yo‘q", "No")) : textValue(item[key]);
  };
  return <dl className="control-key-values">{fields.filter(key => item[key] !== undefined).map(key => <React.Fragment key={key}>
    <dt>{fieldLabel(key, t)}</dt><dd>{displayValue(key)}</dd>
  </React.Fragment>)}</dl>;
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
  const [detailError, setDetailError] = useState("");
  const [history, setHistory] = useState(null);
  const [action, setAction] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [hiddenColumns, setHiddenColumns] = useState([]);
  const [savedViews, setSavedViews] = useState([]);
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem(`admin-sidebar:${user?.id || "user"}`) === "collapsed"; } catch { return false; } });
  const params = useMemo(() => new URLSearchParams(query), [query]);
  const collection = section;
  const listQuery = useMemo(() => {
    const filters = new URLSearchParams(query);
    for (const key of ["object", "sheet", "page", "cell", "line", "row"]) filters.delete(key);
    return filters.toString();
  }, [query, section]);
  const selected = params.get("object");
  const isLegacy = LEGACY.includes(section) || section === "system" || section === "overview";
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
    let live = true;
    read("/session").then(result => { if (live) setSession(result); }).catch(exc => { if (live) setError(exc.message); });
    return () => { live = false; };
  }, [read, refresh, user?.id, user?.admin_role]);
  useEffect(() => {
    if (!session || isLegacy) return;
    const controller = new AbortController();
    setLoading(true); setError("");
    read(`/${collection}?${listQuery}`, { signal: controller.signal })
      .then(result => { setData(result); setLoading(false); }).catch(exc => { if (exc.name !== "AbortError") { setError(exc.message); setLoading(false); } });
    return () => controller.abort();
  }, [section, collection, listQuery, read, refresh, session, isLegacy]);
  useEffect(() => {
    if (!selected || isLegacy) { setDetail(null); return; }
    const controller = new AbortController();
    setDetail(null); setHistory(null); setDetailError("");
    if (collection === "audit") { setDetail(data?.items?.find(r => r.id === selected) || null); return; }
    read(`/${collection}/${encodeURIComponent(selected)}`, { signal: controller.signal }).then(result => setDetail(result.item))
      .catch(exc => { if (exc.name !== "AbortError") setDetailError(exc.message); });
    return () => controller.abort();
  }, [selected, collection, read, refresh, isLegacy, data]);
  const savedKey = `admin-views:${user?.id}:${session?.environment}:${section}`;
  useEffect(() => { try { setSavedViews(JSON.parse(localStorage.getItem(savedKey) || "[]")); } catch { setSavedViews([]); } }, [savedKey]);

  const navigate = useCallback((nextSection, filters = {}) => {
    const search = new URLSearchParams(filters).toString();
    const path = nextSection === "overview" ? "/admin" : `/admin/${nextSection}`;
    window.history.pushState({ view: "admin" }, "", path + (search ? "?" + search : ""));
    setQuery(search ? "?" + search : "");
    onSectionChange(nextSection);
    setNotice("");
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
    if (action.name === "grant") { entity = form.get("email"); input.role = form.get("role"); }
    setBusy(true); setNotice("");
    try {
      const result = await read(`/${action.collection}/${encodeURIComponent(entity)}/${action.name}`, { method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": action.key, "X-Admin-OTP": String(form.get("otp") || "") }, body: JSON.stringify(input) });
      setAction(null); setRefresh(n => n + 1);
      setNotice(t("Действие сохранено в журнале аудита.", "Amal audit jurnalida saqlandi.", "The action was recorded in the audit trail."));
    } catch (exc) { setNotice(exc.message); } finally { setBusy(false); }
  };
  const exportRows = async format => {
    try {
      const p = new URLSearchParams(query); p.delete("cursor"); p.delete("object"); p.set("format", format);
      const response = await apiFetch(`${BASE}/${collection}/export?${p}`);
      if (!response.ok) { const error = await response.json(); throw new Error(error.error?.message || "Export failed"); }
      const url = URL.createObjectURL(await response.blob()); const link = document.createElement("a");
      link.href = url; link.download = `admin-${collection}.${format}`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (exc) { setError(exc.message); }
  };
  const allNav = NAVIGATION.flatMap(g => g.items);
  const title = allNav.find(n => n[0] === section)?.[li + 2] || t("Продуктовая аналитика", "Mahsulot tahlili", "Product analytics");
  const columns = COLUMNS[collection] || ["title", "status"];
  const displayColumns = columns.filter(c => !hiddenColumns.includes(c));
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
      <header className="control-topbar"><span className={`control-environment ${session?.environment === "production" ? "production" : ""}`}><i />{session?.environment || "…"}</span><div className="control-actor"><span>{session?.actor?.email || user?.email}</span><small>{session?.actor?.role || "—"}</small></div></header>
      <main className="control-main"><div className="control-page-head"><div><span className="control-eyebrow">{t("Администрирование", "Boshqaruv", "Administration")} / {t("Рабочая область", "Ish maydoni", "Workspace")}</span><h1>{title}</h1><p>{t("От источника до публикации — с проверкой каждого шага.", "Manbadan nashrgacha — har bir bosqich tekshiriladi.", "From source to publication, with every step accounted for.")}</p></div><div className="control-head-actions"><button className="control-button" onClick={() => setRefresh(n => n + 1)}><Icon name="refresh" />{t("Обновить", "Yangilash", "Refresh")}</button>
        {section === "access" && actionButton("grant", t("Назначить роль", "Rol berish", "Assign role"), "access", null, {}, "access")}
      </div></div>
      {notice && <div className="control-notice" role="status">{notice}</div>}
      {error && <div className="control-error" role="alert"><Icon name="alert" />{error}<button onClick={() => setRefresh(n => n + 1)}>{t("Повторить", "Takrorlash", "Retry")}</button></div>}
      {isLegacy ? <><Suspense fallback={<Loading t={t} />}><LegacyPanel apiFetch={apiFetch} language={language} section={section === "product-overview" ? "overview" : section} onSectionChange={navigate} /></Suspense></>
        : loading ? <Loading t={t} /> : <>
          <section className="control-card control-registry">
            <form className="control-filters" onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); updateFilters({ q: f.get("q"), status: f.get("status"), object: "" }); }} key={`${section}:${listQuery}`}>
              <label>{t("Поиск", "Qidiruv", "Search")}<input name="q" defaultValue={params.get("q") || ""} placeholder={t("По всему реестру", "Barcha yozuvlar", "Search all records")} /></label>
              <label>{t("Статус", "Holat", "Status")}<select name="status" defaultValue={params.get("status") || ""}><option value="">{t("Все статусы", "Barcha holatlar", "All statuses")}</option>{statusOptions.map(status => <option key={status}>{status}</option>)}</select></label>
              <button type="submit" className="control-button primary">{t("Применить", "Qo‘llash", "Apply filters")}</button>
            </form>
            <div className="control-table-tools"><span><strong>{data?.total ?? 0}</strong> {t("записей", "yozuv", "records")} <span className="control-muted">· {t("фильтрация на сервере", "serverda saralash", "filtered on the server")}</span></span><div>
              <button onClick={() => updateFilters({ q: "", status: "", cursor: "", object: "" })}>{t("Сбросить", "Tozalash", "Reset")}</button>
              <details><summary>{t("Столбцы", "Ustunlar", "Columns")}</summary><div className="control-popover">{columns.map(col => <label key={col}><input type="checkbox" checked={!hiddenColumns.includes(col)} onChange={() => setHiddenColumns(old => old.includes(col) ? old.filter(c => c !== col) : [...old, col])} />{fieldLabel(col, t)}</label>)}</div></details>
              <details><summary>{t("Представления", "Ko‘rinishlar", "Saved views")}</summary><div className="control-popover">{savedViews.map(view => <button key={view.name} onClick={() => navigate(section, view.filters)}>{view.name}</button>)}<form onSubmit={event => { event.preventDefault(); const name = new FormData(event.currentTarget).get("name").trim(); if (!name) return; const views = [...savedViews.filter(v => v.name !== name), { name, filters: Object.fromEntries(params) }].slice(-15); setSavedViews(views); try { localStorage.setItem(savedKey, JSON.stringify(views)); } catch { setNotice("Local preferences are unavailable."); } }}><input name="name" aria-label={t("Название представления", "Ko‘rinish nomi", "View name")} required placeholder={t("Название", "Nomi", "View name")} /><button>{t("Сохранить", "Saqlash", "Save")}</button></form></div></details>
              {can("export") && <><button onClick={() => exportRows("csv")}>CSV ↓</button><button onClick={() => exportRows("json")}>JSON ↓</button></>}
            </div></div>
            {data?.items?.length ? <div className="control-table-scroll"><table><thead><tr>{displayColumns.map(col => <th key={col} scope="col"><button disabled={!["ticker", "status", "standard", "period", "severity", "source", "category", "updated_at", "id", "created_at", "actor", "action"].includes(col)} onClick={() => updateFilters({ sort: col, direction: params.get("sort") === col && params.get("direction") === "asc" ? "desc" : "asc" })}>{fieldLabel(col, t)}{params.get("sort") === col ? params.get("direction") === "asc" ? " ↑" : " ↓" : ""}</button></th>)}</tr></thead><tbody>{data.items.map(item => <tr key={item.id} className={selected === item.id ? "selected" : ""}>{displayColumns.map((col, i) => <td key={col}>{i === 0 ? <button className="control-row-link" onClick={() => updateFilters({ object: item.id })}>{textValue(item[col])}<Icon name="external" /></button> : ["status", "result", "severity"].includes(col) ? <StatusBadge value={item[col]} /> : typeof item[col] === "boolean" ? <span className={`control-bool ${item[col] ? "yes" : ""}`}>{item[col] ? t("Да", "Ha", "Yes") : "—"}</span> : <span title={textValue(item[col])}>{textValue(item[col])}</span>}</td>)}</tr>)}</tbody></table></div>
              : <div className="control-empty"><Icon name="search" /><h3>{t("Нет записей для этой выборки", "Tanlov bo‘yicha yozuvlar yo‘q", "No records in this view")}</h3><p>{t("Измените фильтры.", "Filtrlarni o‘zgartiring.", "Adjust the filters.")}</p></div>}
            <footer className="control-pagination"><span>{data?.items?.length || 0} / {data?.total || 0}</span><div><button className="control-button" disabled={!params.get("cursor")} onClick={() => updateFilters({ cursor: "" })}>{t("Первая страница", "Birinchi sahifa", "First page")}</button><button className="control-button" disabled={!data?.next_cursor} onClick={() => updateFilters({ cursor: data.next_cursor, object: "" })}>{t("Следующая", "Keyingi", "Next page")} →</button></div></footer>
          </section>
        </>}
      <footer className="control-footnote"><Icon name="lock" />{t("Исходные данные неизменяемы.", "Asl ma’lumotlar o‘zgarmaydi.", "Source data stays immutable.")}</footer>
      </main>
    </div>
    {selected && !isLegacy && <DetailDialog title={detail?.ticker ? `${detail.ticker} · ${detail.metric_code || detail.period || title}` : title} onClose={closeDetail} t={t}>
      {detailError ? <div className="control-error" role="alert">{detailError}</div> : !detail ? <Loading t={t} /> : <>
        <div className="control-detail-meta"><StatusBadge value={detail.status || detail.result} /><span>v{detail.version || 1}</span><code>{detail.id}</code></div>
        {detail.blockers?.length > 0 && <div className="control-blockers"><strong>{t("Блокеры", "Bloklovchilar", "Blockers")}</strong>{detail.blockers.map(code => <p key={code}><Icon name="alert" />{code}</p>)}</div>}
        <div className="control-detail-actions">
          {collection !== "audit" && <button className="control-button" onClick={() => read(`/${collection}/${encodeURIComponent(detail.id)}/history`).then(result => setHistory(result.items)).catch(exc => setDetailError(exc.message))}>{t("История версий", "Versiyalar tarixi", "Version history")}</button>}
        </div>
        <KeyValues item={detail} fields={Object.keys(detail).filter(key => !["id", "version", "headline", "paragraphs", "inputs", "facts", "config", "previous_config", "tests", "impact", "expression", "formula"].includes(key) && typeof detail[key] !== "object")} t={t} />
        {detail.comments?.map((comment, i) => <div className="control-comment" key={i}><strong>{comment.actor}</strong><small>{comment.at}</small><p>{comment.text}</p></div>)}
        {history && <section><h3>{t("История версий", "Versiyalar tarixi", "Version history")}</h3>{history.map(revision => <details className="control-history" key={revision.version}><summary>v{revision.version} · {revision.updated_at} · {revision.status}</summary><pre>{JSON.stringify(revision, null, 2)}</pre></details>)}</section>}
        <details className="control-history"><summary>{t("Все сохранённые поля", "Barcha saqlangan maydonlar", "All recorded fields")}</summary><pre>{JSON.stringify(detail, null, 2)}</pre></details>
      </>}
    </DetailDialog>}
    {action && <DetailDialog title={t("Подтвердите действие", "Amalni tasdiqlang", "Review this action")} onClose={closeAction} t={t}><form className="control-action-form" onSubmit={submit}>
      <p><strong>{action.collection} / {action.name}</strong></p><p className="control-muted">{action.item?.id || t("Новый объект", "Yangi obyekt", "New object")} · {session?.environment}</p>
      {action.name === "grant" && <><label>Email<input name="email" type="email" required defaultValue={action.item?.email} /></label><label>{t("Роль", "Rol", "Role")}<select name="role">{["viewer", "analyst", "rule_editor", "administrator", "disabled"].map(role => <option key={role}>{role}</option>)}</select></label></>}
      <label>{t("Причина", "Sabab", "Reason")}<textarea name="reason" required minLength={3} maxLength={2000} rows={3} placeholder={t("Что исправляем и почему?", "Nima va nega tuzatiladi?", "What needs to change, and why?")} /></label>
      {session?.mfa_required_for_mutations && <label>{t("Код аутентификатора", "Autentifikator kodi", "Authenticator code")}<input name="otp" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required autoComplete="one-time-code" placeholder="000000" /><small>{t("Для действий требуется двухфакторная проверка.", "Amallar uchun ikki bosqichli tekshiruv kerak.", "Changes require two-factor verification.")}</small></label>}
      {notice && <div className="control-error" role="alert">{notice}</div>}
      <div className="control-detail-actions"><button type="button" className="control-button" disabled={busy} onClick={closeAction}>{t("Отмена", "Bekor qilish", "Cancel")}</button><button className="control-button primary" disabled={busy}>{busy ? t("Выполняется…", "Bajarilmoqda…", "Submitting…") : t("Подтвердить", "Tasdiqlash", "Confirm")}</button></div>
    </form></DetailDialog>}
  </div>;
}

