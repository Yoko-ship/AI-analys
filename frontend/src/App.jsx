import React, { useEffect, useState } from "react";

const STORAGE_KEY = "uz_stock_analyzer_token";
const LANGUAGE_KEY = "uz_stock_analyzer_language";
const THEME_KEY = "uz_stock_analyzer_theme";

const TEXTS = {
  ru: {
    pageTitle: "UZ Stock Analyzer",
    brand: "UZ Stock Analyzer",
    subtitle: "Платформа для анализа компаний Узбекистана",
    nav: { main: "Главная", about: "О проекте", auth: "Вход", profile: "Профиль", analysis: "Анализ" },
    languageLabel: "Язык",
    languageOptions: { ru: "Русский", en: "English", uz: "O'zbek" },
    theme: { label: "Тема", light: "Светлая", dark: "Тёмная" },
    hero: {
      title: "Современный анализ компаний в одном интерфейсе",
      copy:
        "Веб-платформа для быстрого анализа компаний: регистрация, вход, профиль, избранное, история и структурированный финансовый отчет с графиками.",
      badges: ["Финансовые отчеты", "Личный кабинет", "Графики и метрики"],
      ctas: { analysis: "Перейти к анализу", profile: "Открыть профиль" },
    },
    dashboard: {
      title: "Панель показателей",
      copy: "Ключевые ориентиры по проекту и вашей активности",
      cards: {
        companies: "Компаний в каталоге",
        analyses: "Всего анализов",
        avgScore: "Средний скор",
        cached: "Из кэша",
      },
      activityTitle: "Активность анализов",
      activityCopy: "Количество анализов за последние 14 дней",
      activityEmpty: "Активность появится после нескольких анализов",
      peak: "Пик",
      trend: "Тренд",
    },
    main: {
      title: "Что делает сервис",
      copy:
        "Платформа объединяет авторизацию, выбор компаний, получение инвестиционного анализа и персональный кабинет пользователя.",
      cards: [
        { title: "Регистрация и вход", copy: "Email/пароль или Google OAuth." },
        { title: "Выбор компании", copy: "По тикеру, через список или поиск." },
        { title: "Финальный отчет", copy: "Оценка, графики, метрики и вывод." },
      ],
      sideTitle: "Почему это удобно",
      sideCards: [
        { title: "Быстрый старт", copy: "Не нужно собирать данные вручную." },
        { title: "Личный кабинет", copy: "История, избранное и статистика." },
        { title: "Понятный результат", copy: "Коротко, профессионально и по цифрам." },
      ],
    },
    about: {
      title: "О проекте",
      leftCards: [
        { title: "Backend", copy: "API, авторизация, Postgres и анализ уже работают как единый слой." },
        { title: "Frontend", copy: "Новая оболочка собрана на React и Vite для более чистой архитектуры." },
        { title: "Подача данных", copy: "Результат подается через карточки, графики и аккуратные аккордеоны." },
      ],
      rightTitle: "Что получает пользователь",
      rightCards: [
        { title: "Оценка", copy: "Общий скор по компании." },
        { title: "Вердикт", copy: "Краткое итоговое заключение." },
        { title: "Метрики", copy: "Piotroski, Altman, Buffett, DCF, Graham и отраслевые сигналы." },
        { title: "История", copy: "Сохраненные анализы и избранные компании." },
      ],
    },
    auth: {
      title: "Вход",
      signedOut: "Вход не выполнен",
      signedIn: "Вход выполнен",
      loginTab: "Вход",
      registerTab: "Регистрация",
      login: { email: "Email", password: "Пароль", submit: "Войти" },
      register: { fullName: "Имя и фамилия", email: "Email", password: "Пароль", submit: "Создать аккаунт" },
      oauthLabel: "Или продолжить через",
      google: "Google",
      logout: "Выйти",
      signedInAs: "Вошли как",
      messages: {
        loginOk: "Вход выполнен",
        registerOk: "Аккаунт создан",
        logoutOk: "Выход выполнен",
        authRequired: "Сначала выполните вход",
      },
    },
    profile: {
      title: "Личный кабинет",
      subtitle: "Профиль, статистика, избранное и история",
      editTitle: "Редактирование профиля",
      name: "Отображаемое имя",
      avatar: "Аватар",
      save: "Сохранить",
      clearAvatar: "Удалить аватар",
      refresh: "Обновить",
      analyze: "Перейти к анализу",
      statsTitle: "Активность",
      favoritesTitle: "Избранное",
      historyTitle: "История анализов",
      stats: {
        totalAnalyses: "Всего анализов",
        analyses7d: "За 7 дней",
        analyses30d: "За 30 дней",
        analyzedCompanies: "Компаний в истории",
        avgScore: "Средний скор",
        bestScore: "Лучшая оценка",
        cachedAnalyses: "Из кэша",
        topCompany: "Чаще всего смотрят",
      },
      empty: "Профиль появится после входа в систему.",
      historyEmpty: "После первого анализа здесь появится история действий.",
      favoritesEmpty: "Добавляйте компании в избранное из анализа или истории.",
      filters: { search: "Поиск по компании или тикеру", all: "Все анализы", favorites: "Только избранное" },
      remove: "Убрать",
    },
    analysis: {
      title: "Анализ компании",
      company: "Компания",
      mode: "Режим",
      quick: "Быстрый",
      full: "Полный",
      includeHtml: "Возвращать HTML-отчет",
      submit: "Анализировать",
      availableTitle: "Доступные компании",
      resultTitle: "Результат",
      resultEmpty: "Анализ еще не выполнен",
      resultLoading: "Анализ выполняется...",
      resultCacheWaiting: "Ожидание",
      resultCacheHit: "Из кэша",
      resultFresh: "Свежий расчет",
      score: "Оценка / 100",
      verdictPlaceholder: "Запустите анализ, чтобы увидеть итоговый вывод.",
      metricsTitle: "Ключевые показатели",
      sectionsTitle: "Разделы отчета",
      favoriteAdd: "В избранное",
      favoriteRemove: "Убрать из избранного",
      chartTitle: "Динамика выручки и прибыли",
      chartEmpty: "График появится после первого анализа.",
      chartMetaEmpty: "Нет данных",
      noData: "Недостаточно данных",
      signalRevenue: "Выручка",
      signalMargin: "Маржа",
      signalRisk: "Риск",
      signalTrend: "Тренд",
      signalLatest: "Последнее",
      signalUp: "Позитивно",
      signalFlat: "Стабильно",
      signalDown: "Под давлением",
      loadingMetrics: "Загрузка",
      loadingChart: "Загрузка графика",
      loadingSections: "Загрузка отчета",
      loadingCache: "Проверка",
      completed: "Анализ завершен",
    },
    toasts: { success: "Готово", error: "Ошибка", info: "Инфо" },
    sections: {
      СКОРИНГ: "Скоринг",
      ДОСЬЕ: "Досье",
      ЧТО_С_ДЕНЬГАМИ: "Что с деньгами",
      ТРЕНД: "Тренд",
      ФИБОНАЧЧИ: "Фибоначчи",
      ОЦЕНКА_ЦЕНЫ: "Оценка цены",
      КАТАЛИЗАТОРЫ: "Катализаторы",
      СИЛЬНЫЕ_СТОРОНЫ: "Сильные стороны",
      СЛАБЫЕ_СТОРОНЫ: "Слабые стороны",
      ВОЗМОЖНОСТИ: "Возможности",
      УГРОЗЫ: "Угрозы",
      ПРОГНОЗ: "Прогноз",
      ВЕРДИКТ: "Вердикт",
      СОВЕТЫ: "Советы",
      ИТОГ: "Итог",
      ЗЕЛЕНЫЕ_ФЛАГИ: "Зеленые флаги",
      КРАСНЫЕ_ФЛАГИ: "Красные флаги",
    },
    metrics: {
      total_score: "Итоговый скор",
      piotroski_f_score: "Piotroski F-Score",
      altman_z_score: "Altman Z-Score",
      buffett_criteria: "Критерии Баффетта",
      graham_number: "Стоимость Грэма",
      dcf: "DCF-оценка",
      industry: "Отрасль",
      market_liquidity: "Ликвидность",
      momentum: "Тренд",
    },
  },
  en: {
    pageTitle: "UZ Stock Analyzer",
    brand: "UZ Stock Analyzer",
    subtitle: "Company analysis platform for Uzbekistan",
    nav: { main: "Main", about: "About", auth: "Sign in", profile: "Profile", analysis: "Analysis" },
    languageLabel: "Language",
    languageOptions: { ru: "Russian", en: "English", uz: "Uzbek" },
    theme: { label: "Theme", light: "Light", dark: "Dark" },
    hero: {
      title: "Modern company analysis in one dashboard",
      copy: "A web platform for fast company analysis, authentication, profile management, favorites, history, and financial reporting with charts.",
      badges: ["Financial reports", "Personal dashboard", "Charts and metrics"],
      ctas: { analysis: "Go to analysis", profile: "Open profile" },
    },
    dashboard: {
      title: "Dashboard",
      copy: "Project-wide metrics and your recent activity",
      cards: {
        companies: "Companies in catalog",
        analyses: "Total analyses",
        avgScore: "Average score",
        cached: "From cache",
      },
      activityTitle: "Analysis activity",
      activityCopy: "Analyses completed over the last 14 days",
      activityEmpty: "Activity will appear after a few analyses",
      peak: "Peak",
      trend: "Trend",
    },
    main: {
      title: "What the service does",
      copy: "The platform combines authentication, company selection, investment analysis, and a personal user dashboard.",
      cards: [
        { title: "Registration and sign in", copy: "Email/password or Google OAuth." },
        { title: "Company selection", copy: "By ticker, via list, or by search." },
        { title: "Final report", copy: "Score, charts, metrics, and verdict." },
      ],
      sideTitle: "Why it matters",
      sideCards: [
        { title: "Fast start", copy: "No need to gather data manually." },
        { title: "Personal dashboard", copy: "History, favorites, and activity." },
        { title: "Readable output", copy: "Short, professional, and numeric." },
      ],
    },
    about: {
      title: "About the project",
      leftCards: [
        { title: "Backend", copy: "API, auth, Postgres, and analysis already work as one layer." },
        { title: "Frontend", copy: "The new shell is built with React and Vite." },
        { title: "Delivery", copy: "Results are shown through cards, charts, and clean accordions." },
      ],
      rightTitle: "What the user gets",
      rightCards: [
        { title: "Score", copy: "One main score for quick orientation." },
        { title: "Verdict", copy: "A short final recommendation." },
        { title: "Metrics", copy: "Piotroski, Altman, Buffett, DCF, Graham, and sector signals." },
        { title: "History", copy: "Saved analyses and favorite companies." },
      ],
    },
    auth: {
      title: "Sign in",
      signedOut: "Not signed in",
      signedIn: "Signed in",
      loginTab: "Sign in",
      registerTab: "Register",
      login: { email: "Email", password: "Password", submit: "Sign in" },
      register: { fullName: "Full name", email: "Email", password: "Password", submit: "Create account" },
      oauthLabel: "Or continue with",
      google: "Google",
      logout: "Log out",
      signedInAs: "Signed in as",
      messages: {
        loginOk: "Signed in",
        registerOk: "Account created",
        logoutOk: "Signed out",
        authRequired: "Please sign in first",
      },
    },
    profile: {
      title: "Profile",
      subtitle: "Profile, statistics, favorites, and history",
      editTitle: "Edit profile",
      name: "Display name",
      avatar: "Avatar",
      save: "Save",
      clearAvatar: "Remove avatar",
      refresh: "Refresh",
      analyze: "Go to analysis",
      statsTitle: "Activity",
      favoritesTitle: "Favorites",
      historyTitle: "Analysis history",
      stats: {
        totalAnalyses: "Total analyses",
        analyses7d: "Last 7 days",
        analyses30d: "Last 30 days",
        analyzedCompanies: "Companies in history",
        avgScore: "Average score",
        bestScore: "Best score",
        cachedAnalyses: "From cache",
        topCompany: "Most viewed",
      },
      empty: "Profile appears after sign in.",
      historyEmpty: "Your activity history will appear after the first analysis.",
      favoritesEmpty: "Add companies to favorites from analysis or history.",
      filters: { search: "Search by company or ticker", all: "All analyses", favorites: "Favorites only" },
      remove: "Remove",
    },
    analysis: {
      title: "Company analysis",
      company: "Company",
      mode: "Mode",
      quick: "Quick",
      full: "Full",
      includeHtml: "Return HTML report",
      submit: "Analyze",
      availableTitle: "Available companies",
      resultTitle: "Result",
      resultEmpty: "No analysis yet",
      resultLoading: "Running analysis...",
      resultCacheWaiting: "Waiting",
      resultCacheHit: "From cache",
      resultFresh: "Fresh result",
      score: "Score / 100",
      verdictPlaceholder: "Run analysis to see the final verdict.",
      metricsTitle: "Key metrics",
      sectionsTitle: "Report sections",
      favoriteAdd: "Add to favorites",
      favoriteRemove: "Remove from favorites",
      chartTitle: "Revenue and profit trend",
      chartEmpty: "The chart appears after the first analysis.",
      chartMetaEmpty: "No data",
      noData: "No data",
      signalRevenue: "Revenue",
      signalMargin: "Margin",
      signalRisk: "Risk",
      signalTrend: "Trend",
      signalLatest: "Latest",
      signalUp: "Positive",
      signalFlat: "Stable",
      signalDown: "Under pressure",
      loadingMetrics: "Loading",
      loadingChart: "Loading chart",
      loadingSections: "Loading report",
      loadingCache: "Checking",
      completed: "Analysis completed",
    },
    toasts: { success: "Done", error: "Error", info: "Info" },
    sections: {
      СКОРИНГ: "Scoring",
      ДОСЬЕ: "Dossier",
      ЧТО_С_ДЕНЬГАМИ: "Finances",
      ТРЕНД: "Trend",
      ФИБОНАЧЧИ: "Fibonacci",
      ОЦЕНКА_ЦЕНЫ: "Price check",
      КАТАЛИЗАТОРЫ: "Catalysts",
      СИЛЬНЫЕ_СТОРОНЫ: "Strengths",
      СЛАБЫЕ_СТОРОНЫ: "Weaknesses",
      ВОЗМОЖНОСТИ: "Opportunities",
      УГРОЗЫ: "Threats",
      ПРОГНОЗ: "Forecast",
      ВЕРДИКТ: "Verdict",
      СОВЕТЫ: "Recommendations",
      ИТОГ: "Summary",
      ЗЕЛЕНЫЕ_ФЛАГИ: "Green flags",
      КРАСНЫЕ_ФЛАГИ: "Red flags",
    },
    metrics: {
      total_score: "Total score",
      piotroski_f_score: "Piotroski F-Score",
      altman_z_score: "Altman Z-Score",
      buffett_criteria: "Buffett criteria",
      graham_number: "Graham value",
      dcf: "DCF valuation",
      industry: "Industry",
      market_liquidity: "Liquidity",
      momentum: "Trend",
    },
  },
  uz: {
    pageTitle: "UZ Stock Analyzer",
    brand: "UZ Stock Analyzer",
    subtitle: "O'zbekiston kompaniyalarini tahlil qilish platformasi",
    nav: { main: "Bosh sahifa", about: "Loyiha haqida", auth: "Kirish", profile: "Profil", analysis: "Tahlil" },
    languageLabel: "Til",
    languageOptions: { ru: "Ruscha", en: "English", uz: "O'zbek" },
    theme: { label: "Mavzu", light: "Yorug'", dark: "Qorong'i" },
    hero: {
      title: "Bitta panelda zamonaviy kompaniya tahlili",
      copy: "Kompaniyalarni tez tahlil qilish uchun veb-platforma: ro'yxatdan o'tish, kirish, profil, tanlanganlar, tarix va grafiklar bilan moliyaviy hisobot.",
      badges: ["Moliyaviy hisobotlar", "Shaxsiy kabinet", "Grafiklar va metrikalar"],
      ctas: { analysis: "Tahlilga o'tish", profile: "Profilni ochish" },
    },
    dashboard: {
      title: "Ko'rsatkichlar paneli",
      copy: "Loyiha bo'yicha asosiy ko'rsatkichlar va faollik",
      cards: {
        companies: "Katalogdagi kompaniyalar",
        analyses: "Jami tahlillar",
        avgScore: "O'rtacha baho",
        cached: "Keshdan",
      },
      activityTitle: "Tahlil faolligi",
      activityCopy: "So'nggi 14 kun ichidagi tahlillar soni",
      activityEmpty: "Bir nechta tahlildan keyin faollik ko'rinadi",
      peak: "Cho'qqi",
      trend: "Trend",
    },
    main: {
      title: "Xizmat nima qiladi",
      copy: "Platforma avtorizatsiya, kompaniya tanlash, tahlil va shaxsiy kabinetni bir joyga jamlaydi.",
      cards: [
        { title: "Ro'yxatdan o'tish va kirish", copy: "Email/parol yoki Google OAuth." },
        { title: "Kompaniya tanlash", copy: "Ticker, ro'yxat yoki qidiruv orqali." },
        { title: "Yakuniy hisobot", copy: "Baho, grafiklar, metrikalar va xulosa." },
      ],
      sideTitle: "Nega bu qulay",
      sideCards: [
        { title: "Tez boshlash", copy: "Ma'lumotni qo'lda yig'ish shart emas." },
        { title: "Shaxsiy kabinet", copy: "Tarix, tanlanganlar va faollik." },
        { title: "O'qilishi oson natija", copy: "Qisqa, professional va raqamli." },
      ],
    },
    about: {
      title: "Loyiha haqida",
      leftCards: [
        { title: "Backend", copy: "API, avtorizatsiya, Postgres va tahlil bitta qatlam sifatida ishlaydi." },
        { title: "Frontend", copy: "Yangi interfeys React va Vite asosida yig'ilgan." },
        { title: "Taqdimot", copy: "Natija kartalar, grafiklar va ixcham akкордеonlar orqali ko'rsatiladi." },
      ],
      rightTitle: "Foydalanuvchi nimani oladi",
      rightCards: [
        { title: "Baho", copy: "Tez orientatsiya uchun yagona ko'rsatkich." },
        { title: "Xulosa", copy: "Qisqa yakuniy tavsiya." },
        { title: "Metrikalar", copy: "Piotroski, Altman, Buffett, DCF, Graham va sektor signallari." },
        { title: "Tarix", copy: "Saqlangan tahlillar va tanlangan kompaniyalar." },
      ],
    },
    auth: {
      title: "Kirish",
      signedOut: "Kirish yo'q",
      signedIn: "Kirish amalga oshirildi",
      loginTab: "Kirish",
      registerTab: "Ro'yxatdan o'tish",
      login: { email: "Email", password: "Parol", submit: "Kirish" },
      register: { fullName: "Ism va familiya", email: "Email", password: "Parol", submit: "Akkaunt yaratish" },
      oauthLabel: "Yoki davom eting",
      google: "Google",
      logout: "Chiqish",
      signedInAs: "Kirish amalga oshirildi",
      messages: {
        loginOk: "Kirish amalga oshirildi",
        registerOk: "Akkaunt yaratildi",
        logoutOk: "Chiqish amalga oshirildi",
        authRequired: "Avval tizimga kiring",
      },
    },
    profile: {
      title: "Profil",
      subtitle: "Profil, statistika, tanlanganlar va tarix",
      editTitle: "Profilni tahrirlash",
      name: "Ko'rinadigan ism",
      avatar: "Avatar",
      save: "Saqlash",
      clearAvatar: "Avatarni o'chirish",
      refresh: "Yangilash",
      analyze: "Tahlilga o'tish",
      statsTitle: "Faollik",
      favoritesTitle: "Tanlanganlar",
      historyTitle: "Tahlillar tarixi",
      stats: {
        totalAnalyses: "Jami tahlillar",
        analyses7d: "7 kun ichida",
        analyses30d: "30 kun ichida",
        analyzedCompanies: "Tarixdagi kompaniyalar",
        avgScore: "O'rtacha baho",
        bestScore: "Eng yaxshi baho",
        cachedAnalyses: "Keshdan",
        topCompany: "Eng ko'p ko'rilgan",
      },
      empty: "Profil tizimga kirgandan keyin ko'rinadi.",
      historyEmpty: "Birinchi tahlildan keyin bu yerda tarix paydo bo'ladi.",
      favoritesEmpty: "Tahlil yoki tarixdan kompaniyalarni tanlanganlarga qo'shing.",
      filters: { search: "Kompaniya yoki ticker bo'yicha qidirish", all: "Barcha tahlillar", favorites: "Faqat tanlanganlar" },
      remove: "O'chirish",
    },
    analysis: {
      title: "Kompaniya tahlili",
      company: "Kompaniya",
      mode: "Rejim",
      quick: "Tez",
      full: "To'liq",
      includeHtml: "HTML hisobotni qaytarish",
      submit: "Tahlil qilish",
      availableTitle: "Mavjud kompaniyalar",
      resultTitle: "Natija",
      resultEmpty: "Tahlil hali bajarilmagan",
      resultLoading: "Tahlil bajarilmoqda...",
      resultCacheWaiting: "Kutilmoqda",
      resultCacheHit: "Keshdan",
      resultFresh: "Yangi natija",
      score: "Baho / 100",
      verdictPlaceholder: "Yakuniy xulosani ko'rish uchun tahlilni ishga tushiring.",
      metricsTitle: "Asosiy ko'rsatkichlar",
      sectionsTitle: "Hisobot bo'limlari",
      favoriteAdd: "Tanlanganlarga qo'shish",
      favoriteRemove: "Tanlanganlardan olib tashlash",
      chartTitle: "Tushum va foyda dinamikasi",
      chartEmpty: "Grafik birinchi tahlildan so'ng paydo bo'ladi.",
      chartMetaEmpty: "Ma'lumot yo'q",
      noData: "Ma'lumot yo'q",
      signalRevenue: "Tushum",
      signalMargin: "Marja",
      signalRisk: "Risk",
      signalTrend: "Trend",
      signalLatest: "So'nggi",
      signalUp: "Ijobiy",
      signalFlat: "Barqaror",
      signalDown: "Bosim ostida",
      loadingMetrics: "Yuklanmoqda",
      loadingChart: "Grafik yuklanmoqda",
      loadingSections: "Hisobot yuklanmoqda",
      loadingCache: "Tekshirilmoqda",
      completed: "Tahlil yakunlandi",
    },
    toasts: { success: "Tayyor", error: "Xato", info: "Ma'lumot" },
    sections: {
      СКОРИНГ: "Baho",
      ДОСЬЕ: "Dossier",
      ЧТО_С_ДЕНЬГАМИ: "Moliyaviy holat",
      ТРЕНД: "Trend",
      ФИБОНАЧЧИ: "Fibonachchi",
      ОЦЕНКА_ЦЕНЫ: "Narx bahosi",
      КАТАЛИЗАТОРЫ: "Katalizatorlar",
      СИЛЬНЫЕ_СТОРОНЫ: "Kuchli tomonlar",
      СЛАБЫЕ_СТОРОНЫ: "Zaif tomonlar",
      ВОЗМОЖНОСТИ: "Imkoniyatlar",
      УГРОЗЫ: "Xavflar",
      ПРОГНОЗ: "Prognoz",
      ВЕРДИКТ: "Xulosa",
      СОВЕТЫ: "Tavsiyalar",
      ИТОГ: "Yakun",
      ЗЕЛЕНЫЕ_ФЛАГИ: "Yashil belgilar",
      КРАСНЫЕ_ФЛАГИ: "Qizil belgilar",
    },
    metrics: {
      total_score: "Yakuniy baho",
      piotroski_f_score: "Piotroski F-Score",
      altman_z_score: "Altman Z-Score",
      buffett_criteria: "Baffet mezonlari",
      graham_number: "Grem qiymati",
      dcf: "DCF baholash",
      industry: "Sektor",
      market_liquidity: "Likvidlik",
      momentum: "Trend",
    },
  },
};

