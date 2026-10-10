export const NAVIGATION = [
  { title: ["Управление", "Boshqaruv", "Management"], items: [
    ["audit", "list", "Аудит", "Audit", "Audit trail"],
    ["access", "lock", "Пользователи и роли", "Foydalanuvchilar va rollar", "Access & roles"],
    ["feedback", "news", "Обратная связь", "Fikr-mulohaza", "Feedback"],
    ["system", "sliders", "Система", "Tizim", "System"],
  ] },
];
export const LEGACY = ["audience", "engagement", "analysis", "users", "feedback", "companies", "streams", "findings", "intake", "issuer", "rules", "source", "quality", "product-overview"];
export const COLUMNS = {
  audit: ["created_at", "actor", "action", "entity_id", "reason", "result"],
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
