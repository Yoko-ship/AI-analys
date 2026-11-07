import { useState } from "react";
import { useCollectionOperations } from "./useCollectionOperations.js";
import "./collection-runs.css";

function stamp(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Tashkent", dateStyle: "medium", timeStyle: "short",
  }).format(date);
}

const STATES = {
  failed: ["Ошибка", "Xatolik", "Failed"],
  partial: ["Частично", "Qisman", "Partial"],
  completed: ["Завершён", "Tugallangan", "Completed"],
  no_change: ["Без изменений", "O‘zgarishsiz", "No change"],
  running: ["Выполняется", "Bajarilmoqda", "Running"],
  unknown: ["Нет наблюдений", "Kuzatuv yo‘q", "Not observed"],
  queued: ["В очереди", "Navbatda", "Queued"],
  dispatching: ["Запускается", "Boshlanmoqda", "Starting"],
  dispatched: ["Запуск принят", "Ishga tushirish qabul qilindi", "Start accepted"],
  uncertain: ["Запуск не подтверждён", "Ishga tushirish tasdiqlanmadi", "Start unconfirmed"],
  finished: ["Завершён", "Tugallangan", "Finished"],
  cleared: ["Запрос снят", "So‘rov bekor qilindi", "Request cleared"],
  expired: ["Истёк срок ожидания", "Kutish muddati tugadi", "Request expired"],
};
const ISSUES = {
  monitor_offline: ["Нет свежих данных наблюдения", "Yangi kuzatuv ma’lumoti yo‘q", "No recent monitor report"],
  service_missing: ["Служба не установлена", "Xizmat o‘rnatilmagan", "Service is not installed"],
  timer_disabled: ["Расписание отключено", "Jadval o‘chirilgan", "Schedule is disabled"],
  timer_inactive: ["Таймер не работает", "Taymer ishlamayapti", "Schedule timer is inactive"],
  missed_schedule: ["Запланированный запуск не обнаружен", "Rejalashtirilgan ishga tushirish kuzatilmadi", "Scheduled run was not observed"],
};
function State({ value, t }) {
  return <span className={`collection-state collection-state--${value}`}>{t(...(STATES[value] || STATES.unknown))}</span>;
}
function RunEvidence({ run, t }) {
  return <div className="collection-evidence">
    <dl className="collection-facts">
      <div><dt>{t("Начало", "Boshlanish", "Started")}</dt><dd>{stamp(run.started_at)}</dd></div>
      <div><dt>{t("Окончание", "Tugash", "Finished")}</dt><dd>{stamp(run.finished_at)}</dd></div>
      <div><dt>{t("Публикация", "Nashr", "Publication")}</dt><dd>{
        run.publication === "acknowledged" ? t("Запись подтверждена сервером", "Yozuv serverda tasdiqlandi", "Writes acknowledged by server")
          : run.publication === "partial" ? t("Часть записей не применена", "Yozuvlar qisman qo‘llandi", "Some writes failed")
            : run.publication === "failed" ? t("Ошибка публикации", "Nashr xatosi", "Publication failed")
              : t("Нет подтверждения записи", "Yozuv tasdiqlanmadi", "No confirmed write")}</dd></div>
    </dl>
    {run.failed_stage && <p>{t("Этап", "Bosqich", "Stage")}: <code>{run.failed_stage}</code></p>}
    {!!run.receipts?.length && <ul className="collection-receipts">{run.receipts.map((receipt, index) =>
      <li key={index}><code>{receipt.stage}</code> · {receipt.ok ? "✓" : "✕"} {receipt.reason}
        {Object.entries(receipt.counts || {}).map(([key, count]) => <span key={key}> · {key}: {count}</span>)}</li>)}</ul>}
    <p className="muted">{t("Счётчики записи могут включать уже существовавшие строки.", "Hisobga olingan yozuvlar oldingi qatorlarni ham o‘z ichiga olishi mumkin.", "Write counts may include existing, unchanged rows.")}</p>
    <pre className="collection-log">{run.evidence || t("Журнал этого запуска недоступен.", "Bu ishga tushirish jurnali mavjud emas.", "No log was captured for this run.")}</pre>
    {run.evidence_truncated && <p className="muted">{t("Показан фрагмент журнала. Полный журнал доступен на сервере.", "Jurnalning bir qismi ko‘rsatilgan. To‘liq jurnal serverda.", "This is a log excerpt. The full journal is available on the server.")}</p>}
  </div>;
}
function PastRun({ run, job, read, t }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  return <details className="collection-past" onToggle={async event => {
    if (!event.currentTarget.open || detail) return;
    try { setDetail(await read(`/${job.id}/runs/${run.invocation}`)); } catch (failure) { setError(failure.message); }
  }}>
    <summary>{stamp(run.started_at)} · {t(...(STATES[run.status] || STATES.unknown))}</summary>
    <p>{run.reason}</p>
    {error && <p role="alert">{error}</p>}
    {detail && <RunEvidence run={detail} t={t} />}
  </details>;
}
function Collector({ job, t, busy, disabled, act, read }) {
  const [open, setOpen] = useState(false);
  const latest = job.latest || {};
  const issue = ISSUES[job.schedule_issue];
  return <article className="panel collection-card" aria-label={job.title}>
    <div className="collection-card-head">
      <div className="collection-title"><h3>{t(job.title_ru, job.title_uz, job.title)}</h3><code>{job.unit}</code></div>
      <State value={latest.status} t={t} />
      <button className="primary-btn" disabled={disabled || !!busy || !job.can_run} onClick={() => act(job)}>
        {busy === job.id ? t("Отправка…", "Yuborilmoqda…", "Sending…") : t("Запустить", "Ishga tushirish", "Run now")}
      </button>
    </div>
    <p className="collection-reason">{latest.reason}</p>
    {issue && <p className="collection-warning">{t(...issue)}</p>}
    <div className="collection-timing">
      <span>{t("Расписание", "Jadval", "Schedule")}: {job.schedule}</span>
      <span>{t("Следующий запуск", "Keyingi ishga tushirish", "Next run")}: {stamp(job.next_run)}</span>
      <span>{t("Последняя попытка", "Oxirgi urinish", "Last attempt")}: {stamp(latest.started_at)}</span>
    </div>
    {job.request && <div className="collection-request" role="status">
      <State value={job.request.status} t={t} /> <span>{job.request.detail}</span>
      {["queued", "uncertain"].includes(job.request.status) && <button className="secondary-btn" disabled={disabled || !!busy || latest.status === "running"} onClick={() => act(job, true)}>
        {t("Снять запрос", "So‘rovni bekor qilish", "Clear request")}
      </button>}
    </div>}
    <button className="collection-details-button" aria-expanded={open} aria-controls={`details-${job.id}`} onClick={() => setOpen(!open)}>
      {open ? t("Скрыть детали", "Tafsilotlarni yopish", "Hide details") : t("Подробнее", "Batafsil", "Details")}
    </button>
    {open && <div id={`details-${job.id}`} className="collection-detail">
      <RunEvidence run={latest} t={t} />
      <h4>{t("Запустить вручную на сервере", "Serverda qo‘lda ishga tushirish", "Run manually on the server")}</h4>
      <pre className="collection-command"><code>{job.run_command}</code></pre>
      <pre className="collection-command"><code>{job.logs_command}</code></pre>
      <h4>{t("История запусков", "Ishga tushirishlar tarixi", "Run history")}</h4>
      {(job.history || []).map(run => <PastRun key={run.invocation} run={run} job={job} read={read} t={t} />)}
      {!job.history?.length && <p className="muted">{t("История появится после первого наблюдения.", "Tarix birinchi kuzatuvdan keyin paydo bo‘ladi.", "History begins when monitoring observes a run.")}</p>}
      {!!job.requests?.length && <details className="collection-past"><summary>{t("Ручные запросы", "Qo‘lda yuborilgan so‘rovlar", "Manual requests")}</summary>
        {job.requests.map(request => <p key={request.id}>{stamp(request.requested_at)} · {t(...(STATES[request.status] || STATES.unknown))} · {request.detail}</p>)}
      </details>}
    </div>}
  </article>;
}
export function CollectionRuns({ apiFetch, t }) {
  const { data, error, busy, refresh, act, read } = useCollectionOperations(apiFetch);
  return <section className="collection-runs" aria-label={t("Выполнение сборов", "Yig‘ish holati", "Collection runs")}>
    <div className="collection-toolbar">
      <p className="muted">{t("Время — Ташкент (UTC+5). Проверка каждые 15 секунд.", "Vaqt — Toshkent (UTC+5). Har 15 soniyada yangilanadi.", "Times are Tashkent (UTC+5). Refreshes every 15 seconds.")}</p>
      <button className="secondary-btn" onClick={refresh}>{t("Обновить", "Yangilash", "Refresh")}</button>
    </div>
    {error && <p className="collection-warning" role="alert">{error}</p>}
    {!data && !error && <p role="status">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</p>}
    {data && !data.observer?.online && <p className="collection-warning" role="alert">
      {t("Нет связи с серверным наблюдателем. Статусы могут быть устаревшими; запуск из панели недоступен.", "Server kuzatuvchisi bilan aloqa yo‘q. Holatlar eskirgan bo‘lishi mumkin; paneldan ishga tushirib bo‘lmaydi.", "The server monitor is offline. These results may be outdated; Run now is unavailable.")}
    </p>}
    {(data?.items || []).map(job => <Collector key={job.id} job={job} t={t} busy={busy} disabled={!!error || !data.observer?.online} act={act} read={read} />)}
  </section>;
}
