import { fmtInt } from "./adminModel.js";
import { Stat, RunHistory } from "./AdminWidgets.jsx";
import { FindingsTable } from "./FindingsTable.jsx";
export function DataHealthSection({
  t,
  catalog,
  openCounts,
  news,
  streams,
  staleStreams,
  history,
  latest,
  queue,
  onSectionChange,
  rules,
  selected,
  toggleSelected,
  acceptFindings,
  busy
}) {
  return <div className="admin-section">
      <div className="admin-stats">
        <Stat label={t("Бумаг в каталоге", "Kataloqdagi qog'ozlar", "Securities")} value={fmtInt(catalog && catalog.securities)} line1={catalog && catalog.preferred ? t(`${fmtInt(catalog.preferred)} привилегированных`, `${fmtInt(catalog.preferred)} imtiyozli`, `${fmtInt(catalog.preferred)} preferred`) : null} line2={catalog ? t(`${fmtInt(catalog.stocks)} акций и ${fmtInt(catalog.bonds)} облигаций`, `${fmtInt(catalog.stocks)} aksiya, ${fmtInt(catalog.bonds)} obligatsiya`, `${fmtInt(catalog.stocks)} shares and ${fmtInt(catalog.bonds)} bonds`) : null} />
        <Stat
          label={t("Блокирующих находок", "Bloklovchi topilmalar", "Blocking findings")}
          value={fmtInt(openCounts.blocking)}
          warn={Boolean(openCounts.blocking)}
          line1={t(`Предупреждений — ${fmtInt(openCounts.warning)}`, `Ogohlantirish — ${fmtInt(openCounts.warning)}`, `Warnings — ${fmtInt(openCounts.warning)}`)}
          line2={t("Открытые, ещё не разобранные", "Ochiq, ko'rib chiqilmagan", "Open, not yet triaged")}
        />
        <Stat label={news ? t(`Новостей за ${news.days} дней`, `${news.days} kunlik yangiliklar`, `News, ${news.days} days`) : t("Новостей за неделю", "Haftalik yangiliklar", "News this week")} value={fmtInt(news && news.collected)} line1={news ? t(`${fmtInt(news.published)} опубликовано`, `${fmtInt(news.published)} chop etilgan`, `${fmtInt(news.published)} published`) : null} line2={news ? t(`${fmtInt(news.rejected)} отклонено триажем · ${fmtInt(news.without_image)} без картинки`, `${fmtInt(news.rejected)} rad etilgan · ${fmtInt(news.without_image)} rasmsiz`, `${fmtInt(news.rejected)} rejected · ${fmtInt(news.without_image)} without an image`) : null} />
        <Stat
          label={t("Потоки данных", "Ma'lumot oqimlari", "Data streams")}
          value={`${streams.length - staleStreams}/${streams.length}`}
          badge={staleStreams ? t(`${staleStreams} устарел(и)`, `${staleStreams} eskirgan`, `${staleStreams} stale`) : null}
          badgeIcon={staleStreams ? "down" : null}
          line1={staleStreams ? t("Есть потоки без свежих записей", "Yangi yozuvsiz oqimlar bor", "Some streams have no fresh write") : t("Все потоки писали недавно", "Barcha oqimlar yaqinda yozgan", "Every stream wrote recently")}
          line2={t("По последней записи в таблице", "Jadvaldagi oxirgi yozuv bo'yicha", "Measured by the last write in the table")}
        />
      </div>

      <div className="panel">
        <div className="admin-chart-head">
          <div>
            <h2>{t("Блокирующие находки по прогонам", "Prognozlar bo'yicha bloklovchi topilmalar", "Blocking findings by run")}</h2>
            <p>{t(`Последние ${history.length} прогонов аудитора`, `Oxirgi ${history.length} audit`, `Last ${history.length} audit runs`)}</p>
          </div>
        </div>
        {history.length ? <RunHistory runs={history} t={t} /> : <div className="admin-empty">{t("Прогонов пока нет", "Hali prognoz yo'q", "No runs yet")}</div>}
        {latest ? <div className="admin-chart-foot">
            <div><span>{t("Правил в прогоне", "Qoidalar", "Rules run")}</span> <b>{fmtInt(latest.rules_run)}</b></div>
            <div><span>{t("Инструментов", "Vositalar", "Instruments")}</span> <b>{fmtInt(latest.instruments)}</b></div>
            <div><span>{t("Длительность", "Davomiylik", "Duration")}</span> <b>{fmtInt(latest.duration_ms)} мс</b></div>
            <div><span>{t("Статус", "Holat", "Status")}</span> <b>{latest.status}</b></div>
          </div> : null}
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
          <button type="button" className="admin-btn sm" onClick={() => onSectionChange && onSectionChange("findings")}>
            {t("Все находки", "Barcha topilmalar", "All findings")}
          </button>
        </div>
        <FindingsTable items={queue} rules={rules} t={t} selected={selected} onToggle={toggleSelected} onAccept={acceptFindings} busy={busy} />
      </div>
    </div>;
}
