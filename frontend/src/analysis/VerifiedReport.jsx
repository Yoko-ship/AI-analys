import React from "react";
import "./verified-report.css";

const pick = (lang, ru, uz, en) => ({ ru, uz, en }[lang] || ru);
const fmt = (value, lang) => value == null ? "—" : Number(value).toLocaleString(lang === "en" ? "en-US" : "ru-RU", { maximumFractionDigits: 2 });
const safeUrl = (value) => /^https?:\/\//i.test(value || "") ? value : undefined;

export function ReportAvailability({ report, lang = "ru" }) {
  if (!report || report.status === "available") return null;
  return <div className="verified-availability" role="status">
    <strong>{report.headline}</strong>
    <p>{pick(lang, "Последний исходный период", "So‘nggi manba davri", "Latest source period")}: {report.availability?.last_source_period || "—"}</p>
    {(report.data_quality || []).map((item) => <p key={item.code}>{item.message} <small>({item.code})</small></p>)}
    {report.availability?.next_action && <p>{report.availability.next_action}</p>}
    {report.last_successful_report && <details>
      <summary>{pick(lang, "Последний проверенный анализ", "So‘nggi tekshirilgan tahlil", "Last verified analysis")} · {report.last_successful_report.period}</summary>
      {(report.last_successful_report.paragraphs || []).map((p, i) => <p key={i}>{p}</p>)}
    </details>}
  </div>;
}

