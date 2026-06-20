import React, { useEffect, useState } from "react";
import heroImage from "./assets/hero-image.png";
import logoIcon from "./assets/icon.png";

const STORAGE_KEY = "uz_stock_analyzer_token";
const LANGUAGE_KEY = "uz_stock_analyzer_language";
const THEME_KEY = "uz_stock_analyzer_theme";

// Modern SVG Icons for landing page
const Icons = {
  chart: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M3 3v18h18" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M7 14l4-4 4 4 5-5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  shield: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M9 12l2 2 4-4" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  zap: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  users: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx="9" cy="7" r="4" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  target: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="12" cy="12" r="10" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx="12" cy="12" r="6" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx="12" cy="12" r="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  database: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <ellipse cx="12" cy="5" rx="9" ry="3" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  trending: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M23 6l-9.5 9.5-5-5L1 18" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M17 6h6v6" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  lock: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M7 11V7a5 5 0 0 1 10 0v4" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  star: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  play: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="12" cy="12" r="10" strokeLinecap="round" strokeLinejoin="round"/>
      <polygon points="10 8 16 12 10 16 10 8" fill="currentColor" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
};

const TEXTS = {
  ru: {
    pageTitle: "UZ Stock Analyzer",
    brand: "UZ Stock Analyzer",
    subtitle: "Платформа для анализа компаний Узбекистана",
    nav: { main: "Главная", about: "О проекте", auth: "Вход", profile: "Профиль", analysis: "Анализ", catalog: "Каталог" },
    catalog: {
      title: "Каталог отчётности",
      subtitle: "Все доступные отчёты листинговых компаний с openinfo.uz",
      searchPlaceholder: "Поиск по тикеру или названию...",
      syncAll: "Синхронизировать всё",
      syncCompany: "Обновить",
      syncing: "Синхронизация...",
      syncDone: "Обновлено",
      empty: "Каталог пуст — нажмите «Синхронизировать всё»",
      selectCompany: "Выберите компанию из списка",
      noReports: "Отчёты не найдены",
      notPublished: "За выбранный период данный тип отчёта не был опубликован",
      available: "Отчёт опубликован",
      loading: "Загрузка...",
      reports: "отчётов",
      companies: "компаний",
      totalReports: "отчётов в базе",
      lastSync: "Последнее обновление",
      forms: { NSBU: "НСБУ", MSFO: "МСФО", Audition: "Аудит" },
      periods: { annual: "Годовой", q1: "Q1", q2: "Q2", q3: "Q3" },
      analysisLabel: "Тип аналитики",
      runAnalysis: "Запустить анализ",
      analysisLoading: "Анализируем...",
      analysisTypes: {
        financial: "Финансовый анализ",
        ratio: "Коэффициенты (ROA, ROE, Debt...)",
        dynamics: "Динамика показателей",
        quarter_compare: "Сравнение кварталов",
        annual_compare: "Сравнение годовых отчётов",
        swot: "SWOT-анализ",
        recommendation: "Инвестиционная рекомендация",
        multi_company: "Сравнение компаний",
      },
      compareWith: "Сравнить с:",
      comparePeriod: "Период для сравнения:",
      noValue: "Нет данных",
      ratioLabels: { ROA: "ROA", ROE: "ROE", net_margin: "Чистая маржа", debt_ratio: "Debt Ratio", debt_to_equity: "D/E" },
      dynamicsLabels: { revenue: "Выручка", net_income: "Чистая прибыль", total_assets: "Активы", equity: "Капитал", total_liabilities: "Обязательства" },
      pdfReport: "Открыть PDF",
    },
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
      title: "Платформа для инвестиционного анализа",
      copy: "Получайте профессиональный анализ узбекских компаний за секунды. Оценка финансового здоровья, риски и потенциал роста.",
      features: [
        { icon: "chart", title: "Глубокий анализ", copy: "DCF-оценка, отраслевые сигналы, динамика выручки и прибыли" },
        { icon: "zap", title: "Мгновенный результат", copy: "Полный отчет с графиками и рекомендациями за несколько секунд" },
        { icon: "shield", title: "Надежные данные", copy: "Актуальная финансовая отчетность напрямую с Узбекской биржи" },
        { icon: "target", title: "Точные прогнозы", copy: "Анализ трендов, катализаторов и рыночных сигналов" },
      ],
      howItWorks: {
        title: "Как это работает",
        steps: [
          { num: "01", title: "Выберите компанию", copy: "Введите тикер или выберите из каталога доступных компаний" },
          { num: "02", title: "Запустите анализ", copy: "Система соберет данные и проведет комплексный финансовый анализ" },
          { num: "03", title: "Получите отчет", copy: "Изучите оценку, графики, метрики и инвестиционные рекомендации" },
        ],
      },
      stats: {
        title: "Платформа в цифрах",
        items: [
          { value: "50+", label: "Компаний в базе" },
          { value: "15+", label: "Метрик анализа" },
          { value: "24/7", label: "Доступность" },
          { value: "100%", label: "Бесплатно" },
        ],
      },
      cta: {
        title: "Готовы начать?",
        copy: "Зарегистрируйтесь бесплатно и получите доступ ко всем инструментам анализа",
        button: "Начать анализ",
      },
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
        { title: "Метрики", copy: "DCF, отраслевые сигналы, ликвидность и динамика." },
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
      reportType: "Тип анализа",
      fullAnalysis: "Полный анализ",
      quarterlyReport: "Квартальный",
      annualReport: "Годовой",
      quarter: "Квартал",
      currentYear: "Сравнить год",
      previousYear: "С годом",
      reportingForm: "Форма отчётности",
      reportFormIFRS: "МСФО",
      reportFormNAS: "НСБУ",
      reportFormAudit: "Аудиторское заключение",
      reportFormHint: "Выбор формы влияет только на режим квартального/годового сравнения. НСБУ — единственная форма с Excel-данными на openinfo.uz. МСФО и аудиторские заключения публикуются в PDF-формате без Excel-таблиц.",
      reportFormLatestNote: "В режиме «Полный анализ» данные берутся из структурированной отчётности НСБУ (форма 1 + форма 2) — форма отчётности применяется только при квартальном/годовом сравнении.",
      reportFormNotFound: "Компания не опубликовала данный тип отчёта за выбранный период.",
      forceRefresh: "Обновить из источника (обойти кэш)",
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
      signalDebt: "Обязательства",
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
      ОБЩИЕ_СВЕДЕНИЯ: "Общие сведения об эмитенте и методология анализа",
      ГОРИЗОНТАЛЬНЫЙ_АНАЛИЗ: "Горизонтальный анализ бухгалтерского баланса",
      ВЕРТИКАЛЬНЫЙ_АНАЛИЗ: "Вертикальный анализ бухгалтерского баланса",
      АНАЛИЗ_ФИНРЕЗУЛЬТАТОВ: "Анализ отчёта о финансовых результатах",
      КОЭФФИЦИЕНТНЫЙ_АНАЛИЗ: "Коэффициентный анализ",
      СВОДНАЯ_ТАБЛИЦА: "Сводная таблица ключевых показателей",
      ЗАКЛЮЧЕНИЕ: "Итоговая оценка и инвестиционная рекомендация",
      СКОРИНГ: "Общая оценка и скоринг эмитента",
      ДОСЬЕ: "Краткое досье эмитента",
      ЧТО_С_ДЕНЬГАМИ: "Финансовая выжимка",
      ТРЕНД: "Анализ трендов и динамики показателей",
      ЭФФЕКТИВНОСТЬ: "Операционная эффективность и оборачиваемость",
      ТЕХНИЧЕСКИЙ_АНАЛИЗ: "Технический анализ (RSI, Фибоначчи, объёмы)",
      ОЦЕНКА_СТОИМОСТИ: "Оценка справедливой стоимости",
      ФИБОНАЧЧИ: "Технический анализ (уровни Фибоначчи)",
      ОЦЕНКА_ЦЕНЫ: "Оценка инвестиционной привлекательности",
      КАТАЛИЗАТОРЫ: "Факторы влияния на стоимость акций",
      РЫНОЧНЫЕ_ДАННЫЕ: "Рыночные данные и ликвидность",
      СИЛЬНЫЕ_СТОРОНЫ: "Сильные стороны и конкурентные преимущества",
      СЛАБЫЕ_СТОРОНЫ: "Риски и слабые стороны",
      ВОЗМОЖНОСТИ: "Возможности роста",
      УГРОЗЫ: "Угрозы и внешние риски",
      ПРОГНОЗ: "Прогноз развития компании",
      ВЕРДИКТ: "Инвестиционный вердикт",
      СОВЕТЫ: "Рекомендации инвестору",
      ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА: "Ограничения анализа",
      ИТОГ: "Резюме для инвестора",
      ЗЕЛЕНЫЕ_ФЛАГИ: "Позитивные сигналы",
      КРАСНЫЕ_ФЛАГИ: "Негативные сигналы",
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
    nav: { main: "Main", about: "About", auth: "Sign in", profile: "Profile", analysis: "Analysis", catalog: "Catalog" },
    catalog: {
      title: "Report Catalog",
      subtitle: "All available reports of listed companies from openinfo.uz",
      searchPlaceholder: "Search by ticker or name...",
      syncAll: "Sync all",
      syncCompany: "Refresh",
      syncing: "Syncing...",
      syncDone: "Updated",
      empty: "Catalog is empty — click \"Sync all\"",
      selectCompany: "Select a company from the list",
      noReports: "No reports found",
      notPublished: "This report type was not published for the selected period",
      available: "Report is available",
      loading: "Loading...",
      reports: "reports",
      companies: "companies",
      totalReports: "reports in database",
      lastSync: "Last updated",
      forms: { NSBU: "NAS", MSFO: "IFRS", Audition: "Audit" },
      periods: { annual: "Annual", q1: "Q1", q2: "Q2", q3: "Q3" },
      analysisLabel: "Analysis type",
      runAnalysis: "Run analysis",
      analysisLoading: "Analyzing...",
      analysisTypes: {
        financial: "Financial analysis",
        ratio: "Ratios (ROA, ROE, Debt...)",
        dynamics: "Metrics dynamics",
        quarter_compare: "Quarter comparison",
        annual_compare: "Annual comparison",
        swot: "SWOT analysis",
        recommendation: "Investment recommendation",
        multi_company: "Company comparison",
      },
      compareWith: "Compare with:",
      comparePeriod: "Period to compare:",
      noValue: "No data",
      ratioLabels: { ROA: "ROA", ROE: "ROE", net_margin: "Net Margin", debt_ratio: "Debt Ratio", debt_to_equity: "D/E" },
      dynamicsLabels: { revenue: "Revenue", net_income: "Net Income", total_assets: "Total Assets", equity: "Equity", total_liabilities: "Total Liabilities" },
      pdfReport: "Open PDF",
    },
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
      title: "Investment Analysis Platform",
      copy: "Get professional analysis of Uzbek companies in seconds. Financial health assessment, risks, and growth potential.",
      features: [
        { icon: "chart", title: "Deep Analysis", copy: "DCF valuation, sector signals, revenue and profit dynamics" },
        { icon: "zap", title: "Instant Results", copy: "Complete report with charts and recommendations in seconds" },
        { icon: "shield", title: "Reliable Data", copy: "Up-to-date financial statements directly from Uzbek Stock Exchange" },
        { icon: "target", title: "Accurate Forecasts", copy: "Trend analysis, catalysts, and market signals" },
      ],
      howItWorks: {
        title: "How It Works",
        steps: [
          { num: "01", title: "Select Company", copy: "Enter ticker or choose from the available companies catalog" },
          { num: "02", title: "Run Analysis", copy: "System collects data and performs comprehensive financial analysis" },
          { num: "03", title: "Get Report", copy: "Review score, charts, metrics and investment recommendations" },
        ],
      },
      stats: {
        title: "Platform in Numbers",
        items: [
          { value: "50+", label: "Companies" },
          { value: "15+", label: "Analysis Metrics" },
          { value: "24/7", label: "Availability" },
          { value: "100%", label: "Free" },
        ],
      },
      cta: {
        title: "Ready to Start?",
        copy: "Register for free and get access to all analysis tools",
        button: "Start Analysis",
      },
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
        { title: "Metrics", copy: "DCF, sector signals, liquidity, and trend dynamics." },
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
      reportType: "Analysis type",
      fullAnalysis: "Full analysis",
      quarterlyReport: "Quarterly",
      annualReport: "Annual",
      quarter: "Quarter",
      currentYear: "Compare year",
      previousYear: "With year",
      reportingForm: "Reporting form",
      reportFormIFRS: "IFRS",
      reportFormNAS: "NAS",
      reportFormAudit: "Auditor's Report",
      reportFormHint: "Form selection applies only to quarterly/annual comparison mode. NAS is the only form with Excel data on openinfo.uz. IFRS and audit reports are published as PDF with no Excel tables.",
      reportFormLatestNote: "In Full analysis mode data is sourced from NAS structured reports (form 1 + form 2). The reporting form only applies to quarterly/annual comparison.",
      reportFormNotFound: "The company did not publish this type of report for the selected period.",
      forceRefresh: "Refresh from source (bypass cache)",
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
      signalDebt: "Liabilities",
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
      ОБЩИЕ_СВЕДЕНИЯ: "Issuer Overview and Analytical Methodology",
      ГОРИЗОНТАЛЬНЫЙ_АНАЛИЗ: "Horizontal Balance Sheet Analysis",
      ВЕРТИКАЛЬНЫЙ_АНАЛИЗ: "Vertical Balance Sheet Analysis",
      АНАЛИЗ_ФИНРЕЗУЛЬТАТОВ: "Income Statement Analysis",
      КОЭФФИЦИЕНТНЫЙ_АНАЛИЗ: "Financial Ratio Analysis",
      СВОДНАЯ_ТАБЛИЦА: "Summary Table of Key Metrics",
      ЗАКЛЮЧЕНИЕ: "Final Assessment and Investment Recommendation",
      СКОРИНГ: "Overall Assessment and Scoring",
      ДОСЬЕ: "Company Snapshot",
      ЧТО_С_ДЕНЬГАМИ: "Financial Position Brief",
      ТРЕНД: "Trend and Dynamics Analysis",
      ЭФФЕКТИВНОСТЬ: "Operational Efficiency and Turnover",
      ТЕХНИЧЕСКИЙ_АНАЛИЗ: "Technical Analysis (RSI, Fibonacci, Volume)",
      ОЦЕНКА_СТОИМОСТИ: "Fair Value Assessment",
      ФИБОНАЧЧИ: "Technical Analysis (Fibonacci Levels)",
      ОЦЕНКА_ЦЕНЫ: "Investment Attractiveness",
      КАТАЛИЗАТОРЫ: "Stock Price Catalysts",
      РЫНОЧНЫЕ_ДАННЫЕ: "Market Data and Liquidity",
      СИЛЬНЫЕ_СТОРОНЫ: "Strengths and Competitive Advantages",
      СЛАБЫЕ_СТОРОНЫ: "Risks and Weaknesses",
      ВОЗМОЖНОСТИ: "Growth Opportunities",
      УГРОЗЫ: "Threats and External Risks",
      ПРОГНОЗ: "Company Development Forecast",
      ВЕРДИКТ: "Investment Verdict",
      СОВЕТЫ: "Investor Recommendations",
      ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА: "Analysis Limitations",
      ИТОГ: "Executive Summary",
      ЗЕЛЕНЫЕ_ФЛАГИ: "Positive Signals",
      КРАСНЫЕ_ФЛАГИ: "Warning Signals",
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
    nav: { main: "Bosh sahifa", about: "Loyiha haqida", auth: "Kirish", profile: "Profil", analysis: "Tahlil", catalog: "Katalog" },
    catalog: {
      title: "Hisobotlar katalogi",
      subtitle: "openinfo.uz'dan barcha ro'yxatga olingan kompaniyalarning hisobotlari",
      searchPlaceholder: "Ticker yoki nomi bo'yicha qidirish...",
      syncAll: "Hammasini sinxronlash",
      syncCompany: "Yangilash",
      syncing: "Sinxronlanmoqda...",
      syncDone: "Yangilandi",
      empty: "Katalog bo'sh — «Hammasini sinxronlash» ni bosing",
      selectCompany: "Ro'yxatdan kompaniyani tanlang",
      noReports: "Hisobotlar topilmadi",
      notPublished: "Tanlangan davr uchun bu turdagi hisobot e'lon qilinmagan",
      available: "Hisobot mavjud",
      loading: "Yuklanmoqda...",
      reports: "hisobot",
      companies: "kompaniya",
      totalReports: "bazadagi hisobotlar",
      lastSync: "Oxirgi yangilanish",
      forms: { NSBU: "NSBU", MSFO: "MHXS", Audition: "Audit" },
      periods: { annual: "Yillik", q1: "Q1", q2: "Q2", q3: "Q3" },
      analysisLabel: "Tahlil turi",
      runAnalysis: "Tahlilni ishga tushirish",
      analysisLoading: "Tahlil qilinmoqda...",
      analysisTypes: {
        financial: "Moliyaviy tahlil",
        ratio: "Koeffitsientlar (ROA, ROE...)",
        dynamics: "Ko'rsatkichlar dinamikasi",
        quarter_compare: "Choraklar taqqoslash",
        annual_compare: "Yillik hisobotlar taqqoslash",
        swot: "SWOT tahlili",
        recommendation: "Investitsiya tavsiyasi",
        multi_company: "Kompaniyalar taqqoslash",
      },
      compareWith: "Bilan solishtiring:",
      comparePeriod: "Taqqoslash davri:",
      noValue: "Ma'lumot yo'q",
      ratioLabels: { ROA: "ROA", ROE: "ROE", net_margin: "Sof marja", debt_ratio: "Qarz nisbati", debt_to_equity: "D/E" },
      dynamicsLabels: { revenue: "Daromad", net_income: "Sof foyda", total_assets: "Jami aktiv", equity: "Kapital", total_liabilities: "Majburiyatlar" },
      pdfReport: "PDFni ochish",
    },
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
      title: "Investitsion tahlil platformasi",
      copy: "O'zbek kompaniyalarining professional tahlilini soniyalar ichida oling. Moliyaviy salomatlik, xavflar va o'sish imkoniyatlari.",
      features: [
        { icon: "chart", title: "Chuqur tahlil", copy: "DCF baholash, sektor signallari, daromad va foyda dinamikasi" },
        { icon: "zap", title: "Tezkor natija", copy: "Grafik va tavsiyalar bilan to'liq hisobot soniyalar ichida" },
        { icon: "shield", title: "Ishonchli ma'lumot", copy: "O'zbekiston birjasidan to'g'ridan-to'g'ri yangilangan moliyaviy hisobotlar" },
        { icon: "target", title: "Aniq bashoratlar", copy: "Trend, katalizatorlar va bozor signallari tahlili" },
      ],
      howItWorks: {
        title: "Qanday ishlaydi",
        steps: [
          { num: "01", title: "Kompaniyani tanlang", copy: "Ticker kiriting yoki mavjud kompaniyalar katalogidan tanlang" },
          { num: "02", title: "Tahlilni boshlang", copy: "Tizim ma'lumotlarni yig'adi va keng qamrovli moliyaviy tahlil o'tkazadi" },
          { num: "03", title: "Hisobotni oling", copy: "Baho, grafik, metrikalar va investitsion tavsiyalarni ko'rib chiqing" },
        ],
      },
      stats: {
        title: "Platforma raqamlarda",
        items: [
          { value: "50+", label: "Kompaniyalar" },
          { value: "15+", label: "Tahlil metrikasi" },
          { value: "24/7", label: "Mavjudlik" },
          { value: "100%", label: "Bepul" },
        ],
      },
      cta: {
        title: "Boshlashga tayyormisiz?",
        copy: "Bepul ro'yxatdan o'ting va barcha tahlil vositalariga kirish imkoniyatiga ega bo'ling",
        button: "Tahlilni boshlash",
      },
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
        { title: "Metrikalar", copy: "DCF, sektor signallari, likvidlik va trend dinamikasi." },
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
      reportType: "Tahlil turi",
      fullAnalysis: "To'liq tahlil",
      quarterlyReport: "Choraklik",
      annualReport: "Yillik",
      quarter: "Chorak",
      currentYear: "Taqqoslanadigan yil",
      previousYear: "Bilan solishtirish",
      reportingForm: "Hisobot shakli",
      reportFormIFRS: "MXHS",
      reportFormNAS: "MHBS",
      reportFormAudit: "Auditorlik xulosasi",
      reportFormHint: "Shakl tanlash faqat choraklik/yillik taqqoslash rejimiga ta'sir qiladi. MHBS — openinfo.uz'da Excel ma'lumotlari mavjud bo'lgan yagona shakl. MXHS va auditorlik xulosalari Excel jadvallarsiz PDF formatida nashr etiladi.",
      reportFormLatestNote: "«To'liq tahlil» rejimida ma'lumotlar MHBS tizimli hisobotlaridan (forma 1 + forma 2) olinadi. Hisobot shakli faqat choraklik/yillik taqqoslashda qo'llaniladi.",
      reportFormNotFound: "Kompaniya tanlangan davr uchun ushbu turdagi hisobotni nashr etmagan.",
      forceRefresh: "Manbadan yangilash (keshni chetlab o'tish)",
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
      signalDebt: "Majburiyatlar",
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
      ОБЩИЕ_СВЕДЕНИЯ: "Emitent haqida umumiy ma'lumot va tahlil metodologiyasi",
      ГОРИЗОНТАЛЬНЫЙ_АНАЛИЗ: "Buxgalteriya balansining gorizontal tahlili",
      ВЕРТИКАЛЬНЫЙ_АНАЛИЗ: "Buxgalteriya balansining vertikal tahlili",
      АНАЛИЗ_ФИНРЕЗУЛЬТАТОВ: "Moliyaviy natijalar hisoboti tahlili",
      КОЭФФИЦИЕНТНЫЙ_АНАЛИЗ: "Moliyaviy koeffitsientlar tahlili",
      СВОДНАЯ_ТАБЛИЦА: "Asosiy ko'rsatkichlarning umumlashtirilgan jadvali",
      ЗАКЛЮЧЕНИЕ: "Yakuniy baho va investitsion tavsiya",
      СКОРИНГ: "Umumiy baholash va skoringi",
      ДОСЬЕ: "Emitent haqida qisqacha ma'lumot",
      ЧТО_С_ДЕНЬГАМИ: "Moliyaviy holat qisqacha",
      ТРЕНД: "Trendlar va dinamika tahlili",
      ЭФФЕКТИВНОСТЬ: "Operatsion samaradorlik va aylanma",
      ТЕХНИЧЕСКИЙ_АНАЛИЗ: "Texnik tahlil (RSI, Fibonachchi, hajmlar)",
      ОЦЕНКА_СТОИМОСТИ: "Adolatli qiymatni baholash",
      ФИБОНАЧЧИ: "Texnik tahlil (Fibonachchi darajalari)",
      ОЦЕНКА_ЦЕНЫ: "Investitsion jozibadorlikni baholash",
      КАТАЛИЗАТОРЫ: "Aksiya narxiga ta'sir qiluvchi omillar",
      РЫНОЧНЫЕ_ДАННЫЕ: "Bozor ma'lumotlari va likvidlik",
      СИЛЬНЫЕ_СТОРОНЫ: "Kuchli tomonlar va raqobatbardosh ustunliklar",
      СЛАБЫЕ_СТОРОНЫ: "Xavflar va zaif tomonlar",
      ВОЗМОЖНОСТИ: "O'sish imkoniyatlari",
      УГРОЗЫ: "Tahdidlar va tashqi xavflar",
      ПРОГНОЗ: "Kompaniya rivojlanishi prognozi",
      ВЕРДИКТ: "Investitsion xulosa",
      СОВЕТЫ: "Investorga tavsiyalar",
      ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА: "Tahlil cheklovlari",
      ИТОГ: "Investor uchun xulosa",
      ЗЕЛЕНЫЕ_ФЛАГИ: "Ijobiy signallar",
      КРАСНЫЕ_ФЛАГИ: "Ogohlantiruvchi signallar",
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

const VISUAL_TEXTS = {
  ru: {
    dashboardPeriod: "14 дней",
    sparklineEmpty: "пока нет истории",
    financialStructure: "Финансовая структура",
    financialStructureCopy: "Последние доступные данные МСФО",
    scoreAndRisk: "Скоринг и устойчивость",
    scoreAndRiskCopy: "Ключевые индикаторы качества и риска",
    revenue: "Выручка",
    netIncome: "Чистая прибыль",
    assets: "Активы",
    equity: "Капитал",
    debt: "Обязательства",
    totalScore: "Итоговый скоринг",
    piotroski: "Piotroski",
    altman: "Altman Z",
    leverage: "Долговая нагрузка",
    noVisualData: "Недостаточно данных для визуализации",
    latestPeriod: "последний период",
  },
  en: {
    dashboardPeriod: "14 days",
    sparklineEmpty: "no history yet",
    financialStructure: "Financial structure",
    financialStructureCopy: "Latest available IFRS data",
    scoreAndRisk: "Score and resilience",
    scoreAndRiskCopy: "Core quality and risk indicators",
    revenue: "Revenue",
    netIncome: "Net income",
    assets: "Assets",
    equity: "Equity",
    debt: "Liabilities",
    totalScore: "Total score",
    piotroski: "Piotroski",
    altman: "Altman Z",
    leverage: "Leverage",
    noVisualData: "Not enough data to visualize",
    latestPeriod: "latest period",
  },
  uz: {
    dashboardPeriod: "14 kun",
    sparklineEmpty: "hozircha tarix yo'q",
    financialStructure: "Moliyaviy tuzilma",
    financialStructureCopy: "So'nggi mavjud IFRS ma'lumotlari",
    scoreAndRisk: "Skoring va barqarorlik",
    scoreAndRiskCopy: "Sifat va risk bo'yicha asosiy indikatorlar",
    revenue: "Daromad",
    netIncome: "Sof foyda",
    assets: "Aktivlar",
    equity: "Kapital",
    debt: "Majburiyatlar",
    totalScore: "Yakuniy skoring",
    piotroski: "Piotroski",
    altman: "Altman Z",
    leverage: "Qarz yuki",
    noVisualData: "Vizualizatsiya uchun ma'lumot yetarli emas",
    latestPeriod: "so'nggi davr",
  },
};

const DISCLOSURE_TEXTS = {
  ru: {
    capabilitiesLabel: "Информационный контур",
    capabilitiesTitle: "Система должна обеспечивать",
    capabilitiesIntro: "Система проектируется как справочный слой для просмотра рыночной информации и базовых данных фондового рынка.",
    capabilities: [
      "Просмотр котировок",
      "Просмотр графиков цен",
      "Просмотр объемов торгов",
      "Просмотр списка эмитентов",
      "Просмотр облигаций",
      "Просмотр новостей",
      "Просмотр листинга и делистинга",
      "Просмотр режимов торгов",
      "Просмотр тарифов",
      "Просмотр терминов фондового рынка",
      "Просмотр общерыночной статистики",
    ],
    restrictionsLabel: "Публичные ограничения",
    restrictionsTitle: "Ограничения публичного контура",
    restrictionsIntro: "Публичная часть сервиса должна оставаться информационной и не подменять профессиональную консультацию.",
    restrictions: [
      "Персональные данные",
      "Прогнозная аналитика",
      "Инвестиционные рекомендации",
      "Индивидуальные аналитические выводы",
      "Юридические заключения",
    ],
  },
  en: {
    capabilitiesLabel: "Information scope",
    capabilitiesTitle: "The system should provide",
    capabilitiesIntro: "The system is designed as a reference layer for market data and basic stock market information.",
    capabilities: [
      "Quotes",
      "Price charts",
      "Trading volumes",
      "Issuer list",
      "Bonds",
      "News",
      "Listings and delistings",
      "Trading modes",
      "Tariffs",
      "Stock market terms",
      "Market-wide statistics",
    ],
    restrictionsLabel: "Public restrictions",
    restrictionsTitle: "Public scope restrictions",
    restrictionsIntro: "The public part of the service must remain informational and must not replace professional advice.",
    restrictions: [
      "Personal data",
      "Forecast analytics",
      "Investment recommendations",
      "Individual analytical conclusions",
      "Legal opinions",
    ],
  },
  uz: {
    capabilitiesLabel: "Axborot konturi",
    capabilitiesTitle: "Tizim ta'minlashi kerak",
    capabilitiesIntro: "Tizim bozor ma'lumotlari va fond bozori bo'yicha asosiy ma'lumotlarni ko'rish uchun axborot qatlami sifatida loyihalanadi.",
    capabilities: [
      "Kotirovkalarni ko'rish",
      "Narx grafiklarini ko'rish",
      "Savdo hajmlarini ko'rish",
      "Emitentlar ro'yxatini ko'rish",
      "Obligatsiyalarni ko'rish",
      "Yangiliklarni ko'rish",
      "Listing va delistingni ko'rish",
      "Savdo rejimlarini ko'rish",
      "Tariflarni ko'rish",
      "Fond bozori terminlarini ko'rish",
      "Umumbozor statistikasini ko'rish",
    ],
    restrictionsLabel: "Ommaviy cheklovlar",
    restrictionsTitle: "Ommaviy kontur cheklovlari",
    restrictionsIntro: "Servisning ommaviy qismi axborot xarakterida bo'lishi va professional maslahat o'rnini bosmasligi kerak.",
    restrictions: [
      "Shaxsiy ma'lumotlar",
      "Prognoz analitikasi",
      "Investitsion tavsiyalar",
      "Individual analitik xulosalar",
      "Huquqiy xulosalar",
    ],
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

function vt(language, key) {
  const lang = normalizeLanguage(language);
  return VISUAL_TEXTS[lang]?.[key] ?? VISUAL_TEXTS.ru[key] ?? key;
}

function disclosureText(language) {
  return DISCLOSURE_TEXTS[normalizeLanguage(language)] ?? DISCLOSURE_TEXTS.ru;
}

const COMPARE_TEXTS = {
  ru: {
    nav: "Сравнение",
    title: "Сравнение эмитентов",
    subtitle: "Сравните 2-3 компании по МСФО, рыночной ликвидности, отчетам и нормализованным показателям 0-100.",
    company1: "Компания 1",
    company2: "Компания 2",
    company3: "Компания 3",
    placeholder: "Тикер или название компании",
    optional: "необязательно",
    includeAi: "Сформировать comparative AI summary",
    submit: "Сравнить",
    loading: "Сравнение выполняется...",
    ready: "Сравнение готово",
    authRequired: "Сначала выполните вход",
    minRequired: "Выберите минимум две разные компании",
    overview: "Итог сравнения",
    leaders: "Лидеры по ключевым блокам",
    charts: "Сравнительные графики",
    tables: "Сравнительные таблицы",
    aiSummary: "Comparative AI summary",
    methodology: "Методика",
    ranking: "Рейтинг",
    normalizedRanking: "Нормализованный рейтинг",
    normalizedNote: "Все разнородные метрики приведены к шкале 0-100: чем выше, тем сильнее позиция компании.",
    noData: "Нет данных",
    empty: "Добавьте 2-3 компании и запустите сравнение.",
    quick: "Быстрый выбор",
    errors: "Предупреждения",
    raw: "значение",
    normalized: "норм.",
    rank: "место",
  },
  en: {
    nav: "Compare",
    title: "Issuer comparison",
    subtitle: "Compare 2-3 companies by IFRS metrics, market liquidity, reports, and normalized 0-100 indicators.",
    company1: "Company 1",
    company2: "Company 2",
    company3: "Company 3",
    placeholder: "Ticker or company name",
    optional: "optional",
    includeAi: "Generate comparative AI summary",
    submit: "Compare",
    loading: "Comparison is running...",
    ready: "Comparison is ready",
    authRequired: "Please sign in first",
    minRequired: "Select at least two different companies",
    overview: "Comparison result",
    leaders: "Leaders by key blocks",
    charts: "Comparative charts",
    tables: "Comparative tables",
    aiSummary: "Comparative AI summary",
    methodology: "Methodology",
    ranking: "Ranking",
    normalizedRanking: "Normalized ranking",
    normalizedNote: "Different metrics are normalized to a 0-100 scale: higher means a stronger relative position.",
    noData: "No data",
    empty: "Add 2-3 companies and run comparison.",
    quick: "Quick pick",
    errors: "Warnings",
    raw: "value",
    normalized: "norm.",
    rank: "rank",
  },
  uz: {
    nav: "Taqqoslash",
    title: "Emitentlarni taqqoslash",
    subtitle: "2-3 kompaniyani IFRS ko'rsatkichlari, bozor likvidligi, hisobotlar va 0-100 normalizatsiya bo'yicha solishtiring.",
    company1: "Kompaniya 1",
    company2: "Kompaniya 2",
    company3: "Kompaniya 3",
    placeholder: "Ticker yoki kompaniya nomi",
    optional: "ixtiyoriy",
    includeAi: "Comparative AI summary yaratish",
    submit: "Taqqoslash",
    loading: "Taqqoslash bajarilmoqda...",
    ready: "Taqqoslash tayyor",
    authRequired: "Avval tizimga kiring",
    minRequired: "Kamida ikki xil kompaniyani tanlang",
    overview: "Taqqoslash natijasi",
    leaders: "Asosiy bloklar bo'yicha liderlar",
    charts: "Taqqoslash grafiklari",
    tables: "Taqqoslash jadvallari",
    aiSummary: "Comparative AI summary",
    methodology: "Metodika",
    ranking: "Reyting",
    normalizedRanking: "Normalizatsiya reytingi",
    normalizedNote: "Turli metrikalar 0-100 shkalasiga keltiriladi: yuqori qiymat nisbatan kuchliroq pozitsiyani bildiradi.",
    noData: "Ma'lumot yo'q",
    empty: "2-3 kompaniya qo'shing va taqqoslashni boshlang.",
    quick: "Tez tanlash",
    errors: "Ogohlantirishlar",
    raw: "qiymat",
    normalized: "norm.",
    rank: "o'rin",
  },
};

function ct(language, key) {
  const lang = normalizeLanguage(language);
  return COMPARE_TEXTS[lang]?.[key] ?? COMPARE_TEXTS.ru[key] ?? key;
}

const MARKET_TEXTS = {
  ru: {
    nav: "Рынок",
    title: "Цены акций UZSE",
    subtitle: "Актуальные цены, дневной диапазон и изменение к предыдущему закрытию",
    updated: "Обновлено",
    refresh: "Обновить",
    loading: "Загружаем котировки...",
    ready: "Котировки загружены",
    empty: "Нет данных по выбранному фильтру",
    search: "Поиск по тикеру или компании",
    all: "Все",
    stocks: "Акции",
    bonds: "Облигации",
    instruments: "Инструментов",
    traded: "Сделки сегодня",
    advancers: "Рост",
    decliners: "Снижение",
    topGrowth: "Лидер роста",
    topDrop: "Лидер снижения",
    tableTitle: "Биржевые инструменты",
    showing: "Показано",
    ticker: "Тикер",
    company: "Компания",
    last: "Последняя",
    change: "Изм.",
    open: "Открытие",
    high: "Макс.",
    low: "Мин.",
    date: "Дата сделки",
    closeDate: "закр.",
    type: "Тип",
    ordinary: "обыкновенный",
    preferred: "привилегированный",
    source: "UZSE",
    analyze: "Анализ",
    noTrade: "нет сделки",
    volume: "Объём торгов",
    volumeCol: "Объём",
    tradeCount: "сделок",
  },
  en: {
    nav: "Market",
    title: "UZSE stock prices",
    subtitle: "Latest prices, daily range, and change versus previous close",
    updated: "Updated",
    refresh: "Refresh",
    loading: "Loading quotes...",
    ready: "Quotes loaded",
    empty: "No instruments for this filter",
    search: "Search ticker or company",
    all: "All",
    stocks: "Stocks",
    bonds: "Bonds",
    instruments: "Instruments",
    traded: "Traded today",
    advancers: "Up",
    decliners: "Down",
    topGrowth: "Top gainer",
    topDrop: "Top decliner",
    tableTitle: "Market instruments",
    showing: "Showing",
    ticker: "Ticker",
    company: "Company",
    last: "Last",
    change: "Chg.",
    open: "Open",
    high: "High",
    low: "Low",
    date: "Trade date",
    closeDate: "close",
    type: "Type",
    ordinary: "ordinary share",
    preferred: "preferred share",
    source: "UZSE",
    analyze: "Analyze",
    noTrade: "no trade",
    volume: "Volume",
    volumeCol: "Volume",
    tradeCount: "trades",
  },
  uz: {
    nav: "Bozor",
    title: "UZSE aksiya narxlari",
    subtitle: "So'nggi narxlar, kunlik oraliq va oldingi yopilish bilan farq",
    updated: "Yangilandi",
    refresh: "Yangilash",
    loading: "Kotirovkalar yuklanmoqda...",
    ready: "Kotirovkalar yuklandi",
    empty: "Bu filtr bo'yicha ma'lumot yo'q",
    search: "Ticker yoki kompaniya bo'yicha qidirish",
    all: "Hammasi",
    stocks: "Aksiyalar",
    bonds: "Obligatsiyalar",
    instruments: "Instrumentlar",
    traded: "Bugun savdo bo'lgan",
    advancers: "O'sish",
    decliners: "Pasayish",
    topGrowth: "Eng katta o'sish",
    topDrop: "Eng katta pasayish",
    tableTitle: "Bozor instrumentlari",
    showing: "Ko'rsatilgan",
    ticker: "Ticker",
    company: "Kompaniya",
    last: "So'nggi",
    change: "O'zg.",
    open: "Ochilish",
    high: "Maks.",
    low: "Min.",
    date: "Savdo sanasi",
    closeDate: "yop.",
    type: "Tur",
    ordinary: "oddiy aksiya",
    preferred: "imtiyozli aksiya",
    source: "UZSE",
    analyze: "Tahlil",
    noTrade: "savdo yo'q",
    volume: "Savdo hajmi",
    volumeCol: "Hajm",
    tradeCount: "savdo",
  },
};

const SECTOR_LABELS = {
  ru: {
    all: "Все",
    finance: "Финансы",
    manufacturing: "Производство",
    mining: "Добыча",
    transport: "Транспорт",
    telecom: "Телеком",
    trade: "Торговля",
    professional: "Услуги",
    other: "Прочее",
  },
  en: {
    all: "All",
    finance: "Finance",
    manufacturing: "Manufacturing",
    mining: "Mining",
    transport: "Transport",
    telecom: "Telecom",
    trade: "Trade",
    professional: "Services",
    other: "Other",
  },
  uz: {
    all: "Hammasi",
    finance: "Moliya",
    manufacturing: "Ishlab chiqarish",
    mining: "Konchilik",
    transport: "Transport",
    telecom: "Telekom",
    trade: "Savdo",
    professional: "Xizmatlar",
    other: "Boshqalar",
  },
};

function sectorLabel(language, sector) {
  const lang = normalizeLanguage(language);
  return SECTOR_LABELS[lang]?.[sector] ?? SECTOR_LABELS.ru[sector] ?? sector;
}

function mt(language, key) {
  const lang = normalizeLanguage(language);
  return MARKET_TEXTS[lang]?.[key] ?? MARKET_TEXTS.ru[key] ?? key;
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

function formatMarketNumber(value, language, digits = 2) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: Math.abs(num) < 10 ? 2 : 0,
    maximumFractionDigits: digits,
  }).format(num);
}

function formatCompactVolume(value, lang) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  if (num >= 1e9) return formatRatio(num / 1e9, 1, lang) + "B";
  if (num >= 1e6) return formatRatio(num / 1e6, 1, lang) + "M";
  if (num >= 1e3) return formatRatio(num / 1e3, 1, lang) + "K";
  return formatRatio(num, 0, lang);
}

function formatMarketTimestamp(value, language) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function marketChange(stock) {
  const last = safeNumber(stock?.last_price);
  const close = safeNumber(stock?.close_price);
  if (last === null || close === null || close === 0) {
    return { value: null, percent: null };
  }
  const value = last - close;
  return {
    value,
    percent: (value / Math.abs(close)) * 100,
  };
}

function marketTone(percent) {
  if (percent === null || percent === undefined || !Number.isFinite(Number(percent))) return "neutral";
  if (Number(percent) > 0.05) return "good";
  if (Number(percent) < -0.05) return "danger";
  return "neutral";
}

function enrichMarketStock(stock) {
  const change = marketChange(stock);
  return {
    ...stock,
    lastPrice: safeNumber(stock?.last_price),
    closePrice: safeNumber(stock?.close_price),
    openPrice: safeNumber(stock?.open) || null,
    highPrice: safeNumber(stock?.high) || null,
    lowPrice: safeNumber(stock?.low) || null,
    stockVolume: safeNumber(stock?.volume),
    stockQuantity: safeNumber(stock?.quantity),
    stockTradeCount: safeNumber(stock?.trade_count),
    changeValue: change.value,
    changePercent: change.percent,
    tone: marketTone(change.percent),
  };
}

function buildMarketStats(rows) {
  const traded = rows.filter((row) => row.lastPrice !== null).length;
  const advancers = rows.filter((row) => row.changePercent !== null && row.changePercent > 0.05).length;
  const decliners = rows.filter((row) => row.changePercent !== null && row.changePercent < -0.05).length;
  const withChange = rows.filter((row) => Number.isFinite(row.changePercent));
  const topGrowth = withChange.reduce((best, row) => (!best || row.changePercent > best.changePercent ? row : best), null);
  const topDrop = withChange.reduce((worst, row) => (!worst || row.changePercent < worst.changePercent ? row : worst), null);
  return { traded, advancers, decliners, topGrowth, topDrop };
}

const SCORE_EXPLANATION_TEXTS = {
  ru: {
    ranges: {
      A: "сильный диапазон 80-100",
      B: "хороший диапазон 60-79",
      C: "средний диапазон 40-59",
      D: "слабый диапазон ниже 40",
    },
    inputs: "Влияют",
    trend: "тренд",
    momentum: "импульс",
    dcf: "DCF",
    industry: "отрасль",
    liquidity: "ликвидность",
    noFactors: "Недостаточно сильных сигналов, чтобы поднять компанию выше текущего класса",
    advice: {
      A: "Финансовое состояние выглядит сильным.",
      B: "До A нужны еще более устойчивые рост и прибыльность.",
      C: "До B нужны сильнее рост, прибыльность и устойчивость баланса.",
      D: "Нужны заметное улучшение прибыли, ликвидности и долговой нагрузки.",
    },
    signals: { bullish: "положительный", neutral: "нейтральный", bearish: "негативный" },
  },
  en: {
    ranges: {
      A: "strong 80-100 range",
      B: "good 60-79 range",
      C: "middle 40-59 range",
      D: "weak range below 40",
    },
    inputs: "Drivers",
    trend: "trend",
    momentum: "momentum",
    dcf: "DCF",
    industry: "industry",
    liquidity: "liquidity",
    noFactors: "There are not enough strong signals to lift the company above this class",
    advice: {
      A: "Financial condition looks strong.",
      B: "A needs more consistent growth and profitability.",
      C: "B needs stronger growth, profitability, and balance-sheet stability.",
      D: "Profit, liquidity, and debt load need clear improvement.",
    },
    signals: { bullish: "positive", neutral: "neutral", bearish: "negative" },
  },
  uz: {
    ranges: {
      A: "kuchli 80-100 oralig'i",
      B: "yaxshi 60-79 oralig'i",
      C: "o'rtacha 40-59 oralig'i",
      D: "40 dan past zaif oralig'i",
    },
    inputs: "Ta'sir qilganlar",
    trend: "trend",
    momentum: "impuls",
    dcf: "DCF",
    industry: "sektor",
    liquidity: "likvidlik",
    noFactors: "Kompaniyani hozirgi sinfdan yuqoriga olib chiqadigan kuchli signallar yetarli emas",
    advice: {
      A: "Moliyaviy holat kuchli ko'rinadi.",
      B: "A uchun o'sish va rentabellik yanada barqaror bo'lishi kerak.",
      C: "B uchun o'sish, rentabellik va balans barqarorligi kuchliroq bo'lishi kerak.",
      D: "Foyda, likvidlik va qarz yuki aniq yaxshilanishi kerak.",
    },
    signals: { bullish: "ijobiy", neutral: "neytral", bearish: "salbiy" },
  },
};

function scoreGradeCode(score) {
  const value = safeNumber(score);
  if (value === null) return null;
  if (value >= 80) return "A";
  if (value >= 60) return "B";
  if (value >= 40) return "C";
  return "D";
}

function buildScoreExplanation(total = {}, metrics = {}, language = "ru") {
  const lang = normalizeLanguage(language);
  const text = SCORE_EXPLANATION_TEXTS[lang] || SCORE_EXPLANATION_TEXTS.ru;
  const score = safeNumber(total?.score);
  const code = scoreGradeCode(score) || String(total?.grade || "").trim().slice(0, 1).toUpperCase();
  if (!["A", "B", "C", "D"].includes(code)) return "";
  const gradeCode = code;
  const factors = [];

  const trends = metrics?.trends || {};
  const trendScore = safeNumber(trends.overall_score);
  if (trendScore !== null) factors.push(`${text.trend} ${formatRatio(trendScore, 0, lang)}/12`);

  const momentum = metrics?.momentum || {};
  const momentumScore = safeNumber(momentum.overall_score);
  if (momentumScore !== null) {
    factors.push(`${text.momentum} ${formatRatio(momentumScore, 0, lang)}`);
  } else if (momentum.css) {
    factors.push(`${text.momentum} ${text.signals[momentum.css] || momentum.css}`);
  }

  const dcfSignal = metrics?.dcf?.signal;
  if (dcfSignal) factors.push(`${text.dcf} ${text.signals[dcfSignal] || dcfSignal}`);

  const industry = metrics?.industry || {};
  if (industry.good_count !== undefined || industry.weak_count !== undefined) {
    factors.push(`${text.industry} +${industry.good_count ?? 0}/-${industry.weak_count ?? 0}`);
  }

  const liquidityDays = metrics?.market_liquidity?.trade_days;
  if (liquidityDays !== undefined && liquidityDays !== null) {
    factors.push(`${text.liquidity} ${liquidityDays}/30`);
  }

  const range = text.ranges[gradeCode] || text.ranges.C;
  const factorText = factors.length ? `${text.inputs}: ${factors.slice(0, 3).join("; ")}.` : `${text.noFactors}.`;
  return `${gradeCode}: ${range}. ${factorText} ${text.advice[gradeCode] || text.advice.C}`;
}

function getSectionTitle(language, key) {
  return t(language, `sections.${key}`) || key.replaceAll("_", " ");
}

// 14 разделов из _analysis_prompt_v2 в analysis_service.py (public-information-v4-bank-aware-2026-05-27).
// Эти разделы выводятся сверху в строго заданном порядке, остальные — под катом «Дополнительно».
const PRIMARY_SECTIONS = [
  "СКОРИНГ",
  "ДОСЬЕ",
  "ЧТО_С_ДЕНЬГАМИ",
  "ТРЕНД",
  "ЭФФЕКТИВНОСТЬ",
  "ТЕХНИЧЕСКИЙ_АНАЛИЗ",
  "ОЦЕНКА_ЦЕНЫ",
  "КАТАЛИЗАТОРЫ",
  "СИЛЬНЫЕ_СТОРОНЫ",
  "СЛАБЫЕ_СТОРОНЫ",
  "РЫНОЧНЫЕ_ДАННЫЕ",
  "ВЕРДИКТ",
  "ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА",
  "ИТОГ",
];

function splitSections(sections) {
  const sourceEntries = sections ? Object.entries(sections) : [];
  const lookup = new Map(sourceEntries);
  const primary = [];
  const seen = new Set();
  for (const key of PRIMARY_SECTIONS) {
    if (lookup.has(key)) {
      primary.push([key, lookup.get(key)]);
      seen.add(key);
    }
  }
  const supplementary = sourceEntries.filter(([key]) => !seen.has(key));
  return { primary, supplementary };
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
      debt: safeNumber(row?.total_liabilities ?? row?.total_debt ?? row?.debt),
    }))
    .filter((row) => row.year !== undefined && row.year !== null && (row.revenue !== null || row.profit !== null || row.debt !== null));

  if (filtered.length < 2) return null;

  const width = 1000;
  const height = 340;
  const padding = { left: 74, right: 24, top: 28, bottom: 44 };
  const allValues = filtered.flatMap((row) => [row.revenue, row.profit, row.debt]).filter((value) => Number.isFinite(value));
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
  const debtPoints = filtered.map((row) => row.debt ?? min);
  const revenuePath = line(revenuePoints);
  const profitPath = line(profitPoints);
  const debtPath = line(debtPoints);
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
  const debtChange =
    Number.isFinite(latest.debt) && Number.isFinite(previous.debt)
      ? ((latest.debt - previous.debt) / Math.abs(previous.debt || 1)) * 100
      : null;

  return {
    width,
    height,
    filtered,
    areaPath,
    revenuePath,
    profitPath,
    debtPath,
    yTicks,
    latest,
    revenueChange,
    profitChange,
    debtChange,
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
      cached: 0,
      scoreTotal: 0,
      scoreCount: 0,
      avgScore: null,
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
    if (item?.from_cache) bucket.cached += 1;
    const score = safeNumber(item?.score ?? item?.summary?.score ?? item?.result?.summary?.score);
    if (score !== null) {
      bucket.scoreTotal += score;
      bucket.scoreCount += 1;
    }
  }

  const days = Array.from(dayMap.values()).map((day) => ({
    ...day,
    avgScore: day.scoreCount ? day.scoreTotal / day.scoreCount : null,
  }));
  const maxCount = Math.max(1, ...days.map((day) => day.count || 0));
  const maxCached = Math.max(1, ...days.map((day) => day.cached || 0));
  const total = days.reduce((sum, day) => sum + (day.count || 0), 0);
  const cachedTotal = days.reduce((sum, day) => sum + (day.cached || 0), 0);
  const scoreDays = days.filter((day) => day.avgScore !== null);
  const avgScore = scoreDays.length ? scoreDays.reduce((sum, day) => sum + day.avgScore, 0) / scoreDays.length : null;
  const peak = days.reduce((best, day) => (day.count > (best?.count || 0) ? day : best), days[0] || null);

  return { days, maxCount, maxCached, total, cachedTotal, avgScore, peak };
}

