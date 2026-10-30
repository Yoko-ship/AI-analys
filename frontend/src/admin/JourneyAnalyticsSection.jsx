import { useEffect, useState } from "react";
import CONTROLS from "../../../analytics_controls.json" with { type: "json" };
import { fmtInt } from "./adminModel.js";
import { Skeleton, Stat } from "./AdminWidgets.jsx";
import { ReportTable } from "./ProductReportTable.jsx";

function actionName(row, t) {
  const control = CONTROLS[row.control_id];
  if (!control) return row.kind === "feature" ? t("Действие", "Amal", "Feature action") : t("Открытие страницы", "Sahifa ochilishi", "Page open");
  const value = control.values[row.control_value];
  return `${t(...control.label)}${value ? ` · ${t(...value)}` : ""}`;
}
function time(value) {
  return value ? new Date(value).toLocaleString("en-GB", { timeZone: "Asia/Tashkent", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
}
async function read(apiFetch, url) {
  const response = await apiFetch(url);
  if (!response.ok) throw new Error("request failed");
  const data = await response.json();
  if (!data.ok) throw new Error("report unavailable");
  return data;
}

function VisitTimeline({ apiFetch, visit, through, t }) {
  const [retry, setRetry] = useState(0);
  const [cursor, setCursor] = useState(0);
  const [state, setState] = useState({ loading: true, events: [] });
  useEffect(() => {
    let cancelled = false;
    setState(old => ({ ...old, loading: true, error: false }));
    read(apiFetch, `/api/admin/metrics/journeys/${visit}?through=${through}&after=${cursor}`)
      .then(data => { if (!cancelled) setState(old => ({ data, events: cursor ? [...old.events, ...data.events] : data.events })); })
      .catch(() => { if (!cancelled) setState(old => ({ ...old, loading: false, error: true })); });
    return () => { cancelled = true; };
  }, [apiFetch, visit, through, cursor, retry]);
  return <section className="panel product-report journey-timeline" role="region" aria-label={t("Хронология визита", "Tashrif tarixi", "Visit timeline")}>
    <div className="admin-chart-head"><div><h2>{t(`Визит ${visit}`, `Tashrif ${visit}`, `Visit ${visit}`)}</h2>
      <p>{t("Порядок получения событий · время Ташкента", "Hodisalar kelish tartibi · Toshkent vaqti", "Recorded order · Tashkent time")}</p></div></div>
    {state.events.length > 0 && <ol className="journey-events">{state.events.map(event => <li key={event.id}>
      <time dateTime={event.at}>{time(event.at)}</time><div><strong>{actionName(event, t)}</strong>{event.ticker && <span className="journey-ticker">{event.ticker}</span>}
      <small>{event.path || "—"}{event.target_path ? ` → ${event.target_path}` : ""}</small></div>
    </li>)}</ol>}
    {state.loading && <Skeleton rows={3} />}
    {state.error && <div role="alert" className="admin-error"><p>{t("Не удалось загрузить визит.", "Tashrifni yuklab bo‘lmadi.", "Could not load this visit.")}</p>
      <button type="button" className="admin-btn" onClick={() => setRetry(n => n + 1)}>{t("Повторить загрузку визита", "Tashrifni qayta yuklash", "Retry visit")}</button></div>}
    {!state.loading && !state.error && state.data?.next_after != null && <button className="admin-btn" type="button" onClick={() => setCursor(state.data.next_after)}>{t("Ещё события", "Yana hodisalar", "More events")}</button>}
    {!state.loading && !state.error && !state.events.length && <p className="admin-muted">{t("Событий нет.", "Hodisalar yo‘q.", "No recorded events.")}</p>}
  </section>;
}

function JourneysReport({ apiFetch, days, t }) {
  const [retry, setRetry] = useState(0);
  const [page, setPage] = useState(null);
  const [visit, setVisit] = useState(null);
  const [state, setState] = useState({ loading: true, sessions: [] });
  useEffect(() => {
    let cancelled = false;
    setState(old => ({ ...old, loading: true, error: false }));
    const suffix = page ? `&before=${page.before}&through=${page.through}` : "";
    read(apiFetch, `/api/admin/metrics/journeys?days=${days}${suffix}`)
      .then(data => { if (!cancelled) setState(old => ({ data, sessions: page ? [...old.sessions, ...data.sessions] : data.sessions })); })
      .catch(() => { if (!cancelled) setState(old => ({ ...old, loading: false, error: true })); });
    return () => { cancelled = true; };
  }, [apiFetch, days, page, retry]);
  const data = state.data;
  const empty = t("Нет данных за этот период.", "Bu davr uchun ma’lumot yo‘q.", "No data for this period.");
  return <>
    {data && <>
      <div className="admin-stats">
        <Stat label={t("Визиты", "Tashriflar", "Sessions")} value={fmtInt(data.totals.sessions)} line1={t("Активные в выбранные дни", "Tanlangan kunlarda faol", "Active within the selected days")} />
        <Stat label={t("Клики", "Bosishlar", "Clicks")} value={fmtInt(data.totals.clicks)} line1={t("По размеченным элементам", "Belgilangan elementlarda", "On instrumented controls")} />
        <Stat label={t("Просмотры страниц", "Sahifa ko‘rishlari", "Page views")} value={fmtInt(data.totals.pageviews)} line1={t("В этих визитах", "Shu tashriflarda", "Within these sessions")} />
        <Stat label={t("Измеренные визиты", "O‘lchangan tashriflar", "Measured sessions")} value={`${fmtInt(data.coverage.click_sessions)} / ${fmtInt(data.totals.sessions)}`} line1={t("С поддержкой записи кликов", "Bosishlarni qayd etish yoqilgan", "With click tracking available")} />
      </div>
      <p className="product-coverage">{t("Записываются размеченные кнопки, вкладки и публичные ссылки, включая активацию клавиатурой. Введённый текст не собирается. Старые клики восстановить нельзя; часть событий может не дойти.", "Belgilangan tugmalar, bo‘limlar va ochiq havolalar, jumladan klaviatura orqali faollashtirish qayd etiladi. Kiritilgan matn yig‘ilmaydi. Eski bosishlar tiklanmaydi; ayrim hodisalar yetib kelmasligi mumkin.", "Tracks named buttons, tabs and public links, including keyboard activation. Typed text is excluded. Old clicks cannot be recovered, and some events may not arrive.")}</p>
      <ReportTable title={t("Использование элементов", "Elementlardan foydalanish", "Control usage")} description={t("До 50 элементов. Повтор — более одного клика в одном визите; это не обязательно ошибка.", "50 tagacha element. Takror — bir tashrifda bir necha bosish; bu xato degani emas.", "Top 50 controls. Repeat means multiple clicks in one visit; it does not necessarily indicate a problem.")} rows={data.controls} empty={empty}
        columns={[t("Элемент", "Element", "Control"), t("Клики", "Bosishlar", "Clicks"), t("Посетители", "Tashrifchilar", "Visitors"), t("Визиты", "Tashriflar", "Sessions"), t("Визиты с повтором", "Takroriy tashriflar", "Visits with repeats")]}>
        {data.controls.map((r, i) => <tr key={i}><th scope="row">{actionName(r, t)}</th><td>{fmtInt(r.clicks)}</td><td>{fmtInt(r.visitors)}</td><td>{fmtInt(r.sessions)}</td><td>{fmtInt(r.repeated_sessions)}</td></tr>)}
      </ReportTable>
      <ReportTable title={t("Последние действия", "Oxirgi amallar", "Last recorded actions")} description={t("Последнее полученное событие визита. Оно не подтверждает уход или отказ.", "Tashrifning oxirgi kelgan hodisasi. Bu chiqish yoki rad etishni tasdiqlamaydi.", "The last received action in a visit. This does not confirm an exit or abandonment.")} rows={data.last_actions} empty={empty}
        columns={[t("Действие / страница", "Amal / sahifa", "Action / page"), t("Визиты", "Tashriflar", "Sessions")]}>
        {data.last_actions.map((r, i) => <tr key={i}><th scope="row">{actionName(r, t)}<small>{r.path || "—"}</small></th><td>{fmtInt(r.sessions)}</td></tr>)}
      </ReportTable>
      <ReportTable title={t("Последние визиты", "So‘nggi tashriflar", "Recent visits")} description={t("Анонимные визиты по последней активности. Откройте визит, чтобы увидеть последовательность действий.", "Oxirgi faollik bo‘yicha anonim tashriflar. Amallar ketma-ketligini ko‘rish uchun tashrifni oching.", "Anonymous visits ordered by latest activity. Open a visit to see its sequence of actions.")} rows={state.sessions} empty={empty}
        columns={[t("Визит", "Tashrif", "Visit"), t("Начало · Ташкент", "Boshlanish · Toshkent", "Started · Tashkent"), t("Источник", "Manba", "Source"), t("Страницы", "Sahifalar", "Pages"), t("Клики", "Bosishlar", "Clicks")]}>
        {state.sessions.map(s => <tr key={s.id}><th scope="row"><button type="button" className="admin-btn" aria-pressed={visit === s.id} onClick={() => setVisit(s.id)}>{t(`Визит ${s.id}`, `Tashrif ${s.id}`, `Visit ${s.id}`)}</button><small>{s.last_path || "—"}</small></th><td>{time(s.started)}</td><td>{s.source}</td><td>{fmtInt(s.pageviews)}</td><td>{s.measured ? fmtInt(s.clicks) : <span title={t("Старая версия отслеживания", "Eski kuzatuv versiyasi", "Older tracking version")}>{t("Запись кликов недоступна", "Bosishlar qaydi mavjud emas", "Click tracking unavailable")}</span>}</td></tr>)}
      </ReportTable>
      {!state.loading && !state.error && data.next_before != null && <button type="button" className="admin-btn" onClick={() => setPage({ before: data.next_before, through: data.through })}>{t("Ещё визиты", "Yana tashriflar", "More visits")}</button>}
      {visit != null && <VisitTimeline key={`${visit}-${data.through}`} apiFetch={apiFetch} visit={visit} through={data.through} t={t} />}
    </>}
    {state.loading && <Skeleton rows={4} />}
    {state.error && <div role="alert" className="admin-error"><p>{t("Не удалось загрузить пути посетителей.", "Tashrif yo‘llarini yuklab bo‘lmadi.", "Could not load visitor journeys.")}</p><button type="button" className="admin-btn" onClick={() => setRetry(n => n + 1)}>{t("Повторить", "Qayta urinish", "Retry")}</button></div>}
  </>;
}

export function JourneyAnalyticsSection({ apiFetch, t }) {
  const [days, setDays] = useState(7);
  const [refresh, setRefresh] = useState(0);
  return <div className="admin-section product-analytics">
    <div className="admin-panel-bar"><div className="admin-seg" aria-label={t("Период кликов", "Bosishlar davri", "Clicks period")}>{[1,7,30,90].map(n => <button type="button" key={n} aria-pressed={days === n} onClick={() => setDays(n)}>{n === 1 ? t("Сегодня", "Bugun", "Today") : t(`${n} дн.`, `${n} kun`, `${n} days`)}</button>)}</div>
      <span className="admin-muted">{t("Включая сегодня · Ташкент", "Bugunni qo‘shib · Toshkent", "Including today · Tashkent")}</span>
      <button className="admin-btn" type="button" onClick={() => setRefresh(n => n + 1)}>{t("Обновить", "Yangilash", "Refresh")}</button></div>
    <JourneysReport key={`${days}-${refresh}`} apiFetch={apiFetch} days={days} t={t} />
  </div>;
}
