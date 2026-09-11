export const NAVIGATION = [
  { title: ["Операции", "Operatsiyalar", "Operations"], items: [
    ["overview", "dashboard", "Обзор", "Umumiy", "Overview"],
    ["incidents", "alert", "Инциденты", "Hodisalar", "Incidents"],
    ["jobs", "clock", "Задания", "Vazifalar", "Jobs"],
  ] },
  { title: ["Каталог", "Katalog", "Catalog"], items: [
    ["catalog-coverage", "panel", "Полнота каталога", "Katalog qamrovi", "Catalog coverage"],
    ["issuers", "users", "Эмитенты", "Emitentlar", "Issuers"],
    ["documents", "file", "Документы", "Hujjatlar", "Documents"],
    ["sources", "external", "Источники", "Manbalar", "Sources"],
  ] },
  { title: ["Обработка и методика", "Qayta ishlash va usullar", "Processing & methodology"], items: [
    ["parsers", "list", "Парсеры", "Parserlar", "Parsers"],
    ["facts", "list", "Финансовые факты", "Moliyaviy faktlar", "Financial facts"],
    ["mappings", "sliders", "Маппинг", "Moslashtirish", "Mappings"],
    ["formulas", "percent", "Формулы", "Formulalar", "Formulas"],
    ["calculations", "chart", "Расчёты", "Hisob-kitoblar", "Calculations"],
    ["templates", "panel", "ОКЭД и шаблоны", "OKED va shablonlar", "OKED & templates"],
    ["signals", "alert", "Сигналы и решения", "Signallar va yechimlar", "Signals & decisions"],
  ] },
  { title: ["Результат", "Natija", "Results"], items: [
    ["analyses", "search", "AI-анализ", "AI-tahlil", "AI analysis"],
    ["publications", "news", "Публикации", "Nashrlar", "Publications"],
    ["securities", "chart", "Акции и облигации", "Aksiyalar va obligatsiyalar", "Securities"],
  ] },
  { title: ["Управление", "Boshqaruv", "Management"], items: [
    ["audit", "list", "Аудит", "Audit", "Audit trail"],
    ["access", "lock", "Пользователи и роли", "Foydalanuvchilar va rollar", "Access & roles"],
    ["system", "sliders", "Система", "Tizim", "System"],
  ] },
];
export const LEGACY = ["audience", "engagement", "analysis", "users", "feedback", "railway", "companies", "streams", "findings", "intake", "issuer", "rules", "source", "product-overview"];
export const RULE_TYPES = { mappings: "mapping", formulas: "formula", templates: "template", signals: "signal" };
export const COLLECTION = { "catalog-coverage": "coverage", "rules-workspace": "rules", ...Object.fromEntries(Object.keys(RULE_TYPES).map(k => [k, "rules"])) };
export const DEFAULT_RULES = {
  formula: { code: "current_ratio", numerators: ["form1:c320", "form1:c370", "form1:c210", "form1:c140"], denominators: ["form1:c600"], percent: false,
    test_cases: [{ inputs: { "form1:c320": "50", "form1:c370": "50", "form1:c210": "50", "form1:c140": "50", "form1:c600": "100" }, expected: "2" }, { inputs: { "form1:c600": "0" }, expected: null }] },
  parser: { code: "interim_six_months", header_phrase: "Six months ended", duration_months: 6,
    test_cases: [{ document: { standard: "IFRS", published_at: "2026-08-01" }, header: "Six months ended 30 June 2026", expected: { period_end: "2026-06-30", duration_months: 6, statement_type: "interim" } }] },
  mapping: { code: "form1_line_alias", source_line: "form1:c391", target_line: "form1:c390",
    test_cases: [{ snapshot: { organization_type: "non_financial", source_lines: { "form1:c391": { raw_current: "100" } } }, expected: { source_lines: { "form1:c390": { raw_current: "100", original_line: "form1:c391" } } } }] },
  template: { code: "telecom_oked", oked_prefix: "61", template: "telecom",
    test_cases: [{ snapshot: { organization_type: "non_financial" }, issuer: { oked_code: "61100" }, expected: { template_resolution: { selected_template: "telecom", resolution_status: "versioned_oked_rule" } } }] },
  signal: { code: "freshness", max_age_days: 210,
    test_cases: [{ snapshot: {}, expected: { max_age_days: 210 } }] },
};

