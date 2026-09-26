import { formatRatio } from "./format.jsx";

// The price-statistics strip that used to sit under the chart — VWAP, макс/мин,
// среднее закрытий, 1М/YTD/YoY/QoQ, волатильность and макс. дневной диапазон —
// was REMOVED from the company page by the customer on 2026-08-08. It is not on
// the quote page this layout follows, and on a page a shareholder reads it was
// six figures nothing on screen explained: two different averages of the same
// window, six percent apart, next to a historical peak from June 2024 that never
// changes.
//
// Nothing was deleted below the screen. /api/company/{t}/metrics and formulas.py
// are untouched — the auditor, the exports and the paid analysis all read them,
// and this page still reads `quality` and `ma_windows` off the same response to
// decide whether candles are meaningful. The figures are unpublished here, not
// gone; re-rendering them is a component away.

// ТЗ §8: a multiple the server withheld says WHY. «убыток» is a fact about the
// issuer, not missing data; a range status means the figure exists and is not
// suitable for direct comparison.
// ТЗ v1.3 §12.6: the auditor is visible without its rule codes — a withheld
// metric is a dash whose tooltip says why; the reader does not need to know
// which rule fired, only which numbers they can trust.
//
// Module-level because the market board and the company page's key-stats rail
// now read the SAME /api/market/multiples envelope. While this vocabulary lived
// inside MarketView the company page had no way to say «снято аудитом», so it
// recomputed P/E and P/B itself and published figures the board withheld.
const MULTIPLE_STATUS_TEXT = {
  audit_blocked: ["снято аудитом", "audit olib tashladi", "withheld by audit"],
  loss_making: ["убыток", "zarar", "loss"],
  out_of_range: ["вне диапазона", "diapazondan tashqari", "out of range"],
  shares_inconsistent: ["сверка акций", "aksiyalar sverkasi", "share count"],
  incomplete: ["нет всех классов", "barcha sinflar yo'q", "classes missing"],
  no_market_cap: ["нет капитализации", "kapitalizatsiya yo'q", "no market cap"],
  no_share_count: ["нет числа акций", "aksiyalar soni yo'q", "no share count"],
  // ТЗ мультипликаторов 2026-08-10: V4 makes a two-year-old statement «нет
  // данных», a negative capital is a fact about the issuer, and «н/п» marks a
  // figure the issuer's reporting form does not define (P/S for a bank).
  stale_period: ["нет свежего отчёта", "yangi hisobot yo'q", "no recent report"],
  negative_equity: ["отрицательный капитал", "salbiy kapital", "negative equity"],
  not_applicable: ["не применяется", "qo‘llanmaydi", "not applicable"],
  loading: ["загрузка", "yuklanmoqda", "loading"],
  unavailable: ["недоступно", "mavjud emas", "unavailable"],
};

function multipleStatusText(status, lang) {
  const words = MULTIPLE_STATUS_TEXT[status];
  return words ? words[lang === "uz" ? 1 : lang === "en" ? 2 : 0] : null;
}

// P/E, P/B and P/S belong to an issuer, whereas the visible market-cap column
// belongs to one share class.  Do not call an ordinary class "without market
// cap" merely because another class has no current price: that is misleading
// for KSCM/KSCMP and for every other multi-class issuer.  The API supplies the
// class inputs, so this explanation is derived from live data rather than a
// ticker-specific exception.
function incompleteIssuerCapAvailability(metric, issuerCap, ticker, lang) {
  if (metric?.status !== "no_market_cap" || issuerCap?.status !== "incomplete") return null;

  const inputs = Array.isArray(issuerCap.class_inputs) ? issuerCap.class_inputs : [];
  const missing = Array.isArray(issuerCap.missing_classes) ? issuerCap.missing_classes : [];
  const unavailable = inputs.filter((item) => item?.usable_for_issuer_cap === false);
  const unavailableTickers = unavailable.map((item) => String(item?.ticker || "").toUpperCase()).filter(Boolean);
  const classNames = missing.length ? missing : unavailableTickers;
  if (!classNames.length) return null;

  const currentTicker = String(ticker || "").toUpperCase();
  const ownInput = inputs.find((item) => String(item?.ticker || "").toUpperCase() === currentTicker);
  const ownCapAvailable = ownInput?.usable_for_issuer_cap === true
    && Number.isFinite(Number(ownInput?.market_cap));
  const details = unavailable.map((item) => {
    const name = String(item?.ticker || "").toUpperCase() || "—";
    const date = item?.price_as_of ? String(item.price_as_of) : null;
    const age = Number.isFinite(Number(item?.price_age_days)) ? Number(item.price_age_days) : null;
    const maximum = Number.isFinite(Number(item?.max_price_age_days)) ? Number(item.max_price_age_days) : null;
    const ageText = age != null
      ? (lang === "ru" ? `${age} дн.` : lang === "uz" ? `${age} kun` : `${age} days`)
      : null;
    const limitText = maximum != null
      ? (lang === "ru" ? `лимит ${maximum} дн.` : lang === "uz" ? `limit ${maximum} kun` : `limit ${maximum} days`)
      : null;
    return [name, date, [ageText, limitText].filter(Boolean).join(", ")].filter(Boolean).join(" · ");
  });
  const classes = details.length ? details.join("; ") : classNames.join(", ");

  if (lang === "uz") {
    return {
      label: "emitent kapitalizatsiyasi to'liq emas",
      title: `${ownCapAvailable ? `${currentTicker} kapitalizatsiyasi mavjud. ` : ""}Emitentning P/E, P/B va P/S ko'rsatkichlari uchun ${classes} bo'yicha yangiroq narx kerak.`,
    };
  }
  if (lang === "en") {
    return {
      label: "issuer market cap incomplete",
      title: `${ownCapAvailable ? `${currentTicker} market cap is available. ` : ""}A current price for ${classes} is required to calculate issuer P/E, P/B and P/S.`,
    };
  }
  return {
    label: "неполная капитализация эмитента",
    title: `${ownCapAvailable ? `Капитализация ${currentTicker} доступна. ` : ""}Для расчёта P/E, P/B и P/S эмитента нужна свежая цена ${classes}.`,
  };
}

