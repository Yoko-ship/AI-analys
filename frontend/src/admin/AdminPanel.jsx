/**
 * AdminPanel.jsx — the administrative page.
 *
 * A page of the site, not an application beside it. The topbar, brand, language
 * and theme controls stay where they always are; this renders inside the same
 * content column as Рынок or Новости, with the sections as tabs. Everything is
 * painted with the site's tokens, so it follows both themes without owning them.
 *
 * Authentication is the signed-in admin's own Bearer token — the machine
 * X-Admin-Secret never reaches the browser. The server side is `_admin_gate`
 * in api.py, which accepts either credential.
 *
 * Nothing here invents a number. Where the backend cannot measure something the
 * cell renders «—», and the collectors section says «последняя запись» rather
 * than «прогон», because from this process a collector that died and one that
 * had nothing to write look identical.
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
/** `ready: false` renders the tab disabled — an honest "not built yet" beats a
 *  screen that looks finished and answers nothing. */
const SECTIONS = [
  { key: "overview", icon: "dashboard", ready: true,
    title: ["Обзор", "Umumiy", "Overview"] },
  { key: "streams", icon: "refresh", ready: true,
    title: ["Сборщики", "Yig'uvchilar", "Collectors"] },
  { key: "findings", icon: "alert", ready: true,
    title: ["Аудит", "Audit", "Audit"] },
  { key: "catalog", icon: "list", ready: false,
    title: ["Каталог", "Katalog", "Securities"] },
  { key: "financials", icon: "file", ready: false,
    title: ["Отчётность", "Hisobot", "Statements"] },
  { key: "quotes", icon: "chart", ready: false,
    title: ["Котировки", "Kotirovkalar", "Quotes"] },
  { key: "dividends", icon: "percent", ready: false,
    title: ["Дивиденды", "Dividendlar", "Dividends"] },
  { key: "news", icon: "news", ready: false,
    title: ["Новости", "Yangiliklar", "News"] },
  { key: "users", icon: "users", ready: false,
    title: ["Пользователи", "Foydalanuvchilar", "Users"] },
];

export const ADMIN_SECTION_KEYS = SECTIONS.map((s) => s.key);

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

function Skeleton({ rows = 3 }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="admin-skel" style={{ height: i === 0 ? 96 : 58 }} />
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

  const SECTION_LEDE = {
    overview: t(
      "Состояние данных на сегодня: что собрано, что требует решения и сколько это стоит.",
      "Bugungi ma'lumot holati.",
      "Today's state of the data: what was collected, what needs a decision, what it costs."),
    streams: t(
      "Показана последняя запись в таблице, которую пишет служба, а не её код возврата: сборщики работают отдельными сервисами и в этот процесс не отчитываются.",
      "Xizmat yozadigan jadvaldagi oxirgi yozuv ko'rsatilgan.",
      "The last write in the table each service fills, not its exit code: the collectors run as separate services and do not report here."),
    findings: t(
      "Аудитор пересчитывает те же величины независимым путём и сравнивает их с опубликованным. Блокирующая находка снимает число с публикации.",
      "Auditor qiymatlarni mustaqil qayta hisoblab, e'lon qilingani bilan solishtiradi.",
      "The auditor recomputes the same quantities by an independent route and compares them with what was published."),
  };

  /* ── section bodies ─────────────────────────────────────────────────────── */

  const overviewBody = (
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

  const notBuiltBody = (
    <div className="panel">
      <div className="admin-empty">
        <b>{t("Этот раздел ещё не построен", "Bu bo'lim hali qurilmagan", "This section is not built yet")}</b>
        {t("Данные для него уже есть в API — не хватает только экрана.",
           "API'da ma'lumot bor, faqat ekran yetishmaydi.",
           "The API already carries its data — only the screen is missing.")}
      </div>
    </div>
  );

  const bodyBySection = {
    overview: overviewBody,
    streams: streamsBody,
    findings: findingsBody,
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
      </div>

      <nav className="admin-tabs">
        {SECTIONS.map((item) => {
          const badge = item.key === "findings" ? openCounts.blocking
            : item.key === "catalog" ? (catalog && catalog.securities)
              : item.key === "streams" ? (streams.length || null) : null;
          return (
            <button
              key={item.key}
              type="button"
              className={`admin-tab${section === item.key ? " active" : ""}`}
              disabled={!item.ready}
              aria-current={section === item.key ? "page" : undefined}
              onClick={() => item.ready && onSectionChange && onSectionChange(item.key)}
            >
              <Icon name={item.icon} />
              {item.title[lang3(language)]}
              {!item.ready ? (
                <span className="n soon">{t("скоро", "tez orada", "soon")}</span>
              ) : badge !== null && badge !== undefined ? (
                <span className={`n${item.key === "findings" && badge ? " hot" : ""}`}>{fmtInt(badge)}</span>
              ) : null}
            </button>
          );
        })}
      </nav>

      {error ? <div className="admin-error" style={{ marginBottom: 16 }}>{error}</div> : null}
      {loading && !overview ? <Skeleton rows={4} /> : (bodyBySection[section] || notBuiltBody)}
    </div>
  );
}
