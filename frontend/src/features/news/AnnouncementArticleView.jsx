import { useAnnouncementArticle } from "./useAnnouncementArticle.js";
import { interceptNav } from "./editorial.jsx";
import { normalizeLanguage } from "../../shared/i18n.jsx";
export const ANNOUNCEMENT_ARTICLE_TX = {
  ru: {
    back: "К календарю",
    eyebrow: "Объявление OpenInfo",
    details: "Текст объявления",
    organization: "Информация об организации",
    facts: "Сведения",
    original: "Открыть оригинал",
    pdf: "Скачать PDF",
    source: "Источник: openinfo.uz",
    loading: "Загружаем объявление…",
    notFound: "Объявление не найдено.",
    error: "Не удалось загрузить объявление. Попробуйте позже."
  },
  en: {
    back: "Back to calendar",
    eyebrow: "OpenInfo announcement",
    details: "Announcement",
    organization: "Organization information",
    facts: "Details",
    original: "Open original",
    pdf: "Download PDF",
    source: "Source: openinfo.uz",
    loading: "Loading announcement…",
    notFound: "Announcement not found.",
    error: "Could not load the announcement. Please try again later."
  },
  uz: {
    back: "Taqvimga qaytish",
    eyebrow: "OpenInfo e'loni",
    details: "E'lon matni",
    organization: "Tashkilot haqida ma'lumot",
    facts: "Ma'lumotlar",
    original: "Aslini ochish",
    pdf: "PDF-ni yuklab olish",
    source: "Manba: openinfo.uz",
    loading: "E'lon yuklanmoqda…",
    notFound: "E'lon topilmadi.",
    error: "E'lonni yuklab bo'lmadi. Keyinroq qayta urinib ko'ring."
  }
};
export function AnnouncementArticleView({
  announcementId,
  language,
  onBack
}) {
  const lang = normalizeLanguage(language);
  const tx = ANNOUNCEMENT_ARTICLE_TX[lang] || ANNOUNCEMENT_ARTICLE_TX.ru;
  const {
    state
  } = useAnnouncementArticle({
    announcementId,
    lang
  });
  const back = <a className="led-back" href="/news?tab=calendar" onClick={interceptNav(onBack)}>← {tx.back}</a>;
  if (state.loading) {
    return <div className="news-view led announcement-article">
        {back}
        <div className="led-skel-row" aria-label={tx.loading} />
        <div className="led-skel-lead" />
      </div>;
  }
  if (state.error || !state.item) {
    return <div className="news-view led announcement-article">
        {back}
        <div className="led-empty">{state.error === "notFound" ? tx.notFound : tx.error}</div>
      </div>;
  }
  const item = state.item;
  const metadata = Array.isArray(item.metadata) ? item.metadata : [];
  const content = Array.isArray(item.content) ? item.content : [];
  const organizationDetails = Array.isArray(item.organization_details) ? item.organization_details : [];
  return <div className="news-view led announcement-article">
      {back}
      <div className="announcement-layout">
        <main className="announcement-main">
          <article className="led-art">
            <div className="led-eyebrow"><span className="led-cat">{tx.eyebrow}</span></div>
            <h1 className="led-art-title">{item.title}</h1>
            {item.organization && <p className="announcement-company">{item.organization}</p>}

            {metadata.length > 0 && <dl className="announcement-meta" aria-label={tx.facts}>
                {metadata.map((field, i) => <div key={`${field.label}-${i}`}>
                    <dt>{field.label}</dt>
                    <dd>{field.value}</dd>
                  </div>)}
              </dl>}

            {content.length > 0 && <section className="announcement-body">
                <h2 className="led-panel-h">{tx.details}</h2>
                {content.map((block, i) => block.kind === "heading" ? <h3 key={i}>{block.text}</h3> : <p key={i} className={block.kind === "list_item" ? "is-list-item" : undefined}>{block.text}</p>)}
              </section>}

            <div className="led-art-source announcement-actions">
              <p className="led-art-note">{tx.source}</p>
              <div>
                {item.pdf_url && <a className="announcement-secondary" href={item.pdf_url} target="_blank" rel="noopener noreferrer nofollow">
                    {tx.pdf}
                  </a>}
                {item.source_url && <a className="led-art-cta" href={item.source_url} target="_blank" rel="noopener noreferrer nofollow">
                    {tx.original}<span className="led-art-host">openinfo.uz</span>
                  </a>}
              </div>
            </div>
          </article>
        </main>

        {organizationDetails.length > 0 && <aside className="announcement-rail">
            <div className="led-panel">
              <h2 className="led-panel-h">{tx.organization}</h2>
              <dl className="led-sig led-sig--rows">
                {organizationDetails.map((field, i) => <div key={`${field.label}-${i}`}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}
              </dl>
            </div>
          </aside>}
      </div>
    </div>;
}
