import { NewsAdminPanel } from "./NewsAgentPanel.jsx";
import { EDNEWS_TX, NEWS_TX, newsRelTime } from "./editorial.jsx";
import React from "react";
import { normalizeLanguage } from "../../shared/i18n.jsx";
import { pickLeadIndex } from "../../lib/newsfeed.js";
import { MarketEventsFeed } from "../events/index.js";
import { feedSentiment } from "./newsText.jsx";
import { useTranslationTick } from "./newsTranslation.js";
import { NewsDeskPriorityStory, NewsDeskRow, newsDeskFocus } from "./NewsCards.jsx";
import { NEWS_TABS, NEWS_INSTRUMENTS } from "./newsRouting.js";
import { NewsCalendarView } from "./NewsCalendarView.jsx";
import { useNewsFeed } from "./useNewsFeed.js";
export function NewsView({
  language,
  onOpenCompany,
  onOpenNews,
  onOpenAnnouncement,
  user,
  apiFetch
}) {
  const tx = NEWS_TX[language] || NEWS_TX.ru;
  useTranslationTick();
  const etx = EDNEWS_TX[language] || EDNEWS_TX.ru;
  const {
    state,
    tab,
    instrument,
    selectTab,
    selectInstrument,
    setReloadKey
  } = useNewsFeed({});

  // Kept in the URL so a tab can be linked and survives a reload — as a query,
  // not a path, because /news/{slug} is already the article route.

  // One writer for the query string: the tab and the instrument share it, and
  // two callbacks each rebuilding the URL from their own state dropped the
  // other's parameter every time either was pressed.

  const {
    loading,
    error,
    items
  } = state;
  // Which story gets the masthead when the top-ranked one cannot be illustrated
  // — see lib/newsfeed.js. Nothing is dropped: the story that would have led
  // simply leads the stack instead.
  const leadIndex = React.useMemo(() => pickLeadIndex(items), [items]);
  const lead = items[leadIndex];
  const stack = items.filter((_, i) => i !== leadIndex);
  // The main column follows the API's impact ranking; the rail is literally "latest", so it
  // needs its own chronological copy rather than the top of the ranked list.
  const latest = React.useMemo(() => [...items].sort((a, b) => String(b.published_at || "").localeCompare(String(a.published_at || ""))), [items]);
  const mood = feedSentiment(items);
  const moodLabel = mood.cls === "pos" ? etx.moodPos : mood.cls === "neg" ? etx.moodNeg : etx.moodNeu;
  const secondary = stack.slice(0, 2);
  const priorityItems = lead ? [lead, ...secondary] : secondary;
  const feedItems = latest.filter(item => !priorityItems.includes(item));
  const focus = React.useMemo(() => newsDeskFocus(items), [items]);
  const dtx = tx.desk || NEWS_TX.ru.desk;
  const updated = latest[0] && latest[0].published_at ? newsRelTime(latest[0].published_at, language) : "";
  return <div className="news-view led newsdesk">
      <header className="newsdesk-head">
        <div>
          <h1>{tx.title}</h1>
          <p>{tab === "corporate" && instrument !== "all" && tx.instrumentHint && tx.instrumentHint[instrument] || tx.tabHint && tx.tabHint[tab] || tx.subtitle}</p>
        </div>
        {!loading && tab !== "calendar" && <div className="newsdesk-updated">
            {updated && <span>{dtx.updated} {updated}</span>}
            <span>{items.length} {dtx.stories}</span>
          </div>}
      </header>

      <nav className="newsdesk-tabs" aria-label={tx.title}>
        {NEWS_TABS.map(t => <button
          key={t.key}
          type="button"
          className={`newsdesk-tab ${tab === t.key ? "active" : ""}`}
          aria-current={tab === t.key ? "page" : undefined}
          onClick={() => selectTab(t.key)}
        >
            {tx.tabs && tx.tabs[t.key] || t.key}
          </button>)}
      </nav>

      {/* A second row, not three more tabs beside the first: this narrows
          «Корпоративные», it is not a fourth peer of it. */}
      {tab === "corporate" && <div className="newsdesk-subtabs" role="group" aria-label={tx.tabs && tx.tabs.corporate || "corporate"}>
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

      {user && user.is_admin && apiFetch && <NewsAdminPanel language={language} apiFetch={apiFetch} onStored={() => setReloadKey(k => k + 1)} />}
      {tab === "calendar" ? <NewsCalendarView language={language} onOpenCompany={onOpenCompany} onOpenAnnouncement={onOpenAnnouncement} /> : loading ? <div className="newsdesk-loading" aria-label={tx.loadingText}>
          <div className="newsdesk-loading-lead" />
          <div className="newsdesk-loading-side" />
          <div className="newsdesk-loading-feed" />
        </div> : error ? <div className="led-empty">{tx.error}</div> : !items.length ? <div className="led-empty">
          {tab === "corporate" && instrument !== "all" ? tx.emptyInstrument || tx.emptyTab || tx.empty : tab === "all" ? tx.empty : tx.emptyTab || tx.empty}
        </div> : <div className="newsdesk-board">
          <section className="newsdesk-priority" aria-label={dtx.main}>
            {lead && <NewsDeskPriorityStory item={lead} language={language} variant="lead" onOpen={onOpenNews} />}
            <div className="newsdesk-secondary">
              {secondary.map((item, index) => <NewsDeskPriorityStory key={item.id || item.url || index} item={item} language={language} variant="secondary" onOpen={onOpenNews} />)}
            </div>
            <aside className="newsdesk-mood">
              <h2>{dtx.marketNow}</h2>
              <div className="newsdesk-mood-score"><strong className={mood.cls}>{(mood.avg >= 0 ? "+" : "") + mood.avg.toFixed(2)}</strong><span>{dtx.days30}</span></div>
              <div className="newsdesk-mood-row"><span>{dtx.positive}</span><b>{mood.counts.positive}</b></div>
              <div className="newsdesk-mood-row"><span>{dtx.neutral}</span><b>{mood.counts.neutral}</b></div>
              <div className="newsdesk-mood-row"><span>{dtx.negative}</span><b>{mood.counts.negative}</b></div>
              <small>{moodLabel}</small>
            </aside>
          </section>

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
            <aside className="newsdesk-side">
              {focus.length > 0 && <section className="newsdesk-side-section">
                  <h2>{dtx.focus}</h2>
                  {focus.map(([ticker, count]) => <button key={ticker} type="button" className="newsdesk-focus-row" onClick={() => onOpenCompany && onOpenCompany(ticker)}>
                      <strong>{ticker}</strong><span>{count} {dtx.events}</span>
                    </button>)}
                </section>}
              <section className="newsdesk-side-section newsdesk-calendar-callout">
                <h2>{dtx.calendar}</h2>
                <p>{dtx.calendarCopy}</p>
                <button type="button" onClick={() => selectTab("calendar")}>{dtx.openCalendar} →</button>
              </section>
            </aside>
          </section>
        </div>}

      {/* The filings timeline is the raw disclosure record for the corporate
          reading mode. It follows the edited board instead of interrupting its
          priority hierarchy; the Акции/Облигации control still narrows only the
          stories above, while this record keeps its own filing-kind controls. */}
      {tab === "corporate" && <div className="newsdesk-disclosures">
          <MarketEventsFeed lang={normalizeLanguage(language)} onOpenCompany={onOpenCompany} />
        </div>}
    </div>;
}
