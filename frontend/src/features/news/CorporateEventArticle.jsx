import { formatDay } from './calendarEvents.js';
import { CorporateArticlePhoto, CorporateIssuer } from './CorporateStoryMedia.jsx';

const pick = (value, lang) => typeof value === 'string' ? value : value?.[lang] || value?.ru || '';
const COPY = {
  ru: { photo: 'Изображение из первоисточника · OpenInfo' },
  en: { photo: 'Source image · OpenInfo' },
  uz: { photo: 'Birlamchi manba tasviri · OpenInfo' },
};

export function CorporateEventArticle({ story, categories, tx, lang, locale, securitiesMap, onOpenCompany, children }) {
  const copy = COPY[lang];
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
  </div>;
}
