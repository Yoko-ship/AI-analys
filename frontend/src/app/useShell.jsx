import { NEWS_TX, NEWS_TABS } from "../features/news/index.js";
import { snapPixel } from "../lib/geometry.js";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMediaQuery } from "../shared/useMediaQuery.js";
import { rootZoom, zoomedViewport } from "../shared/viewport.jsx";
import { BrandIcon } from "../shared/BrandIcon.jsx";
import { clg, normalizeLanguage, t } from "../shared/i18n.jsx";
import { mt } from "../shared/marketCopy.jsx";
import { createPortal } from "react-dom";
import { ct } from "../features/research/index.js";
import { patternName } from "../lib/patterns.js";
import { accountInitials } from "../shared/accountIdentity.jsx";
import { TEXT_SCALES } from "./preferences.jsx";
import { DisclaimerNote } from "../shared/DisclaimerNote.jsx";
import { ToastStack } from "./toasts.jsx";
import { SponsorOverlay } from "./SponsorOverlay.jsx";

export function useShell({ session: sessionModule, preferences: preferencesModule, navigation: navigationModule, market: marketModule, notifications: notificationsModule, auth: authModule, toasts: toastsModule }) {
  const { token, user, canAccessCatalog } = sessionModule;
  const { language, setLanguage, stepTextScale, textScale, setTextScale, toggleTheme, theme } = preferencesModule;
  const { activeView, setActiveView, openNewsTab } = navigationModule;
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
  const drawerLayout = useMediaQuery('(max-width: 1180px)');
  const mobileNavRef = useRef(null);
  const burgerRef = useRef(null);

  useEffect(() => { if (!drawerLayout) setMobileNavOpen(false); }, [drawerLayout]);
  useLayoutEffect(() => {
    if (!drawerLayout || !mobileNavOpen) return undefined;
    const nav = mobileNavRef.current;
    const burger = burgerRef.current;
    const header = nav.closest('header');
    const background = [...header.children, ...header.parentElement.children]
      .filter(el => el !== header && el !== nav && el !== burger && !el.matches('.topbar-nav-scrim'));
    const previous = background.map(el => [el, el.inert]);
    previous.forEach(([el]) => { el.inert = true; });
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focusable = () => [burger, ...nav.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled)')]
      .filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
    focusable()[1]?.focus();
    const onKey = event => {
      if (event.key === 'Escape') { event.preventDefault(); setMobileNavOpen(false); }
      if (event.key !== 'Tab') return;
      const controls = focusable(), index = controls.indexOf(document.activeElement);
      if (index < 0 || (event.shiftKey && index === 0) || (!event.shiftKey && index === controls.length - 1)) {
        event.preventDefault();
        controls[event.shiftKey ? controls.length - 1 : 0]?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      previous.forEach(([el, inert]) => { el.inert = inert; });
      document.body.style.overflow = overflow;
      if (burger?.isConnected && burger.getClientRects().length) burger.focus();
    };
  }, [drawerLayout, mobileNavOpen]);

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

  const navItems = (token
    ? ["main", "market", "catalog", "news", "portfolio", "feedback", "profile"]
    : ["main", "market", "catalog", "news", "feedback"])
    .filter(key => key !== "catalog" || canAccessCatalog);

  // One hover drop-down open at a time: «Рынок» or «Новости».
  const [navMenu, setNavMenu] = useState(null);

  const [navMenuPos, setNavMenuPos] = useState(null);

  const navMenuWrapRefs = useRef({});

  const navMenuTimer = useRef(null);
  const navPanelRef = useRef(null);
  const pendingMenuFocus = useRef(null);

  useEffect(() => () => clearTimeout(navMenuTimer.current), []);

  const focusMenu = edge => {
    const items = navPanelRef.current?.querySelectorAll('[role="menuitem"]');
    (edge === 'last' ? items?.[items.length - 1] : items?.[0])?.focus();
  };
  useLayoutEffect(() => {
    if (navMenu && pendingMenuFocus.current) focusMenu(pendingMenuFocus.current);
    pendingMenuFocus.current = null;
  }, [navMenu]);

  const openNavMenu = (key, focus = null) => {
    if (drawerLayout) return;
    clearTimeout(navMenuTimer.current);
    pendingMenuFocus.current = focus;
    if (navMenu === key && focus) focusMenu(focus);
    const r = navMenuWrapRefs.current[key]?.getBoundingClientRect();
    if (r) {
      const z = rootZoom();
      setNavMenuPos({ top: r.bottom / z, left: r.left / z });
    }
    setNavMenu(key);
  };

  const closeNavMenuSoon = () => {
    if (navPanelRef.current?.contains(document.activeElement)) return;
    clearTimeout(navMenuTimer.current);
    navMenuTimer.current = setTimeout(() => setNavMenu(null), 140);
  };

  const closeNavMenu = () => {
    clearTimeout(navMenuTimer.current);
    setNavMenu(null);
  };
  const menuTriggerKey = (event, key) => {
    if (['ArrowDown', 'ArrowUp', ' '].includes(event.key) && !drawerLayout) {
      event.preventDefault(); openNavMenu(key, event.key === 'ArrowUp' ? 'last' : 'first');
    }
  };
  const menuKey = (event, key) => {
    const items = [...navPanelRef.current.querySelectorAll('[role="menuitem"]')];
    const current = items.indexOf(document.activeElement);
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
      : event.key === 'ArrowDown' ? (current + 1) % items.length
        : event.key === 'ArrowUp' ? (current - 1 + items.length) % items.length : null;
    if (index !== null) { event.preventDefault(); items[index]?.focus(); }
    if (event.key === 'Tab') {
      event.preventDefault();
      const trigger = navMenuWrapRefs.current[key]?.querySelector('.topbar-nav-btn');
      const controls = [...document.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled)')]
        .filter(el => !navPanelRef.current.contains(el) && !el.closest('[inert]') && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
      const next = controls[controls.indexOf(trigger) + 1];
      closeNavMenu(); (event.shiftKey ? trigger : next || trigger)?.focus();
    }
  };

  useEffect(() => {
    if (!navMenu) return undefined;
    if (drawerLayout) { setNavMenu(null); return undefined; }
    const close = () => { clearTimeout(navMenuTimer.current); setNavMenu(null); };
    const onKey = event => {
      if (event.key !== 'Escape') return;
      event.preventDefault(); close();
      navMenuWrapRefs.current[navMenu]?.querySelector('.topbar-nav-btn')?.focus();
    };
    const outside = event => {
      if (!navPanelRef.current?.contains(event.target) && !navMenuWrapRefs.current[navMenu]?.contains(event.target)) close();
    };
    window.addEventListener("scroll", close, { passive: true, capture: true });
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', outside);
    return () => {
      window.removeEventListener("scroll", close, { capture: true });
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', outside);
    };
  }, [navMenu, drawerLayout]);

  // Portaled to <body>, and clamped into the viewport once the width is known —
  // the trigger can sit far enough right (compact band, long translations) that
  // a left-anchored panel runs off-screen.
  const navMenuPanel = (key, columns) => navMenu === key && navMenuPos && createPortal(
    <div
      className="nav-dd-panel"
      role="menu"
      id={`header-menu-${key}`}
      aria-labelledby={`header-trigger-${key}`}
      onKeyDown={event => menuKey(event, key)}
      style={{ top: navMenuPos.top, left: navMenuPos.left }}
      ref={(el) => {
        navPanelRef.current = el;
        if (!el) return;
        const { vw } = zoomedViewport();
        el.style.left = `${Math.max(8, Math.min(navMenuPos.left, vw - el.offsetWidth - 8))}px`;
      }}
      onMouseEnter={() => openNavMenu(key)}
      onMouseLeave={closeNavMenuSoon}
    >
      {columns.map(({ head, items }) => (
        <div className="nav-dd-col" key={head}>
          <div className="nav-dd-head">{head}</div>
          {items.map(({ label, onSelect }) => (
            <button key={label} type="button" className="nav-dd-item" role="menuitem"
              onClick={() => { onSelect(); closeNavMenu(); }}>
              {label}
            </button>
          ))}
        </div>
      ))}
    </div>,
    document.body
  );

  const navDdLabel = (ru, uz, en) => (language === "en" ? en : language === "uz" ? uz : ru);

  const render = (children, overlay = null) => (<div className={`app-shell-wrap view-${activeView}`} data-build="2026-09-11.2" data-ui={["main", "market"].includes(activeView) ? undefined : "purple"}>
      <div className="bg-glow bg-glow-a" />
      <div className="bg-glow bg-glow-b" />

      <div className="app-shell">
        <header className={`topbar${mobileNavOpen ? " is-nav-open" : ""}`}>
          <button
            ref={burgerRef}
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
          <nav ref={mobileNavRef} className="topbar-nav" aria-label={navDdLabel('Основная навигация', 'Asosiy navigatsiya', 'Main navigation')}
            {...(drawerLayout && !mobileNavOpen ? {inert: '', 'aria-hidden': true} : {})}>
            {navItems.map((key) => key === "market" ? (
              <div
                key={key}
                className="nav-dd-wrap"
                ref={(el) => { navMenuWrapRefs.current.market = el; }}
                onMouseEnter={() => openNavMenu("market")}
                onMouseLeave={closeNavMenuSoon}
              >
                <button
                  className={`topbar-nav-btn ${activeView === key || activeView === "issuers" || activeView === "bankfx" || activeView === "heatmap" || activeView === "companyCompare" ? "active" : ""}`}
                  type="button"
                  id="header-trigger-market"
                  aria-haspopup={drawerLayout ? undefined : 'menu'}
                  aria-controls={drawerLayout ? undefined : 'header-menu-market'}
                  aria-expanded={drawerLayout ? undefined : navMenu === "market"}
                  onKeyDown={event => menuTriggerKey(event, 'market')}
                  onClick={event => { setActiveView("market"); setMobileNavOpen(false); if (drawerLayout) closeNavMenu(); else openNavMenu('market', event.detail === 0 ? 'first' : null); }}
                >
                  {mt(language, "nav")}
                  <span className="nav-dd-caret" aria-hidden="true">▾</span>
                </button>
                {navMenuPanel("market", [
                  { head: navDdLabel("Биржа", "Birja", "Exchange"), items: [
                    { label: navDdLabel("Биржевые инструменты", "Birja instrumentlari", "Exchange instruments"), onSelect: () => setActiveView("market") },
                    { label: navDdLabel("Карта рынка", "Bozor xaritasi", "Market map"), onSelect: () => setActiveView("heatmap") },
                    ...(canAccessCatalog ? [
                      { label: navDdLabel("Каталог компаний", "Kompaniyalar katalogi", "Company directory"), onSelect: () => setActiveView("issuers") },
                      { label: navDdLabel("Сравнение компаний", "Kompaniyalarni solishtirish", "Compare companies"), onSelect: () => setActiveView("companyCompare") },
                    ] : []),
                  ] },
                  { head: navDdLabel("Валюта", "Valyuta", "Currency"), items: [
                    { label: navDdLabel("Курсы валют в банках", "Banklarda valyuta kurslari", "Bank exchange rates"), onSelect: () => setActiveView("bankfx") },
                  ] },
                ])}
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
                {canAccessCatalog && <><button className="topbar-nav-btn nav-dd-mobile-item" type="button" onClick={() => {setActiveView('issuers');setMobileNavOpen(false);}}>{navDdLabel('Каталог компаний','Kompaniyalar katalogi','Company directory')}</button>
                <button
                  className="topbar-nav-btn nav-dd-mobile-item"
                  type="button"
                  onClick={() => { setActiveView("companyCompare"); setMobileNavOpen(false); }}
                >
                  {navDdLabel("Сравнение компаний", "Kompaniyalarni solishtirish", "Compare companies")}
                </button></>}
                <button
                  className="topbar-nav-btn nav-dd-mobile-item"
                  type="button"
                  onClick={() => { setActiveView("bankfx"); setMobileNavOpen(false); }}
                >
                  {navDdLabel("Курсы валют в банках", "Banklarda valyuta kurslari", "Bank exchange rates")}
                </button>
              </div>
            ) : key === "news" ? (
              <div
                key={key}
                className="nav-dd-wrap"
                ref={(el) => { navMenuWrapRefs.current.news = el; }}
                onMouseEnter={() => openNavMenu("news")}
                onMouseLeave={closeNavMenuSoon}
              >
                <button
                  className={`topbar-nav-btn ${["news", "newsArticle", "announcementArticle"].includes(activeView) ? "active" : ""}`}
                  type="button"
                  id="header-trigger-news"
                  aria-haspopup={drawerLayout ? undefined : 'menu'}
                  aria-controls={drawerLayout ? undefined : 'header-menu-news'}
                  aria-expanded={drawerLayout ? undefined : navMenu === "news"}
                  onKeyDown={event => menuTriggerKey(event, 'news')}
                  onClick={event => { openNewsTab("general"); setMobileNavOpen(false); if (drawerLayout) closeNavMenu(); else openNavMenu('news', event.detail === 0 ? 'first' : null); }}
                >
                  {t(language, "nav.news")}
                  <span className="nav-dd-caret" aria-hidden="true">▾</span>
                </button>
                {/* The menu groups reading sections before the events calendar. */}
                {navMenuPanel("news", [
                  { head: navDdLabel("Лента", "Lenta", "Feed"), items: NEWS_TABS.filter(tab => tab.section).map(tab => ({
                    label: (NEWS_TX[language] || NEWS_TX.ru).tabs[tab.key],
                    onSelect: () => openNewsTab(tab.key),
                  })) },
                  { head: navDdLabel("События", "Voqealar", "Events"), items: [
                    { label: navDdLabel("Календарь", "Taqvim", "Calendar"), onSelect: () => openNewsTab("calendar") },
                  ] },
                ])}
                <button
                  className="topbar-nav-btn nav-dd-mobile-item"
                  type="button"
                  onClick={() => { openNewsTab("calendar"); setMobileNavOpen(false); }}
                >
                  {navDdLabel("Календарь", "Taqvim", "Calendar")}
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

            {/* Phone only (mobile.css §2): a 390px topbar with «Войти» in it has
                no room left for A−/A+, so on a phone the text size lives here,
                at the foot of the drawer, instead of being pushed off-screen. */}
            <div className="topbar-nav-textsize">
              <span>{language === "en" ? "Text size" : language === "uz" ? "Matn o'lchami" : "Размер шрифта"}</span>
              <div className="topbar-textsize" role="group"
                aria-label={language === "en" ? "Text size" : language === "uz" ? "Matn o'lchami" : "Размер шрифта"}>
                <button type="button" onClick={() => stepTextScale(-1)} disabled={textScale === TEXT_SCALES[0]}
                  aria-label={language === "en" ? "Smaller text" : language === "uz" ? "Matnni kichraytirish" : "Уменьшить шрифт"}>A−</button>
                <button type="button" className="topbar-textsize-now" onClick={() => setTextScale(100)} disabled={textScale === 100}
                  title={language === "en" ? "Reset to 100%" : language === "uz" ? "100% ga qaytarish" : "Вернуть 100%"}>{textScale}%</button>
                <button type="button" onClick={() => stepTextScale(1)} disabled={textScale === TEXT_SCALES[TEXT_SCALES.length - 1]}
                  aria-label={language === "en" ? "Larger text" : language === "uz" ? "Matnni kattalashtirish" : "Увеличить шрифт"}>A+</button>
              </div>
            </div>
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
                  <button type="button" role="menuitem" onClick={() => { setAccountMenuOpen(false); setActiveView("portfolio"); }}>{navDdLabel("Портфель", "Portfel", "Portfolio")}</button>
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
      {overlay}
    </div>);
  return { render };
}
