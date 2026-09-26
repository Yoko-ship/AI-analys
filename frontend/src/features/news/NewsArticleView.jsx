import { roundedDisplayValue } from "../../lib/format.js";
import { useNewsArticle } from "./useNewsArticle.js";
import { EDNEWS_TX, edHeadline, interceptNav, newsRelTime } from "./editorial.jsx";
import { VIEW_PATHS } from "../../app/routing.jsx";
import { _TONE_CLS, edSummary, edDetail, newsAbsTime, newsHost, newsAddsDetail } from "./newsText.jsx";
import { EdNewsCard } from "./NewsCards.jsx";
import { NewsPriceReaction } from "./NewsPriceReaction.jsx";
import { NewsIssuerContext } from "./NewsIssuerContext.jsx";
export const NEWS_ARTICLE_TX = {
  ru: {
    back: "Все новости",
    loading: "Загружаем новость…",
    notFound: "Новость не найдена или уже недоступна.",
    error: "Не удалось загрузить новость.",
    summaryNote: "Краткое изложение подготовлено платформой на основе публикации источника. Полный текст — на сайте источника.",
    detailNote: "Изложение подготовлено платформой своими словами по публикации источника: это не текст источника. Оригинал и фотографии — на сайте источника.",
    noSummary: "Краткого изложения нет — откройте публикацию у источника.",
    readSource: "Читать в источнике",
    signal: "Оценка влияния",
    tone: "Тональность",
    impact: "Возможное влияние",
    direction: "Направление",
    relevance: "Релевантность рынку",
    dir: {
      up: "рост",
      down: "снижение",
      mixed: "смешанное",
      unclear: "неясно"
    },
    impactNone: "не значимо",
    tickers: "Упомянутые эмитенты",
    tickersHint: "Откройте карточку эмитента — котировки, отчётность и его новости.",
    sectors: "Секторы",
    related: "По теме",
    source: "Источник",
    sourceLead: "Как сообщает источник",
    about: "О публикации",
    origTitle: "Заголовок источника",
    translate: "Перевести заголовок средствами браузера",
    translateHint: "Перевод выполняется офлайн, самим браузером. При первом запуске он загрузит языковой пакет; текст никуда не отправляется.",
    machineTitle: "Заголовок источника, переведён браузером",
    published: "Опубликовано",
    added: "В ленте с",
    langLabel: "Язык",
    langs: {
      ru: "русский",
      uz: "узбекский",
      en: "английский"
    },
    filingDetail: "Из раскрытия эмитента",
    disclosureNote: "Это раскрытие самого эмитента на портале openinfo.uz. Портал не публикует отдельную страницу для каждого существенного факта — ссылка открывает карточку эмитента со списком его раскрытий.",
    openDisclosure: "Карточка эмитента на openinfo.uz",
    issuers: "Эмитенты в этой новости",
    price: "Цена",
    change: "Изм.",
    tone90: "Тон · 90 дн",
    basedOn: "публикаций за 90 дней",
    moreNews: "Другие новости эмитента",
    openCompany: "Открыть карточку эмитента",
    rxTitle: "Котировки вокруг публикации",
    rxVolume: "Объём к среднему",
    rxSince: "С публикации",
    rxNoSession: "После публикации торгов по бумаге ещё не было.",
    rxSameDay: "Сессия того же дня — публикация могла выйти и после её закрытия.",
    rxIlliquid: "Бумага торгуется редко: движение может отражать одну сделку.",
    rxNote: "Это два закрытия биржи и даты, к которым они относятся, — совпадение по времени, а не доказанная реакция рынка на эту новость."
  },
  en: {
    back: "All news",
    loading: "Loading the story…",
    notFound: "This story was not found, or is no longer available.",
    error: "Could not load the story.",
    summaryNote: "This summary was prepared by the platform from the source's publication. The full text is on the source's site.",
    detailNote: "This account was written by the platform in its own words from the source's publication — it is not the source's text. The original and its photographs are on the source's site.",
    noSummary: "No summary available — open the publication at the source.",
    readSource: "Read at the source",
    signal: "Impact assessment",
    tone: "Tone",
    impact: "Possible impact",
    direction: "Direction",
    relevance: "Market relevance",
    dir: {
      up: "up",
      down: "down",
      mixed: "mixed",
      unclear: "unclear"
    },
    impactNone: "not material",
    tickers: "Issuers mentioned",
    tickersHint: "Open an issuer to see its quotes, filings and news.",
    sectors: "Sectors",
    related: "Related",
    source: "Source",
    sourceLead: "As the source reports",
    about: "About this item",
    origTitle: "The source's headline",
    translate: "Translate the headline in your browser",
    translateHint: "The translation runs offline, in the browser itself. The first run downloads a language pack; the text is never sent anywhere.",
    machineTitle: "The source's headline, translated by your browser",
    published: "Published",
    added: "In the feed since",
    langLabel: "Language",
    langs: {
      ru: "Russian",
      uz: "Uzbek",
      en: "English"
    },
    filingDetail: "From the filing",
    disclosureNote: "This is the issuer's own filing on the openinfo.uz portal. The portal publishes no standalone page per material fact — the link opens the issuer's card, which lists its disclosures.",
    openDisclosure: "Issuer page on openinfo.uz",
    issuers: "Issuers in this story",
    price: "Price",
    change: "Chg.",
    tone90: "Tone · 90d",
    basedOn: "items over 90 days",
    moreNews: "More from this issuer",
    openCompany: "Open the issuer page",
    rxTitle: "Quotes around the publication",
    rxVolume: "Volume vs average",
    rxSince: "Since publication",
    rxNoSession: "The security has not traded since this was published.",
    rxSameDay: "Same-day session — the story may also have come out after it closed.",
    rxIlliquid: "This security trades rarely: the move may rest on a single trade.",
    rxNote: "These are two exchange closes and the dates they belong to — a coincidence in time, not a demonstrated market reaction to this story."
  },
  uz: {
    back: "Barcha yangiliklar",
    loading: "Yangilik yuklanmoqda…",
    notFound: "Yangilik topilmadi yoki endi mavjud emas.",
    error: "Yangilikni yuklab bo'lmadi.",
    summaryNote: "Qisqacha bayon platforma tomonidan manba nashri asosida tayyorlangan. To'liq matn manba saytida.",
    detailNote: "Bayon platforma tomonidan manba nashri asosida o'z so'zlari bilan yozilgan — bu manbaning matni emas. Asl nashr va suratlar manba saytida.",
    noSummary: "Qisqacha bayon yo'q — nashrni manbada oching.",
    readSource: "Manbada o'qish",
    signal: "Ta'sir bahosi",
    tone: "Ohang",
    impact: "Mumkin bo'lgan ta'sir",
    direction: "Yo'nalish",
    relevance: "Bozorga aloqadorlik",
    dir: {
      up: "o'sish",
      down: "pasayish",
      mixed: "aralash",
      unclear: "noaniq"
    },
    impactNone: "ahamiyatsiz",
    tickers: "Tilga olingan emitentlar",
    tickersHint: "Emitent kartasini oching — kotirovkalar, hisobotlar va yangiliklar.",
    sectors: "Sektorlar",
    related: "Mavzu bo'yicha",
    source: "Manba",
    sourceLead: "Manba xabar qilishicha",
    about: "Nashr haqida",
    origTitle: "Manba sarlavhasi",
    translate: "Sarlavhani brauzer vositasida tarjima qilish",
    translateHint: "Tarjima brauzerning o'zida, oflayn bajariladi. Birinchi ishga tushirishda til paketi yuklanadi; matn hech qayerga yuborilmaydi.",
    machineTitle: "Manba sarlavhasi, brauzer tarjimasi",
    published: "E'lon qilingan",
    added: "Lentada",
    langLabel: "Til",
    langs: {
      ru: "rus",
      uz: "o'zbek",
      en: "ingliz"
    },
    filingDetail: "Emitent oshkor qilishidan",
    disclosureNote: "Bu emitentning openinfo.uz portalidagi o'z oshkor qilishi. Portal har bir muhim fakt uchun alohida sahifa chop etmaydi — havola emitent kartasini ochadi.",
    openDisclosure: "openinfo.uz dagi emitent kartasi",
    issuers: "Ushbu yangilikdagi emitentlar",
    price: "Narx",
    change: "O'zg.",
    tone90: "Ohang · 90 kun",
    basedOn: "90 kunlik nashrlar",
    moreNews: "Emitentning boshqa yangiliklari",
    openCompany: "Emitent kartasini ochish",
    rxTitle: "E'lon atrofidagi kotirovkalar",
    rxVolume: "Hajm — o'rtachaga nisbatan",
    rxSince: "E'londan beri",
    rxNoSession: "E'londan keyin bu qog'oz bo'yicha savdo bo'lmagan.",
    rxSameDay: "O'sha kungi sessiya — e'lon u yopilgandan keyin ham chiqqan bo'lishi mumkin.",
    rxIlliquid: "Qog'oz kam savdo qilinadi: harakat bitta bitimga tayanishi mumkin.",
    rxNote: "Bu — birjaning ikki yopilishi va ular tegishli sanalar: vaqt bo'yicha mos kelish, bu yangilikka bozor reaksiyasi isboti emas."
  }
};
export function NewsArticleView({
  newsId,
  language,
  securitiesMap,
  onOpenCompany,
  onOpenNews,
  onBack
}) {
  const tx = NEWS_ARTICLE_TX[language] || NEWS_ARTICLE_TX.ru;
  const etx = EDNEWS_TX[language] || EDNEWS_TX.ru;
  const {
    state,
    imgOk,
    setImgOk,
    imgSmall,
    setImgSmall,
    browser
  } = useNewsArticle({
    language,
    newsId
  });

  // A picture narrower than the column it sits in is served at its own size instead of being
  // blown up to fit. The collector now swaps a feed's thumbnail for the full-size original
  // where the CMS keeps one (uza.uz shipped 320px), but some sources simply have no larger
  // file, and a stretched 320px photo is the first thing a reader notices.

  // Above the loading/error returns below, because hooks cannot sit behind one. The hook
  // handles a null item by doing nothing, which is what the loading state needs anyway.

  const back = <a className="led-back" href={VIEW_PATHS.news} onClick={interceptNav(onBack)}>← {tx.back}</a>;
  if (state.loading) {
    return <div className="news-view led">
        {back}
        <div className="led-cols">
          <div className="led-main"><div className="led-skel-row" /><div className="led-skel-lead" /><div className="led-skel-row" /></div>
          <aside className="led-rail"><div className="led-skel-panel" /></aside>
        </div>
      </div>;
  }
  if (state.error || !state.data) {
    return <div className="news-view led">
        {back}
        <div className="led-empty">{state.error === "notFound" ? tx.notFound : tx.error}</div>
      </div>;
  }
  const {
    item,
    related = [],
    disclaimer
  } = state.data;
  const head = edHeadline(item, language, browser.machine);
  const summary = edSummary(item, language);
  // Same rule as the card: when the headline above is already our summary, the lead slot
  // carries the source's own headline instead of repeating it. Once the browser has
  // translated the real headline the summary is no longer a duplicate, so it comes back.
  const lead = head.original && !head.machine ? "" : summary || tx.noSummary;
  // An openinfo item is a filing, not an article: the portal has no page for a single
  // material fact (verified — /facts/{id}, /fact/{id} and /organizations/{org}/facts/{id}
  // all 404), so its link can only reach the issuer's card. Promising "the full text at the
  // source" there would be a lie, so the call to action says what the link actually does.
  const isDisclosure = item.source_id === "openinfo_facts";
  // Only when the snippet is not already doing duty as the lead paragraph above.
  // For a filing the stored text is not a quote from an outlet — it is the disclosure's own
  // figures (dividend per share, percent actually paid, the payment window), which the summary
  // only paraphrases. Those numbers are the whole point, so they are shown unconditionally
  // rather than being suppressed as a near-duplicate.
  // Our own retelling of the source's article, in paragraphs. When it exists it IS the body
  // of the page, and the source's one-sentence teaser below would only repeat its opening.
  const detail = edDetail(item, language);
  const sourceLead = summary && item.snippet && (isDisclosure || !detail.length && newsAddsDetail(item.snippet, summary)) ? item.snippet : "";
  const toneCls = _TONE_CLS[item.tone] || "neu";
  const host = newsHost(item.url);
  const tickers = Array.isArray(item.tickers) ? item.tickers : [];
  const sectors = Array.isArray(item.sectors) ? item.sectors : [];
  const relevancePct = typeof item.relevance_score === "number" ? `${roundedDisplayValue(Math.max(0, Math.min(item.relevance_score, 1)) * 100)}%` : null;
  const toneScore = typeof item.tone_score === "number" ? `${item.tone_score >= 0 ? "+" : ""}${item.tone_score.toFixed(2)}` : "";
  return <div className="news-view led">
      {back}
      <div className="led-cols">
        <main className="led-main">
          <article className="led-art">
            <div className="led-eyebrow">
              <span className="led-cat">{etx.cat[item.type] || item.type}</span>
              {item.tone && <><span className="led-sep">·</span><span className={`led-tone ${toneCls}`}>{etx.tone[item.tone] || item.tone}</span></>}
              {item.impact && item.impact !== "none" && <><span className="led-sep">·</span><span className="led-imp">{etx.impact[item.impact] || item.impact}</span></>}
            </div>
            <h1 className="led-art-title">{head.text}</h1>
            <div className="led-art-byline">
              {item.source && <b>{item.source}</b>}
              {item.published_at && <span>{newsAbsTime(item.published_at, language)}</span>}
              {item.published_at && <span className="led-art-rel">{newsRelTime(item.published_at, language)}</span>}
            </div>

            {item.image_url && imgOk && <div className={`led-figure led-art-figure${imgSmall ? " is-small" : ""}`}>
                <img src={item.image_url} alt="" loading="lazy" onError={() => setImgOk(false)} onLoad={e => setImgSmall((e.target.naturalWidth || 0) < 760)} />
              </div>}

            {lead && <p className="led-art-lead">{lead}</p>}

            {detail.length > 0 && <div className="led-art-body">
                {detail.map((para, i) => <p key={i}>{para}</p>)}
              </div>}

            {head.original && <section className="led-art-quote">
                <h3 className="led-panel-h">{head.machine ? tx.machineTitle : tx.origTitle}</h3>
                <p className="led-orig"><span className="led-lang">{head.lang}</span>{head.original}</p>
                {/* Offered only when the browser HAS the translator but not yet this
                    language pack. Downloading one is a real cost and Chrome requires a
                    gesture for it, so it is the reader's call, remembered afterwards. */}
                {browser.offer && <div className="led-mt-offer">
                    <button type="button" className="led-mt-btn" onClick={browser.request}>
                      {tx.translate}
                    </button>
                    <span className="led-mt-hint">{tx.translateHint}</span>
                  </div>}
              </section>}

            {sourceLead && <section className="led-art-quote">
                <h3 className="led-panel-h">{isDisclosure ? tx.filingDetail : tx.sourceLead}</h3>
                <p>{sourceLead}</p>
              </section>}

            <div className="led-art-source">
              <p className="led-art-note">
                {isDisclosure ? tx.disclosureNote : detail.length > 0 ? tx.detailNote : tx.summaryNote}
              </p>
              {item.url && <a className="led-art-cta" href={item.url} target="_blank" rel="noopener noreferrer nofollow">
                  {isDisclosure ? tx.openDisclosure : tx.readSource}
                  {host && <span className="led-art-host">{host}</span>}
                </a>}
            </div>

            {tickers.length > 0 && <NewsIssuerContext
              tickers={tickers}
              currentId={item.id}
              language={language}
              securitiesMap={securitiesMap}
              onOpenCompany={onOpenCompany}
              onOpenNews={onOpenNews}
              tx={tx}
            />}

            {tickers.length > 0 && item.id && <NewsPriceReaction newsId={item.id} language={language} securitiesMap={securitiesMap} onOpenCompany={onOpenCompany} tx={tx} />}

            {sectors.length > 0 && <section className="led-art-block">
                <h3 className="led-panel-h">{tx.sectors}</h3>
                <div className="led-chips">
                  {sectors.map((s, i) => <span key={`${s}-${i}`} className="led-chip">{s}</span>)}
                </div>
              </section>}
          </article>

          {related.length > 0 && <section className="led-art-related">
              <div className="led-rule" />
              <h3 className="led-panel-h">{tx.related}</h3>
              <div className="led-stack">
                {related.map((it, i) => <EdNewsCard key={it.id || i} item={it} language={language} variant="story" onOpen={onOpenNews} />)}
              </div>
            </section>}
        </main>

        <aside className="led-rail">
          <div className="led-panel">
            <h4 className="led-panel-h">{tx.signal}</h4>
            <dl className="led-sig">
              <div><dt>{tx.tone}</dt><dd className={toneCls}>{etx.tone[item.tone] || item.tone} {toneScore}</dd></div>
              <div><dt>{tx.impact}</dt><dd>{item.impact === "none" ? tx.impactNone : etx.impact[item.impact] || item.impact}</dd></div>
              <div><dt>{tx.direction}</dt><dd>{tx.dir[item.direction] || item.direction || tx.dir.unclear}</dd></div>
              {relevancePct && <div><dt>{tx.relevance}</dt><dd>{relevancePct}</dd></div>}
              {item.source && <div><dt>{tx.source}</dt><dd>{item.source}</dd></div>}
            </dl>
            {disclaimer && <p className="led-sig-note">{disclaimer}</p>}
          </div>
          <div className="led-panel">
            <h4 className="led-panel-h">{tx.about}</h4>
            <dl className="led-sig led-sig--rows">
              {item.published_at && <div><dt>{tx.published}</dt><dd>{newsAbsTime(item.published_at, language)}</dd></div>}
              {item.collected_at && <div><dt>{tx.added}</dt><dd>{newsAbsTime(item.collected_at, language)}</dd></div>}
              {item.lang && <div><dt>{tx.langLabel}</dt><dd>{tx.langs && tx.langs[item.lang] || item.lang}</dd></div>}
            </dl>
          </div>
        </aside>
      </div>
    </div>;
}
