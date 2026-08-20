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

/** A multiple, printed to two places. Rounding happens on OUTPUT only — the
 *  value itself is never touched. */
function fmtNum(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return DASH;
  return Number(value).toLocaleString("ru-RU",
    { minimumFractionDigits: digits, maximumFractionDigits: digits });
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
  { key: "intake", icon: "file", ready: true,
    title: ["Отчёты", "Hisobotlar", "Statements"] },
  { key: "issuer", icon: "list", ready: true,
    title: ["Эмитент", "Emitent", "Issuer"] },
  { key: "rules", icon: "check", ready: true,
    title: ["Правила", "Qoidalar", "Rules"] },
  { key: "catalog", icon: "list", ready: false,
    title: ["Каталог", "Katalog", "Securities"] },
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
  const [intake, setIntake] = useState(null);
  const [intakeState, setIntakeState] = useState("ineligible");
  const [ledger, setLedger] = useState(null);
  const [ledgerTicker, setLedgerTicker] = useState("");
  const [ruleBook, setRuleBook] = useState(null);
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
    (section === "findings" ? Promise.all([loadOverview(), loadFindings()])
      : section === "intake" ? Promise.all([loadOverview(), loadIntake()])
        : section === "rules" ? Promise.all([loadOverview(), loadRuleBook()])
          : loadOverview())
      .catch((e) => { if (!cancelled) setError(String(e.message || e)); })
      .finally(() => { if (!cancelled && alive.current) setLoading(false); });
    return () => { cancelled = true; };
  }, [section, loadOverview, loadFindings, loadIntake, loadRuleBook]);

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
    intake: t(
      "Что конвейер принял на вход. Пока статус записи не виден, любая правка расчёта делается наугад: половина найденных дефектов — не ошибка формулы, а то, какая запись до неё доехала.",
      "Konveyer nimani qabul qilgani.",
      "What the pipeline took in. While a record's status is invisible, every fix to the calculation is made blind."),
    issuer: t(
      "Расчёт разложен построчно: каждое слагаемое двенадцатимесячной базы со своим периодом и знаком, капитализация по классам, остатки, из которых берутся знаменатели, и все прошедшие проверки.",
      "Hisob-kitob qatorma-qator yoyilgan.",
      "The calculation laid out line by line: every component of the twelve-month base with its period and sign, the capitalisation by class, the balances the denominators come from."),
    rules: t(
      "Параметры расчёта и граница ответственности: панель задаёт пороги и исключения, код задаёт вычисления.",
      "Hisob parametrlari va javobgarlik chegarasi.",
      "The calculation's parameters and the boundary: the panel sets thresholds and exceptions, the code holds the computation."),
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

  /* ── 01 · what the pipeline took in ─────────────────────────────────────── */
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

  /* ── 02 · the calculation, line by line ─────────────────────────────────── */
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

  /* ── 05 · the parameters, and the line the panel must not cross ─────────── */
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
    intake: intakeBody,
    issuer: issuerBody,
    rules: rulesBody,
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