export const COLUMNS = {
  issuers: ["ticker", "title", "org_id", "special_type", "sector_template", "status"],
  documents: ["ticker", "title", "standard", "period", "detected_format", "status"],
  coverage: ["ticker", "period", "standard", "file_available", "parsed", "verified", "used_in_analysis", "status"],
  parsers: ["ticker", "period", "standard", "parser_version", "rows_mapped", "status"],
  facts: ["ticker", "title", "value", "unit", "period", "status"],
  calculations: ["ticker", "metric_code", "value", "unit", "period", "formula_version", "status"],
  rules: ["title", "category", "created_by", "approved_by", "version", "status"],
  incidents: ["severity", "blocker_code", "ticker", "stage", "impact_count", "status"],
  analyses: ["ticker", "period", "standard", "language", "headline", "status"],
  publications: ["ticker", "period", "standard", "language", "headline", "status"],
  securities: ["ticker", "isin", "instrument_type", "last_price", "market_as_of", "status"],
  sources: ["title", "source", "last_success", "documents", "status"],
  audit: ["created_at", "actor", "action", "entity_id", "reason", "result"],
  jobs: ["category", "ticker", "processed", "total", "attempt", "status"],
  access: ["email", "role", "status", "updated_at"],
};

export const FIELD_LABELS = {
  ticker: ["Тикер", "Tiker", "Ticker"], title: ["Название", "Nomi", "Title"], status: ["Статус", "Holat", "Status"],
  standard: ["Стандарт", "Standart", "Standard"], period: ["Период", "Davr", "Period"],
  detected_format: ["Формат файла", "Fayl formati", "File format"], source: ["Источник", "Manba", "Source"],
  value: ["Значение", "Qiymat", "Value"], unit: ["Единица", "Birlik", "Unit"], metric_code: ["Показатель", "Ko‘rsatkich", "Metric"],
  formula_version: ["Версия формулы", "Formula versiyasi", "Formula version"], parser_version: ["Версия парсера", "Parser versiyasi", "Parser version"],
  special_type: ["Тип организации", "Tashkilot turi", "Organization type"], sector_template: ["Шаблон отрасли", "Tarmoq shabloni", "Sector template"],
  file_available: ["Файл доступен", "Fayl mavjud", "File available"], parsed: ["Прочитан", "O‘qilgan", "Parsed"],
  verified: ["Проверен", "Tekshirilgan", "Verified"], used_in_analysis: ["Использован в анализе", "Tahlilda ishlatilgan", "Used in analysis"],
  rows_mapped: ["Сопоставлено строк", "Moslangan satrlar", "Mapped rows"], category: ["Категория", "Toifa", "Category"],
  created_by: ["Автор", "Muallif", "Author"], approved_by: ["Проверил", "Tasdiqlagan", "Reviewer"], version: ["Версия", "Versiya", "Version"],
  severity: ["Приоритет", "Ustuvorlik", "Severity"], blocker_code: ["Код блокера", "Bloklovchi kodi", "Blocker code"],
  stage: ["Этап", "Bosqich", "Stage"], impact_count: ["Затронуто объектов", "Ta’sirlangan obyektlar", "Affected objects"],
  language: ["Язык", "Til", "Language"], headline: ["Заголовок", "Sarlavha", "Headline"],
  instrument_type: ["Тип инструмента", "Instrument turi", "Instrument type"], last_price: ["Последняя цена", "So‘nggi narx", "Last price"],
  market_as_of: ["Дата котировки", "Kotirovka sanasi", "Quote date"], last_success: ["Последняя синхронизация", "So‘nggi sinxronlash", "Last sync"],
  documents: ["Документы", "Hujjatlar", "Documents"], created_at: ["Создано", "Yaratilgan", "Created"], updated_at: ["Обновлено", "Yangilangan", "Updated"],
  actor: ["Пользователь", "Foydalanuvchi", "Actor"], action: ["Действие", "Amal", "Action"], entity_id: ["Объект", "Obyekt", "Object"],
  reason: ["Причина", "Sabab", "Reason"], result: ["Результат", "Natija", "Result"], processed: ["Обработано", "Qayta ishlangan", "Processed"],
  total: ["Всего", "Jami", "Total"], attempt: ["Попытка", "Urinish", "Attempt"], role: ["Роль", "Rol", "Role"],
  raw_result: ["Точный результат", "Aniq natija", "Unrounded result"], report_period_end: ["Конец периода", "Davr oxiri", "Period end"],
  market_price_at: ["Дата рыночной цены", "Bozor narxi sanasi", "Market price date"], shares_at: ["Дата числа акций", "Aksiyalar soni sanasi", "Share count date"],
};
