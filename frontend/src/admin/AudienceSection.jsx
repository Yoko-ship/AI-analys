import { DASH, fmtInt, fmtNum, fmtShare, fmtDuration, fmtDay } from "./adminModel.js";
import { Stat, DailyBars, HBarList, RangePicker, NoTraffic } from "./AdminWidgets.jsx";
export function AudienceSection({
  audienceData,
  rangeDays,
  setRangeDays,
  t,
  KIND_LABELS,
  DEVICE_LABELS,
  LANG_LABELS
}) {
  const aud = audienceData && audienceData.ok ? audienceData : null;
  const audTotals = aud && aud.totals || {};
  return <div className="admin-section">
      <div className="admin-panel-bar">
        <RangePicker value={rangeDays} onChange={setRangeDays} t={t} />
      </div>

      <div className="admin-stats">
        <Stat label={t("Уникальных посетителей", "Noyob tashrifchilar", "Unique visitors")} value={fmtInt(audTotals.visitors)} line1={t(`новых — ${fmtInt(audTotals.new_visitors)} · вернувшихся — ${fmtInt(audTotals.returning_visitors)}`, `yangi — ${fmtInt(audTotals.new_visitors)}`, `new — ${fmtInt(audTotals.new_visitors)} · returning — ${fmtInt(audTotals.returning_visitors)}`)} line2={t(`за ${rangeDays} дней`, `${rangeDays} kun ichida`, `over ${rangeDays} days`)} />
        <Stat label={t("Визитов", "Tashriflar", "Sessions")} value={fmtInt(audTotals.sessions)} line1={t(`просмотров — ${fmtInt(audTotals.pageviews)}`, `ko'rishlar — ${fmtInt(audTotals.pageviews)}`, `page views — ${fmtInt(audTotals.pageviews)}`)} line2={t("новый визит после 30 минут тишины", "30 daqiqadan keyin yangi tashrif", "a new session after 30 idle minutes")} />
        <Stat label={t("Глубина визита", "Tashrif chuqurligi", "Session depth")} value={audTotals.pages_per_session != null ? fmtNum(audTotals.pages_per_session, 1) : DASH} line1={t(`длительность — ${fmtDuration(audTotals.avg_session_seconds, t)}`, `davomiyligi — ${fmtDuration(audTotals.avg_session_seconds, t)}`, `duration — ${fmtDuration(audTotals.avg_session_seconds, t)}`)} line2={t("страниц за визит, в среднем", "har tashrifda sahifalar", "pages per session, average")} />
        <Stat label={t("Отказы", "Rad etishlar", "Bounce rate")} value={fmtShare(audTotals.bounce_rate)} line1={t("визиты из одной страницы", "bir sahifalik tashriflar", "single-page sessions")} line2={t("для терминала с одной доской это не приговор", "bitta doskali terminal uchun bu hukm emas", "for a one-board terminal this is not a verdict")} />
      </div>

      <div className="panel">
        <div className="admin-chart-head">
          <div>
            <h2>{t("Посетители по дням", "Kunlik tashrifchilar", "Visitors by day")}</h2>
            <p>{t(`${rangeDays} дней · граница суток — Ташкент`, `${rangeDays} kun`, `${rangeDays} days · Tashkent day boundary`)}</p>
          </div>
        </div>
        {aud && aud.daily && aud.daily.length ? <DailyBars data={aud.daily} valueKey="visitors" titleFn={r => `${fmtDay(r.day)} · ${fmtInt(r.visitors)} ${t("чел.", "kishi", "visitors")} · ${fmtInt(r.sessions)} ${t("визитов", "tashrif", "sessions")}`} /> : <NoTraffic t={t} />}
      </div>

      <div className="admin-cols2">
        <div className="panel">
          <h3>{t("Откуда приходят", "Qayerdan kelishadi", "Where they come from")}</h3>
          <HBarList rows={aud && aud.referrers || []} nameFn={r => r.host === "(direct)" ? t("Прямые заходы", "To'g'ridan-to'g'ri", "Direct") : r.host} valueFn={r => r.sessions} detailFn={r => KIND_LABELS[r.kind] || ""} />
          {aud && !(aud.referrers || []).length ? <NoTraffic t={t} /> : null}
          <p className="admin-muted admin-note">
            {t("Источник берётся только с первой страницы визита — дальше он повторял бы наши же адреса.", "Manba faqat tashrifning birinchi sahifasidan olinadi.", "The source is taken from the first page of the visit only.")}
          </p>
        </div>
        <div className="panel">
          <h3>{t("Устройства и экраны", "Qurilmalar va ekranlar", "Devices and screens")}</h3>
          <HBarList rows={aud && aud.devices || []} nameFn={r => DEVICE_LABELS[r.name] || r.name} valueFn={r => r.visitors} />
          <div style={{
          height: 14
        }} />
          <HBarList rows={aud && aud.screens || []} nameFn={r => r.name === "(unknown)" ? t("ширина неизвестна", "kengligi noma'lum", "unknown width") : `${r.name} px`} valueFn={r => r.visitors} />
        </div>
      </div>

      <div className="admin-cols3">
        <div className="panel">
          <h3>{t("Язык интерфейса", "Interfeys tili", "UI language")}</h3>
          <HBarList rows={aud && aud.languages || []} nameFn={r => LANG_LABELS[r.name] || r.name} valueFn={r => r.visitors} />
          <p className="admin-muted admin-note">
            {t("Сайт держит три языка — здесь видно, читает ли кто-то узбекскую версию.", "Sayt uch tilni saqlaydi — o'zbekchani kim o'qiyotgani shu yerda.", "The site carries three languages — this shows whether anyone reads the Uzbek one.")}
          </p>
        </div>
        <div className="panel">
          <h3>{t("Браузеры", "Brauzerlar", "Browsers")}</h3>
          <HBarList rows={aud && aud.browsers || []} nameFn={r => r.name} valueFn={r => r.visitors} />
        </div>
        <div className="panel">
          <h3>{t("Страны", "Mamlakatlar", "Countries")}</h3>
          <HBarList rows={aud && aud.countries || []} nameFn={r => r.name === "(unknown)" ? t("не определена", "aniqlanmagan", "not detected") : r.name} valueFn={r => r.visitors} />
          <p className="admin-muted admin-note">
            {t("Страна видна, только когда её сообщает прокси; IP не хранится и не геокодируется.", "Mamlakat faqat proksi aytganda ko'rinadi; IP saqlanmaydi.", "The country shows only when the proxy reports it; the IP is neither stored nor geocoded.")}
          </p>
        </div>
      </div>
    </div>;
}