export default function VerifiedReport({ report, lang = "ru", narrative = false }) {
  if (!report) return null;
  if (report.status !== "available") return <ReportAvailability report={report} lang={lang} />;
  const t = (ru, uz, en) => pick(lang, ru, uz, en);
  const divisor = report.display_divisor || 1;
  const money = (value) => fmt(value == null ? null : value / divisor, lang);
  const units = divisor === 1000 ? t("млн сум", "mln so‘m", "million UZS") : t("тыс. сум", "ming so‘m", "thousand UZS");
  const groups = {
    financial_result: t("Финансовый результат", "Moliyaviy natija", "Financial result"),
    cash_and_working_capital: t("Деньги и оборотный капитал", "Pul va aylanma kapital", "Cash and working capital"),
    investment_base: t("Инвестиционная база", "Investitsiya bazasi", "Investment base"),
    sector_operating_facts: t("Отраслевые факты", "Tarmoq faktlari", "Sector facts"),
    market_facts: t("Рыночные факты", "Bozor faktlari", "Market facts"),
  };
  return <div className="verified-report" data-testid="verified-report">
    <div className="verified-meta">
      <span>{report.report?.standard || report.standard?.toUpperCase()} · {report.period_label || report.period}</span>
      <span>{t("Финансовая дата", "Moliyaviy sana", "Financial date")}: {report.financial_as_of || "—"}</span>
      <span>{t("Дата рынка", "Bozor sanasi", "Market date")}: {report.market_as_of || "—"}</span>
    </div>
    {report.publication_restored && <p className="verified-note">{t("Восстановлена предыдущая проверенная публикация. Дата финансовых данных сохранена.", "Oldingi tekshirilgan nashr tiklangan. Moliyaviy sana saqlangan.", "A previous verified publication has been restored with its original financial date.")}</p>}
    {narrative && (report.paragraphs || []).map((p, i) => <p key={i}>{p}</p>)}
    {report.nav && <section className="verified-ratios" aria-label={t("Стоимость активов фонда", "Fond aktivlari qiymati", "Fund asset valuation")}>
      <article><strong>NAV</strong><p>{fmt(report.nav.value_mln_uzs, lang)} {t("млн сум", "mln so‘m", "million UZS")}</p><small>{report.financial_as_of}</small></article>
      <article><strong>{t("NAV на биржевую акцию", "Birja aksiyasiga NAV", "NAV per exchange share")}</strong><p>{fmt(report.nav.per_exchange_share_uzs, lang)} UZS</p></article>
      <article><strong>{t("Цена / NAV", "Narx / NAV", "Price / NAV")}</strong><p>{fmt(report.valuation?.price_to_nav, lang)}{report.valuation?.price_to_nav != null && "×"}</p><small>{report.valuation?.blocked_reason}</small></article>
    </section>}
    {report.instrument?.instrument_type === "preferred_share" && <p className="verified-note">
      {t("Привилегированная акция: финансовый профиль эмитента общий; права и дивиденды этого класса рассматриваются отдельно.", "Imtiyozli aksiya: emitent moliyaviy profili umumiy; bu sinf huquqlari va dividendlari alohida ko‘riladi.", "Preferred share: the issuer financial profile is shared; this class’s rights and dividends are assessed separately.")}
    </p>}
    {Object.entries(report.replacement_blocks || {}).map(([key, rows]) => rows?.length ? <details key={key} className="verified-block">
      <summary>{groups[key] || key}</summary>
      <div className="verified-scroll" tabIndex={0} role="region" aria-label={groups[key] || key}>
        <table>
          <caption>{units}. {report.comparison_status === "not_available_first_reporting_period"
            ? t("Первый отчётный период; сопоставимой базы нет.", "Birinchi hisobot davri; taqqoslash bazasi yo‘q.", "First reporting period; no comparable prior period.")
            : t("Баланс — к началу года, результаты — к тому же периоду прошлого года.", "Balans yil boshiga, natijalar o‘tgan yilning shu davriga.", "Balance changes since year-start; income changes against the same prior-year period.")}</caption>
          <thead><tr><th>{t("Показатель", "Ko‘rsatkich", "Metric")}</th><th>{t("База", "Baza", "Prior")}</th><th>{t("Текущее", "Joriy", "Current")}</th><th>Δ</th><th>Δ %</th><th>{t("Источник", "Manba", "Source")}</th></tr></thead>
          <tbody>{rows.map((fact) => <tr key={fact.metric_code || fact.metric}>
            <th scope="row">{fact.label || fact.metric_code}</th>
            <td>{money(fact.previous)}</td><td>{money(fact.value)}</td>
            <td>{money(fact.change_value)}</td><td>{fmt(fact.change_pct, lang)}{fact.base_effect && <span title={t("Эффект базы / смена знака", "Baza ta’siri / ishora o‘zgarishi", "Base effect / sign change")}> *</span>}</td>
            <td>{safeUrl(fact.source_url) ? <a href={safeUrl(fact.source_url)} target="_blank" rel="noreferrer">{fact.source_line_id || t("Документ", "Hujjat", "Document")}</a> : "—"}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </details> : null)}
    {report.ratios?.length > 0 && <details className="verified-block">
      <summary>{t("Проверенные формулы НСБУ", "Tekshirilgan NSBU formulalari", "Verified NSBU formulas")}</summary>
      <div className="verified-ratios">
        {report.ratios.map((item) => <article key={item.method_id}>
          <strong>{item.metric_code}: {fmt(item.value, lang)}{item.unit === "percent" ? "%" : ""}</strong>
          <p>{item.formula}</p><p>{fmt(item.numerator_value, lang)} / {fmt(item.denominator_value, lang)}</p>
          {item.benchmark_type && <small>{t("Методический ориентир", "Metodik mezon", "Methodological reference")}: {item.benchmark_min}{item.benchmark_max ? "–" + item.benchmark_max : "+"}</small>}
          {item.value == null && <small>{t("Нет полного набора компонентов", "Tarkibiy qismlar to‘liq emas", "Components are incomplete or invalid")}</small>}
        </article>)}
      </div>
    </details>}
    {report.analytical_issues?.length > 0 && <section className="verified-issues">
      <h3>{t("Проблемы и выводы", "Muammolar va xulosalar", "Issues and conclusions")}</h3>
      {report.analytical_issues.map((issue) => <article key={issue.issue_code}>
        <h4>{issue.title}</h4>
        <p>{issue.period}: {issue.comparison_value != null && <>{money(issue.comparison_value)} → </>}{money(issue.actual_value)} {units}</p>
        <p>{issue.cause_text} {issue.impact}</p><p>{issue.solution_text}</p>
        <strong>{issue.verdict_text}</strong><p>{issue.next_trigger}</p>
        {safeUrl(issue.source_url) && <a href={safeUrl(issue.source_url)} target="_blank" rel="noreferrer">{t("Проверить источник", "Manbani tekshirish", "View evidence")} ↗</a>}
      </article>)}
    </section>}
    {report.data_quality?.length > 0 && <aside className="verified-note">
      <h3>{t("Ограничения данных", "Ma’lumotlar cheklovlari", "Data limitations")}</h3>
      {report.data_quality.map((item) => <p key={item.code}>{item.message}</p>)}
    </aside>}
    <small className="verified-version">{report.template_version} · {report.calculation_version}</small>
  </div>;
}