function normalizeLanguage(value) {
  return ["ru", "en", "uz"].includes(value) ? value : "ru";
}

function t(language, path, params = {}) {
  const lang = normalizeLanguage(language);
  const parts = path.split(".");
  const resolve = (obj) => {
    let current = obj;
    for (const part of parts) {
      current = current?.[part];
    }
    return current;
  };
  let value = resolve(TEXTS[lang]) ?? resolve(TEXTS.ru);
  if (value === undefined || value === null) return "";
  const stringValue = String(value);
  return stringValue.replace(/\{(\w+)\}/g, (_, key) => String(params[key] ?? ""));
}

function safeNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function formatDateLabel(value, language) {
  if (!value) return t(language, "analysis.noData");
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return t(language, "analysis.noData");
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.DateTimeFormat(locale, { day: "2-digit", month: "long", year: "numeric" }).format(date);
}

function formatCompactNumber(value, language, digits = 1) {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.NumberFormat(locale, {
    notation: Math.abs(num) >= 1000 ? "compact" : "standard",
    maximumFractionDigits: digits,
  }).format(num);
}

function formatSignedPercent(value, digits = 1) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const fixed = Number(num.toFixed(digits));
  return `${fixed > 0 ? "+" : ""}${fixed}%`;
}

function formatRatio(value, digits = 2, language = "ru") {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(num);
}

