import React from 'react';
import { createPortal } from 'react-dom';
import { CompanyLogo } from '../../shared/CompanyLogo.jsx';
import { CompanyPreviewCard } from './CompanyPreviewCard.jsx';
import './companyPreview.css';

const PreviewContext = React.createContext(null);
const previewLabel = (lang, ticker) => `${lang === 'en' ? 'Company preview' : lang === 'uz' ? 'Kompaniya haqida' : 'Обзор компании'} ${ticker}`;

export function CompanyPreviewProvider({ enabled = false, children, ...props }) {
  // Unmount preview state, timers and requests when administrator access ends.
  return enabled ? <ActiveCompanyPreviewProvider {...props}>{children}</ActiveCompanyPreviewProvider>
    : <PreviewContext.Provider value={null}>{children}</PreviewContext.Provider>;
}

function ActiveCompanyPreviewProvider({ lang, changePeriod, onOpenCompany, children }) {
  const [active, setActive] = React.useState(null);
  const [position, setPosition] = React.useState(null);
  const panel = React.useRef(null), activeRef = React.useRef(null);
  const timer = React.useRef(null), cache = React.useRef(new Map());
  const suppressFocus = React.useRef(false);
  const id = React.useId();
  const cancelTimer = React.useCallback(() => clearTimeout(timer.current), []);
  const close = React.useCallback((restoreFocus = false) => {
    cancelTimer();
    const anchor = activeRef.current?.anchor;
    activeRef.current = null;
    setActive(null);
    if (restoreFocus && anchor?.isConnected) {
      suppressFocus.current = true;
      anchor.focus({ preventScroll: true });
      suppressFocus.current = false;
    }
  }, [cancelTimer]);
  const show = (item, immediate = false, focus = false) => {
    cancelTimer();
    if (suppressFocus.current) return;
    const open = () => {
      if (!item.anchor.isConnected) return;
      activeRef.current = item;
      setPosition(null);
      setActive({ ...item, focus });
    };
    if (immediate) open();
    else timer.current = setTimeout(open, 240);
  };
  const leave = () => {
    cancelTimer();
    timer.current = setTimeout(() => {
      const focused = document.activeElement;
      if (!panel.current?.contains(focused) && focused !== activeRef.current?.anchor) close();
    }, 180);
  };

  React.useEffect(() => {
    const entries = cache.current;
    return () => { cancelTimer(); entries.forEach(entry => entry.controller.abort()); };
  }, [cancelTimer]);

  React.useLayoutEffect(() => {
    if (!active) return undefined;
    const element = panel.current;
    const place = () => {
      if (!active.anchor.isConnected) { close(); return; }
      const box = active.anchor.getBoundingClientRect(), card = element.getBoundingClientRect();
      const margin = 8, gap = 10, vw = window.innerWidth, vh = window.innerHeight;
      // Prefer beside the logo, where the pointer can travel straight into the
      // card. Narrow screens place it above/below and clamp both dimensions.
      let left = box.right + gap;
      let top = box.top - 12;
      if (left + card.width > vw - margin) {
        left = box.left - card.width - gap;
        if (left < margin) {
          left = margin;
          top = box.top >= card.height + gap + margin ? box.top - card.height - gap : box.bottom + gap;
        }
      }
      setPosition({ left: Math.max(margin, Math.min(left, vw - card.width - margin)),
        top: Math.max(margin, Math.min(top, vh - card.height - margin)) });
    };
    place();
    const observer = new ResizeObserver(place);
    observer.observe(element);
    const onScroll = event => {
      if (element.contains(event.target)) return;
      const box = active.anchor.getBoundingClientRect();
      // Tabbing to a logo below the fold scrolls it into view. Keep its newly
      // opened preview attached instead of dismissing it on that same scroll.
      if (document.activeElement === active.anchor && box.bottom > 0 && box.top < window.innerHeight
        && box.right > 0 && box.left < window.innerWidth) place();
      else close();
    };
    const onOutside = event => { if (!element.contains(event.target) && !active.anchor.contains(event.target)) close(); };
    const onKey = event => {
      if (event.key === 'Escape') { event.preventDefault(); close(true); }
    };
    window.addEventListener('resize', place);
    window.addEventListener('scroll', onScroll, true);
    document.addEventListener('pointerdown', onOutside);
    document.addEventListener('keydown', onKey);
    // The first layout pass positions a hidden card. Focus only after that
    // position has committed; browsers cannot focus an invisible link.
    const focusFrame = active.focus ? requestAnimationFrame(() => {
      element.querySelector('[data-preview-primary]')?.focus({ preventScroll: true });
    }) : null;
    return () => {
      if (focusFrame != null) cancelAnimationFrame(focusFrame);
      observer.disconnect();
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', onScroll, true);
      document.removeEventListener('pointerdown', onOutside);
      document.removeEventListener('keydown', onKey);
    };
  }, [active, close]);

  return <PreviewContext.Provider value={{ active, id, lang, show, leave, close, panel }}>
    {children}
    {active && createPortal(<section ref={panel} id={id} className="company-preview" role="dialog" aria-modal="false"
      aria-label={previewLabel(lang, active.row.ticker)} style={{ ...position, visibility: position ? 'visible' : 'hidden' }}
      onPointerEnter={cancelTimer} onPointerLeave={leave} onFocus={cancelTimer}
      onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget) && event.relatedTarget !== active.anchor) close();
      }}>
      <CompanyPreviewCard key={active.row.ticker} item={active} lang={lang} changePeriod={changePeriod}
        cache={cache.current} onClose={() => close(true)} onOpenCompany={onOpenCompany} />
    </section>, document.body)}
  </PreviewContext.Provider>;
}

export function CompanyPreviewLogo({ row, security }) {
  const ctx = React.useContext(PreviewContext);
  const triggerId = React.useId();
  if (!ctx) return <CompanyLogo logo={security.logo_url} name="" ticker={row.ticker} />;
  const item = anchor => ({ row, security, anchor, triggerId });
  const open = ctx.active?.triggerId === triggerId;
  return <button type="button" className="company-preview-trigger" aria-label={previewLabel(ctx.lang, row.ticker)}
    aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? ctx.id : undefined}
    onPointerEnter={event => { if (event.pointerType !== 'touch') ctx.show(item(event.currentTarget)); }}
    onPointerLeave={ctx.leave}
    onFocus={event => ctx.show(item(event.currentTarget), true)}
    onBlur={event => { if (!ctx.panel.current?.contains(event.relatedTarget)) ctx.leave(); }}
    onClick={event => ctx.show(item(event.currentTarget), true, true)}
    onKeyDown={event => {
      if (event.key === 'ArrowDown' || (event.key === 'Tab' && !event.shiftKey && open)) {
        event.preventDefault(); ctx.show(item(event.currentTarget), true, true);
      }
    }}>
    <CompanyLogo logo={security.logo_url} name="" ticker={row.ticker} />
  </button>;
}
