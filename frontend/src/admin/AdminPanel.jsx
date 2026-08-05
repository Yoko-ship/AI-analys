/**
 * AdminPanel.jsx — the administrative panel («Neutral», направление A).
 *
 * Renders full-screen as a sibling of the site shell: the panel has its own
 * sidebar and header, so wrapping it in the product's topbar would give the
 * operator two navigations for one screen.
 *
 * Authentication is the signed-in admin's own Bearer token — the machine
 * X-Admin-Secret never reaches the browser. The server side of that is
 * `_admin_gate` in api.py, which accepts either credential.
 *
 * Nothing here invents a number. Where the backend cannot measure something the
 * cell renders «—», and the freshness section says «последняя запись» rather
 * than «прогон», because from this process a collector that died and a collector
 * that had nothing to write look identical.
 */
import React from "react";
import { Icon, IconSprite } from "./icons.jsx";
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

const SEVERITY_TONE = { blocking: "err", warning: "warn", info: "ok" };

/* ── sections ─────────────────────────────────────────────────────────────── */
/** `ready: false` renders the item disabled — an honest "not built yet" beats a
 *  screen that looks finished and answers nothing. */
const SECTIONS = [
  { key: "overview", icon: "dashboard", group: "platform", ready: true,
    title: ["Обзор", "Umumiy ko'rinish", "Overview"] },
  { key: "streams", icon: "refresh", group: "platform", ready: true,
    title: ["Сборщики", "Yig'uvchilar", "Collectors"] },
  { key: "findings", icon: "alert", group: "platform", ready: true,
    title: ["Аудит", "Audit", "Audit"] },
  { key: "catalog", icon: "list", group: "data", ready: false,
    title: ["Каталог бумаг", "Qimmatli qog'ozlar", "Securities"] },
  { key: "financials", icon: "file", group: "data", ready: false,
    title: ["Отчётность", "Hisobot", "Statements"] },
  { key: "quotes", icon: "chart", group: "data", ready: false,
    title: ["Котировки", "Kotirovkalar", "Quotes"] },
  { key: "dividends", icon: "percent", group: "data", ready: false,
    title: ["Дивиденды", "Dividendlar", "Dividends"] },
  { key: "news", icon: "news", group: "content", ready: false,
    title: ["Новости", "Yangiliklar", "News"] },
  { key: "logos", icon: "image", group: "content", ready: false,
    title: ["Логотипы", "Logotiplar", "Logos"] },
  { key: "users", icon: "users", group: "access", ready: false,
    title: ["Пользователи", "Foydalanuvchilar", "Users"] },
];

const GROUP_TITLES = {
  platform: ["Платформа", "Platforma", "Platform"],
  data: ["Данные", "Ma'lumotlar", "Data"],
  content: ["Контент", "Kontent", "Content"],
  access: ["Доступ", "Kirish", "Access"],
};

export const ADMIN_SECTION_KEYS = SECTIONS.map((s) => s.key);

/* ── small pieces ─────────────────────────────────────────────────────────── */

function Stat({ label, value, badge, badgeIcon, line1, line1Icon, line2 }) {
  return (
    <div className="adm-card adm-stat">
      <div className="top">
        <span className="lab">{label}</span>
        {badge ? (
          <span className="adm-badge">
            {badgeIcon ? <Icon name={badgeIcon} /> : null}{badge}
          </span>
        ) : null}
      </div>
      <div className="v">{value}</div>
      {line1 ? (
        <div className="l1">{line1}{line1Icon ? <Icon name={line1Icon} /> : null}</div>
      ) : null}
      {line2 ? <div className="l2">{line2}</div> : null}
    </div>
  );
}

function Severity({ value, t }) {
  const label = value === "blocking"
    ? t("Блокирующая", "Bloklovchi", "Blocking")
    : value === "warning"
      ? t("Предупреждение", "Ogohlantirish", "Warning")
      : t("Информация", "Ma'lumot", "Info");
  return (
    <span className="adm-pill">
      <span className={`adm-dot ${SEVERITY_TONE[value] || ""}`} />{label}
    </span>
  );
}

/** Blocking findings per run, oldest on the left. Bare divs, not a chart
 *  library: fourteen bars do not justify a dependency. */
