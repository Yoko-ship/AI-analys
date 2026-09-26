import React from "react";
import { reportFormLabel } from "../../lib/reportPresentation.js";
import { createPortal } from "react-dom";
import { formatCompactVolume } from "../../shared/marketModel.jsx";
import { finLabel } from "../../shared/financialLabels.jsx";
import { formatMarketNumber, formatRatio } from "../../shared/format.jsx";

// ЛЕНТА СОБЫТИЙ ПО БУМАГАМ. /api/news has served a dated timeline of real market
// events — filings, listings, delistings — since the §3.2 work, and no page ever
// read it: it was built and left invisible while the News section grew out of the
// separate editorial module. This is that timeline.
//
// It lives on the «Корпоративные» tab of the news section (it stood under the
// board until 2026-08-20): a filing IS corporate news, and that is the page a
// reader looking for one opens.
//
// Every row is dated by the ISSUER's own publication date and OPENS the
// document, so it is a way INTO the filing rather than a note that one exists.
function MarketEventsFeed({ lang, onOpenCompany }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const [items, setItems] = React.useState(null);
  const [kind, setKind] = React.useState("all");
  const [expanded, setExpanded] = React.useState(false);
  const [detail, setDetail] = React.useState(null);

  React.useEffect(() => {
    let alive = true;
    fetch("/api/news?limit=120&days=365")
      .then((r) => r.json())
      .then((d) => { if (alive) setItems(d && d.ok ? (d.items || []) : []); })
      .catch(() => { if (alive) setItems([]); });
    return () => { alive = false; };
  }, []);

  if (items === null) return null;

  const KINDS = [
    ["all", t("Все", "Barchasi", "All")],
    ["report", t("Отчётность", "Hisobot", "Filings")],
    ["listing", t("Листинги", "Listinglar", "Listings")],
    ["delisting", t("Делистинг", "Delisting", "Delisting")],
  ];
  const counts = items.reduce((acc, i) => ({ ...acc, [i.type]: (acc[i.type] || 0) + 1 }), {});
  const shown = kind === "all" ? items : items.filter((i) => i.type === kind);
  if (items.length === 0) return null;
  const visible = expanded ? shown.slice(0, 120) : shown.slice(0, 12);

  const day = (d) => {
    const s = String(d || "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return "";
    const [y, m, dd] = s.split("-");
    return `${dd}.${m}.${y}`;
  };
  // The period a filing covers, said the way the reader asked for it elsewhere on
  // the site: «2025 · год» / «2026 · II кв.».
  const period = (i) => {
    if (!i.year) return "";
    if (i.quarter) {
      const roman = ["", "I", "II", "III", "IV"][i.quarter] || i.quarter;
      return `${i.year} · ${roman} ${t("кв.", "chorak", "Q")}`;
    }
    return `${i.year} · ${t("год", "yil", "FY")}`;
  };
  // The row opens the event ON THIS SITE. It used to hand the reader straight to
  // openinfo's PDF — the source is the source, but a click on a row in OUR
  // timeline should first say what the event is in our own terms: who filed it,
  // for which period, and what that filing put into our database. The document
  // stays one click away, from the row and from the detail alike.
  const openHint = () => t("Подробнее о событии", "Hodisa haqida batafsil", "Event details");

  // The filing's form, in the reader's language — the headline and the event's
  // own detail must not disagree over whether it is «НСБУ» or «NSBU».
  const formLabel = (raw) => (["NSBU", "MSFO", "Audition"].includes(raw)
    ? reportFormLabel(raw, lang)
    : raw === "Audit" ? t("Аудиторское заключение", "Auditor xulosasi", "Auditor's report") : raw);
  const headline = (i) => {
    if (i.type === "report") {
      return `${t("Опубликована отчётность", "Hisobot e'lon qilindi", "Filing published")} · ${formLabel(i.report_form)}`;
    }
    if (i.type === "listing") return t("Допуск к торгам", "Savdoga qo'yildi", "Admitted to trading");
    return t("Нет сделок более 60 дней", "60 kundan ortiq bitimsiz", "No trades for over 60 days");
  };

  return (
    <article className="panel market-events">
      <div className="market-events-head">
        <div>
          <div className="panel-label">{t("Биржевые события", "Birja hodisalari", "Market events")}</div>
          <h2>{t("Лента событий по бумагам", "Qog'ozlar bo'yicha hodisalar lentasi", "Securities events feed")}</h2>
        </div>
        <div className="market-events-kinds">
          {KINDS.map(([k, label]) => (
            <button key={k} type="button"
              className={`sector-chip${kind === k ? " active" : ""}`}
              aria-pressed={kind === k}
              onClick={() => { setKind(k); setExpanded(false); }}>
              {label}
              {k !== "all" && counts[k] ? ` (${counts[k]})` : ""}
            </button>
          ))}
        </div>
      </div>
      <ul className="market-events-list">
        {visible.map((i, index) => (
          <li key={`${i.type}-${i.ticker}-${i.date}-${i.year || ""}-${i.quarter || ""}-${index}`}
            className={`market-events-row ev-${i.type} is-openable`}
            role="link"
            tabIndex={0}
            title={openHint()}
            onClick={() => setDetail(i)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setDetail(i); }
            }}>
            <time className="ev-date">{day(i.date)}</time>
            <button type="button" className="ev-ticker"
              onClick={(e) => { e.stopPropagation(); if (onOpenCompany) onOpenCompany(i.ticker); }}>{i.ticker}</button>
            <span className="ev-what">
              <span className="ev-headline">{headline(i)}</span>
              {period(i) ? <span className="ev-period">{period(i)}</span> : null}
              <span className="ev-company">{i.company}</span>
            </span>
            {/* The document, where the source published one. NSBU quarterlies carry
                both forms in one workbook, so one link is the whole filing. */}
            <span className="ev-links" onClick={(e) => e.stopPropagation()}>
              {i.pdf_url && (
                <a href={i.pdf_url} target="_blank" rel="noopener noreferrer">PDF</a>
              )}
              {i.excel_url && (
                <a href={i.excel_url} target="_blank" rel="noopener noreferrer">XLS</a>
              )}
            </span>
          </li>
        ))}
      </ul>
      {shown.length > visible.length && (
        <button type="button" className="market-events-more" onClick={() => setExpanded(true)}>
          {t(`Показать все ${shown.length}`, `Barchasini ko'rsatish (${shown.length})`,
             `Show all ${shown.length}`)}
        </button>
      )}
      <p className="fin-note muted">
        {t("События по данным биржи и openinfo.uz. Дата — дата публикации эмитентом, не дата нашей загрузки.",
           "Hodisalar birja va openinfo.uz ma'lumotlari bo'yicha. Sana — emitent e'lon qilgan sana.",
           "Events from the exchange and openinfo.uz. The date is the issuer's publication date, not the date we ingested it.")}
      </p>
      {detail && (
        <MarketEventDetail
          item={detail}
          lang={lang}
          headline={headline(detail)}
          period={period(detail)}
          day={day(detail.date)}
          form={formLabel(detail.report_form)}
          onClose={() => setDetail(null)}
          onOpenCompany={onOpenCompany}
        />
      )}
    </article>
  );
}

