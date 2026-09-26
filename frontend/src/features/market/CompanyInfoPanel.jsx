import { normalizeLanguage } from "../../shared/i18n.jsx";
import { useEffect, useRef } from "react";
import { sectorLabel } from "../../shared/marketCopy.jsx";
import { createPortal } from "react-dom";
import { CompanyLogo } from "../../shared/CompanyLogo.jsx";

function CompanyInfoPanel({ ticker, secInfo, wikiInfo, language, onClose, loading }) {
  const lang = normalizeLanguage(language);
  const panelRef = useRef(null);
  const closeRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!ticker) return undefined;

    // This drawer is rendered through a body portal below. Keep the page at the
    // row that opened it, move focus into the dialog, and return focus to that
    // row's info button when the drawer closes.
    const returnFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusFrame = window.requestAnimationFrame(() => closeRef.current?.focus());

    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current?.();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusable = [...panelRef.current.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )].filter((element) => !element.hasAttribute("hidden"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      if (returnFocus instanceof HTMLElement && returnFocus.isConnected) returnFocus.focus();
    };
  }, [ticker]);

  if (!ticker) return null;
  const name = secInfo?.name || ticker;
  const logo = secInfo?.logo_url;
  const sector = secInfo?.sector;
  const isin = secInfo?.isin;
  const isPreferred = secInfo?.is_preferred;
  const secType = secInfo?.type;

  const sectorText = sector ? sectorLabel(lang, sector) : null;
  const typeLabels = { stock: lang === "en" ? "Stock" : lang === "uz" ? "Aksiya" : "Акция", bond: lang === "en" ? "Bond" : lang === "uz" ? "Obligatsiya" : "Облигация" };
  const closeLabel = lang === "en" ? "Close company details" : lang === "uz" ? "Kompaniya ma'lumotlarini yopish" : "Закрыть сведения о компании";
  const titleId = `company-panel-title-${String(ticker).replace(/[^a-zA-Z0-9_-]/g, "-")}`;

  return createPortal(
    <div className="company-panel-overlay" onClick={onClose}>
      <aside
        ref={panelRef}
        className="company-info-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
      >
        <button ref={closeRef} className="company-panel-close" type="button" onClick={onClose} aria-label={closeLabel} title={closeLabel}>×</button>
        <div className="company-panel-header">
          <CompanyLogo logo={logo} name={name} ticker={ticker} />
          <div className="company-panel-title">
            <h2 id={titleId}>{name}</h2>
            <div className="company-panel-meta">
              <span className="status-badge muted">{ticker}</span>
              {isin && <span className="status-badge muted">{isin}</span>}
              {sectorText && <span className="status-badge">{sectorText}</span>}
              {secType && <span className="status-badge muted">{typeLabels[secType] || secType}</span>}
              {isPreferred && <span className="status-badge muted">{lang === "en" ? "Preferred" : lang === "uz" ? "Imtiyozli" : "Привилег."}</span>}
            </div>
          </div>
        </div>
        <div className="company-panel-body">
          {loading ? (
            <p className="company-panel-wiki muted">{lang === "en" ? "Loading..." : lang === "uz" ? "Yuklanmoqda..." : "Загрузка..."}</p>
          ) : wikiInfo?.extract ? (
            <>
              <p className="company-panel-wiki">{wikiInfo.extract}</p>
              {wikiInfo.page_url && (
                <a href={wikiInfo.page_url} target="_blank" rel="noreferrer" className="company-panel-wiki-link">
                  {wikiInfo.source === "wikipedia"
                    ? (lang === "en" ? "Read on Wikipedia →" : lang === "uz" ? "Vikipediyada o'qish →" : "Читать на Википедии →")
                    : (lang === "en" ? "Official website →" : lang === "uz" ? "Rasmiy sayt →" : "Официальный сайт →")}
                </a>
              )}
            </>
          ) : (
            <p className="company-panel-wiki muted">
              {lang === "en" ? "No description available." : lang === "uz" ? "Tavsif mavjud emas." : "Описание недоступно."}
            </p>
          )}
          {secInfo?.last_price != null && (
            <div className="company-panel-price">
              <span className="company-panel-price-label">{lang === "en" ? "Last price" : lang === "uz" ? "Oxirgi narx" : "Последняя цена"}</span>
              <strong className="company-panel-price-value">{Number(secInfo.last_price).toLocaleString(lang === "en" ? "en-US" : "ru-RU")} сум</strong>
              {secInfo.last_trade_date && <span className="muted">{secInfo.last_trade_date}</span>}
            </div>
          )}
        </div>
      </aside>
    </div>,
    document.body,
  );
}

export { CompanyInfoPanel };
