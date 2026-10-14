import { safeHref } from "../../lib/safeHref.js";
import React, { Suspense } from "react";
import { ReportAvailability, VerifiedReport } from "../../shared/VerifiedReport.jsx";
import { createPortal } from "react-dom";
import { SharePanel, ShareIcon, canShareNatively, shareNatively } from "./Share.jsx";
import { localizedPath } from "../../lib/languagePath.js";

const COMPANY_INSIGHT_TX = {
  ru: {
    details: "Открыть полный анализ",
    retry: "Повторить",
    unavailable: "Краткий AI-вывод сейчас недоступен.",
    loading: "Формируем краткий финансовый вывод…",
    title: "AI-финансовый отчёт",
    close: "Закрыть AI-финансовый отчёт",
    sources: "Источники отчёта",
    source: "Финансовая отчётность",
    generated: "Сформировано AI",
    shortened: "Сокращённый отчёт",
    disclaimer: "Материал основан на публичной отчётности, носит информационный характер и не является инвестиционной рекомендацией.",
    share: "Поделиться отчётом",
  },
  uz: {
    details: "To‘liq tahlilni ochish",
    retry: "Qayta urinish",
    unavailable: "Qisqa AI xulosasi hozir mavjud emas.",
    loading: "Qisqa moliyaviy xulosa tayyorlanmoqda…",
    title: "AI moliyaviy hisobot",
    close: "AI moliyaviy hisobotini yopish",
    sources: "Hisobot manbalari",
    source: "Moliyaviy hisobot",
    generated: "AI yordamida tayyorlandi",
    shortened: "Qisqartirilgan hisobot",
    disclaimer: "Material ochiq moliyaviy hisobotlarga asoslangan, faqat ma’lumot uchun berilgan va investitsiya tavsiyasi emas.",
    share: "Hisobotni ulashish",
  },
  en: {
    details: "Open full analysis",
    retry: "Retry",
    unavailable: "The short AI insight is currently unavailable.",
    loading: "Preparing a short financial insight…",
    title: "AI financial report",
    close: "Close AI financial report",
    sources: "Report sources",
    source: "Financial statement",
    generated: "Generated with AI",
    shortened: "Shortened report",
    disclaimer: "This material is based on public filings, is for information only, and is not investment advice.",
    share: "Share report",
  },
};

function CompanyInsightIcon({ small = false }) {
  const gradientId = `company-ai-${React.useId().replaceAll(":", "")}`;
  return (
    <svg className={`company-insight-icon ${small ? "small" : ""}`} viewBox="0 0 24 24" aria-hidden="true">
      <defs>
        <linearGradient id={gradientId} x1="12" y1="1" x2="12" y2="23" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#f8d34a" />
          <stop offset=".42" stopColor="#ef6952" />
          <stop offset=".76" stopColor="#8b4be3" />
          <stop offset="1" stopColor="#6530a4" />
        </linearGradient>
      </defs>
      <path d="M12 2.2c-2.25 1.18-3.8 3.85-3.8 6.73v6.42h7.6V8.93c0-2.88-1.55-5.55-3.8-6.73Z" fill="none" stroke={`url(#${gradientId})`} strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M8.2 9.25 5.7 11.5a4.4 4.4 0 0 0-1.22 4.55l.22.68h3.5M15.8 9.25l2.5 2.25a4.4 4.4 0 0 1 1.22 4.55l-.22.68h-3.5M9.65 19.05c.45 1.35 1.32 2.22 2.35 2.75 1.03-.53 1.9-1.4 2.35-2.75" fill="none" stroke={`url(#${gradientId})`} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="9" r="1.1" fill={`url(#${gradientId})`} />
    </svg>
  );
}

// The card is the analysis's own first line: one headline sentence and the
// verdict with its reason, exactly as the server wrote them. The page does not
// compose a second wording of the result from the figures.
function companyInsightTeaser(report) {
  if (!report) return { headline: "", verdict: "" };
  const verdict = report.verdict_line || "";
  const card = report.card_text || report.short_summary || report.headline || "";
  const headline = verdict && card.endsWith(verdict) ? card.slice(0, card.length - verdict.length).trim() : card;
  return { headline, verdict };
}

function CompanyInsightCard({ report, loading, error, onOpen, onRetry, buttonRef, lang }) {
  const tx = COMPANY_INSIGHT_TX[lang] || COMPANY_INSIGHT_TX.ru;
  const teaser = companyInsightTeaser(report);
  const isReadable = report && ["available", "stale"].includes(report.status);
  return (
    <section className={`company-insight-card tone-${report?.headline_tone || "neutral"}`} data-testid="company-insight-card" aria-live="polite" aria-busy={loading ? "true" : "false"}>
      <CompanyInsightIcon />
      <div className="company-insight-card-copy">
        {loading ? (
          <p className="muted">{tx.loading}</p>
        ) : report?.status && !isReadable && !error ? (
          <Suspense fallback={null}><ReportAvailability report={report} lang={lang} /></Suspense>
        ) : error ? (
          <p>{tx.unavailable}</p>
        ) : (
          <>
            <p>{teaser.headline}</p>
            {teaser.verdict && <p className="company-insight-verdict">{teaser.verdict}</p>}
          </>
        )}
      </div>
      {!loading && error && (
        <button className="company-insight-action" type="button" onClick={onRetry}>{tx.retry}</button>
      )}
      {!loading && !error && isReadable && (report.deferred_full_report || report.paragraphs?.length > 0) && (
        <button ref={buttonRef} className="company-insight-action" type="button" onClick={onOpen}>{tx.details}</button>
      )}
    </section>
  );
}

