"""Role and rubric contracts, shared by the workspace and orchestration."""
ROLES = [
    {"id": "cmo", "name": "ИИ-CMO", "department": "strategy", "purpose": "Стратегия, выполнимость и план-факт", "recipient": "Владелец"},
    {"id": "coordinator", "name": "Координатор", "department": "strategy", "purpose": "Задачи, зависимости, сроки и передача результатов", "recipient": "Команда"},
    {"id": "market", "name": "Аналитик рынка", "department": "research", "purpose": "События, рынок и конкуренты с датами и источниками", "recipient": "CMO и редактор"},
    {"id": "pr", "name": "PR-менеджер", "department": "strategy", "purpose": "Позиционирование, голос бренда и факты об основателе", "recipient": "Контент-мейкер"},
    {"id": "news", "name": "Редактор новостей", "department": "content", "purpose": "Отбор событий, объединение перепечаток и дайджесты", "recipient": "Контент-мейкер"},
    {"id": "copywriter", "name": "Контент-мейкер", "department": "content", "purpose": "Отдельные тексты под площадку и язык", "recipient": "Креативщик и редактор качества"},
    {"id": "targeting", "name": "Таргетолог", "department": "growth", "purpose": "Платные гипотезы и эксперименты без самостоятельных расходов", "recipient": "CMO и владелец"},
    {"id": "analytics", "name": "Data / Web-аналитик", "department": "growth", "purpose": "Воронка, стоимость, источники и сравнимые отчёты", "recipient": "CMO"},
    {"id": "creative", "name": "Креативщик", "department": "content", "purpose": "Визуалы, графики, субтитры и доступные файлы", "recipient": "Редактор качества"},
    {"id": "media", "name": "Медиа-аналитик", "department": "research", "purpose": "Зарубежные и местные референсы, приёмы и права", "recipient": "Креативщик"},
    {"id": "quality", "name": "Редактор качества", "department": "content", "purpose": "Проверка оригиналов, цифр, периодов и прав", "recipient": "Очередь или терминальный пропуск"},
]
RUBRICS = [
    {"id": "market", "name": "Итоги торгов", "trigger": "Полная проверенная закрытая сессия"},
    {"id": "news", "name": "Новости UZStock", "trigger": "Подтверждённое независимое событие"},
    {"id": "digest", "name": "Дайджест", "trigger": "Несколько разных подтверждённых событий"},
    {"id": "quarterly", "name": "Квартальный ИИ-разбор", "trigger": "Готовый разбор UZStock и сопоставимые оригиналы"},
    {"id": "dividend", "name": "Дивидендный радар", "trigger": "Новое подтверждённое состояние решения или выплаты"},
    {"id": "calendar", "name": "Календарь недели", "trigger": "Объявленные даты с первоисточником"},
    {"id": "chart", "name": "Один график — один вопрос", "trigger": "Сопоставимый ряд с единицами и периодом"},
]
FORMATS = {
    'telegram': ['post', 'image', 'carousel', 'video'],
    'instagram': ['image', 'carousel', 'video', 'story'],
    'facebook': ['post', 'image', 'carousel', 'video'],
    'linkedin': ['post', 'image', 'carousel', 'video'],
}
PLATFORMS = [
    {"id": "telegram", "name": "Telegram UZStock", "login": "Токен бота и доступ к конкретному каналу"},
    {"id": "instagram", "name": "Instagram UZStock", "login": "Авторизация профессионального аккаунта Meta"},
    {"id": "facebook", "name": "Facebook UZStock", "login": "Авторизация и разрешения страницы Meta"},
    {"id": "linkedin", "name": "Личный LinkedIn", "login": "Отдельная авторизация личного профиля"},
]
PLATFORMS = [{**platform, 'formats': FORMATS[platform['id']]} for platform in PLATFORMS]