function buildSparkline(values, width = 220, height = 74) {
  const points = (Array.isArray(values) ? values : []).map((value) => safeNumber(value)).filter((value) => value !== null);
  if (!points.length) return null;

  let min = Math.min(...points);
  let max = Math.max(...points);
  if (min === max) {
    min -= 1;
    max += 1;
  }

  const padding = { left: 8, right: 8, top: 10, bottom: 12 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const range = max - min || 1;
  const x = (index) => padding.left + (points.length <= 1 ? innerWidth / 2 : (index / (points.length - 1)) * innerWidth);
  const y = (value) => padding.top + ((max - value) / range) * innerHeight;
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(2)} ${y(point).toFixed(2)}`).join(" ");
  const areaPath = `${path} L ${x(points.length - 1).toFixed(2)} ${height - padding.bottom} L ${x(0).toFixed(2)} ${height - padding.bottom} Z`;

  return { width, height, points, path, areaPath, latest: points.at(-1), min, max };
}

function scorePercent(score) {
  if (score === null || score === undefined || score === "") return null;
  const value = Number(score);
  if (!Number.isFinite(value)) return null;
  return clampPercent(value <= 10 ? value * 10 : value);
}

function scoreTone(score) {
  const value = scorePercent(score);
  if (value === null) return "neutral";
  if (value >= 70) return "good";
  if (value >= 45) return "warning";
  return "danger";
}

function clampPercent(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return null;
  return Math.max(0, Math.min(100, num));
}

function CompanyLogo({ logo, name, ticker }) {
  const [failed, setFailed] = React.useState(false);
  const letter = (ticker || name || "?")[0].toUpperCase();
  if (!logo || failed) {
    return <span className="chip-logo chip-logo-fallback">{letter}</span>;
  }
  return (
    <img
      className="chip-logo"
      src={logo}
      alt={name}
      onError={() => setFailed(true)}
      loading="lazy"
    />
  );
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

function DisclosureCard({ label, title, intro, items, tone = "neutral" }) {
  return (
    <article className={`panel disclosure-card tone-${tone}`}>
      <div className="panel-head">
        <div>
          <div className="panel-label">{label}</div>
          <h2>{title}</h2>
        </div>
      </div>
      <p className="panel-intro">{intro}</p>
      <ul className="disclosure-list">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </article>
  );
}

function MiniSparkline({ values, tone = "neutral", language }) {
  const data = buildSparkline(values);

  if (!data) {
    return <div className="mini-sparkline-empty" aria-label={vt(language, "sparklineEmpty")} />;
  }

  return (
    <svg className={`mini-sparkline tone-${tone}`} viewBox={`0 0 ${data.width} ${data.height}`} role="img" aria-label={vt(language, "dashboardPeriod")}>
      <path d={data.areaPath} className="mini-sparkline-area" />
      <path d={data.path} className="mini-sparkline-line" />
      {data.points.map((point, index) => {
        if (index !== data.points.length - 1) return null;
        const x = data.points.length <= 1 ? data.width / 2 : 8 + (index / (data.points.length - 1)) * (data.width - 16);
        const y = 10 + ((data.max - point) / (data.max - data.min || 1)) * (data.height - 22);
        return <circle key={index} cx={x} cy={y} r="4" className="mini-sparkline-dot" />;
      })}
    </svg>
  );
}

function DashboardMetricCard({ label, value, sub, tone = "neutral", sparkline, language }) {
  return (
    <article className={`dashboard-metric-card tone-${tone}`}>
      <div className="dashboard-metric-top">
        <div>
          <div className="profile-stat-label">{label}</div>
          <div className="profile-stat-value">{value}</div>
        </div>
        <span className="metric-pulse" />
      </div>
      <MiniSparkline values={sparkline} tone={tone} language={language} />
      <div className="profile-stat-sub">{sub}</div>
    </article>
  );
}

function ScoreGauge({ score, language }) {
  const numeric = safeNumber(score);
  const value = scorePercent(numeric) ?? 0;
  const radius = 48;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - (value / 100) * circumference;
  const tone = scoreTone(numeric);

  // Gradient colors based on tone
  const gradientColors = {
    good: ["#10b981", "#059669"],
    warning: ["#f59e0b", "#d97706"],
    danger: ["#ef4444", "#dc2626"],
    neutral: ["#ff9d00", "#e68a00"],
  };
  const [startColor, endColor] = gradientColors[tone] || gradientColors.neutral;

  return (
    <div className={`score-gauge tone-${tone}`}>
      <svg viewBox="0 0 128 128" role="img" aria-label={t(language, "analysis.score")}>
        <defs>
          <linearGradient id={`scoreGradient-${tone}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={startColor} />
            <stop offset="100%" stopColor={endColor} />
          </linearGradient>
          <filter id="gaugeGlow">
            <feGaussianBlur stdDeviation="2" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <circle className="score-gauge-track" cx="64" cy="64" r={radius} />
        <circle
          className="score-gauge-progress"
          cx="64"
          cy="64"
          r={radius}
          style={{
            strokeDasharray: circumference,
            strokeDashoffset: dashOffset,
            stroke: `url(#scoreGradient-${tone})`,
          }}
          filter="url(#gaugeGlow)"
        />
      </svg>
      <div className="score-gauge-center">
        <strong>{numeric === null ? "--" : Math.round(numeric)}</strong>
        <span>{t(language, "analysis.score")}</span>
      </div>
    </div>
  );
}