// An outlier is calculated data, not a loss and not missing data. Show the
// number, but mark it so a near-zero denominator cannot masquerade as a useful
// valuation multiple or participate silently in comparisons.
const outlierLabel = (lang) => (lang === "ru" ? "вне диапазона" : lang === "uz" ? "diapazondan tashqari" : "outside range");

const outlierTitle = (metric, digits, suffix, lang) => [
  lang === "ru"
    ? "Коэффициент рассчитан, но находится вне обычного диапазона. Это может быть связано с очень маленькой базой расчёта или особенностями структуры капитала; не используйте его для прямого сравнения компаний."
    : lang === "uz"
      ? "Ko‘rsatkich hisoblangan, ammo odatiy diapazondan tashqarida. Bunga juda kichik hisoblash bazasi yoki kapital tuzilmasining o‘ziga xosligi sabab bo‘lishi mumkin; uni kompaniyalarni bevosita taqqoslash uchun ishlatmang."
      : "The ratio is calculated but falls outside the usual range. This can result from a very small calculation base or an unusual capital structure; do not use it for direct company comparisons.",
  `${lang === "ru" ? "Значение вне диапазона сопоставимости" : lang === "uz" ? "Taqqoslash oralig‘idan tashqaridagi qiymat" : "Value outside the comparison range"}: ` +
    `${formatRatio(metric.value, digits, lang)}${suffix}`,
  metric.allowed
    ? `${lang === "ru" ? "Диапазон сопоставимости" : lang === "uz" ? "Taqqoslash oralig‘i" : "Comparison range"}: ` +
      `[${metric.allowed.join("; ")}]`
    : null,
  metric.base_period,
  metric.note,
].filter(Boolean).join(" · ");

function RangeHelpIcon({ title }) {
  return <span className="range-help-icon" role="img" tabIndex={0} title={title} aria-label={title}>?</span>;
}

const notApplicableTitle = (lang) => (lang === "ru"
  ? "P/S не применяется к банкам: в отчётности OpenInfo нет сопоставимой строки выручки от продаж. Для оценки используйте P/B, ROE и Капитал/Активы."
  : lang === "uz"
    ? "P/S banklarga qo‘llanmaydi: OpenInfo hisobotida sotuv tushumining taqqoslanadigan qatori yo‘q. Baholash uchun P/B, ROE va Kapital/Aktivlardan foydalaning."
    : "P/S does not apply to banks because OpenInfo bank filings have no comparable sales-revenue line. Use P/B, ROE and Equity/Assets instead.");

// A loss is not missing data and it is more useful than the generic n/m label.
// Keep the arithmetical negative P/E available for audit in the tooltip, but do
// not present it as a valuation multiple that can be ranked against positive P/E.
const lossLabel = (lang) => (lang === "ru" ? "Убыток" : lang === "uz" ? "Zarar" : "Loss");

const lossTitle = (metric, digits, suffix, lang) => [
  lang === "ru"
    ? `P/E не применим: чистый убыток. Расчётное значение: ${formatRatio(metric.computed, digits, lang)}${suffix}`
    : lang === "uz"
      ? `P/E qo'llanmaydi: sof zarar. Hisoblangan qiymat: ${formatRatio(metric.computed, digits, lang)}${suffix}`
      : `P/E is not applicable: net loss. Calculated value: ${formatRatio(metric.computed, digits, lang)}${suffix}`,
  metric.base_period,
  metric.note,
].filter(Boolean).join(" · ");

export { RangeHelpIcon, incompleteIssuerCapAvailability, lossLabel, lossTitle, multipleStatusText, notApplicableTitle, outlierLabel, outlierTitle };
