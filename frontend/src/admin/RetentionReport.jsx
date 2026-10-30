import { fmtInt, fmtShare } from "./adminModel.js";
import { ReportTable } from "./ProductReportTable.jsx";

export function RetentionReport({ data, t }) {
  const title = t("Возврат за 7 дней", "7 kun ichida qaytish", "7-day return rate");
  if (!data) return <section className="panel product-report" role="region" aria-label={title}>
    <div className="admin-chart-head"><div><h2>{title}</h2><p>{t("Данные о возвратах пока недоступны.", "Qaytish ma’lumotlari hozircha mavjud emas.", "Return measurements are not available yet.")}</p></div></div>
  </section>;
  const pending = data.pending_visitors || 0;
  return <section className="panel product-report retention-report" role="region" aria-label={title}>
    <div className="admin-chart-head"><div><h2>{title}</h2>
      <p>{t("Дни 1–7 после первого использования финансов, графиков, коэффициентов, документов или дивидендов.", "Moliya, grafiklar, koeffitsiyentlar, hujjatlar yoki dividendlardan ilk foydalanishdan keyingi 1–7-kunlar.", "Days 1–7 after first use of financials, charts, ratios, reports or dividends.")}</p>
    </div></div>
    <div className="retention-summary">
      <div><strong className="retention-rate">{fmtShare(data.return_rate)}</strong>
        <p>{data.eligible_visitors > 0
          ? t(`${fmtInt(data.returned_visitors)} из ${fmtInt(data.eligible_visitors)} активированных посетителей вернулись`, `${fmtInt(data.eligible_visitors)} faol tashrifchidan ${fmtInt(data.returned_visitors)} tasi qaytdi`, `${fmtInt(data.returned_visitors)} of ${fmtInt(data.eligible_visitors)} activated visitors returned`)
          : pending ? t("Ожидаем завершения окон возврата", "Qaytish muddatlari tugashini kutmoqdamiz", "Waiting for complete return windows")
            : t("Нет записанных активаций с полным окном в этом периоде.", "Bu davrda to‘liq muddatli faollashuvlar qayd etilmagan.", "No recorded activations with complete windows in this period.")}</p>
      </div>
      <dl className="retention-context">
        <div><dt>{t("Первое использование", "Ilk foydalanish", "First-use dates")}</dt><dd>{data.cohort_period.start} — {data.cohort_period.end}</dd></div>
        <div><dt>{t("Возвраты учтены по", "Qaytishlar shu sanagacha", "Returns observed through")}</dt><dd>{data.observed_through} · {t("Ташкент", "Toshkent", "Tashkent")}</dd></div>
      </dl>
    </div>
    <p className="admin-muted retention-definition">{t("Период первого использования сдвинут на 7 дней назад, чтобы у всех было полное окно возврата. Считается новый визит в следующие 7 календарных дней; день активации не входит. Один браузер попадает в группу только один раз за всю записанную историю.", "Barchaga to‘liq qaytish muddati berilishi uchun ilk foydalanish davri 7 kun orqaga surilgan. Keyingi 7 kalendar kundagi yangi tashrif hisoblanadi; faollashuv kuni kirmaydi. Har bir brauzer qayd etilgan tarix davomida guruhga bir marta kiradi.", "First-use dates are shifted back 7 days so everyone has a complete return window. Counts a new visit during the next 7 calendar days, excluding the activation day. Each browser enters a cohort only once in recorded history.")}</p>
    {pending > 0 && <div className="product-coverage retention-pending">
      <strong>{t(`${fmtInt(pending)} посетителей ещё в окне возврата`, `${fmtInt(pending)} tashrifchining qaytish muddati hali tugamagan`, `${fmtInt(pending)} visitors still in their return window`)}</strong>
      <p>{t("Они пока не входят в процент, даже если уже вернулись.", "Ular allaqachon qaytgan bo‘lsa ham, hozircha foizga kirmaydi.", "They are excluded from the percentage, even if they have already returned.")}
        {data.next_ready_date && <> {t("Ближайший результат:", "Eng yaqin natija:", "Next results:")} {data.next_ready_date} · {t("Ташкент", "Toshkent", "Tashkent")}</>}</p>
    </div>}
    {!data.history_complete && <p className="admin-muted retention-history">{data.history_since
      ? t(`Записанная история действий начинается ${data.history_since}. Период покрыт не полностью.`, `Amallar tarixi ${data.history_since} dan boshlanadi. Davr to‘liq qamrab olinmagan.`, `Recorded interaction history starts ${data.history_since}. This period has partial coverage.`)
      : t("Истории измеренных действий пока нет. Старые клики восстановить нельзя.", "O‘lchangan amallar tarixi hali yo‘q. Eski bosishlarni tiklab bo‘lmaydi.", "No measured interaction history yet. Past clicks cannot be recovered.")}</p>}
    <ReportTable title={t("Группы по дате активации", "Faollashuv sanasi bo‘yicha guruhlar", "Activation cohorts")}
      description={t("Только группы с полными 7 днями наблюдения. Общая доля рассчитана по посетителям, а не как среднее процентов по дням.", "Faqat to‘liq 7 kun kuzatilgan guruhlar. Umumiy ulush kunlik foizlar o‘rtachasi emas, tashrifchilar bo‘yicha hisoblanadi.", "Only cohorts with 7 complete observation days. The overall rate uses visitor counts, not an average of daily percentages.")}
      columns={[t("Первое использование", "Ilk foydalanish", "First use"), t("Посетители", "Tashrifchilar", "Visitors"), t("Вернулись", "Qaytganlar", "Returned"), t("Доля возврата", "Qaytish ulushi", "Return rate")]}
      rows={data.cohorts} empty={t("Нет зрелых групп за этот период.", "Bu davrda muddati to‘lgan guruhlar yo‘q.", "No mature cohorts for this period.")}>
      {data.cohorts.map(row => <tr key={row.day}><th scope="row">{row.day}</th><td>{fmtInt(row.observed === false ? null : row.visitors)}</td><td>{fmtInt(row.observed === false ? null : row.returned)}</td><td>{fmtShare(row.return_rate)}</td></tr>)}
    </ReportTable>
    <p className="admin-muted retention-footnote">{t("Посетитель — отдельный браузер. Смена устройства, очистка данных или потеря событий могут снизить измеренный возврат. Небольшие группы оценивайте по числу людей вместе с процентом.", "Tashrifchi — alohida brauzer. Qurilma almashishi, ma’lumotlar tozalanishi yoki hodisalar yo‘qolishi o‘lchangan qaytishni kamaytirishi mumkin. Kichik guruhlarda foiz bilan birga odamlar soniga qarang.", "Visitors are unique browsers. Device changes, cleared browser data or lost events can reduce measured returns. For small cohorts, read the counts alongside the percentage.")}</p>
  </section>;
}
