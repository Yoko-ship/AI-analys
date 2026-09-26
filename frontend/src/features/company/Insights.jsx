import React, { Suspense } from "react";
import { ReportAvailability, VerifiedReport } from "../../shared/VerifiedReport.jsx";
import { createPortal } from "react-dom";

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

function companyInsightTeaser(report, lang) {
  if (!report) return "";
  const rows = Object.values(report.replacement_blocks || {}).flatMap((items) => Array.isArray(items) ? items : []);
  const candidates = ["revenue", "operating_income", "net_income"];
  const labels = {
    revenue: ["выручка", "tushum", "revenue"],
    operating_income: ["операционная прибыль", "operatsion foyda", "operating profit"],
    net_income: ["чистая прибыль", "sof foyda", "net profit"],
  };
  const languageIndex = lang === "uz" ? 1 : lang === "en" ? 2 : 0;
  const comparable = candidates.map((code) => rows.find((row) => row.metric_code === code))
    .filter((row) => Number.isFinite(Number(row?.change_pct)))
    .slice(0, 2);
  if (comparable.length) {
    const movement = Object.fromEntries(comparable.map((row) => [row.metric_code, Number(row.change_pct)]));
    let thesis;
    if (movement.revenue > 0 && (movement.operating_income < 0 || movement.net_income < 0)) {
      if (movement.operating_income < 0) {
        thesis = [
          "рост выручки при падении операционной прибыли указывает на сжатие маржи и ухудшение эффективности",
          "tushum o‘sib, operatsion foyda pasayishi marja qisqarishi va samaradorlik yomonlashganini ko‘rsatadi",
          "revenue growth alongside falling operating profit indicates margin compression and weaker efficiency",
        ][languageIndex];
      } else {
        thesis = [
          "рост выручки при падении чистой прибыли указывает на снижение чистой маржи и качества результата",
          "tushum o‘sib, sof foyda pasayishi sof marja va natija sifati yomonlashganini ko‘rsatadi",
          "revenue growth alongside falling net profit indicates lower net margins and weaker earnings quality",
        ][languageIndex];
      }
    } else if (comparable.length >= 2 && comparable.every((row) => Number(row.change_pct) >= 0)) {
      thesis = [
        "доходы и прибыль растут — финансовая динамика положительная",
        "daromad va foyda o‘smoqda — moliyaviy dinamika ijobiy",
        "income and profit are growing — financial momentum is positive",
      ][languageIndex];
    } else if (comparable.length >= 2 && comparable.every((row) => Number(row.change_pct) < 0)) {
      thesis = [
        "доходы и прибыль снижаются — финансовые результаты ослабевают",
        "daromad va foyda pasaymoqda — moliyaviy natijalar zaiflashmoqda",
        "income and profit are declining — financial performance is weakening",
      ][languageIndex];
    } else if (comparable.length >= 2) {
      thesis = [
        "ключевые показатели разнонаправленные — устойчивого улучшения пока нет",
        "asosiy ko‘rsatkichlar turli yo‘nalishda — barqaror yaxshilanish hali yo‘q",
        "key metrics are mixed — there is no sustained improvement yet",
      ][languageIndex];
    } else {
      const row = comparable[0];
      const labelText = labels[row.metric_code][languageIndex];
      const rising = Number(row.change_pct) >= 0;
      thesis = [
        `${labelText} ${rising ? "растёт" : "снижается"} — это главный подтверждённый сигнал периода`,
        `${labelText} ${rising ? "o‘smoqda" : "pasaymoqda"} — bu davrning asosiy tasdiqlangan signali`,
        `${labelText} is ${rising ? "growing" : "declining"} — the period’s main verified signal`,
      ][languageIndex];
    }
    const detailedTeaser = `${report.issuer?.ticker || ""}: ${thesis}.`.trim();
    const detailedWords = detailedTeaser.split(/\s+/).filter(Boolean);
    return detailedWords.length > 18
      ? `${detailedWords.slice(0, 18).join(" ").replace(/[\s,;:]+$/, "")}…`
      : detailedTeaser;
  }
  const teaser = report.card_text || report.short_summary || report.headline || "";
  const words = String(teaser).trim().split(/\s+/).filter(Boolean);
  return words.length > 22 ? `${words.slice(0, 22).join(" ").replace(/[\s,;:]+$/, "")}…` : teaser;
}

function CompanyInsightCard({ report, loading, error, onOpen, onRetry, buttonRef, lang }) {
  const tx = COMPANY_INSIGHT_TX[lang] || COMPANY_INSIGHT_TX.ru;
  const teaser = companyInsightTeaser(report, lang);
  const isReadable = report && ["available", "stale"].includes(report.status);
  return (
    <section className={`company-insight-card tone-${report?.headline_tone || "neutral"}`} data-testid="company-insight-card" aria-live="polite" aria-busy={loading ? "true" : "false"}>
      <CompanyInsightIcon />
      <div className="company-insight-card-copy">
        {loading ? (
          <p className="muted">{tx.loading}</p>
        ) : report?.status && !isReadable && !error ? (
          <Suspense fallback={null}><ReportAvailability report={report} lang={lang} /></Suspense>
        ) : (
          <p>{error ? tx.unavailable : teaser}</p>
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
          <button ref={closeRef} className="company-insight-close" type="button" onClick={onClose} aria-label={tx.close}>×</button>
          <CompanyInsightIcon />
          <div>
            <div className="company-insight-eyebrow">{report.standard?.toUpperCase()} · {report.period_label || report.period || "—"}</div>
            <h2 id={titleId}>{tx.title} {ticker}</h2>
            <p>{companyName}</p>
          </div>
        </header>
        {report.content_status === "shortened" && <div className="company-insight-status">{tx.shortened}</div>}
        {sources.length > 0 && (
          <section className="company-insight-sources" aria-label={tx.sources}>
            <h3>{tx.sources}</h3>
            <div>
              {sources.map((source, index) => {
                const label = `${tx.source} ${report.standard?.toUpperCase() || ""} · ${source.period || report.period || "—"}`;
                return source.url ? (
                  <a key={source.document_id || source.url || index} href={source.url} target="_blank" rel="noreferrer">{label} ↗</a>
                ) : <span key={source.document_id || index}>{label}</span>;
              })}
            </div>
          </section>
        )}
        <div id={bodyId} className="company-insight-report-copy">
          {report.abstract && !report.task1_sections?.length && <aside className="company-insight-abstract"><span>{lang === "ru" ? "Аннотация" : lang === "uz" ? "Annotatsiya" : "Abstract"}</span><p>{companyInsightTeaser(report, lang)}</p></aside>}
          {narrativeSections.map((section, index) => (
            <section className="company-insight-report-section" key={section.id || index}>
              {section.title && <header><span>{section.number || String(index + 1).padStart(2, "0")}</span><h3>{section.title}</h3></header>}
              {section.blocks?.length ? section.blocks.map((block, blockIndex) => (
                <p key={`${section.id || index}-block-${blockIndex}`}>
                  {block.lead && <><strong>{block.lead.replace(/[.!?]+$/, "")}.</strong>{" "}</>}
                  {block.text}
                </p>
              )) : <p>{section.text}</p>}
            </section>
          ))}
        </div>
        <Suspense fallback={null}><VerifiedReport report={report} lang={lang} /></Suspense>
        <footer className="company-insight-dialog-foot">
          <span><CompanyInsightIcon small />{tx.generated}</span>
          <p>{tx.disclaimer}</p>
        </footer>
      </article>
    </div>
  ), document.body);
}

export { CompanyInsightCard, CompanyInsightDialog };
