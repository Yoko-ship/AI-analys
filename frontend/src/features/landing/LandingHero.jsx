import { useState } from 'react';
import lightArtwork from '../../assets/landing-glass-light.webp';
import darkArtwork from '../../assets/landing-glass-dark.webp';

const COPY = {
  ru: {
    topics: ['Акции', 'Аналитика', 'Дивиденды'],
    titles: [['За каждой', 'акцией —', 'компания.'], ['За цифрами —', 'целая история.'], ['У каждой', 'выплаты —', 'своя история.']],
    descriptions: [
      'Котировки, отчётность и события рынка Узбекистана.',
      'Отчётность, финансовая история и показатели компаний. Изучайте данные в контексте.',
      'История дивидендов и корпоративные события. Узнайте, что стоит за каждой выплатой.',
    ],
    market: 'Исследовать рынок', company: 'Изучить компанию', open: 'Открыть компанию',
    explore: 'Исследуйте рынок', group: 'Откройте для себя UZStock',
  },
  uz: {
    topics: ['Aksiyalar', 'Tahlil', 'Dividendlar'],
    titles: [['Har bir aksiya', 'ortida —', 'kompaniya.'], ['Raqamlar ortida —', 'butun bir tarix.'], ['Har bir to‘lovning', 'o‘z tarixi bor.']],
    descriptions: [
      'O‘zbekiston bozori kotirovkalari, hisobotlari va voqealari.',
      'Kompaniyalar hisobotlari, moliyaviy tarixi va ko‘rsatkichlari. Ma’lumotlarni mazmuni bilan o‘rganing.',
      'Dividendlar tarixi va korporativ voqealar. Har bir to‘lov ortidagi ma’lumotlarni o‘rganing.',
    ],
    market: 'Bozorni o‘rganish', company: 'Kompaniyani o‘rganish', open: 'Kompaniyani ochish',
    explore: 'Bozorni o‘rganing', group: 'UZStock imkoniyatlari',
  },
  en: {
    topics: ['Shares', 'Analysis', 'Dividends'],
    titles: [['Behind every', 'share is', 'a company.'], ['Behind the numbers,', 'a bigger picture.'], ['Every dividend', 'has a story.']],
    descriptions: [
      'Quotes, financial reports and events from Uzbekistan’s market.',
      'Financial reports, company history and key ratios. Explore the numbers in context.',
      'Dividend history and corporate events. Discover the context behind each payment.',
    ],
    market: 'Explore the market', company: 'Explore the company', open: 'Open company',
    explore: 'Explore the market', group: 'Discover UZStock',
  },
};

function Arrow({ diagonal = false }) {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
    <path d={diagonal ? 'M5 19 19 5M5 5h14v14' : 'M4 12h16m-6-6 6 6-6 6'} />
  </svg>;
}

export function LandingHero({ lang, theme, onNavigate, onOpenCompany }) {
  const [topic, setTopic] = useState(0);
  const copy = COPY[lang] || COPY.ru;
  return <section className="lv-stage landing-hero" aria-labelledby="landing-headline">
    <div className="landing-hero-art" aria-hidden="true">
      <img src={theme === 'dark' ? darkArtwork : lightArtwork} width="1586" height="992" alt="" fetchPriority="high" />
    </div>
    <div className="landing-hero-main">
      <div className="landing-hero-copy" key={`${lang}-${topic}`}>
        <h1 className="lv-h1" id="landing-headline">{copy.titles[topic].map((line, i) => <span key={line}>{i > 0 && ' '}{line}</span>)}</h1>
        <p className="landing-hero-description">{copy.descriptions[topic]}</p>
        <div className="lv-actions">
          <button type="button" className="landing-hero-primary" data-track-control="landing_hero_cta" data-track-value={topic === 0 ? 'market' : 'company'}
            onClick={() => topic === 0 ? onNavigate('market') : onOpenCompany('UZTL')}>
            {topic === 0 ? copy.market : copy.company}<Arrow diagonal />
          </button>
        </div>
      </div>
    </div>
    <button type="button" className="landing-hero-company" onClick={() => onOpenCompany('UZTL')}
      data-track-control="landing_featured_company" data-track-value="UZTL">
      <span><b>UZTL</b><span aria-hidden="true"> / </span>{copy.open}</span><Arrow diagonal />
    </button>
    <div className="landing-hero-footer">
      <div className="landing-hero-rail">
        <div className="landing-hero-topics" role="group" aria-label={copy.group}>
          {copy.topics.map((label, i) => <button type="button" key={i} aria-pressed={topic === i}
            data-track-control="landing_topic" data-track-value={['shares', 'analysis', 'dividends'][i]}
            onClick={() => setTopic(i)}><span className="landing-topic-number">0{i + 1} / </span>{label}</button>)}
        </div>
        <button className="landing-hero-explore" type="button" onClick={() => onNavigate('market')}>{copy.explore}<Arrow /></button>
      </div>
    </div>
  </section>;
}
