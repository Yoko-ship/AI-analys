import { useState } from "react";
import { DASH, fmtInt, fmtNum, fmtShare, fmtDuration, fmtDay } from "./adminModel.js";
import { Stat, DailyBars, HBarList, Funnel, RangePicker, NoTraffic } from "./AdminWidgets.jsx";
import { isBrowserExcluded, setBrowserExcluded } from "../lib/track.js";

function countryName(code, language) {
  if (!code || code === "(unknown)") return null;
  try {
    return new Intl.DisplayNames([language || "ru"], { type: "region" }).of(code) || code;
  } catch {
    return code;
  }
}

/** sessions · bounce · time — how a group of visits went, in one line. */
function visitLine(row, t) {
  const bounce = row.bounce_rate == null ? DASH : fmtShare(row.bounce_rate);
  return t(`отказы ${bounce} · ${fmtDuration(row.avg_seconds, t)}`, `rad ${bounce} · ${fmtDuration(row.avg_seconds, t)}`, `bounce ${bounce} · ${fmtDuration(row.avg_seconds, t)}`);
}

export function AudienceSection({
  audienceData,
  rangeDays,
  setRangeDays,
  t,
  language,
  DEVICE_LABELS,
  LANG_LABELS,
  VIEW_LABELS
}) {
  const aud = audienceData && audienceData.ok ? audienceData : null;
  const audTotals = aud && aud.totals || {};
  const quality = aud && aud.quality || null;
  const [excluded, setExcluded] = useState(isBrowserExcluded);
  const [siteFilter, setSiteFilter] = useState("all");
  const CHANNEL_LABELS = {
    telegram: "Telegram",
    search: t("Поисковики", "Qidiruv tizimlari", "Search engines"),
    social: t("Соцсети", "Ijtimoiy tarmoqlar", "Social networks"),
    referral: t("Другие сайты", "Boshqa saytlar", "Other sites"),
    direct: t("Прямые заходы", "To'g'ridan-to'g'ri", "Direct"),
    ads: t("Реклама", "Reklama", "Ads"),
    email: t("Рассылки", "Xatlar", "Email"),
    campaign: t("Прочие кампании", "Boshqa kampaniyalar", "Other campaigns")
  };
  const JOURNEY_LABELS = {
    visited: t("Зашли на сайт", "Saytga kirdi", "Visited"),
    security: t("Открыли бумагу", "Qog'ozni ochdi", "Opened a security"),
    signed_in: t("Вошли в аккаунт", "Akkauntga kirdi", "Signed in"),
    analysed: t("Запустили AI-анализ", "AI-tahlil qildi", "Ran an AI analysis")
  };
  const sites = aud && aud.sites || [];
  const siteChannels = ["all", ...["referral", "search", "social", "telegram", "ads", "email", "campaign"].filter(c => sites.some(s => s.channel === c))];
  const shownSites = siteFilter === "all" ? sites : sites.filter(s => s.channel === siteFilter);
  const showSitesOf = row => {
    if (!sites.some(s => s.channel === row.channel)) return;
    setSiteFilter(row.channel);
    const panel = document.getElementById("admin-referring-sites");
    if (panel) panel.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const APP_LABELS = {
    "org.telegram.messenger": t("Приложение Telegram (Android)", "Telegram ilovasi (Android)", "Telegram app (Android)"),
    "com.google.android.googlequicksearchbox": t("Приложение Google (Android)", "Google ilovasi (Android)", "Google app (Android)"),
    "com.google.android.gm": "Gmail (Android)"
  };
  const placeLabel = r => {
    const country = countryName(r.country, language);
    return [r.city, country].filter(Boolean).join(", ") || t("не определено", "aniqlanmagan", "unknown");
  };
  const toggleExcluded = () => {
    const next = !excluded;
    setBrowserExcluded(next);
    setExcluded(next);
  };
  return <div className="admin-section">
      <div className="admin-panel-bar">
        <RangePicker value={rangeDays} onChange={setRangeDays} t={t} />
      </div>

      <div className="admin-stats">
        <Stat label={t("Уникальных посетителей", "Noyob tashrifchilar", "Unique visitors")} value={fmtInt(audTotals.visitors)} line1={t(`новых — ${fmtInt(audTotals.new_visitors)} · вернувшихся — ${fmtInt(audTotals.returning_visitors)}`, `yangi — ${fmtInt(audTotals.new_visitors)}`, `new — ${fmtInt(audTotals.new_visitors)} · returning — ${fmtInt(audTotals.returning_visitors)}`)} line2={t("без браузеров команды", "jamoa brauzerlarisiz", "the team's browsers excluded")} />
        <Stat label={t("Визитов", "Tashriflar", "Sessions")} value={fmtInt(audTotals.sessions)} line1={t(`просмотров — ${fmtInt(audTotals.pageviews)}`, `ko'rishlar — ${fmtInt(audTotals.pageviews)}`, `page views — ${fmtInt(audTotals.pageviews)}`)} line2={t("новый визит после 30 минут тишины", "30 daqiqadan keyin yangi tashrif", "a new session after 30 idle minutes")} />
        <Stat label={t("Время на сайте", "Saytdagi vaqt", "Time on site")} value={fmtDuration(audTotals.engaged_session_seconds, t)} line1={t(`страниц за визит — ${audTotals.pages_per_session != null ? fmtNum(audTotals.pages_per_session, 1) : DASH}`, `har tashrifda sahifalar — ${audTotals.pages_per_session != null ? fmtNum(audTotals.pages_per_session, 1) : DASH}`, `pages per session — ${audTotals.pages_per_session != null ? fmtNum(audTotals.pages_per_session, 1) : DASH}`)} line2={t("только пока вкладка на экране", "faqat oyna ko'rinib turganda", "counted only while the tab is visible")} />
        <Stat label={t("Отказы", "Rad etishlar", "Bounce rate")} value={fmtShare(audTotals.bounce_rate)} line1={t("визиты из одной страницы", "bir sahifalik tashriflar", "single-page sessions")} line2={t("по каналам и страницам входа — ниже", "kanallar bo'yicha — pastda", "by channel and landing page below")} />
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
          <h3>{t("Каналы", "Kanallar", "Channels")}</h3>
          <HBarList rows={aud && aud.channels || []} nameFn={r => CHANNEL_LABELS[r.channel] || r.channel} valueFn={r => r.sessions} detailFn={r => visitLine(r, t)} onClickRow={showSitesOf} canClickRow={r => sites.some(site => site.channel === r.channel)} />
          {aud && !(aud.channels || []).length ? <NoTraffic t={t} /> : null}
          <p className="admin-muted admin-note">
            {t("Визиты по источнику первой страницы. Встроенный браузер Telegram не сообщает, откуда пришёл человек, — такие переходы видны как Telegram, только если ссылка помечена utm_source=telegram.", "Tashriflar birinchi sahifa manbasi bo'yicha. Telegram havolalarini utm_source=telegram bilan belgilang.", "Sessions by the source of their first page. Telegram's in-app browser hides where a reader came from — tag links with utm_source=telegram to see them as Telegram.")}
          </p>
        </div>
        <div className="panel">
          <h3>{t("Путь посетителя", "Tashrifchi yo'li", "Visitor journey")}</h3>
          {aud && aud.journey ? <Funnel steps={aud.journey} labels={JOURNEY_LABELS} /> : <div className="admin-empty">{DASH}</div>}
          <p className="admin-muted admin-note">
            {t("Каждый шаг — те же люди (браузеры), процент — от предыдущего шага.", "Har bir qadam — o'sha odamlar, foiz — oldingi qadamdan.", "Every step counts the same people (browsers); the share is of the step before.")}
          </p>
        </div>
      </div>

      <div className="panel" id="admin-referring-sites" style={{
      scrollMarginTop: 96
    }}>
        <h3>{t("С каких сайтов приходят", "Qaysi saytlardan kelishadi", "Which sites send visitors")}</h3>
        {sites.length ? <div className="admin-seg" style={{
        marginBottom: 12
      }}>
            {siteChannels.map(c => <button key={c} type="button" aria-selected={siteFilter === c} onClick={() => setSiteFilter(c)}>
                {c === "all" ? t("Все", "Hammasi", "All") : CHANNEL_LABELS[c] || c}
              </button>)}
          </div> : null}
        {shownSites.length ? <div className="admin-scroll narrow">
            <table>
              <thead>
                <tr>
                  <th>{t("Сайт", "Sayt", "Site")}</th>
                  <th>{t("Канал", "Kanal", "Channel")}</th>
                  <th>{t("Визитов", "Tashriflar", "Sessions")}</th>
                  <th>{t("Отказы", "Rad etish", "Bounce")}</th>
                  <th>{t("Время", "Vaqt", "Time")}</th>
                </tr>
              </thead>
              <tbody>
                {shownSites.map(r => <tr key={r.host}>
                    <td>
                      <strong>{APP_LABELS[r.host] || r.host}</strong>
                      {APP_LABELS[r.host] ? null : <a className="admin-muted" href={`https://${r.host}`} target="_blank" rel="noopener noreferrer"> ↗</a>}
                      {(r.pages || []).map(page => <div key={page.path} className="admin-muted admin-path">{page.path} · {fmtInt(page.sessions)}</div>)}
                    </td>
                    <td>{CHANNEL_LABELS[r.channel] || r.channel}</td>
                    <td>{fmtInt(r.sessions)}</td>
                    <td>{fmtShare(r.bounce_rate)}</td>
                    <td>{fmtDuration(r.avg_seconds, t)}</td>
                  </tr>)}
              </tbody>
            </table>
          </div> : <div className="admin-empty">{t("За этот период переходов с других сайтов не было", "Bu davrda boshqa saytlardan o'tishlar bo'lmagan", "No visits came from other sites in this period")}</div>}
        <p className="admin-muted admin-note">
          {t("Нажмите канал выше, чтобы увидеть его сайты. Обычно браузер сообщает только сайт; конкретная страница-источник видна, когда сайт её передаёт. Прямые заходы и наш собственный сайт сюда не входят.", "Kanalni bosing — uning saytlari ko'rinadi. Brauzer odatda faqat saytni aytadi.", "Click a channel above to see its sites. Browsers usually report only the site; the exact page shows when the referring site passes it on. Direct visits and our own site are not listed.")}
        </p>
      </div>

      <div className="panel">
        <h3>{t("Кампании (UTM)", "Kampaniyalar (UTM)", "Campaigns (UTM)")}</h3>
        <HBarList rows={aud && aud.campaigns || []} nameFn={r => [r.source, r.medium, r.campaign].filter(Boolean).join(" · ")} valueFn={r => r.sessions} detailFn={r => visitLine(r, t)} />
        {aud && !(aud.campaigns || []).length ? <div className="admin-empty">{t("Помеченных ссылок ещё не было", "Belgilangan havolalar hali yo'q", "No tagged links yet")}</div> : null}
        <p className="admin-muted admin-note">
          {t("Пометьте ссылку, которую публикуете, и она появится здесь отдельной строкой: ", "Havolani belgilang: ", "Tag a link you post and it shows up here on its own: ")}
          <code>uzstock.uz/?utm_source=telegram&amp;utm_campaign=…</code>
        </p>
      </div>

      <div className="panel">
        <h3>{t("Страницы входа", "Kirish sahifalari", "Landing pages")}</h3>
        {aud && (aud.landings || []).length ? <div className="admin-scroll narrow">
            <table>
              <thead>
                <tr>
                  <th>{t("Страница", "Sahifa", "Page")}</th>
                  <th>{t("Визитов", "Tashriflar", "Sessions")}</th>
                  <th>{t("Отказы", "Rad etish", "Bounce")}</th>
                  <th>{t("Время", "Vaqt", "Time")}</th>
                </tr>
              </thead>
              <tbody>
                {aud.landings.map(r => <tr key={r.path}>
                    <td><span className="admin-path">{r.path}</span> <span className="admin-muted">{VIEW_LABELS[r.view] || ""}</span></td>
                    <td>{fmtInt(r.sessions)}</td>
                    <td>{fmtShare(r.bounce_rate)}</td>
                    <td>{fmtDuration(r.avg_seconds, t)}</td>
                  </tr>)}
              </tbody>
            </table>
          </div> : <NoTraffic t={t} />}
        <p className="admin-muted admin-note">
          {t("Где начинается визит и чем он кончается: высокая доля отказов при коротком времени — страница не дала того, за чем пришли.", "Tashrif qayerda boshlanadi va qanday tugaydi.", "Where visits start and how they go: a high bounce rate with a short time means the page did not give what people came for.")}
        </p>
      </div>

      <div className="admin-cols2">
        <div className="panel">
          <h3>{t("Страны", "Mamlakatlar", "Countries")}</h3>
          <HBarList rows={aud && aud.countries || []} nameFn={r => countryName(r.name, language) || t("не определена", "aniqlanmagan", "not detected")} valueFn={r => r.visitors} />
        </div>
        <div className="panel">
          <h3>{t("Города", "Shaharlar", "Cities")}</h3>
          <HBarList rows={aud && aud.cities || []} nameFn={r => placeLabel({ city: r.name, country: r.country })} valueFn={r => r.visitors} />
          {aud && !(aud.cities || []).length ? <div className="admin-empty">{t("Города появятся с новыми визитами", "Shaharlar yangi tashriflar bilan paydo bo'ladi", "Cities appear with new visits")}</div> : null}
          <p className="admin-muted admin-note">
            {t("Место определяется по IP в момент визита; сам адрес не хранится. Мобильные операторы часто выходят в сеть через Ташкент. ", "Joy IP bo'yicha aniqlanadi; manzil saqlanmaydi. ", "The place is resolved from the IP at visit time; the address itself is never stored. Mobile carriers often route through Tashkent. ")}
            <a href="https://db-ip.com" target="_blank" rel="noopener noreferrer">IP Geolocation by DB-IP</a>
          </p>
        </div>
      </div>

      <div className="admin-cols3">
        <div className="panel">
          <h3>{t("Устройства и экраны", "Qurilmalar va ekranlar", "Devices and screens")}</h3>
          <HBarList rows={aud && aud.devices || []} nameFn={r => DEVICE_LABELS[r.name] || r.name} valueFn={r => r.visitors} />
          <div style={{
          height: 14
        }} />
          <HBarList rows={aud && aud.screens || []} nameFn={r => r.name === "(unknown)" ? t("ширина неизвестна", "kengligi noma'lum", "unknown width") : `${r.name} px`} valueFn={r => r.visitors} />
        </div>
        <div className="panel">
          <h3>{t("Язык интерфейса", "Interfeys tili", "UI language")}</h3>
          <HBarList rows={aud && aud.languages || []} nameFn={r => LANG_LABELS[r.name] || r.name} valueFn={r => r.visitors} />
        </div>
        <div className="panel">
          <h3>{t("Браузеры", "Brauzerlar", "Browsers")}</h3>
          <HBarList rows={aud && aud.browsers || []} nameFn={r => r.name} valueFn={r => r.visitors} />
        </div>
      </div>

      <div className="panel">
        <h3>{t("Насколько это разные люди", "Bular qanchalik turli odamlar", "How many of these are different people")}</h3>
        <div className="admin-stats">
          <Stat label={t("Посетителей (браузеров)", "Tashrifchilar (brauzerlar)", "Visitors (browsers)")} value={fmtInt(quality && quality.visitors)} line1={t("один человек в двух браузерах — двое", "ikki brauzerdagi bitta odam — ikkita", "one person in two browsers counts twice")} />
          <Stat label={t("Разных сетей (IP)", "Turli tarmoqlar (IP)", "Distinct networks (IP)")} value={fmtInt(quality && quality.networks)} line1={t("нижняя граница числа людей", "odamlar sonining quyi chegarasi", "a floor for the number of people")} />
          <Stat label={t("Браузеры команды", "Jamoa brauzerlari", "Team browsers")} value={fmtInt(quality && quality.team_excluded)} line1={t("исключены из всех цифр", "barcha raqamlardan chiqarilgan", "excluded from every figure")} />
        </div>
        {quality && quality.crowded_networks && quality.crowded_networks.length ? <>
            <p className="admin-muted admin-note">{t("Сети, за которыми несколько посетителей: офис, оператор связи — или один человек в режиме инкогнито.", "Bir nechta tashrifchili tarmoqlar.", "Networks with several visitors behind them: an office, a carrier — or one person in incognito windows.")}</p>
            <HBarList rows={quality.crowded_networks} nameFn={r => `${t("сеть", "tarmoq", "network")} ${r.network} · ${placeLabel(r)}`} valueFn={r => r.visitors} detailFn={r => t(`разных устройств/браузеров: ${fmtInt(r.clients)}`, `qurilmalar: ${fmtInt(r.clients)}`, `distinct device/browser: ${fmtInt(r.clients)}`)} />
          </> : null}
        <div style={{
        marginTop: 16
      }}>
          <button type="button" className={`admin-btn sm${excluded ? " accent" : ""}`} onClick={toggleExcluded}>
            {excluded ? t("Этот браузер не считается — вернуть", "Bu brauzer hisoblanmaydi — qaytarish", "This browser is not counted — count it again") : t("Не считать этот браузер", "Bu brauzerni hisoblamaslik", "Don't count this browser")}
          </button>
          <p className="admin-muted admin-note">{t("Браузеры, где входили администраторы, исключаются сами. Кнопку нажмите на телефоне и других устройствах команды.", "Administratorlar kirgan brauzerlar avtomatik chiqariladi.", "Browsers an administrator signed in to are excluded automatically. Press this on the team's phones and other devices.")}</p>
        </div>
      </div>
    </div>;
}
