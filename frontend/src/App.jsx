import { Suspense, useEffect } from "react";
import { loadConfig } from "./lib/flags.js";
import { setTrackedUser } from "./lib/track.js";
import { LandingView } from "./features/landing/index.js";
import { CatalogView } from "./features/catalog/index.js";
import { AdminPanel, SectorMonitorPage } from "./app/LazyViews.jsx";
import { AnnouncementArticleView, NewsArticleView, NewsView } from "./features/news/index.js";
import { normalizeLanguage } from "./shared/i18n.jsx";
import { CompanyPage } from "./features/company/index.js";
import { AdvancedChart } from "./features/charts/index.js";
import { BondCard } from "./features/bonds/index.js";
import { MarketView } from "./features/market/index.js";
import { BankFxPage } from "./features/currency/index.js";
import { FeedbackPage } from "./features/feedback/index.js";
import { PortfolioView } from "./features/portfolio/index.js";
import { useSession } from "./session/useSession.js";
import { usePreferences } from "./app/usePreferences.jsx";
import { useNavigation } from "./app/useNavigation.jsx";
import { useToasts } from "./app/useToasts.jsx";
import { useMarketData } from "./features/market/index.js";
import { useAuthentication } from "./features/auth/index.js";
import { useResearch } from "./features/research/index.js";
import { useProfile } from "./features/profile/index.js";
import { useNotifications } from "./app/useNotifications.jsx";
import { useShell } from "./app/useShell.jsx";
import { useFavorites } from "./features/profile/index.js";

