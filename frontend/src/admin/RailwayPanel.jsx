import React, { useCallback, useEffect, useRef, useState } from "react";

const stamp = (value) => value ? new Date(value).toLocaleString() : "—";

function stateLabel(service, t) {
  const dep = service.deployment;
  if (!dep) return t("Нет развёртываний", "Joylashtirish yo'q", "No deployments");
  const labels = {
    SUCCESS: t("Работает", "Ishlamoqda", "Running"),
    CRASHED: t("Сбой", "Nosozlik", "Crashed"),
    FAILED: t("Ошибка развёртывания", "Joylashtirish xatosi", "Deployment failed"),
    COMPLETED: t("Завершён", "Tugallangan", "Completed"),
    SLEEPING: t("Спящий", "Uyquda", "Sleeping"),
    BUILDING: t("Сборка", "Yig'ilmoqda", "Building"),
    DEPLOYING: t("Запускается", "Ishga tushmoqda", "Deploying"),
  };
  if (["CRASHED", "FAILED"].includes(dep.status)) return labels[dep.status];
  if (dep.stopped) return t("Остановлен", "To'xtatilgan", "Stopped");
  if (dep.status === "SUCCESS" && service.cron_schedule) return t("По расписанию", "Jadval bo'yicha", "Scheduled");
  return labels[dep.status] || dep.status;
}

