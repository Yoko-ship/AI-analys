import { DASH, fmtInt, fmtNum, fmtShare, fmtDay } from "./adminModel.js";
import { Stat, deltaBadge, DailyBars, NoTraffic } from "./AdminWidgets.jsx";
export function ProductOverviewSection({
  metrics,
  t,
  overview,
  streams,
  staleStreams,
  openCounts
}) {
  const mVisitors = metrics && metrics.visitors || {};
  const mReg = metrics && metrics.registrations || {};
  const mAn = metrics && metrics.analyses || {};
  const todayDelta = deltaBadge(mVisitors.today, mVisitors.yesterday);
  const weekDelta = deltaBadge(mVisitors.d7, mVisitors.prev7);
  return <div className="admin-section">
      <div className="admin-stats">
        <Stat
          label={t("Посетителей сегодня", "Bugungi tashrifchilar", "Visitors today")}
          value={fmtInt(mVisitors.today)}
          badge={todayDelta ? todayDelta.text : null}
          badgeIcon={todayDelta ? todayDelta.icon : null}
          line1={t(`Вчера — ${fmtInt(mVisitors.yesterday)}`, `Kecha — ${fmtInt(mVisitors.yesterday)}`, `Yesterday — ${fmtInt(mVisitors.yesterday)}`)}
          line2={t(`Просмотров сегодня — ${fmtInt(metrics && metrics.pageviews_today)}`, `Bugungi ko'rishlar — ${fmtInt(metrics && metrics.pageviews_today)}`, `Page views today — ${fmtInt(metrics && metrics.pageviews_today)}`)}
        />
        <Stat
          label={t("За 7 дней", "7 kun ichida", "Last 7 days")}
          value={fmtInt(mVisitors.d7)}
          badge={weekDelta ? weekDelta.text : null}
          badgeIcon={weekDelta ? weekDelta.icon : null}
          line1={t(`За 30 дней — ${fmtInt(mVisitors.d30)}`, `30 kun — ${fmtInt(mVisitors.d30)}`, `30 days — ${fmtInt(mVisitors.d30)}`)}
          line2={t("Уникальные посетители", "Noyob tashrifchilar", "Unique visitors")}
        />
        <Stat label={t("Прилипчивость DAU/MAU", "DAU/MAU", "Stickiness DAU/MAU")} value={fmtShare(metrics && metrics.stickiness, 1)} line1={t(`средний DAU за неделю — ${fmtNum(metrics && metrics.avg_dau_7d, 1)}`, `haftalik o'rtacha DAU — ${fmtNum(metrics && metrics.avg_dau_7d, 1)}`, `avg DAU last week — ${fmtNum(metrics && metrics.avg_dau_7d, 1)}`)} line2={t("≈20% — здоровый продукт; <10% — разовые визиты", "≈20% — sog'lom mahsulot", "≈20% is healthy; below 10% means one-off visits")} />
        <Stat label={t("Сейчас на сайте", "Hozir saytda", "Live now")} value={fmtInt(metrics && metrics.live_now)} line1={t("за последние 5 минут", "so'nggi 5 daqiqada", "in the last 5 minutes")} line2={t(`Вошедших сегодня — ${fmtInt(metrics && metrics.signed_in && metrics.signed_in.today)}`, `Bugun kirganlar — ${fmtInt(metrics && metrics.signed_in && metrics.signed_in.today)}`, `Signed-in today — ${fmtInt(metrics && metrics.signed_in && metrics.signed_in.today)}`)} />
      </div>

      <div className="panel">
        <div className="admin-chart-head">
          <div>
            <h2>{t("Посетители по дням", "Kunlik tashrifchilar", "Visitors by day")}</h2>
            <p>{t("Последние 14 дней, граница суток — Ташкент", "So'nggi 14 kun, Toshkent vaqti", "Last 14 days, Tashkent day boundary")}</p>
          </div>
        </div>
        {metrics && metrics.daily && metrics.daily.length ? <DailyBars data={metrics.daily} valueKey="visitors" titleFn={r => `${fmtDay(r.day)} · ${fmtInt(r.visitors)} ${t("чел.", "kishi", "visitors")} · ${fmtInt(r.pageviews)} ${t("просмотров", "ko'rish", "views")}`} /> : <NoTraffic t={t} />}
      </div>

      <div className="admin-stats">
        <Stat label={t("Регистраций сегодня", "Bugungi ro'yxatdan o'tish", "Registrations today")} value={fmtInt(mReg.today)} line1={t(`за 7 дней — ${fmtInt(mReg.d7)}`, `7 kun — ${fmtInt(mReg.d7)}`, `7 days — ${fmtInt(mReg.d7)}`)} line2={t(`всего аккаунтов — ${fmtInt(mReg.total)}`, `jami — ${fmtInt(mReg.total)}`, `total accounts — ${fmtInt(mReg.total)}`)} />
        <Stat label={t("Анализов сегодня", "Bugungi tahlillar", "Analyses today")} value={fmtInt(mAn.today)} line1={t(`за 7 дней — ${fmtInt(mAn.d7)}`, `7 kun — ${fmtInt(mAn.d7)}`, `7 days — ${fmtInt(mAn.d7)}`)} line2={t("Запуски AI-анализа", "AI-tahlil ishga tushirishlari", "AI analysis runs")} />
        <Stat
          label={t("Потоки данных", "Ma'lumot oqimlari", "Data streams")}
          value={overview ? `${streams.length - staleStreams}/${streams.length}` : DASH}
          warn={Boolean(staleStreams)}
          line1={staleStreams ? t(`${staleStreams} устарел(и)`, `${staleStreams} eskirgan`, `${staleStreams} stale`) : t("Все потоки писали недавно", "Barcha oqimlar yaqinda yozgan", "Every stream wrote recently")}
          line2={t("Подробности — в «Системе»", "Tafsilotlar — «Tizim»da", "Details under System")}
        />
        <Stat
          label={t("Блокирующих находок", "Bloklovchi topilmalar", "Blocking findings")}
          value={overview ? fmtInt(openCounts.blocking) : DASH}
          warn={Boolean(openCounts.blocking)}
          line1={overview ? t(`Предупреждений — ${fmtInt(openCounts.warning)}`, `Ogohlantirish — ${fmtInt(openCounts.warning)}`, `Warnings — ${fmtInt(openCounts.warning)}`) : null}
          line2={t("Аудит данных — в «Системе»", "Ma'lumot auditi — «Tizim»da", "Data audit under System")}
        />
      </div>
    </div>;
}
