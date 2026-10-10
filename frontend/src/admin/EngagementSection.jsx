import { DASH, fmtInt, fmtShare, fmtDuration } from "./adminModel.js";
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

      <div className="panel">
        <h3>{t("Сколько читают и где бросают", "Qancha o'qishadi va qayerda tashlab ketishadi", "How long they read, and where they give up")}</h3>
        {eng && (eng.reading || []).length ? <div className="admin-scroll narrow">
            <table>
              <thead>
                <tr>
                  <th>{t("Раздел", "Bo'lim", "Section")}</th>
                  <th>{t("Просмотров с замером", "O'lchangan ko'rishlar", "Measured views")}</th>
                  <th>{t("Время на странице", "Sahifadagi vaqt", "Time on page")}</th>
                  <th>{t("Прокрутка", "Aylantirish", "Scrolled")}</th>
                  <th>{t("Ушли за 10 с", "10 s ichida ketdi", "Left within 10 s")}</th>
                </tr>
              </thead>
              <tbody>
                {eng.reading.map(r => <tr key={r.view}>
                    <td>{VIEW_LABELS[r.view] || r.view}</td>
                    <td>{fmtInt(r.measured)}</td>
                    <td>{fmtDuration(r.avg_seconds, t)}</td>
                    <td>{r.avg_scroll == null ? DASH : `${fmtInt(r.avg_scroll)}%`}</td>
                    <td>{fmtShare(r.quick_share)}</td>
                  </tr>)}
              </tbody>
            </table>
          </div> : <div className="admin-empty">{t("Замеры появятся с новыми визитами: время и прокрутку сообщает каждая страница, когда её закрывают.", "O'lchovlar yangi tashriflar bilan paydo bo'ladi.", "Measurements appear with new visits: each page reports its time and scroll when it is left.")}</div>}
        <p className="admin-muted admin-note">
          {t("Время — только пока вкладка на экране. Прокрутка — насколько глубоко дочитали страницу, в среднем.", "Vaqt — faqat oyna ko'rinib turganda.", "Time counts only while the tab is visible. Scroll is how far down the page was read, on average.")}
        </p>
      </div>

      <div className="panel">
        <h3>{t("Страницы выхода", "Chiqish sahifalari", "Exit pages")}</h3>
        <HBarList rows={eng && eng.exits || []} nameFn={r => r.path} valueFn={r => r.exits} detailFn={r => t(`${VIEW_LABELS[r.view] || ""} · визит закончился здесь в ${fmtShare(r.exit_rate)} просмотров`, `${VIEW_LABELS[r.view] || ""} · chiqish ${fmtShare(r.exit_rate)}`, `${VIEW_LABELS[r.view] || ""} · ${fmtShare(r.exit_rate)} of views ended the visit`)} />
        {eng && !(eng.exits || []).length ? <NoTraffic t={t} /> : null}
        <p className="admin-muted admin-note">
          {t("Последняя страница каждого визита. Страница, на которой заканчивается большая доля просмотров, — место, где читатель сдаётся.", "Har bir tashrifning oxirgi sahifasi.", "The last page of each visit. A page where a large share of views ends the visit is where readers give up.")}
        </p>
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
