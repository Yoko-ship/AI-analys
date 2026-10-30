import { RetentionReport } from "./RetentionReport.jsx";
import { ReportTable } from "./ProductReportTable.jsx";
import { useEffect, useState } from "react";
import { JourneyAnalyticsSection } from "./JourneyAnalyticsSection.jsx";
import { fmtInt, fmtShare } from "./adminModel.js";
import { Skeleton, Stat } from "./AdminWidgets.jsx";


function PerformanceReport({ apiFetch, t }) {
  const [days, setDays] = useState(7);
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    let cancelled = false;
    setState({ loading: true });
    (async () => {
      try {
        const response = await apiFetch(`/api/admin/metrics/product?days=${days}`);
        if (!response.ok) throw new Error("request failed");
        const data = await response.json();
        if (!data.ok) throw new Error("measurements unavailable");
        if (!cancelled) setState({ data });
      } catch {
        if (!cancelled) setState({ error: true });
      }
    })();
    return () => { cancelled = true; };
  }, [apiFetch, days, retry]);
  const data = state.data;
  const coverage = data?.coverage || {};
  const featureNames = {
    financials: t("Финансовая отчётность", "Moliyaviy hisobotlar", "Financial statements"),
    chart: t("Графики", "Grafiklar", "Charts"),
    ratios: t("Коэффициенты", "Koeffitsiyentlar", "Ratios"),
    reports: t("Документы компании", "Kompaniya hujjatlari", "Company reports"),
    dividends: t("Дивиденды", "Dividendlar", "Dividends"),
    news: t("Новости", "Yangiliklar", "News"),
  };
  const sources = data?.sources || [], companies = data?.companies || [], features = data?.features || [];
  const empty = t("Нет данных за этот период.", "Bu davr uchun ma’lumot yo‘q.", "No data for this period.");
  return <div className="admin-section product-analytics">
    <div className="admin-panel-bar">
      <div className="admin-seg" aria-label={t("Период аналитики", "Tahlil davri", "Analytics period")}>
        {[7, 30, 90].map(n => <button key={n} type="button" aria-pressed={days === n} onClick={() => setDays(n)}>{t(`${n} дней`, `${n} kun`, `${n} days`)}</button>)}
      </div>
      <span className="admin-muted">{t("Полные дни · Ташкент", "To‘liq kunlar · Toshkent", "Complete days · Tashkent")}</span>
    </div>
    {state.loading ? <Skeleton rows={5} /> : state.error ? <div role="alert" className="admin-error">
      <p>{t("Не удалось загрузить аналитику продукта.", "Mahsulot tahlilini yuklab bo‘lmadi.", "Could not load product analytics.")}</p>
      <button type="button" className="admin-btn" onClick={() => setRetry(n => n + 1)}>{t("Повторить", "Qayta urinish", "Retry")}</button>
    </div> : <>
      <div className="product-period">
        <strong>{data.period.start} — {data.period.end}</strong>
        <span>{t("Сравнение", "Taqqoslash", "Compared with")} {data.period.previous_start} — {data.period.previous_end}</span>
      </div>
      <div className="admin-stats">
        <Stat label={t("Посетители", "Tashrifchilar", "Visitors")} value={fmtInt(data.totals.visitors)} line1={t("Уникальные браузеры", "Noyob brauzerlar", "Unique browsers")} />
        <Stat label={t("Визиты", "Tashriflar", "Sessions")} value={fmtInt(data.totals.sessions)} line1={t("По дате начала визита", "Tashrif boshlangan sana bo‘yicha", "Dated by visit start")} />
        <Stat label={t("Вовлечённые визиты", "Faol tashriflar", "Engaged sessions")} value={fmtInt(data.totals.engaged_sessions)} line1={t("30 секунд, 2 страницы или действие", "30 soniya, 2 sahifa yoki amal", "30 seconds, 2 pages or an action")} />
        <Stat label={t("Регистрации из визитов", "Tashrifdan ro‘yxatdan o‘tish", "Attributed registrations")} value={fmtInt(data.totals.registrations)} line1={t("Новые аккаунты с известным визитом", "Tashrifi aniqlangan yangi hisoblar", "New accounts linked to a visit")} />
      </div>
      <RetentionReport data={data.retention} t={t} />
      <p className="admin-muted product-history">
        {coverage.history_since ? t(`История с ${coverage.history_since}.`, `${coverage.history_since} dan beri tarix.`, `History available since ${coverage.history_since}.`) : empty}
        {" "}{t("Малые выборки сравнивайте по числу людей, а не только по процентам.", "Kichik tanlamada foiz bilan birga tashrifchilar sonini ham solishtiring.", "For small samples, compare visitor counts alongside percentages.")}
      </p>
      <ReportTable title={t("Эффективность источников", "Manbalar samaradorligi", "Source performance")}
        description={t("Источник первой страницы визита. Регистрация относится к последнему подходящему визиту. Доля — визиты с регистрацией.", "Tashrifning birinchi sahifasi manbasi. Ro‘yxatdan o‘tish oxirgi mos tashrifga yoziladi. Ulush — ro‘yxatdan o‘tilgan tashriflar.", "Source of the first page. A registration is credited once, to the latest eligible visit. The rate is the share of visits with a registration.")}
        columns={[t("Источник / кампания", "Manba / kampaniya", "Source / campaign"), t("Посетители", "Tashrifchilar", "Visitors"), t("Визиты", "Tashriflar", "Sessions"), t("Вовлечённые", "Faol", "Engaged"), t("Регистрации", "Ro‘yxatdan o‘tish", "Registrations"), t("Доля регистраций", "Ro‘yxatdan o‘tish ulushi", "Registration rate")]}
        rows={sources} empty={empty}>
        {sources.map((r, i) => <tr key={i}><th scope="row"><span>{r.source === "direct" ? t("Прямой / неизвестно", "Bevosita / noma’lum", "Direct / unknown") : r.source}</span><small>{[r.campaign, r.medium].filter(Boolean).join(" · ") || "—"}</small></th><td>{fmtInt(r.visitors)}</td><td>{fmtInt(r.sessions)}</td><td>{fmtInt(r.engaged_sessions)}</td><td>{fmtInt(r.registrations)}</td><td>{fmtShare(r.registration_rate)}</td></tr>)}
      </ReportTable>
      <p className="admin-muted">{t("Для публикаций в Telegram используйте utm_source и utm_campaign: без меток источник может остаться неизвестным.", "Telegram havolalariga utm_source va utm_campaign qo‘shing: belgisiz manba noma’lum qolishi mumkin.", "Tag Telegram links with utm_source and utm_campaign; untagged sharing may appear as direct / unknown.")}</p>
      {!coverage.previous_complete && <p className="product-coverage">{t("История предыдущего периода неполная.", "Oldingi davr tarixi to‘liq emas.", "Previous period has incomplete history.")}</p>}
      <ReportTable title={t("Интерес к компаниям", "Kompaniyalarga qiziqish", "Company interest")}
        description={t("До 100 бумаг по числу читателей. Вернувшиеся уже открывали эту бумагу до выбранного периода.", "O‘quvchilar soni bo‘yicha 100 tagacha qog‘oz. Qaytganlar bu qog‘ozni avval ham ochgan.", "Up to 100 securities ranked by readers. Returning readers viewed the same security before this period.")}
        columns={[t("Тикер", "Tiker", "Ticker"), t("Читатели", "O‘quvchilar", "Readers"), t("Ранее", "Oldingi", "Previous"), t("Изменение", "O‘zgarish", "Change"), t("Вернулись", "Qaytganlar", "Returning"), t("Просмотры", "Ko‘rishlar", "Page views")]}
        rows={companies} empty={empty}>
        {companies.map(r => <tr key={r.ticker}><th scope="row" className="product-ticker">{r.ticker}</th><td>{fmtInt(r.visitors)}</td><td>{fmtInt(r.previous_visitors)}</td><td>{coverage.previous_complete && r.change_pct != null ? `${r.change_pct > 0 ? "+" : ""}${r.change_pct}%` : "—"}</td><td>{fmtInt(r.returning_visitors)}</td><td>{fmtInt(r.pageviews)}</td></tr>)}
      </ReportTable>
      <section className="product-coverage" aria-label={t("Полнота измерений", "O‘lchovlar qamrovi", "Measurement coverage")}>
        <strong>{coverage.measured_sessions ? t(`Измерены действия в ${coverage.measured_sessions} из ${coverage.total_sessions} визитов`, `${coverage.total_sessions} tashrifdan ${coverage.measured_sessions} tasida amallar o‘lchangan`, `${coverage.measured_sessions} of ${coverage.total_sessions} sessions had interaction tracking`) : t("В этом периоде нет измерений действий.", "Bu davrda amallar o‘lchanmagan.", "No interaction measurements in this period.")}</strong>
        <p>{t("Новые измерения не восстанавливают старые клики. Доля использования рассчитана только по измеренным визитам; прочерк означает отсутствие измерений.", "Yangi o‘lchov eski bosishlarni tiklamaydi. Ulush faqat o‘lchangan tashriflardan hisoblanadi; chiziq — o‘lchov yo‘q.", "New tracking cannot recover old clicks. Usage share includes only measured sessions; a dash means unmeasured.")}</p>
      </section>
      <ReportTable title={t("Использование функций", "Funksiyalardan foydalanish", "Feature usage")}
        description={t("Открытие вкладки или изменение представления. Повторное использование — в двух и более визитах. Новости измеряются по открытиям страниц.", "Bo‘limni ochish yoki ko‘rinishni o‘zgartirish. Takroriy foydalanish — ikki yoki ko‘p tashrifda. Yangiliklar sahifa ochilishi bilan o‘lchanadi.", "Opening a tab or changing a view. Repeat use means two or more visits. News is measured by page opens.")}
        columns={[t("Функция", "Funksiya", "Feature"), t("Пользователи", "Foydalanuvchilar", "Users"), t("Визиты", "Tashriflar", "Sessions"), t("Действия / открытия", "Amallar / ochilishlar", "Actions / opens"), t("Повторно", "Takroriy", "Repeat users"), t("Доля визитов", "Tashriflar ulushi", "Usage share")]}
        rows={features} empty={empty}>
        {features.map(r => <tr key={r.feature}><th scope="row">{featureNames[r.feature] || r.feature}<small>{r.measurement === "pageview" ? t("Открытия страниц · все визиты", "Sahifa ochilishi · barcha tashriflar", "Page opens · all sessions") : t("Действия · измеренные визиты", "Amallar · o‘lchangan tashriflar", "Interactions · measured sessions")}</small></th><td>{fmtInt(r.users)}</td><td>{fmtInt(r.sessions)}</td><td>{fmtInt(r.actions)}</td><td>{fmtInt(r.repeat_users)}</td><td>{fmtShare(r.adoption_rate)}</td></tr>)}
      </ReportTable>
    </>}
  </div>;
}


export function ProductAnalyticsSection(props) {
  const [view, setView] = useState("performance");
  const { t } = props;
  return <div className="admin-section product-analytics">
    <div className="admin-seg product-report-switch" aria-label={t("Отчёт продукта", "Mahsulot hisoboti", "Product report")}>
      <button type="button" aria-pressed={view === "performance"} onClick={() => setView("performance")}>{t("Эффективность", "Samaradorlik", "Performance")}</button>
      <button type="button" aria-pressed={view === "journeys"} onClick={() => setView("journeys")}>{t("Клики и пути", "Bosishlar va yo‘llar", "Clicks and journeys")}</button>
    </div>
    {view === "performance" ? <PerformanceReport {...props} /> : <JourneyAnalyticsSection {...props} />}
  </div>;
}
