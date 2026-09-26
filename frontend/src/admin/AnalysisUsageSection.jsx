import AnalysisMonitor from "./AnalysisMonitor.jsx";
import { fmtInt, fmtShare, fmtUsd, fmtDay } from "./adminModel.js";
import { Stat, DailyBars, HBarList, RangePicker } from "./AdminWidgets.jsx";
export function AnalysisUsageSection({
  analysisData,
  readJson,
  language,
  rangeDays,
  setRangeDays,
  t
}) {
  const ana = analysisData && analysisData.ok ? analysisData : null;
  const anaTotals = ana && ana.totals || {};
  const anaMtd = ana && ana.month_to_date || {};
  return <div className="admin-section">
      <AnalysisMonitor readJson={readJson} language={language} />
      <div className="admin-panel-bar">
        <RangePicker value={rangeDays} onChange={setRangeDays} t={t} />
      </div>

      <div className="admin-stats">
        <Stat label={t("Анализов", "Tahlillar", "Analyses")} value={fmtInt(anaTotals.analyses)} line1={t(`пользователей — ${fmtInt(anaTotals.users)}`, `foydalanuvchilar — ${fmtInt(anaTotals.users)}`, `users — ${fmtInt(anaTotals.users)}`)} line2={t(`за ${rangeDays} дней`, `${rangeDays} kun ichida`, `over ${rangeDays} days`)} />
        <Stat label={t("Доля кэша", "Kesh ulushi", "Cache hit rate")} value={fmtShare(anaTotals.cache_rate)} line1={t(`из кэша — ${fmtInt(anaTotals.cached)}`, `keshdan — ${fmtInt(anaTotals.cached)}`, `from cache — ${fmtInt(anaTotals.cached)}`)} line2={t("каждый кэш-хит — несписанные деньги", "har bir kesh-xit — sarflanmagan pul", "every cache hit is money not spent")} />
        <Stat label={t("Расход на LLM", "LLM xarajati", "LLM spend")} value={fmtUsd(anaTotals.cost)} line1={t(`на один анализ — ${fmtUsd(anaTotals.cost_per_analysis, 4)}`, `bitta tahlilga — ${fmtUsd(anaTotals.cost_per_analysis, 4)}`, `per analysis — ${fmtUsd(anaTotals.cost_per_analysis, 4)}`)} line2={t(`за ${rangeDays} дней, без кэш-хитов`, `${rangeDays} kun, keshsiz`, `over ${rangeDays} days, cache hits excluded`)} />
        <Stat label={t("Прогноз на месяц", "Oylik prognoz", "Month projection")} value={fmtUsd(anaMtd.projected_cost)} line1={t(`с начала месяца — ${fmtUsd(anaMtd.cost)}`, `oy boshidan — ${fmtUsd(anaMtd.cost)}`, `month to date — ${fmtUsd(anaMtd.cost)}`)} line2={t("линейная экстраполяция текущего темпа", "joriy sur'atning chiziqli davomi", "linear extrapolation of the current rate")} />
      </div>

      <div className="panel">
        <div className="admin-chart-head">
          <div>
            <h2>{t("Анализы по дням", "Kunlik tahlillar", "Analyses by day")}</h2>
            <p>{t(`${rangeDays} дней`, `${rangeDays} kun`, `${rangeDays} days`)}</p>
          </div>
        </div>
        {ana && ana.daily && ana.daily.length ? <DailyBars data={ana.daily} valueKey="analyses" titleFn={r => `${fmtDay(r.day)} · ${fmtInt(r.analyses)} ${t("анализов", "tahlil", "analyses")} · ${fmtUsd(r.cost)}`} /> : <div className="admin-empty">
              {t("За выбранный период анализов не было", "Tanlangan davrda tahlillar bo'lmagan", "No analyses in this period")}
            </div>}
      </div>

      <div className="admin-cols3">
        <div className="panel">
          <h3>{t("Что анализируют", "Nimani tahlil qilishadi", "What gets analysed")}</h3>
          <HBarList rows={ana && ana.top_companies || []} nameFn={r => r.name} valueFn={r => r.analyses} detailFn={r => t(`${fmtInt(r.users)} чел.`, `${fmtInt(r.users)} kishi`, `${fmtInt(r.users)} users`)} />
        </div>
        <div className="panel">
          <h3>{t("Модели и их счёт", "Modellar va hisob", "Models and their bill")}</h3>
          <HBarList rows={ana && ana.models || []} nameFn={r => r.model} valueFn={r => r.analyses} detailFn={r => fmtUsd(r.cost)} />
        </div>
        <div className="panel">
          <h3>{t("Раздача оценок", "Baholar taqsimoti", "Grade distribution")}</h3>
          <HBarList rows={ana && ana.grades || []} nameFn={r => r.grade} valueFn={r => r.analyses} />
        </div>
      </div>
    </div>;
}