function getSectionTitle(language, key) {
  return t(language, `sections.${key}`) || key.replaceAll("_", " ");
}

function getProfileInitials(user) {
  const source = (user?.full_name || user?.email || "?").trim();
  const parts = source.split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  const first = parts[0][0] || "";
  const second = parts.length > 1 ? parts[1][0] : parts[0][1] || "";
  return (first + second).toUpperCase();
}

function hashToHue(source) {
  return String(source || "").split("").reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) % 360, 47);
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read image"));
    reader.readAsDataURL(file);
  });
}

function buildSeriesChart(series, language) {
  const points = Array.isArray(series) ? series : [];
  const filtered = points
    .map((row) => ({
      year: row?.year,
      revenue: safeNumber(row?.revenue),
      profit: safeNumber(row?.net_income),
    }))
    .filter((row) => row.year !== undefined && row.year !== null && (row.revenue !== null || row.profit !== null));

  if (filtered.length < 2) return null;

  const width = 1000;
  const height = 340;
  const padding = { left: 74, right: 24, top: 28, bottom: 44 };
  const allValues = filtered.flatMap((row) => [row.revenue, row.profit]).filter((value) => Number.isFinite(value));
  let min = Math.min(...allValues);
  let max = Math.max(...allValues);
  if (min > 0) min = 0;
  if (max < 0) max = 0;
  const range = max - min === 0 ? 1 : max - min;
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const x = (index) => padding.left + (filtered.length <= 1 ? innerWidth / 2 : (index / (filtered.length - 1)) * innerWidth);
  const y = (value) => padding.top + ((max - value) / range) * innerHeight;
  const line = (arr) =>
    arr
      .map((point, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(2)} ${y(Number.isFinite(point) ? point : min).toFixed(2)}`)
      .join(" ");

  const revenuePoints = filtered.map((row) => row.revenue ?? min);
  const profitPoints = filtered.map((row) => row.profit ?? min);
  const revenuePath = line(revenuePoints);
  const profitPath = line(profitPoints);
  const zeroY = y(0);
  const areaPath = `${revenuePath} L ${x(filtered.length - 1).toFixed(2)} ${zeroY.toFixed(2)} L ${x(0).toFixed(2)} ${zeroY.toFixed(2)} Z`;

  const yTicks = Array.from({ length: 5 }, (_, idx) => {
    const ratio = idx / 4;
    const value = max - ratio * range;
    const yy = padding.top + ratio * innerHeight;
    return { value, y: yy };
  });

  const latest = filtered.at(-1);
  const previous = filtered.at(-2) || {};
  const revenueChange =
    Number.isFinite(latest.revenue) && Number.isFinite(previous.revenue)
      ? ((latest.revenue - previous.revenue) / Math.abs(previous.revenue || 1)) * 100
      : null;
  const profitChange =
    Number.isFinite(latest.profit) && Number.isFinite(previous.profit)
      ? ((latest.profit - previous.profit) / Math.abs(previous.profit || 1)) * 100
      : null;

  return {
    width,
    height,
    filtered,
    areaPath,
    revenuePath,
    profitPath,
    yTicks,
    latest,
    revenueChange,
    profitChange,
    x,
    y,
  };
}

function buildActivitySeries(entries, language) {
  const items = Array.isArray(entries) ? entries : [];
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  const dayMap = new Map();
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const keyFor = (date) =>
    [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0"),
    ].join("-");

  for (let offset = 13; offset >= 0; offset -= 1) {
    const date = new Date(now);
    date.setDate(now.getDate() - offset);
    const key = keyFor(date);
    dayMap.set(key, {
      key,
      label: new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }).format(date),
      shortLabel: new Intl.DateTimeFormat(locale, { weekday: "short" }).format(date),
      count: 0,
    });
  }

  for (const item of items) {
    const createdAt = item?.created_at;
    if (!createdAt) continue;
    const date = new Date(createdAt);
    if (Number.isNaN(date.getTime())) continue;
    date.setHours(0, 0, 0, 0);
    const key = keyFor(date);
    const bucket = dayMap.get(key);
    if (!bucket) continue;
    bucket.count += 1;
  }

  const days = Array.from(dayMap.values());
  const maxCount = Math.max(1, ...days.map((day) => day.count || 0));
  const total = days.reduce((sum, day) => sum + (day.count || 0), 0);
  const peak = days.reduce((best, day) => (day.count > (best?.count || 0) ? day : best), days[0] || null);

  return { days, maxCount, total, peak };
}

function ToastStack({ toasts, onDismiss, language }) {
  return (
    <div className="toast-stack" aria-live="polite" aria-atomic="true">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.tone} show`}>
          <div className="toast-label">{toast.tone === "error" ? t(language, "toasts.error") : toast.tone === "success" ? t(language, "toasts.success") : t(language, "toasts.info")}</div>
          <div className="toast-message">{toast.message}</div>
          <button className="toast-close" type="button" onClick={() => onDismiss(toast.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

function StatCard({ label, value, sub }) {
  return (
    <article className="profile-stat-card">
      <div className="profile-stat-label">{label}</div>
      <div className="profile-stat-value">{value}</div>
      <div className="profile-stat-sub">{sub}</div>
    </article>
  );
}

function MetricCard({ label, value, sub, tone = "warning" }) {
  return (
    <article className={`metric-card metric-${tone}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-sub">{sub}</div>
    </article>
  );
}

function SectionCard({ title, body, index, open = false }) {
  return (
    <details className="section-card fade-in" open={open}>
      <summary>
        <span>{title}</span>
        <span className="muted">#{String(index + 1).padStart(2, "0")}</span>
      </summary>
      <div className="section-content">{body}</div>
    </details>
  );
}

function App() {
  const [language, setLanguage] = useState(() => normalizeLanguage(localStorage.getItem(LANGUAGE_KEY) || "ru"));
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  const [token, setToken] = useState(() => localStorage.getItem(STORAGE_KEY) || "");
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [activeView, setActiveView] = useState("main");
  const [authTab, setAuthTab] = useState("login");
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [registerForm, setRegisterForm] = useState({ full_name: "", email: "", password: "" });
  const [authMessage, setAuthMessage] = useState("");
  const [analysisCompany, setAnalysisCompany] = useState("");
  const [includeHtml, setIncludeHtml] = useState(true);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisMessage, setAnalysisMessage] = useState("");
  const [profileForm, setProfileForm] = useState({ full_name: "" });
  const [profileAvatarFile, setProfileAvatarFile] = useState(null);
  const [profileAvatarPreview, setProfileAvatarPreview] = useState("");
  const [profileAvatarCleared, setProfileAvatarCleared] = useState(false);
  const [historySearch, setHistorySearch] = useState("");
  const [historyMode, setHistoryMode] = useState("all");
  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    const lang = normalizeLanguage(language);
    localStorage.setItem(LANGUAGE_KEY, lang);
    document.documentElement.lang = lang;
    document.title = t(lang, "pageTitle");
  }, [language]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.body.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    const themeMeta = document.querySelector('meta[name="theme-color"]');
    if (themeMeta) {
      themeMeta.setAttribute("content", theme === "dark" ? "#07111f" : "#f4f7fb");
    }
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const oauthError = hash.get("oauth_error") || hash.get("error");
    const oauthToken = hash.get("token");
    const provider = hash.get("provider") || hash.get("oauth");

    if (oauthError) {
      addToast(decodeURIComponent(oauthError.replace(/\+/g, " ")), "error");
      clearHash();
    } else if (oauthToken) {
      setToken(oauthToken);
      localStorage.setItem(STORAGE_KEY, oauthToken);
      const providerLabel = provider === "google" ? "Google" : provider || "";
      addToast(providerLabel ? `${providerLabel}: ${t(language, "auth.messages.loginOk")}` : t(language, "auth.messages.loginOk"), "success");
      clearHash();
      setActiveView("profile");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadCompanies().catch((error) => {
      addToast(error.message, "error");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language]);

  useEffect(() => {
    if (!token) {
      setUser(null);
      setProfile(null);
      setAnalysisResult(null);
      return;
    }
    refreshSession().catch(() => {
      setToken("");
      localStorage.removeItem(STORAGE_KEY);
      setUser(null);
      setProfile(null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (!user) return;
    loadProfile().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, language]);

  useEffect(() => {
    if (profile?.user?.full_name || profile?.user?.email) {
      setProfileForm((prev) =>
        prev.full_name && prev.full_name !== ""
          ? prev
          : {
              full_name: profile.user.full_name || "",
            }
      );
    }
  }, [profile]);

  useEffect(() => {
    setHistorySearch("");
  }, [activeView]);

  const addToast = (message, tone = "info") => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setToasts((current) => [...current, { id, message, tone }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, 3600);
  };

  const clearHash = () => {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  };

  const apiFetch = async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    return fetch(path, { ...options, headers });
  };

  const refreshSession = async () => {
    if (!token) return;
    const res = await apiFetch("/api/auth/me");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Session is invalid");
    setUser(data.user);
  };

  const loadCompanies = async () => {
    const res = await apiFetch("/api/companies");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not load companies");
    setCompanies(data.companies || []);
  };

  const loadProfile = async () => {
    if (!token) return;
    const res = await apiFetch("/api/profile");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not load profile");
    setProfile(data);
    if (data?.user) {
      setProfileForm({ full_name: data.user.full_name || "" });
    }
    return data;
  };

  const setAuthSuccess = (data) => {
    if (data.token) {
      setToken(data.token);
      localStorage.setItem(STORAGE_KEY, data.token);
    }
    if (data.user) {
      setUser(data.user);
      setProfileForm({ full_name: data.user.full_name || "" });
    }
    setAuthMessage(t(language, "auth.messages.loginOk"));
    addToast(t(language, "auth.messages.loginOk"), "success");
    setActiveView("profile");
  };

  const handleLogin = async (event) => {
    event.preventDefault();
    setAuthMessage("...");
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(loginForm),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Request failed");
      setAuthSuccess(data);
      setAuthMessage(t(language, "auth.messages.loginOk"));
      await loadProfile();
    } catch (error) {
      setAuthMessage(error.message);
      addToast(error.message, "error");
    }
  };

  const handleRegister = async (event) => {
    event.preventDefault();
    setAuthMessage("...");
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(registerForm),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Request failed");
      setAuthSuccess(data);
      setAuthMessage(t(language, "auth.messages.registerOk"));
      await loadProfile();
    } catch (error) {
      setAuthMessage(error.message);
      addToast(error.message, "error");
    }
  };

  const handleGoogleLogin = () => {
    window.location.href = "/api/auth/oauth/google/start";
  };

  const handleLogout = async () => {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch {
      // ignore
    }
    localStorage.removeItem(STORAGE_KEY);
    setToken("");
    setUser(null);
    setProfile(null);
    setAnalysisResult(null);
    setActiveView("auth");
    addToast(t(language, "auth.messages.logoutOk"), "info");
  };

  const handleAnalysisSubmit = async (event) => {
    event.preventDefault();
    const company = analysisCompany.trim();
    if (!token) {
      addToast(t(language, "auth.messages.authRequired"), "error");
      setActiveView("auth");
      return;
    }
    if (!company) {
      addToast(t(language, "analysis.resultEmpty"), "error");
      return;
    }

    setAnalysisLoading(true);
    setAnalysisMessage(t(language, "analysis.resultLoading"));
    try {
      const res = await apiFetch("/api/analyze", {
        method: "POST",
        body: JSON.stringify({
          company,
          language,
          include_html: includeHtml,
          include_raw: false,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not complete the analysis");
      setAnalysisResult(data);
      setAnalysisMessage(t(language, "analysis.completed"));
      addToast(`${t(language, "analysis.completed")}: ${data.company_name || company}`, "success");
      setActiveView("analysis");
      await loadProfile();
    } catch (error) {
      addToast(error.message, "error");
      setAnalysisMessage(error.message);
      setAnalysisResult(null);
    } finally {
      setAnalysisLoading(false);
    }
  };

  const handleToggleFavorite = async (ticker, companyName = "") => {
    if (!token) {
      addToast(t(language, "auth.messages.authRequired"), "error");
      setActiveView("auth");
      return;
    }
    const normalized = String(ticker || "").trim();
    if (!normalized) return;
    try {
      const res = await apiFetch("/api/favorites/toggle", {
        method: "POST",
        body: JSON.stringify({ ticker: normalized, company_name: companyName || undefined }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not update favorites");
      addToast(`${normalized} ${data.favorited ? "saved" : "removed"}`, "success");
      await loadProfile();
    } catch (error) {
      addToast(error.message, "error");
    }
  };

  const handleProfileSave = async (event) => {
    event.preventDefault();
    if (!token) {
      addToast(t(language, "auth.messages.authRequired"), "error");
      return;
    }

    const payload = {};
    const nextName = profileForm.full_name.trim();
    const currentName = user?.full_name?.trim() || "";

    if (nextName !== currentName) {
      payload.full_name = nextName;
    }

    if (profileAvatarFile) {
      payload.avatar_data_url = await readFileAsDataUrl(profileAvatarFile);
    } else if (profileAvatarCleared) {
      payload.avatar_data_url = null;
    }

    if (!Object.keys(payload).length) {
      addToast("No changes", "info");
      return;
    }

    try {
      const res = await apiFetch("/api/profile", {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not save profile");
      setUser(data.user);
      setProfileAvatarFile(null);
      setProfileAvatarPreview("");
      setProfileAvatarCleared(false);
      setProfileForm({ full_name: data.user.full_name || "" });
      addToast(t(language, "profile.save"), "success");
      await loadProfile();
    } catch (error) {
      addToast(error.message, "error");
    }
  };

  const filteredCompanies = companies
    .filter((item) => {
      const q = analysisCompany.trim().toLowerCase();
      if (!q) return true;
      return item.ticker.toLowerCase().includes(q) || item.company_name.toLowerCase().includes(q);
    })
    .slice(0, 16);

  const resolveTicker = (value) => {
    const normalized = String(value || "").trim();
    if (!normalized) return "";
    const upper = normalized.toUpperCase();
    const match = companies.find((item) => item.ticker.toUpperCase() === upper || item.company_name.toLowerCase() === normalized.toLowerCase());
    return match?.ticker || upper;
  };

  const favoriteTickers = new Set((profile?.favorites || []).map((item) => String(item?.ticker || "").trim().toUpperCase()).filter(Boolean));
  const recentAnalyses = (profile?.recent_analyses || []).filter((item) => {
    const match = `${item?.company_name || ""} ${item?.company_input || ""} ${item?.ticker || ""}`.toLowerCase().includes(historySearch.trim().toLowerCase());
    const fav = !favoriteTickers.size || favoriteTickers.has(String(item?.ticker || "").trim().toUpperCase());
    return match && (historyMode === "favorites" ? fav : true);
  });

  const chartData = buildSeriesChart(analysisResult?.ifrs_snapshot?.series?.annual || [], language);
  const analysisLabel = analysisResult?.company_name || analysisResult?.input || t(language, "analysis.resultEmpty");
  const analysisTicker = analysisResult?.ticker || resolveTicker(analysisResult?.input || analysisCompany || analysisResult?.company_name);
  const resultScore = analysisResult?.summary?.score ?? analysisResult?.metrics?.total_score?.score ?? null;
  const resultGrade = analysisResult?.summary?.grade ?? analysisResult?.metrics?.total_score?.grade ?? "—";
  const resultVerdict = analysisResult?.summary?.verdict ?? "";
  const resultSummary = analysisResult?.summary?.itog ?? analysisResult?.summary?.score_summary ?? "";
  const resultCacheText = analysisResult ? (analysisResult.from_cache ? t(language, "analysis.resultCacheHit") : t(language, "analysis.resultFresh")) : t(language, "analysis.resultCacheWaiting");

  const metricCards = (() => {
    if (!analysisResult?.metrics) return [];
    const metrics = analysisResult.metrics;
    const cards = [];
    const push = (label, value, sub, tone = "warning") => {
      if (value === undefined || value === null || value === "") return;
      cards.push({ label, value, sub, tone });
    };

    const total = metrics.total_score || {};
    push(t(language, "metrics.total_score"), total.score ?? "—", total.summary || total.grade || "", total.score >= 70 ? "good" : total.score >= 45 ? "warning" : "danger");
    const piotroski = metrics.piotroski_f_score || {};
    push(t(language, "metrics.piotroski_f_score"), `${piotroski.score ?? "—"}/9`, piotroski.verdict || "", piotroski.score >= 7 ? "good" : piotroski.score >= 4 ? "warning" : "danger");
    const altman = metrics.altman_z_score || {};
    push(t(language, "metrics.altman_z_score"), altman.score ?? "—", altman.verdict || "", altman.score > 2.99 ? "good" : altman.score > 1.81 ? "warning" : "danger");
    const buffett = metrics.buffett_criteria || {};
    push(t(language, "metrics.buffett_criteria"), `${buffett.passed ?? "—"}/${buffett.total ?? "—"}`, buffett.verdict || "", buffett.passed >= 4 ? "good" : buffett.passed >= 2 ? "warning" : "danger");
    const graham = metrics.graham_number || {};
    push(
      t(language, "metrics.graham_number"),
      graham.graham_number ?? graham.value ?? "—",
      [graham.verdict, graham.upside_pct != null ? `${graham.upside_pct}% ${language === "ru" ? "потенциал" : language === "uz" ? "salohiyat" : "upside"}` : ""].filter(Boolean).join(" · "),
      graham.upside_pct > 0 ? "good" : "warning"
    );
    const dcf = metrics.dcf || {};
    push(t(language, "metrics.dcf"), dcf.intrinsic_value_bn ?? "—", dcf.verdict || dcf.signal || "", dcf.signal === "bullish" ? "good" : dcf.signal === "bearish" ? "danger" : "warning");
    const industry = metrics.industry || {};
    push(
      t(language, "metrics.industry"),
      industry.sector_name ?? "—",
      [industry.verdict || "", `${industry.good_count ?? 0} / ${industry.weak_count ?? 0}`].filter(Boolean).join(" · "),
      industry.good_count > industry.weak_count ? "good" : "warning"
    );
    const liquidity = metrics.market_liquidity || {};
    push(
      t(language, "metrics.market_liquidity"),
      liquidity.liquidity_label ?? "—",
      [`${t(language, "analysis.signalLatest")}: ${liquidity.trade_days ?? "—"}/30`, liquidity.avg_trade_value ? formatCompactNumber(liquidity.avg_trade_value, language) : ""].filter(Boolean).join(" · "),
      liquidity.liquidity_label === "high" ? "good" : "warning"
    );
    const momentum = metrics.momentum || {};
    push(t(language, "metrics.momentum"), momentum.overall || "—", momentum.acceleration || "", momentum.css === "bullish" ? "good" : momentum.css === "bearish" ? "danger" : "warning");
    return cards;
  })();

  const profileStats = profile?.stats || {};
  const profileUser = profile?.user || user;
  const profileAvatar = profileUser?.avatar_data_url;
  const profileCreated = profileUser?.created_at;
  const activitySeries = buildActivitySeries(profile?.recent_analyses || [], language);
  const dashboardCards = [
    {
      label: t(language, "dashboard.cards.companies"),
      value: companies.length || 0,
      sub: t(language, "analysis.availableTitle"),
      tone: "good",
    },
    {
      label: t(language, "dashboard.cards.analyses"),
      value: profileStats.total_analyses ?? 0,
      sub: profile ? t(language, "profile.statsTitle") : t(language, "profile.empty"),
      tone: "warning",
    },
    {
      label: t(language, "dashboard.cards.avgScore"),
      value: profile ? profileStats.avg_score ?? "—" : "—",
      sub: profile ? t(language, "profile.stats.avgScore") : t(language, "analysis.resultEmpty"),
      tone: "good",
    },
    {
      label: t(language, "dashboard.cards.cached"),
      value: profileStats.cached_analyses ?? 0,
      sub: profile ? t(language, "analysis.resultCacheHit") : t(language, "dashboard.trend"),
      tone: "neutral",
    },
  ];

  const navItems = ["main", "about", "auth", "profile", "analysis"];

  const onAvatarChange = async (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      setProfileAvatarFile(null);
      setProfileAvatarPreview("");
      return;
    }
    setProfileAvatarFile(file);
    try {
      const dataUrl = await readFileAsDataUrl(file);
      setProfileAvatarPreview(dataUrl);
      setProfileAvatarCleared(false);
    } catch (error) {
      addToast(error.message, "error");
    }
  };

  const removeAvatar = () => {
    setProfileAvatarFile(null);
    setProfileAvatarPreview("");
    setProfileAvatarCleared(true);
    addToast(language === "ru" ? "Текущий аватар будет удален после сохранения" : language === "uz" ? "Joriy avatar saqlangandan so'ng o'chiriladi" : "Current avatar will be removed after saving", "info");
  };

  const toggleTheme = () => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  };

  return (
    <div className="app-shell-wrap">
      <div className="bg-glow bg-glow-a" />
      <div className="bg-glow bg-glow-b" />

      <div className="app-shell">
        <header className="topbar">
          <div className="topbar-brand">
            <div className="brand-mark">UZ</div>
            <div className="brand-copy">
              <div className="brand-title">{t(language, "brand")}</div>
              <div className="brand-subtitle">{t(language, "subtitle")}</div>
            </div>
          </div>

          <nav className="topbar-nav">
            {navItems.map((key) => (
              <button key={key} className={`topbar-nav-btn ${activeView === key ? "active" : ""}`} type="button" onClick={() => setActiveView(key)}>
                {t(language, `nav.${key}`)}
              </button>
            ))}
          </nav>

          <div className="topbar-meta">
            <div className="topbar-status">
              <span className="auth-chip-label">{activeView ? t(language, `nav.${activeView}`) : t(language, "nav.main")}</span>
              <span className={`status-badge ${token ? "" : "muted"}`}>{token ? t(language, "auth.signedIn") : t(language, "auth.signedOut")}</span>
            </div>

            <div className="topbar-controls">
              <button className="theme-toggle" type="button" onClick={toggleTheme}>
                <span className="field-label">{t(language, "theme.label")}</span>
                <strong>{theme === "dark" ? t(language, "theme.light") : t(language, "theme.dark")}</strong>
              </button>

              <label className="topbar-language">
                <span className="field-label">{t(language, "languageLabel")}</span>
                <select
                  id="languageSelect"
                  className="select-field"
                  value={language}
                  onChange={(event) => setLanguage(normalizeLanguage(event.target.value))}
                >
                  <option value="ru">{t(language, "languageOptions.ru")}</option>
                  <option value="en">{t(language, "languageOptions.en")}</option>
                  <option value="uz">{t(language, "languageOptions.uz")}</option>
                </select>
              </label>

              <div className="auth-chip topbar-auth-chip">
                <div className="auth-chip-label">{token ? t(language, "auth.signedIn") : t(language, "auth.signedOut")}</div>
                <div className="auth-chip-name">{profileUser?.full_name || profileUser?.email || "—"}</div>
                <div className="auth-chip-email">{profileUser?.email || ""}</div>
              </div>
            </div>
          </div>
        </header>

        <main className="content">
          <section className="hero-panel">
            <div className="hero-copy-block">
              <div className="eyebrow">{t(language, "subtitle")}</div>
              <h1>{t(language, "hero.title")}</h1>
              <p>{t(language, "hero.copy")}</p>
              <div className="hero-actions">
                <button className="primary-btn" type="button" onClick={() => setActiveView("analysis")}>
                  {TEXTS[language].hero.ctas.analysis}
                </button>
                <button className="ghost-btn" type="button" onClick={() => setActiveView("profile")}>
                  {TEXTS[language].hero.ctas.profile}
                </button>
              </div>
            </div>
            <div className="hero-badges">
              {TEXTS[language].hero.badges.map((badge) => (
                <span key={badge}>{badge}</span>
              ))}
            </div>
          </section>

          <section className="dashboard-overview">
            <article className="panel overview-panel">
              <div className="panel-head">
                <div>
                  <div className="panel-label">{t(language, "dashboard.title")}</div>
                  <h2>{t(language, "dashboard.title")}</h2>
                </div>
                <span className="status-badge muted">{t(language, "dashboard.copy")}</span>
              </div>
              <div className="overview-grid">
                {dashboardCards.map((card) => (
                  <StatCard key={card.label} {...card} />
                ))}
              </div>
            </article>

            <article className="panel activity-panel">
              <div className="panel-head">
                <div>
                  <div className="panel-label">{t(language, "dashboard.activityTitle")}</div>
                  <h2>{t(language, "dashboard.activityTitle")}</h2>
                </div>
                <span className="status-badge muted">
                  {activitySeries?.total ? `${activitySeries.total} ${language === "uz" ? "tahlil" : language === "en" ? "analyses" : "анализов"}` : t(language, "dashboard.activityEmpty")}
                </span>
              </div>
              <ActivityChart series={activitySeries} language={language} />
            </article>
          </section>

          {activeView === "main" && (
            <section className="view-grid">
              <article className="panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "nav.main")}</div>
                    <h2>{t(language, "main.title")}</h2>
                  </div>
                </div>
                <p className="panel-copy">{t(language, "main.copy")}</p>
                <div className="tile-grid">
                  {TEXTS[language].main.cards.map((item) => (
                    <div className="tile-card" key={item.title}>
                      <strong>{item.title}</strong>
                      <span>{item.copy}</span>
                    </div>
                  ))}
                </div>
              </article>

              <article className="panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "nav.main")}</div>
                    <h2>{TEXTS[language].main.sideTitle}</h2>
                  </div>
                </div>
                <div className="stacked-list">
                  {TEXTS[language].main.sideCards.map((item) => (
                    <div className="note-card" key={item.title}>
                      <strong>{item.title}</strong>
                      <p>{item.copy}</p>
                    </div>
                  ))}
                </div>
              </article>
            </section>
          )}

          {activeView === "about" && (
            <section className="view-grid">
              <article className="panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "nav.about")}</div>
                    <h2>{t(language, "about.title")}</h2>
                  </div>
                </div>
                <div className="stacked-list">
                  {TEXTS[language].about.leftCards.map((item) => (
                    <div className="note-card" key={item.title}>
                      <strong>{item.title}</strong>
                      <p>{item.copy}</p>
                    </div>
                  ))}
                </div>
              </article>
              <article className="panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "nav.about")}</div>
                    <h2>{TEXTS[language].about.rightTitle}</h2>
                  </div>
                </div>
                <div className="tile-grid tile-grid-2">
                  {TEXTS[language].about.rightCards.map((item) => (
                    <div className="tile-card" key={item.title}>
                      <strong>{item.title}</strong>
                      <span>{item.copy}</span>
                    </div>
                  ))}
                </div>
              </article>
            </section>
          )}

          {activeView === "auth" && (
            <section className="auth-layout">
              <article className="panel auth-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "nav.auth")}</div>
                    <h2>{t(language, "auth.title")}</h2>
                  </div>
                  <span className={`status-badge ${token ? "" : "muted"}`}>{token ? t(language, "auth.signedIn") : t(language, "auth.signedOut")}</span>
                </div>

                <div className="segmented-control">
                  <button type="button" className={authTab === "login" ? "active" : ""} onClick={() => setAuthTab("login")}>
                    {t(language, "auth.loginTab")}
                  </button>
                  <button type="button" className={authTab === "register" ? "active" : ""} onClick={() => setAuthTab("register")}>
                    {t(language, "auth.registerTab")}
                  </button>
                </div>

                {authTab === "login" ? (
                  <form className="form-grid" onSubmit={handleLogin}>
                    <label>
                      <span>{t(language, "auth.login.email")}</span>
                      <input
                        type="email"
                        value={loginForm.email}
                        onChange={(event) => setLoginForm({ ...loginForm, email: event.target.value })}
                        placeholder="you@example.com"
                        required
                      />
                    </label>
                    <label>
                      <span>{t(language, "auth.login.password")}</span>
                      <input
                        type="password"
                        value={loginForm.password}
                        onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })}
                        placeholder="••••••••"
                        required
                      />
                    </label>
                    <button className="primary-btn" type="submit">
                      {t(language, "auth.login.submit")}
                    </button>
                  </form>
                ) : (
                  <form className="form-grid" onSubmit={handleRegister}>
                    <label>
                      <span>{t(language, "auth.register.fullName")}</span>
                      <input
                        type="text"
                        value={registerForm.full_name}
                        onChange={(event) => setRegisterForm({ ...registerForm, full_name: event.target.value })}
                        placeholder={t(language, "auth.register.fullName")}
                      />
                    </label>
                    <label>
                      <span>{t(language, "auth.register.email")}</span>
                      <input
                        type="email"
                        value={registerForm.email}
                        onChange={(event) => setRegisterForm({ ...registerForm, email: event.target.value })}
                        placeholder="you@example.com"
                        required
                      />
                    </label>
                    <label>
                      <span>{t(language, "auth.register.password")}</span>
                      <input
                        type="password"
                        value={registerForm.password}
                        onChange={(event) => setRegisterForm({ ...registerForm, password: event.target.value })}
                        placeholder="••••••••"
                        required
                      />
                    </label>
                    <button className="primary-btn" type="submit">
                      {t(language, "auth.register.submit")}
                    </button>
                  </form>
                )}

                <div className="oauth-block">
                  <div className="oauth-label">{t(language, "auth.oauthLabel")}</div>
                  <button className="oauth-btn oauth-google" type="button" onClick={handleGoogleLogin}>
                    {t(language, "auth.google")}
                  </button>
                </div>

                <div className="helper-text">{authMessage}</div>
              </article>

              <article className="panel auth-side-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "nav.auth")}</div>
                    <h2>{t(language, "auth.signedInAs")}</h2>
                  </div>
                </div>
                {token && profileUser ? (
                  <div className="user-card">
                    <div className="user-line">
                      <span className="muted">{t(language, "auth.signedInAs")}</span>
                      <strong>{profileUser.full_name || profileUser.email}</strong>
                    </div>
                    <div className="user-line">
                      <span className="muted">Email</span>
                      <strong>{profileUser.email}</strong>
                    </div>
                    <button className="ghost-btn" type="button" onClick={handleLogout}>
                      {t(language, "auth.logout")}
                    </button>
                  </div>
                ) : (
                  <div className="empty-state">
                    <p className="empty-copy">{t(language, "auth.messages.authRequired")}</p>
                  </div>
                )}
              </article>
            </section>
          )}

          {activeView === "profile" && (
            <section className="profile-layout">
              <article className="panel profile-hero">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "nav.profile")}</div>
                    <h2>{t(language, "profile.title")}</h2>
                  </div>
                  <span className="status-badge muted">{profile ? t(language, "profile.subtitle") : t(language, "profile.empty")}</span>
                </div>

                {profileUser ? (
                  <>
                    <div className="profile-identity">
                      <div className="profile-avatar" style={profileAvatarPreview || profileAvatar ? {} : { background: `linear-gradient(135deg, hsl(${hashToHue(profileUser.email)} 80% 66%), hsl(${(hashToHue(profileUser.email) + 45) % 360} 80% 55%))` }}>
                        {profileAvatarPreview ? <img src={profileAvatarPreview} alt="" /> : profileAvatar ? <img src={profileAvatar} alt="" /> : getProfileInitials(profileUser)}
                      </div>
                      <div className="profile-copy">
                        <h3>{profileUser.full_name || profileUser.email}</h3>
                        <p>{profileUser.email}</p>
                        <p className="muted">{profileCreated ? t(language, "profile.subtitle") : t(language, "profile.empty")}</p>
                      </div>
                    </div>

                    <div className="profile-actions">
                      <button className="primary-btn" type="button" onClick={() => setActiveView("analysis")}>
                        {t(language, "profile.analyze")}
                      </button>
                      <button className="ghost-btn" type="button" onClick={() => loadProfile().then(() => addToast(t(language, "profile.refresh"), "success")).catch((error) => addToast(error.message, "error"))}>
                        {t(language, "profile.refresh")}
                      </button>
                    </div>

                    <form className="profile-edit-form" onSubmit={handleProfileSave}>
                      <div className="section-title-row">
                        <h3>{t(language, "profile.editTitle")}</h3>
                        <span className="muted">{t(language, "profile.subtitle")}</span>
                      </div>
                      <label>
                        <span>{t(language, "profile.name")}</span>
                        <input
                          type="text"
                          value={profileForm.full_name}
                          onChange={(event) => setProfileForm({ full_name: event.target.value })}
                          placeholder={t(language, "profile.name")}
                        />
                      </label>
                      <label>
                        <span>{t(language, "profile.avatar")}</span>
                        <input type="file" accept="image/*" onChange={onAvatarChange} />
                      </label>
                      <div className="profile-edit-actions">
                        <button className="primary-btn" type="submit">
                          {t(language, "profile.save")}
                        </button>
                        <button className="ghost-btn" type="button" onClick={removeAvatar}>
                          {t(language, "profile.clearAvatar")}
                        </button>
                      </div>
                    </form>
                  </>
                ) : (
                  <div className="empty-state">
                    <p className="empty-copy">{t(language, "profile.empty")}</p>
                  </div>
                )}
              </article>

              <article className="panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "profile.statsTitle")}</div>
                    <h2>{t(language, "profile.statsTitle")}</h2>
                  </div>
                </div>
                {profile ? (
                  <div className="profile-stats-grid">
                    <StatCard label={t(language, "profile.stats.totalAnalyses")} value={profileStats.total_analyses ?? 0} sub={t(language, "profile.stats.totalAnalyses")} />
                    <StatCard label={t(language, "profile.stats.analyses7d")} value={profileStats.analyses_7d ?? 0} sub={t(language, "profile.stats.analyses7d")} />
                    <StatCard label={t(language, "profile.stats.analyses30d")} value={profileStats.analyses_30d ?? 0} sub={t(language, "profile.stats.analyses30d")} />
                    <StatCard label={t(language, "profile.stats.analyzedCompanies")} value={profileStats.analyzed_companies ?? 0} sub={t(language, "profile.stats.analyzedCompanies")} />
                    <StatCard label={t(language, "profile.stats.avgScore")} value={profileStats.avg_score ?? "—"} sub={t(language, "profile.stats.avgScore")} />
                    <StatCard label={t(language, "profile.stats.bestScore")} value={profileStats.best_score ?? "—"} sub={t(language, "profile.stats.bestScore")} />
                    <StatCard label={t(language, "profile.stats.cachedAnalyses")} value={profileStats.cached_analyses ?? 0} sub={t(language, "profile.stats.cachedAnalyses")} />
                    <StatCard label={t(language, "profile.stats.topCompany")} value={profileStats.top_company || "—"} sub={profileStats.top_company_count ? `${profileStats.top_company_count} ${language === "ru" ? "анализов" : language === "uz" ? "tahlil" : "analyses"}` : ""} />
                  </div>
                ) : (
                  <div className="empty-state">
                    <p className="empty-copy">{t(language, "profile.empty")}</p>
                  </div>
                )}
              </article>

              <article className="panel favorites-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "profile.favoritesTitle")}</div>
                    <h2>{t(language, "profile.favoritesTitle")}</h2>
                  </div>
                </div>
                {profile?.favorites?.length ? (
                  <div className="favorites-list">
                    {profile.favorites.map((item) => (
                      <div className="favorite-item" key={`${item.ticker}-${item.created_at}`}>
                        <div className="favorite-main">
                          <strong>{item.company_name || item.ticker}</strong>
                          <span>{item.ticker} · {formatDateLabel(item.created_at, language)}</span>
                        </div>
                        <button className="ghost-btn" type="button" onClick={() => handleToggleFavorite(item.ticker, item.company_name)}>
                          {t(language, "profile.remove")}
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-state">
                    <p className="empty-copy">{t(language, "profile.favoritesEmpty")}</p>
                  </div>
                )}
              </article>

              <article className="panel history-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "profile.historyTitle")}</div>
                    <h2>{t(language, "profile.historyTitle")}</h2>
                  </div>
                  <div className="history-filters">
                    <input
                      type="search"
                      value={historySearch}
                      onChange={(event) => setHistorySearch(event.target.value)}
                      placeholder={t(language, "profile.filters.search")}
                    />
                    <select value={historyMode} onChange={(event) => setHistoryMode(event.target.value)}>
                      <option value="all">{t(language, "profile.filters.all")}</option>
                      <option value="favorites">{t(language, "profile.filters.favorites")}</option>
                    </select>
                  </div>
                </div>
                {recentAnalyses.length ? (
                  <div className="history-list">
                    {recentAnalyses.map((item) => (
                      <article className="history-item" key={`${item.created_at}-${item.company_input}`}>
                        <div className="history-main">
                          <div>
                            <div className="history-title">{item.company_name || item.company_input || t(language, "profile.empty")}</div>
                            <div className="history-sub">
                              {item.ticker || "—"} · {item.from_cache ? t(language, "analysis.resultCacheHit") : t(language, "analysis.resultFresh")} · {item.model || ""}
                            </div>
                          </div>
                          <div className="history-score">{item.score ?? "—"}</div>
                        </div>
                        <div className="history-meta">
                          <span>{formatDateLabel(item.created_at, language)}</span>
                          <span>{item.verdict || ""}</span>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="empty-state">
                    <p className="empty-copy">{profile ? t(language, "profile.historyEmpty") : t(language, "profile.empty")}</p>
                  </div>
                )}
              </article>
            </section>
          )}

          {activeView === "analysis" && (
            <section className="analysis-layout">
              <article className="panel analysis-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "nav.analysis")}</div>
                    <h2>{t(language, "analysis.title")}</h2>
                  </div>
                  <span className={`status-badge ${analysisLoading ? "" : "muted"}`}>{analysisLoading ? t(language, "analysis.loadingChart") : t(language, "analysis.chartMetaEmpty")}</span>
                </div>

                <form className="analysis-form" onSubmit={handleAnalysisSubmit}>
                  <label className="wide">
                    <span>{t(language, "analysis.company")}</span>
                    <input
                      list="companiesList"
                      value={analysisCompany}
                      onChange={(event) => setAnalysisCompany(event.target.value)}
                      placeholder={language === "en" ? "Type a company name or ticker" : language === "uz" ? "Kompaniya nomi yoki ticker" : "Начните вводить название или тикер"}
                      autoComplete="off"
                      required
                    />
                    <datalist id="companiesList">
                      {companies.map((company) => (
                        <option key={company.ticker} value={company.ticker}>
                          {company.company_name}
                        </option>
                      ))}
                    </datalist>
                  </label>
                  <label>
                    <span>{t(language, "analysis.mode")}</span>
                    <select defaultValue="full">
                      <option value="quick">{t(language, "analysis.quick")}</option>
                      <option value="full">{t(language, "analysis.full")}</option>
                    </select>
                  </label>
                  <label className="toggle-row">
                    <input type="checkbox" checked={includeHtml} onChange={(event) => setIncludeHtml(event.target.checked)} />
                    <span>{t(language, "analysis.includeHtml")}</span>
                  </label>
                  <button className="primary-btn analyze-btn" type="submit">
                    {t(language, "analysis.submit")}
                  </button>
                </form>

                <div className="quick-list-wrap">
                  <div className="section-title-row">
                    <h3>{t(language, "analysis.availableTitle")}</h3>
                    <span className="muted">{companies.length}</span>
                  </div>
                  <div className="quick-list">
                    {filteredCompanies.map((company) => (
                      <button
                        key={company.ticker}
                        className="quick-chip"
                        type="button"
                        onClick={() => setAnalysisCompany(company.ticker)}
                      >
                        {company.ticker}
                      </button>
                    ))}
                  </div>
                </div>
              </article>

              <article className={`panel result-hero ${analysisLoading ? "is-loading" : ""}`}>
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "analysis.resultTitle")}</div>
                    <h2>{analysisLabel}</h2>
                  </div>
                  <span className="status-badge muted">{resultCacheText}</span>
                </div>

                {analysisLoading ? (
                  <ResultSkeleton language={language} />
                ) : (
                  <>
                    <div className="score-strip">
                      <div className="score-card">
                        <div className={`score-value ${resultScore != null && resultScore >= 70 ? "metric-good" : resultScore != null && resultScore >= 45 ? "metric-warning" : "metric-danger"}`}>
                          {resultScore ?? "--"}
                        </div>
                        <div className="score-caption">{t(language, "analysis.score")}</div>
                      </div>
                      <div className="score-meta">
                        <div className="grade-pill">{resultGrade || "—"}</div>
                        <p className="verdict-text">{resultVerdict || t(language, "analysis.verdictPlaceholder")}</p>
                        <p className="summary-text">{resultSummary}</p>
                      </div>
                    </div>

                    <div className="chart-card">
                      <div className="chart-head">
                        <div>
                          <div className="panel-label">{t(language, "analysis.chartTitle")}</div>
                          <h3>{t(language, "analysis.chartTitle")}</h3>
                        </div>
                        <span className="status-badge muted">{chartData ? `${chartData.filtered[0].year}–${chartData.filtered.at(-1).year}` : t(language, "analysis.chartMetaEmpty")}</span>
                      </div>
                      <AnalysisChart chartData={chartData} language={language} />
                    </div>

                    <div className="market-strip">
                      <SignalCard
                        label={t(language, "analysis.signalRevenue")}
                        value={chartData && chartData.latest?.revenue != null ? formatCompactNumber(chartData.latest.revenue, language) : "—"}
                        sub={chartData && chartData.revenueChange !== null ? `${t(language, "analysis.signalTrend")} ${formatSignedPercent(chartData.revenueChange)} · ${t(language, "analysis.signalLatest")} ${chartData.latest.year}` : t(language, "analysis.noData")}
                        tone={chartData && chartData.revenueChange !== null ? (chartData.revenueChange >= 10 ? "good" : chartData.revenueChange >= 0 ? "warning" : "danger") : "neutral"}
                      />
                      <SignalCard
                        label={t(language, "analysis.signalMargin")}
                        value={analysisResult?.ifrs_snapshot?.income_statement?.net_margin_pct != null ? `${formatSignedPercent(analysisResult.ifrs_snapshot.income_statement.net_margin_pct)}` : analysisResult?.ifrs_snapshot?.quality?.roe_pct != null ? `${formatSignedPercent(analysisResult.ifrs_snapshot.quality.roe_pct)}` : "—"}
                        sub={
                          [
                            analysisResult?.ifrs_snapshot?.quality?.roe_pct != null ? `ROE ${formatSignedPercent(analysisResult.ifrs_snapshot.quality.roe_pct)}` : "",
                            analysisResult?.ifrs_snapshot?.quality?.roa_pct != null ? `ROA ${formatSignedPercent(analysisResult.ifrs_snapshot.quality.roa_pct)}` : "",
                          ]
                            .filter(Boolean)
                            .join(" · ") || t(language, "analysis.noData")
                        }
                        tone={
                          Number(analysisResult?.ifrs_snapshot?.income_statement?.net_margin_pct) >= 15 || Number(analysisResult?.ifrs_snapshot?.quality?.roe_pct) >= 15
                            ? "good"
                            : Number(analysisResult?.ifrs_snapshot?.income_statement?.net_margin_pct) >= 5 || Number(analysisResult?.ifrs_snapshot?.quality?.roe_pct) >= 5
                              ? "warning"
                              : "danger"
                        }
                      />
                      <SignalCard
                        label={t(language, "analysis.signalRisk")}
                        value={
                          Number.isFinite(Number(analysisResult?.metrics?.altman_z_score?.score))
                            ? Number(analysisResult.metrics.altman_z_score.score) > 2.99
                              ? t(language, "analysis.signalUp")
                              : Number(analysisResult.metrics.altman_z_score.score) > 1.81
                                ? t(language, "analysis.signalFlat")
                                : t(language, "analysis.signalDown")
                            : t(language, "analysis.noData")
                        }
                        sub={
                          [
                            Number.isFinite(Number(analysisResult?.metrics?.altman_z_score?.score)) ? `Altman ${formatRatio(analysisResult.metrics.altman_z_score.score, 2, language)}` : "",
                            analysisResult?.ifrs_snapshot?.balance_sheet?.debt_to_equity != null ? `D/E ${formatRatio(analysisResult.ifrs_snapshot.balance_sheet.debt_to_equity, 2, language)}` : "",
                            analysisResult?.ifrs_snapshot?.balance_sheet?.current_ratio != null ? `CR ${formatRatio(analysisResult.ifrs_snapshot.balance_sheet.current_ratio, 2, language)}` : "",
                          ]
                            .filter(Boolean)
                            .join(" · ") || t(language, "analysis.noData")
                        }
                        tone={
                          Number.isFinite(Number(analysisResult?.metrics?.altman_z_score?.score))
                            ? Number(analysisResult.metrics.altman_z_score.score) > 2.99
                              ? "good"
                              : Number(analysisResult.metrics.altman_z_score.score) > 1.81
                                ? "warning"
                                : "danger"
                            : "neutral"
                        }
                      />
                    </div>

                    <div className="meta-grid">
                      <button
                        id="resultFavoriteBtn"
                        className={`ghost-btn result-favorite-btn ${analysisTicker && favoriteTickers.has(String(analysisTicker).trim().toUpperCase()) ? "is-active" : ""}`}
                        type="button"
                        onClick={() => analysisResult && handleToggleFavorite(analysisTicker, analysisResult.company_name || analysisResult.input || "")}
                      >
                        {analysisTicker && favoriteTickers.has(String(analysisTicker).trim().toUpperCase()) ? t(language, "analysis.favoriteRemove") : t(language, "analysis.favoriteAdd")}
                      </button>
                    </div>
                  </>
                )}
              </article>
            </section>
          )}

          {activeView === "analysis" && (
            <section className="results-grid">
              <article className="panel metrics-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "analysis.metricsTitle")}</div>
                    <h2>{t(language, "analysis.metricsTitle")}</h2>
                  </div>
                </div>
                {metricCards.length ? (
                  <div className="metrics-grid">
                    {metricCards.map((item) => (
                      <MetricCard key={item.label} {...item} />
                    ))}
                  </div>
                ) : (
                  <div className="empty-state">
                    <p className="empty-copy">{analysisLoading ? t(language, "analysis.loadingMetrics") : t(language, "analysis.resultEmpty")}</p>
                  </div>
                )}
              </article>

              <article className="panel sections-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "analysis.sectionsTitle")}</div>
                    <h2>{t(language, "analysis.sectionsTitle")}</h2>
                  </div>
                </div>
                {analysisResult?.sections ? (
                  <div className="sections-wrap">
                    {Object.entries(analysisResult.sections).map(([key, value], index) => (
                      <SectionCard key={key} title={getSectionTitle(language, key)} body={value || t(language, "analysis.noData")} index={index} open={index === 0} />
                    ))}
                  </div>
                ) : (
                  <div className="empty-state">
                    <p className="empty-copy">{analysisLoading ? t(language, "analysis.loadingSections") : t(language, "analysis.resultEmpty")}</p>
                  </div>
                )}
              </article>
            </section>
          )}
        </main>
      </div>

      <ToastStack toasts={toasts} onDismiss={(id) => setToasts((current) => current.filter((item) => item.id !== id))} language={language} />
    </div>
  );
}

function SignalCard({ label, value, sub, tone = "neutral" }) {
  return (
    <article className={`mini-market-card tone-${tone}`} data-tone={tone}>
      <span className="mini-market-label">{label}</span>
      <strong>{value}</strong>
      <p>{sub}</p>
    </article>
  );
}

function AnalysisChart({ chartData, language }) {
  if (!chartData) {
    return (
      <div className="analysis-chart empty-state">
        <p className="empty-copy">{t(language, "analysis.chartEmpty")}</p>
      </div>
    );
  }

  const { width, height, filtered, areaPath, revenuePath, profitPath, yTicks, x, y, revenueChange, profitChange, latest } = chartData;

  return (
    <div className="analysis-chart">
      <svg className="result-chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t(language, "analysis.chartTitle")}>
        <defs>
          <linearGradient id="revenueAreaGradient" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#6ef0c1" stopOpacity="0.42" />
            <stop offset="100%" stopColor="#6ef0c1" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {yTicks.map((tick, index) => (
          <g key={index}>
            <line x1="74" y1={tick.y} x2={width - 24} y2={tick.y} className="chart-grid-line" />
            <text x="64" y={tick.y + 4} className="chart-axis-label chart-axis-label-y" textAnchor="end">
              {formatCompactNumber(tick.value, language)}
            </text>
          </g>
        ))}
        <path d={areaPath} className="chart-area" />
        <path d={revenuePath} className="chart-line chart-line-revenue" />
        <path d={profitPath} className="chart-line chart-line-profit" />
        {filtered.map((point, index) => (
          <g key={`${point.year}-${index}`}>
            <circle cx={x(index)} cy={y(point.revenue ?? 0)} r="4.8" className="chart-dot chart-dot-revenue" />
            <circle cx={x(index)} cy={y(point.profit ?? 0)} r="4.8" className="chart-dot chart-dot-profit" />
          </g>
        ))}
        {filtered.map((point, index) => (
          <text key={`${point.year}-label`} x={x(index)} y={height - 16} className="chart-axis-label chart-axis-label-x" textAnchor="middle">
            {point.year}
          </text>
        ))}
      </svg>

      <div className="chart-legend">
        <div className="legend-chip">
          <span className="legend-swatch legend-swatch-revenue" />
          <span className="legend-label">{t(language, "analysis.signalRevenue")}</span>
          <strong className="legend-value">{formatCompactNumber(latest.revenue, language)}</strong>
          <span className={`legend-delta ${revenueChange === null ? "" : revenueChange >= 0 ? "is-up" : "is-down"}`}>
            {revenueChange === null ? "—" : formatSignedPercent(revenueChange)}
          </span>
        </div>
        <div className="legend-chip">
          <span className="legend-swatch legend-swatch-profit" />
          <span className="legend-label">{t(language, "analysis.signalLatest")}</span>
          <strong className="legend-value">{latest.profit != null ? formatCompactNumber(latest.profit, language) : "—"}</strong>
          <span className={`legend-delta ${profitChange === null ? "" : profitChange >= 0 ? "is-up" : "is-down"}`}>
            {profitChange === null ? "—" : formatSignedPercent(profitChange)}
          </span>
        </div>
      </div>

      <div className="chart-axis-note">
        <span>{filtered[0]?.year || ""}</span>
        <span>{filtered.at(-1)?.year || ""}</span>
      </div>
    </div>
  );
}

function ActivityChart({ series, language }) {
  const hasData = Boolean(series?.days?.some((day) => day.count > 0));

  if (!hasData) {
    return (
      <div className="activity-chart empty-state">
        <p className="empty-copy">{t(language, "dashboard.activityEmpty")}</p>
      </div>
    );
  }

  const width = 1000;
  const height = 280;
  const padding = { left: 20, right: 20, top: 20, bottom: 44 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const barGap = 12;
  const barWidth = (innerWidth - barGap * (series.days.length - 1)) / series.days.length;

  return (
    <div className="activity-chart">
      <svg className="activity-chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t(language, "dashboard.activityTitle")}>
        <defs>
          <linearGradient id="activityBarGradient" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#2563eb" stopOpacity="0.92" />
            <stop offset="100%" stopColor="#10b981" stopOpacity="0.34" />
          </linearGradient>
        </defs>
        {series.days.map((day, index) => {
          const barHeight = ((day.count || 0) / series.maxCount) * innerHeight;
          const x = padding.left + index * (barWidth + barGap);
          const y = padding.top + innerHeight - barHeight;
          return (
            <g key={day.key}>
              <rect x={x} y={padding.top} width={barWidth} height={innerHeight} rx="16" className="activity-bar-track" />
              <rect x={x} y={y} width={barWidth} height={barHeight} rx="16" className="activity-bar" />
              <text x={x + barWidth / 2} y={height - 16} textAnchor="middle" className="activity-axis-label">
                {day.shortLabel}
              </text>
              <text x={x + barWidth / 2} y={Math.max(y - 10, 16)} textAnchor="middle" className="activity-value">
                {day.count}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="activity-footer">
        <div>
          <span className="activity-footer-label">{t(language, "dashboard.activityCopy")}</span>
          <strong>{series.total}</strong>
        </div>
        <div>
          <span className="activity-footer-label">{t(language, "dashboard.peak")}</span>
          <strong>{series.peak ? series.peak.label : "—"}</strong>
        </div>
      </div>
    </div>
  );
}

function ResultSkeleton({ language }) {
  return (
    <>
      <div className="score-strip">
        <div className="score-card skeleton-card">
          <div className="skeleton-line skeleton-line-lg" />
          <div className="skeleton-line skeleton-line-sm" />
        </div>
        <div className="score-meta">
          <div className="grade-pill skeleton-pill" />
          <div className="skeleton-line skeleton-line-lg" />
          <div className="skeleton-line skeleton-line-md" />
        </div>
      </div>
      <div className="chart-card">
        <div className="chart-head">
          <div>
            <div className="panel-label">{t(language, "analysis.chartTitle")}</div>
            <div className="skeleton-line skeleton-line-md" />
          </div>
          <div className="skeleton-pill" />
        </div>
        <div className="chart-skeleton">
          <div className="chart-skeleton-grid">
            <span />
            <span />
            <span />
            <span />
          </div>
          <div className="chart-skeleton-wave">
            <span />
            <span />
            <span />
          </div>
        </div>
      </div>
      <div className="market-strip">
        <div className="mini-market-card skeleton-card" />
        <div className="mini-market-card skeleton-card" />
        <div className="mini-market-card skeleton-card" />
      </div>
    </>
  );
}

export default App;
