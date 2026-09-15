import React from "react";
import "./verified-report.css";

const pick = (lang, ru, uz, en) => ({ ru, uz, en }[lang] || ru);
const fmt = (value, lang) => value == null ? "—" : Number(value).toLocaleString(lang === "en" ? "en-US" : "ru-RU", { maximumFractionDigits: 2 });
const safeUrl = (value) => /^https?:\/\//i.test(value || "") ? value : undefined;

const RATIO_COPY = {
  P1: ["Рентабельность активов", "Aktivlar rentabelligi", "Return on assets", "Чистая прибыль на каждые 100 сум активов", "Har 100 so‘mlik aktivdan sof foyda", "Net profit per 100 UZS of assets"],
  P2: ["Доходность оборотных активов", "Aylanma aktivlar daromadliligi", "Return on current assets", "Прибыль до налога на каждые 100 сум оборотных активов", "Har 100 so‘mlik aylanma aktivdan soliqdan oldingi foyda", "Pre-tax profit per 100 UZS of current assets"],
  P3: ["Рентабельность вложенного капитала", "Kiritilgan kapital rentabelligi", "Return on invested capital", "Прибыль до налога на каждые 100 сум вложенного капитала", "Har 100 so‘mlik kiritilgan kapitaldan soliqdan oldingi foyda", "Pre-tax profit per 100 UZS of invested capital"],
  P4: ["Рентабельность собственного капитала", "O‘z kapitali rentabelligi", "Return on equity", "Прибыль до налога на каждые 100 сум собственного капитала", "Har 100 so‘mlik o‘z kapitalidan soliqdan oldingi foyda", "Pre-tax profit per 100 UZS of equity"],
  P5: ["Валовая маржа", "Yalpi marja", "Gross margin", "Валовая прибыль в каждых 100 сум выручки", "Har 100 so‘mlik tushumdagi yalpi foyda", "Gross profit in every 100 UZS of revenue"],
  P6: ["Рентабельность себестоимости", "Tannarx rentabelligi", "Return on cost of sales", "Валовая прибыль на каждые 100 сум себестоимости", "Har 100 so‘mlik tannarxdan yalpi foyda", "Gross profit per 100 UZS of cost of sales"],
  P7: ["Маржа до налога", "Soliqqacha marja", "Pre-tax margin", "Прибыль до налога в каждых 100 сум выручки", "Har 100 so‘mlik tushumdagi soliqdan oldingi foyda", "Pre-tax profit in every 100 UZS of revenue"],
  P8: ["Доходность долгосрочных активов", "Uzoq muddatli aktivlar daromadliligi", "Return on long-term assets", "Прибыль до налога на каждые 100 сум долгосрочных активов", "Har 100 so‘mlik uzoq muddatli aktivdan soliqdan oldingi foyda", "Pre-tax profit per 100 UZS of long-term assets"],
  current_ratio: ["Текущая ликвидность", "Joriy likvidlik", "Current ratio", "Покрытие текущих обязательств оборотными активами", "Joriy majburiyatlarning aylanma aktivlar bilan qoplanishi", "Coverage of current liabilities by current assets"],
  quick_ratio: ["Быстрая ликвидность", "Tezkor likvidlik", "Quick ratio", "Покрытие текущих обязательств без продажи запасов", "Zaxiralarni sotmasdan joriy majburiyatlarni qoplash", "Coverage of current liabilities without selling inventory"],
  absolute_liquidity: ["Абсолютная ликвидность", "Mutlaq likvidlik", "Absolute liquidity", "Доля текущих обязательств, которую можно погасить сразу", "Darhol to‘lash mumkin bo‘lgan joriy majburiyatlar ulushi", "Share of current liabilities payable immediately"],
};

const ratioText = (item, lang, offset) => {
  const copy = RATIO_COPY[item.metric_code] || [item.metric_code, item.metric_code, item.metric_code, "", "", ""];
  const languageIndex = lang === "uz" ? 1 : lang === "en" ? 2 : 0;
  return copy[offset + languageIndex];
};

const compactNumber = (value, lang) => value == null ? "—" : Number(value).toLocaleString(
  lang === "en" ? "en-US" : "ru-RU",
  { notation: "compact", maximumFractionDigits: 2 },
);

export function ReportAvailability({ report, lang = "ru" }) {
  if (!report || ["available", "stale"].includes(report.status)) return null;
  const mappingFailed = report.status === "mapping_failed"
    || (report.data_quality || []).some((item) => item.code === "SOURCE_MAPPING_FAILED");
  const heading = mappingFailed
    ? pick(lang, "Отчёт пока готовится", "Hisobot hozir tayyorlanmoqda", "The report is being prepared")
    : report.headline;
  const qualityMessage = (item) => item.code === "SOURCE_MAPPING_FAILED"
    ? pick(lang,
      "Данные найдены, но их пока не удалось подготовить для анализа.",
      "Ma’lumotlar topildi, ammo hozircha tahlil uchun tayyorlanmadi.",
      "The data was found but is not ready for analysis yet.")
    : item.message;
  return <div className="verified-availability" role="status">
    <strong>{heading}</strong>
    <p>{pick(lang, "Доступный период", "Mavjud davr", "Available period")}: {report.availability?.last_source_period || report.period || "—"}</p>
    {(report.data_quality || []).map((item) => <p key={item.code}>{qualityMessage(item)}</p>)}
    {report.availability?.next_action && <p>{mappingFailed
      ? pick(lang, "Мы проверим данные снова после обновления источника.", "Manba yangilangach ma’lumotlarni yana tekshiramiz.", "We will check the data again after the source is updated.")
      : report.availability.next_action}</p>}
    {report.last_successful_report && <details>
      <summary>{pick(lang, "Последний проверенный анализ", "So‘nggi tekshirilgan tahlil", "Last verified analysis")} · {report.last_successful_report.period}</summary>
      {(report.last_successful_report.paragraphs || []).map((p, i) => <p key={i}>{p}</p>)}
    </details>}
  </div>;
}

