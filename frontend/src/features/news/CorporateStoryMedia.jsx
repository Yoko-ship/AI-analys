import { useState } from 'react';
import { CompanyLogo } from '../../shared/CompanyLogo.jsx';
import { safeHref } from '../../lib/safeHref.js';

function issuerIdentity(story, securitiesMap) {
  const tickers = story.tickers || [];
  const ticker = tickers.find(t => securitiesMap[t]?.logo_url) || tickers[0] || '';
  return { ticker, logo: safeHref(securitiesMap[ticker]?.logo_url), name: story.organization || securitiesMap[ticker]?.name || ticker };
}

function IssuerMark({ story, securitiesMap }) {
  const { ticker, logo, name } = issuerIdentity(story, securitiesMap);
  return <CompanyLogo key={`${ticker}-${logo || ''}`} logo={logo} name={name} ticker={ticker} />;
}

function useSourceImage(imageURL) {
  const [failed, setFailed] = useState('');
  const [loaded, setLoaded] = useState(null);
  const src = safeHref(imageURL);
  return {
    src: src && src !== failed ? src : null,
    naturalWidth: loaded && loaded.src === src ? loaded.width : undefined,
    onLoad: e => setLoaded({ src, width: e.currentTarget.naturalWidth }),
    onError: () => setFailed(src),
  };
}

export function CorporateIssuer({ story, securitiesMap, onOpenCompany }) {
  return <div className="ce-article-issuer">
    <IssuerMark story={story} securitiesMap={securitiesMap} />
    <div><strong>{story.organization}</strong><span className="ce-issuer-tickers">{(story.tickers || []).map(t =>
      <button type="button" key={t} onClick={() => onOpenCompany?.(t)}>{t}</button>
    )}</span></div>
  </div>;
}

export function CorporateArticlePhoto({ story, caption }) {
  const image = useSourceImage(story.image_url);
  return image.src ? <figure className="ce-article-photo">
    <img src={image.src} alt="" decoding="async" style={{ maxWidth: image.naturalWidth }} onLoad={image.onLoad} onError={image.onError} />
    <figcaption>{caption}</figcaption>
  </figure> : null;
}
