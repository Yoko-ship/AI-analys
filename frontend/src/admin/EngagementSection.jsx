import { fmtInt } from "./adminModel.js";
import { HBarList, RangePicker, NoTraffic } from "./AdminWidgets.jsx";
export function EngagementSection({
  engagementData,
  rangeDays,
  setRangeDays,
  t,
  VIEW_LABELS
}) {
  const eng = engagementData && engagementData.ok ? engagementData : null;
  return <div className="admin-section">
      <div className="admin-panel-bar">
        <RangePicker value={rangeDays} onChange={setRangeDays} t={t} />
      </div>

      <div className="admin-cols2">
        <div className="panel">
          <h3>{t("Разделы сайта", "Sayt bo'limlari", "Site sections")}</h3>
          <HBarList rows={eng && eng.views || []} nameFn={r => VIEW_LABELS[r.view] || r.view} valueFn={r => r.pageviews} detailFn={r => t(`${fmtInt(r.visitors)} чел.`, `${fmtInt(r.visitors)} kishi`, `${fmtInt(r.visitors)} visitors`)} />
          {eng && !(eng.views || []).length ? <NoTraffic t={t} /> : null}
        </div>
        <div className="panel">
          <h3>{t("Топ бумаг по просмотрам", "Ko'rishlar bo'yicha top qog'ozlar", "Top tickers by views")}</h3>
          <HBarList rows={eng && eng.tickers || []} nameFn={r => r.ticker} valueFn={r => r.pageviews} detailFn={r => t(`${fmtInt(r.visitors)} чел.`, `${fmtInt(r.visitors)} kishi`, `${fmtInt(r.visitors)} visitors`)} />
          {eng && !(eng.tickers || []).length ? <div className="admin-empty">{t("Карточки компаний ещё не открывали", "Kompaniya sahifalari hali ochilmagan", "No company pages opened yet")}</div> : null}
          <p className="admin-muted admin-note">
            {t("Считаются карточки компаний, продвинутые графики и страницы облигаций. Этот список — готовый приоритет для бэклога данных.", "Kompaniya sahifalari, grafiklar va obligatsiya sahifalari hisoblanadi.", "Company pages, advanced charts and bond pages count. This ranking is a ready-made priority for the data backlog.")}
          </p>
        </div>
      </div>

      <div className="admin-cols2">
        <div className="panel">
          <h3>{t("Читаемые новости", "O'qilgan yangiliklar", "Stories read")}</h3>
          <HBarList rows={eng && eng.news || []} nameFn={r => r.path.replace("/news/", "№")} valueFn={r => r.pageviews} />
          {eng && !(eng.news || []).length ? <div className="admin-empty">{t("Отдельные новости ещё не открывали", "Alohida yangiliklar hali ochilmagan", "No individual stories opened yet")}</div> : null}
        </div>
        <div className="panel">
          <h3>{t("Действия на сайте", "Saytdagi amallar", "On-site events")}</h3>
          <HBarList rows={eng && eng.events || []} nameFn={r => r.event} valueFn={r => r.count} />
          {eng && !(eng.events || []).length ? <div className="admin-empty">
              {t("Пока считаются только просмотры страниц; события (поиск, фильтры, вкладки) добавляются по одному в lib/track.js.", "Hozircha faqat sahifa ko'rishlari hisoblanadi.", "Only page views are counted so far; custom events (search, filters, tabs) are added one by one in lib/track.js.")}
            </div> : null}
        </div>
      </div>
    </div>;
}
