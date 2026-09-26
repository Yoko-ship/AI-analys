import { snapPixel } from "../lib/geometry.js";
import { useEffect, useRef, useState } from "react";
import { rootZoom, zoomedViewport } from "../shared/viewport.jsx";
import { BrandIcon } from "../shared/BrandIcon.jsx";
import { clg, normalizeLanguage, t } from "../shared/i18n.jsx";
import { mt } from "../shared/marketCopy.jsx";
import { createPortal } from "react-dom";
import { ct } from "../features/research/index.js";
import { patternName } from "../lib/patterns.js";
import { accountInitials } from "../shared/accountIdentity.jsx";
import { TopbarFxTicker } from "../features/currency/index.js";
import { TEXT_SCALES } from "./preferences.jsx";
import { DisclaimerNote } from "../shared/DisclaimerNote.jsx";
import { ToastStack } from "./toasts.jsx";
import { SponsorOverlay } from "./SponsorOverlay.jsx";

export function useShell({ session: sessionModule, preferences: preferencesModule, navigation: navigationModule, market: marketModule, notifications: notificationsModule, auth: authModule, toasts: toastsModule }) {
  const { token, user } = sessionModule;
  const { language, setLanguage, stepTextScale, textScale, setTextScale, toggleTheme, theme } = preferencesModule;
  const { activeView, setActiveView } = navigationModule;
  const { catalogStatus } = marketModule;
  const { setNotifOpen, notifCount, notifOpen, notifItems, updateNotificationState, openNotification } = notificationsModule;
  const { handleLogout } = authModule;
  const { toasts, setToasts } = toastsModule;
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);

  const accountMenuRef = useRef(null);

  useEffect(() => {
    if (!accountMenuOpen) return undefined;
    const closeOutside = (event) => {
      if (accountMenuRef.current && !accountMenuRef.current.contains(event.target)) setAccountMenuOpen(false);
    };
    const closeOnEscape = (event) => { if (event.key === "Escape") setAccountMenuOpen(false); };
    document.addEventListener("mousedown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [accountMenuOpen]);

  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    const bar = document.querySelector(".topbar");
    if (!bar) return undefined;
    let raf = 0;
    const apply = () => {
      raf = 0;
      const h = snapPixel(bar.getBoundingClientRect().height);
      if (h > 0) document.documentElement.style.setProperty("--topbar-h", `${h}px`);
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(apply); };
    apply();
    const ro = new ResizeObserver(schedule);
    ro.observe(bar);
    window.addEventListener("resize", schedule);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", schedule);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  const navItems = token
    ? ["main", "market", "catalog", "news", "feedback", "profile"]
    : ["main", "market", "catalog", "news", "feedback", "auth"];

  const [marketMenuOpen, setMarketMenuOpen] = useState(false);

  const [marketMenuPos, setMarketMenuPos] = useState(null);

  const marketMenuWrapRef = useRef(null);

  const marketMenuTimer = useRef(null);

  useEffect(() => () => clearTimeout(marketMenuTimer.current), []);

  const openMarketMenu = () => {
    clearTimeout(marketMenuTimer.current);
    const r = marketMenuWrapRef.current?.getBoundingClientRect();
    if (r) {
      const z = rootZoom();
      setMarketMenuPos({ top: r.bottom / z, left: r.left / z });
    }
    setMarketMenuOpen(true);
  };

  const closeMarketMenuSoon = () => {
    clearTimeout(marketMenuTimer.current);
    marketMenuTimer.current = setTimeout(() => setMarketMenuOpen(false), 140);
  };

  const closeMarketMenu = () => {
    clearTimeout(marketMenuTimer.current);
    setMarketMenuOpen(false);
  };

  useEffect(() => {
    if (!marketMenuOpen) return undefined;
    const close = () => { clearTimeout(marketMenuTimer.current); setMarketMenuOpen(false); };
    window.addEventListener("scroll", close, { passive: true, capture: true });
    return () => window.removeEventListener("scroll", close, { capture: true });
  }, [marketMenuOpen]);

  const navDdLabel = (ru, uz, en) => (language === "en" ? en : language === "uz" ? uz : ru);

  const render = (children) => (<div className={`app-shell-wrap view-${activeView}`} data-build="2026-09-11.2">
      <div className="bg-glow bg-glow-a" />
      <div className="bg-glow bg-glow-b" />

      <div className="app-shell">
        <header className={`topbar${mobileNavOpen ? " is-nav-open" : ""}`}>
          <button
            className="topbar-burger"
            type="button"
            aria-label={mobileNavOpen ? (language === "en" ? "Close menu" : language === "uz" ? "Menyuni yopish" : "Закрыть меню") : (language === "en" ? "Open menu" : language === "uz" ? "Menyuni ochish" : "Открыть меню")}
            aria-expanded={mobileNavOpen}
            onClick={() => setMobileNavOpen((v) => !v)}
          >
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M3 6h18M3 12h18M3 18h18" /></svg>
          </button>
          <div className="topbar-brand">
            <BrandIcon />
            <div className="brand-copy">
              <div className="brand-title">{t(language, "brand")}</div>
              <div className="brand-subtitle">{t(language, "subtitle")}</div>
            </div>
          </div>

          <button className="topbar-nav-scrim" type="button" aria-hidden="true" tabIndex={-1} onClick={() => setMobileNavOpen(false)} />
          <nav className="topbar-nav">
            {navItems.map((key) => key === "market" ? (
              <div
                key={key}
                className="nav-dd-wrap"
                ref={marketMenuWrapRef}
                onMouseEnter={openMarketMenu}
                onMouseLeave={closeMarketMenuSoon}
              >
                <button
                  className={`topbar-nav-btn ${activeView === key || activeView === "bankfx" || activeView === "heatmap" ? "active" : ""}`}
                  type="button"
                  aria-haspopup="menu"
                  aria-expanded={marketMenuOpen}
                  onClick={() => { setActiveView("market"); setMobileNavOpen(false); closeMarketMenu(); }}
                >
                  {mt(language, "nav")}
                  <span className="nav-dd-caret" aria-hidden="true">▾</span>
                </button>
                {marketMenuOpen && marketMenuPos && createPortal(
                  <div
                    className="nav-dd-panel"
                    role="menu"
                    style={{ top: marketMenuPos.top, left: marketMenuPos.left }}
                    ref={(el) => {
                      // Clamp into the viewport once the width is known — the
                      // trigger can sit far enough right (compact band, long
                      // translations) that a left-anchored panel runs off-screen.
                      if (!el) return;
                      const { vw } = zoomedViewport();
                      el.style.left = `${Math.max(8, Math.min(marketMenuPos.left, vw - el.offsetWidth - 8))}px`;
                    }}
                    onMouseEnter={openMarketMenu}
                    onMouseLeave={closeMarketMenuSoon}
                  >
                    <div className="nav-dd-col">
                      <div className="nav-dd-head">{navDdLabel("Биржа", "Birja", "Exchange")}</div>
                      <button type="button" className="nav-dd-item" role="menuitem"
                        onClick={() => { setActiveView("market"); closeMarketMenu(); }}>
                        {navDdLabel("Биржевые инструменты", "Birja instrumentlari", "Exchange instruments")}
                      </button>
                      <button type="button" className="nav-dd-item" role="menuitem"
                        onClick={() => { setActiveView("heatmap"); closeMarketMenu(); }}>
                        {navDdLabel("Карта рынка", "Bozor xaritasi", "Market map")}
                      </button>
                    </div>
                    <div className="nav-dd-col">
                      <div className="nav-dd-head">{navDdLabel("Валюта", "Valyuta", "Currency")}</div>
                      <button type="button" className="nav-dd-item" role="menuitem"
                        onClick={() => { setActiveView("bankfx"); closeMarketMenu(); }}>
                        {navDdLabel("Курсы валют в банках", "Banklarda valyuta kurslari", "Bank exchange rates")}
                      </button>
                    </div>
                  </div>,
                  document.body
                )}
                {/* Drawer counterpart of the drop-down: indented rows. The
                    board itself is the parent item, so only the destinations
                    that live inside the panel need a way in. */}
                <button
                  className="topbar-nav-btn nav-dd-mobile-item"
                  type="button"
                  onClick={() => { setActiveView("heatmap"); setMobileNavOpen(false); }}
                >
                  {navDdLabel("Карта рынка", "Bozor xaritasi", "Market map")}
                </button>
                <button
                  className="topbar-nav-btn nav-dd-mobile-item"
                  type="button"
                  onClick={() => { setActiveView("bankfx"); setMobileNavOpen(false); }}
                >
                  {navDdLabel("Курсы валют в банках", "Banklarda valyuta kurslari", "Bank exchange rates")}
                </button>
              </div>
            ) : (
              <button key={key} className={`topbar-nav-btn ${activeView === key || (key === "news" && ["newsArticle", "announcementArticle"].includes(activeView)) ? "active" : ""}`} type="button" onClick={() => { setActiveView(key); setMobileNavOpen(false); }}>
                {key === "catalog" ? (
                  <span className="nav-catalog-wrap">
                    {t(language, "nav.catalog")}
                    {(() => {
                      if (!catalogStatus?.last_sync) return null;
                      const ageH = (Date.now() - new Date(catalogStatus.last_sync).getTime()) / 3600000;
                      return ageH > 24 ? <span className="nav-stale-dot" title={language === "ru" ? "Каталог устарел" : "Catalog stale"} /> : null;
                    })()}
                  </span>
                ) : key === "compare" ? ct(language, "nav")
                  : key === "portfolio" ? (language === "en" ? "Portfolio" : language === "uz" ? "Portfel" : "Портфель")
                    : key === "feedback" ? (language === "en" ? "Feedback" : language === "uz" ? "Fikr-mulohaza" : "Обратная связь")
                    : t(language, `nav.${key}`)}
              </button>
            ))}
          </nav>

          {token && (
            <div className="notif-wrap">
              <button className="notif-bell" type="button" onClick={() => { setNotifOpen((o) => !o); setAccountMenuOpen(false); }} aria-label="Notifications">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="20" height="20">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                  <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                </svg>
                {notifCount > 0 && <span className="notif-badge">{notifCount > 9 ? "9+" : notifCount}</span>}
              </button>
              {notifOpen && (
                <div className="notif-panel panel">
                  <div className="notif-panel-header">
                    <span className="panel-label">{clg(language, "notifications")}</span>
                    <div className="notif-panel-actions">
                      {notifItems.some((item) => !item.read) ? (
                        <button type="button" onClick={() => updateNotificationState(notifItems.filter((item) => !item.read).map((item) => item.id))}>
                          {language === "en" ? "Mark read" : language === "uz" ? "O'qildi" : "Прочитать всё"}
                        </button>
                      ) : null}
                      <button className="icon-btn" type="button" onClick={() => setNotifOpen(false)}>✕</button>
                    </div>
                  </div>
                  {notifItems.length === 0 ? (
                    <p className="muted notif-empty">{clg(language, "notifEmpty")}</p>
                  ) : (
                    <ul className="notif-list">
                      {notifItems.map((n, i) => (
                        <li key={n.id || i} className={`notif-item${n.read ? " is-read" : ""}`}>
                          <button className="notif-item-main" type="button" onClick={() => openNotification(n)}>
                            <div className="notif-item-title">{n.kind === "feedback"
                              ? (language === "en" ? "New feedback" : language === "uz" ? "Yangi fikr-mulohaza" : "Новая обратная связь")
                              : n.kind === "pattern"
                                ? `${n.ticker} · ${patternName(n.pattern, normalizeLanguage(language))}`
                                : `${n.ticker} · ${n.report_form} · ${n.year || "—"}${n.quarter > 0 ? ` Q${n.quarter}` : ""}`}</div>
                            <div className="notif-item-sub muted">{n.kind === "pattern"
                              ? `${n.direction === "bullish" ? "↑" : "↓"} ${language === "en" ? "pattern completed on the chart" : language === "uz" ? "grafikda pattern yakunlandi" : "фигура завершилась на графике"}`
                              : (n.title || clg(language, "notifNewReport"))} · {n.detected_at?.slice(0, 10)}</div>
                          </button>
                          <button className="notif-item-dismiss" type="button" onClick={() => updateNotificationState([n.id], true)} aria-label={language === "en" ? "Dismiss" : language === "uz" ? "O'chirish" : "Удалить"}>×</button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}

          {token && user ? (
            <div className="account-wrap" ref={accountMenuRef}>
              <button
                className="account-button"
                type="button"
                aria-haspopup="menu"
                aria-expanded={accountMenuOpen}
                aria-label={`${language === "en" ? "Account" : language === "uz" ? "Akkaunt" : "Аккаунт"}: ${user.full_name || user.email}`}
                onClick={() => { setAccountMenuOpen((open) => !open); setNotifOpen(false); }}
              >
                {user.avatar_data_url
                  ? <img src={user.avatar_data_url} alt="" />
                  : accountInitials(user)}
              </button>
              {accountMenuOpen && (
                <div className="account-menu panel" role="menu" aria-label={language === "en" ? "Account" : language === "uz" ? "Akkaunt" : "Аккаунт"}>
                  <div className="account-menu-head">
                    {user.full_name ? <strong>{user.full_name}</strong> : null}
                    <span>{user.email}</span>
                  </div>
                  <button type="button" role="menuitem" onClick={() => { setAccountMenuOpen(false); setMobileNavOpen(false); setActiveView("profile"); }}>
                    {t(language, "nav.profile")}
                  </button>
                  <button type="button" role="menuitem" className="is-logout" onClick={() => { setAccountMenuOpen(false); setMobileNavOpen(false); handleLogout(); }}>
                    {t(language, "auth.logout")}
                  </button>
                </div>
              )}
            </div>
          ) : !token ? (
            <button className="account-signin" type="button" onClick={() => { setMobileNavOpen(false); setActiveView("auth"); }}>
              {language === "en" ? "Sign in" : language === "uz" ? "Kirish" : "Войти"}
            </button>
          ) : null}

          <div className="topbar-meta">
            <div className="topbar-controls">
              {/* The rate ticker, left of the language control — the place the
                  customer pointed at (finko.uz). It used to sit in the CBU
                  strip on /market only. */}
              <TopbarFxTicker
                language={language}
                onOpen={() => { setActiveView("bankfx"); setMobileNavOpen(false); }}
              />

              {/* The panel is not a product section, so it stays out of the main
                  nav — but an administrator should not have to type the URL. The
                  label collapses to the icon on narrow widths, where the topbar
                  has no room to spare (see mobile.css §2). */}
              {user?.is_admin && (
                <button
                  className={`topbar-admin${activeView === "admin" ? " active" : ""}`}
                  type="button"
                  onClick={() => { setActiveView("admin"); setMobileNavOpen(false); }}
                  title={language === "en" ? "Admin panel" : language === "uz" ? "Admin paneli" : "Админ-панель"}
                  aria-label={language === "en" ? "Admin panel" : language === "uz" ? "Admin paneli" : "Админ-панель"}
                >
                  <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect width="7" height="9" x="3" y="3" rx="1" />
                    <rect width="7" height="5" x="14" y="3" rx="1" />
                    <rect width="7" height="9" x="14" y="12" rx="1" />
                    <rect width="7" height="5" x="3" y="16" rx="1" />
                  </svg>
                  <span>{language === "en" ? "Admin" : language === "uz" ? "Admin" : "Админка"}</span>
                </button>
              )}

              <label className="topbar-language">
                <select
                  id="languageSelect"
                  className="select-field"
                  value={language}
                  onChange={(event) => setLanguage(normalizeLanguage(event.target.value))}
                >
                  <option value="ru">RU</option>
                  <option value="en">EN</option>
                  <option value="uz">UZ</option>
                </select>
              </label>

              {/* Text size. Two buttons and the current percentage between them —
                  the number is there so a reader who has drifted from 100 % can
                  see it and click back, and so the control reads as a setting
                  rather than as a pair of mystery arrows. */}
              <div className="topbar-textsize" role="group"
                aria-label={language === "en" ? "Text size" : language === "uz" ? "Matn o'lchami" : "Размер шрифта"}>
                <button
                  type="button"
                  onClick={() => stepTextScale(-1)}
                  disabled={textScale === TEXT_SCALES[0]}
                  title={language === "en" ? "Smaller text" : language === "uz" ? "Matnni kichraytirish" : "Уменьшить шрифт"}
                  aria-label={language === "en" ? "Smaller text" : language === "uz" ? "Matnni kichraytirish" : "Уменьшить шрифт"}
                >A−</button>
                <button
                  type="button"
                  className="topbar-textsize-now"
                  onClick={() => setTextScale(100)}
                  disabled={textScale === 100}
                  title={language === "en" ? "Reset to 100%" : language === "uz" ? "100% ga qaytarish" : "Вернуть 100%"}
                >{textScale}%</button>
                <button
                  type="button"
                  onClick={() => stepTextScale(1)}
                  disabled={textScale === TEXT_SCALES[TEXT_SCALES.length - 1]}
                  title={language === "en" ? "Larger text" : language === "uz" ? "Matnni kattalashtirish" : "Увеличить шрифт"}
                  aria-label={language === "en" ? "Larger text" : language === "uz" ? "Matnni kattalashtirish" : "Увеличить шрифт"}
                >A+</button>
              </div>

              <button className="theme-toggle" type="button" onClick={toggleTheme} title={theme === "dark" ? t(language, "theme.light") : t(language, "theme.dark")}>
                <strong>{theme === "dark" ? "☀" : "☾"}</strong>
              </button>
            </div>
          </div>
        </header>

        <main className="content">{children}</main>

        <footer className="app-footer">
          <DisclaimerNote language={language} variant="footer" />
          {(activeView === "company" || activeView === "chart") && (
            <small className="app-chart-attribution">
              <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">
                Lightweight Charts™ © 2025 TradingView, Inc.
              </a>
            </small>
          )}
        </footer>
      </div>

      <ToastStack toasts={toasts} onDismiss={(id) => setToasts((current) => current.filter((item) => item.id !== id))} language={language} />
      {/* Keep staff tooling and authentication focused: a floating promotion
          must not cover findings or compete with credentials and recovery. */}
      {!["admin", "auth"].includes(activeView) && <SponsorOverlay language={language} />}
    </div>);
  return { render };
}