function RunHistory({ runs, t }) {
  const peak = Math.max(1, ...runs.map((r) => Number(r.blocking) || 0));
  return (
    <div className="adm-bars">
      {runs.map((run, index) => {
        const value = Number(run.blocking) || 0;
        const last = index === runs.length - 1;
        const label = fmtStamp(run.finished_at || run.started_at, { withTime: false }).slice(0, 5);
        const cls = ["b", last ? "now" : "", run.status === "failed" ? "failed" : ""]
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

function Skeleton({ rows = 3 }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="adm-skel" style={{ height: i === 0 ? 86 : 54 }} />
      ))}
    </div>
  );
}

/* ── findings table (shared by Обзор and Аудит) ───────────────────────────── */

function FindingsTable({ items, rules, t, selected, onToggle, onAccept, busy }) {
  const ruleTitle = useCallback((code) => {
    const rule = rules.find((r) => r.code === code);
    return rule ? rule.title : "";
  }, [rules]);

  if (!items.length) {
    return (
      <div className="adm-empty">
        <b>{t("Ничего не ждёт решения", "Hech narsa kutmayapti", "Nothing is waiting")}</b>
        {t("Все открытые находки разобраны.", "Barcha topilmalar ko'rib chiqilgan.",
           "Every open finding has been dealt with.")}
      </div>
    );
  }

  return (
    <div className="adm-wide">
      <table>
        <thead>
          <tr>
            <th style={{ width: 40 }} />
            <th>{t("Правило", "Qoida", "Rule")}</th>
            <th style={{ width: 142 }}>{t("Уровень", "Daraja", "Severity")}</th>
            <th style={{ width: 96 }}>{t("Бумага", "Qog'oz", "Security")}</th>
            <th style={{ width: 110 }}>{t("Держится", "Ushlanib turibdi", "Seen")}</th>
            <th className="r" style={{ width: 118 }}>{t("Открыта", "Ochilgan", "Opened")}</th>
            <th style={{ width: 44 }} />
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
                    className="adm-chk"
                    role="checkbox"
                    aria-checked={checked}
                    aria-label={t("Выбрать находку", "Topilmani tanlash", "Select finding")}
                    onClick={() => onToggle(item.id)}
                  />
                </td>
                <td>
                  <div className="rule"><code>{item.rule_code}</code>{ruleTitle(item.rule_code)}</div>
                  {item.message ? <div className="dim">{item.message}</div> : null}
                </td>
                <td><Severity value={item.severity} t={t} /></td>
                <td className="who">{item.ticker || DASH}</td>
                <td className="who">
                  {item.seen_count
                    ? t(`${item.seen_count} прогон(ов)`, `${item.seen_count} marta`, `${item.seen_count} runs`)
                    : DASH}
                </td>
                <td className="r who">{fmtStamp(item.first_seen, { withTime: false })}</td>
                <td>
                  <button
                    type="button"
                    className="adm-more"
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

/* ── panel ────────────────────────────────────────────────────────────────── */

export default function AdminPanel({
  apiFetch, user, language = "ru", theme = "dark", onToggleTheme, onExit,
  section = "overview", onSectionChange,
}) {
  const t = useT(language);
  const [navOpen, setNavOpen] = useState(false);
  const [overview, setOverview] = useState(null);
  const [rules, setRules] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [findings, setFindings] = useState([]);
  const [filters, setFilters] = useState({ severity: "blocking", status: "new" });
  const [selected, setSelected] = useState(() => new Set());
  const alive = useRef(true);

  useEffect(() => () => { alive.current = false; }, []);

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

  const loadOverview = useCallback(async () => {
    const data = await readJson("/api/admin/overview");
    if (alive.current) setOverview(data);
  }, [readJson]);

  const loadFindings = useCallback(async () => {
    const params = new URLSearchParams({ limit: "300" });
    if (filters.severity) params.set("severity", filters.severity);
    if (filters.status) params.set("status", filters.status);
    const data = await readJson(`/api/audit/findings?${params}`);
    if (alive.current) setFindings(data.items || []);
  }, [filters, readJson]);

  // The rule book is public and cacheable; a failure there must not blank the screen.
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
    (section === "findings" ? Promise.all([loadOverview(), loadFindings()]) : loadOverview())
      .catch((e) => { if (!cancelled) setError(String(e.message || e)); })
      .finally(() => { if (!cancelled && alive.current) setLoading(false); });
    return () => { cancelled = true; };
  }, [section, loadOverview, loadFindings]);

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

  const goto = (key) => {
    setNavOpen(false);
    if (onSectionChange) onSectionChange(key);
  };

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

  const current = SECTIONS.find((s) => s.key === section) || SECTIONS[0];
  const sectionTitle = current.title[lang3(language)];

  /* ── section bodies ─────────────────────────────────────────────────────── */

  const overviewBody = (
    <>
      <div className="adm-h1row">
        <h1 className="adm-h1">{t("Обзор", "Umumiy ko'rinish", "Overview")}</h1>
        <p>
          {latest && latest.finished_at
            ? t(`Последний прогон аудита — ${fmtStamp(latest.finished_at)}`,
                `Oxirgi audit — ${fmtStamp(latest.finished_at)}`,
                `Last audit run — ${fmtStamp(latest.finished_at)}`)
            : t("Аудит ещё не прогонялся", "Audit hali ishga tushirilmagan", "The auditor has not run yet")}
        </p>
      </div>

      <div className="adm-stats">
        <Stat
          label={t("Бумаг в каталоге", "Kataloqdagi qog'ozlar", "Securities")}
          value={fmtInt(catalog && catalog.securities)}
          line2={catalog
            ? t(`${fmtInt(catalog.stocks)} акций и ${fmtInt(catalog.bonds)} облигаций`,
                `${fmtInt(catalog.stocks)} aksiya, ${fmtInt(catalog.bonds)} obligatsiya`,
                `${fmtInt(catalog.stocks)} shares and ${fmtInt(catalog.bonds)} bonds`)
            : null}
          line1={catalog && catalog.preferred
            ? t(`${fmtInt(catalog.preferred)} привилегированных`,
                `${fmtInt(catalog.preferred)} imtiyozli`,
                `${fmtInt(catalog.preferred)} preferred`)
            : null}
        />
        <Stat
          label={t("Блокирующих находок", "Bloklovchi topilmalar", "Blocking findings")}
          value={fmtInt(openCounts.blocking)}
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

      <div className="adm-card">
        <div className="adm-chhead">
          <div>
            <h2>{t("Блокирующие находки по прогонам", "Prognozlar bo'yicha bloklovchi topilmalar",
                   "Blocking findings by run")}</h2>
            <p>{t(`Последние ${history.length} прогонов аудитора`,
                  `Oxirgi ${history.length} audit`, `Last ${history.length} audit runs`)}</p>
          </div>
        </div>
        {history.length ? <RunHistory runs={history} t={t} /> : (
          <div className="adm-empty">{t("Прогонов пока нет", "Hali prognoz yo'q", "No runs yet")}</div>
        )}
        {latest ? (
          <div className="adm-chfoot">
            <div><span>{t("Правил в прогоне", "Qoidalar", "Rules run")}</span> <b>{fmtInt(latest.rules_run)}</b></div>
            <div><span>{t("Инструментов", "Vositalar", "Instruments")}</span> <b>{fmtInt(latest.instruments)}</b></div>
            <div><span>{t("Длительность", "Davomiylik", "Duration")}</span> <b>{fmtInt(latest.duration_ms)} мс</b></div>
            <div><span>{t("Статус", "Holat", "Status")}</span> <b>{latest.status}</b></div>
          </div>
        ) : null}
      </div>

      <div className="adm-card">
        <div className="adm-tbar">
          <div className="adm-tabs">
            <button type="button" aria-selected="true">
              {t("Требует решения", "Qaror kerak", "Needs a decision")}
              <span className="c">{queue.length}</span>
            </button>
          </div>
          <span className="sp" />
          <button type="button" className="adm-btn sm" onClick={() => goto("findings")}>
            {t("Все находки", "Barcha topilmalar", "All findings")}
          </button>
        </div>
        <FindingsTable
          items={queue} rules={rules} t={t} selected={selected}
          onToggle={toggleSelected} onAccept={acceptFindings} busy={busy}
        />
      </div>
    </>
  );

  const streamsBody = (
    <>
      <div className="adm-h1row">
        <h1 className="adm-h1">{t("Сборщики", "Yig'uvchilar", "Collectors")}</h1>
        <p>
          {t("Показана последняя запись в таблице, которую пишет служба, а не её код возврата: сборщики работают отдельными сервисами и в этот процесс не отчитываются.",
             "Xizmat yozadigan jadvaldagi oxirgi yozuv ko'rsatilgan.",
             "This is the last write in the table each service fills, not its exit code: the collectors run as separate services and do not report here.")}
        </p>
      </div>
      <div className="adm-card adm-wide">
        <table>
          <thead>
            <tr>
              <th>{t("Поток", "Oqim", "Stream")}</th>
              <th style={{ width: 190 }}>{t("Служба", "Xizmat", "Service")}</th>
              <th style={{ width: 180 }}>{t("Расписание", "Jadval", "Schedule")}</th>
              <th style={{ width: 120 }}>{t("Состояние", "Holat", "State")}</th>
              <th className="r" style={{ width: 100 }}>{t("Строк", "Qatorlar", "Rows")}</th>
              <th className="r" style={{ width: 190 }}>{t("Последняя запись", "Oxirgi yozuv", "Last write")}</th>
            </tr>
          </thead>
          <tbody>
            {streams.map((stream) => (
              <tr key={stream.key}>
                <td>
                  <div className="rule">{stream.title}</div>
                  <div className="dim"><code>{stream.table}</code></div>
                </td>
                <td className="who">{stream.service}</td>
                <td className="who">{stream.schedule}</td>
                <td>
                  <span className="adm-pill">
                    <span className={`adm-dot ${stream.state === "fresh" ? "ok" : stream.state === "stale" ? "warn" : ""}`} />
                    {stream.state === "fresh"
                      ? t("Свежий", "Yangi", "Fresh")
                      : stream.state === "stale"
                        ? t("Устарел", "Eskirgan", "Stale")
                        : t("Нет записей", "Yozuv yo'q", "Never written")}
                  </span>
                </td>
                <td className="r who">{fmtInt(stream.rows)}</td>
                <td className="r who">
                  {fmtStamp(stream.last_write)}
                  <div className="dim">{fmtAge(stream.age_hours, t)}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );

  const findingsBody = (
    <>
      <div className="adm-h1row">
        <h1 className="adm-h1">{t("Аудит данных", "Ma'lumot auditi", "Data audit")}</h1>
        <p>
          {t("Аудитор пересчитывает те же величины независимым путём и сравнивает их с опубликованным. Блокирующая находка снимает число с публикации.",
             "Auditor qiymatlarni mustaqil qayta hisoblab, e'lon qilingani bilan solishtiradi.",
             "The auditor recomputes the same quantities by an independent route and compares them with what was published.")}
        </p>
      </div>
      <div className="adm-card">
        <div className="adm-tbar">
          <div className="adm-tabs">
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
                <span className="c">{fmtInt(openCounts[severity])}</span>
              </button>
            ))}
          </div>
          <span className="sp" />
          <button
            type="button"
            className="adm-btn sm"
            aria-pressed={filters.status === ""}
            onClick={() => setFilters((f) => ({ ...f, status: f.status ? "" : "new" }))}
          >
            {filters.status
              ? t("Показать разобранные", "Ko'rib chiqilganlarni ko'rsatish", "Include triaged")
              : t("Только открытые", "Faqat ochiq", "Open only")}
          </button>
        </div>
        {loading ? <div style={{ padding: 16 }}><Skeleton rows={4} /></div> : (
          <>
            <FindingsTable
              items={findings} rules={rules} t={t} selected={selected}
              onToggle={toggleSelected} onAccept={acceptFindings} busy={busy}
            />
            <div className="adm-tfoot">
              <span>
                {t(`Показано ${findings.length}`, `${findings.length} ta ko'rsatildi`,
                   `Showing ${findings.length}`)}
                {selected.size
                  ? t(` · выбрано ${selected.size}`, ` · ${selected.size} tanlandi`,
                      ` · ${selected.size} selected`)
                  : ""}
              </span>
              <span className="sp" />
              <button
                type="button"
                className="adm-btn sm"
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
    </>
  );

  const notBuiltBody = (
    <div className="adm-card">
      <div className="adm-empty">
        <b>{t("Этот раздел ещё не построен", "Bu bo'lim hali qurilmagan", "This section is not built yet")}</b>
        {t("Каркас панели готов, раздел добавится следующим шагом. Данные для него уже есть в API — не хватает только экрана.",
           "Panel tayyor, bo'lim keyingi bosqichda qo'shiladi.",
           "The shell is ready; this section lands next. The API already carries its data — only the screen is missing.")}
      </div>
    </div>
  );

  const bodyBySection = {
    overview: overviewBody,
    streams: streamsBody,
    findings: findingsBody,
  };

  const initials = ((user && (user.full_name || user.email)) || "?")
    .trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

  return (
    <div className={`adm${navOpen ? " is-open" : ""}`}>
      <IconSprite />

      <button
        type="button"
        className="adm-scrim"
        aria-label={t("Закрыть меню", "Menyuni yopish", "Close menu")}
        onClick={() => setNavOpen(false)}
      />

      <aside className="adm-side">
        <button type="button" className="adm-ws" onClick={onExit}>
          <span className="sq">AI</span>
          <span className="t">
            <b>AI-analys</b>
            <span>{t("Администрирование", "Administratsiya", "Administration")}</span>
          </span>
          <Icon name="updown" />
        </button>

        {["platform", "data", "content", "access"].map((group) => (
          <React.Fragment key={group}>
            <div className="adm-grp">{GROUP_TITLES[group][lang3(language)]}</div>
            {SECTIONS.filter((s) => s.group === group).map((item) => {
              const badge = item.key === "findings" ? openCounts.blocking
                : item.key === "catalog" ? (catalog && catalog.securities)
                  : item.key === "streams" ? streams.length : null;
              return (
                <button
                  key={item.key}
                  type="button"
                  className="adm-nav"
                  disabled={!item.ready}
                  aria-current={section === item.key ? "page" : undefined}
                  onClick={() => item.ready && goto(item.key)}
                >
                  <Icon name={item.icon} />
                  {item.title[lang3(language)]}
                  {!item.ready ? (
                    <span className="b soon">{t("скоро", "tez orada", "soon")}</span>
                  ) : badge !== null && badge !== undefined ? (
                    <span className={`b${item.key === "findings" && badge ? " hi" : ""}`}>{fmtInt(badge)}</span>
                  ) : null}
                </button>
              );
            })}
          </React.Fragment>
        ))}

        <div className="foot">
          <button type="button" className="adm-nav" onClick={onExit}>
            <Icon name="arrowLeft" />
            {t("Вернуться на сайт", "Saytga qaytish", "Back to the site")}
          </button>
          <button type="button" className="adm-user">
            {user && user.avatar_data_url
              ? <img className="av" src={user.avatar_data_url} alt="" />
              : <span className="av">{initials}</span>}
            <span className="t">
              <b>{(user && user.full_name) || t("Администратор", "Administrator", "Administrator")}</b>
              <span>{user && user.email}</span>
            </span>
            <Icon name="updown" />
          </button>
        </div>
      </aside>

      <main className="adm-main">
        <header className="adm-head">
          <button
            type="button"
            className="adm-btn icon adm-burger"
            aria-label={t("Меню", "Menyu", "Menu")}
            onClick={() => setNavOpen((v) => !v)}
          >
            <Icon name="panel" />
          </button>
          <div className="adm-crumbs">
            {t("Админка", "Admin", "Admin")} <span className="sep">/</span> <b>{sectionTitle}</b>
          </div>
          <span className="sp" />
          <button
            type="button"
            className="adm-btn icon"
            onClick={onToggleTheme}
            aria-label={t("Сменить тему", "Mavzuni almashtirish", "Switch theme")}
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} />
          </button>
          <button type="button" className="adm-btn pri" disabled={busy} onClick={runAudit}>
            <Icon name={busy ? "clock" : "play"} />
            {busy
              ? t("Идёт прогон…", "Ishlamoqda…", "Running…")
              : t("Прогнать аудит", "Auditni ishga tushirish", "Run the audit")}
          </button>
        </header>

        <div className="adm-body">
          {error ? <div className="adm-err">{error}</div> : null}
          {loading && !overview ? <Skeleton rows={4} />
            : bodyBySection[section] || notBuiltBody}
        </div>
      </main>
    </div>
  );
}