function App() {
  useEffect(() => { loadConfig(); }, []);
  const preferences = usePreferences();
  const sessionState = useSession(preferences.language);
  const session = {
   ...sessionState,
   favoriteTickers: new Set((sessionState.profile?.favorites || []).map(item => String(item?.ticker || "").trim().toUpperCase()).filter(Boolean)),
   profileUser: sessionState.profile?.user || sessionState.user,
   hasProAccess: Boolean(sessionState.profile?.user?.pro_access ?? sessionState.user?.pro_access),
   loadProfile: sessionState.refreshProfile, endSession: sessionState.logout,
  };
  useEffect(() => { setTrackedUser(session.user && session.user.id); }, [session.user]);
  const navigation = useNavigation();
  const toasts = useToasts();
  const market = useMarketData({ toasts, preferences, session, navigation });
  const auth = useAuthentication({ navigation, session, toasts, preferences, market });
  const favorites = useFavorites({ session, toasts, preferences, navigation });
  const research = useResearch({ session, toasts, preferences, navigation, market, favorites });
  const account = useProfile({ session, toasts, preferences, navigation, market, auth, favorites });
  const notifications = useNotifications({ session, toasts, navigation });
  const shell = useShell({ session, preferences, navigation, market, notifications, auth, toasts });
  const { activeView, setActiveView, openCompanyPage, openNewsArticle, adminSection, setAdminSection, openAnnouncementArticle, newsId, backToNewsCalendar, companyTicker, openChartPage, prevView, chartState, openBondPage } = navigation;
  const { language, theme } = preferences;
  const { marketRows, marketTradeStats, securitiesMap, companies, catalogStatus, setMarketType, marketMeta, marketLoading, marketMessage, marketQuery, setMarketQuery, marketType, loadMarketStocks, marketFinancials } = market;
  const { token, user, apiFetch, favoriteTickers, hasProAccess } = session;
  const { addToast } = toasts;
  const { setAnalysisCompany } = research;
  const { handleToggleFavorite } = favorites;
  return shell.render(<>
          {activeView === "main" && (
            <LandingView
              language={language}
              theme={theme}
              marketRows={marketRows}
              tradeStats={marketTradeStats}
              securitiesMap={securitiesMap}
              companies={companies}
              onNavigate={setActiveView}
              onOpenCompany={openCompanyPage}
              onOpenNews={openNewsArticle}
            />
          )}

          {activeView === "catalog" && (
            <CatalogView
              language={language}
              companies={companies}
              token={token}
              addToast={addToast}
              onNavigateToAnalysis={(t) => { setAnalysisCompany(t); setActiveView("analysis"); }}
              initialStatus={catalogStatus}
              user={user}
            />
          )}

          {/* Reached by direct link only — it is deliberately absent from
              navItems, because it is a tool for whoever maintains the data. */}
          {/* The panel is a page of the site, so it renders in the same content
              column as every other view. A non-admin who guesses the URL is told
              plainly rather than redirected: silently bouncing a signed-in user
              reads as a bug, and the page is not secret — its data is guarded on
              the server, where guarding belongs. */}
          {activeView === "admin" && (
            user && adminSection === "sector-analysis" ? <Suspense fallback={<div className="panel">Loading…</div>}><SectorMonitorPage apiFetch={apiFetch} language={language} /></Suspense> : (user?.is_admin || user?.admin_role) ? (
              <Suspense fallback={<div className="panel">Loading…</div>}><AdminPanel
                apiFetch={apiFetch}
                language={language}
                section={adminSection}
                onSectionChange={setAdminSection}
                user={user}
              /></Suspense>
            ) : (
              <div className="panel" style={{ textAlign: "center", padding: 48 }}>
                <div className="panel-label">
                  {language === "en" ? "Internal" : language === "uz" ? "Xizmat" : "Служебное"}
                </div>
                <h2 style={{ margin: "0 0 8px" }}>
                  {language === "en" ? "Administrators only"
                    : language === "uz" ? "Faqat administratorlar uchun"
                      : "Только для администраторов"}
                </h2>
                <p className="muted" style={{ margin: "0 auto 18px", maxWidth: "48ch" }}>
                  {language === "en" ? "This page maintains the data behind the site. Your account does not have access to it."
                    : language === "uz" ? "Bu sahifa sayt ma'lumotlarini boshqaradi. Hisobingizda unga kirish huquqi yo'q."
                      : "Эта страница обслуживает данные сайта. У вашей учётной записи нет к ней доступа."}
                </p>
                <button type="button" className="primary-btn" onClick={() => setActiveView("main")}>
                  {language === "en" ? "Back to the site" : language === "uz" ? "Saytga qaytish" : "Вернуться на сайт"}
                </button>
              </div>
            )
          )}

          {activeView === "news" && (
            <NewsView
              language={language}
              onOpenCompany={openCompanyPage}
              onOpenNews={openNewsArticle}
              onOpenAnnouncement={openAnnouncementArticle}
              user={user}
              apiFetch={apiFetch}
            />
          )}

          {activeView === "newsArticle" && newsId && (
            <NewsArticleView
              key={newsId}
              newsId={newsId}
              language={language}
              securitiesMap={securitiesMap}
              onOpenCompany={openCompanyPage}
              onOpenNews={openNewsArticle}
              onBack={() => setActiveView("news")}
            />
          )}

          {activeView === "announcementArticle" && newsId && (
            <AnnouncementArticleView
              key={`${newsId}-${normalizeLanguage(language)}`}
              announcementId={newsId}
              language={language}
              onBack={backToNewsCalendar}
            />
          )}

          {activeView === "company" && companyTicker && (
            <CompanyPage
              key={companyTicker}
              ticker={companyTicker}
              securitiesMap={securitiesMap}
              language={language}
              marketRows={marketRows}
              tradeStats={marketTradeStats}
              favoriteTickers={favoriteTickers}
              onToggleFavorite={handleToggleFavorite}
              signedIn={Boolean(token)}
              hasProAccess={hasProAccess}
              apiFetch={apiFetch}
              onUpgrade={() => setActiveView(token ? "profile" : "auth")}
              onOpenCompany={openCompanyPage}
              onOpenChart={openChartPage}
              onBack={() => setActiveView(prevView || "market")}
            />
          )}

          {activeView === "chart" && companyTicker && (
            <AdvancedChart
              key={companyTicker}
              ticker={companyTicker}
              securitiesMap={securitiesMap}
              marketRows={marketRows}
              tradeStats={marketTradeStats}
              lang={normalizeLanguage(language)}
              favorites={favoriteTickers}
              onToggleFavorite={handleToggleFavorite}
              signedIn={Boolean(token)}
              hasProAccess={hasProAccess}
              apiFetch={apiFetch}
              onUpgrade={() => setActiveView(token ? "profile" : "auth")}
              initial={chartState}
              onBack={() => setActiveView(prevView === "chart" ? "company" : (prevView || "company"))}
              onOpenCompany={openCompanyPage}
              // The chart hands back the toolbar it is actually showing —
              // `chartState` here is only what the URL was parsed into on a
              // cold load, and goes stale the moment anything is pressed.
              onOpenChart={(tk, state) => openChartPage(tk, state || { ...chartState, compare: [] })}
            />
          )}

          {activeView === "bond" && companyTicker && (
            <BondCard
              key={companyTicker}
              ticker={companyTicker}
              language={language}
              onBack={() => {
                // The list behind the card is the board's «Облигации» segment.
                const target = prevView && prevView !== "bond" ? prevView : "market";
                if (target === "market") setMarketType("bond");
                setActiveView(target);
              }}
              onOpenChart={openChartPage}
            />
          )}

          {(activeView === "market" || activeView === "heatmap") && (
            <MarketView
              rows={marketRows}
              meta={marketMeta}
              loading={marketLoading}
              message={marketMessage}
              query={marketQuery}
              onQueryChange={setMarketQuery}
              type={marketType}
              onTypeChange={setMarketType}
              onRefresh={() => { loadMarketStocks(null, { refresh: true }).catch((error) => addToast(error.message, "error")); }}
              onAnalyze={(ticker) => {
                setAnalysisCompany(ticker || "");
                setActiveView("analysis");
              }}
              onOpenCompany={openCompanyPage}
              onOpenBond={openBondPage}
              onOpenBankFx={() => setActiveView("bankfx")}
              language={language}
              companies={companies}
              securitiesMap={securitiesMap}
              financials={marketFinancials}
              tradeStats={marketTradeStats}
              favoriteTickers={favoriteTickers}
              onToggleFavorite={handleToggleFavorite}
              viewMode={activeView === "heatmap" ? "heatmap" : "table"}
              onViewModeChange={(m) => setActiveView(m === "heatmap" ? "heatmap" : "market")}
              isAdmin={Boolean(user?.is_admin)}
            />
          )}

          {activeView === "bankfx" && <BankFxPage language={language} />}

          {activeView === "feedback" && (
            <FeedbackPage language={language} signedIn={Boolean(token)} apiFetch={apiFetch}
              onSignIn={() => setActiveView("auth")} />
          )}

          {activeView === "portfolio" && (
            <PortfolioView language={language} apiFetch={apiFetch} signedIn={Boolean(token)}
              hasProAccess={hasProAccess} onUpgrade={() => setActiveView(token ? "profile" : "auth")}
              onOpenCompany={openCompanyPage} />
          )}

        {auth.view}{account.view}{research.view}</>);
}

export default App;
