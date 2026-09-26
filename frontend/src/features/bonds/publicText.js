// Public bond copy is allowlisted: API diagnostics and unknown codes stay off the page.
const select = (text, lang) => text[lang === "uz" ? 1 : lang === "en" ? 2 : 0];
const unavailable = ["данных пока недостаточно", "hozircha ma’lumot yetarli emas", "there is not enough information yet"];

const reasons = {
  NO_VERIFIED_TRADE: ["нет подтверждённой цены сделки", "tasdiqlangan bitim narxi yo‘q", "no confirmed trade price is available"],
  COUPON_RATE_IMPLAUSIBLE: ["данные о купоне требуют уточнения", "kupon ma’lumotlarini aniqlashtirish kerak", "the coupon details need clarification"],
  YIELD_OUT_OF_RANGE: ["данные о цене и выплатах требуют уточнения", "narx va to‘lov ma’lumotlarini aniqlashtirish kerak", "the price and payment details need clarification"],
  UNKNOWN_FUTURE_COUPONS: ["размер будущих купонов ещё не известен", "kelgusi kuponlar miqdori hali noma’lum", "future coupon amounts are not yet known"],
  AMORTIZATION_OR_OPTIONS_NOT_VERIFIED: ["условия погашения требуют уточнения", "so‘ndirish shartlarini aniqlashtirish kerak", "the repayment terms need clarification"],
  PAYMENT_OR_ISSUE_STATUS_BLOCKED: ["статус выпуска или выплат требует уточнения", "chiqarilish yoki to‘lovlar holatini aniqlashtirish kerak", "the issue or payment status needs clarification"],
  DAY_COUNT_NOT_DISCLOSED: ["эмитент не указал порядок начисления процентов", "emitent foizlarni hisoblash tartibini ko‘rsatmagan", "the issuer has not disclosed how interest accrues"],
  DAY_COUNT_NOT_SUPPORTED: ["расчёт по условиям этого выпуска пока недоступен", "ushbu chiqarilish shartlari bo‘yicha hisoblash hozircha mavjud emas", "calculations for this issue’s terms are not yet available"],
  ACCRUAL_PERIOD_NOT_VERIFIED: ["период начисления купона требует уточнения", "kupon hisoblash davrini aniqlashtirish kerak", "the coupon accrual period needs clarification"],
  PRINCIPAL_SCHEDULE_NOT_RECONCILED: ["график возврата номинала требует уточнения", "nominalni qaytarish jadvalini aniqlashtirish kerak", "the principal repayment schedule needs clarification"],
  BASIS_NOT_VERIFIED: ["недостаточно данных для сравнения доходности", "daromadlilikni taqqoslash uchun ma’lumot yetarli emas", "there is not enough information to compare yields"],
  NO_GOV_CURVE: ["нет данных о доходности государственных облигаций для сравнения", "taqqoslash uchun davlat obligatsiyalari daromadliligi haqida ma’lumot yo‘q", "government bond yields are not available for comparison"],
};

const statuses = {
  exact: ["расчёт по подтверждённым условиям", "tasdiqlangan shartlar bo‘yicha hisob", "calculated from confirmed terms"],
  ok: ["данные доступны", "ma’lumotlar mavjud", "data available"],
  indicative: ["приблизительный расчёт", "taxminiy hisob", "estimated calculation"],
  stale_indicative: ["приблизительный расчёт по устаревшей цене", "eskirgan narx bo‘yicha taxminiy hisob", "estimate based on an older price"],
  matured: ["выпуск погашен", "chiqarilish so‘ndirilgan", "the issue has matured"],
  no_price: reasons.NO_VERIFIED_TRADE,
  not_traded: reasons.NO_VERIFIED_TRADE,
  never_traded: reasons.NO_VERIFIED_TRADE,
  no_curve: reasons.NO_GOV_CURVE,
  no_bond_reference: ["не все условия выпуска раскрыты", "chiqarilishning barcha shartlari oshkor qilinmagan", "some issue terms have not been disclosed"],
  scenario_required: reasons.UNKNOWN_FUTURE_COUPONS,
  not_applicable: ["не предусмотрено условиями выпуска", "chiqarilish shartlarida nazarda tutilmagan", "not included in this issue’s terms"],
  verified: ["проверено", "tekshirilgan", "verified"],
  limited: ["ограничено данными", "ma’lumotlar cheklangan", "limited information"],
  calculation_verified: ["расчёт проверен", "hisob tekshirilgan", "calculation verified"],
  insufficient_data: unavailable,
  fresh: ["актуальная котировка", "dolzarb kotirovka", "current quote"],
  aging: ["с последней сделки прошло больше недели", "so‘nggi bitimdan bir haftadan ko‘p vaqt o‘tgan", "the last trade was more than a week ago"],
  stale: ["устаревшая котировка", "eskirgan kotirovka", "older quote"],
  very_stale: ["давно не было сделок", "anchadan beri bitimlar bo‘lmagan", "no recent trades"],
  invalid_future_quote: ["дата сделки требует уточнения", "bitim sanasini aniqlashtirish kerak", "the trade date needs clarification"],
  due_unconfirmed: ["срок наступил, выплата не подтверждена", "muddat keldi, to‘lov tasdiqlanmagan", "payment is due but has not been confirmed"],
  scheduled: ["выплата запланирована", "to‘lov rejalashtirilgan", "payment is scheduled"],
  paid_confirmed: ["выплата подтверждена", "to‘lov tasdiqlangan", "payment confirmed"],
  full: ["полная история", "to‘liq tarix", "complete history"],
  partial: ["неполная история", "to‘liq bo‘lmagan tarix", "partial history"],
};

const terms = {
  nominal: ["номинал", "nominal", "par value"],
  coupon_rate: ["ставка купона", "kupon stavkasi", "coupon rate"],
  coupon_freq: ["частота выплат", "to‘lovlar davriyligi", "payment frequency"],
  maturity_date: ["дата погашения", "so‘ndirish sanasi", "maturity date"],
  issue_date: ["дата размещения", "joylashtirish sanasi", "issue date"],
  day_count_basis: ["порядок начисления процентов", "foizlarni hisoblash tartibi", "interest accrual method"],
};

export function bondBlockedText(code, lang) {
  return select(Object.hasOwn(reasons, code) ? reasons[code] : unavailable, lang);
}

export function bondStatusText(status, lang) {
  if (!status) return "—";
  return select(Object.hasOwn(statuses, status) ? statuses[status] : unavailable, lang);
}

export function bondMissingTerms(fields, lang) {
  const other = ["другие условия выпуска", "chiqarilishning boshqa shartlari", "other issue terms"];
  return [...new Set((fields || []).map((field) => select(Object.hasOwn(terms, field) ? terms[field] : other, lang)))].join(", ");
}

export function bondMetricText(metric, lang) {
  if (metric?.blocked_reason) return bondBlockedText(metric.blocked_reason, lang);
  const missing = bondMissingTerms(metric?.missing, lang);
  if (missing) return `${select(["Не хватает данных", "Ma’lumot yetishmayapti", "Missing information"], lang)}: ${missing}`;
  const status = metric?.calculation_status || metric?.status;
  if (status) return bondStatusText(status, lang);
  return metric?.value != null ? "" : select(unavailable, lang);
}
