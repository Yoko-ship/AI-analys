import { useEffect, useState } from 'react';
import { edHeadline, newsArticlePath, interceptNav, newsRelTime } from '../news/index.js';
import { LandingArrow } from './LandingHero.jsx';

export function LandingNews({ copy, lang, onOpenNews, onNavigate }) {
  const [state, setState] = useState({ loading: true, error: false, items: [] });
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ loading: true, error: false, items: [] });
    fetch('/api/news/feed?limit=3&days=30&section=general', { signal: controller.signal })
      .then(async response => {
        const data = await response.json();
        if (!response.ok || !data.ok || !Array.isArray(data.items)) throw new Error('News unavailable');
        return data.items;
      })
      .then(items => setState({ loading: false, error: false, items: items.slice(0, 3) }))
      .catch(error => { if (error.name !== 'AbortError') setState({ loading: false, error: true, items: [] }); });
    return () => controller.abort();
  }, [reload]);
  return <section className="landing-news" aria-labelledby="landing-news-title">
    <div className="landing-section-heading"><div><p className="landing-eyebrow">{copy.newsEyebrow}</p><h2 id="landing-news-title">{copy.newsTitle}</h2></div>
      <button className="landing-text-link" type="button" onClick={() => onNavigate('news')}>{copy.allNews}<LandingArrow /></button>
    </div>
    {state.loading ? <div className="landing-loading" role="status">{copy.newsLoading}</div>
      : state.error ? <div className="landing-data-notice" role="alert"><p>{copy.newsError}</p><button type="button" onClick={() => setReload(value => value + 1)}>{copy.retry}</button></div>
      : !state.items.length ? <p className="landing-data-notice">{copy.newsEmpty}</p>
      : <div className="landing-news-grid">{state.items.map((item, index) => <a key={item.id || index} className="landing-news-card" href={newsArticlePath(item, lang)}
        onClick={item.id ? event => interceptNav(event, () => onOpenNews(item.id)) : undefined}>
        <span className="landing-news-source">{item.source_name || item.source || 'UZStock'}</span>
        <h3>{edHeadline(item, lang).text}</h3>
        <span className="landing-news-bottom"><time dateTime={item.published_at}>{newsRelTime(item.published_at, lang)}</time><LandingArrow /></span>
      </a>)}</div>}
  </section>;
}
