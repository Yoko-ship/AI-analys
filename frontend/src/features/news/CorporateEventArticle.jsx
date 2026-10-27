import { safeHref } from '../../lib/safeHref.js';
import { formatDay } from './calendarEvents.js';
import { CorporateArticlePhoto, CorporateIssuer } from './CorporateStoryMedia.jsx';

const pick = (value, lang) => typeof value === 'string' ? value : value?.[lang] || value?.ru || '';
const COPY = {
  ru: { documents: 'Документы раскрытия', photo: 'Изображение из первоисточника · OpenInfo', context: 'О раскрытии', priority: 'Приоритет' },
  en: { documents: 'Disclosure documents', photo: 'Source image · OpenInfo', context: 'About this disclosure', priority: 'Priority' },
  uz: { documents: 'Oshkor qilish hujjatlari', photo: 'Birlamchi manba tasviri · OpenInfo', context: 'Oshkor qilish haqida', priority: 'Ustuvorlik' },
};

export function CorporateEventArticle({ story, categories, tx, lang, locale, securitiesMap, onOpenCompany, children }) {
  const copy = COPY[lang];
  const documents = story.documents?.length ? story.documents : [story];
  return <div className="ce-article-layout">
    <article className="ce-article">
      <header className="ce-article-header">
        <div className="ce-story-meta">
          <span className="ce-category">{pick(categories?.[story.category], lang) || tx.title}</span>
          <span className="ce-stage">{tx.stages[story.stage] || tx.review}</span>
        </div>
        <h1 className="led-art-title">{pick(story.title, lang)}</h1>
        <CorporateIssuer story={story} securitiesMap={securitiesMap} onOpenCompany={onOpenCompany} />
        <div className="led-art-byline"><b>OpenInfo</b><span>{tx.published}: <time dateTime={story.published_at}>{formatDay(story.published_at?.slice(0,10), locale)}</time></span></div>
      </header>
      <CorporateArticlePhoto story={story} caption={copy.photo} />
      {story.summary && <p className="led-art-lead ce-article-lead">{pick(story.summary, lang)}</p>}
      {children}
    </article>
    <aside className="ce-article-rail">
      <section className="led-panel">
        <h2 className="led-panel-h">{copy.context}</h2>
        <dl className="ce-context">
          <div><dt>{copy.priority}</dt><dd><span className={`ce-priority ce-p${story.priority}`} title={story.priority_provisional ? tx.provisional : undefined}>P{story.priority} · {tx.priorities[story.priority]}{story.priority_provisional ? ' *' : ''}</span></dd></div>
          <div><dt>OpenInfo</dt><dd>{story.code ? `№ ${story.code} · ` : ''}{story.confidence === 'confirmed' ? tx.confirmed : tx.review}</dd></div>
        </dl>
        {story.priority_explanation && <p className="ce-note">{pick(story.priority_explanation, lang)}</p>}
        <a className="ce-source-link" href={safeHref(story.source_url)} target="_blank" rel="noreferrer">{tx.source} ↗</a>
      </section>
      <nav className="led-panel" aria-label={copy.documents}>
        <h2 className="led-panel-h">{copy.documents} <span>{documents.length}</span></h2>
        {documents.map((d, i) => <a className="ce-document-link" key={d.id} href={`#ce-document-${i}`}>
          <span>{pick(d.title, lang)}</span>
          <small>{tx.stages[d.stage] || tx.review} · {formatDay(d.published_at?.slice(0,10), locale)}</small>
        </a>)}
      </nav>
      <p className="ce-note">{tx.note}</p>
    </aside>
  </div>;
}