// The lines a filing puts on the page, in the order the Финансы tab reads them:
// what came in, what was left of it, and what the balance says at the period's end.
const EVENT_DETAIL_ROWS = [
  "net_revenue", "gross_profit", "operating_income", "net_profit",
  "total_assets", "total_liabilities", "total_equity",
];

// ОДНО СОБЫТИЕ, НА НАШЕЙ СТОРОНЕ. A dialog rather than a route: an event has no
// id of its own — it is identified by issuer, kind and period together — so
// there is no honest URL to give it, and the reader keeps their place in the
// timeline.
//
// For a filing it answers the question the row raises: the period stated in
// full, and the figures THIS period holds in our database, read from the same
// series the Финансы tab draws. The source documents are offered at the bottom,
// named as sources — which is what they are.
function MarketEventDetail({ item, lang, headline, period, day, form, onClose, onOpenCompany }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const isReport = item.type === "report";
  const quarterly = !!item.quarter;
  const periodKey = item.year ? (quarterly ? `${item.year}Q${item.quarter}` : String(item.year)) : "";
  const [fin, setFin] = React.useState(null);

  React.useEffect(() => {
    if (!isReport || !item.ticker || !periodKey) { setFin({}); return undefined; }
    let alive = true;
    setFin(null);
    fetch(`/api/company/${encodeURIComponent(item.ticker)}/financials`
          + `?freq=${quarterly ? "quarterly" : "annual"}`)
      .then((r) => r.json())
      .then((d) => { if (alive) setFin(d && d.ok ? d : {}); })
      .catch(() => { if (alive) setFin({}); });
    return () => { alive = false; };
  }, [isReport, item.ticker, periodKey, quarterly]);

  React.useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const series = (fin && fin.series) || {};
  const figures = EVENT_DETAIL_ROWS
    .map((field) => {
      const s = series[field];
      const v = s && s.values ? s.values[periodKey] : undefined;
      return Number.isFinite(Number(v)) ? { field, value: Number(v), money: !!s.money } : null;
    })
    .filter(Boolean);

  const classLabel = (raw) => {
    const key = String(raw || "").toLowerCase();
    if (!key) return null;
    if (key === "bond") return t("Облигация", "Obligatsiya", "Bond");
    if (key.startsWith("prefer") || key.startsWith("imtiyoz")) {
      return t("Привилегированная акция", "Imtiyozli aksiya", "Preferred share");
    }
    if (key === "ordinary") return t("Обыкновенная акция", "Oddiy aksiya", "Ordinary share");
    return raw;
  };

  const kindLabel = item.type === "report"
    ? t("Отчётность", "Hisobot", "Filing")
    : item.type === "listing"
      ? t("Листинг", "Listing", "Listing")
      : t("Делистинг", "Delisting", "Delisting");

  const line = (label, value) => (value == null || value === "" ? null : (
    <div className="ev-detail-line">
      <span className="ev-detail-k">{label}</span>
      <span className="ev-detail-v">{value}</span>
    </div>
  ));

  return createPortal(
    <div className="ev-detail-backdrop" role="presentation" onClick={onClose}>
      <article className={`ev-detail ev-${item.type}`} role="dialog" aria-modal="true"
        aria-label={`${item.ticker} — ${headline}`}
        onClick={(e) => e.stopPropagation()}>
        <button type="button" className="ev-detail-close" onClick={onClose}
          aria-label={t("Закрыть", "Yopish", "Close")}>×</button>

        <div className="ev-detail-head">
          {/* The kind alone: the date is stated below, under the label that says
              WHOSE date it is — the issuer's, not our ingestion clock. */}
          <span className={`ev-detail-kind ev-${item.type}`}>{kindLabel}</span>
        </div>
        <h3 className="ev-detail-title">{headline}</h3>
        <button type="button" className="ev-detail-issuer"
          onClick={() => { if (onOpenCompany) onOpenCompany(item.ticker); onClose(); }}>
          <b>{item.ticker}</b>
          <span>{item.company}</span>
        </button>

        <div className="ev-detail-facts">
          {line(t("Период", "Davr", "Period"), period || null)}
          {line(t("Форма", "Shakl", "Form"), isReport ? (form || item.report_form) : null)}
          {line(item.type === "delisting"
                  ? t("Последняя сделка", "Oxirgi bitim", "Last trade")
                  : item.type === "listing"
                    ? t("Допуск к торгам", "Savdoga qo'yilgan", "Admitted to trading")
                    : t("Опубликовано эмитентом", "Emitent e'lon qilgan", "Published by the issuer"),
                day)}
          {line(t("Класс бумаги", "Qog'oz sinfi", "Share class"), classLabel(item.share_type))}
          {line(t("Капитализация при допуске", "Listingdagi kapitallashuv", "Cap at admission"),
                Number.isFinite(Number(item.market_cap))
                  ? formatCompactVolume(item.market_cap, lang) : null)}
        </div>

        {isReport && (
          <div className="ev-detail-fin">
            <h4>{t("Что этот отчёт даёт по периоду", "Bu hisobot davr bo'yicha nima beradi",
                   "What this filing holds for the period")}</h4>
            {fin === null ? (
              <p className="muted">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</p>
            ) : figures.length ? (
              <table className="ev-detail-table">
                <tbody>
                  {figures.map((f) => (
                    <tr key={f.field}>
                      <th scope="row">{finLabel(f.field, lang)}</th>
                      <td title={formatMarketNumber(f.value, lang, 0)}>
                        {f.money ? formatCompactVolume(f.value, lang)
                                 : formatRatio(f.value, 2, lang)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              // Said plainly rather than shown as an empty table: the filing is
              // real, the parse of THIS period simply has not reached us yet.
              <p className="muted">
                {t("Показатели за этот период у нас пока не разобраны — откройте документ или страницу компании.",
                   "Bu davr ko'rsatkichlari hali tahlil qilinmagan — hujjatni yoki kompaniya sahifasini oching.",
                   "The figures for this period are not parsed on our side yet — open the document or the company page.")}
              </p>
            )}
          </div>
        )}

        <div className="ev-detail-actions">
          <button type="button" className="ev-detail-primary"
            onClick={() => { if (onOpenCompany) onOpenCompany(item.ticker); onClose(); }}>
            {t("Страница компании", "Kompaniya sahifasi", "Company page")}
          </button>
          {(item.pdf_url || item.excel_url) && (
            <span className="ev-detail-src">
              <span className="muted">{t("Источник — openinfo.uz:", "Manba — openinfo.uz:", "Source — openinfo.uz:")}</span>
              {item.pdf_url && <a href={item.pdf_url} target="_blank" rel="noopener noreferrer">PDF</a>}
              {item.excel_url && <a href={item.excel_url} target="_blank" rel="noopener noreferrer">XLS</a>}
            </span>
          )}
        </div>
      </article>
    </div>,
    document.body
  );
}

export { MarketEventsFeed };
