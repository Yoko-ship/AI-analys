import { NEWS_TX, newsRelTime } from "./editorial.jsx";
import React from "react";
import { CorporateEvents } from "./CorporateEvents.jsx";
import { useTranslationTick } from "./newsTranslation.js";
import { NewsDeskRow } from "./NewsCards.jsx";
import { NEWS_TABS, NEWS_INSTRUMENTS } from "./newsRouting.js";
import { NewsCalendarView } from "./NewsCalendarView.jsx";
import { useNewsFeed } from "./useNewsFeed.js";
export function NewsView({
  language,
  onOpenCompany,
  onOpenNews,
  onOpenAnnouncement,
  favoriteTickers, apiFetch, signedIn, securitiesMap
}) {
  const tx = NEWS_TX[language] || NEWS_TX.ru;
  useTranslationTick();
  const {
    state,
    tab,
    instrument,
    corporateEventId,
    selectTab,
    selectInstrument
  } = useNewsFeed({});

  // Kept in the URL so a tab can be linked and survives a reload — as a query,
  // not a path, because /news/{slug} is already the article route.

  // One writer for the query string: the tab and the instrument share it, and
  // two callbacks each rebuilding the URL from their own state dropped the
  // other's parameter every time either was pressed.

  const {
    loading,
    error,
    items: sourceItems
  } = state;
  const [newsSearch, setNewsSearch] = React.useState("");
  const searchLabel = language === "en" ? "Search news" : language === "uz" ? "Yangiliklarni qidirish" : "Поиск новостей";
  const items = React.useMemo(() => {
    const query = newsSearch.trim().toLocaleLowerCase();
    return query ? sourceItems.filter(item => [item.title, item.title_ru, item.title_en, item.title_uz,
      item.summary_ru, item.summary_en, item.summary_uz, ...(item.tickers || [])].filter(Boolean).join(" ").toLocaleLowerCase().includes(query)) : sourceItems;
  }, [sourceItems, newsSearch]);
  const latest = React.useMemo(() => [...items].sort((a,b)=>String(b.published_at||'').localeCompare(String(a.published_at||''))),[items]);
  const feedItems=latest;
  const dtx = tx.desk || NEWS_TX.ru.desk;
  const updated = latest[0] && latest[0].published_at ? newsRelTime(latest[0].published_at, language) : "";
  const corporateDetail = tab === "corporate" && Boolean(corporateEventId);
  return <div className={`news-view led newsdesk${corporateDetail ? " newsdesk--corporate-article" : ""}`}>
      {!corporateDetail && <header className="newsdesk-head">
        <div>
          {tab === 'calendar' && <button type="button" className="newsdesk-back" onClick={() => selectTab('general')}>← {tx.title}</button>}
          <h1>{tab === 'calendar' ? language === 'en' ? 'Events calendar' : language === 'uz' ? 'Voqealar taqvimi' : 'Календарь событий' : tx.title}</h1>
          <p>{tab === "corporate" && instrument !== "all" && tx.instrumentHint && tx.instrumentHint[instrument] || tx.tabHint && tx.tabHint[tab] || tx.subtitle}</p>
        </div>
        {!loading && tab !== "calendar" && tab !== "corporate" && <div className="newsdesk-updated">
            {updated && <span>{dtx.updated} {updated}</span>}
            <span>{items.length} {dtx.stories}</span>
          </div>}
      </header>}

      <div className="newsdesk-tabbar">
      <nav className="newsdesk-tabs" aria-label={tx.title}>
        {NEWS_TABS.map(t => <button
          key={t.key}
          type="button"
          data-tab={t.key}
          className={`newsdesk-tab ${tab === t.key ? "active" : ""}`}
          aria-current={tab === t.key ? "page" : undefined}
          onClick={() => selectTab(t.key)}
        >
            {tx.tabs && tx.tabs[t.key] || t.key}
          </button>)}
      </nav>
      </div>

      {tab !== "corporate" && tab !== "calendar" && <label className="newsdesk-search">
        <span>{searchLabel}</span>
        <input type="search" value={newsSearch} onChange={e => setNewsSearch(e.target.value)} />
      </label>}

      {/* A second row, not three more tabs beside the first: this narrows
          «Корпоративные», it is not a fourth peer of it. */}
      {tab === "corporate" && !corporateDetail && <div className="newsdesk-subtabs" role="group" aria-label={tx.tabs && tx.tabs.corporate || "corporate"}>
          {NEWS_INSTRUMENTS.map(key => <button
            key={key}
            type="button"
            className={`newsdesk-subtab ${instrument === key ? "active" : ""}`}
            aria-pressed={instrument === key}
            onClick={() => selectInstrument(key)}
          >
              {tx.instruments && tx.instruments[key] || key}
            </button>)}
        </div>}

      {tab === "corporate" ? <CorporateEvents apiFetch={apiFetch} signedIn={signedIn} securitiesMap={securitiesMap} language={language} favoriteTickers={favoriteTickers} instrument={instrument} onOpenCompany={onOpenCompany} /> : tab === "calendar" ? <NewsCalendarView language={language} onOpenCompany={onOpenCompany} onOpenAnnouncement={onOpenAnnouncement} onOpenNews={onOpenNews} /> : loading ? <div className="newsdesk-loading" aria-label={tx.loadingText}>
          <div className="newsdesk-loading-lead" />
          <div className="newsdesk-loading-feed" />
        </div> : error ? <div className="led-empty">{tx.error}</div> : !items.length ? <div className="led-empty">
          {newsSearch.trim() ? language === "en" ? "No news matches your search." : language === "uz" ? "So‘rovingiz bo‘yicha yangiliklar yo‘q." : "По вашему запросу новостей нет." : tab === "general" ? tx.empty : tx.emptyTab || tx.empty}
        </div> : <div className="newsdesk-board">
          <section className="newsdesk-feed-layout">
            <main className="newsdesk-feed">
              <div className="newsdesk-feed-head">
                <span className="newsdesk-live-dot" aria-hidden="true" />
                <h2>{dtx.latest}</h2>
                <span>{dtx.important}</span>
              </div>
              <div className="newsdesk-rows">
                {feedItems.map((item, index) => <NewsDeskRow key={item.id || item.url || index} item={item} language={language} onOpen={onOpenNews} />)}
                {!feedItems.length && <div className="newsdesk-feed-empty">{tx.emptyTab || tx.empty}</div>}
              </div>
            </main>
          </section>
        </div>}

    </div>;
}
