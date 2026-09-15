/**
 * AdminPanel.jsx — the administrative page.
 *
 * A page of the site, not an application beside it. The topbar, brand, language
 * and theme controls stay where they always are; this renders inside the same
 * content column as Рынок or Новости, with the sections as tabs.
 *
 * The panel has two halves. The PRODUCT half — Обзор, Аудитория, Вовлечённость,
 * AI-анализ, Пользователи — reads the visit record (web_events, filled by the
 * /api/track beacon) and answers "how many people opened the site and what did
 * they do". The OPERATIONS half — the collectors, the audit queue, the intake
 * and the TTM ledger — is the old console, collapsed into one «Система» tab:
 * one place to look when a cron card goes red, not seven top-level tabs.
 *
 * Authentication is the signed-in admin's own Bearer token — the machine
 * X-Admin-Secret never reaches the browser and cannot open these product/user
 * endpoints. The server derives the actor from that Bearer session.
 *
 * Nothing here invents a number. Where the backend cannot measure something the
 * cell renders «—» — zero and unknown are different facts — and the collectors
 * section says «последняя запись» rather than «прогон», because from this
 * process a collector that died and one that had nothing to write look identical.
 */
import React from "react";
import { Icon, IconSprite } from "./icons.jsx";
import RailwayPanel from "./RailwayPanel.jsx";
import AnalysisMonitor from "./AnalysisMonitor.jsx";
import "./admin.css";

const { useCallback, useEffect, useMemo, useRef, useState } = React;

/* ── i18n ─────────────────────────────────────────────────────────────────── */
const lang3 = (language) => (language === "uz" ? 1 : language === "en" ? 2 : 0);
const useT = (language) => {
  const i = lang3(language);
  return useCallback((ru, uz, en) => [ru, uz, en][i] ?? ru, [i]);
};

/* ── formatting ───────────────────────────────────────────────────────────── */
const DASH = "—";

function fmtInt(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return DASH;
  return Number(value).toLocaleString("ru-RU");
}

/** A multiple, printed to two places. Rounding happens on OUTPUT only — the
 *  value itself is never touched. */