function MetricCard({ label, value, sub, tone = "neutral" }) {
  // Tone indicator icons
  const toneIcons = {
    good: "↑",
    warning: "→",
    danger: "↓",
    neutral: "•",
  };
  const icon = toneIcons[tone] || toneIcons.neutral;

  return (
    <article className={`metric-card metric-${tone} tone-${tone}`}>
      <div className="metric-header">
        <div className="metric-label">{label}</div>
        <span className={`metric-indicator tone-${tone}`}>{icon}</span>
      </div>
      <div className="metric-value">{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </article>
  );
}

const SECTION_LABELS = {
  ru: "РАЗДЕЛ",
  en: "SECTION",
  uz: "BO'LIM",
};

const SUPPLEMENTARY_LABELS = {
  ru: "ПРИЛОЖЕНИЕ",
  en: "APPENDIX",
  uz: "ILOVA",
};

// Subheaders we want to bold: any uppercase phrase (4-60 chars) ending with ":"
// covers RU/EN/UZ ("ЛИКВИДНОСТЬ:", "LIQUIDITY:", "LIKVIDLIK:") in one rule.
const UPPER_SUBHEADER_RE = /^[A-ZА-ЯЁЎҚҒҲ][A-ZА-ЯЁЎҚҒҲ0-9\s,'’\-/()&]{2,58}:\s*$/u;

// KV pair: short label, then value that *starts with a number or sign* — keeps
// real metric lines ("ROE: 15.2%") and rejects normal prose ("Главное: банк…").
const KV_LABEL_MAX = 40;
const KV_VALUE_NUMERIC_RE = /^\s*[+\-−]?\s*[\d(]/;

const TLDR_HEADER_RE = /^\s*(?:>\s*)?(?:TL;?DR|КРАТКО|Кратко|Brief|Qisqacha)\s*[-:：—]?\s*$/i;
const TLDR_INLINE_RE = /^\s*(?:>\s*)?(?:TL;?DR|КРАТКО|Кратко|Brief|Qisqacha)\s*[-:：—]\s*(.+)$/i;
const TLDR_STARTS_RE = /^\s*(?:>\s*)?(?:TL;?DR|КРАТКО|Кратко|Brief|Qisqacha)\b/i;
const TLDR_STRUCTURED_HINT_RE = /\b(?:Тон|Tone|Плюсы|Минусы|Pluses|Minuses|Strengths|Concerns|Score|Скор|Для\s+тебя|For\s+you|Bu\s+siz)\s*[-:：—]/i;
const TLDR_TONE_LABEL_RE = /^\s*Тон\s*[-:：—]\s*(.+)$/i;
const TLDR_SCORE_LABEL_RE = /^\s*Скор\s*[-:：—]\s*(.+)$/i;
const TLDR_PLUSES_LABEL_RE = /^\s*Плюсы\s*[-:：—]?\s*$/i;
const TLDR_MINUSES_LABEL_RE = /^\s*Минусы\s*[-:：—]?\s*$/i;
const TLDR_FORYOU_LABEL_RE = /^\s*Для\s+тебя\s*[-:：—]\s*(.+)$/i;
const TLDR_BULLET_RE = /^\s*[-•—]\s+(.+)$/;
const TLDR_TONE_KEYS = {
  позитивный: "positive",
  positive: "positive",
  ijobiy: "positive",
  умеренный: "neutral",
  умеренная: "neutral",
  neutral: "neutral",
  mixed: "neutral",
  смешанный: "neutral",
  o_rtacha: "neutral",
  "o'rtacha": "neutral",
  тревожный: "caution",
  тревожная: "caution",
  осторожно: "caution",
  caution: "caution",
  warning: "caution",
  ehtiyot: "caution",
  критичный: "critical",
  критическая: "critical",
  critical: "critical",
  негативный: "critical",
  негативная: "critical",
  tanqidiy: "critical",
  нет_данных: "unknown",
  unknown: "unknown",
  insufficient: "unknown",
  "ma'lumot_yo'q": "unknown",
};

function normalizeToneKey(raw) {
  if (!raw) return "unknown";
  const clean = String(raw)
    .toLowerCase()
    .replace(/[.,;!?].*$/, "")
    .replace(/\s+/g, "_")
    .trim();
  return TLDR_TONE_KEYS[clean] || TLDR_TONE_KEYS[clean.replace(/_.*$/, "")] || "neutral";
}

function splitInlineBullets(text) {
  if (!text) return [];
  const cleaned = text.replace(/^[-•—]\s*/, "");
  return cleaned
    .split(/\s+[-•—]\s+/)
    .map((s) => s.replace(/[\s.;,]+$/, "").trim())
    .filter(Boolean);
}

function parseInlineTldr(rawText) {
  if (!rawText) return null;
  const text = rawText.replace(/^\s*(?:>\s*)?(?:TL;?DR|КРАТКО|Кратко|Brief|Qisqacha)\s*[-:：—]?\s*/i, "").trim();
  if (!text) return null;

  const tldr = {
    tone: "neutral",
    toneRaw: null,
    score: null,
    pluses: [],
    minuses: [],
    forYou: null,
    summary: null,
  };

  const labelOrder = [
    { key: "tone", re: /Тон\s*[-:：—]\s*/i },
    { key: "score", re: /Скор\s*[-:：—]\s*/i },
    { key: "pluses", re: /Плюсы\s*[-:：—]\s*/i },
    { key: "minuses", re: /Минусы\s*[-:：—]\s*/i },
    { key: "forYou", re: /Для\s+тебя\s*[-:：—]\s*/i },
  ];

  const matches = [];
  for (const { key, re } of labelOrder) {
    const m = text.match(re);
    if (m && m.index !== undefined) {
      matches.push({ key, start: m.index, valueStart: m.index + m[0].length });
    }
  }
  if (!matches.length) {
    tldr.summary = text;
    return tldr;
  }
  matches.sort((a, b) => a.start - b.start);

  if (matches[0].start > 0) {
    const head = text.slice(0, matches[0].start).trim();
    if (head) tldr.summary = head;
  }

  for (let i = 0; i < matches.length; i++) {
    const current = matches[i];
    const end = i + 1 < matches.length ? matches[i + 1].start : text.length;
    const value = text.slice(current.valueStart, end).trim();
    if (!value) continue;
    if (current.key === "tone") {
      tldr.toneRaw = value;
      tldr.tone = normalizeToneKey(value);
    } else if (current.key === "score") {
      tldr.score = value;
    } else if (current.key === "pluses") {
      tldr.pluses = splitInlineBullets(value);
    } else if (current.key === "minuses") {
      tldr.minuses = splitInlineBullets(value);
    } else if (current.key === "forYou") {
      // The "Для тебя" value is the LAST inline label, so when the model crams
      // an entire section onto one line it greedily swallows the trailing hero
      // paragraph ("Статус: ... Причина — ..."). Cut it off so "Для тебя" stays
      // a short phrase and the rest renders as normal section text.
      const heroCut = value.search(/(?:Статус|Вывод|Итог|Резюме|Заключение)\s*[:：]/i);
      if (heroCut > 0) {
        tldr.forYou = value.slice(0, heroCut).trim();
        tldr.trailing = value.slice(heroCut).trim();
      } else {
        tldr.forYou = value;
      }
    }
  }

  return tldr;
}

function parseTldrBlock(body) {
  if (!body) return { tldr: null, rest: body };
  const lines = body.split("\n");

  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (!trimmed) continue;
    if (!TLDR_STARTS_RE.test(trimmed)) return { tldr: null, rest: body };
    start = i;
    break;
  }
  if (start === -1) return { tldr: null, rest: body };

  const firstLine = lines[start].trim();
  const firstLineHasStructuredHint = TLDR_STRUCTURED_HINT_RE.test(firstLine);

  // CASE A: LLM emitted TL;DR as a single dense line with inline labels
  // ("TL;DR Тон: ... Плюсы: - ... Минусы: - ... Для тебя: ...").
  // Consume the whole TL;DR header line and parse it inline.
  if (firstLineHasStructuredHint) {
    const tldr = parseInlineTldr(firstLine);
    if (tldr && (tldr.pluses.length || tldr.minuses.length || tldr.forYou || tldr.toneRaw || tldr.summary)) {
      let rest = lines.slice(0, start).concat(lines.slice(start + 1)).join("\n").replace(/^\s+|\s+$/g, "");
      if (tldr.trailing) {
        rest = `${tldr.trailing}\n\n${rest}`.replace(/^\s+|\s+$/g, "");
        delete tldr.trailing;
      }
      return { tldr, rest };
    }
  }

  // CASE B: classic multiline structured block.
  let headerLines = 1;
  let inlineSummary = null;
  const inlineMatch = firstLine.match(TLDR_INLINE_RE);
  if (inlineMatch) {
    inlineSummary = inlineMatch[1].trim();
  }

  const tldr = {
    tone: "neutral",
    toneRaw: null,
    score: null,
    pluses: [],
    minuses: [],
    forYou: null,
    summary: inlineSummary,
  };

  let cursor = start + headerLines;
  let activeList = null;
  let consumed = cursor;

  while (cursor < lines.length) {
    const trimmed = lines[cursor].trim();
    if (!trimmed) {
      cursor += 1;
      consumed = cursor;
      continue;
    }

    let matched = false;

    const tone = trimmed.match(TLDR_TONE_LABEL_RE);
    if (tone) {
      tldr.toneRaw = tone[1].trim();
      tldr.tone = normalizeToneKey(tone[1]);
      activeList = null;
      matched = true;
    }

    const score = !matched && trimmed.match(TLDR_SCORE_LABEL_RE);
    if (score) {
      tldr.score = score[1].trim();
      activeList = null;
      matched = true;
    }

    if (!matched && TLDR_PLUSES_LABEL_RE.test(trimmed)) {
      activeList = "pluses";
      matched = true;
    }
    if (!matched && TLDR_MINUSES_LABEL_RE.test(trimmed)) {
      activeList = "minuses";
      matched = true;
    }

    const forYou = !matched && trimmed.match(TLDR_FORYOU_LABEL_RE);
    if (forYou) {
      tldr.forYou = forYou[1].trim();
      activeList = null;
      matched = true;
    }

    const bullet = !matched && trimmed.match(TLDR_BULLET_RE);
    if (bullet && activeList) {
      tldr[activeList].push(bullet[1].trim());
      matched = true;
    }

    if (!matched) break;

    cursor += 1;
    consumed = cursor;
  }

  if (!tldr.pluses.length && !tldr.minuses.length && !tldr.forYou && !tldr.toneRaw && !tldr.summary) {
    // Last-resort: parse the first paragraph as inline.
    const fallback = parseInlineTldr(firstLine);
    if (fallback) {
      let rest = lines.slice(0, start).concat(lines.slice(start + 1)).join("\n").replace(/^\s+|\s+$/g, "");
      if (fallback.trailing) {
        rest = `${fallback.trailing}\n\n${rest}`.replace(/^\s+|\s+$/g, "");
        delete fallback.trailing;
      }
      return { tldr: fallback, rest };
    }
    return { tldr: null, rest: body };
  }

  const rest = lines.slice(0, start).concat(lines.slice(consumed)).join("\n").replace(/^\s+|\s+$/g, "");
  return { tldr, rest };
}

function tldrCardTitle(language, tone) {
  const dict = {
    ru: {
      positive: "Сильная сторона",
      neutral: "Смешанная картина",
      caution: "Требует внимания",
      critical: "Повышенный риск",
      unknown: "Недостаточно данных",
    },
    en: {
      positive: "Strong signal",
      neutral: "Mixed picture",
      caution: "Watch closely",
      critical: "Elevated risk",
      unknown: "Insufficient data",
    },
    uz: {
      positive: "Kuchli tomon",
      neutral: "Aralash holat",
      caution: "Diqqat talab qiladi",
      critical: "Yuqori xavf",
      unknown: "Ma'lumot yetarli emas",
    },
  };
  return dict[language]?.[tone] || dict.ru[tone] || dict.ru.neutral;
}

const TONE_ICONS = {
  positive: "✓",
  neutral: "~",
  caution: "⚠",
  critical: "✗",
  unknown: "?",
};

function TldrCard({ tldr, language = "ru", variant = "default" }) {
  if (!tldr) return null;
  const hasPluses = tldr.pluses?.length > 0;
  const hasMinuses = tldr.minuses?.length > 0;
  const labels = {
    ru: { pluses: "Плюсы", minuses: "Минусы", forYou: "Что это значит для тебя" },
    en: { pluses: "Strengths", minuses: "Concerns", forYou: "What this means for you" },
    uz: { pluses: "Kuchli tomonlar", minuses: "Zaif tomonlar", forYou: "Bu siz uchun nimani anglatadi" },
  }[language] || {
    ru: { pluses: "Плюсы", minuses: "Минусы", forYou: "Что это значит для тебя" },
  }.ru;

  return (
    <div className={`tldr-card tldr-card--${tldr.tone} tldr-card--${variant}`}>
      <div className="tldr-card__head">
        <span className="tldr-card__tone-icon" aria-hidden="true">{TONE_ICONS[tldr.tone] || "~"}</span>
        <span className="tldr-card__tone-label">{tldrCardTitle(language, tldr.tone)}</span>
        {tldr.score && <span className="tldr-card__score">{tldr.score}</span>}
      </div>
      {tldr.summary && <p className="tldr-card__summary">{tldr.summary}</p>}
      <div className="tldr-card__body">
        {hasPluses && (
          <div className="tldr-card__col tldr-card__col--pos">
            <div className="tldr-card__col-label">{labels.pluses}</div>
            <ul>
              {tldr.pluses.map((item, idx) => <li key={`p-${idx}`}>{item}</li>)}
            </ul>
          </div>
        )}
        {hasMinuses && (
          <div className="tldr-card__col tldr-card__col--neg">
            <div className="tldr-card__col-label">{labels.minuses}</div>
            <ul>
              {tldr.minuses.map((item, idx) => <li key={`m-${idx}`}>{item}</li>)}
            </ul>
          </div>
        )}
      </div>
      {tldr.forYou && (
        <div className="tldr-card__foryou">
          <span className="tldr-card__foryou-label">{labels.forYou}:</span>
          <span className="tldr-card__foryou-text">{tldr.forYou}</span>
        </div>
      )}
    </div>
  );
}

function pickFirstParagraph(text) {
  if (!text) return null;
  const blocks = text.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
  if (!blocks.length) return null;
  return blocks[0]
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .join(" ");
}

function HeroVerdictBlock({ analysisResult, language = "ru" }) {
  if (!analysisResult?.sections) return null;
  const scoringRaw = analysisResult.sections["СКОРИНГ"];
  const summaryRaw =
    analysisResult.sections["ИТОГ"] ||
    analysisResult.sections["ВЕРДИКТ"] ||
    null;
  if (!scoringRaw && !summaryRaw) return null;

  const { tldr: scoringTldr } = parseTldrBlock(scoringRaw || "");
  const { tldr: summaryTldr, rest: summaryRest } = parseTldrBlock(summaryRaw || "");
  const heroParagraph = pickFirstParagraph(summaryRest);

  const tone = scoringTldr?.tone || summaryTldr?.tone || "neutral";
  const score = scoringTldr?.score || null;
  const verdictTitle = tldrCardTitle(language, tone);
  const pluses = scoringTldr?.pluses?.length ? scoringTldr.pluses : summaryTldr?.pluses || [];
  const minuses = scoringTldr?.minuses?.length ? scoringTldr.minuses : summaryTldr?.minuses || [];
  const forYou = summaryTldr?.forYou || scoringTldr?.forYou || null;

  const headline = {
    ru: { lead: "Что показывает отчётность", pluses: "Главные плюсы", minuses: "Главные минусы", paragraph: "Простыми словами" },
    en: { lead: "What the report shows", pluses: "Key positives", minuses: "Key concerns", paragraph: "In plain language" },
    uz: { lead: "Hisobotda nima ko'rinmoqda", pluses: "Asosiy ijobiy tomonlar", minuses: "Asosiy salbiy tomonlar", paragraph: "Sodda til bilan" },
  }[language] || {
    lead: "Что показывает отчётность", pluses: "Главные плюсы", minuses: "Главные минусы", paragraph: "Простыми словами",
  };

  return (
    <article className={`hero-verdict hero-verdict--${tone}`}>
      <div className="hero-verdict__crown">
        <span className="hero-verdict__crown-label">{headline.lead}</span>
        {score && <span className="hero-verdict__crown-score">{score}</span>}
      </div>
      <div className="hero-verdict__headline">
        <span className="hero-verdict__icon" aria-hidden="true">{TONE_ICONS[tone] || "~"}</span>
        <h2 className="hero-verdict__title">{verdictTitle}</h2>
      </div>
      {(pluses.length > 0 || minuses.length > 0) && (
        <div className="hero-verdict__grid">
          {pluses.length > 0 && (
            <div className="hero-verdict__col hero-verdict__col--pos">
              <div className="hero-verdict__col-label">{headline.pluses}</div>
              <ul>
                {pluses.slice(0, 3).map((item, idx) => <li key={`hp-${idx}`}>{item}</li>)}
              </ul>
            </div>
          )}
          {minuses.length > 0 && (
            <div className="hero-verdict__col hero-verdict__col--neg">
              <div className="hero-verdict__col-label">{headline.minuses}</div>
              <ul>
                {minuses.slice(0, 3).map((item, idx) => <li key={`hm-${idx}`}>{item}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
      {heroParagraph && (
        <div className="hero-verdict__paragraph">
          <div className="hero-verdict__paragraph-label">{headline.paragraph}</div>
          <p>{heroParagraph}</p>
        </div>
      )}
      {!heroParagraph && forYou && (
        <div className="hero-verdict__paragraph">
          <div className="hero-verdict__paragraph-label">{headline.paragraph}</div>
          <p>{forYou}</p>
        </div>
      )}
    </article>
  );
}

function renderAnalysisContent(text, { keyPrefix = "analysis" } = {}) {
  if (!text) return null;
  const lines = text.split('\n');
  const elements = [];
  let tableBuffer = [];
  let inTable = false;
  let proseBuffer = [];

  const tableCaptionRe = /^(?:таблица|table|jadval)\b/i;

  const flushProse = () => {
    if (!proseBuffer.length) return;
    elements.push(
      <section key={`${keyPrefix}-detail-${elements.length}`} className="analysis-sector analysis-sector--detail">
        {proseBuffer.map(({ key, text: paragraph }) => (
          <p key={key} className="analysis-para">{paragraph}</p>
        ))}
      </section>
    );
    proseBuffer = [];
  };

  const popTableCaption = () => {
    if (!proseBuffer.length) return null;
    const last = proseBuffer[proseBuffer.length - 1].text.trim();
    if (!tableCaptionRe.test(last)) return null;
    proseBuffer = proseBuffer.slice(0, -1);
    return last;
  };

  const flushTable = () => {
    if (tableBuffer.length > 0) {
      const caption = popTableCaption();
      flushProse();
      const headers = tableBuffer[0].split('|').filter(c => c.trim()).map(c => c.trim());
      const rows = tableBuffer.slice(2).filter(row => !row.match(/^\|[-\s|]+\|$/));
      elements.push(
        <section key={`${keyPrefix}-table-${elements.length}`} className="analysis-sector analysis-sector--table">
          {caption && <div className="analysis-sector__caption">{caption}</div>}
          <div className="analysis-table-wrap">
            <table className="analysis-table">
              <thead>
                <tr>{headers.map((h, i) => <th key={i}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((row, ri) => (
                  <tr key={ri} className={row.includes('ИТОГО') || row.includes('Итого') ? 'total-row' : ''}>
                    {row.split('|').filter(c => c.trim()).map((cell, ci) => {
                      const val = cell.trim();
                      const isNeg = val.startsWith('-') || val.startsWith('−');
                      const isPos = val.startsWith('+');
                      return <td key={ci} className={`${ci > 0 ? 'num' : ''} ${isNeg ? 'neg' : ''} ${isPos ? 'pos' : ''}`}>{val}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      );
      tableBuffer = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      inTable = true;
      tableBuffer.push(trimmed);
      continue;
    } else if (inTable) {
      flushTable();
      inTable = false;
    }

    if (!trimmed) {
      continue;
    } else if (trimmed.match(/^[0-9]+\.[0-9]+\.\s+/)) {
      flushProse();
      elements.push(<h3 key={`${keyPrefix}-subsec-${i}`} className="analysis-subsection">{trimmed}</h3>);
    } else if (UPPER_SUBHEADER_RE.test(trimmed)) {
      flushProse();
      elements.push(<h4 key={`${keyPrefix}-h4-${i}`} className="analysis-subheader">{trimmed}</h4>);
    } else if (trimmed.match(/^(Формула|Formula|Formula):/i) || trimmed.match(/^Формула:\s*.+=.+/i) || (trimmed.includes('=') && trimmed.match(/^\•?\s*[\w\s()]+\s*[=:]\s*.*[0-9]/))) {
      flushProse();
      elements.push(<div key={`${keyPrefix}-formula-${i}`} className="formula-box">{trimmed}</div>);
    } else if (trimmed.startsWith('•') || trimmed.startsWith('—') || trimmed.startsWith('-')) {
      flushProse();
      elements.push(<div key={`${keyPrefix}-bullet-${i}`} className="analysis-bullet">{trimmed}</div>);
    } else if (trimmed.match(/^[0-9]+\./)) {
      flushProse();
      elements.push(<div key={`${keyPrefix}-num-${i}`} className="analysis-numbered">{trimmed}</div>);
    } else if (trimmed.match(/^(✓|✗|🟢|🟡|🟠|🔴)/)) {
      const isGood = trimmed.startsWith('✓') || trimmed.startsWith('🟢');
      const isBad = trimmed.startsWith('✗') || trimmed.startsWith('🔴');
      flushProse();
      elements.push(<div key={`${keyPrefix}-check-${i}`} className={`analysis-check ${isGood ? 'good' : ''} ${isBad ? 'bad' : ''}`}>{trimmed}</div>);
    } else if (
      trimmed.includes(':') &&
      trimmed.split(':')[0].length < KV_LABEL_MAX &&
      !trimmed.startsWith('http') &&
      KV_VALUE_NUMERIC_RE.test(trimmed.split(':').slice(1).join(':').trim())
    ) {
      flushProse();
      const [label, ...rest] = trimmed.split(':');
      const value = rest.join(':').trim();
      elements.push(
        <div key={`${keyPrefix}-kv-${i}`} className="analysis-kv">
          <span className="analysis-kv-label">{label}:</span>
          <span className="analysis-kv-value">{value}</span>
        </div>
      );
    } else {
      proseBuffer.push({ key: `${keyPrefix}-p-${i}`, text: trimmed });
    }
  }

  flushTable();
  flushProse();
  return elements;
}

function SectionCard({ title, body, index, open = false, language = "ru" }) {
  const sectionLabel = SECTION_LABELS[language] || SECTION_LABELS.ru;
  const { tldr, rest } = parseTldrBlock(body);
  const summaryHint = tldr?.summary || tldr?.forYou || null;

  return (
    <details className={`section-card fade-in${tldr ? ` section-card--tone-${tldr.tone}` : ""}`} open={open}>
      <summary>
        <span className="section-number">{sectionLabel} {String(index + 1).padStart(2, "0")}</span>
        <span className="section-title-text">{title}</span>
        {summaryHint && <span className="section-tldr-inline">{summaryHint}</span>}
      </summary>
      <div className="section-content">
        {tldr && <TldrCard tldr={tldr} language={language} />}
        {renderAnalysisContent(rest, { keyPrefix: `section-${index}` })}
      </div>
    </details>
  );
}

const ARTICLE_SECTION_ORDER = [
  "ДОСЬЕ",
  "ЧТО_С_ДЕНЬГАМИ",
  "ТРЕНД",
  "ЭФФЕКТИВНОСТЬ",
  "ОЦЕНКА_ЦЕНЫ",
  "РЫНОЧНЫЕ_ДАННЫЕ",
  "ВЕРДИКТ",
  "ИТОГ",
];

const ARTICLE_SECTION_TITLES = {
  ru: {
    ДОСЬЕ: "Общие сведения об эмитенте и методология анализа",
    ЧТО_С_ДЕНЬГАМИ: "Горизонтальный и вертикальный анализ отчётности",
    ТРЕНД: "Анализ динамики показателей",
    ЭФФЕКТИВНОСТЬ: "Коэффициентный анализ",
    ОЦЕНКА_ЦЕНЫ: "Оценка стоимости и качества цены",
    РЫНОЧНЫЕ_ДАННЫЕ: "Публичные рыночные данные",
    ВЕРДИКТ: "Итоговая оценка качества отчётности",
    ИТОГ: "Заключение для частного инвестора",
  },
  en: {
    ДОСЬЕ: "Issuer overview and analysis method",
    ЧТО_С_ДЕНЬГАМИ: "Horizontal and vertical financial analysis",
    ТРЕНД: "Performance trend analysis",
    ЭФФЕКТИВНОСТЬ: "Ratio analysis",
    ОЦЕНКА_ЦЕНЫ: "Valuation and price quality",
    РЫНОЧНЫЕ_ДАННЫЕ: "Public market data",
    ВЕРДИКТ: "Final reporting-quality assessment",
    ИТОГ: "Conclusion for a private investor",
  },
  uz: {
    ДОСЬЕ: "Emitent haqida umumiy ma'lumot va tahlil usuli",
    ЧТО_С_ДЕНЬГАМИ: "Hisobotning gorizontal va vertikal tahlili",
    ТРЕНД: "Ko'rsatkichlar dinamikasi tahlili",
    ЭФФЕКТИВНОСТЬ: "Koeffitsiyentlar tahlili",
    ОЦЕНКА_ЦЕНЫ: "Qiymat va narx sifati",
    РЫНОЧНЫЕ_ДАННЫЕ: "Ochiq bozor ma'lumotlari",
    ВЕРДИКТ: "Hisobot sifati bo'yicha yakuniy baho",
    ИТОГ: "Xususiy investor uchun xulosa",
  },
};

function countReportTables(reportTables) {
  if (!reportTables || typeof reportTables !== "object") return 0;
  return Object.values(reportTables).reduce((sum, tables) => sum + (Array.isArray(tables) ? tables.length : 0), 0);
}

function articleTableCellClass(cell, columnIndex) {
  const value = String(cell ?? "").trim();
  const classes = [];
  if (columnIndex > 0) classes.push("num");
  if (value.startsWith("-") || value.startsWith("\u2212")) classes.push("neg");
  if (value.startsWith("+")) classes.push("pos");
  return classes.join(" ");
}

function isArticleTotalRow(row) {
  const label = String(Array.isArray(row) ? row[0] ?? "" : "").toLowerCase();
  return label.includes("итого") || label.includes("total") || label.includes("jami");
}

function StructuredReportBlocks({ blocks = [], keyPrefix = "article" }) {
  return blocks.map((block, index) => {
    if (block?.type === "subheading" && block.text) {
      return (
        <section key={`${keyPrefix}-subheading-${index}`} className="analysis-sector analysis-sector--subheading">
          <h4 className="article-subheading">{block.text}</h4>
        </section>
      );
    }
    if (block?.type === "rating") {
      return (
        <section key={`${keyPrefix}-rating-${index}`} className={`analysis-sector analysis-sector--rating tone-${block.tone || "neutral"}`}>
          <div className={`article-rating tone-${block.tone || "neutral"}`}>
            {block.label && <span className="article-rating__label">{block.label}</span>}
            <strong className="article-rating__value">{block.value ?? "—"}</strong>
            {block.text && <p>{block.text}</p>}
          </div>
        </section>
      );
    }
    if (block?.type === "kpi_grid") {
      const items = Array.isArray(block.items) ? block.items : [];
      if (!items.length) return null;
      return (
        <section key={`${keyPrefix}-kpi-${index}`} className="analysis-sector analysis-sector--kpi-grid">
          <div className="article-kpi-grid">
            {items.map((item, itemIndex) => (
              <div key={`${item.label || itemIndex}-${itemIndex}`} className={`article-kpi-card tone-${item.tone || "neutral"}`}>
                <span className="article-kpi-card__label">{item.label}</span>
                <strong className="article-kpi-card__value">{item.value ?? "—"}</strong>
                {item.hint && <p className="article-kpi-card__hint">{item.hint}</p>}
              </div>
            ))}
          </div>
        </section>
      );
    }
    if (block?.type === "formula") {
      return (
        <section key={`${keyPrefix}-formula-${index}`} className={`analysis-sector analysis-sector--formula tone-${block.tone || "neutral"}`}>
          <div className={`article-formula tone-${block.tone || "neutral"}`}>
            {block.title && <div className="article-formula__title">{block.title}</div>}
            <div className="article-formula__body">
              <code>{block.formula}</code>
              <strong>{block.result ?? "—"}</strong>
            </div>
            {block.description && <p>{block.description}</p>}
          </div>
        </section>
      );
    }
    if (block?.type === "verdict_summary") {
      const items = Array.isArray(block.items) ? block.items : [];
      if (!items.length) return null;
      return (
        <section key={`${keyPrefix}-verdict-summary-${index}`} className="analysis-sector analysis-sector--verdict-summary">
          <div className="article-verdict-summary">
            {items.map((item, itemIndex) => (
              <div key={`${item.label || itemIndex}-${itemIndex}`} className={`article-verdict-summary-card tone-${item.tone || "neutral"}`}>
                <span className="article-verdict-summary-card__label">{item.label}</span>
                {item.value && <strong className="article-verdict-summary-card__value">{item.value}</strong>}
                {item.text && <p className="article-verdict-summary-card__text">{item.text}</p>}
              </div>
            ))}
          </div>
        </section>
      );
    }
    if (block?.type === "verdict_list") {
      const items = Array.isArray(block.items) ? block.items : [];
      if (!items.length) return null;
      return (
        <section key={`${keyPrefix}-verdict-${index}`} className="analysis-sector analysis-sector--verdict-list">
          <div className="article-verdict-list">
            {items.map((item, itemIndex) => (
              <div key={`${item.label || itemIndex}-${itemIndex}`} className={`article-verdict-item tone-${item.tone || "neutral"}`}>
                <span>{item.label}</span>
                <p>{item.text}</p>
              </div>
            ))}
          </div>
        </section>
      );
    }
    if (block?.type === "table") {
      const headers = Array.isArray(block.headers) ? block.headers : [];
      const rows = Array.isArray(block.rows) ? block.rows : [];
      if (!headers.length || !rows.length) return null;
      return (
        <section key={`${keyPrefix}-table-${block.id || index}`} className="analysis-sector analysis-sector--table">
          {block.caption && <div className="analysis-sector__caption">{block.caption}</div>}
          {block.note && <div className="analysis-sector__note">{block.note}</div>}
          <div className="analysis-table-wrap">
            <table className="analysis-table">
              <thead>
                <tr>{headers.map((header, headerIndex) => <th key={headerIndex}>{header}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((row, rowIndex) => {
                  const cells = Array.isArray(row) ? row : [];
                  return (
                    <tr key={rowIndex} className={isArticleTotalRow(cells) ? "total-row" : ""}>
                      {cells.map((cell, cellIndex) => (
                        <td key={cellIndex} className={articleTableCellClass(cell, cellIndex)}>
                          {cell ?? "—"}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      );
    }
    if (block?.type === "paragraph" && block.text) {
      return (
        <section key={`${keyPrefix}-paragraph-${index}`} className="analysis-sector analysis-sector--detail">
          <p className="analysis-para">{block.text}</p>
        </section>
      );
    }
    return null;
  });
}

function ReportArticleView({ analysisResult, language = "ru" }) {
  const articleReport = analysisResult?.article_report?.sections?.length ? analysisResult.article_report : null;
  const sections = analysisResult?.sections || {};
  const ordered = ARTICLE_SECTION_ORDER
    .filter((key) => sections[key])
    .map((key) => [key, sections[key]]);
  const fallback = Object.entries(sections).filter(([key]) => !ARTICLE_SECTION_ORDER.includes(key));
  const entries = ordered.length ? ordered : fallback;
  if (!articleReport && !entries.length) return null;

  const dict = {
    ru: {
      desk: "UZ STOCK ANALYZER",
      title: "Анализ финансовой отчётности",
      subtitle: "Структурированный отчёт с таблицами и подробным разбором",
      annotation: "Аннотация",
      company: "Эмитент",
      ticker: "Тикер",
      annual: "Годовой период",
      quarterly: "Квартальный период",
      analysisPeriod: "Период анализа",
      comparison: "Сравнение",
      tables: "Таблиц",
      source: "Источник",
      fresh: "Свежий расчёт",
      cache: "Из кэша",
    },
    en: {
      desk: "UZ STOCK ANALYZER",
      title: "Financial Statement Analysis",
      subtitle: "Structured report with tables and detailed commentary",
      annotation: "Abstract",
      company: "Issuer",
      ticker: "Ticker",
      annual: "Annual period",
      quarterly: "Quarterly period",
      analysisPeriod: "Analysis period",
      comparison: "Comparison",
      tables: "Tables",
      source: "Source",
      fresh: "Fresh run",
      cache: "Cached",
    },
    uz: {
      desk: "UZ STOCK ANALYZER",
      title: "Moliyaviy hisobot tahlili",
      subtitle: "Jadvallar va batafsil izohlar bilan tuzilgan hisobot",
      annotation: "Annotatsiya",
      company: "Emitent",
      ticker: "Tiker",
      annual: "Yillik davr",
      quarterly: "Chorak davr",
      analysisPeriod: "Tahlil davri",
      comparison: "Taqqoslash",
      tables: "Jadval",
      source: "Manba",
      fresh: "Yangi hisob",
      cache: "Keshdan",
    },
  }[language] || {
    desk: "UZ STOCK ANALYZER",
    title: "Анализ финансовой отчётности",
    subtitle: "Структурированный отчёт с таблицами и подробным разбором",
    annotation: "Аннотация",
    company: "Эмитент",
    ticker: "Тикер",
    annual: "Годовой период",
    quarterly: "Квартальный период",
    analysisPeriod: "Период анализа",
    comparison: "Сравнение",
    tables: "Таблиц",
    source: "Источник",
    fresh: "Свежий расчёт",
    cache: "Из кэша",
  };

  const reportMeta = articleReport?.meta || {};
  const company = reportMeta.company || analysisResult.company_name || analysisResult.input || "—";
  const ticker = reportMeta.ticker || analysisResult.ticker || "—";
  const tableCount = reportMeta.table_count ?? countReportTables(analysisResult.report_tables);
  const selectedComparison = reportMeta.report_comparison?.label || analysisResult.report_comparison?.label || "";
  const summaryRaw = sections["ИТОГ"] || sections["ВЕРДИКТ"] || entries[0]?.[1] || "";
  const { rest: summaryRest } = parseTldrBlock(summaryRaw);
  const abstractText = articleReport?.abstract || pickFirstParagraph(summaryRest) || tldrCardTitle(language, "neutral");
  const sectionTitles = ARTICLE_SECTION_TITLES[language] || ARTICLE_SECTION_TITLES.ru;
  const articleSections = articleReport?.sections || [];

  return (
    <article className="report-article-panel">
      <div className="report-article">
        <header className="report-article__masthead">
          <div className="report-article__desk">{dict.desk}</div>
          <h2>{dict.title}</h2>
          <div className="report-article__subtitle">{dict.subtitle}</div>
          <div className="report-article__rule" aria-hidden="true"><span /><em>DATA REPORT</em><span /></div>
        </header>

        <div className="report-article__meta">
          {[
            [dict.company, company],
            [dict.ticker, ticker],
            [dict.annual, reportMeta.annual_period || analysisResult.annual_period || "—"],
            [dict.quarterly, reportMeta.quarterly_period || analysisResult.quarterly_period || "—"],
            [dict.analysisPeriod, reportMeta.analysis_period || reportMeta.analysis_comparison || "—"],
            ...(selectedComparison ? [[dict.comparison, selectedComparison]] : []),
            [dict.tables, tableCount || "—"],
            [dict.source, analysisResult.from_cache ? dict.cache : dict.fresh],
          ].map(([label, value]) => (
            <div className="report-article__meta-item" key={label}>
              <div className="report-article__meta-label">{label}</div>
              <div className="report-article__meta-value">{value}</div>
            </div>
          ))}
        </div>

        {abstractText && (
          <section className="report-article__abstract">
            <div className="report-article__abstract-label">{dict.annotation}</div>
            <p>{abstractText}</p>
          </section>
        )}

        <div className="report-article__body">
          {articleReport ? articleSections.map((section, index) => (
            <section className="report-article__section" key={section.id || index}>
              <span className="report-article__section-number">{section.number || String(index + 1).padStart(2, "0")}</span>
              <h3>{section.title || `${dict.tables} ${String(index + 1).padStart(2, "0")}`}</h3>
              <div className="report-article__section-content">
                <StructuredReportBlocks blocks={section.blocks || []} keyPrefix={`article-structured-${section.id || index}`} />
              </div>
            </section>
          )) : entries.map(([key, value], index) => {
            const { rest } = parseTldrBlock(value || "");
            if (!rest) return null;
            return (
              <section className="report-article__section" key={key}>
                <span className="report-article__section-number">{String(index + 1).padStart(2, "0")}</span>
                <h3>{sectionTitles[key] || getSectionTitle(language, key)}</h3>
                <div className="report-article__section-content">
                  {renderAnalysisContent(rest, { keyPrefix: `article-${index}-${key}` })}
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </article>
  );
}

const COMPARE_COLORS = ["#6ef0c1", "#f5b84d", "#7dd3fc"];

const COMPARE_TABLE_TITLES = {
  ru: {
    overview: "Обзор",
    profitability: "Прибыльность",
    growth: "Рост",
    balance: "Баланс и риск",
    market: "Рынок",
    documents: "Отчеты",
    category_scores: "Сводные категории",
  },
  en: {
    overview: "Overview",
    profitability: "Profitability",
    growth: "Growth",
    balance: "Balance and risk",
    market: "Market",
    documents: "Reports",
    category_scores: "Category scores",
  },
  uz: {
    overview: "Umumiy",
    profitability: "Rentabellik",
    growth: "O'sish",
    balance: "Balans va risk",
    market: "Bozor",
    documents: "Hisobotlar",
    category_scores: "Kategoriya ballari",
  },
};

const COMPARE_LEADER_LABELS = {
  ru: {
    overall_leader: "Общий лидер",
    profitability_leader: "Прибыльность",
    roe_leader: "ROE",
    balance_quality_leader: "Качество баланса",
    market_liquidity_leader: "Ликвидность",
    lowest_debt_ratio: "Минимальная долговая нагрузка",
  },
  en: {
    overall_leader: "Overall leader",
    profitability_leader: "Profitability",
    roe_leader: "ROE",
    balance_quality_leader: "Balance quality",
    market_liquidity_leader: "Liquidity",
    lowest_debt_ratio: "Lowest debt load",
  },
  uz: {
    overall_leader: "Umumiy lider",
    profitability_leader: "Rentabellik",
    roe_leader: "ROE",
    balance_quality_leader: "Balans sifati",
    market_liquidity_leader: "Likvidlik",
    lowest_debt_ratio: "Eng past qarz yuki",
  },
};

function compareTableTitle(language, key) {
  const lang = normalizeLanguage(language);
  return COMPARE_TABLE_TITLES[lang]?.[key] ?? key.replaceAll("_", " ");
}

function compareLeaderLabel(language, key) {
  const lang = normalizeLanguage(language);
  return COMPARE_LEADER_LABELS[lang]?.[key] ?? key.replaceAll("_", " ");
}

function formatCompareValue(value, language, unit = "") {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  const normalizedUnit = String(unit || "").trim();
  const formatted = Math.abs(num) >= 1000 ? formatCompactNumber(num, language, 2) : formatRatio(num, 2, language);
  if (normalizedUnit === "%") return `${formatted}%`;
  if (normalizedUnit === "x") return `${formatted}x`;
  if (normalizedUnit.startsWith("/")) return `${formatted}${normalizedUnit}`;
  if (!normalizedUnit) return formatted;
  return `${formatted} ${normalizedUnit}`;
}

function formatCompareCell(cell, column, language) {
  if (cell && typeof cell === "object" && !Array.isArray(cell)) {
    return {
      value: formatCompareValue(cell.raw, language, column?.unit),
      normalized: cell.normalized,
      rank: cell.rank,
    };
  }
  return {
    value: formatCompareValue(cell, language, column?.unit),
    normalized: null,
    rank: null,
  };
}

function getCompareSeriesData(series) {
  return Array.isArray(series?.data) ? series.data : Array.isArray(series?.values) ? series.values : [];
}

function getCompareAxisLabel(item) {
  if (!item || typeof item !== "object") return String(item || "");
  return item.ticker || item.company_name || item.label || "";
}

function CompareLeaderCards({ leaders, language }) {
  const entries = Object.entries(leaders || {}).filter(([, value]) => value);
  if (!entries.length) {
    return <div className="empty-state"><p className="empty-copy">{ct(language, "noData")}</p></div>;
  }

  return (
    <div className="compare-leader-grid">
      {entries.map(([key, value], index) => (
        <article key={key} className="compare-leader-card" style={{ "--series-color": COMPARE_COLORS[index % COMPARE_COLORS.length] }}>
          <span>{compareLeaderLabel(language, key)}</span>
          <strong>{value.ticker || value.company || "—"}</strong>
          <p>{formatCompareValue(value.value, language)}</p>
        </article>
      ))}
    </div>
  );
}

function CompareRanking({ title, rows, scoreKey, language }) {
  const items = Array.isArray(rows) ? rows : [];
  if (!items.length) return null;
  return (
    <article className="compare-ranking-card">
      <h3>{title}</h3>
      <div className="compare-ranking-list">
        {items.map((item) => (
          <div key={`${title}-${item.rank}-${item.ticker || item.company}`} className="compare-ranking-row">
            <span className="compare-rank">#{item.rank}</span>
            <span className="compare-company">{item.ticker || item.company || "—"}</span>
            <strong>{formatCompareValue(item[scoreKey], language, scoreKey.endsWith("score") ? "/100" : "")}</strong>
          </div>
        ))}
      </div>
    </article>
  );
}

function CompareRadarChart({ chart, language }) {
  const labels = Array.isArray(chart?.labels) ? chart.labels : [];
  const datasets = Array.isArray(chart?.datasets) ? chart.datasets : [];
  const size = 360;
  const center = size / 2;
  const radius = 116;
  const labelRadius = 150;

  if (labels.length < 3 || !datasets.length) {
    return <div className="compare-chart-empty">{ct(language, "noData")}</div>;
  }

  const point = (index, value, customRadius = radius) => {
    const angle = -Math.PI / 2 + (index / labels.length) * Math.PI * 2;
    const bounded = Math.max(0, Math.min(100, Number(value) || 0)) / 100;
    const r = customRadius * bounded;
    return {
      x: center + Math.cos(angle) * r,
      y: center + Math.sin(angle) * r,
    };
  };

  const ringPath = (level) =>
    labels
      .map((_, index) => {
        const p = point(index, 100, radius * level);
        return `${index === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
      })
      .join(" ") + " Z";

  return (
    <div className="compare-radar-wrap">
      <svg className="compare-radar" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={chart.title || ct(language, "charts")}>
        {[0.25, 0.5, 0.75, 1].map((level) => (
          <path key={level} className="compare-radar-ring" d={ringPath(level)} />
        ))}
        {labels.map((label, index) => {
          const edge = point(index, 100);
          const textPoint = point(index, 100, labelRadius);
          return (
            <g key={label.key || label.label || index}>
              <line className="compare-radar-axis" x1={center} y1={center} x2={edge.x} y2={edge.y} />
              <text className="compare-radar-label" x={textPoint.x} y={textPoint.y} textAnchor="middle">
                {label.label || label.key || index + 1}
              </text>
            </g>
          );
        })}
        {datasets.map((dataset, datasetIndex) => {
          const data = getCompareSeriesData(dataset);
          const path = labels
            .map((_, index) => {
              const p = point(index, data[index]);
              return `${index === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
            })
            .join(" ") + " Z";
          return (
            <g key={dataset.label || dataset.company_name || datasetIndex} style={{ "--series-color": COMPARE_COLORS[datasetIndex % COMPARE_COLORS.length] }}>
              <path className="compare-radar-area" d={path} />
              <path className="compare-radar-line" d={path} />
            </g>
          );
        })}
      </svg>
      <div className="compare-chart-legend">
        {datasets.map((dataset, index) => (
          <span key={dataset.label || dataset.company_name || index} className="legend-chip">
            <i className="legend-swatch" style={{ background: COMPARE_COLORS[index % COMPARE_COLORS.length] }} />
            {dataset.label || dataset.company_name || `#${index + 1}`}
          </span>
        ))}
      </div>
    </div>
  );
}

function CompareBarChart({ chart, language }) {
  const axis = Array.isArray(chart?.x) ? chart.x : [];
  const series = Array.isArray(chart?.series) ? chart.series : [];
  const values = series.flatMap((item) => getCompareSeriesData(item).map((value) => Math.abs(Number(value))).filter(Number.isFinite));
  const max = Math.max(1, ...values);

  if (!axis.length || !series.length) {
    return <div className="compare-chart-empty">{ct(language, "noData")}</div>;
  }

  return (
    <div className="compare-bars">
      {axis.map((item, rowIndex) => (
        <div key={`${getCompareAxisLabel(item)}-${rowIndex}`} className="compare-bar-company">
          <div className="compare-bar-company-name">{getCompareAxisLabel(item)}</div>
          <div className="compare-bar-series">
            {series.map((serie, serieIndex) => {
              const raw = getCompareSeriesData(serie)[rowIndex];
              const num = Number(raw);
              const isFiniteValue = Number.isFinite(num);
              const width = isFiniteValue ? Math.max(4, (Math.abs(num) / max) * 100) : 0;
              return (
                <div key={`${serie.key || serie.label}-${rowIndex}`} className="compare-bar-row">
                  <span>{serie.label || serie.key}</span>
                  <div className="compare-bar-track">
                    <i
                      className={isFiniteValue && num < 0 ? "is-negative" : ""}
                      style={{ width: `${width}%`, background: COMPARE_COLORS[serieIndex % COMPARE_COLORS.length] }}
                    />
                  </div>
                  <strong>{formatCompareValue(raw, language)}</strong>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function CompareChartCard({ chart, language }) {
  if (!chart) return null;
  const isRadar = chart.type === "radar";
  return (
    <article className={`chart-card compare-chart-card compare-chart-${chart.type || "bar"}`}>
      <div className="chart-head">
        <div>
          <div className="panel-label">{ct(language, "charts")}</div>
          <h3>{chart.title || ct(language, "charts")}</h3>
        </div>
        <span className="status-badge muted">{isRadar ? "0-100" : chart.type || "chart"}</span>
      </div>
      {isRadar ? <CompareRadarChart chart={chart} language={language} /> : <CompareBarChart chart={chart} language={language} />}
    </article>
  );
}

function CompareTable({ table, title, language }) {
  const columns = Array.isArray(table?.columns) ? table.columns : [];
  const rows = Array.isArray(table?.rows) ? table.rows : [];
  if (!columns.length || !rows.length) return null;

  return (
    <article className="compare-table-card">
      <div className="section-title-row">
        <h3>{title}</h3>
        <span className="muted">{rows.length}</span>
      </div>
      <div className="compare-table-scroll">
        <table className="compare-table">
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column.key}>{column.label || column.key}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={`${title}-${row.company_name || row.ticker || rowIndex}`}>
                {columns.map((column) => {
                  const cell = formatCompareCell(row[column.key], column, language);
                  return (
                    <td key={column.key}>
                      <strong>{cell.value}</strong>
                      {cell.normalized !== null && cell.normalized !== undefined ? (
                        <span>{ct(language, "normalized")}: {formatCompareValue(cell.normalized, language, "/100")}</span>
                      ) : null}
                      {cell.rank ? <em>#{cell.rank}</em> : null}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function CompareSummaryText({ summary, language }) {
  const text = summary?.text || summary?.summary || "";
  if (!text) {
    return <p className="empty-copy">{summary?.error || ct(language, "noData")}</p>;
  }
  return (
    <div className="compare-ai-text">
      {String(text)
        .split(/\n+/)
        .filter(Boolean)
        .map((line, index) => (
          <p key={index}>{line}</p>
        ))}
    </div>
  );
}

function MarketStatCard({ label, value, sub, tone = "neutral" }) {
  return (
    <article className={`market-stat-card tone-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {sub ? <em>{sub}</em> : null}
    </article>
  );
}

function MarketChangeBadge({ value, percent, language }) {
  const tone = marketTone(percent);
  const sign = Number(value) > 0 ? "+" : "";
  const percentSign = Number(percent) > 0 ? "+" : "";
  return (
    <span className={`market-change-badge tone-${tone}`}>
      {value === null || percent === null
        ? "—"
        : `${sign}${formatMarketNumber(value, language)} · ${percentSign}${formatRatio(percent, 2, language)}%`}
    </span>
  );
}

const SECTOR_ORDER = ["finance", "energy", "manufacturing", "telecom", "mining", "transport", "other"];

function heatmapTileStyle(changePercent) {
  if (changePercent === null || !Number.isFinite(changePercent)) return {};
  const abs = Math.abs(changePercent);
  // 0.1% → L 20%; 5%+ → L 42% (TradingView-style vivid HSL)
  const lightness = Math.min(20 + (abs / 5) * 22, 44).toFixed(0);
  if (changePercent > 0.1) return { background: `hsl(160 65% ${lightness}%)` };
  if (changePercent < -0.1) return { background: `hsl(0 70% ${lightness}%)` };
  return {};
}

function heatmapShortName(name) {
  if (!name) return "";
  // Extract content inside quotes: "Hamkorbank" ATB → Hamkorbank
  const m = name.match(/["""«»]([^"""«»]+)["""«»]/);
  const base = m ? m[1] : name.replace(/\s+(AJ|ATB|MK|OAJ|XK)\b.*/i, "").trim();
  return base.length > 13 ? base.slice(0, 12) + "…" : base;
}

function MarketHeatmap({ rows, companies, language, onAnalyze }) {
  const lang = normalizeLanguage(language);

  const companyMap = {};
  (companies || []).forEach((c) => { companyMap[c.ticker] = c; });

  // Group rows by sector, sort gainers first within each sector
  const sectorGroups = {};
  rows.forEach((row) => {
    const sector = companyMap[row.ticker]?.sector || "other";
    (sectorGroups[sector] = sectorGroups[sector] || []).push(row);
  });
  Object.values(sectorGroups).forEach((group) =>
    group.sort((a, b) => (b.changePercent ?? -Infinity) - (a.changePercent ?? -Infinity))
  );
  const orderedSectors = SECTOR_ORDER.filter((s) => sectorGroups[s]?.length);

  const formatPct = (pct) => {
    if (pct === null || !Number.isFinite(pct)) return "—";
    return `${pct > 0 ? "+" : ""}${formatRatio(pct, 2, lang)}%`;
  };

  const LEGEND_STOPS = [
    { pct: -5.5, label: "≤ −5%" },
    { pct: -2,   label: "−2%" },
    { pct: 0,    label: "0" },
    { pct: 2,    label: "+2%" },
    { pct: 5.5,  label: "≥ +5%" },
  ];

  return (
    <div className="heatmap-wrap">
      {/* Legend */}
      <div className="heatmap-legend">
        {LEGEND_STOPS.map(({ pct, label }) => {
          const s = heatmapTileStyle(pct);
          return (
            <span key={label} className="heatmap-legend-item">
              <span className="heatmap-legend-swatch" style={s.background ? { background: s.background } : undefined} />
              <span>{label}</span>
            </span>
          );
        })}
      </div>

      {/* Sector blocks */}
      {orderedSectors.map((sector) => {
        const tileRows = sectorGroups[sector];
        const label = sectorLabel(lang, sector);
        const withChange = tileRows.filter((r) => Number.isFinite(r.changePercent));
        const avgChange = withChange.length
          ? withChange.reduce((s, r) => s + r.changePercent, 0) / withChange.length
          : null;

        // Volume-proportional flex weights — high-volume stocks get wider tiles
        // Use sqrt to compress extreme volume differences, then clamp to [0.55, 2.2]
        // so no tile is more than ~4x wider than another
        const sectorVol = tileRows.reduce((s, r) => s + Math.sqrt(Math.max(r.stockVolume || 0, 1)), 0);
        const getWeight = (row) => {
          const raw = Math.sqrt(Math.max(row.stockVolume || 1, 1)) / sectorVol * tileRows.length;
          return Math.min(Math.max(raw, 0.55), 2.2);
        };

        return (
          <div key={sector} className="heatmap-sector">
            {/* Sector header strip */}
            <div className="heatmap-sector-strip">
              <span className="heatmap-sector-label">{label}</span>
              <span className="heatmap-sector-count">{tileRows.length}</span>
              {avgChange !== null && (
                <span className={`heatmap-sector-avg tone-${avgChange > 0.1 ? "good" : avgChange < -0.1 ? "danger" : "neutral"}`}>
                  {formatPct(avgChange)}
                </span>
              )}
            </div>

            {/* Tiles row — proportional width per volume */}
            <div className="heatmap-sector-tiles">
              {tileRows.map((row) => {
                const company = companyMap[row.ticker];
                const tileStyle = heatmapTileStyle(row.changePercent);
                const isNeutral = !tileStyle.background;
                const pctStr = formatPct(row.changePercent);
                const weight = getWeight(row);
                // Size class drives how much text to show
                const sz = weight >= 1.5 ? "lg" : "sm";
                const shortN = heatmapShortName(company?.company_name || row.name || "");
                const tooltip = [
                  row.name || company?.company_name || row.ticker,
                  row.lastPrice !== null ? `${lang === "ru" ? "Цена" : "Price"}: ${formatMarketNumber(row.lastPrice, lang)}` : null,
                  `${lang === "ru" ? "Изм." : "Chg."}: ${pctStr}`,
                  row.stockVolume ? `${lang === "ru" ? "Объём" : "Vol"}: ${formatCompactVolume(row.stockVolume, lang)}` : null,
                ].filter(Boolean).join("\n");

                return (
                  <button
                    key={row.ticker}
                    type="button"
                    className={`heatmap-tile heatmap-tile-${sz}${isNeutral ? " heatmap-tile-neutral" : ""}`}
                    style={{ ...tileStyle, "--vol-weight": weight }}
                    onClick={() => onAnalyze(row.ticker)}
                    title={tooltip}
                  >
                    {sz === "lg" && shortN && <span className="heatmap-tile-name">{shortN}</span>}
                    {sz !== "xs"  && <span className="heatmap-tile-ticker">{row.ticker}</span>}
                    <span className="heatmap-tile-pct">{pctStr}</span>
                    {sz === "lg" && row.lastPrice !== null && (
                      <span className="heatmap-tile-price">{formatMarketNumber(row.lastPrice, lang)}</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}

      {orderedSectors.length === 0 && (
        <p className="market-empty-cell">
          {lang === "ru" ? "Нет данных для карты" : lang === "uz" ? "Xarita uchun ma'lumot yo'q" : "No data for map"}
        </p>
      )}
    </div>
  );
}

function MarketView({
  rows,
  meta,
  trades,
  loading,
  message,
  query,
  onQueryChange,
  type,
  onTypeChange,
  onRefresh,
  onAnalyze,
  language,
  companies,
}) {
  const lang = normalizeLanguage(language);
  const [viewMode, setViewMode] = useState("table");
  const prepared = (Array.isArray(rows) ? rows : []).map(enrichMarketStock);
  const search = String(query || "").trim().toLowerCase();
  const visibleRows = prepared
    .filter((row) => {
      if (!search) return true;
      return `${row.ticker || ""} ${row.name || ""} ${row.isin || ""}`.toLowerCase().includes(search);
    })
    .sort((a, b) => {
      const aDate = a.last_trade_date || "";
      const bDate = b.last_trade_date || "";
      if (aDate !== bDate) return bDate.localeCompare(aDate);
      return Math.abs(b.changePercent ?? -Infinity) - Math.abs(a.changePercent ?? -Infinity);
    });
  const stats = buildMarketStats(prepared);
  const formatLeader = (row) => row ? `${row.ticker} ${formatRatio(row.changePercent, 2, lang)}%` : "—";

  return (
    <section className="market-layout">
      <article className="panel market-hero-panel">
        <div className="market-hero-copy">
          <div className="panel-label">{mt(lang, "nav")}</div>
          <h1>{mt(lang, "title")}</h1>
          <p>{mt(lang, "subtitle")}</p>
        </div>
        <div className="market-hero-actions">
          <span className="status-badge muted">{mt(lang, "updated")}: {formatMarketTimestamp(meta?.updated_at, lang)}</span>
          <button className="ghost-btn" type="button" onClick={onRefresh} disabled={loading}>
            {loading ? mt(lang, "loading") : mt(lang, "refresh")}
          </button>
        </div>
      </article>

      <div className="market-stats-grid">
        <MarketStatCard label={mt(lang, "instruments")} value={formatRatio(prepared.length || meta?.count || 0, 0, lang)} sub={message || mt(lang, "ready")} />
        <MarketStatCard label={mt(lang, "traded")} value={formatRatio(stats.traded, 0, lang)} sub={mt(lang, "date")} />
        <MarketStatCard label={mt(lang, "advancers")} value={formatRatio(stats.advancers, 0, lang)} sub={formatLeader(stats.topGrowth)} tone="good" />
        <MarketStatCard label={mt(lang, "decliners")} value={formatRatio(stats.decliners, 0, lang)} sub={formatLeader(stats.topDrop)} tone="danger" />
        {trades && <MarketStatCard label={mt(lang, "volume")} value={formatCompactVolume(trades.total_volume, lang)} sub={trades.total_trade_count ? `${formatRatio(trades.total_trade_count, 0, lang)} ${mt(lang, "tradeCount")}` : null} />}
      </div>

      <article className="panel market-board">
        <div className="market-board-head">
          <div>
            <div className="panel-label">{viewMode === "heatmap" ? (lang === "en" ? "Market Map" : lang === "uz" ? "Bozor xaritasi" : "Карта рынка") : mt(lang, "tableTitle")}</div>
            <h2>{viewMode === "heatmap" ? (lang === "en" ? "Market Map" : lang === "uz" ? "Bozor xaritasi" : "Карта рынка") : mt(lang, "tableTitle")}</h2>
          </div>
          <div className="market-board-head-right">
            <div className="market-view-toggle">
              <button
                type="button"
                className={viewMode === "table" ? "active" : ""}
                onClick={() => setViewMode("table")}
                title={lang === "en" ? "Table view" : lang === "uz" ? "Jadval ko'rinishi" : "Таблица"}
              >
                <svg width="15" height="15" viewBox="0 0 15 15" fill="currentColor">
                  <rect x="1" y="2" width="13" height="1.8" rx="0.9"/>
                  <rect x="1" y="6.6" width="13" height="1.8" rx="0.9"/>
                  <rect x="1" y="11.2" width="13" height="1.8" rx="0.9"/>
                </svg>
              </button>
              <button
                type="button"
                className={viewMode === "heatmap" ? "active" : ""}
                onClick={() => setViewMode("heatmap")}
                title={lang === "en" ? "Market map" : lang === "uz" ? "Bozor xaritasi" : "Карта рынка"}
              >
                <svg width="15" height="15" viewBox="0 0 15 15" fill="currentColor">
                  <rect x="1" y="1" width="5.8" height="5.8" rx="1.2"/>
                  <rect x="8.2" y="1" width="5.8" height="5.8" rx="1.2"/>
                  <rect x="1" y="8.2" width="5.8" height="5.8" rx="1.2"/>
                  <rect x="8.2" y="8.2" width="5.8" height="5.8" rx="1.2"/>
                </svg>
              </button>
            </div>
            {viewMode === "table" && (
              <span className="status-badge muted">{mt(lang, "showing")}: {visibleRows.length}/{prepared.length}</span>
            )}
          </div>
        </div>

        <div className="market-controls">
          <div className="segmented-control market-type-control">
            {[
              ["stock", mt(lang, "stocks")],
              ["bond", mt(lang, "bonds")],
              ["all", mt(lang, "all")],
            ].map(([value, label]) => (
              <button key={value} type="button" className={type === value ? "active" : ""} onClick={() => onTypeChange(value)}>
                {label}
              </button>
            ))}
          </div>
          {viewMode === "table" && (
            <label className="market-search">
              <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder={mt(lang, "search")} />
            </label>
          )}
        </div>

        {viewMode === "heatmap" ? (
          loading ? (
            <p className="market-empty-cell">{mt(lang, "loading")}</p>
          ) : (
            <MarketHeatmap rows={prepared} companies={companies} language={lang} onAnalyze={onAnalyze} />
          )
        ) : (
          <div className="market-table-wrap">
            <table className="market-table">
              <thead>
                <tr>
                  <th>{mt(lang, "ticker")}</th>
                  <th>{mt(lang, "company")}</th>
                  <th>{mt(lang, "last")}</th>
                  <th>{mt(lang, "change")}</th>
                  <th>{mt(lang, "open")}</th>
                  <th>{mt(lang, "high")}</th>
                  <th>{mt(lang, "low")}</th>
                  <th>{mt(lang, "volumeCol")}</th>
                  <th>{mt(lang, "date")}</th>
                  <th>{mt(lang, "source")}</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan="10" className="market-empty-cell">{mt(lang, "loading")}</td></tr>
                ) : visibleRows.length ? (
                  visibleRows.map((row) => (
                    <tr key={`${row.ticker}-${row.isin}`}>
                      <td>
                        <button type="button" className="market-ticker-btn" onClick={() => onAnalyze(row.ticker)}>
                          {row.ticker || "—"}
                        </button>
                        <span>{row.share_type ? mt(lang, row.share_type) : row.type || "—"}</span>
                      </td>
                      <td>
                        <strong>{row.name || "—"}</strong>
                        <span>{row.isin || "—"}</span>
                      </td>
                      <td className="num">{row.lastPrice === null ? "—" : formatMarketNumber(row.lastPrice, lang)}</td>
                      <td className="num"><MarketChangeBadge value={row.changeValue} percent={row.changePercent} language={lang} /></td>
                      <td className="num">{row.openPrice === null ? "—" : formatMarketNumber(row.openPrice, lang)}</td>
                      <td className="num">{row.highPrice === null ? "—" : formatMarketNumber(row.highPrice, lang)}</td>
                      <td className="num">{row.lowPrice === null ? "—" : formatMarketNumber(row.lowPrice, lang)}</td>
                      <td className="num">
                        {row.stockVolume !== null ? formatRatio(row.stockVolume, 0, lang) : "—"}
                        {row.stockQuantity !== null && <span>{formatRatio(row.stockQuantity, 0, lang)} шт. · {row.stockTradeCount !== null ? formatRatio(row.stockTradeCount, 0, lang) : "—"} {mt(lang, "tradeCount")}</span>}
                      </td>
                      <td>
                        <strong>{row.last_trade_date || mt(lang, "noTrade")}</strong>
                        {row.close_date && <span>{mt(lang, "closeDate")} {row.close_date}</span>}
                      </td>
                      <td>
                        {row.url ? (
                          <a className="market-source-link" href={row.url} target="_blank" rel="noreferrer">{mt(lang, "source")}</a>
                        ) : "—"}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr><td colSpan="10" className="market-empty-cell">{mt(lang, "empty")}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </article>
    </section>
  );
}

// ---------------------------------------------------------------------------
// CatalogView
// ---------------------------------------------------------------------------

function clg(language, key) {
  const parts = key.split(".");
  let cur = (TEXTS[language] || TEXTS.ru).catalog;
  for (const part of parts) {
    if (!cur || typeof cur !== "object") return key;
    cur = cur[part];
  }
  return cur !== undefined ? cur : key;
}

function CatalogRatioTable({ result, language }) {
  const metrics = result.metrics || {};
  const vals = result.source_values || {};
  const labelMap = (TEXTS[language] || TEXTS.ru).catalog.ratioLabels;
  const valLabels = (TEXTS[language] || TEXTS.ru).catalog.dynamicsLabels;
  const fmt = (v) => (v === null || v === undefined ? clg(language, "noValue") : `${v}%`);
  const fmtRaw = (v) => {
    if (v === null || v === undefined) return clg(language, "noValue");
    return new Intl.NumberFormat(language === "en" ? "en-US" : "ru-RU", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  };
  return (
    <div className="catalog-result-body">
      <div className="catalog-ratio-grid">
        {Object.entries(metrics).map(([k, v]) => (
          <div key={k} className={`catalog-ratio-card ${v !== null && v !== undefined ? (parseFloat(v) > 0 ? "tone-good" : "tone-danger") : ""}`}>
            <span className="ratio-name">{labelMap[k] || k}</span>
            <strong className="ratio-value">{k === "debt_to_equity" ? (v !== null ? v : clg(language, "noValue")) : fmt(v)}</strong>
          </div>
        ))}
      </div>
      <table className="catalog-source-table">
        <tbody>
          {Object.entries(vals).filter(([, v]) => v !== null).map(([k, v]) => (
            <tr key={k}><td>{valLabels[k] || k}</td><td className="num">{fmtRaw(v)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CatalogDynamicsTable({ result, language }) {
  const years = result.years || [];
  const series = result.series || {};
  const labels = (TEXTS[language] || TEXTS.ru).catalog.dynamicsLabels;
  const fmtN = (v) => {
    if (v === null || v === undefined) return "—";
    return new Intl.NumberFormat(language === "en" ? "en-US" : "ru-RU", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  };
  if (!years.length) return <p className="muted">{clg(language, "noReports")}</p>;
  return (
    <div className="catalog-result-body">
      <div className="catalog-table-wrap">
        <table className="market-table">
          <thead>
            <tr>
              <th>{language === "ru" ? "Показатель" : language === "uz" ? "Ko'rsatkich" : "Metric"}</th>
              {years.map((y) => <th key={y} className="num">{y}</th>)}
            </tr>
          </thead>
          <tbody>
            {Object.entries(series).map(([key, vals]) => (
              <tr key={key}>
                <td>{labels[key] || key}</td>
                {vals.map((v, i) => <td key={i} className="num">{fmtN(v)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CatalogCompareTable({ result, language }) {
  const p1 = result.period1 || {};
  const p2 = result.period2 || {};
  const m1 = p1.metrics || {};
  const m2 = p2.metrics || {};
  const v1 = p1.source_values || {};
  const v2 = p2.source_values || {};
  const ratioLabels = (TEXTS[language] || TEXTS.ru).catalog.ratioLabels;
  const valLabels = (TEXTS[language] || TEXTS.ru).catalog.dynamicsLabels;
  const periodLabel = (p) => p.quarter > 0 ? `Q${p.quarter} ${p.year}` : `${p.year}`;
  const fmt = (v, isPercent = true) => (v === null || v === undefined ? "—" : isPercent ? `${v}%` : String(v));
  const fmtN = (v) => {
    if (v === null || v === undefined) return "—";
    return new Intl.NumberFormat(language === "en" ? "en-US" : "ru-RU", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  };
  const diff = (a, b) => {
    if (a === null || b === null || a === undefined || b === undefined) return null;
    return Math.round((a - b) * 100) / 100;
  };
  return (
    <div className="catalog-result-body">
      <div className="catalog-table-wrap">
        <table className="market-table">
          <thead>
            <tr>
              <th>{language === "ru" ? "Показатель" : "Metric"}</th>
              <th className="num">{periodLabel(p1)}</th>
              <th className="num">{periodLabel(p2)}</th>
              <th className="num">{language === "ru" ? "Изменение" : "Change"}</th>
            </tr>
          </thead>
          <tbody>
            {Object.keys({ ...v1, ...v2 }).map((k) => (
              <tr key={k}>
                <td>{valLabels[k] || k}</td>
                <td className="num">{fmtN(v1[k])}</td>
                <td className="num">{fmtN(v2[k])}</td>
                <td className={`num ${diff(v1[k], v2[k]) > 0 ? "tone-good" : diff(v1[k], v2[k]) < 0 ? "tone-danger" : ""}`}>
                  {diff(v1[k], v2[k]) !== null ? fmtN(diff(v1[k], v2[k])) : "—"}
                </td>
              </tr>
            ))}
            {Object.entries(ratioLabels).map(([k]) => (
              <tr key={`r-${k}`}>
                <td>{ratioLabels[k]}</td>
                <td className="num">{fmt(m1[k], k !== "debt_to_equity")}</td>
                <td className="num">{fmt(m2[k], k !== "debt_to_equity")}</td>
                <td className={`num ${diff(m1[k], m2[k]) > 0 ? "tone-good" : diff(m1[k], m2[k]) < 0 ? "tone-danger" : ""}`}>
                  {diff(m1[k], m2[k]) !== null ? `${diff(m1[k], m2[k])}${k !== "debt_to_equity" ? "%" : ""}` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CatalogView({ language, companies, token, addToast, onNavigateToAnalysis }) {
  const lang = normalizeLanguage(language);
  const [status, setStatus] = useState(null);
  const [catalogComps, setCatalogComps] = useState([]);
  const [compsLoading, setCompsLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [ticker, setTicker] = useState("");
  const [index, setIndex] = useState(null);
  const [indexLoading, setIndexLoading] = useState(false);
  const [form, setForm] = useState("NSBU");
  const [year, setYear] = useState("");
  const [quarter, setQuarter] = useState(0);
  const [analysisType, setAnalysisType] = useState("financial");
  const [compareTicker, setCompareTicker] = useState("");
  const [compareYear, setCompareYear] = useState("");
  const [compareQuarter, setCompareQuarter] = useState(0);
  const [result, setResult] = useState(null);
  const [resultLoading, setResultLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const apiFetch = (path, options = {}) => {
    const stored = localStorage.getItem(STORAGE_KEY) || "";
    return fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(stored ? { Authorization: `Bearer ${stored}` } : {}), ...(options.headers || {}) } });
  };

  const loadStatus = async () => {
    try {
      const res = await apiFetch("/api/catalog/status");
      const data = await res.json();
      if (res.ok) setStatus(data);
    } catch { /* optional */ }
  };

  const loadCatalogComps = async () => {
    setCompsLoading(true);
    try {
      const res = await apiFetch("/api/catalog/companies");
      const data = await res.json();
      if (res.ok) setCatalogComps(data.companies || []);
    } catch { /* ignore */ }
    finally { setCompsLoading(false); }
  };

  const loadIndex = async (t) => {
    setIndexLoading(true);
    setIndex(null);
    setYear("");
    setQuarter(0);
    setResult(null);
    try {
      const res = await apiFetch(`/api/catalog/index/${t}`);
      const data = await res.json();
      if (res.ok) setIndex(data);
    } catch { /* ignore */ }
    finally { setIndexLoading(false); }
  };

  useEffect(() => { loadStatus(); loadCatalogComps(); }, []);
  useEffect(() => { if (ticker) loadIndex(ticker); else { setIndex(null); setYear(""); setQuarter(0); setResult(null); } }, [ticker]);
  useEffect(() => { setYear(""); setQuarter(0); setResult(null); }, [form, ticker]);

  const handleSync = async (specificTicker = null) => {
    if (!token) { addToast(lang === "ru" ? "Войдите для синхронизации" : "Sign in to sync", "error"); return; }
    setSyncing(true);
    try {
      const body = { force: true, ...(specificTicker ? { ticker: specificTicker } : {}) };
      const res = await apiFetch("/api/catalog/sync", { method: "POST", body: JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Sync failed");
      addToast(clg(lang, "syncDone"), "success");
      loadStatus();
      loadCatalogComps();
      if (ticker) loadIndex(ticker);
    } catch (err) { addToast(err.message, "error"); }
    finally { setSyncing(false); }
  };

  const handleRunAnalysis = async () => {
    if (!token) { addToast(lang === "ru" ? "Войдите для анализа" : "Sign in to analyze", "error"); return; }
    if (!ticker || !year) return;
    setResultLoading(true);
    setResult(null);
    try {
      const body = {
        ticker, year: parseInt(year), quarter, form, analysis_type: analysisType, language: lang,
        ...(compareTicker ? { compare_ticker: compareTicker } : {}),
        ...(compareYear ? { compare_year: parseInt(compareYear), compare_quarter: compareQuarter } : {}),
      };
      const res = await apiFetch("/api/catalog/analyze", { method: "POST", body: JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Analysis failed");
      setResult(data);
    } catch (err) { addToast(err.message, "error"); }
    finally { setResultLoading(false); }
  };

  // Derived availability helpers
  const avail = index?.availability || {};
  const formAvail = avail[form] || { annual: [], quarter: [] };
  const availYears = [...new Set([...(formAvail.annual || []), ...(formAvail.quarter || [])].map((r) => r.year))].filter(Boolean).sort((a, b) => b - a);
  const availQuarters = year ? (formAvail.quarter || []).filter((r) => r.year === parseInt(year)).map((r) => r.quarter).sort() : [];
  const isAnnualAvail = year ? (formAvail.annual || []).some((r) => r.year === parseInt(year)) : false;
  const isCurrentAvail = year ? (quarter === 0 ? isAnnualAvail : (formAvail.quarter || []).some((r) => r.year === parseInt(year) && r.quarter === quarter)) : false;
  const currentReport = year ? (quarter === 0
    ? (formAvail.annual || []).find((r) => r.year === parseInt(year))
    : (formAvail.quarter || []).find((r) => r.year === parseInt(year) && r.quarter === quarter)
  ) : null;

  const needsComparePeriod = ["quarter_compare", "annual_compare"].includes(analysisType);
  const needsCompareTicker = analysisType === "multi_company";

  const filteredComps = catalogComps.filter((c) => {
    const q = search.toLowerCase();
    return !q || c.ticker.toLowerCase().includes(q) || (c.company_name || "").toLowerCase().includes(q);
  });

  const analysisTypesObj = (TEXTS[lang] || TEXTS.ru).catalog.analysisTypes;
  const formsObj = (TEXTS[lang] || TEXTS.ru).catalog.forms;
  const periodsObj = (TEXTS[lang] || TEXTS.ru).catalog.periods;

  const renderResult = () => {
    if (!result) return null;
    const type = result.analysis_type;

    if (type === "ratio") return <CatalogRatioTable result={result} language={lang} />;
    if (type === "dynamics") return <CatalogDynamicsTable result={result} language={lang} />;
    if (type === "quarter_compare" || type === "annual_compare") return <CatalogCompareTable result={result} language={lang} />;

    // AI analysis: render sections + article_report
    const sections = result.sections || {};
    const articleSections = result.article_report?.sections || [];
    const hasArticle = articleSections.length > 0;
    const sectionEntries = Object.entries(sections).filter(([, v]) => v && typeof v === "string");
    return (
      <div className="catalog-result-body">
        {hasArticle ? articleSections.map((section, i) => (
          <div key={section.id || i} className="catalog-section">
            <div className="panel-label">{section.title || section.id}</div>
            <div className="catalog-section-text">
              <StructuredReportBlocks blocks={section.blocks || []} keyPrefix={`cat-${i}`} />
            </div>
          </div>
        )) : sectionEntries.map(([key, text]) => (
          <div key={key} className="catalog-section">
            <div className="panel-label">{key.replace(/_/g, " ")}</div>
            <div className="catalog-section-text">{text}</div>
          </div>
        ))}
        {!hasArticle && !sectionEntries.length && (
          <p className="muted">{lang === "ru" ? "Нет данных для отображения" : "No data to display"}</p>
        )}
      </div>
    );
  };

  return (
    <section className="catalog-layout">
      {/* Status bar */}
      <article className="panel catalog-header">
        <div className="catalog-header-copy">
          <div className="panel-label">{clg(lang, "title")}</div>
          <p className="muted">{clg(lang, "subtitle")}</p>
        </div>
        <div className="catalog-header-stats">
          {status ? (
            <>
              <span className="status-badge">{status.companies_synced} {clg(lang, "companies")} · {status.total_reports} {clg(lang, "totalReports")}</span>
              {status.last_sync && <span className="status-badge muted">{clg(lang, "lastSync")}: {formatMarketTimestamp(status.last_sync, lang)}</span>}
            </>
          ) : <span className="status-badge muted">{clg(lang, "loading")}</span>}
          <button className="ghost-btn" type="button" onClick={() => handleSync()} disabled={syncing}>
            {syncing ? clg(lang, "syncing") : clg(lang, "syncAll")}
          </button>
        </div>
      </article>

      <div className="catalog-body">
        {/* Sidebar: company list */}
        <aside className="catalog-sidebar">
          <input
            className="search-input"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={clg(lang, "searchPlaceholder")}
          />
          {compsLoading ? (
            <div className="catalog-list-loading">{clg(lang, "loading")}</div>
          ) : filteredComps.length === 0 ? (
            <div className="catalog-list-empty">
              {catalogComps.length === 0 ? clg(lang, "empty") : clg(lang, "noReports")}
            </div>
          ) : (
            <div className="catalog-company-list">
              {filteredComps.map((c) => (
                <button
                  key={c.ticker}
                  type="button"
                  className={`catalog-company-item ${ticker === c.ticker ? "active" : ""}`}
                  onClick={() => setTicker(c.ticker)}
                >
                  <div className="catalog-company-item-head">
                    <strong>{c.ticker}</strong>
                    <em>{c.total_count || 0} {clg(lang, "reports")}</em>
                  </div>
                  <span className="catalog-company-name">{c.company_name}</span>
                  {c.total_count > 0 && (
                    <div className="catalog-company-badges">
                      {c.nsbu_count > 0 && <span className="catalog-form-badge">{formsObj.NSBU} {c.nsbu_count}</span>}
                      {c.msfo_count > 0 && <span className="catalog-form-badge">{formsObj.MSFO} {c.msfo_count}</span>}
                      {c.audit_count > 0 && <span className="catalog-form-badge">{formsObj.Audition} {c.audit_count}</span>}
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}
        </aside>

        {/* Main area */}
        <main className="catalog-main">
          {!ticker ? (
            <div className="empty-state"><p className="empty-copy">{clg(lang, "selectCompany")}</p></div>
          ) : indexLoading ? (
            <div className="catalog-loading">{clg(lang, "loading")}</div>
          ) : (
            <>
              {/* Company header */}
              <div className="catalog-company-header">
                <div>
                  <h2>{index?.company_name || ticker}</h2>
                  <span className="status-badge muted">{ticker}</span>
                  {index?.last_synced_at && <span className="status-badge muted">{clg(lang, "lastSync")}: {formatMarketTimestamp(index.last_synced_at, lang)}</span>}
                </div>
                <button className="ghost-btn" type="button" onClick={() => handleSync(ticker)} disabled={syncing}>
                  {syncing ? clg(lang, "syncing") : clg(lang, "syncCompany")}
                </button>
              </div>

              {/* Form tabs */}
              <div className="catalog-form-tabs">
                {["NSBU", "MSFO", "Audition"].map((f) => (
                  <button key={f} type="button" className={`tab-btn ${form === f ? "active" : ""}`} onClick={() => setForm(f)}>
                    {formsObj[f]}
                  </button>
                ))}
              </div>

              {/* Year selector */}
              {availYears.length > 0 ? (
                <div className="catalog-year-row">
                  {availYears.map((y) => (
                    <button key={y} type="button"
                      className={`catalog-year-btn ${year === String(y) ? "active" : ""}`}
                      onClick={() => { setYear(String(y)); setQuarter(0); setResult(null); }}>
                      {y}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="muted catalog-no-form">{clg(lang, "notPublished")}</p>
              )}

              {/* Quarter selector for NSBU */}
              {year && form === "NSBU" && (
                <div className="catalog-quarter-row">
                  <button type="button"
                    className={`catalog-period-btn ${quarter === 0 ? "active" : ""} ${isAnnualAvail ? "" : "unavailable"}`}
                    onClick={() => { setQuarter(0); setResult(null); }}>
                    {periodsObj.annual}
                  </button>
                  {[1, 2, 3].map((q) => {
                    const qAvail = availQuarters.includes(q);
                    return (
                      <button key={q} type="button"
                        className={`catalog-period-btn ${quarter === q ? "active" : ""} ${qAvail ? "" : "unavailable"}`}
                        onClick={() => { if (qAvail) { setQuarter(q); setResult(null); } }}>
                        {periodsObj[`q${q}`]}
                      </button>
                    );
                  })}
                </div>
              )}

              {/* Availability indicator */}
              {year && (
                <div className={`catalog-avail ${isCurrentAvail ? "avail-yes" : "avail-no"}`}>
                  {isCurrentAvail ? (
                    <>
                      <span>{clg(lang, "available")}</span>
                      {currentReport?.has_pdf && (
                        <a className="ghost-btn catalog-pdf-btn" href={index ? undefined : "#"} target="_blank" rel="noreferrer"
                          onClick={async (e) => {
                            e.preventDefault();
                            const res = await apiFetch(`/api/catalog/index/${ticker}`);
                            const data = await res.json();
                            const a = (data.availability?.[form]?.[quarter === 0 ? "annual" : "quarter"] || [])
                              .find((r) => r.year === parseInt(year) && r.quarter === quarter);
                            if (a?.pdf_url) window.open(a.pdf_url, "_blank");
                          }}>
                          {clg(lang, "pdfReport")}
                        </a>
                      )}
                    </>
                  ) : (
                    <span>{clg(lang, "notPublished")}</span>
                  )}
                </div>
              )}

              {/* Analysis controls */}
              {year && isCurrentAvail && (
                <div className="catalog-analysis-controls">
                  <label className="catalog-field">
                    <span>{clg(lang, "analysisLabel")}</span>
                    <select value={analysisType} onChange={(e) => { setAnalysisType(e.target.value); setResult(null); }}>
                      {Object.entries(analysisTypesObj).map(([k, v]) => (
                        <option key={k} value={k}>{v}</option>
                      ))}
                    </select>
                  </label>

                  {needsCompareTicker && (
                    <label className="catalog-field">
                      <span>{clg(lang, "compareWith")}</span>
                      <select value={compareTicker} onChange={(e) => setCompareTicker(e.target.value)}>
                        <option value="">—</option>
                        {filteredComps.filter((c) => c.ticker !== ticker).map((c) => (
                          <option key={c.ticker} value={c.ticker}>{c.ticker} — {c.company_name}</option>
                        ))}
                      </select>
                    </label>
                  )}

                  {needsComparePeriod && (
                    <div className="catalog-compare-period">
                      <span>{clg(lang, "comparePeriod")}</span>
                      <div className="catalog-compare-period-row">
                        <select value={compareYear} onChange={(e) => setCompareYear(e.target.value)}>
                          <option value="">—</option>
                          {availYears.map((y) => <option key={y} value={y}>{y}</option>)}
                        </select>
                        {form === "NSBU" && (
                          <select value={compareQuarter} onChange={(e) => setCompareQuarter(parseInt(e.target.value))}>
                            <option value={0}>{periodsObj.annual}</option>
                            {[1, 2, 3].map((q) => <option key={q} value={q}>{periodsObj[`q${q}`]}</option>)}
                          </select>
                        )}
                      </div>
                    </div>
                  )}

                  <button className="primary-btn" type="button" onClick={handleRunAnalysis} disabled={resultLoading}>
                    {resultLoading ? clg(lang, "analysisLoading") : clg(lang, "runAnalysis")}
                  </button>
                </div>
              )}

              {/* Result */}
              {result && (
                <article className="panel catalog-result-panel">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{analysisTypesObj[result.analysis_type] || result.analysis_type}</div>
                      <h3>{result.company_name || ticker} · {result.year}{result.quarter > 0 ? ` Q${result.quarter}` : ""}</h3>
                    </div>
                  </div>
                  {renderResult()}
                </article>
              )}
            </>
          )}
        </main>
      </div>
    </section>
  );
}

function App() {
  const defaultReportYear = Math.max(2000, new Date().getFullYear() - 1);
  const reportYearOptions = Array.from({ length: 12 }, (_, index) => String(defaultReportYear + 1 - index));
  const [language, setLanguage] = useState(() => normalizeLanguage(localStorage.getItem(LANGUAGE_KEY) || "ru"));
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
    return "dark"; // Default to dark theme (Finam AI style)
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
  const [selectedSector, setSelectedSector] = useState(null);
  const [includeAllExcelReports, setIncludeAllExcelReports] = useState(false);
  const [forceRefresh, setForceRefresh] = useState(false);
  const [excelReportLimit, setExcelReportLimit] = useState("");
  const [reportAnalysisType, setReportAnalysisType] = useState("latest");
  const [reportQuarter, setReportQuarter] = useState("1");
  const [reportCurrentYear, setReportCurrentYear] = useState(String(defaultReportYear));
  const [reportPreviousYear, setReportPreviousYear] = useState(String(defaultReportYear - 1));
  const [reportForm, setReportForm] = useState("NAS");
  const [availablePeriods, setAvailablePeriods] = useState(null);
  const [periodsLoading, setPeriodsLoading] = useState(false);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisMessage, setAnalysisMessage] = useState("");
  const [compareCompanies, setCompareCompanies] = useState(["", "", ""]);
  const [compareResult, setCompareResult] = useState(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareMessage, setCompareMessage] = useState("");
  const [compareAiSummary, setCompareAiSummary] = useState(true);
  const [profileForm, setProfileForm] = useState({ full_name: "" });
  const [profileAvatarFile, setProfileAvatarFile] = useState(null);
  const [profileAvatarPreview, setProfileAvatarPreview] = useState("");
  const [showProfileEdit, setShowProfileEdit] = useState(false);
  const [profileAvatarCleared, setProfileAvatarCleared] = useState(false);
  const [historySearch, setHistorySearch] = useState("");
  const [historyMode, setHistoryMode] = useState("all");
  const [marketRows, setMarketRows] = useState([]);
  const [marketMeta, setMarketMeta] = useState({ updated_at: null, count: 0 });
  const [marketTrades, setMarketTrades] = useState(null);
  const [marketType, setMarketType] = useState("stock");
  const [marketQuery, setMarketQuery] = useState("");
  const [marketLoading, setMarketLoading] = useState(false);
  const [marketMessage, setMarketMessage] = useState("");
  const [toasts, setToasts] = useState([]);

  // Dynamic year/quarter options: fallback to static list until per-company periods are fetched
  const annualYearOptions = availablePeriods?.annual_years?.map(String) || reportYearOptions;
  const quarterlyYearOptions = availablePeriods
    ? [...new Set(availablePeriods.quarterly.map((q) => q.year))].sort((a, b) => b - a).map(String)
    : reportYearOptions;
  const availableQuartersForYear = availablePeriods
    ? availablePeriods.quarterly.filter((q) => String(q.year) === reportCurrentYear).map((q) => q.quarter).sort((a, b) => a - b)
    : [1, 2, 3];

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
      themeMeta.setAttribute("content", theme === "dark" ? "#0a0f1a" : "#f8fafc");
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
      setCompareResult(null);
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

  useEffect(() => {
    if (activeView !== "market") return;
    loadMarketStocks().catch((error) => {
      addToast(error.message, "error");
    });
    loadMarketTrades();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeView, marketType, language]);

  // Fetch available periods whenever the analysis company changes
  useEffect(() => {
    const query = analysisCompany.trim();
    if (!query) {
      setAvailablePeriods(null);
      return;
    }
    let cancelled = false;
    setPeriodsLoading(true);
    setAvailablePeriods(null);
    fetch(`/api/periods?company=${encodeURIComponent(query)}`)
      .then((res) => res.json())
      .then((data) => {
        if (cancelled || !data.ok || !data.periods) return;
        setAvailablePeriods(data.periods);
      })
      .catch(() => {}) // fail silently — static fallback remains active
      .finally(() => { if (!cancelled) setPeriodsLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisCompany]);

  // Auto-select the latest available year/quarter when periods arrive for a new company
  useEffect(() => {
    if (!availablePeriods) return;
    if (reportAnalysisType === "quarterly" && availablePeriods.latest_quarterly) {
      const { year, quarter } = availablePeriods.latest_quarterly;
      setReportCurrentYear(String(year));
      setReportQuarter(String(quarter));
      setReportPreviousYear(String(year - 1));
    } else if (reportAnalysisType !== "latest" && availablePeriods.latest_annual_year) {
      const yr = availablePeriods.latest_annual_year;
      setReportCurrentYear(String(yr));
      setReportPreviousYear(String(yr - 1));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availablePeriods]);

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

  const loadMarketStocks = async () => {
    setMarketLoading(true);
    setMarketMessage(mt(language, "loading"));
    try {
      const params = new URLSearchParams();
      if (marketType !== "all") params.set("type", marketType);
      const res = await apiFetch(`/api/market/stocks${params.toString() ? `?${params}` : ""}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not load stock prices");
      setMarketRows(Array.isArray(data.stocks) ? data.stocks : []);
      setMarketMeta({ updated_at: data.updated_at || null, count: data.count || 0, type: data.type || marketType });
      setMarketMessage(mt(language, "ready"));
    } catch (error) {
      setMarketMessage(error.message);
      throw error;
    } finally {
      setMarketLoading(false);
    }
  };

  const loadMarketTrades = async () => {
    try {
      const res = await apiFetch("/api/market/trades");
      const data = await res.json();
      if (res.ok) setMarketTrades(data);
    } catch {
      // trades are optional — don't block the page
    }
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
    setCompareResult(null);
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
    if (reportAnalysisType !== "latest" && reportCurrentYear === reportPreviousYear) {
      addToast(language === "en" ? "Choose two different years" : language === "uz" ? "Ikki xil yilni tanlang" : "Выберите два разных года", "error");
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
          include_raw: false,
          force_refresh: forceRefresh,
          include_all_excel_reports: includeAllExcelReports,
          report_analysis_type: reportAnalysisType,
          report_form: reportForm,
          ...(reportAnalysisType !== "latest" ? {
            report_current_year: Number(reportCurrentYear),
            report_previous_year: Number(reportPreviousYear),
          } : {}),
          ...(reportAnalysisType === "quarterly" ? { report_quarter: Number(reportQuarter) } : {}),
          ...(includeAllExcelReports && excelReportLimit.trim() ? { excel_report_limit: Number(excelReportLimit) } : {}),
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

  const updateCompareCompany = (index, value) => {
    setCompareCompanies((current) => current.map((item, itemIndex) => (itemIndex === index ? value : item)));
  };

  const addQuickCompareCompany = (ticker) => {
    setCompareCompanies((current) => {
      const normalized = String(ticker || "").trim();
      if (!normalized) return current;
      if (current.some((item) => item.trim().toLowerCase() === normalized.toLowerCase())) return current;
      const next = [...current];
      const emptyIndex = next.findIndex((item) => !item.trim());
      if (emptyIndex >= 0) {
        next[emptyIndex] = normalized;
      } else {
        next[2] = normalized;
      }
      return next;
    });
  };

  const handleCompareSubmit = async (event) => {
    event.preventDefault();
    if (!token) {
      addToast(ct(language, "authRequired"), "error");
      setActiveView("auth");
      return;
    }

    const cleaned = [];
    const seen = new Set();
    for (const item of compareCompanies) {
      const value = String(item || "").trim();
      const key = value.toLowerCase();
      if (value && !seen.has(key)) {
        cleaned.push(value);
        seen.add(key);
      }
    }

    if (cleaned.length < 2) {
      addToast(ct(language, "minRequired"), "error");
      return;
    }

    setCompareLoading(true);
    setCompareMessage(ct(language, "loading"));
    try {
      const res = await apiFetch("/api/compare", {
        method: "POST",
        body: JSON.stringify({
          companies: cleaned.slice(0, 3),
          language,
          include_market_context: false,
          include_ai_summary: compareAiSummary,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not complete the comparison");
      setCompareResult(data);
      setCompareMessage(ct(language, "ready"));
      addToast(`${ct(language, "ready")}: ${cleaned.join(" / ")}`, "success");
      setActiveView("compare");
      await loadProfile();
    } catch (error) {
      addToast(error.message, "error");
      setCompareMessage(error.message);
      setCompareResult(null);
    } finally {
      setCompareLoading(false);
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

  const availableSectors = [...new Set(companies.map((c) => c.sector).filter(Boolean))];

  const filteredCompanies = companies
    .filter((item) => {
      const q = analysisCompany.trim().toLowerCase();
      const matchSearch = !q || item.ticker.toLowerCase().includes(q) || item.company_name.toLowerCase().includes(q);
      const matchSector = !selectedSector || item.sector === selectedSector;
      return matchSearch && matchSector;
    })
    .slice(0, 48);

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
    push(t(language, "metrics.total_score"), total.score ?? "—", buildScoreExplanation(total, metrics, language), scoreTone(total.score));
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
    return cards;
  })();

  const profileStats = profile?.stats || {};
  const profileUser = profile?.user || user;
  const profileAvatar = profileUser?.avatar_data_url;
  const profileCreated = profileUser?.created_at;
  const activitySeries = buildActivitySeries(profile?.recent_analyses || [], language);
  const activitySparkline = activitySeries.days.map((day) => day.count);
  const cachedSparkline = activitySeries.days.map((day) => day.cached);
  const scoreSparkline = activitySeries.days.map((day) => day.avgScore).filter((value) => value !== null);
  const companySparkline = companies.length ? activitySeries.days.map(() => companies.length) : [];
  const dashboardCards = [
    {
      label: t(language, "dashboard.cards.companies"),
      value: companies.length || 0,
      sub: t(language, "analysis.availableTitle"),
      tone: "good",
      sparkline: companySparkline,
    },
    {
      label: t(language, "dashboard.cards.analyses"),
      value: profileStats.total_analyses ?? 0,
      sub: profile ? vt(language, "dashboardPeriod") : t(language, "profile.empty"),
      tone: "warning",
      sparkline: activitySparkline,
    },
    {
      label: t(language, "dashboard.cards.avgScore"),
      value: profile ? profileStats.avg_score ?? "—" : "—",
      sub: profile ? t(language, "profile.stats.avgScore") : t(language, "analysis.resultEmpty"),
      tone: "good",
      sparkline: scoreSparkline,
    },
    {
      label: t(language, "dashboard.cards.cached"),
      value: profileStats.cached_analyses ?? 0,
      sub: profile ? t(language, "analysis.resultCacheHit") : t(language, "dashboard.trend"),
      tone: "neutral",
      sparkline: cachedSparkline,
    },
  ];
  const disclosure = disclosureText(language);
  const comparison = compareResult?.comparison || null;
  const compareCharts = Array.isArray(comparison?.charts) ? comparison.charts : [];
  const compareTables = comparison?.tables || {};
  const compareSummary = comparison?.summary || {};
  const compareAi = comparison?.comparative_ai_summary || {};
  const compareErrors = Array.isArray(comparison?.errors) ? comparison.errors : [];
  const comparePrimaryChart = compareCharts.find((chart) => chart.id === "normalized_radar") || compareCharts[0];
  const compareSecondaryCharts = compareCharts.filter((chart) => chart !== comparePrimaryChart);
  const compareQuickCompanies = companies.slice(0, 18);

  const navItems = token
    ? ["main", "market", "catalog", "profile", "analysis", "compare"]
    : ["main", "market", "catalog", "auth", "analysis", "compare"];

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
            <img src={logoIcon} alt="UZ Stock Analyzer" className="brand-icon" />
            <div className="brand-copy">
              <div className="brand-title">{t(language, "brand")}</div>
              <div className="brand-subtitle">{t(language, "subtitle")}</div>
            </div>
          </div>

          <nav className="topbar-nav">
            {navItems.map((key) => (
              <button key={key} className={`topbar-nav-btn ${activeView === key ? "active" : ""}`} type="button" onClick={() => setActiveView(key)}>
                {key === "market" ? mt(language, "nav") : key === "compare" ? ct(language, "nav") : t(language, `nav.${key}`)}
              </button>
            ))}
          </nav>

          <div className="topbar-meta">
            <div className="topbar-controls">
              <label className="topbar-language">
                <select
                  id="languageSelect"
                  className="select-field"
                  value={language}
                  onChange={(event) => setLanguage(normalizeLanguage(event.target.value))}
                >
                  <option value="ru">RU</option>
                  <option value="en">EN</option>
                  <option value="uz">UZ</option>
                </select>
              </label>

              <button className="theme-toggle" type="button" onClick={toggleTheme} title={theme === "dark" ? t(language, "theme.light") : t(language, "theme.dark")}>
                <strong>{theme === "dark" ? "☀" : "☾"}</strong>
              </button>
            </div>
          </div>
        </header>

        <main className="content">
          {activeView === "main" && (
            <>
              {/* Hero Section */}
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
                  <div className="hero-badges">
                    {TEXTS[language].hero.badges.map((badge) => (
                      <span key={badge}>{badge}</span>
                    ))}
                  </div>
                </div>
                <div className="hero-image">
                  <img src={heroImage} alt="Stock Analysis Dashboard" />
                </div>
              </section>

              {/* Features Section */}
              <section className="landing-features">
                <div className="section-header">
                  <h2>{t(language, "main.title")}</h2>
                  <p>{t(language, "main.copy")}</p>
                </div>
                <div className="features-grid">
                  {TEXTS[language].main.features.map((feature) => (
                    <article className="feature-card" key={feature.title}>
                      <div className="feature-icon">{Icons[feature.icon]}</div>
                      <h3>{feature.title}</h3>
                      <p>{feature.copy}</p>
                    </article>
                  ))}
                </div>
              </section>

              {/* How It Works Section */}
              <section className="landing-how-it-works">
                <div className="section-header">
                  <h2>{TEXTS[language].main.howItWorks.title}</h2>
                </div>
                <div className="steps-grid">
                  {TEXTS[language].main.howItWorks.steps.map((step) => (
                    <article className="step-card" key={step.num}>
                      <div className="step-number">{step.num}</div>
                      <h3>{step.title}</h3>
                      <p>{step.copy}</p>
                    </article>
                  ))}
                </div>
              </section>

              {/* Stats Section */}
              <section className="landing-stats">
                <div className="section-header">
                  <h2>{TEXTS[language].main.stats.title}</h2>
                </div>
                <div className="stats-grid">
                  {TEXTS[language].main.stats.items.map((stat) => (
                    <article className="stat-card" key={stat.label}>
                      <div className="stat-value">{stat.value}</div>
                      <div className="stat-label">{stat.label}</div>
                    </article>
                  ))}
                </div>
              </section>

              {/* CTA Section */}
              <section className="landing-cta">
                <div className="cta-content">
                  <h2>{TEXTS[language].main.cta.title}</h2>
                  <p>{TEXTS[language].main.cta.copy}</p>
                  <button className="primary-btn cta-btn" type="button" onClick={() => setActiveView("analysis")}>
                    {TEXTS[language].main.cta.button}
                  </button>
                </div>
              </section>
            </>
          )}

          {activeView === "catalog" && (
            <CatalogView
              language={language}
              companies={companies}
              token={token}
              addToast={addToast}
              onNavigateToAnalysis={(t) => { setAnalysisCompany(t); setActiveView("analysis"); }}
            />
          )}

          {activeView === "market" && (
            <MarketView
              rows={marketRows}
              meta={marketMeta}
              trades={marketTrades}
              loading={marketLoading}
              message={marketMessage}
              query={marketQuery}
              onQueryChange={setMarketQuery}
              type={marketType}
              onTypeChange={setMarketType}
              onRefresh={() => { loadMarketStocks().catch((error) => addToast(error.message, "error")); loadMarketTrades(); }}
              onAnalyze={(ticker) => {
                setAnalysisCompany(ticker || "");
                setActiveView("analysis");
              }}
              language={language}
              companies={companies}
            />
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
            <>
              {/* Profile Header Card */}
              {profileUser && (
                <section className="profile-header-card">
                  <div className="profile-header-bg" />
                  <div className="profile-header-content">
                    <div className="profile-header-avatar" style={profileAvatarPreview || profileAvatar ? {} : { background: `linear-gradient(135deg, hsl(${hashToHue(profileUser.email)} 70% 60%), hsl(${(hashToHue(profileUser.email) + 45) % 360} 70% 50%))` }}>
                      {profileAvatarPreview ? <img src={profileAvatarPreview} alt="" /> : profileAvatar ? <img src={profileAvatar} alt="" /> : getProfileInitials(profileUser)}
                    </div>
                    <div className="profile-header-info">
                      <h1>{profileUser.full_name || profileUser.email.split('@')[0]}</h1>
                      <p className="profile-header-email">{profileUser.email}</p>
                      <div className="profile-header-meta">
                        <span className="profile-header-badge">{t(language, "auth.signedIn")}</span>
                      </div>
                    </div>
                    <div className="profile-header-actions">
                      <button className="primary-btn" type="button" onClick={() => setActiveView("analysis")}>
                        {t(language, "profile.analyze")}
                      </button>
                      <button className="ghost-btn" type="button" onClick={() => setShowProfileEdit(!showProfileEdit)}>
                        {showProfileEdit ? (language === "en" ? "Cancel" : language === "uz" ? "Bekor qilish" : "Отмена") : (language === "en" ? "Edit Profile" : language === "uz" ? "Tahrirlash" : "Редактировать")}
                      </button>
                    </div>
                  </div>
                  {/* Inline Edit Form */}
                  {showProfileEdit && (
                    <div className="profile-edit-inline">
                      <form className="profile-settings-form" onSubmit={handleProfileSave}>
                        <div className="profile-form-group">
                          <label>{t(language, "profile.name")}</label>
                          <input
                            type="text"
                            value={profileForm.full_name}
                            onChange={(event) => setProfileForm({ full_name: event.target.value })}
                            placeholder={t(language, "profile.name")}
                          />
                        </div>
                        <div className="profile-form-group">
                          <label>{t(language, "profile.avatar")}</label>
                          <div className="profile-avatar-upload">
                            <input type="file" accept="image/*" onChange={onAvatarChange} id="avatar-input" />
                            <label htmlFor="avatar-input" className="profile-avatar-btn">
                              {language === "en" ? "Choose file" : language === "uz" ? "Fayl tanlash" : "Выбрать файл"}
                            </label>
                            {(profileAvatarPreview || profileAvatar) && (
                              <button type="button" className="profile-avatar-remove" onClick={removeAvatar}>
                                {t(language, "profile.clearAvatar")}
                              </button>
                            )}
                          </div>
                        </div>
                        <div className="profile-form-actions">
                          <button className="primary-btn" type="submit">
                            {t(language, "profile.save")}
                          </button>
                        </div>
                      </form>
                    </div>
                  )}
                </section>
              )}

              {/* Stats Overview */}
              <section className="profile-stats-section">
                <div className="profile-stats-grid">
                  {dashboardCards.map((card) => (
                    <DashboardMetricCard key={card.label} {...card} language={language} />
                  ))}
                </div>
              </section>

              {/* Activity Chart */}
              <section className="profile-activity-section">
                <article className="panel">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{t(language, "dashboard.activityTitle")}</div>
                      <h2>{t(language, "dashboard.activityTitle")}</h2>
                    </div>
                    <span className="profile-activity-total">
                      {activitySeries?.total ? `${activitySeries.total} ${language === "uz" ? "tahlil" : language === "en" ? "analyses" : "анализов"}` : ""}
                    </span>
                  </div>
                  <ActivityChart series={activitySeries} language={language} />
                </article>
              </section>

              {/* Favorites */}
              <section className="profile-favorites-section">
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
              </section>

              {/* History */}
              <section className="profile-history-section">
                <article className="panel history-panel">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{t(language, "profile.historyTitle")}</div>
                      <h2>{t(language, "profile.historyTitle")}</h2>
                    </div>
                  </div>
                  <div className="panel-toolbar history-filters">
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
                  {recentAnalyses.length ? (
                    <div className="history-list">
                      {recentAnalyses.map((item) => (
                        <article className="history-item" key={`${item.created_at}-${item.company_input}`}>
                          <div className="history-main">
                            <div>
                              <div className="history-title">{item.company_name || item.company_input || t(language, "profile.empty")}</div>
                              <div className="history-sub">
                                {item.ticker || "—"} · {item.from_cache ? t(language, "analysis.resultCacheHit") : t(language, "analysis.resultFresh")}
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
            </>
          )}

          {activeView === "analysis" && (
            <section className="analysis-layout">
              <article className="panel analysis-panel analysis-hero">
                <div className="analysis-hero-header">
                  <div className="analysis-hero-icon">
                    {Icons.chart}
                  </div>
                  <div className="analysis-hero-text">
                    <h1>{t(language, "analysis.title")}</h1>
                    <p>{language === "en" ? "Get comprehensive financial analysis powered by AI" : language === "uz" ? "AI yordamida moliyaviy tahlil oling" : "Получите комплексный финансовый анализ на основе ИИ"}</p>
                  </div>
                  {analysisLoading && <span className="status-badge analysis-loading-badge">{t(language, "analysis.loadingChart")}</span>}
                </div>

                <form className="analysis-form-modern" onSubmit={handleAnalysisSubmit}>
                  <div className="analysis-input-group">
                    <label>{t(language, "analysis.company")}</label>
                    <div className="analysis-input-wrapper">
                      <span className="analysis-input-icon">{Icons.target}</span>
                      <input
                        list="companiesList"
                        value={analysisCompany}
                        onChange={(event) => setAnalysisCompany(event.target.value)}
                        placeholder={language === "en" ? "Enter company name or ticker..." : language === "uz" ? "Kompaniya nomi yoki ticker kiriting..." : "Введите название компании или тикер..."}
                        autoComplete="off"
                        required
                      />
                    </div>
                    <datalist id="companiesList">
                      {companies.map((company) => (
                        <option key={company.ticker} value={company.ticker}>
                          {company.company_name}
                        </option>
                      ))}
                    </datalist>
                  </div>

                  <div className="analysis-period-picker">
                    <div className="analysis-input-group">
                      <label>{t(language, "analysis.reportType")}</label>
                      <select value={reportAnalysisType} onChange={(event) => setReportAnalysisType(event.target.value)}>
                        <option value="latest">{t(language, "analysis.fullAnalysis")}</option>
                        <option value="quarterly">{t(language, "analysis.quarterlyReport")}</option>
                        <option value="annual">{t(language, "analysis.annualReport")}</option>
                      </select>
                    </div>
                    {reportAnalysisType !== "latest" ? (
                      <div className="analysis-input-group">
                        <label>{t(language, "analysis.reportingForm")}</label>
                        <select
                          value={reportForm}
                          onChange={(event) => {
                            setReportForm(event.target.value);
                            if (event.target.value === "IFRS" && reportAnalysisType === "quarterly") {
                              setReportAnalysisType("annual");
                            }
                          }}
                        >
                          <option value="NAS">{t(language, "analysis.reportFormNAS")}</option>
                          <option value="IFRS">{t(language, "analysis.reportFormIFRS")}</option>
                        </select>
                        <span className="analysis-form-hint">{t(language, "analysis.reportFormHint")}</span>
                      </div>
                    ) : (
                      <div className="analysis-input-group analysis-source-note">
                        <span className="analysis-source-badge">
                          {language === "en" ? "Data source" : language === "uz" ? "Ma'lumot manbai" : "Источник данных"}:
                          {" "}<strong>{language === "en" ? "NAS structured reports" : language === "uz" ? "MHBS tizimli hisobotlar" : "НСБУ структурированная отчётность"}</strong>
                        </span>
                        <span className="analysis-form-hint">{t(language, "analysis.reportFormLatestNote")}</span>
                      </div>
                    )}
                    {reportAnalysisType === "quarterly" ? (
                      <div className="analysis-input-group">
                        <label>{t(language, "analysis.quarter")}</label>
                        <select value={reportQuarter} onChange={(event) => setReportQuarter(event.target.value)} disabled={periodsLoading}>
                          {availableQuartersForYear.length > 0
                            ? availableQuartersForYear.map((q) => (
                                <option key={q} value={String(q)}>
                                  {language === "en" ? `Q${q}` : language === "uz" ? `${q}-chorak` : `${q} квартал`}
                                </option>
                              ))
                            : [1, 2, 3].map((q) => (
                                <option key={q} value={String(q)}>
                                  {language === "en" ? `Q${q}` : language === "uz" ? `${q}-chorak` : `${q} квартал`}
                                </option>
                              ))}
                        </select>
                        {periodsLoading && <span className="analysis-periods-loading">{language === "en" ? "Loading periods…" : language === "uz" ? "Davrlar yuklanmoqda…" : "Загрузка периодов…"}</span>}
                      </div>
                    ) : null}
                    {reportAnalysisType !== "latest" ? (
                      <>
                        <div className="analysis-input-group">
                          <label>{t(language, "analysis.currentYear")}</label>
                          <select value={reportCurrentYear} onChange={(event) => setReportCurrentYear(event.target.value)} disabled={periodsLoading}>
                            {(reportAnalysisType === "quarterly" ? quarterlyYearOptions : annualYearOptions).map((year) => (
                              <option key={`current-${year}`} value={year}>{year}</option>
                            ))}
                          </select>
                          {periodsLoading && <span className="analysis-periods-loading">{language === "en" ? "Loading periods…" : language === "uz" ? "Davrlar yuklanmoqda…" : "Загрузка периодов…"}</span>}
                        </div>
                        <div className="analysis-input-group">
                          <label>{t(language, "analysis.previousYear")}</label>
                          <select value={reportPreviousYear} onChange={(event) => setReportPreviousYear(event.target.value)} disabled={periodsLoading}>
                            {annualYearOptions.map((year) => (
                              <option key={`previous-${year}`} value={year}>{year}</option>
                            ))}
                          </select>
                        </div>
                      </>
                    ) : null}
                  </div>

                  <div className="analysis-options-row">
                    <div className="analysis-input-group">
                      <label>{t(language, "analysis.mode")}</label>
                      <select defaultValue="full">
                        <option value="quick">{t(language, "analysis.quick")}</option>
                        <option value="full">{t(language, "analysis.full")}</option>
                      </select>
                    </div>
                    <label className="analysis-checkbox">
                      <input type="checkbox" checked={forceRefresh} onChange={(event) => setForceRefresh(event.target.checked)} />
                      <span>{t(language, "analysis.forceRefresh")}</span>
                    </label>
                  </div>

                  <div className={`analysis-deep-excel ${includeAllExcelReports ? "is-active" : ""}`}>
                    <label className="analysis-checkbox analysis-deep-checkbox">
                      <input type="checkbox" checked={includeAllExcelReports} onChange={(event) => setIncludeAllExcelReports(event.target.checked)} />
                      <span>{language === "en" ? "Deep Excel analysis: use all available XLSX reports" : language === "uz" ? "Deep Excel tahlil: barcha mavjud XLSX hisobotlardan foydalanish" : "Глубокий Excel-анализ: использовать все доступные XLSX-отчеты"}</span>
                    </label>
                    {includeAllExcelReports ? (
                      <div className="analysis-input-group analysis-excel-limit">
                        <label>{language === "en" ? "Optional XLSX cap" : language === "uz" ? "Ixtiyoriy XLSX chegarasi" : "Ограничение XLSX, необязательно"}</label>
                        <input
                          type="number"
                          min="1"
                          max="100"
                          value={excelReportLimit}
                          onChange={(event) => setExcelReportLimit(event.target.value)}
                          placeholder={language === "en" ? "Leave empty = all found" : language === "uz" ? "Bo'sh qoldiring = hammasi" : "Пусто = все найденные"}
                        />
                      </div>
                    ) : null}
                    <p>
                      {language === "en"
                        ? "Leave the limit empty to parse every found XLSX report. This mode is slower on first run, then snapshots are cached."
                        : language === "uz"
                          ? "Barcha topilgan XLSX hisobotlarni olish uchun limitni bo'sh qoldiring. Bu rejim birinchi ishga tushishda sekinroq, keyin snapshot keshdan olinadi."
                          : "Оставьте лимит пустым, чтобы разобрать все найденные XLSX-отчёты. Этот режим медленнее при первом запуске, после парсинга snapshot берется из кэша."}
                    </p>
                  </div>

                  <button className="primary-btn analysis-submit-btn" type="submit" disabled={analysisLoading}>
                    {Icons.zap}
                    <span>{analysisLoading ? (language === "en" ? "Analyzing..." : language === "uz" ? "Tahlil qilinmoqda..." : "Анализируем...") : t(language, "analysis.submit")}</span>
                  </button>
                </form>

                <div className="analysis-companies-section">
                  <div className="analysis-companies-header">
                    <h3>{t(language, "analysis.availableTitle")}</h3>
                    <span className="analysis-companies-count">{filteredCompanies.length} {language === "en" ? "companies" : language === "uz" ? "kompaniya" : "компаний"}</span>
                  </div>
                  <div className="sector-filter">
                    <button
                      className={`sector-chip${!selectedSector ? " active" : ""}`}
                      type="button"
                      onClick={() => setSelectedSector(null)}
                    >
                      {sectorLabel(language, "all")}
                    </button>
                    {availableSectors.map((sector) => (
                      <button
                        key={sector}
                        className={`sector-chip${selectedSector === sector ? " active" : ""}`}
                        type="button"
                        onClick={() => setSelectedSector(selectedSector === sector ? null : sector)}
                      >
                        {sectorLabel(language, sector)}
                      </button>
                    ))}
                  </div>
                  <div className="analysis-companies-grid">
                    {filteredCompanies.map((company) => (
                      <button
                        key={company.ticker}
                        className="analysis-company-chip"
                        type="button"
                        onClick={() => setAnalysisCompany(company.ticker)}
                      >
                        <CompanyLogo logo={company.logo} name={company.company_name} ticker={company.ticker} />
                        <span className="chip-ticker">{company.ticker}</span>
                        <span className="chip-name">{company.company_name}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </article>

              {(analysisResult || analysisLoading) && (
                <article className={`panel result-hero ${analysisLoading ? "is-loading" : ""}`}>
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{t(language, "analysis.resultTitle")}</div>
                      <h2>{analysisLabel}</h2>
                    </div>
                    {analysisResult ? <span className="status-badge muted">{resultCacheText}</span> : null}
                  </div>

                  {analysisLoading ? (
                    <ResultSkeleton language={language} />
                  ) : (
                  <>
                    <HeroKpiStrip
                      analysisResult={analysisResult}
                      chartData={chartData}
                      language={language}
                    />
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

                    <BankMetricsPanel analysisResult={analysisResult} language={language} />

                    <FinancialVisuals result={analysisResult} language={language} score={resultScore} />

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
              )}
            </section>
          )}

          {activeView === "analysis" && (analysisResult || analysisLoading) && (
            <section className="results-grid">
              <HeroVerdictBlock analysisResult={analysisResult} language={language} />
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

              {analysisResult?.sections && <ReportArticleView analysisResult={analysisResult} language={language} />}

              <article className="panel sections-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "analysis.sectionsTitle")}</div>
                    <h2>{t(language, "analysis.sectionsTitle")}</h2>
                  </div>
                </div>
                {analysisResult?.sections ? (() => {
                  const { primary, supplementary } = splitSections(analysisResult.sections);
                  return (
                    <div className="sections-wrap">
                      {primary.map(([key, value], index) => (
                        <SectionCard
                          key={key}
                          title={getSectionTitle(language, key)}
                          body={value || t(language, "analysis.noData")}
                          index={index}
                          open={index === 0}
                          language={language}
                        />
                      ))}
                      {supplementary.length > 0 && (
                        <details className="section-card section-card--supplementary fade-in">
                          <summary>
                            <span className="section-number">{SUPPLEMENTARY_LABELS[language] || SUPPLEMENTARY_LABELS.ru}</span>
                            <span className="section-title-text">
                              {language === "en"
                                ? "Additional analysis blocks"
                                : language === "uz"
                                ? "Qo'shimcha tahlil bloklari"
                                : "Дополнительные блоки анализа"}
                            </span>
                          </summary>
                          <div className="section-content">
                            <div className="sections-wrap sections-wrap--nested">
                              {supplementary.map(([key, value], idx) => (
                                <SectionCard
                                  key={key}
                                  title={getSectionTitle(language, key)}
                                  body={value || t(language, "analysis.noData")}
                                  index={primary.length + idx}
                                  language={language}
                                />
                              ))}
                            </div>
                          </div>
                        </details>
                      )}
                    </div>
                  );
                })() : (
                  <div className="empty-state">
                    <p className="empty-copy">{analysisLoading ? t(language, "analysis.loadingSections") : t(language, "analysis.resultEmpty")}</p>
                  </div>
                )}
              </article>
            </section>
          )}

          {activeView === "compare" && (
            <section className="compare-layout">
              <article className="panel analysis-panel analysis-hero">
                <div className="analysis-hero-header">
                  <div className="analysis-hero-icon">
                    {Icons.users}
                  </div>
                  <div className="analysis-hero-text">
                    <h1>{ct(language, "title")}</h1>
                    <p>{ct(language, "subtitle")}</p>
                  </div>
                  {compareLoading && <span className="status-badge analysis-loading-badge">{ct(language, "loading")}</span>}
                </div>

                <form className="analysis-form-modern" onSubmit={handleCompareSubmit}>
                  <div className="compare-inputs-grid">
                    {compareCompanies.map((value, index) => (
                      <div className="analysis-input-group" key={index}>
                        <label>
                          {ct(language, `company${index + 1}`)}
                          {index === 2 && <span className="optional-tag">{ct(language, "optional")}</span>}
                        </label>
                        <div className="analysis-input-wrapper">
                          <span className="analysis-input-icon">{Icons.target}</span>
                          <input
                            list="compareCompaniesList"
                            value={value}
                            onChange={(event) => updateCompareCompany(index, event.target.value)}
                            placeholder={ct(language, "placeholder")}
                            autoComplete="off"
                            required={index < 2}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                  <datalist id="compareCompaniesList">
                    {companies.map((company) => (
                      <option key={company.ticker} value={company.ticker}>
                        {company.company_name}
                      </option>
                    ))}
                  </datalist>

                  <div className="analysis-options-row">
                    <label className="analysis-checkbox">
                      <input type="checkbox" checked={compareAiSummary} onChange={(event) => setCompareAiSummary(event.target.checked)} />
                      <span>{ct(language, "includeAi")}</span>
                    </label>
                  </div>

                  <button className="primary-btn analysis-submit-btn" type="submit" disabled={compareLoading}>
                    {Icons.zap}
                    <span>{compareLoading ? ct(language, "loading") : ct(language, "submit")}</span>
                  </button>
                </form>

                <div className="analysis-companies-section">
                  <div className="analysis-companies-header">
                    <h3>{ct(language, "quick")}</h3>
                    <span className="analysis-companies-count">{companies.length} {language === "en" ? "companies" : language === "uz" ? "kompaniya" : "компаний"}</span>
                  </div>
                  <div className="analysis-companies-grid">
                    {compareQuickCompanies.map((company) => (
                      <button
                        key={company.ticker}
                        className="analysis-company-chip"
                        type="button"
                        onClick={() => addQuickCompareCompany(company.ticker)}
                      >
                        <span className="chip-ticker">{company.ticker}</span>
                        <span className="chip-name">{company.company_name}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </article>

              {(compareResult || compareLoading) && (
                <article className={`panel compare-overview-panel ${compareLoading ? "is-loading" : ""}`}>
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{ct(language, "overview")}</div>
                      <h2>{compareResult ? ct(language, "ready") : ct(language, "empty")}</h2>
                    </div>
                    {compareMessage ? <span className="status-badge muted">{compareMessage}</span> : null}
                  </div>

                  {compareLoading ? (
                    <div className="compare-loading-grid">
                      <div />
                      <div />
                      <div />
                    </div>
                  ) : comparison ? (
                    <>
                      <div className="compare-summary-card">
                        <p>{compareSummary.short || ct(language, "noData")}</p>
                        <span>{ct(language, "normalizedNote")}</span>
                      </div>
                      <CompareLeaderCards leaders={comparison.leaders} language={language} />
                      <div className="compare-ranking-grid">
                        <CompareRanking title={ct(language, "ranking")} rows={comparison.ranking} scoreKey="score" language={language} />
                        <CompareRanking title={ct(language, "normalizedRanking")} rows={comparison.normalized_ranking} scoreKey="composite_score" language={language} />
                      </div>
                    </>
                  ) : (
                    <div className="empty-state">
                      <p className="empty-copy">{ct(language, "empty")}</p>
                    </div>
                  )}
                </article>
              )}
            </section>
          )}

          {activeView === "compare" && (compareResult || compareLoading) && (
            <section className="compare-results-grid">
              <article className="panel compare-chart-main">
                {comparePrimaryChart ? <CompareChartCard chart={comparePrimaryChart} language={language} /> : (
                  <div className="empty-state">
                    <p className="empty-copy">{compareLoading ? ct(language, "loading") : ct(language, "noData")}</p>
                  </div>
                )}
              </article>

              <article className="panel compare-ai-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{ct(language, "aiSummary")}</div>
                    <h2>{ct(language, "aiSummary")}</h2>
                  </div>
                  {compareAi?.model ? <span className="status-badge muted">{compareAi.model}</span> : null}
                </div>
                <CompareSummaryText summary={compareAi} language={language} />
                {compareSummary.methodology ? (
                  <div className="compare-methodology">
                    <strong>{ct(language, "methodology")}</strong>
                    <p>{compareSummary.methodology}</p>
                  </div>
                ) : null}
                {compareErrors.length ? (
                  <div className="compare-errors">
                    <strong>{ct(language, "errors")}</strong>
                    {compareErrors.map((error) => (
                      <p key={`${error.company}-${error.error}`}>{error.company}: {error.error}</p>
                    ))}
                  </div>
                ) : null}
              </article>

              {compareSecondaryCharts.length ? (
                <article className="panel compare-charts-panel">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{ct(language, "charts")}</div>
                      <h2>{ct(language, "charts")}</h2>
                    </div>
                  </div>
                  <div className="compare-chart-grid">
                    {compareSecondaryCharts.map((chart) => (
                      <CompareChartCard key={chart.id || chart.title} chart={chart} language={language} />
                    ))}
                  </div>
                </article>
              ) : null}

              {Object.keys(compareTables).length ? (
                <article className="panel compare-tables-panel">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{ct(language, "tables")}</div>
                      <h2>{ct(language, "tables")}</h2>
                    </div>
                  </div>
                  <div className="compare-tables-grid">
                    {Object.entries(compareTables).map(([key, table]) => (
                      <CompareTable key={key} table={table} title={compareTableTitle(language, key)} language={language} />
                    ))}
                  </div>
                </article>
              ) : null}
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

const HERO_LABELS = {
  ru: { revenue: "Выручка", profit: "Чистая прибыль", roe: "Доходность капитала (ROE)", noData: "Нет данных" },
  en: { revenue: "Revenue", profit: "Net income", roe: "Return on equity (ROE)", noData: "No data" },
  uz: { revenue: "Daromad", profit: "Sof foyda", roe: "Kapital rentabelligi (ROE)", noData: "Maʼlumot yoʻq" },
};

function HeroKpiTile({ label, value, year, change, tone = "neutral", hint }) {
  const arrow = change == null ? null : change > 0 ? "▲" : change < 0 ? "▼" : "→";
  const yoyText = change == null ? null : `${arrow} ${formatSignedPercent(change)}`;
  return (
    <article className={`hero-kpi-tile tone-${tone}`}>
      <span className="hero-kpi-label">{label}</span>
      <strong className="hero-kpi-value">{value}</strong>
      <div className="hero-kpi-foot">
        {yoyText && <span className={`hero-kpi-yoy tone-${tone}`}>{yoyText}</span>}
        {year && <span className="hero-kpi-year">{year}</span>}
        {hint && !year && <span className="hero-kpi-year">{hint}</span>}
      </div>
    </article>
  );
}

const BANK_METRIC_LABELS = {
  ru: {
    title: "Банковские коэффициенты",
    car: "Достаточность капитала",
    nim: "Чистая процентная маржа",
    ldr: "Кредиты / депозиты",
    cir: "Cost-to-Income",
  },
  en: {
    title: "Banking ratios",
    car: "Capital adequacy",
    nim: "Net interest margin",
    ldr: "Loan-to-deposit",
    cir: "Cost-to-Income",
  },
  uz: {
    title: "Bank koeffitsientlari",
    car: "Kapital yetarliligi",
    nim: "Sof foiz marjasi",
    ldr: "Kreditlar / depozitlar",
    cir: "Cost-to-Income",
  },
};

function BankMetricCell({ label, value, tone = "neutral", note, language }) {
  return (
    <article className={`bank-metric-cell tone-${tone}`}>
      <span className="bank-metric-label">{label}</span>
      <strong className="bank-metric-value">{value ?? "—"}</strong>
      {note && <p className="bank-metric-note">{note}</p>}
    </article>
  );
}

function BankMetricsPanel({ analysisResult, language }) {
  const bank = analysisResult?.ifrs_snapshot?.bank;
  if (!bank || !bank.is_bank) return null;
  const lbl = BANK_METRIC_LABELS[language] || BANK_METRIC_LABELS.ru;
  const tones = bank.tones || {};
  const notes = bank.notes || {};
  const fmt = (v) => v == null ? "—" : `${formatRatio(v, 1, language)}%`;
  return (
    <article className="panel bank-metrics-panel">
      <div className="panel-head">
        <div>
          <div className="panel-label">{lbl.title}</div>
          <h3>{lbl.title}</h3>
        </div>
      </div>
      <div className="bank-metrics-grid">
        <BankMetricCell label={lbl.car} value={fmt(bank.car_simple_pct)} tone={tones.car_simple_pct} note={notes.car_simple_pct} language={language} />
        <BankMetricCell label={lbl.nim} value={fmt(bank.nim_pct)} tone={tones.nim_pct} note={notes.nim_pct} language={language} />
        <BankMetricCell label={lbl.ldr} value={fmt(bank.ldr_pct)} tone={tones.ldr_pct} note={notes.ldr_pct} language={language} />
        <BankMetricCell label={lbl.cir} value={fmt(bank.cir_pct)} tone={tones.cir_pct} note={notes.cir_pct} language={language} />
      </div>
    </article>
  );
}

function HeroKpiStrip({ analysisResult, chartData, language }) {
  const lbl = HERO_LABELS[language] || HERO_LABELS.ru;
  const ifrs = analysisResult?.ifrs_snapshot || {};
  const quality = ifrs.quality || {};
  const latest = chartData?.latest;
  const noData = lbl.noData;

  // Revenue
  const revenue = latest && Number.isFinite(latest.revenue) ? latest.revenue : null;
  const revenueChange = chartData?.revenueChange;
  const revenueTone = revenueChange == null ? "neutral" : revenueChange >= 10 ? "good" : revenueChange >= 0 ? "warning" : "danger";

  // Net income
  const profit = latest && Number.isFinite(latest.profit) ? latest.profit : null;
  const profitChange = chartData?.profitChange;
  const profitTone = profitChange == null ? "neutral" : profitChange >= 10 ? "good" : profitChange >= 0 ? "warning" : "danger";

  // ROE
  const roe = Number(quality.roe_pct);
  const haveRoe = Number.isFinite(roe);
  const roeTone = !haveRoe ? "neutral" : roe >= 15 ? "good" : roe >= 5 ? "warning" : "danger";

  return (
    <div className="hero-kpi-strip">
      <HeroKpiTile
        label={lbl.revenue}
        value={revenue != null ? formatCompactNumber(revenue, language) : noData}
        year={latest?.year ?? null}
        change={revenueChange}
        tone={revenueTone}
      />
      <HeroKpiTile
        label={lbl.profit}
        value={profit != null ? formatCompactNumber(profit, language) : noData}
        year={latest?.year ?? null}
        change={profitChange}
        tone={profitTone}
      />
      <HeroKpiTile
        label={lbl.roe}
        value={haveRoe ? `${formatRatio(roe, 1, language)}%` : noData}
        year={null}
        change={null}
        tone={roeTone}
      />
    </div>
  );
}

function MetricRing({ label, percent, display, tone = "neutral" }) {
  const value = clampPercent(percent);
  const radius = 38;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - ((value ?? 0) / 100) * circumference;

  return (
    <div className={`metric-ring tone-${tone}`}>
      <svg viewBox="0 0 104 104" role="img" aria-label={label}>
        <circle className="metric-ring-track" cx="52" cy="52" r={radius} />
        <circle
          className="metric-ring-progress"
          cx="52"
          cy="52"
          r={radius}
          style={{ strokeDasharray: circumference, strokeDashoffset: dashOffset }}
        />
      </svg>
      <div className="metric-ring-center">
        <strong>{display}</strong>
      </div>
      <span>{label}</span>
    </div>
  );
}

function FinancialVisuals({ result, language, score }) {
  if (!result) return null;

  const snapshot = result?.ifrs_snapshot || {};
  const metrics = result?.metrics || {};
  const annualSeries = Array.isArray(snapshot?.series?.annual) ? snapshot.series.annual : [];
  const latestAnnual = annualSeries.at(-1) || {};
  const income = snapshot?.income_statement || {};
  const balance = snapshot?.balance_sheet || {};
  const pickNumber = (...values) => {
    for (const value of values) {
      const number = safeNumber(value);
      if (number !== null) return number;
    }
    return null;
  };
  const makeRow = (key, value, tone = "neutral") => ({
    key,
    label: vt(language, key),
    value,
    tone,
  });

  const revenue = pickNumber(latestAnnual.revenue, income.revenue, income.sales);
  const netIncome = pickNumber(latestAnnual.net_income, income.net_income, income.profit);
  const assets = pickNumber(latestAnnual.assets, latestAnnual.total_assets, balance.assets, balance.total_assets);
  const equity = pickNumber(latestAnnual.equity, latestAnnual.total_equity, balance.equity, balance.total_equity);
  const debt = pickNumber(latestAnnual.debt, latestAnnual.total_debt, latestAnnual.total_liabilities, balance.debt, balance.total_debt, balance.total_liabilities);
  const rows = [
    makeRow("revenue", revenue, "good"),
    makeRow("netIncome", netIncome, netIncome === null ? "neutral" : netIncome >= 0 ? "good" : "danger"),
    makeRow("assets", assets, "neutral"),
    makeRow("equity", equity, "good"),
    makeRow("debt", debt, "warning"),
  ].filter((row) => row.value !== null);
  const maxAbs = Math.max(1, ...rows.map((row) => Math.abs(row.value)));

  const scoreValue = safeNumber(score);
  const scoreValuePercent = scorePercent(scoreValue);
  const roePct = pickNumber(result?.ifrs_snapshot?.quality?.roe_pct, latestAnnual?.roe_pct);
  const netMarginPct = pickNumber(result?.ifrs_snapshot?.income_statement?.net_margin_pct, latestAnnual?.net_margin_pct);
  const debtToEquity = pickNumber(balance?.debt_to_equity, latestAnnual?.debt_to_equity);
  const rings = [
    {
      label: vt(language, "totalScore"),
      percent: scoreValuePercent,
      display: scoreValue === null ? "—" : Math.round(scoreValue),
      tone: scoreTone(scoreValue),
    },
    {
      label: language === "en" ? "ROE" : language === "uz" ? "ROE" : "ROE",
      percent: roePct === null ? null : Math.min(100, Math.max(0, roePct / 30 * 100)),
      display: roePct === null ? "—" : `${formatRatio(roePct, 1, language)}%`,
      tone: roePct === null ? "neutral" : roePct >= 15 ? "good" : roePct >= 5 ? "warning" : "danger",
    },
    {
      label: language === "en" ? "Net margin" : language === "uz" ? "Sof marja" : "Чистая маржа",
      percent: netMarginPct === null ? null : Math.min(100, Math.max(0, netMarginPct / 25 * 100)),
      display: netMarginPct === null ? "—" : `${formatRatio(netMarginPct, 1, language)}%`,
      tone: netMarginPct === null ? "neutral" : netMarginPct >= 10 ? "good" : netMarginPct >= 3 ? "warning" : "danger",
    },
    {
      label: vt(language, "leverage"),
      percent: debtToEquity === null ? null : 100 / (1 + Math.max(0, debtToEquity)),
      display: debtToEquity === null ? "—" : `D/E ${formatRatio(debtToEquity, 2, language)}`,
      tone: debtToEquity === null ? "neutral" : debtToEquity <= 1 ? "good" : debtToEquity <= 2 ? "warning" : "danger",
    },
  ];

  return (
    <div className="financial-visual-grid">
      <article className="visual-panel financial-bars-panel">
        <div className="visual-panel-head">
          <div>
            <div className="panel-label">{vt(language, "latestPeriod")}</div>
            <h3>{vt(language, "financialStructure")}</h3>
          </div>
          <span>{vt(language, "financialStructureCopy")}</span>
        </div>
        {rows.length ? (
          <div className="financial-bars">
            {rows.map((row) => (
              <div key={row.key} className={`financial-bar-row tone-${row.tone}`}>
                <div className="financial-bar-label">
                  <span>{row.label}</span>
                  <strong>{formatCompactNumber(row.value, language)}</strong>
                </div>
                <div className="financial-bar-track">
                  <span className={row.value < 0 ? "is-negative" : ""} style={{ width: `${Math.max(4, (Math.abs(row.value) / maxAbs) * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="visual-empty">{vt(language, "noVisualData")}</div>
        )}
      </article>

      <article className="visual-panel metric-rings-panel">
        <div className="visual-panel-head">
          <div>
            <div className="panel-label">{vt(language, "latestPeriod")}</div>
            <h3>{vt(language, "scoreAndRisk")}</h3>
          </div>
          <span>{vt(language, "scoreAndRiskCopy")}</span>
        </div>
        <div className="metric-rings-grid">
          {rings.map((ring) => (
            <MetricRing key={ring.label} {...ring} />
          ))}
        </div>
      </article>
    </div>
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

  const { width, height, filtered, areaPath, revenuePath, profitPath, debtPath, yTicks, x, y, revenueChange, profitChange, debtChange, latest } = chartData;

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
        <path d={debtPath} className="chart-line chart-line-debt" />
        {filtered.map((point, index) => (
          <g key={`${point.year}-${index}`}>
            <circle cx={x(index)} cy={y(point.revenue ?? 0)} r="4.8" className="chart-dot chart-dot-revenue" />
            <circle cx={x(index)} cy={y(point.profit ?? 0)} r="4.8" className="chart-dot chart-dot-profit" />
            <circle cx={x(index)} cy={y(point.debt ?? 0)} r="4.8" className="chart-dot chart-dot-debt" />
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
        <div className="legend-chip">
          <span className="legend-swatch legend-swatch-debt" />
          <span className="legend-label">{t(language, "analysis.signalDebt")}</span>
          <strong className="legend-value">{latest.debt != null ? formatCompactNumber(latest.debt, language) : "—"}</strong>
          <span className={`legend-delta ${debtChange === null ? "" : debtChange >= 0 ? "is-down" : "is-up"}`}>
            {debtChange === null ? "—" : formatSignedPercent(debtChange)}
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
          const hasActivity = day.count > 0;
          return (
            <g key={day.key}>
              <rect x={x} y={padding.top} width={barWidth} height={innerHeight} rx="16" className={`activity-bar-track ${hasActivity ? "has-activity" : ""}`} />
              {hasActivity && <rect x={x} y={y} width={barWidth} height={barHeight} rx="16" className="activity-bar" />}
              <text x={x + barWidth / 2} y={height - 16} textAnchor="middle" className={`activity-axis-label ${hasActivity ? "has-activity" : ""}`}>
                {day.shortLabel}
              </text>
              <text x={x + barWidth / 2} y={Math.max(y - 10, 16)} textAnchor="middle" className={`activity-value ${hasActivity ? "has-activity" : ""}`}>
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