export default function VerifiedReport({ report, lang = "ru", narrative = false, hideMeta = false }) {
  if (!report) return null;
  if (!["available", "stale"].includes(report.status)) return <ReportAvailability report={report} lang={lang} />;
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
    {!hideMeta && <div className="verified-meta">
      <span>{report.report?.standard || report.standard?.toUpperCase()} · {report.period_label || report.period}</span>
      <span>{t("Финансовая дата", "Moliyaviy sana", "Financial date")}: {report.financial_as_of || "—"}</span>
      <span>{t("Дата рынка", "Bozor sanasi", "Market date")}: {report.market_as_of || "—"}</span>
    </div>}
    {report.status === "stale" && <p className="verified-note">
      {t(`Анализ построен по последней доступной отчётности (${report.period_label || report.period}); более свежий отчёт источник пока не опубликовал.`,
        `Tahlil oxirgi mavjud hisobot (${report.period_label || report.period}) asosida tuzilgan; manba hali yangiroq hisobotni e’lon qilmagan.`,
        `This analysis uses the latest available filing (${report.period_label || report.period}); the source has not published a newer filing yet.`)}
    </p>}
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
          <thead><tr><th>{t("Показатель", "Ko‘rsatkich", "Metric")}</th><th>{t("За соответствующий период прошлого года", "O‘tgan yilning mos davri", "Same period last year")}</th><th>{t("За текущий отчётный период", "Joriy hisobot davri", "Current reporting period")}</th><th>{t("Изменение", "O‘zgarish", "Change")}</th><th>{t("Изменение, %", "O‘zgarish, %", "Change, %")}</th><th>{t("Источник", "Manba", "Source")}</th></tr></thead>
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
      <summary>{t("Финансовые коэффициенты", "Moliyaviy koeffitsiyentlar", "Financial ratios")}</summary>
      <div className="verified-ratios">
        {report.ratios.map((item) => <article key={item.method_id} data-testid={`verified-ratio-${item.metric_code}`}>
          <strong className="verified-ratio-name">{ratioText(item, lang, 0)}</strong>
          <p className="verified-ratio-value">{fmt(item.value, lang)}{item.unit === "percent" ? "%" : "×"}</p>
          <p className="verified-ratio-meaning">{ratioText(item, lang, 3)}</p>
          {item.benchmark_type && item.value != null && <small className={`verified-ratio-status ${item.value >= item.benchmark_min && (item.benchmark_max == null || item.value <= item.benchmark_max) ? "good" : "attention"}`}>
            {item.value >= item.benchmark_min && (item.benchmark_max == null || item.value <= item.benchmark_max)
              ? t("В пределах ориентира", "Me’yor doirasida", "Within reference range")
              : t("Требует внимания", "E’tibor talab qiladi", "Needs attention")}
            {` · ${t("ориентир", "me’yor", "reference")} ${item.benchmark_min}${item.benchmark_max ? "–" + item.benchmark_max : "+"}`}
          </small>}
          {item.value == null && <small>{t("Нет полного набора компонентов", "Tarkibiy qismlar to‘liq emas", "Components are incomplete or invalid")}</small>}
          <details className="verified-ratio-details">
            <summary>{t("Как рассчитано", "Qanday hisoblangan", "How it is calculated")}</summary>
            <p><code>{item.metric_code}</code> · {item.formula}</p>
            <p>{compactNumber(item.numerator_value, lang)} / {compactNumber(item.denominator_value, lang)}</p>
          </details>
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
    {report.verification_summary && <aside className="verified-checks">
      <p><strong>{t("Проверено", "Tekshirildi", "Checked")}:</strong> {(report.verification_summary.checked || []).join("; ") || "—"}.</p>
      <p><strong>{t("Не хватает", "Yetishmaydi", "Missing")}:</strong> {(report.verification_summary.missing || []).join("; ") || t("существенных строк не выявлено", "muhim satrlar yetishmaydi deb topilmadi", "no material line gaps identified")}.</p>
      <p><strong>{t("Поэтому нельзя оценить", "Shuning uchun baholab bo‘lmaydi", "Therefore cannot assess")}:</strong> {(report.verification_summary.cannot_assess || []).join("; ") || "—"}.</p>
    </aside>}
    {report.data_quality?.length > 0 && <aside className="verified-note">
      <h3>{t("Ограничения данных", "Ma’lumotlar cheklovlari", "Data limitations")}</h3>
      {report.data_quality.map((item) => <p key={item.code}>{item.message}</p>)}
    </aside>}
  </div>;
}
