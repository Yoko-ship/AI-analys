const REASONS = {
  NOTES_MISSING: ['Примечания отсутствуют или не проверены.', 'Izohlar yo‘q yoki tekshirilmagan.', 'Notes are missing or have not been verified.'],
  NO_IMPORTED_SOURCE_ROWS: ['Исходные строки ещё не импортированы.', 'Asl qatorlar hali import qilinmagan.', 'Original source rows have not been imported yet.'],
  LEGACY_PARTIAL_IMPORT: ['Ранее были загружены только основные показатели.', 'Oldin faqat asosiy ko‘rsatkichlar yuklangan.', 'The earlier import contains headline figures only.'],
  PARTIAL_SOURCE_IMPORT: ['Исходная форма загружена не полностью.', 'Asl shakl to‘liq yuklanmagan.', 'The original form was only partly imported.'],
  EMPTY_OR_SCANNED_PAGES: ['Часть страниц требует распознавания скана.', 'Ayrim sahifalar skanini tanish kerak.', 'Some pages need scan recognition.'],
  PAGES_NOT_EXTRACTED: ['Не все страницы документа прочитаны.', 'Hujjatning barcha sahifalari o‘qilmagan.', 'Some document pages have not been read.'],
  STATEMENT_ROWS_MISSING: ['Строки отчётности не распознаны. Нужна проверка оригинала.', 'Hisobot qatorlari aniqlanmagan. Aslini tekshiring.', 'Statement rows could not be read. The original needs review.'],
  FORM_MISSING: ['Форма отсутствует или не распознана.', 'Shakl yo‘q yoki aniqlanmagan.', 'A statement is missing or could not be recognized.'],
  UNIT_UNRESOLVED: ['Валюта или масштаб суммы не подтверждены.', 'Valyuta yoki summa miqyosi tasdiqlanmagan.', 'The source currency or amount scale is unconfirmed.'],
  SCOPE_UNRESOLVED: ['Периметр отчётности не подтверждён.', 'Hisobot qamrovi tasdiqlanmagan.', 'The reporting scope is unconfirmed.'],
  TABLE_COLUMNS_UNRESOLVED: ['Периоды колонок не удалось подтвердить.', 'Ustunlar davri tasdiqlanmagan.', 'The table column periods could not be confirmed.'],
  COLUMN_PARTITION_UNRESOLVED: ['Не удалось однозначно разделить суммы по колонкам.', 'Summalarni ustunlarga aniq ajratib bo‘lmadi.', 'Amounts could not be assigned unambiguously to columns.'],
  PERIOD_START_UNRESOLVED: ['Начало отчётного периода не подтверждено.', 'Hisobot davri boshlanishi tasdiqlanmagan.', 'The start of the reporting period is unconfirmed.'],
  SOURCE_VALUE_MISSING: ['В источнике нет значения для этого периода.', 'Bu davr uchun manba qiymati yo‘q.', 'No source amount is available for this period.'],
  PERIOD_COVERAGE_MISSING: ['Не хватает сопоставимых периодов для расчёта.', 'Hisoblash uchun taqqoslanadigan davrlar yetarli emas.', 'Comparable reporting periods are missing for this calculation.'],
  CONFLICTING_SOURCE_VALUES: ['Источники содержат разные значения. Требуется проверка.', 'Manbalardagi qiymatlar farq qiladi. Tekshirish kerak.', 'Source amounts disagree and need review.'],
  CONFLICTING_SOURCE_VERSIONS: ['Версии источника расходятся. Расчёт остановлен.', 'Manba versiyalari farq qiladi.', 'Source versions disagree, so the calculation is blocked.'],
  UNDER_REVIEW: ['Этот период находится на проверке.', 'Bu davr tekshirilmoqda.', 'This period is under review.'],
  AVERAGE_EARNING_ASSETS_MISSING: ['Нет сопоставимой средней базы доходных активов.', 'Daromadli aktivlarning o‘rtacha bazasi yo‘q.', 'A comparable average interest-earning asset base is missing.'],
  INPUTS_MISSING: ['Для формулы не хватает подтверждённых входных данных.', 'Formula uchun tasdiqlangan ma’lumotlar yetarli emas.', 'Verified inputs are missing for this formula.'],
  STOCK_REQUIRES_REPORTING_DATE: ['Балансовый показатель относится к дате, а не TTM.', 'Balans ko‘rsatkichi TTM emas, sanaga tegishli.', 'A balance-sheet measure belongs to a reporting date, not TTM.'],
  STOCK_IS_AS_OF_DATE: ['Остаток показывается на отчётную дату.', 'Qoldiq hisobot sanasiga ko‘rsatiladi.', 'Balances are shown at the reporting date.'],
  NONPOSITIVE_DENOMINATOR: ['Нулевая или отрицательная база не допускает обычный коэффициент.', 'Nol yoki manfiy baza odatiy koeffitsiyentga mos emas.', 'A zero or negative denominator does not support the usual ratio.'],
  NOPAT_OR_INVESTED_CAPITAL_POLICY_MISSING: ['Не подтверждена единая методика NOPAT и задействованного капитала.', 'NOPAT va kapital metodikasi tasdiqlanmagan.', 'A consistent NOPAT and invested-capital policy has not been verified.'],
  FX_EVIDENCE_MISSING: ['Нет подтверждённого курса для этой валюты и даты.', 'Valyuta va sana uchun tasdiqlangan kurs yo‘q.', 'A verified exchange rate is missing for this currency and date.'],
  CODE_LABEL_MISMATCH: ['Код строки не соответствует её названию в этой форме.', 'Qator kodi ushbu shakldagi nomiga mos emas.', 'The row code does not match its label in this form.'],
};

export function qualityReason(code, t) {
  const [key, detail] = String(code || '').split(':');
  const labels = REASONS[key] || (key.startsWith('SOURCE_') && key.endsWith('_MISMATCH')
    ? ['Итоги источника не сходятся. Исходные суммы сохранены.', 'Manba jami mos kelmaydi. Asl summalar saqlangan.', 'Source totals do not reconcile. The original amounts are retained.']
    : ['См. условия расчёта и входные данные в паспорте.', 'Hisoblash shartlari va manba ma’lumotlarini tekshiring.', 'See the formula conditions and source inputs in the passport.']);
  return t(...labels) + (detail ? ` (${detail})` : '');
}