function fmtNum(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return DASH;
  return Number(value).toLocaleString("ru-RU",
    { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** A 0..1 share as a percentage. */
function fmtShare(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return DASH;
  return `${(Number(value) * 100).toLocaleString("ru-RU",
    { minimumFractionDigits: digits, maximumFractionDigits: Math.max(digits, 1) })}%`;
}

/** LLM spend is billed in dollars; printing it in anything else would repeat
 *  the 8.9× mistake this screen exists to prevent. */
function fmtUsd(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return DASH;
  return `$${Number(value).toLocaleString("en-US",
    { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function fmtDuration(seconds, t) {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return DASH;
  const total = Math.round(Number(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (!minutes) return t(`${rest} с`, `${rest} s`, `${rest}s`);
  return t(`${minutes} мин ${rest} с`, `${minutes} min ${rest} s`, `${minutes}m ${rest}s`);
}

function fmtStamp(value, { withTime = true } = {}) {
  if (!value) return DASH;
  const text = String(value).trim().replace(" ", "T");
  const date = new Date(/[Z+]|\d\d:\d\d$/.test(text) ? text : `${text}Z`);
  if (Number.isNaN(date.getTime())) return String(value);
  const opts = withTime
    ? { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }
    : { day: "2-digit", month: "2-digit", year: "numeric" };
  return date.toLocaleString("ru-RU", opts).replace(",", " ·");
}

function fmtAge(hours, t) {
  if (hours === null || hours === undefined) return DASH;
  if (hours < 1) return t("меньше часа назад", "bir soatdan kam", "less than an hour ago");
  if (hours < 48) return t(`${Math.round(hours)} ч назад`, `${Math.round(hours)} soat oldin`, `${Math.round(hours)} h ago`);
  const days = Math.round(hours / 24);
  return t(`${days} дн. назад`, `${days} kun oldin`, `${days} d ago`);
}

/** Day label for daily charts: "12.08". */
function fmtDay(iso) {
  const parts = String(iso || "").split("-");
  return parts.length === 3 ? `${parts[2]}.${parts[1]}` : String(iso || "");
}

function companyDraftOf(item) {
  if (!item) return null;
  return {
    ticker: String(item.ticker || "").toUpperCase(),
    company_name: item.company_name || "",
    org_id: item.org_id || "",
    isin: item.isin || "",
    sector: item.sector || "other",
    logo_url: item.logo_url || "",
    security_type: item.security_type || "stock",
    share_type: item.share_type || "",
    review_note: item.review_note || "",
    warnings: item.warnings || [],
    can_approve: item.can_approve !== false && Boolean(item.org_id),
    status: item.status || "pending",
    sync_status: item.sync_status || "",
    catalog_visible: item.catalog_visible !== 0,
  };
}

const SEVERITY_TONE = { blocking: "err", warning: "warn", info: "ok" };

/* ── sections ─────────────────────────────────────────────────────────────── */
/** The product half is the tab bar; the operations console lives entire under
 *  «Система». Old deep links (/admin/streams, /admin/findings…) keep working —
 *  those keys simply select the Система tab with the right sub-section. */
const SECTIONS = [
  { key: "overview", icon: "dashboard",
    title: ["Обзор", "Umumiy", "Overview"] },
  { key: "audience", icon: "up",
    title: ["Аудитория", "Auditoriya", "Audience"] },
  { key: "engagement", icon: "chart",
    title: ["Вовлечённость", "Faollik", "Engagement"] },
  { key: "analysis", icon: "search",
    title: ["AI-анализ", "AI-tahlil", "AI analysis"] },
  { key: "users", icon: "users",
    title: ["Пользователи", "Foydalanuvchilar", "Users"] },
  { key: "feedback", icon: "news",
    title: ["Обратная связь", "Fikr-mulohaza", "Feedback"] },
  { key: "system", icon: "sliders",
    title: ["Система", "Tizim", "System"] },
];

/** Sub-tabs of «Система». The key "system" itself is the data overview. */
const SYSTEM_SECTIONS = [
  { key: "system", title: ["Данные", "Ma'lumotlar", "Data"] },
  { key: "railway", title: ["Railway", "Railway", "Railway"] },
  { key: "companies", title: ["Компании", "Kompaniyalar", "Companies"] },
  { key: "streams", title: ["Сборщики", "Yig'uvchilar", "Collectors"] },
  { key: "findings", title: ["Аудит", "Audit", "Audit"] },
  { key: "intake", title: ["Отчёты", "Hisobotlar", "Statements"] },
  { key: "issuer", title: ["Эмитент", "Emitent", "Issuer"] },
  { key: "rules", title: ["Правила", "Qoidalar", "Rules"] },
  { key: "source", title: ["Источник", "Manba", "Source"] },
  { key: "quality", title: ["Качество данных", "Ma'lumotlar sifati", "Data quality"] },
];

const SYSTEM_KEYS = SYSTEM_SECTIONS.map((s) => s.key);

export const ADMIN_SECTION_KEYS = [
  ...SECTIONS.map((s) => s.key),
  ...SYSTEM_KEYS.filter((k) => k !== "system"),
];

/* ── small pieces ─────────────────────────────────────────────────────────── */

function Stat({ label, value, warn, badge, badgeIcon, line1, line2 }) {
  return (
    <div className="panel admin-stat">
      <div className="admin-stat-top">
        <span className="admin-stat-label">{label}</span>
        {badge ? (
          <span className="admin-stat-badge">
            {badgeIcon ? <Icon name={badgeIcon} /> : null}{badge}
          </span>
        ) : null}
      </div>
      <div className={`admin-stat-value${warn ? " warn" : ""}`}>{value}</div>
      {line1 ? <div className="admin-stat-l1">{line1}</div> : null}
      {line2 ? <div className="admin-stat-l2">{line2}</div> : null}
    </div>
  );
}

/** «+12% к прошлой неделе» — or nothing, when the previous period is unknown
 *  or empty. A change against zero is not a percentage. */
function deltaBadge(now, prev) {
  if (now === null || now === undefined || !prev) return null;
  const change = (now - prev) / prev;
  const text = `${change >= 0 ? "+" : ""}${(change * 100).toFixed(Math.abs(change) < 0.1 ? 1 : 0)}%`;
  return { text, icon: change >= 0 ? "up" : "down" };
}

function Severity({ value, t }) {
  const label = value === "blocking"
    ? t("Блокирующая", "Bloklovchi", "Blocking")
    : value === "warning"
      ? t("Предупреждение", "Ogohlantirish", "Warning")
      : t("Информация", "Ma'lumot", "Info");
  return (
    <span className="admin-pill">
      <span className={`admin-dot ${SEVERITY_TONE[value] || ""}`} />{label}
    </span>
  );
}

/** Blocking findings per run, oldest on the left. Bare divs, not a chart
 *  library: fourteen bars do not justify a dependency. */
function RunHistory({ runs, t }) {
  const peak = Math.max(1, ...runs.map((r) => Number(r.blocking) || 0));
  return (
    <div className="admin-bars">
      {runs.map((run, index) => {
        const value = Number(run.blocking) || 0;
        const last = index === runs.length - 1;
        const label = fmtStamp(run.finished_at || run.started_at, { withTime: false }).slice(0, 5);
        const cls = ["bar", last ? "now" : "", run.status === "failed" ? "failed" : ""]
          .filter(Boolean).join(" ");
        return (
          <div
            key={run.id || index}
            className={cls}
            style={{ height: `${Math.max(4, Math.round((value / peak) * 100))}%` }}
            title={`${label} · ${value} ${t("блокирующих", "bloklovchi", "blocking")}`}
          >
            {(last || index === 0 || index === Math.floor(runs.length / 2)) ? <span>{label}</span> : null}
          </div>
        );
      })}
    </div>
  );
}

/** A daily series as bars, oldest left. Same bare-div school as RunHistory. */
function DailyBars({ data, valueKey, titleFn }) {
  const rows = data || [];
  if (!rows.length) return null;
  const peak = Math.max(1, ...rows.map((r) => Number(r[valueKey]) || 0));
  const step = Math.max(1, Math.ceil(rows.length / 7));
  return (
    <div className="admin-bars">
      {rows.map((row, index) => {
        const value = Number(row[valueKey]) || 0;
        const last = index === rows.length - 1;
        return (
          <div
            key={row.day || index}
            className={`bar${last ? " now" : ""}`}
            style={{ height: `${Math.max(3, Math.round((value / peak) * 100))}%` }}
            title={titleFn ? titleFn(row) : `${fmtDay(row.day)} · ${fmtInt(value)}`}
          >
            {(last || index % step === 0) ? <span>{fmtDay(row.day)}</span> : null}
          </div>
        );
      })}
    </div>
  );
}

/** A ranked breakdown as horizontal bars: the panel's workhorse for "top N of
 *  something". The bar is proportion; the number is the fact. */
function HBarList({ rows, nameFn, valueFn, detailFn, onClickRow }) {
  const items = rows || [];
  if (!items.length) return null;
  const peak = Math.max(1, ...items.map((r) => Number(valueFn(r)) || 0));
  return (
    <div className="admin-hbars">
      {items.map((row, index) => {
        const value = Number(valueFn(row)) || 0;
        const name = nameFn(row);
        return (
          <div key={`${name}-${index}`} className="admin-hbar">
            <span className="admin-hbar-name">
              {onClickRow
                ? <button type="button" className="admin-link" onClick={() => onClickRow(row)}>{name}</button>
                : name}
              {detailFn ? <span className="admin-hbar-detail">{detailFn(row)}</span> : null}
            </span>
            <span className="admin-hbar-track">
              <span className="admin-hbar-fill" style={{ width: `${Math.max(2, (value / peak) * 100)}%` }} />
            </span>
            <span className="admin-hbar-val">{fmtInt(value)}</span>
          </div>
        );
      })}
    </div>
  );
}

/** The activation funnel: absolute counts with the drop between steps. */
function Funnel({ steps, labels }) {
  const rows = steps || [];
  const first = rows.length ? Number(rows[0].count) : 0;
  return (
    <div className="admin-funnel">
      {rows.map((step, index) => {
        const value = step.count === null || step.count === undefined ? null : Number(step.count);
        const width = first && value !== null ? Math.max(2, (value / first) * 100) : 2;
        const prev = index > 0 ? rows[index - 1].count : null;
        const share = prev && value !== null && Number(prev) > 0 ? value / Number(prev) : null;
        return (
          <div key={step.key} className="admin-funnel-step">
            <span className="admin-funnel-label">{labels[step.key] || step.key}</span>
            <span className="admin-funnel-track">
              <span className="admin-funnel-fill" style={{ width: `${width}%` }} />
            </span>
            <span className="admin-funnel-val">
              {fmtInt(value)}
              {share !== null && index > 0 ? <em>{fmtShare(share)}</em> : null}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function RangePicker({ value, onChange, t }) {
  return (
    <div className="admin-seg">
      {[7, 30, 90].map((days) => (
        <button key={days} type="button" aria-selected={value === days}
                onClick={() => onChange(days)}>
          {t(`${days} дней`, `${days} kun`, `${days} days`)}
        </button>
      ))}
    </div>
  );
}

function Skeleton({ rows = 3 }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="admin-skel" style={{ height: i === 0 ? 96 : 58 }} />
      ))}
    </div>
  );
}

/** The one empty state the product half shares: the beacon has not filled the
 *  record yet. Distinct from an error — the plumbing works, the data is young. */
function NoTraffic({ t }) {
  return (
    <div className="admin-empty">
      <b>{t("Записей о посещениях пока нет", "Tashriflar yozuvi hali yo'q", "No visit records yet")}</b>
      {t("Счётчик начал писать с этого развёртывания; цифры появятся, как только на сайт кто-то зайдёт.",
         "Hisoblagich shu joylashuvdan boshlab yozadi.",
         "The counter started writing with this deployment; numbers appear as soon as someone visits.")}
    </div>
  );
}

/* ── findings table (shared by Система → Данные and Аудит) ────────────────── */

function FindingsTable({ items, rules, t, selected, onToggle, onAccept, busy }) {
  const ruleTitle = useCallback((code) => {
    const rule = rules.find((r) => r.code === code);
    return rule ? rule.title : "";
  }, [rules]);

  if (!items.length) {
    return (
      <div className="admin-empty">
        <b>{t("Ничего не ждёт решения", "Hech narsa kutmayapti", "Nothing is waiting")}</b>
        {t("Все открытые находки разобраны.", "Barcha topilmalar ko'rib chiqilgan.",
           "Every open finding has been dealt with.")}
      </div>
    );
  }

  return (
    <div className="admin-scroll">
      <table>
        <thead>
          <tr>
            <th style={{ width: 42 }} />
            <th>{t("Правило", "Qoida", "Rule")}</th>
            <th style={{ width: 156 }}>{t("Уровень", "Daraja", "Severity")}</th>
            <th style={{ width: 96 }}>{t("Бумага", "Qog'oz", "Security")}</th>
            <th style={{ width: 116 }}>{t("Держится", "Ushlanib turibdi", "Seen")}</th>
            <th className="r" style={{ width: 118 }}>{t("Открыта", "Ochilgan", "Opened")}</th>
            <th style={{ width: 46 }} />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const checked = selected.has(item.id);
            return (
              <tr key={item.id}>
                <td>
                  <button
                    type="button"
                    className="admin-check"
                    role="checkbox"
                    aria-checked={checked}
                    aria-label={t("Выбрать находку", "Topilmani tanlash", "Select finding")}
                    onClick={() => onToggle(item.id)}
                  />
                </td>
                <td>
                  <div className="admin-rule"><code>{item.rule_code}</code>{ruleTitle(item.rule_code)}</div>
                  {item.message ? <div className="admin-sub">{item.message}</div> : null}
                </td>
                <td><Severity value={item.severity} t={t} /></td>
                <td className="admin-num">{item.ticker || DASH}</td>
                <td className="admin-num">
                  {item.seen_count
                    ? t(`${item.seen_count} прогон(ов)`, `${item.seen_count} marta`, `${item.seen_count} runs`)
                    : DASH}
                </td>
                <td className="r admin-num">{fmtStamp(item.first_seen, { withTime: false })}</td>
                <td>
                  <button
                    type="button"
                    className="admin-row-act"
                    title={t("Принять как известное", "Ma'lum deb qabul qilish", "Accept as known")}
                    disabled={busy}
                    onClick={() => onAccept([item.id])}
                  >
                    <Icon name="check" />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ── page ─────────────────────────────────────────────────────────────────── */

export default function AdminPanel({
  apiFetch, language = "ru", section = "overview", onSectionChange,
}) {
  const t = useT(language);
  const isSystem = SYSTEM_KEYS.includes(section);

  /* product half */
  const [metrics, setMetrics] = useState(null);
  const [audienceData, setAudienceData] = useState(null);
  const [engagementData, setEngagementData] = useState(null);
  const [analysisData, setAnalysisData] = useState(null);
  const [rangeDays, setRangeDays] = useState(30);
  const [usersData, setUsersData] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [adminLog, setAdminLog] = useState(null);
  const [usersQuery, setUsersQuery] = useState("");
  const [usersOnly, setUsersOnly] = useState("");
  const [userDetail, setUserDetail] = useState(null);
  const [confirmAction, setConfirmAction] = useState(null); // {id, action}
  const [feedbackData, setFeedbackData] = useState(null);
  const [feedbackFilter, setFeedbackFilter] = useState("");
  const [feedbackBusy, setFeedbackBusy] = useState(0);

  /* operations half */
  const [overview, setOverview] = useState(null);
  const [rules, setRules] = useState([]);
  const [findings, setFindings] = useState([]);
  const [filters, setFilters] = useState({ severity: "blocking", status: "new" });
  const [intake, setIntake] = useState(null);
  const [intakeState, setIntakeState] = useState("ineligible");
  const [ledger, setLedger] = useState(null);
  const [ledgerTicker, setLedgerTicker] = useState("");
  const [ruleBook, setRuleBook] = useState(null);
  const [source, setSource] = useState(null);
  const [companyImports, setCompanyImports] = useState(null);
  const [companyLookup, setCompanyLookup] = useState("");
  const [companyFilter, setCompanyFilter] = useState("pending");
  const [companyDraft, setCompanyDraft] = useState(null);
  const [companyNotice, setCompanyNotice] = useState("");
  const [companyBusy, setCompanyBusy] = useState("");
  const [quality, setQuality] = useState(null);
  const [qualityCorrections, setQualityCorrections] = useState(null);
  const [qualityBusy, setQualityBusy] = useState("");
  const [qualityDraft, setQualityDraft] = useState(null);
  const [qualityTicker, setQualityTicker] = useState("");
  const [qualitySelectedTicker, setQualitySelectedTicker] = useState("");
  const [qualitySuggestions, setQualitySuggestions] = useState([]);
  const [qualitySuggestionsOpen, setQualitySuggestionsOpen] = useState(false);
  const [qualitySearchLoading, setQualitySearchLoading] = useState(false);
  const [qualityNotice, setQualityNotice] = useState("");
  const [selected, setSelected] = useState(() => new Set());

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);

  // React Strict Mode replays effect setup/cleanup once in development. Reset
  // the guard in setup so that replay does not leave this mounted panel
  // permanently "dead" and discard every API response.
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const readJson = useCallback(async (path, options) => {
    const res = await apiFetch(path, options);
    let data = null;
    try { data = await res.json(); } catch { /* a 500 may not be JSON */ }
    if (!res.ok) {
      const detail = (data && (data.detail || data.message)) || `HTTP ${res.status}`;
      throw new Error(res.status === 403
        ? t("Нужны права администратора", "Administrator huquqi kerak", "Admin access required")
        : String(detail));
    }
    return data || {};
  }, [apiFetch, t]);

  /* ── loads: product ─────────────────────────────────────────────────────── */
  const loadMetrics = useCallback(async () => {
    const data = await readJson("/api/admin/metrics/overview");
    if (alive.current) setMetrics(data);
  }, [readJson]);

  const loadAudience = useCallback(async (days) => {
    const data = await readJson(`/api/admin/metrics/audience?days=${days}`);
    if (alive.current) setAudienceData(data);
  }, [readJson]);

  const loadEngagement = useCallback(async (days) => {
    const data = await readJson(`/api/admin/metrics/engagement?days=${days}`);
    if (alive.current) setEngagementData(data);
  }, [readJson]);

  const loadAnalysis = useCallback(async (days) => {
    const data = await readJson(`/api/admin/metrics/analysis?days=${days}`);
    if (alive.current) setAnalysisData(data);
  }, [readJson]);

  const loadUsers = useCallback(async (query, only) => {
    const params = new URLSearchParams({ limit: "100" });
    if (query) params.set("query", query);
    if (only) params.set("only", only);
    const [list, fun, log] = await Promise.all([
      readJson(`/api/admin/users?${params}`),
      readJson("/api/admin/users/funnel?days=30"),
      readJson("/api/admin/audit-log?limit=30"),
    ]);
    if (alive.current) { setUsersData(list); setFunnel(fun); setAdminLog(log); }
  }, [readJson]);

  const loadFeedback = useCallback(async (status = feedbackFilter) => {
    const suffix = status ? `?status=${encodeURIComponent(status)}` : "";
    const data = await readJson(`/api/admin/feedback${suffix}`);
    if (alive.current) setFeedbackData(data);
  }, [feedbackFilter, readJson]);

  const updateFeedbackStatus = useCallback(async (id, status) => {
    setFeedbackBusy(id);
    setError("");
    try {
      await readJson(`/api/admin/feedback/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      await loadFeedback(feedbackFilter);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setFeedbackBusy(0);
    }
  }, [feedbackFilter, loadFeedback, readJson]);

  const openUser = useCallback(async (id) => {
    const data = await readJson(`/api/admin/users/${id}`);
    if (alive.current) setUserDetail(data);
  }, [readJson]);

  const runUserAction = useCallback(async (id, action) => {
    setBusy(true);
    setError("");
    try {
      await readJson(`/api/admin/users/${id}/action`, {
        method: "POST",
        body: JSON.stringify(action === "delete" ? { action, confirm: true } : { action }),
      });
      setConfirmAction(null);
      if (action === "delete") setUserDetail(null);
      else if (userDetail && userDetail.user && userDetail.user.id === id) await openUser(id);
      await loadUsers(usersQuery, usersOnly);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setBusy(false);
    }
  }, [readJson, loadUsers, openUser, usersQuery, usersOnly, userDetail]);

  /* ── loads: operations ──────────────────────────────────────────────────── */
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
    setIntakeState((s) => (s === "ineligible" && !data.ineligible ? "used" : s));
  }, [readJson]);

  const loadRuleBook = useCallback(async () => {
    const data = await readJson("/api/admin/rules");
    if (alive.current) setRuleBook(data);
  }, [readJson]);

  const loadSource = useCallback(async () => {
    const data = await readJson("/api/admin/source");
    if (alive.current) setSource(data);
  }, [readJson]);

  const loadQuality = useCallback(async () => {
    const [issues, corrections] = await Promise.all([
      readJson("/api/admin/data-quality/issues"),
      readJson("/api/admin/data-quality/corrections"),
    ]);
    if (alive.current) { setQuality(issues); setQualityCorrections(corrections); }
  }, [readJson]);

  const scanQualityCompany = useCallback(async (ticker) => {
    const normalized = String(ticker || "").trim().toUpperCase();
    if (!normalized) { setError(t("Введите тикер компании.", "Kompaniya tikerini kiriting.", "Enter a company ticker.")); return; }
    const busyKey = `analysis:${normalized}`;
    setQualityBusy(busyKey); setError("");
    try {
      await readJson(`/api/admin/data-quality/analysis/${encodeURIComponent(normalized)}/scan`, { method: "POST" });
      setQualityTicker(normalized);
      setQualitySelectedTicker(normalized);
      await loadQuality();
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  }, [loadQuality, readJson, t]);

  const refreshQualityCompanyReporting = useCallback(async (ticker) => {
    const normalized = String(ticker || "").trim().toUpperCase();
    if (!normalized) { setError(t("Выберите компанию.", "Kompaniyani tanlang.", "Choose a company.")); return; }
    const busyKey = `refresh:${normalized}`;
    setQualityBusy(busyKey); setQualityNotice(""); setError("");
    try {
      const data = await readJson(`/api/admin/data-quality/companies/${encodeURIComponent(normalized)}/refresh`, { method: "POST" });
      setQualityTicker(normalized);
      setQualitySelectedTicker(normalized);
      const period = data.latest_period || t("последний доступный период", "mavjud so'nggi davr", "the latest available period");
      setQualityNotice(t(
        `Официальные отчёты ${normalized} обновлены. Актуальный период: ${period}. Обновлено записей: ${data.financials_updated || 0}; закрыто проверок: ${data.resolved_issues || 0}.`,
        `${normalized} rasmiy hisobotlari yangilandi. Joriy davr: ${period}. Yangilangan yozuvlar: ${data.financials_updated || 0}; yopilgan tekshiruvlar: ${data.resolved_issues || 0}.`,
        `${normalized} official reports were refreshed. Current period: ${period}. Updated records: ${data.financials_updated || 0}; resolved checks: ${data.resolved_issues || 0}.`,
      ));
      await loadQuality();
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  }, [loadQuality, readJson, t]);

  // The queue may have no finding for a company yet, so the picker searches
  // the complete known-issuer catalog rather than only filtering open rows.
  useEffect(() => {
    const query = qualityTicker.trim();
    if (!query) {
      setQualitySuggestions([]);
      setQualitySuggestionsOpen(false);
      setQualitySearchLoading(false);
      return undefined;
    }
    let active = true;
    const timer = window.setTimeout(() => {
      setQualitySearchLoading(true);
      readJson(`/api/admin/companies/search?q=${encodeURIComponent(query)}&limit=12`)
        .then((data) => {
          if (!active) return;
          setQualitySuggestions(data.items || []);
          if (!qualitySelectedTicker) setQualitySuggestionsOpen(true);
        })
        .catch(() => { if (active) setQualitySuggestions([]); })
        .finally(() => { if (active) setQualitySearchLoading(false); });
    }, 180);
    return () => { active = false; window.clearTimeout(timer); };
  }, [qualityTicker, qualitySelectedTicker, readJson]);

  const submitQualityCorrection = useCallback(async (event) => {
    event.preventDefault();
    if (!qualityDraft) return;
    setQualityBusy("create"); setError("");
    try {
      const { suggestion, alternatives, evidenceMissing, ...correction } = qualityDraft;
      const data = await readJson("/api/admin/data-quality/corrections/apply", {
        method: "POST", body: JSON.stringify({
          ...correction,
          year: Number(correction.year), quarter: Number(correction.quarter || 0),
          value_thousands_uzs: Number(correction.value_thousands_uzs),
        }),
      });
      setQualityDraft(null);
      await loadQuality();
      return data;
    } catch (e) { setError(String(e.message || e)); return null; }
    finally { if (alive.current) setQualityBusy(""); }
  }, [loadQuality, qualityDraft, readJson]);

  const reviewQualityCorrection = useCallback(async (id, status) => {
    setQualityBusy(id); setError("");
    try {
      await readJson(`/api/admin/data-quality/corrections/${encodeURIComponent(id)}/review`, {
        method: "POST", body: JSON.stringify({ status }),
      });
      await loadQuality();
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  }, [loadQuality, readJson]);

  const autoApplyQualityIssue = useCallback(async (issue) => {
    const busyKey = `apply:${issue.id}`;
    setQualityBusy(busyKey); setError("");
    try {
      await readJson(`/api/admin/data-quality/issues/${encodeURIComponent(issue.id)}/apply`, { method: "POST" });
      await loadQuality();
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  }, [loadQuality, readJson]);

  const autoApplyUnitScale = useCallback(async (issue) => {
    const busyKey = `scale:${issue.id}`;
    setQualityBusy(busyKey); setError("");
    try {
      await readJson(`/api/admin/data-quality/issues/${encodeURIComponent(issue.id)}/apply-unit-scale`, { method: "POST" });
      await loadQuality();
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  }, [loadQuality, readJson]);

  const loadCompanyImports = useCallback(async (status = companyFilter) => {
    const suffix = status && status !== "all" ? `?status=${encodeURIComponent(status)}` : "";
    const data = await readJson(`/api/admin/companies${suffix}`);
    if (alive.current) setCompanyImports(data);
  }, [companyFilter, readJson]);

  const discoverCompanies = useCallback(async () => {
    setCompanyBusy("discover");
    setCompanyNotice("");
    setError("");
    try {
      const data = await readJson("/api/admin/companies/discover", { method: "POST" });
      if (alive.current) {
        setCompanyImports(companyFilter === "all" ? data : {
          ...data,
          items: (data.items || []).filter((item) => item.status === companyFilter),
        });
        setCompanyNotice(t(
          `Проверено бумаг: ${data.seen ?? data.discovered ?? 0}`,
          `Tekshirilgan qog'ozlar: ${data.seen ?? data.discovered ?? 0}`,
          `Securities checked: ${data.seen ?? data.discovered ?? 0}`,
        ));
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setCompanyBusy("");
    }
  }, [companyFilter, readJson, t]);

  const previewCompany = useCallback(async (ticker, refresh = true) => {
    const one = String(ticker || "").trim().toUpperCase();
    if (!one) return;
    setCompanyBusy(`preview:${one}`);
    setCompanyNotice("");
    setError("");
    try {
      const data = await readJson(
        `/api/admin/companies/${encodeURIComponent(one)}/preview?refresh=${refresh ? "true" : "false"}`,
      );
      if (alive.current) {
        setCompanyLookup(one);
        setCompanyDraft(companyDraftOf(data.company));
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setCompanyBusy("");
    }
  }, [readJson]);

  const fixIssuerMapping = useCallback(async (issue) => {
    const ticker = String(issue?.ticker || "").trim().toUpperCase();
    if (!ticker) return;
    const busyKey = `issuer:${issue.id}`;
    setQualityBusy(busyKey); setError("");
    try {
      onSectionChange?.("companies");
      await previewCompany(ticker, true);
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  }, [onSectionChange, previewCompany]);

  const approveCompany = useCallback(async () => {
    if (!companyDraft) return;
    setCompanyBusy(`approve:${companyDraft.ticker}`);
    setCompanyNotice("");
    setError("");
    try {
      const body = {
        company_name: companyDraft.company_name,
        org_id: companyDraft.org_id,
        isin: companyDraft.isin || null,
        sector: companyDraft.sector,
        logo_url: companyDraft.logo_url || null,
        security_type: companyDraft.security_type,
        share_type: companyDraft.share_type || null,
        review_note: companyDraft.review_note || null,
        sync: true,
      };
      const data = await readJson(
        `/api/admin/companies/${encodeURIComponent(companyDraft.ticker)}/approve`,
        { method: "POST", body: JSON.stringify(body) },
      );
      if (alive.current) {
        setCompanyDraft(companyDraftOf(data.company));
        setCompanyNotice(data.sync_started
          ? t("Компания опубликована, синхронизация запущена.", "Kompaniya e'lon qilindi, sinxronlash boshlandi.", "Company published; synchronization started.")
          : t("Компания опубликована.", "Kompaniya e'lon qilindi.", "Company published."));
        await loadCompanyImports(companyFilter);
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setCompanyBusy("");
    }
  }, [companyDraft, companyFilter, loadCompanyImports, readJson, t]);

  const rejectCompany = useCallback(async (item) => {
    const one = String(item?.ticker || companyDraft?.ticker || "").toUpperCase();
    if (!one) return;
    setCompanyBusy(`reject:${one}`);
    setCompanyNotice("");
    setError("");
    try {
      await readJson(`/api/admin/companies/${encodeURIComponent(one)}/reject`, {
        method: "POST",
        body: JSON.stringify({ note: item?.review_note || companyDraft?.review_note || null }),
      });
      if (companyDraft?.ticker === one) setCompanyDraft(null);
      await loadCompanyImports(companyFilter);
      setCompanyNotice(t("Кандидат отклонён.", "Nomzod rad etildi.", "Candidate rejected."));
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setCompanyBusy("");
    }
  }, [companyDraft, companyFilter, loadCompanyImports, readJson, t]);

  const syncCompany = useCallback(async (ticker) => {
    const one = String(ticker || "").toUpperCase();
    setCompanyBusy(`sync:${one}`);
    setCompanyNotice("");
    setError("");
    try {
      const data = await readJson(`/api/admin/companies/${encodeURIComponent(one)}/sync`, { method: "POST" });
      setCompanyNotice(data.started
        ? t("Синхронизация запущена.", "Sinxronlash boshlandi.", "Synchronization started.")
        : t("Синхронизация уже идёт.", "Sinxronlash davom etmoqda.", "Synchronization is already running."));
      await loadCompanyImports(companyFilter);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setCompanyBusy("");
    }
  }, [companyFilter, loadCompanyImports, readJson, t]);

  const setCompanyVisibility = useCallback(async (item, visible) => {
    const one = String(item?.ticker || "").toUpperCase();
    if (!one) return;
    setCompanyBusy(`visibility:${one}`);
    setCompanyNotice("");
    setError("");
    try {
      await readJson(`/api/admin/companies/${encodeURIComponent(one)}/visibility`, {
        method: "PATCH",
        body: JSON.stringify({ visible }),
      });
      await loadCompanyImports(companyFilter);
      setCompanyNotice(visible
        ? t("Компания возвращена в каталог.", "Kompaniya katalogga qaytarildi.", "Company restored to the catalog.")
        : t("Компания скрыта из каталога.", "Kompaniya katalogdan yashirildi.", "Company hidden from the catalog."));
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setCompanyBusy("");
    }
  }, [companyFilter, loadCompanyImports, readJson, t]);

  const loadLedger = useCallback(async (ticker) => {
    const one = String(ticker || "").trim().toUpperCase();
    if (!one) return;
    const data = await readJson(`/api/admin/issuer/${encodeURIComponent(one)}`);
    if (alive.current) setLedger(data);
  }, [readJson]);

  const loadFindings = useCallback(async () => {
    const params = new URLSearchParams({ limit: "300" });
    if (filters.severity) params.set("severity", filters.severity);
    if (filters.status) params.set("status", filters.status);
    const data = await readJson(`/api/audit/findings?${params}`);
    if (alive.current) setFindings(data.items || []);
  }, [filters, readJson]);

  // The rule book is public and cacheable; a failure there must not blank the page.
  useEffect(() => {
    fetch("/api/audit/rules")
      .then((r) => r.json())
      .then((d) => { if (alive.current && d && d.ok) setRules(d.items || []); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const jobs = [];
    if (isSystem) {
      if (section !== "railway") jobs.push(loadOverview());
      if (section === "companies") jobs.push(loadCompanyImports(companyFilter));
      else if (section === "findings") jobs.push(loadFindings());
      else if (section === "intake") jobs.push(loadIntake());
      else if (section === "rules") jobs.push(loadRuleBook());
      else if (section === "source") jobs.push(loadSource());
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
    Promise.all(jobs)
      .catch((e) => { if (!cancelled) setError(String(e.message || e)); })
      .finally(() => { if (!cancelled && alive.current) setLoading(false); });
    return () => { cancelled = true; };
    // usersQuery deliberately not a dependency: the list reloads on Enter or a
    // filter click, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, rangeDays, usersOnly, isSystem, loadOverview, loadFindings, loadIntake,
      loadRuleBook, loadSource, loadQuality, loadCompanyImports, companyFilter,
      loadMetrics, loadAudience, loadEngagement, loadAnalysis, loadFeedback, feedbackFilter]);

  const runAudit = async () => {
    setBusy(true);
    setError("");
    try {
      await readJson("/api/audit/run", {
        method: "POST",
        body: JSON.stringify({ trigger: "manual", with_history: 8 }),
      });
      await Promise.all([loadOverview(), section === "findings" ? loadFindings() : null]);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const acceptFindings = async (ids) => {
    if (!ids.length) return;
    setBusy(true);
    setError("");
    try {
      for (const id of ids) {
        await readJson(`/api/audit/findings/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ status: "accepted", note: "принято в админ-панели" }),
        });
      }
      setSelected((current) => {
        const next = new Set(current);
        ids.forEach((id) => next.delete(id));
        return next;
      });
      await Promise.all([loadOverview(), loadFindings()]);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const toggleSelected = (id) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const audit = overview && overview.audit;
  const catalog = overview && overview.catalog;
  const news = overview && overview.news;
  const streams = (overview && overview.streams) || [];
  const latest = audit && audit.latest;
  const openCounts = (audit && audit.open) || {};
  const history = (audit && audit.history) || [];
  const queue = (audit && audit.queue) || [];

  const staleStreams = useMemo(
    () => streams.filter((s) => s.state === "stale").length, [streams]);

  const activeTab = isSystem ? "system" : section;

  const SECTION_LEDE = {
    railway: t("Состояние сервисов Railway, ошибки из логов и безопасный перезапуск после сбоя.",
      "Railway xizmatlari holati, loglardagi xatolar va nosozlikdan keyin xavfsiz qayta ishga tushirish.",
      "Railway service status, errors from logs, and controlled recovery after a failure."),
    overview: t(
      "Сколько людей открыло сайт сегодня, живёт ли аудитория и работает ли продукт — прежде чем смотреть на таблицы.",
      "Bugun saytni nechta odam ochgani va mahsulot ishlayotgani.",
      "How many people opened the site today, whether the audience is alive and the product is used — before the plumbing."),
    audience: t(
      "Кто приходит: сколько, откуда, на чём и на каком языке. Ответ на буквальный вопрос «сколько человек открыло сайт».",
      "Kim kelmoqda: qancha, qayerdan va qaysi tilda.",
      "Who comes: how many, from where, on what device and in which language."),
    engagement: t(
      "Что они на самом деле смотрят: страницы, бумаги, новости. Топ бумаг — самая коммерчески интересная таблица панели.",
      "Ular aslida nimani ko'rmoqda: sahifalar, qog'ozlar, yangiliklar.",
      "What they actually look at: pages, tickers, stories. The ticker ranking is the most commercially interesting table here."),
    analysis: t(
      "Кто запускает AI-анализ, что анализируют и во сколько это обходится. Доля кэша — это напрямую счёт за LLM.",
      "Kim AI-tahlil ishga tushiradi va bu qancha turadi.",
      "Who runs the AI analysis, what they analyse and what it costs. The cache share is directly the LLM bill."),
    users: t(
      "Зарегистрированные: список, воронка от визита до возврата, безопасные действия поддержки и их постоянный журнал.",
      "Ro'yxatdan o'tganlar: ro'yxat, voronka, xavfsiz amallar va ularning jurnali.",
      "Registered users: the visit-to-return funnel, safe support actions and their durable audit trail."),
    feedback: t(
      "Отзывы и обращения пользователей. Сообщения видны только администраторам и остаются привязанными к аккаунту для ответа.",
      "Foydalanuvchi fikrlari va murojaatlari. Xabarlarni faqat administratorlar ko'radi.",
      "User feedback and support requests. Messages are visible only to administrators and remain linked to an account for follow-up."),
    system: t(
      "Состояние данных: что собрано, что требует решения. Служебная половина панели — один взгляд, когда карточка крона красная.",
      "Ma'lumotlar holati: nima yig'ilgan, nima qaror kutmoqda.",
      "The state of the data: what was collected, what needs a decision. The operations half, one look when a cron card goes red."),
    companies: t(
      "Новые бумаги приходят с UZSE и OpenInfo автоматически. Здесь администратор проверяет точное соответствие эмитента и публикует компанию без правки кода.",
      "Yangi qog'ozlar UZSE va OpenInfo'dan avtomatik keladi; administrator ularni tekshiradi va e'lon qiladi.",
      "New securities arrive automatically from UZSE and OpenInfo. Review the issuer match here and publish without a code change."),
    streams: t(
      "Показана последняя запись в таблице, которую пишет служба, а не её код возврата: сборщики работают отдельными сервисами и в этот процесс не отчитываются.",
      "Xizmat yozadigan jadvaldagi oxirgi yozuv ko'rsatilgan.",
      "The last write in the table each service fills, not its exit code: the collectors run as separate services and do not report here."),
    intake: t(
      "Что конвейер принял на вход. Пока статус записи не виден, любая правка расчёта делается наугад: половина найденных дефектов — не ошибка формулы, а то, какая запись до неё доехала.",
      "Konveyer nimani qabul qilgani.",
      "What the pipeline took in. While a record's status is invisible, every fix to the calculation is made blind."),
    issuer: t(
      "Расчёт разложен построчно: каждое слагаемое двенадцатимесячной базы со своим периодом и знаком, капитализация по классам, остатки, из которых берутся знаменатели, и все прошедшие проверки.",
      "Hisob-kitob qatorma-qator yoyilgan.",
      "The calculation laid out line by line: every component of the twelve-month base with its period and sign, the capitalisation by class, the balances the denominators come from."),
    source: t(
      "Кто должен был отчитаться, кто отчитался и кто молчит. Просрочка — это факт об эмитенте, а не о нашем сборщике, и тот же список — основа публичного индекса раскрытия.",
      "Kim hisobot berishi kerak edi, kim berdi va kim jim.",
      "Who was due to file, who did, and who has gone quiet. Being late is a fact about the issuer, not about our collector."),
    rules: t(
      "Параметры расчёта и граница ответственности: панель задаёт пороги и исключения, код задаёт вычисления.",
      "Hisob parametrlari va javobgarlik chegarasi.",
      "The calculation's parameters and the boundary: the panel sets thresholds and exceptions, the code holds the computation."),
    findings: t(
      "Аудитор пересчитывает те же величины независимым путём и сравнивает их с опубликованным. Блокирующая находка снимает число с публикации.",
      "Auditor qiymatlarni mustaqil qayta hisoblab, e'lon qilingani bilan solishtiradi.",
      "The auditor recomputes the same quantities by an independent route and compares them with what was published."),
  };

  /* labels shared by the product bodies */
  const VIEW_LABELS = {
    main: t("Главная", "Bosh sahifa", "Home"),
    market: t("Рынок", "Bozor", "Market"),
    company: t("Карточка компании", "Kompaniya sahifasi", "Company page"),
    chart: t("График", "Grafik", "Chart"),
    bond: t("Облигация", "Obligatsiya", "Bond"),
    news: t("Новости", "Yangiliklar", "News"),
    newsArticle: t("Новость", "Yangilik", "Story"),
    heatmap: t("Карта рынка", "Bozor xaritasi", "Heat map"),
    catalog: t("Каталог отчётов", "Hisobotlar katalogi", "Reports catalog"),
    bankfx: t("Курсы банков", "Bank kurslari", "Bank FX"),
    analysis: t("AI-анализ", "AI-tahlil", "AI analysis"),
    compare: t("Сравнение", "Taqqoslash", "Compare"),
    profile: t("Профиль", "Profil", "Profile"),
    auth: t("Вход", "Kirish", "Sign in"),
    "(other)": t("Прочее", "Boshqa", "Other"),
  };
  const DEVICE_LABELS = {
    mobile: t("Телефон", "Telefon", "Mobile"),
    tablet: t("Планшет", "Planshet", "Tablet"),
    desktop: t("Компьютер", "Kompyuter", "Desktop"),
    "(unknown)": t("Неизвестно", "Noma'lum", "Unknown"),
  };
  const KIND_LABELS = {
    direct: t("прямые", "to'g'ridan-to'g'ri", "direct"),
    search: t("поиск", "qidiruv", "search"),
    social: t("соцсети", "ijtimoiy", "social"),
    referral: t("переход", "havola", "referral"),
    internal: t("внутренний", "ichki", "internal"),
  };
  const LANG_LABELS = {
    ru: "Русский", uz: "O'zbekcha", en: "English",
    "(unknown)": t("Не выбран", "Tanlanmagan", "Not chosen"),
  };

  /* ══════════════════════════════════════════════════════════════════════════
     PRODUCT · Обзор
     ════════════════════════════════════════════════════════════════════════ */
  const mVisitors = (metrics && metrics.visitors) || {};
  const mReg = (metrics && metrics.registrations) || {};
  const mAn = (metrics && metrics.analyses) || {};
  const todayDelta = deltaBadge(mVisitors.today, mVisitors.yesterday);
  const weekDelta = deltaBadge(mVisitors.d7, mVisitors.prev7);

  const overviewBody = (
    <div className="admin-section">
      <div className="admin-stats">
        <Stat
          label={t("Посетителей сегодня", "Bugungi tashrifchilar", "Visitors today")}
          value={fmtInt(mVisitors.today)}
          badge={todayDelta ? todayDelta.text : null}
          badgeIcon={todayDelta ? todayDelta.icon : null}
          line1={t(`Вчера — ${fmtInt(mVisitors.yesterday)}`, `Kecha — ${fmtInt(mVisitors.yesterday)}`,
                   `Yesterday — ${fmtInt(mVisitors.yesterday)}`)}
          line2={t(`Просмотров сегодня — ${fmtInt(metrics && metrics.pageviews_today)}`,
                   `Bugungi ko'rishlar — ${fmtInt(metrics && metrics.pageviews_today)}`,
                   `Page views today — ${fmtInt(metrics && metrics.pageviews_today)}`)}
        />
        <Stat
          label={t("За 7 дней", "7 kun ichida", "Last 7 days")}
          value={fmtInt(mVisitors.d7)}
          badge={weekDelta ? weekDelta.text : null}
          badgeIcon={weekDelta ? weekDelta.icon : null}
          line1={t(`За 30 дней — ${fmtInt(mVisitors.d30)}`, `30 kun — ${fmtInt(mVisitors.d30)}`,
                   `30 days — ${fmtInt(mVisitors.d30)}`)}
          line2={t("Уникальные посетители", "Noyob tashrifchilar", "Unique visitors")}
        />
        <Stat
          label={t("Прилипчивость DAU/MAU", "DAU/MAU", "Stickiness DAU/MAU")}
          value={fmtShare(metrics && metrics.stickiness, 1)}
          line1={t(`средний DAU за неделю — ${fmtNum(metrics && metrics.avg_dau_7d, 1)}`,
                   `haftalik o'rtacha DAU — ${fmtNum(metrics && metrics.avg_dau_7d, 1)}`,
                   `avg DAU last week — ${fmtNum(metrics && metrics.avg_dau_7d, 1)}`)}
          line2={t("≈20% — здоровый продукт; <10% — разовые визиты",
                   "≈20% — sog'lom mahsulot",
                   "≈20% is healthy; below 10% means one-off visits")}
        />
        <Stat
          label={t("Сейчас на сайте", "Hozir saytda", "Live now")}
          value={fmtInt(metrics && metrics.live_now)}
          line1={t("за последние 5 минут", "so'nggi 5 daqiqada", "in the last 5 minutes")}
          line2={t(`Вошедших сегодня — ${fmtInt(metrics && metrics.signed_in && metrics.signed_in.today)}`,
                   `Bugun kirganlar — ${fmtInt(metrics && metrics.signed_in && metrics.signed_in.today)}`,
                   `Signed-in today — ${fmtInt(metrics && metrics.signed_in && metrics.signed_in.today)}`)}
        />
      </div>

      <div className="panel">
        <div className="admin-chart-head">
          <div>
            <h2>{t("Посетители по дням", "Kunlik tashrifchilar", "Visitors by day")}</h2>
            <p>{t("Последние 14 дней, граница суток — Ташкент",
                  "So'nggi 14 kun, Toshkent vaqti",
                  "Last 14 days, Tashkent day boundary")}</p>
          </div>
        </div>
        {metrics && metrics.daily && metrics.daily.length
          ? <DailyBars data={metrics.daily} valueKey="visitors"
                       titleFn={(r) => `${fmtDay(r.day)} · ${fmtInt(r.visitors)} ${t("чел.", "kishi", "visitors")} · ${fmtInt(r.pageviews)} ${t("просмотров", "ko'rish", "views")}`} />
          : <NoTraffic t={t} />}
      </div>

      <div className="admin-stats">
        <Stat
          label={t("Регистраций сегодня", "Bugungi ro'yxatdan o'tish", "Registrations today")}
          value={fmtInt(mReg.today)}
          line1={t(`за 7 дней — ${fmtInt(mReg.d7)}`, `7 kun — ${fmtInt(mReg.d7)}`, `7 days — ${fmtInt(mReg.d7)}`)}
          line2={t(`всего аккаунтов — ${fmtInt(mReg.total)}`, `jami — ${fmtInt(mReg.total)}`,
                   `total accounts — ${fmtInt(mReg.total)}`)}
        />
        <Stat
          label={t("Анализов сегодня", "Bugungi tahlillar", "Analyses today")}
          value={fmtInt(mAn.today)}
          line1={t(`за 7 дней — ${fmtInt(mAn.d7)}`, `7 kun — ${fmtInt(mAn.d7)}`, `7 days — ${fmtInt(mAn.d7)}`)}
          line2={t("Запуски AI-анализа", "AI-tahlil ishga tushirishlari", "AI analysis runs")}
        />
        <Stat
          label={t("Потоки данных", "Ma'lumot oqimlari", "Data streams")}
          value={overview ? `${streams.length - staleStreams}/${streams.length}` : DASH}
          warn={Boolean(staleStreams)}
          line1={staleStreams
            ? t(`${staleStreams} устарел(и)`, `${staleStreams} eskirgan`, `${staleStreams} stale`)
            : t("Все потоки писали недавно", "Barcha oqimlar yaqinda yozgan", "Every stream wrote recently")}
          line2={t("Подробности — в «Системе»", "Tafsilotlar — «Tizim»da", "Details under System")}
        />
        <Stat
          label={t("Блокирующих находок", "Bloklovchi topilmalar", "Blocking findings")}
          value={overview ? fmtInt(openCounts.blocking) : DASH}
          warn={Boolean(openCounts.blocking)}
          line1={overview
            ? t(`Предупреждений — ${fmtInt(openCounts.warning)}`, `Ogohlantirish — ${fmtInt(openCounts.warning)}`,
                `Warnings — ${fmtInt(openCounts.warning)}`)
            : null}
          line2={t("Аудит данных — в «Системе»", "Ma'lumot auditi — «Tizim»da", "Data audit under System")}
        />
      </div>
    </div>
  );

  // The product overview also wants the two operations numbers above; load them
  // lazily once the section is open so the screen never blocks on them.
  useEffect(() => {
    if (section === "overview" && !overview) {
      loadOverview().catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section]);

  /* ══════════════════════════════════════════════════════════════════════════
     PRODUCT · Аудитория
     ════════════════════════════════════════════════════════════════════════ */
  const aud = audienceData && audienceData.ok ? audienceData : null;
  const audTotals = (aud && aud.totals) || {};
  const audienceBody = (
    <div className="admin-section">
      <div className="admin-panel-bar">
        <RangePicker value={rangeDays} onChange={setRangeDays} t={t} />
      </div>

      <div className="admin-stats">
        <Stat
          label={t("Уникальных посетителей", "Noyob tashrifchilar", "Unique visitors")}
          value={fmtInt(audTotals.visitors)}
          line1={t(`новых — ${fmtInt(audTotals.new_visitors)} · вернувшихся — ${fmtInt(audTotals.returning_visitors)}`,
                   `yangi — ${fmtInt(audTotals.new_visitors)}`,
                   `new — ${fmtInt(audTotals.new_visitors)} · returning — ${fmtInt(audTotals.returning_visitors)}`)}
          line2={t(`за ${rangeDays} дней`, `${rangeDays} kun ichida`, `over ${rangeDays} days`)}
        />
        <Stat
          label={t("Визитов", "Tashriflar", "Sessions")}
          value={fmtInt(audTotals.sessions)}
          line1={t(`просмотров — ${fmtInt(audTotals.pageviews)}`, `ko'rishlar — ${fmtInt(audTotals.pageviews)}`,
                   `page views — ${fmtInt(audTotals.pageviews)}`)}
          line2={t("новый визит после 30 минут тишины", "30 daqiqadan keyin yangi tashrif",
                   "a new session after 30 idle minutes")}
        />
        <Stat
          label={t("Глубина визита", "Tashrif chuqurligi", "Session depth")}
          value={audTotals.pages_per_session != null ? fmtNum(audTotals.pages_per_session, 1) : DASH}
          line1={t(`длительность — ${fmtDuration(audTotals.avg_session_seconds, t)}`,
                   `davomiyligi — ${fmtDuration(audTotals.avg_session_seconds, t)}`,
                   `duration — ${fmtDuration(audTotals.avg_session_seconds, t)}`)}
          line2={t("страниц за визит, в среднем", "har tashrifda sahifalar", "pages per session, average")}
        />
        <Stat
          label={t("Отказы", "Rad etishlar", "Bounce rate")}
          value={fmtShare(audTotals.bounce_rate)}
          line1={t("визиты из одной страницы", "bir sahifalik tashriflar", "single-page sessions")}
          line2={t("для терминала с одной доской это не приговор",
                   "bitta doskali terminal uchun bu hukm emas",
                   "for a one-board terminal this is not a verdict")}
        />
      </div>

      <div className="panel">
        <div className="admin-chart-head">
          <div>
            <h2>{t("Посетители по дням", "Kunlik tashrifchilar", "Visitors by day")}</h2>
            <p>{t(`${rangeDays} дней · граница суток — Ташкент`, `${rangeDays} kun`, `${rangeDays} days · Tashkent day boundary`)}</p>
          </div>
        </div>
        {aud && aud.daily && aud.daily.length
          ? <DailyBars data={aud.daily} valueKey="visitors"
                       titleFn={(r) => `${fmtDay(r.day)} · ${fmtInt(r.visitors)} ${t("чел.", "kishi", "visitors")} · ${fmtInt(r.sessions)} ${t("визитов", "tashrif", "sessions")}`} />
          : <NoTraffic t={t} />}
      </div>

      <div className="admin-cols2">
        <div className="panel">
          <h3>{t("Откуда приходят", "Qayerdan kelishadi", "Where they come from")}</h3>
          <HBarList
            rows={(aud && aud.referrers) || []}
            nameFn={(r) => r.host === "(direct)" ? t("Прямые заходы", "To'g'ridan-to'g'ri", "Direct") : r.host}
            valueFn={(r) => r.sessions}
            detailFn={(r) => KIND_LABELS[r.kind] || ""}
          />
          {aud && !(aud.referrers || []).length ? <NoTraffic t={t} /> : null}
          <p className="admin-muted admin-note">
            {t("Источник берётся только с первой страницы визита — дальше он повторял бы наши же адреса.",
               "Manba faqat tashrifning birinchi sahifasidan olinadi.",
               "The source is taken from the first page of the visit only.")}
          </p>
        </div>
        <div className="panel">
          <h3>{t("Устройства и экраны", "Qurilmalar va ekranlar", "Devices and screens")}</h3>
          <HBarList
            rows={(aud && aud.devices) || []}
            nameFn={(r) => DEVICE_LABELS[r.name] || r.name}
            valueFn={(r) => r.visitors}
          />
          <div style={{ height: 14 }} />
          <HBarList
            rows={(aud && aud.screens) || []}
            nameFn={(r) => r.name === "(unknown)" ? t("ширина неизвестна", "kengligi noma'lum", "unknown width") : `${r.name} px`}
            valueFn={(r) => r.visitors}
          />
        </div>
      </div>

      <div className="admin-cols3">
        <div className="panel">
          <h3>{t("Язык интерфейса", "Interfeys tili", "UI language")}</h3>
          <HBarList
            rows={(aud && aud.languages) || []}
            nameFn={(r) => LANG_LABELS[r.name] || r.name}
            valueFn={(r) => r.visitors}
          />
          <p className="admin-muted admin-note">
            {t("Сайт держит три языка — здесь видно, читает ли кто-то узбекскую версию.",
               "Sayt uch tilni saqlaydi — o'zbekchani kim o'qiyotgani shu yerda.",
               "The site carries three languages — this shows whether anyone reads the Uzbek one.")}
          </p>
        </div>
        <div className="panel">
          <h3>{t("Браузеры", "Brauzerlar", "Browsers")}</h3>
          <HBarList rows={(aud && aud.browsers) || []} nameFn={(r) => r.name} valueFn={(r) => r.visitors} />
        </div>
        <div className="panel">
          <h3>{t("Страны", "Mamlakatlar", "Countries")}</h3>
          <HBarList
            rows={(aud && aud.countries) || []}
            nameFn={(r) => r.name === "(unknown)" ? t("не определена", "aniqlanmagan", "not detected") : r.name}
            valueFn={(r) => r.visitors}
          />
          <p className="admin-muted admin-note">
            {t("Страна видна, только когда её сообщает прокси; IP не хранится и не геокодируется.",
               "Mamlakat faqat proksi aytganda ko'rinadi; IP saqlanmaydi.",
               "The country shows only when the proxy reports it; the IP is neither stored nor geocoded.")}
          </p>
        </div>
      </div>
    </div>
  );

  /* ══════════════════════════════════════════════════════════════════════════
     PRODUCT · Вовлечённость
     ════════════════════════════════════════════════════════════════════════ */
  const eng = engagementData && engagementData.ok ? engagementData : null;
  const engagementBody = (
    <div className="admin-section">
      <div className="admin-panel-bar">
        <RangePicker value={rangeDays} onChange={setRangeDays} t={t} />
      </div>

      <div className="admin-cols2">
        <div className="panel">
          <h3>{t("Разделы сайта", "Sayt bo'limlari", "Site sections")}</h3>
          <HBarList
            rows={(eng && eng.views) || []}
            nameFn={(r) => VIEW_LABELS[r.view] || r.view}
            valueFn={(r) => r.pageviews}
            detailFn={(r) => t(`${fmtInt(r.visitors)} чел.`, `${fmtInt(r.visitors)} kishi`, `${fmtInt(r.visitors)} visitors`)}
          />
          {eng && !(eng.views || []).length ? <NoTraffic t={t} /> : null}
        </div>
        <div className="panel">
          <h3>{t("Топ бумаг по просмотрам", "Ko'rishlar bo'yicha top qog'ozlar", "Top tickers by views")}</h3>
          <HBarList
            rows={(eng && eng.tickers) || []}
            nameFn={(r) => r.ticker}
            valueFn={(r) => r.pageviews}
            detailFn={(r) => t(`${fmtInt(r.visitors)} чел.`, `${fmtInt(r.visitors)} kishi`, `${fmtInt(r.visitors)} visitors`)}
          />
          {eng && !(eng.tickers || []).length
            ? <div className="admin-empty">{t("Карточки компаний ещё не открывали", "Kompaniya sahifalari hali ochilmagan", "No company pages opened yet")}</div>
            : null}
          <p className="admin-muted admin-note">
            {t("Считаются карточки компаний, продвинутые графики и страницы облигаций. Этот список — готовый приоритет для бэклога данных.",
               "Kompaniya sahifalari, grafiklar va obligatsiya sahifalari hisoblanadi.",
               "Company pages, advanced charts and bond pages count. This ranking is a ready-made priority for the data backlog.")}
          </p>
        </div>
      </div>

      <div className="admin-cols2">
        <div className="panel">
          <h3>{t("Читаемые новости", "O'qilgan yangiliklar", "Stories read")}</h3>
          <HBarList
            rows={(eng && eng.news) || []}
            nameFn={(r) => r.path.replace("/news/", "№")}
            valueFn={(r) => r.pageviews}
          />
          {eng && !(eng.news || []).length
            ? <div className="admin-empty">{t("Отдельные новости ещё не открывали", "Alohida yangiliklar hali ochilmagan", "No individual stories opened yet")}</div>
            : null}
        </div>
        <div className="panel">
          <h3>{t("Действия на сайте", "Saytdagi amallar", "On-site events")}</h3>
          <HBarList
            rows={(eng && eng.events) || []}
            nameFn={(r) => r.event}
            valueFn={(r) => r.count}
          />
          {eng && !(eng.events || []).length ? (
            <div className="admin-empty">
              {t("Пока считаются только просмотры страниц; события (поиск, фильтры, вкладки) добавляются по одному в lib/track.js.",
                 "Hozircha faqat sahifa ko'rishlari hisoblanadi.",
                 "Only page views are counted so far; custom events (search, filters, tabs) are added one by one in lib/track.js.")}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );

  /* ══════════════════════════════════════════════════════════════════════════
     PRODUCT · AI-анализ
     ════════════════════════════════════════════════════════════════════════ */
  const ana = analysisData && analysisData.ok ? analysisData : null;
  const anaTotals = (ana && ana.totals) || {};
  const anaMtd = (ana && ana.month_to_date) || {};
  const analysisBody = (
    <div className="admin-section">
      <AnalysisMonitor readJson={readJson} language={language} />
      <div className="admin-panel-bar">
        <RangePicker value={rangeDays} onChange={setRangeDays} t={t} />
      </div>

      <div className="admin-stats">
        <Stat
          label={t("Анализов", "Tahlillar", "Analyses")}
          value={fmtInt(anaTotals.analyses)}
          line1={t(`пользователей — ${fmtInt(anaTotals.users)}`, `foydalanuvchilar — ${fmtInt(anaTotals.users)}`,
                   `users — ${fmtInt(anaTotals.users)}`)}
          line2={t(`за ${rangeDays} дней`, `${rangeDays} kun ichida`, `over ${rangeDays} days`)}
        />
        <Stat
          label={t("Доля кэша", "Kesh ulushi", "Cache hit rate")}
          value={fmtShare(anaTotals.cache_rate)}
          line1={t(`из кэша — ${fmtInt(anaTotals.cached)}`, `keshdan — ${fmtInt(anaTotals.cached)}`,
                   `from cache — ${fmtInt(anaTotals.cached)}`)}
          line2={t("каждый кэш-хит — несписанные деньги", "har bir kesh-xit — sarflanmagan pul",
                   "every cache hit is money not spent")}
        />
        <Stat
          label={t("Расход на LLM", "LLM xarajati", "LLM spend")}
          value={fmtUsd(anaTotals.cost)}
          line1={t(`на один анализ — ${fmtUsd(anaTotals.cost_per_analysis, 4)}`,
                   `bitta tahlilga — ${fmtUsd(anaTotals.cost_per_analysis, 4)}`,
                   `per analysis — ${fmtUsd(anaTotals.cost_per_analysis, 4)}`)}
          line2={t(`за ${rangeDays} дней, без кэш-хитов`, `${rangeDays} kun, keshsiz`, `over ${rangeDays} days, cache hits excluded`)}
        />
        <Stat
          label={t("Прогноз на месяц", "Oylik prognoz", "Month projection")}
          value={fmtUsd(anaMtd.projected_cost)}
          line1={t(`с начала месяца — ${fmtUsd(anaMtd.cost)}`, `oy boshidan — ${fmtUsd(anaMtd.cost)}`,
                   `month to date — ${fmtUsd(anaMtd.cost)}`)}
          line2={t("линейная экстраполяция текущего темпа", "joriy sur'atning chiziqli davomi",
                   "linear extrapolation of the current rate")}
        />
      </div>

      <div className="panel">
        <div className="admin-chart-head">
          <div>
            <h2>{t("Анализы по дням", "Kunlik tahlillar", "Analyses by day")}</h2>
            <p>{t(`${rangeDays} дней`, `${rangeDays} kun`, `${rangeDays} days`)}</p>
          </div>
        </div>
        {ana && ana.daily && ana.daily.length
          ? <DailyBars data={ana.daily} valueKey="analyses"
                       titleFn={(r) => `${fmtDay(r.day)} · ${fmtInt(r.analyses)} ${t("анализов", "tahlil", "analyses")} · ${fmtUsd(r.cost)}`} />
          : (
            <div className="admin-empty">
              {t("За выбранный период анализов не было", "Tanlangan davrda tahlillar bo'lmagan", "No analyses in this period")}
            </div>
          )}
      </div>

      <div className="admin-cols3">
        <div className="panel">
          <h3>{t("Что анализируют", "Nimani tahlil qilishadi", "What gets analysed")}</h3>
          <HBarList
            rows={(ana && ana.top_companies) || []}
            nameFn={(r) => r.name}
            valueFn={(r) => r.analyses}
            detailFn={(r) => t(`${fmtInt(r.users)} чел.`, `${fmtInt(r.users)} kishi`, `${fmtInt(r.users)} users`)}
          />
        </div>
        <div className="panel">
          <h3>{t("Модели и их счёт", "Modellar va hisob", "Models and their bill")}</h3>
          <HBarList
            rows={(ana && ana.models) || []}
            nameFn={(r) => r.model}
            valueFn={(r) => r.analyses}
            detailFn={(r) => fmtUsd(r.cost)}
          />
        </div>
        <div className="panel">
          <h3>{t("Раздача оценок", "Baholar taqsimoti", "Grade distribution")}</h3>
          <HBarList
            rows={(ana && ana.grades) || []}
            nameFn={(r) => r.grade}
            valueFn={(r) => r.analyses}
          />
        </div>
      </div>
    </div>
  );

  /* ══════════════════════════════════════════════════════════════════════════
     PRODUCT · Пользователи
     ════════════════════════════════════════════════════════════════════════ */
  const FUNNEL_LABELS = {
    visited: t("Зашли на сайт", "Saytga kirdi", "Visited"),
    registered: t("Зарегистрировались", "Ro'yxatdan o'tdi", "Registered"),
    activated: t("Запустили анализ", "Tahlil ishga tushirdi", "Ran an analysis"),
    returned: t("Вернулись позже", "Keyinroq qaytdi", "Came back later"),
  };

  const userRows = (usersData && usersData.items) || [];
  const detailUser = userDetail && userDetail.ok ? userDetail : null;
  const adminLogRows = (adminLog && adminLog.items) || [];

  const USER_ACTION_LABELS = {
    deactivate: t("Отключил", "O'chirdi", "Deactivated"),
    reactivate: t("Включил", "Yoqdi", "Reactivated"),
    revoke_sessions: t("Отозвал сессии", "Seanslarni bekor qildi", "Revoked sessions"),
    delete: t("Удалил", "O'chirib tashladi", "Deleted"),
  };

  const actionButton = (id, action, label, danger, disabled = false) => {
    const armed = confirmAction && confirmAction.id === id && confirmAction.action === action;
    return (
      <button
        type="button"
        className={`admin-btn sm${armed ? " danger" : ""}`}
        disabled={busy || disabled}
        title={disabled
          ? t("Сначала удалите адрес из ADMIN_EMAILS", "Avval manzilni ADMIN_EMAILS dan olib tashlang",
              "Remove the address from ADMIN_EMAILS first")
          : undefined}
        onClick={() => {
          if (danger && !armed) { setConfirmAction({ id, action }); return; }
          runUserAction(id, action);
        }}
      >
        {armed ? t("Точно?", "Aniqmi?", "Sure?") : label}
      </button>
    );
  };

  const usersBody = (
    <div className="admin-section">
      <div className="panel">
        <h3>{t("Воронка за 30 дней", "30 kunlik voronka", "30-day funnel")}</h3>
        {funnel && funnel.ok
          ? <Funnel steps={funnel.steps} labels={FUNNEL_LABELS} />
          : <div className="admin-empty">{DASH}</div>}
        <p className="admin-muted admin-note">
          {t("«Вернулись» — вход спустя сутки и больше после регистрации. Процент у шага — доля от предыдущего.",
             "«Qaytdi» — ro'yxatdan keyin bir kundan so'ng kirish.",
             "\u201cCame back\u201d means a sign-in a day or more after registering. The percentage is of the previous step.")}
        </p>
      </div>

      <div className="panel">
        <div className="admin-filters" style={{ padding: 0, marginBottom: 14 }}>
          <input
            className="admin-input"
            placeholder={t("Почта или имя…", "Pochta yoki ism…", "Email or name…")}
            value={usersQuery}
            onChange={(e) => setUsersQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") loadUsers(usersQuery, usersOnly); }}
          />
          <button type="button" className="admin-btn sm" onClick={() => loadUsers(usersQuery, usersOnly)}>
            <Icon name="search" />{t("Найти", "Qidirish", "Search")}
          </button>
          <span className="admin-sp" />
          <div className="admin-seg">
            {[["", t("Все", "Barchasi", "All")],
              ["active", t("Активные", "Faol", "Active")],
              ["inactive", t("Отключённые", "O'chirilgan", "Deactivated")],
              ["analysed", t("С анализами", "Tahlili borlar", "With analyses")]].map(([key, label]) => (
              <button key={key || "all"} type="button" aria-selected={usersOnly === key}
                      onClick={() => setUsersOnly(key)}>
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="admin-scroll">
          <table>
            <thead>
              <tr>
                <th>{t("Пользователь", "Foydalanuvchi", "User")}</th>
                <th style={{ width: 140 }}>{t("Регистрация", "Ro'yxatdan o'tgan", "Registered")}</th>
                <th style={{ width: 140 }}>{t("Последний вход", "Oxirgi kirish", "Last sign-in")}</th>
                <th className="r" style={{ width: 90 }}>{t("Анализов", "Tahlillar", "Analyses")}</th>
                <th className="r" style={{ width: 96 }}>{t("Избранных", "Sevimlilar", "Favourites")}</th>
                <th style={{ width: 105 }}>{t("Тариф", "Tarif", "Tier")}</th>
                <th style={{ width: 120 }}>{t("Статус", "Holat", "State")}</th>
              </tr>
            </thead>
            <tbody>
              {!userRows.length ? (
                <tr>
                  <td colSpan={7} className="admin-muted" style={{ padding: "24px 0", textAlign: "center" }}>
                    {t("Никого не найдено.", "Hech kim topilmadi.", "Nobody found.")}
                  </td>
                </tr>
              ) : null}
              {userRows.map((u) => (
                <tr key={u.id}>
                  <td>
                    <button type="button" className="admin-link" onClick={() => openUser(u.id)}>
                      {u.email}
                    </button>
                    {u.is_admin ? (
                      <span className="admin-pill" style={{ marginLeft: 8 }}>
                        <span className="admin-dot ok" />admin
                      </span>
                    ) : null}
                    {u.full_name ? <div className="admin-sub">{u.full_name}{u.oauth_providers ? ` · ${u.oauth_providers}` : ""}</div>
                      : (u.oauth_providers ? <div className="admin-sub">{u.oauth_providers}</div> : null)}
                  </td>
                  <td className="admin-num">{fmtStamp(u.created_at, { withTime: false })}</td>
                  <td className="admin-num">{fmtStamp(u.last_login_at, { withTime: false })}</td>
                  <td className="r admin-num">{fmtInt(u.analyses)}</td>
                  <td className="r admin-num">{fmtInt(u.favorites)}</td>
                  <td>
                    <span className="admin-pill">
                      <span className={`admin-dot ${u.tier === "pro" ? "ok" : ""}`} />
                      {u.tier === "pro" ? "PRO" : t("бесплатный", "bepul", "free")}
                    </span>
                  </td>
                  <td>
                    <span className="admin-pill">
                      <span className={`admin-dot ${u.is_active ? "ok" : "err"}`} />
                      {u.is_active ? t("активен", "faol", "active") : t("отключён", "o'chirilgan", "off")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="admin-table-foot">
          <span>
            {t(`Показано ${userRows.length} из ${fmtInt(usersData && usersData.total)}`,
               `${fmtInt(usersData && usersData.total)} tadan ${userRows.length} ta`,
               `Showing ${userRows.length} of ${fmtInt(usersData && usersData.total)}`)}
          </span>
        </div>
      </div>

      {detailUser ? (
        <div className="panel">
          <div className="admin-panel-head">
            <h2>{detailUser.user.email}</h2>
            <span className="admin-muted">
              {detailUser.user.full_name || DASH} · {t("зарегистрирован", "ro'yxatdan o'tgan", "registered")} {fmtStamp(detailUser.user.created_at, { withTime: false })}
            </span>
          </div>

          <div className="admin-filters" style={{ padding: 0 }}>
            {detailUser.user.is_active
              ? actionButton(detailUser.user.id, "deactivate", t("Отключить", "O'chirish", "Deactivate"), true,
                             detailUser.user.is_admin)
              : actionButton(detailUser.user.id, "reactivate", t("Включить", "Yoqish", "Reactivate"), false)}
            {actionButton(detailUser.user.id, "revoke_sessions",
                          t("Разлогинить везде", "Hamma joydan chiqarish", "Revoke sessions"), false)}
            {actionButton(detailUser.user.id, "delete",
                          t("Удалить аккаунт", "Hisobni o'chirish", "Delete account"), true,
                          detailUser.user.is_admin)}
            <span className="admin-sp" />
            <button type="button" className="admin-btn sm" onClick={() => { setUserDetail(null); setConfirmAction(null); }}>
              {t("Свернуть", "Yopish", "Close")}
            </button>
          </div>
          <p className="admin-muted admin-note">
            {detailUser.user.is_admin
              ? t("Администратор защищён от отключения и удаления. Сначала уберите адрес из ADMIN_EMAILS — это намеренное изменение контура доступа.",
                  "Administrator o'chirish va o'chirib tashlashdan himoyalangan. Avval manzilni ADMIN_EMAILS dan olib tashlang.",
                  "This administrator is protected from deactivation and deletion. Remove the address from ADMIN_EMAILS first—an explicit access-control change.")
              : t("Удаление уносит и историю анализов, и избранное — это право пользователя на удаление данных, а не уборка. Отключение мгновенно разрывает все сессии.",
                  "O'chirish tahlil tarixini ham olib ketadi.",
                  "Deletion takes the analysis history and favourites with it—the user's right to erasure, not housekeeping. Deactivation severs every session immediately.")}
          </p>

          <div className="admin-cols3" style={{ marginTop: 14 }}>
            <div>
              <div className="panel-label">{t("Сессии", "Sessiyalar", "Sessions")}</div>
              <table className="admin-kv">
                <tbody>
                  {detailUser.sessions.slice(0, 6).map((s, i) => (
                    <tr key={i}>
                      <td>{fmtStamp(s.created_at)}</td>
                      <td className="n">{s.revoked
                        ? t("отозвана", "bekor qilingan", "revoked")
                        : t("живая", "faol", "live")}</td>
                    </tr>
                  ))}
                  {!detailUser.sessions.length
                    ? <tr><td className="admin-muted">{t("Сессий не было", "Sessiyalar bo'lmagan", "No sessions")}</td><td /></tr>
                    : null}
                </tbody>
              </table>
            </div>
            <div>
              <div className="panel-label">{t("Анализы", "Tahlillar", "Analyses")}</div>
              <table className="admin-kv">
                <tbody>
                  {detailUser.analyses.slice(0, 6).map((a, i) => (
                    <tr key={i}>
                      <td>{a.ticker || a.company}</td>
                      <td className="n">{a.grade || DASH} · {fmtStamp(a.created_at, { withTime: false })}</td>
                    </tr>
                  ))}
                  {!detailUser.analyses.length
                    ? <tr><td className="admin-muted">{t("Анализов не было", "Tahlillar bo'lmagan", "No analyses")}</td><td /></tr>
                    : null}
                </tbody>
              </table>
            </div>
            <div>
              <div className="panel-label">{t("Избранное", "Sevimlilar", "Favourites")}</div>
              <table className="admin-kv">
                <tbody>
                  {detailUser.favorites.slice(0, 6).map((f, i) => (
                    <tr key={i}>
                      <td>{f.ticker}</td>
                      <td className="n">{fmtStamp(f.created_at, { withTime: false })}</td>
                    </tr>
                  ))}
                  {!detailUser.favorites.length
                    ? <tr><td className="admin-muted">{t("Пусто", "Bo'sh", "Empty")}</td><td /></tr>
                    : null}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}

      <div className="panel">
        <div className="admin-panel-head">
          <h2>{t("Журнал действий", "Amallar jurnali", "Administrative activity")}</h2>
          <span className="admin-muted">
            {t("Кто, что, над кем и когда", "Kim, nima, kimga va qachon", "Who did what, to whom, and when")}
          </span>
        </div>
        <div className="admin-scroll">
          <table>
            <thead>
              <tr>
                <th style={{ width: 165 }}>{t("Время", "Vaqt", "Time")}</th>
                <th>{t("Администратор", "Administrator", "Administrator")}</th>
                <th style={{ width: 170 }}>{t("Действие", "Amal", "Action")}</th>
                <th>{t("Объект", "Obyekt", "Target")}</th>
                <th style={{ width: 120 }}>{t("Результат", "Natija", "Outcome")}</th>
              </tr>
            </thead>
            <tbody>
              {!adminLogRows.length ? (
                <tr>
                  <td colSpan={5} className="admin-muted" style={{ padding: "24px 0", textAlign: "center" }}>
                    {t("Действий пока не было.", "Hali amallar bo'lmagan.", "No administrative actions yet.")}
                  </td>
                </tr>
              ) : null}
              {adminLogRows.map((entry) => (
                <tr key={entry.id}>
                  <td className="admin-num">{fmtStamp(entry.created_at)}</td>
                  <td>{entry.actor_email}</td>
                  <td>{USER_ACTION_LABELS[entry.action] || entry.action}</td>
                  <td>
                    {entry.target_label || `${entry.target_type} ${entry.target_id || ""}`}
                    {entry.target_id ? <div className="admin-sub">ID {entry.target_id}</div> : null}
                  </td>
                  <td>
                    <span className="admin-pill">
                      <span className={`admin-dot ${entry.outcome === "success" ? "ok" : "err"}`} />
                      {entry.outcome === "success"
                        ? t("выполнено", "bajarildi", "success")
                        : t("отклонено", "rad etildi", "denied")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="admin-muted admin-note">
          {t("Журнал хранится в базе отдельно от серверных логов; удаление пользователя не удаляет запись о действии.",
             "Jurnal server loglaridan alohida bazada saqlanadi.",
             "This trail is stored in the database separately from server logs; deleting a user does not delete the action record.")}
        </p>
      </div>
    </div>
  );

  /* ══════════════════════════════════════════════════════════════════════════
     СИСТЕМА · Данные (the old data overview)
     ════════════════════════════════════════════════════════════════════════ */
  const dataBody = (
    <div className="admin-section">
      <div className="admin-stats">
        <Stat
          label={t("Бумаг в каталоге", "Kataloqdagi qog'ozlar", "Securities")}
          value={fmtInt(catalog && catalog.securities)}
          line1={catalog && catalog.preferred
            ? t(`${fmtInt(catalog.preferred)} привилегированных`,
                `${fmtInt(catalog.preferred)} imtiyozli`,
                `${fmtInt(catalog.preferred)} preferred`)
            : null}
          line2={catalog
            ? t(`${fmtInt(catalog.stocks)} акций и ${fmtInt(catalog.bonds)} облигаций`,
                `${fmtInt(catalog.stocks)} aksiya, ${fmtInt(catalog.bonds)} obligatsiya`,
                `${fmtInt(catalog.stocks)} shares and ${fmtInt(catalog.bonds)} bonds`)
            : null}
        />
        <Stat
          label={t("Блокирующих находок", "Bloklovchi topilmalar", "Blocking findings")}
          value={fmtInt(openCounts.blocking)}
          warn={Boolean(openCounts.blocking)}
          line1={t(`Предупреждений — ${fmtInt(openCounts.warning)}`,
                   `Ogohlantirish — ${fmtInt(openCounts.warning)}`,
                   `Warnings — ${fmtInt(openCounts.warning)}`)}
          line2={t("Открытые, ещё не разобранные", "Ochiq, ko'rib chiqilmagan", "Open, not yet triaged")}
        />
        <Stat
          label={news
            ? t(`Новостей за ${news.days} дней`, `${news.days} kunlik yangiliklar`, `News, ${news.days} days`)
            : t("Новостей за неделю", "Haftalik yangiliklar", "News this week")}
          value={fmtInt(news && news.collected)}
          line1={news
            ? t(`${fmtInt(news.published)} опубликовано`, `${fmtInt(news.published)} chop etilgan`,
                `${fmtInt(news.published)} published`)
            : null}
          line2={news
            ? t(`${fmtInt(news.rejected)} отклонено триажем · ${fmtInt(news.without_image)} без картинки`,
                `${fmtInt(news.rejected)} rad etilgan · ${fmtInt(news.without_image)} rasmsiz`,
                `${fmtInt(news.rejected)} rejected · ${fmtInt(news.without_image)} without an image`)
            : null}
        />
        <Stat
          label={t("Потоки данных", "Ma'lumot oqimlari", "Data streams")}
          value={`${streams.length - staleStreams}/${streams.length}`}
          badge={staleStreams
            ? t(`${staleStreams} устарел(и)`, `${staleStreams} eskirgan`, `${staleStreams} stale`)
            : null}
          badgeIcon={staleStreams ? "down" : null}
          line1={staleStreams
            ? t("Есть потоки без свежих записей", "Yangi yozuvsiz oqimlar bor", "Some streams have no fresh write")
            : t("Все потоки писали недавно", "Barcha oqimlar yaqinda yozgan", "Every stream wrote recently")}
          line2={t("По последней записи в таблице", "Jadvaldagi oxirgi yozuv bo'yicha",
                   "Measured by the last write in the table")}
        />
      </div>

      <div className="panel">
        <div className="admin-chart-head">
          <div>
            <h2>{t("Блокирующие находки по прогонам", "Prognozlar bo'yicha bloklovchi topilmalar",
                   "Blocking findings by run")}</h2>
            <p>{t(`Последние ${history.length} прогонов аудитора`,
                  `Oxirgi ${history.length} audit`, `Last ${history.length} audit runs`)}</p>
          </div>
        </div>
        {history.length ? <RunHistory runs={history} t={t} /> : (
          <div className="admin-empty">{t("Прогонов пока нет", "Hali prognoz yo'q", "No runs yet")}</div>
        )}
        {latest ? (
          <div className="admin-chart-foot">
            <div><span>{t("Правил в прогоне", "Qoidalar", "Rules run")}</span> <b>{fmtInt(latest.rules_run)}</b></div>
            <div><span>{t("Инструментов", "Vositalar", "Instruments")}</span> <b>{fmtInt(latest.instruments)}</b></div>
            <div><span>{t("Длительность", "Davomiylik", "Duration")}</span> <b>{fmtInt(latest.duration_ms)} мс</b></div>
            <div><span>{t("Статус", "Holat", "Status")}</span> <b>{latest.status}</b></div>
          </div>
        ) : null}
      </div>

      <div className="panel">
        <div className="admin-panel-bar">
          <div className="admin-seg">
            <button type="button" aria-selected="true">
              {t("Требует решения", "Qaror kerak", "Needs a decision")}
              <span className="n">{queue.length}</span>
            </button>
          </div>
          <span className="admin-sp" />
          <button type="button" className="admin-btn sm"
                  onClick={() => onSectionChange && onSectionChange("findings")}>
            {t("Все находки", "Barcha topilmalar", "All findings")}
          </button>
        </div>
        <FindingsTable
          items={queue} rules={rules} t={t} selected={selected}
          onToggle={toggleSelected} onAccept={acceptFindings} busy={busy}
        />
      </div>
    </div>
  );

  /* ── Система · Компании (OpenInfo import review) ─────────────────────── */
  const companyItems = (companyImports && companyImports.items) || [];
  const companySummary = (companyImports && companyImports.summary) || {};
  const sectorTitles = {
    finance: t("Финансы", "Moliya", "Finance"),
    manufacturing: t("Промышленность", "Sanoat", "Manufacturing"),
    mining: t("Добыча", "Konchilik", "Mining"),
    transport: t("Транспорт", "Transport", "Transport"),
    logistics: t("Логистика", "Logistika", "Logistics"),
    telecom: t("Телеком", "Telekom", "Telecom"),
    professional: t("Профессиональные услуги", "Professional xizmatlar", "Professional services"),
    trade: t("Торговля", "Savdo", "Trade"),
    funds: t("Фонды", "Fondlar", "Funds"),
    other: t("Прочее", "Boshqa", "Other"),
  };
  const syncTitle = (value) => ({
    queued: t("в очереди", "navbatda", "queued"),
    running: t("синхронизация", "sinxronlash", "syncing"),
    complete: t("готово", "tayyor", "complete"),
    failed: t("ошибка", "xato", "failed"),
  }[value] || t("не запускалась", "ishga tushmagan", "not started"));

  const companiesBody = (
    <div className="admin-section">
      <div className="admin-stats">
        <Stat label={t("Ждут проверки", "Tekshiruv kutilmoqda", "Awaiting review")}
              value={fmtInt(companySummary.pending)} warn={Boolean(companySummary.pending)}
              line1={t("Обнаружены UZSE/OpenInfo", "UZSE/OpenInfo topdi", "Discovered by UZSE/OpenInfo")} />
        <Stat label={t("Опубликованы", "E'lon qilingan", "Published")}
              value={fmtInt(companySummary.approved)}
              line1={t("Доступны без деплоя", "Deploysiz mavjud", "Available without a deploy")} />
        <Stat label={t("Отклонены", "Rad etilgan", "Rejected")}
              value={fmtInt(companySummary.rejected)}
              line1={t("Сохраняются в журнале", "Jurnalda saqlanadi", "Kept in the audit trail")} />
        <Stat label={t("Без OpenInfo ID", "OpenInfo ID yo'q", "Missing OpenInfo ID")}
              value={fmtInt(companyImports && companyImports.unresolved)}
              warn={Boolean(companyImports && companyImports.unresolved)}
              line1={t("Нельзя публиковать", "E'lon qilib bo'lmaydi", "Cannot be published")} />
      </div>

      <div className="panel admin-company-intake">
        <div className="admin-panel-head">
          <div>
            <h2>{t("Импортировать компанию", "Kompaniyani import qilish", "Import a company")}</h2>
            <p className="admin-muted admin-note">
              {t("Введите тикер — название, ISIN и эмитент будут взяты из UZSE и OpenInfo.",
                 "Tickerni kiriting — nom, ISIN va emitent UZSE va OpenInfo'dan olinadi.",
                 "Enter a ticker; name, ISIN, and issuer are read from UZSE and OpenInfo.")}
            </p>
          </div>
          <button type="button" className="admin-btn" disabled={Boolean(companyBusy)} onClick={discoverCompanies}>
            <Icon name={companyBusy === "discover" ? "clock" : "refresh"} />
            {companyBusy === "discover"
              ? t("Проверяем источники…", "Manbalar tekshirilmoqda…", "Checking sources…")
              : t("Найти новые", "Yangilarini topish", "Discover new")}
          </button>
        </div>
        <form className="admin-company-lookup" onSubmit={(event) => { event.preventDefault(); previewCompany(companyLookup, true); }}>
          <label>
            <span>{t("Тикер", "Ticker", "Ticker")}</span>
            <input className="admin-input" value={companyLookup}
                   onChange={(event) => setCompanyLookup(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
                   placeholder="UZTL" maxLength={40} />
          </label>
          <button type="submit" className="admin-btn accent" disabled={!companyLookup || Boolean(companyBusy)}>
            <Icon name={companyBusy.startsWith("preview:") ? "clock" : "search"} />
            {t("Проверить OpenInfo", "OpenInfo'ni tekshirish", "Check OpenInfo")}
          </button>
        </form>
        {companyNotice ? <div className="admin-company-notice"><span className="admin-dot ok" />{companyNotice}</div> : null}
      </div>

      {companyDraft ? (
        <div className="panel admin-company-review">
          <div className="admin-panel-head">
            <div>
              <div className="panel-label">{t("Предпросмотр источника", "Manba ko'rinishi", "Source preview")}</div>
              <h2>{companyDraft.ticker} · {companyDraft.company_name || t("Без названия", "Nomsiz", "Unnamed")}</h2>
            </div>
            <span className="admin-pill">
              <span className={`admin-dot ${companyDraft.org_id ? "ok" : "err"}`} />
              {companyDraft.org_id ? `OpenInfo ${companyDraft.org_id}` : t("OpenInfo не найден", "OpenInfo topilmadi", "OpenInfo unresolved")}
            </span>
          </div>

          {companyDraft.warnings.length ? (
            <div className="admin-company-warnings">
              {companyDraft.warnings.map((warning) => <span key={warning}><span className="admin-dot warn" />{warning}</span>)}
            </div>
          ) : null}

          <div className="admin-company-form">
            <label className="wide"><span>{t("Официальное название", "Rasmiy nomi", "Official name")}</span>
              <input value={companyDraft.company_name} onChange={(event) => setCompanyDraft({ ...companyDraft, company_name: event.target.value })} /></label>
            <label><span>{t("OpenInfo org ID", "OpenInfo org ID", "OpenInfo org ID")}</span>
              <input value={companyDraft.org_id} onChange={(event) => setCompanyDraft({ ...companyDraft, org_id: event.target.value })} /></label>
            <label><span>ISIN</span>
              <input value={companyDraft.isin} onChange={(event) => setCompanyDraft({ ...companyDraft, isin: event.target.value.toUpperCase() })} /></label>
            <label><span>{t("Сектор", "Sektor", "Sector")}</span>
              <select value={companyDraft.sector} onChange={(event) => setCompanyDraft({ ...companyDraft, sector: event.target.value })}>
                {Object.entries(sectorTitles).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select></label>
            <label><span>{t("Тип бумаги", "Qog'oz turi", "Security type")}</span>
              <select value={companyDraft.security_type} onChange={(event) => setCompanyDraft({ ...companyDraft, security_type: event.target.value })}>
                <option value="stock">{t("Акция", "Aksiya", "Stock")}</option>
                <option value="bond">{t("Облигация", "Obligatsiya", "Bond")}</option>
                <option value="fund">{t("Фонд", "Fond", "Fund")}</option>
                <option value="other">{t("Прочее", "Boshqa", "Other")}</option>
              </select></label>
            <label className="wide"><span>{t("Логотип из OpenInfo", "OpenInfo logotipi", "OpenInfo logo")}</span>
              <div className="admin-company-logo-field">
                {companyDraft.logo_url ? <img src={companyDraft.logo_url} alt="" /> : <span className="admin-company-logo-empty">{companyDraft.ticker.slice(0, 2)}</span>}
                <input value={companyDraft.logo_url} onChange={(event) => setCompanyDraft({ ...companyDraft, logo_url: event.target.value })} placeholder="https://…" />
              </div></label>
            <label className="wide"><span>{t("Причина ручной коррекции", "Qo'lda tuzatish sababi", "Reason for a manual correction")}</span>
              <textarea rows="3" value={companyDraft.review_note} onChange={(event) => setCompanyDraft({ ...companyDraft, review_note: event.target.value })}
                        placeholder={t("Оставьте пустым, если данные источника верны", "Manba to'g'ri bo'lsa bo'sh qoldiring", "Leave blank when the source is correct")} /></label>
          </div>

          <div className="admin-company-actions">
            <button type="button" className="admin-btn accent" disabled={!companyDraft.org_id || Boolean(companyBusy)} onClick={approveCompany}>
              <Icon name={companyBusy.startsWith("approve:") ? "clock" : "check"} />
              {companyDraft.status === "approved"
                ? t("Сохранить и синхронизировать", "Saqlash va sinxronlash", "Save and synchronize")
                : t("Опубликовать и синхронизировать", "E'lon qilish va sinxronlash", "Publish and synchronize")}
            </button>
            {companyDraft.status !== "approved" ? (
              <button type="button" className="admin-btn danger" disabled={Boolean(companyBusy)} onClick={() => rejectCompany(companyDraft)}>
                {t("Отклонить", "Rad etish", "Reject")}
              </button>
            ) : null}
            <button type="button" className="admin-btn" onClick={() => setCompanyDraft(null)}>
              {t("Закрыть", "Yopish", "Close")}
            </button>
          </div>
        </div>
      ) : null}

      <div className="panel">
        <div className="admin-panel-bar">
          <div className="admin-seg">
            {["pending", "approved", "rejected", "all"].map((status) => (
              <button type="button" key={status} aria-selected={companyFilter === status}
                      onClick={() => setCompanyFilter(status)}>
                {status === "pending" ? t("На проверке", "Tekshiruvda", "Pending")
                  : status === "approved" ? t("Опубликованы", "E'lon qilingan", "Published")
                    : status === "rejected" ? t("Отклонены", "Rad etilgan", "Rejected")
                      : t("Все", "Barchasi", "All")}
                {status !== "all" ? <span className="n">{fmtInt(companySummary[status])}</span> : null}
              </button>
            ))}
          </div>
          <span className="admin-sp" />
          <button type="button" className="admin-btn sm" onClick={() => loadCompanyImports(companyFilter)} disabled={Boolean(companyBusy)}>
            <Icon name="refresh" />{t("Обновить", "Yangilash", "Refresh")}
          </button>
        </div>
        <div className="admin-scroll">
          <table className="admin-company-table">
            <thead><tr>
              <th>{t("Компания", "Kompaniya", "Company")}</th>
              <th>{t("Идентификаторы", "Identifikatorlar", "Identifiers")}</th>
              <th>{t("Разрешение", "Moslik", "Resolution")}</th>
              <th>{t("В каталоге", "Katalogda", "In catalog")}</th>
              <th>{t("Синхронизация", "Sinxronlash", "Synchronization")}</th>
              <th className="r">{t("Действие", "Amal", "Action")}</th>
            </tr></thead>
            <tbody>
              {!companyItems.length ? <tr><td colSpan={6}><div className="admin-empty"><b>{t("Список пуст", "Ro'yxat bo'sh", "Nothing here")}</b>{companyFilter === "pending" ? t("Запустите поиск новых компаний.", "Yangi kompaniyalarni qidiring.", "Run discovery to find new companies.") : ""}</div></td></tr> : null}
              {companyItems.map((item) => (
                <tr key={item.ticker}>
                  <td><div className="admin-rule"><code>{item.ticker}</code>{item.company_name}</div><div className="admin-sub">{sectorTitles[item.sector] || item.sector}</div></td>
                  <td className="admin-num"><b>{item.isin || "—"}</b><div className="admin-sub">OpenInfo {item.org_id || "—"}</div></td>
                  <td><span className="admin-pill"><span className={`admin-dot ${item.org_id ? "ok" : "err"}`} />{item.resolved_by || t("не найдено", "topilmadi", "unresolved")}</span></td>
                  <td>
                    {item.status === "approved" ? (
                      <label className="admin-catalog-toggle" title={t("Показывать компанию в публичном каталоге", "Kompaniyani ochiq katalogda ko'rsatish", "Show company in the public catalog")}>
                        <input type="checkbox" checked={item.catalog_visible !== 0}
                          disabled={Boolean(companyBusy)}
                          onChange={(event) => setCompanyVisibility(item, event.target.checked)} />
                        <span>{item.catalog_visible !== 0
                          ? t("Показана", "Ko'rsatilgan", "Visible")
                          : t("Скрыта", "Yashirilgan", "Hidden")}</span>
                      </label>
                    ) : <span className="admin-sub">—</span>}
                  </td>
                  <td><span className="admin-pill" title={item.sync_error || item.catalog_sync_error || ""}><span className={`admin-dot ${item.sync_status === "complete" ? "ok" : item.sync_status === "failed" ? "err" : item.sync_status ? "warn" : ""}`} />{syncTitle(item.sync_status)}</span><div className="admin-sub">{fmtStamp(item.catalog_last_synced_at)}</div></td>
                  <td className="r"><div className="admin-company-row-actions">
                    <button type="button" className="admin-btn sm" disabled={Boolean(companyBusy)} onClick={() => { setCompanyDraft(companyDraftOf(item)); setCompanyLookup(item.ticker); }}>{item.status === "approved" ? t("Изменить", "O'zgartirish", "Edit") : t("Проверить", "Tekshirish", "Review")}</button>
                    {item.status === "approved" ? <button type="button" className="admin-btn sm" disabled={Boolean(companyBusy)} onClick={() => syncCompany(item.ticker)}>{t("Синхр.", "Sinxr.", "Sync")}</button> : null}
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );

  const streamsBody = (
    <div className="admin-section">
      <div className="panel">
        <div className="admin-scroll">
          <table>
            <thead>
              <tr>
                <th>{t("Поток", "Oqim", "Stream")}</th>
                <th style={{ width: 190 }}>{t("Служба", "Xizmat", "Service")}</th>
                <th style={{ width: 176 }}>{t("Расписание", "Jadval", "Schedule")}</th>
                <th style={{ width: 140 }}>{t("Состояние", "Holat", "State")}</th>
                <th className="r" style={{ width: 96 }}>{t("Строк", "Qatorlar", "Rows")}</th>
                <th className="r" style={{ width: 190 }}>{t("Последняя запись", "Oxirgi yozuv", "Last write")}</th>
              </tr>
            </thead>
            <tbody>
              {streams.map((stream) => (
                <tr key={stream.key}>
                  <td>
                    <div className="admin-rule">{stream.title}</div>
                    <div className="admin-sub"><code>{stream.table}</code></div>
                  </td>
                  <td className="admin-num">{stream.service}</td>
                  <td className="admin-num">{stream.schedule}</td>
                  <td>
                    <span className="admin-pill">
                      <span className={`admin-dot ${stream.state === "fresh" ? "ok" : stream.state === "stale" ? "warn" : ""}`} />
                      {stream.state === "fresh"
                        ? t("Свежий", "Yangi", "Fresh")
                        : stream.state === "stale"
                          ? t("Устарел", "Eskirgan", "Stale")
                          : t("Нет записей", "Yozuv yo'q", "Never written")}
                    </span>
                  </td>
                  <td className="r admin-num">{fmtInt(stream.rows)}</td>
                  <td className="r admin-num">
                    {fmtStamp(stream.last_write)}
                    <div className="admin-sub">{fmtAge(stream.age_hours, t)}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );

  const findingsBody = (
    <div className="admin-section">
      <div className="panel">
        <div className="admin-panel-bar">
          <div className="admin-seg">
            {["blocking", "warning", "info"].map((severity) => (
              <button
                key={severity}
                type="button"
                aria-selected={filters.severity === severity}
                onClick={() => setFilters((f) => ({ ...f, severity }))}
              >
                {severity === "blocking"
                  ? t("Блокирующие", "Bloklovchi", "Blocking")
                  : severity === "warning"
                    ? t("Предупреждения", "Ogohlantirish", "Warnings")
                    : t("Информация", "Ma'lumot", "Info")}
                <span className="n">{fmtInt(openCounts[severity])}</span>
              </button>
            ))}
          </div>
          <span className="admin-sp" />
          <button
            type="button"
            className="admin-btn sm"
            onClick={() => setFilters((f) => ({ ...f, status: f.status ? "" : "new" }))}
          >
            {filters.status
              ? t("Показать разобранные", "Ko'rib chiqilganlarni ko'rsatish", "Include triaged")
              : t("Только открытые", "Faqat ochiq", "Open only")}
          </button>
        </div>
        {loading ? <Skeleton rows={4} /> : (
          <>
            <FindingsTable
              items={findings} rules={rules} t={t} selected={selected}
              onToggle={toggleSelected} onAccept={acceptFindings} busy={busy}
            />
            <div className="admin-table-foot">
              <span>
                {t(`Показано ${findings.length}`, `${findings.length} ta ko'rsatildi`,
                   `Showing ${findings.length}`)}
                {selected.size
                  ? t(` · выбрано ${selected.size}`, ` · ${selected.size} tanlandi`,
                      ` · ${selected.size} selected`)
                  : ""}
              </span>
              <span className="admin-sp" />
              <button
                type="button"
                className="admin-btn sm"
                disabled={!selected.size || busy}
                onClick={() => acceptFindings([...selected])}
              >
                <Icon name="check" />
                {t("Принять выбранные", "Tanlanganlarni qabul qilish", "Accept selected")}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );

  /* ── Система · Отчёты (intake) ──────────────────────────────────────────── */
  const intakeRows = useMemo(() => {
    const items = (intake && intake.items) || [];
    return intakeState === "all" ? items : items.filter((r) => r.state === intakeState);
  }, [intake, intakeState]);

  const STATE_TITLE = {
    used: t("в расчёте", "hisobda", "in the calculation"),
    superseded: t("вытеснена свежей", "yangisi bilan almashtirilgan", "superseded"),
    ineligible: t("не допущена", "qabul qilinmagan", "ineligible"),
  };

  const intakeBody = (
    <div className="admin-section">
      <div className="admin-stats">
        <Stat label={t("Записей отчётности", "Hisobot yozuvlari", "Statement records")}
              value={fmtInt(intake && intake.count)}
              line1={intake ? t(`${fmtInt(intake.issuers)} эмитентов`, `${fmtInt(intake.issuers)} emitent`, `${fmtInt(intake.issuers)} issuers`) : null} />
        <Stat label={t("Легли в расчёт", "Hisobga kirdi", "Used")} value={fmtInt(intake && intake.used)}
              line1={t("по одной на эмитента", "har emitentga bittadan", "one per issuer")} />
        <Stat label={t("Вытеснены свежей", "Almashtirilgan", "Superseded")} value={fmtInt(intake && intake.superseded)}
              line1={t("нормальное состояние, не дефект", "normal holat", "normal, not a defect")} />
        <Stat label={t("Не допущены к расчёту", "Qabul qilinmagan", "Ineligible")}
              value={fmtInt(intake && intake.ineligible)}
              warn={!!(intake && intake.ineligible)}
              line1={t("отбрасываются молча — здесь видно", "jimgina tashlab yuboriladi", "dropped silently — visible here")} />
      </div>

      {intake && intake.by_flag && intake.by_flag.length ? (
        <div className="panel admin-flagbar">
          {intake.by_flag.map((f) => (
            <span key={f.flag} className="admin-pill"><span className="admin-dot warn" />{f.title}: {fmtInt(f.count)}</span>
          ))}
        </div>
      ) : null}

      <div className="panel">
        <div className="admin-filters">
          {["ineligible", "used", "superseded", "all"].map((key) => (
            <button key={key} type="button"
                    className={`admin-btn sm${intakeState === key ? " accent" : ""}`}
                    onClick={() => setIntakeState(key)}>
              {key === "all" ? t("Все записи", "Barchasi", "All") : STATE_TITLE[key]}
            </button>
          ))}
          <span className="admin-sp" />
          <span className="admin-muted">{t(`Показано ${intakeRows.length}`, `${intakeRows.length} ta`, `Showing ${intakeRows.length}`)}</span>
        </div>
        <div className="admin-table">
          <table>
            <thead>
              <tr>
                <th>{t("Эмитент", "Emitent", "Issuer")}</th>
                <th>{t("Форма", "Shakl", "Form")}</th>
                <th>{t("Период", "Davr", "Period")}</th>
                <th className="n">{t("Мес.", "Oy", "Mo")}</th>
                <th className="n">{t("Выручка", "Tushum", "Revenue")}</th>
                <th className="n">{t("Прибыль", "Foyda", "Profit")}</th>
                <th className="n">{t("Активы", "Aktivlar", "Assets")}</th>
                <th>{t("Состояние", "Holat", "State")}</th>
                <th>{t("Отметки", "Belgilar", "Flags")}</th>
              </tr>
            </thead>
            <tbody>
              {!intakeRows.length ? (
                <tr>
                  <td colSpan={9} className="admin-muted" style={{ padding: "24px 0", textAlign: "center" }}>
                    {intakeState === "ineligible"
                      ? t("Ни одна запись не отброшена — весь приём дошёл до расчёта.",
                          "Hech bir yozuv tashlab yuborilmagan.",
                          "No record was dropped — the whole intake reached the calculation.")
                      : t("Записей нет.", "Yozuvlar yo'q.", "No records.")}
                  </td>
                </tr>
              ) : null}
              {intakeRows.slice(0, 400).map((r, i) => (
                <tr key={`${r.ticker}-${r.year}-${r.quarter}-${i}`}>
                  <td>
                    <button type="button" className="admin-link"
                            onClick={() => { setLedgerTicker(r.ticker); loadLedger(r.ticker); onSectionChange && onSectionChange("issuer"); }}>
                      {r.ticker}
                    </button>
                  </td>
                  <td className="admin-muted">{r.org_type || r.form || "—"}</td>
                  <td>{r.period || "—"}</td>
                  <td className="n">{r.months == null ? "—" : r.months}</td>
                  <td className="n">{r.revenue == null ? "—" : fmtInt(r.revenue)}</td>
                  <td className="n">{r.net_income == null ? "—" : fmtInt(r.net_income)}</td>
                  <td className="n">{r.total_assets == null ? "—" : fmtInt(r.total_assets)}</td>
                  <td>
                    <span className="admin-pill">
                      <span className={`admin-dot ${r.state === "ineligible" ? "err" : r.state === "used" ? "ok" : ""}`} />
                      {STATE_TITLE[r.state]}
                    </span>
                  </td>
                  <td className="admin-muted">
                    {r.flags.length
                      ? r.flags.map((f) => (intake.by_flag.find((x) => x.flag === f) || {}).title || f).join(" · ")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {intakeRows.length > 400 ? (
          <div className="admin-table-foot">
            <span>{t(`Показаны первые 400 из ${intakeRows.length}`, `${intakeRows.length} tadan birinchi 400 tasi`, `First 400 of ${intakeRows.length}`)}</span>
          </div>
        ) : null}
      </div>
      <p className="admin-muted admin-note">
        {t("Суммы — в тысячах сум, как они хранятся: экран печатает то, что лежит в базе, а не то, на что делит витрина. «Не допущена» означает, что путь чтения отбрасывает запись в SQL и до расчёта она не доходит.",
           "Summalar ming so'mda, bazada saqlanganidek.",
           "Sums are in thousands of UZS, as stored: the screen prints what is in the database, not what the market screen divides by.")}
      </p>
    </div>
  );

  /* ── Система · Эмитент (the TTM ledger) ─────────────────────────────────── */
  const money = (v) => (v == null ? "—" : fmtInt(v));
  const ratio = (m) => (m && m.value != null
    ? fmtNum(m.value, 2)
    : <span className="admin-muted" title={(m && (m.note || m.status)) || ""}>—</span>);

  const issuerBody = (
    <div className="admin-section">
      <div className="panel admin-filters">
        <input
          className="admin-input"
          placeholder={t("Тикер, например UZTL", "Ticker, masalan UZTL", "Ticker, e.g. UZTL")}
          value={ledgerTicker}
          onChange={(e) => setLedgerTicker(e.target.value.toUpperCase())}
          onKeyDown={(e) => { if (e.key === "Enter") loadLedger(ledgerTicker); }}
        />
        <button type="button" className="admin-btn accent" onClick={() => loadLedger(ledgerTicker)}>
          {t("Разобрать", "Tahlil qilish", "Open")}
        </button>
      </div>

      {!ledger ? (
        <div className="panel">
          <div className="admin-empty">
            <b>{t("Выберите эмитента", "Emitentni tanlang", "Pick an issuer")}</b>
            {t("Экран показывает расчёт того же пути, который публикует витрину, — не второй реализации: второй реализации свойственно расходиться с первой, и тогда панель сообщает о собственной ошибке.",
               "Ekran vitrinani e'lon qiladigan yo'lning hisobini ko'rsatadi.",
               "The screen shows the calculation of the same path that publishes the market screen — not a second implementation.")}
          </div>
        </div>
      ) : (
        <>
          <div className="panel">
            <div className="admin-panel-head">
              <h2>{ledger.issuer} · {ledger.ticker}</h2>
              <span className="admin-muted">
                {ledger.form && ledger.form.org_type ? `${ledger.form.org_type} · ` : ""}
                {t("база", "baza", "base")}: {ledger.form && ledger.form.base_period ? ledger.form.base_period : "—"}
              </span>
            </div>

            <div className="admin-ledger">
              <div className="admin-ledger-head">
                <span>{t("Числитель · двенадцать месяцев прибыли", "Numerator", "Numerator · twelve months of profit")}</span>
                <span className="admin-muted">{ledger.ttm && ledger.ttm.method_note}</span>
              </div>
              {((ledger.ttm && ledger.ttm.components) || []).map((c, i) => (
                <div key={i} className={`admin-ledger-row${c.dropped ? " dropped" : ""}`}>
                  <span className="admin-ledger-sign">{c.sign}</span>
                  <span className="admin-ledger-label">
                    <b>{c.label}</b>
                    <span className="admin-muted">
                      {c.period || "—"}{c.months ? ` · ${c.months} ${t("мес.", "oy", "mo")}` : ""}
                      {c.report_id ? ` · report ${c.report_id}` : ""}
                      {c.dropped ? ` · ${t("не вошло в базу", "bazaga kirmadi", "not used")}` : ""}
                    </span>
                  </span>
                  <span className="admin-ledger-val">{money(c.net_income)}</span>
                </div>
              ))}
              <div className="admin-ledger-row total">
                <span className="admin-ledger-sign">=</span>
                <span className="admin-ledger-label">
                  <b>{t("Принято к расчёту", "Hisobga qabul qilindi", "Taken into the calculation")}</b>
                  <span className="admin-muted">{(ledger.ttm && ledger.ttm.period) || "—"}
                    {ledger.ttm && ledger.ttm.estimate ? ` · ${t("ОЦЕНКА", "BAHO", "ESTIMATE")}` : ""}</span>
                </span>
                <span className="admin-ledger-val">
                  {money(ledger.ttm && ledger.ttm.result && ledger.ttm.result.net_income)}
                </span>
              </div>
            </div>
          </div>

          <div className="admin-cols3">
            <div className="panel">
              <h3>{t("Капитализация", "Kapitalizatsiya", "Capitalisation")}</h3>
              <table className="admin-kv">
                <tbody>
                  {(ledger.classes || []).map((c) => (
                    <tr key={c.ticker}>
                      <td>{c.ticker} · {c.share_class === "preferred" ? t("привилег.", "imtiyozli", "preferred") : t("обыкн.", "oddiy", "ordinary")}</td>
                      <td className="n">{c.counted ? money(c.market_cap)
                        : <span className="admin-muted" title={t("Класс ни разу не торговался: цена была бы номиналом из реестра, а капитализация на номинале — вымысел.", "Sinf hech qachon savdo bo'lmagan.", "The class has never traded: its price would be the registry's nominal.")}>{t("не учтён", "hisobga olinmagan", "not counted")}</span>}</td>
                    </tr>
                  ))}
                  <tr className="total">
                    <td><b>{t("По компании", "Kompaniya bo'yicha", "Whole company")}</b></td>
                    <td className="n"><b>{money(ledger.market_cap && ledger.market_cap.value)}</b></td>
                  </tr>
                </tbody>
              </table>
              {ledger.market_cap && ledger.market_cap.note
                ? <p className="admin-muted admin-note">{ledger.market_cap.note}</p> : null}
            </div>

            <div className="panel">
              <h3>{t("Знаменатели · остатки", "Maxrajlar · qoldiqlar", "Denominators · balances")}</h3>
              <table className="admin-kv">
                <tbody>
                  <tr><td>{t("Период баланса", "Balans davri", "Balance period")}</td><td className="n">{(ledger.balance && ledger.balance.period) || "—"}</td></tr>
                  <tr><td>{t("Капитал на конец", "Oxiriga kapital", "Equity, close")}</td><td className="n">{money(ledger.balance && ledger.balance.equity)}</td></tr>
                  <tr><td>{t("Капитал средний", "O'rtacha kapital", "Equity, average")}</td><td className="n">{money(ledger.balance && ledger.balance.equity_avg)}</td></tr>
                  <tr><td>{t("Активы на конец", "Oxiriga aktivlar", "Assets, close")}</td><td className="n">{money(ledger.balance && ledger.balance.assets)}</td></tr>
                  <tr><td>{t("Активы средние", "O'rtacha aktivlar", "Assets, average")}</td><td className="n">{money(ledger.balance && ledger.balance.assets_avg)}</td></tr>
                </tbody>
              </table>
              <p className="admin-muted admin-note">{ledger.balance && ledger.balance.rule}</p>
            </div>

            <div className="panel">
              <h3>{t("Проверки", "Tekshiruvlar", "Validations")}</h3>
              <div className="admin-checklist">
                {Object.entries((ledger.checks && ledger.checks.results) || {}).map(([code, ok]) => (
                  <div key={code}>
                    <span className="admin-pill"><span className={`admin-dot ${ok ? "ok" : "err"}`} />{code}</span>
                  </div>
                ))}
                {!Object.keys((ledger.checks && ledger.checks.results) || {}).length
                  ? <span className="admin-muted">{t("Тождества не проверялись: не хватает входов.", "Tekshirilmadi.", "Not checked: inputs missing.")}</span>
                  : null}
              </div>
              {ledger.validation && ledger.validation.reason
                ? <p className="admin-muted admin-note">{ledger.validation.reason}</p> : null}
            </div>
          </div>

          <div className="panel">
            <h3>{t("Показатели", "Ko'rsatkichlar", "Multiples")}</h3>
            <div className="admin-table">
              <table>
                <thead>
                  <tr>
                    <th>{t("Показатель", "Ko'rsatkich", "Metric")}</th>
                    <th>{t("Формула", "Formula", "Formula")}</th>
                    <th className="n">{t("Числитель", "Surat", "Numerator")}</th>
                    <th className="n">{t("Знаменатель", "Maxraj", "Denominator")}</th>
                    <th className="n">{t("Значение", "Qiymat", "Value")}</th>
                    <th className="n">{t("На витрине", "Vitrinada", "Published")}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(ledger.inputs || {}).map(([name, b]) => (
                    <tr key={name}>
                      <td><b>{name.toUpperCase().replace("_", " ")}</b></td>
                      <td className="admin-muted">{b.formula}</td>
                      <td className="n">{money(b.numerator)}</td>
                      <td className="n">{money(b.denominator)}</td>
                      <td className="n">{b.value == null
                        ? <span className="admin-muted" title={b.note || b.status || ""}>—</span>
                        : fmtNum(b.value, 2)}</td>
                      <td className="n">{ratio(ledger.published && ledger.published[name])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="admin-muted admin-note">
              {t("Обе колонки приходят из одного вызова: расхождение здесь — ошибка этого экрана, а не рынка, и её тоже стоит видеть.",
                 "Ikkala ustun bitta chaqiruvdan keladi.",
                 "Both columns come from one call: a difference here is a bug in this screen, not in the market — and worth seeing too.")}
            </p>
          </div>
        </>
      )}
    </div>
  );

  /* ── Система · Правила ──────────────────────────────────────────────────── */
  const rulesBody = (
    <div className="admin-section">
      <div className="panel">
        <h3>{t("Граница ответственности", "Javobgarlik chegarasi", "The boundary")}</h3>
        <div className="admin-cols2">
          <div>
            <div className="panel-label">{t("Через панель", "Panel orqali", "Through the panel")}</div>
            <ul className="admin-list">
              {((ruleBook && ruleBook.boundary && ruleBook.boundary.panel) || []).map((x) => <li key={x}>{x}</li>)}
            </ul>
          </div>
          <div>
            <div className="panel-label">{t("Через PR с прогоном валидаций", "PR orqali", "Through a pull request")}</div>
            <ul className="admin-list">
              {((ruleBook && ruleBook.boundary && ruleBook.boundary.code) || []).map((x) => <li key={x}>{x}</li>)}
            </ul>
          </div>
        </div>
        <p className="admin-muted admin-note">{ruleBook && ruleBook.boundary && ruleBook.boundary.why}</p>
      </div>

      <div className="panel">
        <h3>{t("Пороги и диапазоны", "Chegara va oraliqlar", "Thresholds and ranges")}</h3>
        <div className="admin-table">
          <table>
            <thead>
              <tr>
                <th>{t("Параметр", "Parametr", "Parameter")}</th>
                <th className="n">{t("Значение", "Qiymat", "Value")}</th>
                <th>{t("Где задан", "Qayerda", "Owner")}</th>
                <th>{t("Что делает", "Nima qiladi", "What it does")}</th>
              </tr>
            </thead>
            <tbody>
              {((ruleBook && ruleBook.thresholds) || []).map((r) => (
                <tr key={r.name}>
                  <td>{r.name}</td>
                  <td className="n">{String(r.value)}</td>
                  <td className="admin-muted">{r.owner}</td>
                  <td className="admin-muted">{r.note || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );

  /* ── Система · Источник ─────────────────────────────────────────────────── */
  const cal = (source && source.calendar) || null;
  const probe = (source && source.probe) || null;
  const sourceBody = (
    <div className="admin-section">
      <div className="admin-stats">
        <Stat label={t("Ожидаемый период", "Kutilayotgan davr", "Expected period")}
              value={(cal && cal.expected) || DASH}
              line1={cal ? t(`окно ${cal.window_opens} — ${cal.window_closes}`,
                             `oyna ${cal.window_opens} — ${cal.window_closes}`,
                             `window ${cal.window_opens} — ${cal.window_closes}`) : null} />
        <Stat label={t("Сдали", "Topshirdi", "Filed")} value={fmtInt(cal && cal.filed)}
              line1={cal ? t(`из ${fmtInt(cal.issuers)} эмитентов`, `${fmtInt(cal.issuers)} tadan`, `of ${fmtInt(cal.issuers)} issuers`) : null} />
        <Stat label={t("Просрочили", "Kechikdi", "Late")} value={fmtInt(cal && cal.late)}
              warn={!!(cal && cal.late)}
              line1={cal && cal.overdue_days
                ? t(`окно закрылось ${cal.overdue_days} дн. назад`, `${cal.overdue_days} kun oldin`, `window closed ${cal.overdue_days} d ago`)
                : t("окно ещё открыто", "oyna ochiq", "the window is still open")} />
        <Stat label={t("Молчат больше года", "Bir yildan ortiq jim", "Quiet over a year")}
              value={fmtInt(cal && cal.silent)} warn={!!(cal && cal.silent)}
              line1={t("это факт об эмитенте", "bu emitent haqidagi fakt", "a fact about the issuer")} />
      </div>

      <div className="panel">
        <h3>{t("Доступность источника", "Manba mavjudligi", "Source availability")}</h3>
        <p className="admin-muted admin-note" style={{ marginTop: 0 }}>
          {probe
            ? `${probe.verdict} · ${t("доступно", "mavjud", "reachable")} ${probe.reachable}, ${t("недоступно", "mavjud emas", "failed")} ${probe.failed}`
            : t("Проба не выполнялась.", "Sinov bajarilmadi.", "The probe did not run.")}
        </p>
        <div className="admin-table">
          <table>
            <thead>
              <tr>
                <th>{t("Класс запроса", "So'rov sinfi", "Endpoint class")}</th>
                <th className="n">{t("Ответ, мс", "Javob, ms", "Response, ms")}</th>
                <th className="n">{t("Код", "Kod", "Code")}</th>
                <th>{t("Состояние", "Holat", "State")}</th>
              </tr>
            </thead>
            <tbody>
              {((probe && probe.steps) || []).map((sres) => (
                <tr key={sres.name}>
                  <td className="mono">{sres.name}</td>
                  <td className="n">{fmtInt(sres.elapsed_ms)}</td>
                  <td className="n">{sres.status_code || DASH}</td>
                  <td>
                    <span className="admin-pill" title={sres.error || ""}>
                      <span className={`admin-dot ${sres.ok ? "ok" : "err"}`} />
                      {sres.ok ? t("ок", "ok", "ok") : (sres.error ? String(sres.error).slice(0, 48) : t("сбой", "xato", "failed"))}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="admin-muted admin-note">
          {t("Проба идёт с этого же хоста и тем же клиентом, что и сборщик, — иначе она отвечала бы на другой вопрос. Недоступность одного класса при доступности остальных означает не «openinfo лежит», а что отвалился конкретный эндпоинт.",
             "Sinov kollektor bilan bir xil xost va mijozdan boradi.",
             "The probe runs from the same host and with the same client as the collector — otherwise it would be answering a different question.")}
        </p>
      </div>

      <div className="panel">
        <h3>{t("Календарь отчётности", "Hisobot taqvimi", "The reporting calendar")}</h3>
        <div className="admin-table">
          <table>
            <thead>
              <tr>
                <th>{t("Эмитент", "Emitent", "Issuer")}</th>
                <th>{t("Ожидается", "Kutilmoqda", "Expected")}</th>
                <th>{t("Последний поданный", "Oxirgi topshirilgan", "Latest filed")}</th>
                <th className="n">{t("Кварталов позади", "Chorak orqada", "Quarters behind")}</th>
                <th className="n">{t("Просрочка, дн.", "Kechikish, kun", "Overdue, d")}</th>
                <th>{t("Статус", "Holat", "State")}</th>
              </tr>
            </thead>
            <tbody>
              {((cal && cal.items) || []).map((r) => (
                <tr key={r.ticker}>
                  <td>
                    <button type="button" className="admin-link"
                            onClick={() => { setLedgerTicker(r.ticker); loadLedger(r.ticker); onSectionChange && onSectionChange("issuer"); }}>
                      {r.ticker}
                    </button>
                  </td>
                  <td>{r.expected}</td>
                  <td>{r.latest}</td>
                  <td className="n">{r.quarters_behind || DASH}</td>
                  <td className="n">{r.overdue_days || DASH}</td>
                  <td>
                    <span className="admin-pill">
                      <span className={`admin-dot ${r.state === "сдан" ? "ok" : r.state === "молчит" ? "err" : r.state === "просрочен" ? "warn" : ""}`} />
                      {r.state}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="admin-muted admin-note">
          {t("Окно раскрытия открывается на 25-й день после закрытия квартала и держится 45 дней. Пока оно открыто, отсутствие отчёта — «ожидается», а не «просрочен»: между «ещё не подал» и «перестал подавать» разница принципиальная, и складывать их в одну кучу значит прятать второе за первым.",
             "Oshkoralik oynasi chorak yopilgandan 25 kun keyin ochiladi va 45 kun turadi.",
             "The disclosure window opens on the 25th day after the quarter closes and runs 45 days. While it is open, a missing report is «expected», not «late».")}
        </p>
      </div>
    </div>
  );

  /* ── Система · Качество данных ─────────────────────────────────────────── */
  const qualityIssueRecords = quality?.items || [];
  const qualityOpenIssues = qualityIssueRecords.filter(item => item.status === "open");
  const qualityIssues = qualitySelectedTicker
    ? qualityOpenIssues.filter((item) => (item.issuer_tickers || [item.ticker])
      .some((ticker) => String(ticker).toUpperCase() === qualitySelectedTicker))
    : qualityOpenIssues;
  const qualityCorrectionsRows = qualityCorrections?.items || [];
  const qualityIssuerNames = Object.fromEntries(qualityIssueRecords.map(item => [item.ticker, item.issuer_name || item.ticker]));
  const fixedQualityCompanies = Object.values(qualityCorrectionsRows
    .filter(record => record.status === "approved")
    .reduce((groups, record) => {
      const key = `${record.ticker}:${record.year}:${record.quarter || 0}`;
      const group = groups[key] || {
        key, ticker: record.ticker, issuerName: qualityIssuerNames[record.ticker] || record.ticker,
        year: record.year, quarter: record.quarter || 0, fields: [], reviewedAt: record.reviewed_at || record.created_at,
      };
      group.fields.push(record.field);
      if (String(record.reviewed_at || record.created_at || "") > String(group.reviewedAt || "")) group.reviewedAt = record.reviewed_at || record.created_at;
      groups[key] = group;
      return groups;
    }, {}))
    .sort((a, b) => String(b.reviewedAt || "").localeCompare(String(a.reviewedAt || "")))
    .slice(0, 6);
  const qualityIssueExplanation = (issue) => {
    const details = issue.details && typeof issue.details === "object" ? issue.details : {};
    const values = details.observed_values || {};
    if (issue.rule_code === "BALANCE_MISMATCH" && ["total_assets", "total_equity", "total_liabilities"].every(key => values[key] !== null && values[key] !== undefined)) {
      const difference = Number(details.difference_thousands_uzs ?? (Number(values.total_assets) - Number(values.total_equity) - Number(values.total_liabilities)));
      const direction = difference > 0
        ? t("Активы больше суммы капитала и обязательств", "Aktivlar kapital va majburiyatlar yig'indisidan katta", "Assets exceed equity plus liabilities")
        : t("Активы меньше суммы капитала и обязательств", "Aktivlar kapital va majburiyatlar yig'indisidan kichik", "Assets are below equity plus liabilities");
      return t(`Активы: ${fmtNum(values.total_assets)}; капитал: ${fmtNum(values.total_equity)}; обязательства: ${fmtNum(values.total_liabilities)} тыс. UZS. ${direction} на ${fmtNum(Math.abs(difference))} тыс. UZS.`,
        `Aktivlar: ${fmtNum(values.total_assets)}; kapital: ${fmtNum(values.total_equity)}; majburiyatlar: ${fmtNum(values.total_liabilities)} ming UZS. Farq: ${fmtNum(Math.abs(difference))} ming UZS.`,
        `Assets: ${fmtNum(values.total_assets)}; equity: ${fmtNum(values.total_equity)}; liabilities: ${fmtNum(values.total_liabilities)} thousand UZS. Difference: ${fmtNum(Math.abs(difference))} thousand UZS.`);
    }
    if (issue.rule_code === "MISSING_FINANCIAL_FIELD") return t(`В распознанном отчёте нет значения поля «${issue.field}».`, `Tanib olingan hisobotda «${issue.field}» maydoni qiymati yo'q.`, `The parsed filing has no value for “${issue.field}”.`);
    if (issue.rule_code === "UNRESOLVED_ISSUER") return t("Для тикера не найдена привязка к эмитенту.", "Tiker uchun emitent bog'lanishi topilmadi.", "No issuer mapping was found for this ticker.");
    if (issue.rule_code === "MISSING_FINANCIAL_COVERAGE") return t("В каталоге нет финансового отчёта NSBU.", "Katalogda NSBU moliyaviy hisoboti yo'q.", "No NSBU financial record is available in the catalog.");
    if (issue.rule_code === "MISSING_REPORT_COVERAGE") return t("К тикеру не прикреплён исходный отчёт.", "Tikerga manba hisoboti biriktirilmagan.", "No source report is linked to this ticker.");
    return String(details.message || t("Требуется проверка источника.", "Manbani tekshirish kerak.", "Source verification is required."));
  };
  const beginCorrection = (issue = {}) => setQualityDraft({
    ticker: issue.ticker || "", form: issue.form || "NSBU", year: issue.year || new Date().getFullYear(),
    quarter: issue.quarter || 0, field: issue.field || "", value_thousands_uzs: "",
    source_url: "", source_reference: "", reason: "", evidenceMissing: true,
  });
  const openSuggestedCorrection = async (issue) => {
    const busyKey = `suggest:${issue.id}`;
    setQualityBusy(busyKey); setError("");
    try {
      const proposal = await readJson(`/api/admin/data-quality/issues/${encodeURIComponent(issue.id)}/suggestion`);
      const recommended = proposal.recommended;
      const evidence = proposal.evidence || {};
      setQualityDraft({
        ticker: issue.ticker || "", form: issue.form || "NSBU", year: issue.year || new Date().getFullYear(),
        quarter: issue.quarter || 0, field: recommended?.field || issue.field || "",
        value_thousands_uzs: recommended ? String(recommended.value_thousands_uzs) : "",
        source_url: evidence.source_url || "", source_reference: evidence.source_reference || "",
        reason: proposal.reason || "", suggestion: proposal.message || "", evidenceMissing: !evidence.available,
        alternatives: proposal.alternatives || [],
      });
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  };
  const qualityCompanyUrl = (issue) => {
    const params = new URLSearchParams({
      tab: "financials", freq: "quarterly", qualityIssue: String(issue.rule_code || ""),
      qualityPeriod: issue.year ? `${issue.year}Q${issue.quarter || 4}` : "",
      qualityField: String(issue.field || ""),
    });
    return `/company/${encodeURIComponent(issue.ticker)}?${params.toString()}`;
  };
  const qualityBody = (
    <div className="admin-section">
      <div className="panel admin-panel-head">
        <div><h2>{t("Очередь качества данных", "Ma'lumotlar sifati navbati", "Data-quality queue")}</h2>
          <p className="admin-muted" style={{ margin: "4px 0 0" }}>{t("Выберите компанию: «Обновить отчёты» повторно импортирует официальный источник, «Исправить» меняет только проверенное значение с записью в журнале.", "Kompaniyani tanlang: «Hisobotlarni yangilash» rasmiy manbani qayta import qiladi, «Tuzatish» esa faqat tekshirilgan qiymatni jurnalga yozib o'zgartiradi.", "Choose a company: “Refresh reports” re-imports the official source; “Correct” changes only a verified value with an audit record.")}</p></div>
        <div className="admin-head-actions"><div className="admin-quality-picker"><input className="admin-input" value={qualityTicker} onChange={e => { setQualityTicker(e.target.value); setQualitySelectedTicker(""); setQualitySuggestionsOpen(true); }} onFocus={() => qualityTicker.trim() && setQualitySuggestionsOpen(true)} onKeyDown={(event) => { if (event.key === "Enter" && qualitySuggestions[0]) { event.preventDefault(); const match = qualitySuggestions[0]; setQualityTicker(match.ticker); setQualitySelectedTicker(match.ticker); setQualitySuggestionsOpen(false); } }} placeholder={t("Тикер или компания", "Tiker yoki kompaniya", "Ticker or company")} aria-label={t("Поиск компании", "Kompaniya qidiruvi", "Company search")} autoComplete="off" />
          {qualitySuggestionsOpen && (qualitySearchLoading || qualitySuggestions.length > 0) && <div className="admin-quality-suggestions" role="listbox">{qualitySearchLoading && <div className="admin-quality-search-state">{t("Поиск…", "Qidirilmoqda…", "Searching…")}</div>}{qualitySuggestions.map(company => <button type="button" role="option" key={company.ticker} onMouseDown={event => event.preventDefault()} onClick={() => { setQualityTicker(company.ticker); setQualitySelectedTicker(company.ticker); setQualitySuggestionsOpen(false); }}><b>{company.ticker}</b><span>{company.company_name || company.ticker}</span></button>)}</div>}</div>
          <button type="button" className="admin-btn accent" disabled={!qualitySelectedTicker || qualityBusy === `refresh:${qualitySelectedTicker}`} onClick={() => refreshQualityCompanyReporting(qualitySelectedTicker)}>{qualityBusy === `refresh:${qualitySelectedTicker}` ? t("Обновление отчётов…", "Hisobotlar yangilanmoqda…", "Refreshing reports…") : t("Обновить отчёты", "Hisobotlarni yangilash", "Refresh reports")}</button><button type="button" className="admin-btn" disabled={!qualitySelectedTicker || qualityBusy === `analysis:${qualitySelectedTicker}`} onClick={() => scanQualityCompany(qualitySelectedTicker)}>{qualityBusy === `analysis:${qualitySelectedTicker}` ? t("Проверка…", "Tekshirilmoqda…", "Checking…") : t("Проверить компанию", "Kompaniyani tekshirish", "Check company")}</button><button type="button" className="admin-btn" onClick={() => beginCorrection()}>{t("Новое исправление", "Yangi tuzatish", "New correction")}</button>
        </div>
      </div>
      {qualityNotice && <div className="admin-quality-fixed" role="status"><div className="admin-quality-fixed-title">✓ {t("Официальные данные обновлены", "Rasmiy ma'lumotlar yangilandi", "Official data refreshed")}</div><div>{qualityNotice}</div></div>}

      {qualityDraft && <form className="panel admin-company-form" onSubmit={submitQualityCorrection}>
        <div className="admin-panel-head"><div><h2>{t("Черновик исправления", "Tuzatish qoralamasi", "Correction draft")}</h2><p className="admin-muted">{qualityDraft.evidenceMissing ? t("Для этого периода в каталоге нет ссылки на официальный отчёт — добавьте её вручную.", "Bu davr uchun katalogda rasmiy hisobot havolasi yo'q — uni qo'lda qo'shing.", "No official-report link is stored for this period; add one manually.") : t("Значение, источник и обоснование подставлены автоматически. При необходимости их можно изменить.", "Qiymat, manba va asos avtomatik to'ldirildi. Zarur bo'lsa, o'zgartirish mumkin.", "Value, source and rationale were filled automatically. You can edit them if needed.")}</p></div><button type="button" className="admin-btn" onClick={() => setQualityDraft(null)}>{t("Закрыть", "Yopish", "Close")}</button></div>
        {qualityDraft.suggestion && <div className="admin-note"><b>{t("Автоподсказка — требуется подтверждение", "Avto-taklif — tasdiqlash kerak", "Automatic proposal — confirmation required")}</b><br />{qualityDraft.suggestion}<br /><span className="admin-muted">{t("Поле и значение ниже можно изменить вручную. Официальный источник обязателен.", "Quyidagi maydon va qiymatni qo'lda o'zgartirish mumkin. Rasmiy manba majburiy.", "You can edit the field and value below. Official evidence is still required.")}</span>{qualityDraft.alternatives?.length > 1 && <div className="admin-company-row-actions" style={{ marginTop: 10 }}>{qualityDraft.alternatives.map(option => <button type="button" className="admin-btn" key={option.field} onClick={() => setQualityDraft(old => ({ ...old, field: option.field, value_thousands_uzs: String(option.value_thousands_uzs) }))}>{option.field}: {fmtNum(option.value_thousands_uzs)}</button>)}</div>}</div>}
        {[['ticker', t("Тикер", "Tiker", "Ticker")], ['year', t("Год", "Yil", "Year")], ['quarter', t("Квартал (0=годовой)", "Chorak (0=yillik)", "Quarter (0=annual)")], ['field', t("Поле", "Maydon", "Field")], ['value_thousands_uzs', t("Значение, тыс. UZS", "Qiymat, ming UZS", "Value, thousand UZS")], ['source_url', t("Ссылка на источник", "Manba havolasi", "Evidence URL")], ['source_reference', t("Строка / страница источника", "Manba qatori / sahifasi", "Source line / page")], ['reason', t("Причина", "Sabab", "Reason")]].map(([key, label]) => <label className={['source_url', 'source_reference', 'reason'].includes(key) ? 'wide' : ''} key={key}><span>{label}</span>{key === 'field' ? <select required value={qualityDraft.field} onChange={e => setQualityDraft(old => ({ ...old, field: e.target.value }))}><option value="" disabled>{t("Выберите поле", "Maydonni tanlang", "Choose field")}</option>{['revenue', 'gross_profit', 'cash', 'total_liabilities', 'net_income', 'operating_income', 'total_assets', 'total_equity', 'current_assets', 'current_liabilities', 'inventories'].map(field => <option key={field}>{field}</option>)}</select> : key === 'reason' ? <textarea required value={qualityDraft[key]} onChange={e => setQualityDraft(old => ({ ...old, [key]: e.target.value }))} /> : <input required={key !== 'quarter'} type={['year', 'quarter', 'value_thousands_uzs'].includes(key) ? 'number' : key === 'source_url' ? 'url' : 'text'} step={key === 'value_thousands_uzs' ? 'any' : undefined} value={qualityDraft[key]} onChange={e => setQualityDraft(old => ({ ...old, [key]: e.target.value }))} />}</label>)}
        <div className="admin-company-actions"><button className="admin-btn accent" disabled={qualityBusy === 'create'}>{qualityBusy === 'create' ? t("Исправление…", "Tuzatilmoqda…", "Applying…") : t("Применить исправление", "Tuzatishni qo'llash", "Apply correction")}</button></div>
      </form>}

      {!!fixedQualityCompanies.length && <div className="admin-quality-fixed" role="status">
        <div className="admin-quality-fixed-title">✓ {t("Недавно исправлено", "Yaqinda tuzatildi", "Recently fixed")}</div>
        <div className="admin-quality-fixed-list">{fixedQualityCompanies.map(company => <div className="admin-quality-fixed-item" key={company.key}>
          <b>{company.issuerName}</b> <span className="admin-muted">· {company.ticker} · {company.year}Q{company.quarter || 4}</span>
          <div>{t("Исправлены поля", "Tuzatilgan maydonlar", "Corrected fields")}: {company.fields.join(", ")}. {t("Значения уже используются на сайте.", "Qiymatlar saytda allaqachon qo'llanmoqda.", "The corrected values are already used on the site.")}</div>
        </div>)}</div>
      </div>}

      <div className="panel"><div className="admin-panel-head"><h3>{t("Открытые проверки", "Ochiq tekshiruvlar", "Open checks")} <span className="admin-muted">· {fmtInt(qualityIssues.length)}</span></h3>{qualitySelectedTicker && <div className="admin-company-row-actions"><span className="admin-muted">{t(`Показана компания: ${qualitySelectedTicker}`, `Ko'rsatilgan kompaniya: ${qualitySelectedTicker}`, `Showing company: ${qualitySelectedTicker}`)}</span><button type="button" className="admin-btn" onClick={() => { setQualityTicker(""); setQualitySelectedTicker(""); }}>{t("Сбросить", "Tozalash", "Clear")}</button></div>}</div>
        {!qualityIssues.length ? <div className="admin-empty"><b>{t("Очередь пуста", "Navbat bo'sh", "The queue is empty")}</b>{t("Запустите сканирование после синхронизации каталога.", "Katalog sinxronlangach skanerlashni ishga tushiring.", "Run a scan after catalog synchronization.")}</div> : <div className="admin-scroll"><table><thead><tr><th>{t("Эмитент / тикеры", "Emitent / tikerlar", "Issuer / tickers")}</th><th>{t("Период", "Davr", "Period")}</th><th>{t("Проверка", "Tekshiruv", "Check")}</th><th>{t("Что не так", "Nima noto'g'ri", "What is wrong")}</th><th>{t("Поле", "Maydon", "Field")}</th><th>{t("Приоритет", "Ustuvorlik", "Severity")}</th><th /></tr></thead><tbody>{qualityIssues.map(issue => <tr key={issue.id}><td><b>{issue.issuer_name || issue.ticker}</b><div className="admin-muted">{(issue.issuer_tickers || [issue.ticker]).join(" · ")}</div></td><td>{issue.year ? `${issue.year}Q${issue.quarter || 4}` : DASH}</td><td>{issue.rule_code}</td><td className="admin-muted">{qualityIssueExplanation(issue)}</td><td>{issue.field || DASH}</td><td><span className="admin-pill"><span className={`admin-dot ${issue.severity === 'blocking' ? 'err' : 'warn'}`} />{issue.severity}</span></td><td className="admin-company-row-actions">{issue.details?.source_url && <a className="admin-btn" href={issue.details.source_url} target="_blank" rel="noreferrer">{t("Исходный отчёт", "Asl hisobot", "Source report")}</a>}<a className="admin-btn" href={qualityCompanyUrl(issue)} target="_blank" rel="noreferrer">{t("Открыть на сайте", "Saytda ochish", "Open on site")}</a>{["financials", "coverage"].includes(issue.dataset) && <button type="button" className="admin-btn accent" disabled={qualityBusy === `refresh:${issue.ticker}`} onClick={() => refreshQualityCompanyReporting(issue.ticker)}>{qualityBusy === `refresh:${issue.ticker}` ? t("Обновление…", "Yangilanmoqda…", "Refreshing…") : t("Обновить отчёт", "Hisobotni yangilash", "Refresh report")}</button>}{issue.rule_code === 'UNRESOLVED_ISSUER' && <button type="button" className="admin-btn accent" disabled={qualityBusy === `issuer:${issue.id}`} onClick={() => fixIssuerMapping(issue)}>{qualityBusy === `issuer:${issue.id}` ? t("Открытие…", "Ochilyapti…", "Opening…") : t("Исправить эмитента", "Emitentni tuzatish", "Fix issuer")}</button>}{issue.rule_code === 'BLOCKED_UNIT_MISMATCH' && <button type="button" className="admin-btn accent" disabled={qualityBusy === `scale:${issue.id}`} onClick={() => autoApplyUnitScale(issue)}>{qualityBusy === `scale:${issue.id}` ? t("Исправление…", "Tuzatilmoqda…", "Applying…") : t("Исправить масштаб", "Masshtabni tuzatish", "Fix scale")}</button>}{issue.dataset === 'financials' && <button type="button" className="admin-btn accent" disabled={qualityBusy === `apply:${issue.id}`} onClick={() => autoApplyQualityIssue(issue)}>{qualityBusy === `apply:${issue.id}` ? t("Исправление…", "Tuzatilmoqda…", "Applying…") : t("Исправить", "Tuzatish", "Correct")}</button>}<button type="button" className="admin-btn" disabled={qualityBusy === `analysis:${issue.ticker}`} onClick={() => scanQualityCompany(issue.ticker)}>{qualityBusy === `analysis:${issue.ticker}` ? t("Проверка…", "Tekshirilmoqda…", "Checking…") : t("Проверить компанию", "Kompaniyani tekshirish", "Check company")}</button></td></tr>)}</tbody></table></div>}
      </div>

      <div className="panel"><h3>{t("Журнал исправлений", "Tuzatishlar jurnali", "Correction history")}</h3>
        {!qualityCorrectionsRows.length ? <p className="admin-muted">{t("Пока нет исправлений.", "Hali tuzatishlar yo'q.", "No corrections yet.")}</p> : <div className="admin-scroll"><table><thead><tr><th>{t("Эмитент", "Emitent", "Ticker")}</th><th>{t("Период", "Davr", "Period")}</th><th>{t("Поле", "Maydon", "Field")}</th><th>{t("Статус", "Holat", "Status")}</th><th>{t("Источник", "Manba", "Evidence")}</th><th /></tr></thead><tbody>{qualityCorrectionsRows.map(record => <tr key={record.id}><td>{record.ticker}</td><td>{record.year}Q{record.quarter || 4}</td><td>{record.field}</td><td>{record.status}</td><td><a className="admin-link" href={record.source_url} target="_blank" rel="noreferrer">{record.source_reference}</a></td><td className="admin-company-row-actions">{record.status === 'draft' && <><button className="admin-btn accent" disabled={qualityBusy === record.id} onClick={() => reviewQualityCorrection(record.id, 'approved')}>{t("Подтвердить", "Tasdiqlash", "Approve")}</button><button className="admin-btn" disabled={qualityBusy === record.id} onClick={() => reviewQualityCorrection(record.id, 'rejected')}>{t("Отклонить", "Rad etish", "Reject")}</button></>}{record.status === 'approved' && <button className="admin-btn danger" disabled={qualityBusy === record.id} onClick={() => reviewQualityCorrection(record.id, 'reverted')}>{t("Отменить", "Bekor qilish", "Revert")}</button>}</td></tr>)}</tbody></table></div>}
      </div>
    </div>
  );

  const feedbackRows = feedbackData?.items || [];
  const feedbackStatusLabel = (status) => ({
    open: t("Новое", "Yangi", "New"),
    in_progress: t("В работе", "Jarayonda", "In progress"),
    resolved: t("Закрыто", "Yopilgan", "Resolved"),
  }[status] || status);
  const feedbackBody = (
    <div className="admin-section">
      <div className="panel">
        <div className="admin-panel-head">
          <div><h2>{t("Входящие сообщения", "Kiruvchi xabarlar", "Incoming messages")}</h2>
            <p className="admin-muted" style={{ margin: "4px 0 0" }}>{t("Отзывы, идеи и обращения из формы «Обратная связь».", "Fikrlar, g'oyalar va murojaatlar.", "Feedback, ideas, and requests sent through the Feedback form.")}</p></div>
          <div className="admin-seg">
            {[["", t("Все", "Barchasi", "All")], ["open", t("Новые", "Yangi", "New")], ["in_progress", t("В работе", "Jarayonda", "In progress")], ["resolved", t("Закрытые", "Yopilgan", "Resolved")]].map(([key, label]) => (
              <button key={key || "all"} type="button" aria-selected={feedbackFilter === key}
                onClick={() => setFeedbackFilter(key)}>{label}</button>
            ))}
          </div>
        </div>
        {!feedbackRows.length ? <div className="admin-empty">{t("Сообщений пока нет.", "Hozircha xabarlar yo'q.", "No feedback yet.")}</div> : (
          <div className="admin-scroll"><table><thead><tr>
            <th style={{ width: 155 }}>{t("Когда", "Vaqt", "When")}</th>
            <th style={{ width: 220 }}>{t("Пользователь", "Foydalanuvchi", "User")}</th>
            <th>{t("Сообщение", "Xabar", "Message")}</th>
            <th style={{ width: 160 }}>{t("Статус", "Holat", "Status")}</th>
          </tr></thead><tbody>{feedbackRows.map((item) => <tr key={item.id}>
            <td className="admin-num">{fmtStamp(item.created_at)}</td>
            <td><b>{item.full_name || t("Без имени", "Ismsiz", "No name")}</b><div className="admin-sub">{item.email}</div></td>
            <td><b>{item.subject}</b><div style={{ marginTop: 6, whiteSpace: "pre-wrap", lineHeight: 1.45 }}>{item.message}</div></td>
            <td><span className="admin-pill"><span className={`admin-dot ${item.status === "resolved" ? "ok" : item.status === "open" ? "warn" : ""}`} />{feedbackStatusLabel(item.status)}</span>
              <select aria-label={t("Изменить статус", "Holatni o'zgartirish", "Change status")} value={item.status}
                disabled={feedbackBusy === item.id} onChange={(event) => updateFeedbackStatus(item.id, event.target.value)}
                style={{ display: "block", marginTop: 8, width: "100%" }}>
                <option value="open">{feedbackStatusLabel("open")}</option><option value="in_progress">{feedbackStatusLabel("in_progress")}</option><option value="resolved">{feedbackStatusLabel("resolved")}</option>
              </select></td>
          </tr>)}</tbody></table></div>
        )}
      </div>
    </div>
  );

  const bodyBySection = {
    overview: overviewBody,
    audience: audienceBody,
    engagement: engagementBody,
    analysis: analysisBody,
    users: usersBody,
    feedback: feedbackBody,
    system: dataBody,
    railway: <RailwayPanel readJson={readJson} t={t} />,
    companies: companiesBody,
    streams: streamsBody,
    findings: findingsBody,
    intake: intakeBody,
    issuer: issuerBody,
    rules: rulesBody,
    source: sourceBody,
    quality: qualityBody,
  };

  return (
    <div className="admin-view">
      <IconSprite />

      <div className="admin-head">
        <div className="admin-head-copy">
          <div className="panel-label">{t("Служебное", "Xizmat", "Internal")}</div>
          <h1>{t("Администрирование", "Administratsiya", "Administration")}</h1>
          <p>{SECTION_LEDE[section] || SECTION_LEDE.overview}</p>
        </div>
        {isSystem && section !== "railway" ? (
          <div className="admin-head-actions">
            {latest && latest.finished_at ? (
              <span className="admin-btn" style={{ pointerEvents: "none" }}>
                <Icon name="clock" />
                {fmtStamp(latest.finished_at)}
              </span>
            ) : null}
            <button type="button" className="admin-btn accent" disabled={busy} onClick={runAudit}>
              <Icon name={busy ? "clock" : "play"} />
              {busy
                ? t("Идёт прогон…", "Ishlamoqda…", "Running…")
                : t("Прогнать аудит", "Auditni ishga tushirish", "Run the audit")}
            </button>
          </div>
        ) : null}
      </div>

      <nav className="admin-tabs">
        {SECTIONS.map((item) => {
          const active = activeTab === item.key;
          const badge = item.key === "system" && openCounts.blocking ? openCounts.blocking : null;
          return (
            <button
              key={item.key}
              type="button"
              className={`admin-tab${active ? " active" : ""}`}
              aria-current={active ? "page" : undefined}
              onClick={() => onSectionChange && onSectionChange(item.key)}
            >
              <Icon name={item.icon} />
              {item.title[lang3(language)]}
              {badge ? <span className="n hot">{fmtInt(badge)}</span> : null}
            </button>
          );
        })}
      </nav>

      {isSystem ? (
        <div className="admin-subtabs">
          <div className="admin-seg">
            {SYSTEM_SECTIONS.map((item) => (
              <button
                key={item.key}
                type="button"
                aria-selected={section === item.key}
                onClick={() => onSectionChange && onSectionChange(item.key)}
              >
                {item.title[lang3(language)]}
                {item.key === "findings" && openCounts.blocking
                  ? <span className="n">{fmtInt(openCounts.blocking)}</span> : null}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {error ? <div className="admin-error" style={{ marginBottom: 16 }}>{error}</div> : null}
      {loading && !(isSystem && overview) ? <Skeleton rows={4} />
        : (bodyBySection[section] || overviewBody)}
    </div>
  );
}