function CompanyInsightDialog({ report, ticker, companyName, lang, onClose }) {
  const tx = COMPANY_INSIGHT_TX[lang] || COMPANY_INSIGHT_TX.ru;
  const dialogRef = React.useRef(null);
  const closeRef = React.useRef(null);
  const titleId = `company-insight-title-${String(ticker || "company").replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const bodyId = `${titleId}-body`;
  const shareId = `${titleId}-share`;
  const [shareOpen, setShareOpen] = React.useState(false);
  // The link opens this same report, in the language it is read in: CompanyPage
  // reads ?report=ai on load, the /uz prefix opens it in Uzbek.
  const shareUrl = `${window.location.origin}${localizedPath(`/company/${encodeURIComponent(ticker)}`, lang)}?report=ai`;
  const shareTitle = `${tx.title} ${ticker} | UZStock`;
  const shareText = [`${tx.title} ${ticker}`, companyInsightTeaser(report).headline || report?.headline].filter(Boolean).join(": ");
  const openShare = () => {
    // A phone's own share sheet reaches every messenger, Instagram included;
    // a desktop gets the panel of links.
    if (canShareNatively() && window.matchMedia?.("(pointer: coarse)").matches) {
      shareNatively({ url: shareUrl, title: shareTitle, text: shareText }).then((done) => { if (!done) setShareOpen(true); });
      return;
    }
    setShareOpen((value) => !value);
  };
  const sources = React.useMemo(() => {
    const seen = new Set();
    return (report?.number_references || []).reduce((items, ref) => {
      const source = ref?.source || {};
      const key = source.document_id || source.url;
      if (!key || seen.has(key)) return items;
      seen.add(key);
      items.push({ ...source, period: ref.period });
      return items;
    }, []);
  }, [report]);
  const narrativeSections = report?.task1_sections?.length
    ? report.task1_sections
    : report?.sections?.length
      ? report.sections
      : (report?.paragraphs || []).map((text, index) => ({ id: `section-${index}`, text }));

  React.useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const handleKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll('button:not([disabled]), a[href], summary, [tabindex]:not([tabindex="-1"])')].filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  return createPortal((
    <div className="company-insight-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <article ref={dialogRef} className="company-insight-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={bodyId}>
        <header className="company-insight-dialog-head">
          <button className="company-insight-close company-insight-share" type="button" onClick={openShare}
            aria-label={tx.share} title={tx.share} aria-expanded={shareOpen} aria-controls={shareId}><ShareIcon /></button>
          <button ref={closeRef} className="company-insight-close" type="button" onClick={onClose} aria-label={tx.close}>×</button>
          <CompanyInsightIcon />
          <div>
            <div className="company-insight-eyebrow">{report.standard?.toUpperCase()} · {report.period_label || report.period || "—"}</div>
            <h2 id={titleId}>{tx.title} {ticker}</h2>
            <p>{companyName}</p>
          </div>
        </header>
        {shareOpen && <SharePanel id={shareId} url={shareUrl} title={shareTitle} text={shareText} lang={lang} />}
        {report.content_status === "shortened" && <div className="company-insight-status">{tx.shortened}</div>}
        {sources.length > 0 && (
          <section className="company-insight-sources" aria-label={tx.sources}>
            <h3>{tx.sources}</h3>
            <div>
              {sources.map((source, index) => {
                const label = `${tx.source} ${report.standard?.toUpperCase() || ""} · ${source.period || report.period || "—"}`;
                return source.url ? (
                  <a key={source.document_id || source.url || index} href={safeHref(source.url)} target="_blank" rel="noreferrer">{label} ↗</a>
                ) : <span key={source.document_id || index}>{label}</span>;
              })}
            </div>
          </section>
        )}
        <div id={bodyId} className="company-insight-report-copy">
          {narrativeSections.map((section, index) => (
            <section className={`company-insight-report-section${section.style ? ` is-${section.style}` : ""}`} key={section.id || index}>
              {section.title && <header><span>{section.number || String(index + 1).padStart(2, "0")}</span><h3>{section.title}</h3></header>}
              {section.style === "list" ? (
                <ul>{section.blocks.map((block, blockIndex) => <li key={`${section.id || index}-item-${blockIndex}`}>{block.text}</li>)}</ul>
              ) : section.style === "footnote" ? (
                <p><em>{section.text}</em></p>
              ) : section.blocks?.length ? section.blocks.map((block, blockIndex) => (
                <p key={`${section.id || index}-block-${blockIndex}`} className={block.style === "verdict" ? "company-insight-verdict" : undefined}>
                  {block.lead && <><strong>{block.lead.replace(/[.!?]+$/, "")}.</strong>{" "}</>}
                  {block.text}
                </p>
              )) : <p>{section.text}</p>}
            </section>
          ))}
        </div>
        <Suspense fallback={null}><VerifiedReport report={report} lang={lang} withCommentary={false} /></Suspense>
        <footer className="company-insight-dialog-foot">
          <span><CompanyInsightIcon small />{tx.generated}</span>
          <p>{tx.disclaimer}</p>
        </footer>
      </article>
    </div>
  ), document.body);
}

export { CompanyInsightCard, CompanyInsightDialog };