export default function RailwayPanel({ readJson, t }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [details, setDetails] = useState(null);
  const [logs, setLogs] = useState(null);
  const [detailError, setDetailError] = useState("");
  const [detailBusy, setDetailBusy] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [cooldowns, setCooldowns] = useState({});
  const alive = useRef(false);
  const refreshing = useRef(false);
  const detailVersion = useRef(0);
  const actionPending = useRef(false);
  const detailsPanel = useRef(null);
  const detailsServiceId = details?.service.id;

  useEffect(() => {
    if (detailsServiceId && detailsPanel.current) {
      detailsPanel.current.focus({ preventScroll: true });
      detailsPanel.current.scrollIntoView({ block: "start" });
    }
  }, [detailsServiceId]);

  const refresh = useCallback(async () => {
    if (refreshing.current) return;
    refreshing.current = true;
    setLoading(true);
    try {
      const next = await readJson("/api/admin/railway");
      if (alive.current) { setData(next); setError(""); }
    } catch (e) {
      if (alive.current) setError(e.message);
    } finally {
      refreshing.current = false;
      if (alive.current) setLoading(false);
    }
  }, [readJson]);

  useEffect(() => {
    alive.current = true;
    refresh();
    const timer = setInterval(() => { if (!document.hidden) refresh(); }, 30000);
    return () => { alive.current = false; detailVersion.current += 1; clearInterval(timer); };
  }, [refresh]);

  const loadLogs = async (service, deploymentId, kind, history = []) => {
    const version = ++detailVersion.current;
    setDetails({ service, deploymentId, kind, history });
    setLogs(null); setDetailError(""); setDetailBusy(true);
    try {
      const result = await readJson(`/api/admin/railway/services/${service.id}/deployments/${deploymentId}/logs?kind=${kind}`);
      if (alive.current && version === detailVersion.current) setLogs(result);
    } catch (e) {
      if (alive.current && version === detailVersion.current) setDetailError(e.message);
    } finally {
      if (alive.current && version === detailVersion.current) setDetailBusy(false);
    }
  };

  const openDetails = async (service) => {
    const version = ++detailVersion.current;
    setDetails({ service, history: [], deploymentId: "", kind: "runtime" });
    setLogs(null); setDetailError(""); setDetailBusy(true);
    try {
      const result = await readJson(`/api/admin/railway/services/${service.id}/deployments`);
      if (!alive.current || version !== detailVersion.current) return;
      const history = result.deployments || [];
      const selected = history[0];
      if (selected) await loadLogs(service, selected.id, selected.status === "FAILED" ? "build" : "runtime", history);
      else setDetailBusy(false);
    } catch (e) {
      if (alive.current && version === detailVersion.current) { setDetailError(e.message); setDetailBusy(false); }
    }
  };

  const recover = async () => {
    if (!confirm || actionPending.current) return;
    const service = confirm;
    actionPending.current = true;
    setBusy(true); setNotice("");
    setCooldowns((old) => ({ ...old, [service.id]: Date.now() + 60000 }));
    try {
      await readJson(`/api/admin/railway/services/${service.id}/recover`, {
        method: "POST", body: JSON.stringify({ deployment_id: service.deployment.id,
          action: service.recovery_action, confirm: true }),
      });
      if (alive.current) setNotice(t("Запрос принят Railway. Ожидаем обновления состояния; восстановление ещё не подтверждено.",
        "Railway so'rovni qabul qildi. Holat yangilanishi kutilmoqda; tiklanish hali tasdiqlanmagan.",
        "Railway accepted the request. Waiting for status updates; recovery is not confirmed yet."));
    } catch (e) {
      if (alive.current) setNotice(`${e.message} ${t("Проверьте состояние перед повтором.", "Qayta urinishdan oldin holatni tekshiring.", "Check status before trying again.")}`);
    } finally {
      actionPending.current = false;
      if (alive.current) { setBusy(false); setConfirm(null); await refresh(); }
    }
  };

  const failures = data?.services?.filter((s) => ["CRASHED", "FAILED"].includes(s.deployment?.status)).length || 0;
  return <section className="admin-section railway-panel" aria-label="Railway">
    <div className="panel railway-toolbar">
      <div><h2>Railway {data?.environment ? <span className="admin-muted">· {data.environment}</span> : null}</h2>
        <p className="admin-muted">{t("Проверка каждые 30 секунд, пока эта вкладка открыта.",
          "Bu sahifa ochiq bo'lsa, har 30 soniyada tekshiriladi.", "Checks every 30 seconds while this page is open.")}</p>
        {data?.checked_at ? <small>{t("Проверено", "Tekshirildi", "Checked")} {stamp(data.checked_at)} · {error ? t("Данные устарели", "Ma'lumot eskirgan", "Data is stale") : `${failures} ${t("сбоев", "nosozlik", "failures")}`}</small> : null}
      </div>
      <button className="admin-btn" disabled={loading} onClick={refresh}>{loading ? t("Проверяем…", "Tekshirilmoqda…", "Checking…") : t("Обновить", "Yangilash", "Refresh")}</button>
    </div>
    {error ? <div className="admin-error" role="alert">{error} {t("Состояние сервисов неизвестно. Действия отключены.", "Xizmatlar holati noma'lum. Amallar o'chirilgan.", "Current service state is unknown. Actions are disabled.")}</div> : null}
    {notice ? <div className="panel" role="status">{notice}</div> : null}
    {!data && loading ? <p role="status">{t("Загружаем сервисы…", "Xizmatlar yuklanmoqda…", "Loading services…")}</p> : null}
    {data?.configured === false ? <div className="panel">
      <h3>{t("Railway ещё не подключён", "Railway hali ulanmagan", "Railway is not connected yet")}</h3>
      <p>{t("На сервере нужны токен проекта и идентификаторы проекта и окружения. Кнопки восстановления включаются отдельно для выбранных сервисов.",
        "Serverda loyiha tokeni, loyiha va muhit IDlari kerak. Tiklash tugmalari tanlangan xizmatlar uchun alohida yoqiladi.",
        "The server needs a project token and project/environment IDs. Recovery controls are enabled separately for selected services.")}</p>
      <p className="admin-muted">{t("Не вводите токены в браузере. Настройка описана в DEPLOY.md.", "Tokenlarni brauzerga kiritmang. Sozlash DEPLOY.md da.", "Do not enter tokens in the browser. Setup is documented in DEPLOY.md.")}</p>
    </div> : null}
    {data?.configured && !data.services.length ? <p>{t("В этом окружении нет сервисов.", "Bu muhitda xizmatlar yo'q.", "No services in this environment.")}</p> : null}
    <div className={`railway-grid${error ? " is-stale" : ""}`}>
      {(data?.services || []).map((service) => {
        const failed = ["CRASHED", "FAILED"].includes(service.deployment?.status);
        const pending = (cooldowns[service.id] || 0) > Date.now();
        return <article key={service.id} className="panel railway-service" aria-label={service.name}>
          <div className="railway-service-head"><h3>{service.name}</h3><span className="admin-pill"><span className={`admin-dot ${error ? "" : failed ? "err" : service.deployment?.status === "SUCCESS" && !service.deployment?.stopped ? "ok" : "warn"}`} />{stateLabel(service, t)}</span></div>
          <dl><dt>{t("Состояние изменено", "Holat o'zgardi", "Status changed")}</dt><dd>{stamp(service.deployment?.changed_at)}</dd>
            <dt>{t("Тип", "Turi", "Type")}</dt><dd>{service.cron_schedule ? t("Плановая задача", "Rejalashtirilgan vazifa", "Scheduled job") : t("Постоянный сервис", "Doimiy xizmat", "Persistent service")}</dd>
            {service.cron_schedule ? <><dt>{t("Следующий запуск", "Keyingi ishga tushish", "Next scheduled run")}</dt><dd>{stamp(service.next_run_at)}</dd></> : null}
          </dl>
          <div className="railway-actions">
            <button className="admin-btn" disabled={!service.deployment || !!error} onClick={() => openDetails(service)}>{t("Логи и история", "Loglar va tarix", "Logs & history")}</button>
            <a className="admin-btn" href={service.railway_url} target="_blank" rel="noopener noreferrer">Railway ↗</a>
            {service.recovery_action ? <button className="admin-btn accent" disabled={!!error || busy || pending} onClick={() => { setConfirm(service); setNotice(""); }}>{pending ? t("Ожидание…", "Kutilmoqda…", "Waiting…") : service.recovery_action === "restart" ? t("Перезапустить", "Qayta ishga tushirish", "Restart") : t("Повторить развёртывание", "Qayta joylashtirish", "Redeploy")}</button> : failed ? <small className="admin-muted">{t("Восстановление доступно в Railway; кнопка здесь не включена.", "Tiklash Railwayda mavjud; bu yerdagi tugma yoqilmagan.", "Recovery is available in Railway; the control here is not enabled.")}</small> : null}
          </div>
          {confirm?.id === service.id ? <div className="railway-confirm" role="group" aria-label={t("Подтвердите восстановление", "Tiklashni tasdiqlang", "Confirm recovery")}>
            <p>{t("Восстановить", "Tiklash", "Recover")} <strong>{service.name}</strong>? {t("Будет использован тот же код. Повторный запуск не исправляет причину сбоя и может повторить операции задачи.",
              "Xuddi shu kod ishlatiladi. Qayta ishga tushirish sababni tuzatmaydi va vazifa amallarini takrorlashi mumkin.",
              "This uses the same code. Restarting does not fix the cause and may repeat job operations.")}</p>
            <div className="railway-actions"><button className="admin-btn accent" disabled={busy || !!error} onClick={recover}>{busy ? t("Отправляем…", "Yuborilmoqda…", "Sending…") : t("Подтвердить", "Tasdiqlash", "Confirm")}</button><button className="admin-btn" disabled={busy} onClick={() => setConfirm(null)}>{t("Отмена", "Bekor qilish", "Cancel")}</button></div>
          </div> : null}
        </article>;
      })}
    </div>
    {details ? <div className="panel railway-details" ref={detailsPanel} tabIndex={-1}>
      <div className="railway-service-head"><h3>{details.service.name} · {t("Логи и история", "Loglar va tarix", "Logs & history")}</h3><button className="admin-btn" onClick={() => { detailVersion.current += 1; setDetails(null); }}>{t("Закрыть", "Yopish", "Close")}</button></div>
      <p className="admin-muted">{t("Последние 10 развёртываний и до 80 строк логов. История зависит от срока хранения Railway; это не полный журнал инцидентов.",
        "Oxirgi 10 joylashtirish va 80 tagacha log satri. Tarix Railway saqlash muddatiga bog'liq; bu to'liq hodisalar jurnali emas.",
        "Latest 10 deployments and up to 80 log lines. History depends on Railway retention; this is not a complete incident archive.")}</p>
      {details.history.length ? <div className="railway-actions">
        <label>{t("Развёртывание", "Joylashtirish", "Deployment")} <select aria-label={t("Развёртывание", "Joylashtirish", "Deployment")} value={details.deploymentId} onChange={(e) => loadLogs(details.service, e.target.value, details.kind, details.history)}>{details.history.map((dep) => <option key={dep.id} value={dep.id}>{stamp(dep.changed_at || dep.created_at)} · {dep.status} · {dep.id.slice(0, 8)}</option>)}</select></label>
        <label>{t("Логи", "Loglar", "Logs")} <select aria-label={t("Логи", "Loglar", "Logs")} value={details.kind} onChange={(e) => loadLogs(details.service, details.deploymentId, e.target.value, details.history)}><option value="runtime">{t("Выполнение", "Bajarilish", "Runtime")}</option><option value="build">{t("Сборка", "Yig'ish", "Build")}</option></select></label>
      </div> : null}
      {detailBusy ? <p role="status">{t("Загрузка логов…", "Loglar yuklanmoqda…", "Loading logs…")}</p> : null}
      {detailError ? <p className="admin-error" role="alert">{detailError}</p> : null}
      {logs?.error_excerpt ? <div className="railway-excerpt"><strong>{t("Ошибка из лога — возможная причина", "Logdagi xato — ehtimoliy sabab", "Error from logs — possible cause")}</strong><pre>{logs.error_excerpt}</pre></div> : null}
      {logs ? <><pre className="railway-log" tabIndex={0}>{logs.lines.length ? logs.lines.map((line) => `${line.timestamp || ""} ${line.severity || ""} ${line.message}`).join("\n") : t("Логов нет. Причина неизвестна или срок хранения истёк.", "Loglar yo'q. Sabab noma'lum yoki saqlash muddati tugagan.", "No logs available. The cause is unknown or logs have expired.")}</pre><p className="admin-muted">{t("Известные форматы секретов скрыты. Логи всё ещё могут содержать внутреннюю информацию — не публикуйте их без проверки.", "Ma'lum maxfiy formatlar yashirilgan. Loglarda ichki ma'lumot bo'lishi mumkin — tekshirmasdan ulashmang.", "Known secret formats are masked. Logs may still contain internal information; review before sharing.")}</p></> : null}
    </div> : null}
    <p className="admin-muted">{t("Если упадёт сервер сайта или база авторизации, эта панель тоже станет недоступна. Используйте Railway для восстановления самого сайта. Для независимого контроля нужен отдельный сервис мониторинга.",
      "Sayt serveri yoki avtorizatsiya bazasi ishlamasa, panel ham ochilmaydi. Saytni Railway orqali tiklang. Mustaqil nazorat uchun alohida monitoring xizmati kerak.",
      "If the website server or authentication database goes down, this panel is unavailable too. Recover the website through Railway. Independent monitoring requires a separate service.")}</p>
  </section>;
}
