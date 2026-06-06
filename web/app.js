const API_BASE = window.location.origin;
const STORAGE_KEY = "uz_stock_analyzer_token";
const LANGUAGE_KEY = "uz_stock_analyzer_language";

const state = {
  token: localStorage.getItem(STORAGE_KEY) || "",
  language: localStorage.getItem(LANGUAGE_KEY) || "ru",
  user: null,
  profile: null,
  companies: [],
  lastResult: null,
  oauthMessage: "",
  profileAvatarCleared: false,
};

let loadingSkeletonTimer = null;

const els = {
  navButtons: Array.from(document.querySelectorAll(".nav-btn")),
  views: Array.from(document.querySelectorAll(".page-view")),
  authStatus: document.getElementById("authStatus"),
  apiState: document.getElementById("apiState"),
  languageSelect: document.getElementById("languageSelect"),
  loginForm: document.getElementById("loginForm"),
  registerForm: document.getElementById("registerForm"),
  authMessage: document.getElementById("authMessage"),
  googleLoginBtn: document.getElementById("googleLoginBtn"),
  toastStack: document.getElementById("toastStack"),
  userCard: document.getElementById("userCard"),
  userName: document.getElementById("userName"),
  userEmail: document.getElementById("userEmail"),
  logoutBtn: document.getElementById("logoutBtn"),
  profileStatus: document.getElementById("profileStatus"),
  profileAvatar: document.getElementById("profileAvatar"),
  profileName: document.getElementById("profileName"),
  profileEmail: document.getElementById("profileEmail"),
  profileMemberSince: document.getElementById("profileMemberSince"),
  profileStats: document.getElementById("profileStats"),
  profileRecent: document.getElementById("profileRecent"),
  profileFavorites: document.getElementById("profileFavorites"),
  profileHistorySearch: document.getElementById("profileHistorySearch"),
  profileHistoryMode: document.getElementById("profileHistoryMode"),
  profileHistorySummary: document.getElementById("profileHistorySummary"),
  profileEditForm: document.getElementById("profileEditForm"),
  profileFullName: document.getElementById("profileFullName"),
  profileAvatarInput: document.getElementById("profileAvatarInput"),
  profileEditHint: document.getElementById("profileEditHint"),
  profileSaveBtn: document.getElementById("profileSaveBtn"),
  profileClearAvatarBtn: document.getElementById("profileClearAvatarBtn"),
  profileAnalyzeBtn: document.getElementById("profileAnalyzeBtn"),
  profileRefreshBtn: document.getElementById("profileRefreshBtn"),
  analysisForm: document.getElementById("analysisForm"),
  companyInput: document.getElementById("companyInput"),
  companiesList: document.getElementById("companiesList"),
  quickCompanies: document.getElementById("quickCompanies"),
  companyCount: document.getElementById("companyCount"),
  includeHtml: document.getElementById("includeHtml"),
  resultCompany: document.getElementById("resultCompany"),
  resultCache: document.getElementById("resultCache"),
  resultHero: document.getElementById("resultHero"),
  scoreValue: document.getElementById("scoreValue"),
  gradeValue: document.getElementById("gradeValue"),
  verdictValue: document.getElementById("verdictValue"),
  summaryValue: document.getElementById("summaryValue"),
  chartTitle: document.getElementById("chartTitle"),
  chartMeta: document.getElementById("chartMeta"),
  analysisChart: document.getElementById("analysisChart"),
  revenueSignal: document.getElementById("revenueSignal"),
  revenueSignalSub: document.getElementById("revenueSignalSub"),
  marginSignal: document.getElementById("marginSignal"),
  marginSignalSub: document.getElementById("marginSignalSub"),
  riskSignal: document.getElementById("riskSignal"),
  riskSignalSub: document.getElementById("riskSignalSub"),
  resultFavoriteBtn: document.getElementById("resultFavoriteBtn"),
  metricsGrid: document.getElementById("metricsGrid"),
  sectionsWrap: document.getElementById("sectionsWrap"),
};

const UI_TEXT = {
  ru: {
    pageTitle: "UZ Stock Analyzer",
    languageLabel: "Язык",
    languageOptions: { ru: "Русский", en: "English", uz: "O'zbek" },
    hero: {
      eyebrow: "Аналитика публичных компаний Узбекистана",
      copy:
        "Веб-сервис для быстрого и структурированного анализа компаний. Сервис позволяет зарегистрироваться, войти в аккаунт, выбрать компанию и получить итог с оценкой, ключевыми метриками и развернутым отчетом.",
    },
    nav: { main: "Главная", about: "О проекте", auth: "Авторизация", profile: "Профиль", analysis: "Анализ" },
    main: {
      panelLabel: "Главная",
      title: "Что делает сервис",
      copy:
        "Минимальный веб-интерфейс для анализа компаний Узбекистана. Пользователь может создать учетную запись, войти в систему, выбрать компанию и получить структурированный результат с итоговой оценкой, вердиктом и набором ключевых блоков.",
      features: [
        { title: "1. Регистрация", copy: "Создание учетной записи по email и паролю." },
        { title: "2. Выбор компании", copy: "Поиск по тикеру или выбор из списка доступных компаний." },
        { title: "3. Получение анализа", copy: "Итоговая оценка, вердикт, метрики и разделы отчета." },
      ],
      sideTitle: "Зачем это нужно",
      notes: [
        { title: "Быстрая первичная оценка", copy: "Сервис помогает быстро понять, стоит ли углубляться в исследование компании." },
        { title: "Контроль доступа", copy: "Запуск анализа доступен только авторизованным пользователям." },
        { title: "Понятный результат", copy: "Интерфейс показывает итоговую оценку, ключевые метрики и структурированный отчет." },
      ],
    },
    about: {
      panelLabel: "О проекте",
      title: "Описание решения",
      leftNotes: [
        { title: "Источник данных", copy: "Бэкенд собирает и структурирует данные по компании перед формированием ответа анализа." },
        { title: "Бэкенд", copy: "API, авторизация и сессии на Railway Postgres уже настроены и работают как единый слой." },
        { title: "Фронтенд", copy: "Интерфейс построен как компактная аналитическая панель с регистрацией, входом и результатами анализа." },
      ],
      rightTitle: "Что получает пользователь",
      rightCards: [
        { title: "Оценка", copy: "Единый показатель для первичной ориентации." },
        { title: "Вердикт", copy: "Краткое, профессиональное заключение по компании." },
        { title: "Метрики", copy: "Ключевые показатели в карточках для быстрого чтения." },
        { title: "Отчет", copy: "Развернутые секции для детального изучения." },
      ],
    },
    auth: {
      panelLabel: "Аккаунт",
      title: "Авторизация",
      statusSignedOut: "Не выполнен вход",
      statusSignedIn: "Вход выполнен",
      loginTab: "Вход",
      registerTab: "Регистрация",
      login: {
        email: "Email",
        emailPlaceholder: "you@example.com",
        password: "Пароль",
        passwordPlaceholder: "Введите пароль",
        submit: "Войти",
      },
      register: {
        fullName: "Имя и фамилия",
        fullNamePlaceholder: "Ваше имя",
        email: "Email",
        emailPlaceholder: "you@example.com",
        password: "Пароль",
        passwordPlaceholder: "Не менее 8 символов",
        submit: "Создать аккаунт",
      },
      oauthLabel: "Или продолжить через",
      signedInAs: "Вошли как",
      emailLabel: "Email",
      logout: "Выйти",
      messages: {
        loggingIn: "Выполняется вход...",
        registering: "Создание аккаунта...",
        loginSuccess: "Вход выполнен, {name}",
        registerSuccess: "Аккаунт создан: {email}",
        signOut: "Выход выполнен",
        oauthSuccess: "Вход через {provider} выполнен",
        oauthReady: "OAuth-вход выполнен",
        authRequired: "Сначала выполните вход",
        signedIn: "В системе: {email}",
      },
    },
    profile: {
      panelLabel: "Профиль",
      title: "Личный кабинет",
      statusNotLoaded: "Профиль не загружен",
      statusLoaded: "Профиль обновлен",
      unavailable: "Профиль недоступен",
      emailHint: "Войдите в учетную запись, чтобы увидеть персональные данные.",
      memberSince: "Дата регистрации будет отображаться здесь.",
      memberSinceWithDate: "В системе с {date}",
      analyzeBtn: "Перейти к анализу",
      refreshBtn: "Обновить профиль",
      editTitle: "Редактирование профиля",
      editSub: "Имя и аватар",
      nameLabel: "Отображаемое имя",
      namePlaceholder: "Ваше имя",
      avatarLabel: "Аватар",
      saveBtn: "Сохранить изменения",
      clearAvatarBtn: "Удалить аватар",
      editHint: "Можно обновить имя, загрузить аватар или очистить текущее изображение.",
      savedHint: "Профиль обновлен.",
      clearHint: "После сохранения текущий аватар будет удалён.",
      readImageError: "Не удалось прочитать изображение",
      statsLabel: "Статистика",
      statsTitle: "Показатели активности",
      statsEmpty: "Статистика появится после первого анализа.",
      favoritesLabel: "Избранное",
      favoritesTitle: "Сохраненные компании",
      favoritesEmpty: "Добавляйте компании в избранное из анализа или из истории.",
      historyLabel: "История",
      historyTitle: "Последние анализы",
      historySearchPlaceholder: "Поиск по компании или тикеру",
      historyAll: "Все анализы",
      historyFavorites: "Только избранное",
      historySummaryPrefix: "Показано",
      historyEmpty: "После первого анализа здесь появится история действий.",
      historyFilteredEmpty: "По выбранному фильтру ничего не найдено.",
      historyFromCache: "из кэша",
      historyFresh: "свежий расчет",
      historyModelPrefix: "модель",
      historyFavoriteAdd: "В избранное",
      historyFavoriteRemove: "Убрать из избранного",
      historyAnalysisDone: "Анализ выполнен",
      favoritesRemove: "Убрать",
      noTitle: "Без названия",
      stats: {
        totalAnalyses: "Всего анализов",
        totalAnalysesSub: "Все выполненные запросы",
        analyses7d: "За 7 дней",
        analyses7dSub: "Активность за неделю",
        analyses30d: "За 30 дней",
        analyses30dSub: "Активность за месяц",
        analyzedCompanies: "Компаний в истории",
        analyzedCompaniesSub: "Уникальные тикеры",
        avgScore: "Средний скор",
        avgScoreSub: "Средний итог по анализам",
        bestScore: "Лучшая оценка",
        bestScoreSub: "Максимальный скор",
        topCompany: "Чаще всего смотрит",
        topCompanySub: "{count} анализов",
        topCompanySubEmpty: "Пока нет данных",
        cachedAnalyses: "Кэшированных",
        cachedAnalysesSub: "Сколько ответов пришло из кэша",
        lastAnalysis: "Последний анализ",
        lastAnalysisSub: "Время последнего запроса",
      },
    },
    analysis: {
      panelLabel: "Анализ",
      title: "Анализ компании",
      apiReady: "API готов",
      apiLoading: "Получение данных...",
      apiError: "API недоступен",
      companyLabel: "Компания",
      companyPlaceholder: "Начните вводить название или тикер",
      modeLabel: "Режим",
      modeQuick: "Быстрый",
      modeFull: "Полный",
      includeHtml: "Возвращать HTML-отчет",
      submit: "Анализировать",
      availableTitle: "Доступные компании",
      companyCount: "{count} компаний",
      resultLabel: "Результат",
      resultEmpty: "Анализ еще не выполнялся",
      resultCacheWaiting: "Ожидание",
      resultCacheHit: "Из кэша",
      resultFresh: "Свежий расчет",
      resultRunning: "Анализ выполняется...",
      scoreCaption: "Оценка / 100",
      verdictPlaceholder: "Выполните анализ, чтобы увидеть итоговое заключение.",
      favoriteAdd: "Добавить в избранное",
      favoriteRemove: "Убрать из избранного",
      metricsLabel: "Метрики",
      metricsTitle: "Ключевые показатели",
      metricsEmpty: "Метрики появятся после первого запроса.",
      sectionsLabel: "Отчет",
      sectionsTitle: "Разделы отчета",
      sectionsEmpty: "После анализа здесь появятся разделы отчета.",
      loadingTitle: "Анализ: {company}",
      loadingRunning: "Анализ выполняется...",
      loadingCache: "Загрузка",
      loadingVerdict: "Анализ выполняется. Пожалуйста, подождите.",
      loadingMetrics: "Загрузка",
      completed: "Анализ завершен: {company}",
    },
    toasts: { error: "Ошибка", success: "Готово", info: "Инфо" },
    sections: {
      "СКОРИНГ": "Скоринг",
      "ДОСЬЕ": "Досье",
      "ЧТО_С_ДЕНЬГАМИ": "Что с деньгами",
      "ТРЕНД": "Тренд",
      "ФИБОНАЧЧИ": "Фибоначчи",
      "ОЦЕНКА_ЦЕНЫ": "Оценка цены",
      "КАТАЛИЗАТОРЫ": "Катализаторы",
      "СИЛЬНЫЕ_СТОРОНЫ": "Сильные стороны",
      "СЛАБЫЕ_СТОРОНЫ": "Слабые стороны",
      "ВОЗМОЖНОСТИ": "Возможности",
      "УГРОЗЫ": "Угрозы",
      "ПРОГНОЗ": "Прогноз",
      "ВЕРДИКТ": "Вердикт",
      "СОВЕТЫ": "Советы",
      "ИТОГ": "Итог",
      "ЗЕЛЕНЫЕ_ФЛАГИ": "Зеленые флаги",
      "КРАСНЫЕ_ФЛАГИ": "Красные флаги",
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
      noData: "Метрики появятся после первого запроса.",
    },
  },
};

UI_TEXT.en = {
  pageTitle: "UZ Stock Analyzer",
  languageLabel: "Language",
  languageOptions: { ru: "Russian", en: "English", uz: "Uzbek" },
  hero: {
    eyebrow: "Analytics for public companies in Uzbekistan",
    copy:
      "A web service for fast and structured company analysis. Create an account, sign in, choose a company, and receive a score, key metrics, and a structured report.",
  },
  nav: { main: "Main", about: "About", auth: "Sign in", profile: "Profile", analysis: "Analysis" },
  main: {
    panelLabel: "Main",
    title: "What the service does",
    copy:
      "A compact web interface for analyzing companies in Uzbekistan. The user can create an account, sign in, choose a company, and receive a structured result with a score, verdict, and key blocks.",
    features: [
      { title: "1. Registration", copy: "Create an account with email and password." },
      { title: "2. Company selection", copy: "Search by ticker or choose from the available list." },
      { title: "3. Analysis", copy: "Final score, verdict, metrics, and report sections." },
    ],
    sideTitle: "Why it matters",
    notes: [
      { title: "Fast first pass", copy: "The service helps you quickly decide whether to dig deeper into a company." },
      { title: "Access control", copy: "Analysis is available only to authenticated users." },
      { title: "Readable output", copy: "The interface shows the final score, key metrics, and a structured report." },
    ],
  },
  about: {
    panelLabel: "About",
    title: "Solution overview",
    leftNotes: [
      { title: "Data source", copy: "The backend collects and structures company data before the analysis is generated." },
      { title: "Backend", copy: "API, auth, and sessions on Railway Postgres are configured and operate as one layer." },
      { title: "Frontend", copy: "The interface is a compact analytics dashboard with sign in, account creation, and analysis results." },
    ],
    rightTitle: "What the user gets",
    rightCards: [
      { title: "Score", copy: "A single indicator for a quick starting point." },
      { title: "Verdict", copy: "A short professional conclusion about the company." },
      { title: "Metrics", copy: "Key indicators in cards for quick reading." },
      { title: "Report", copy: "Detailed sections for deeper review." },
    ],
  },
  auth: {
    panelLabel: "Account",
    title: "Sign in",
    statusSignedOut: "Not signed in",
    statusSignedIn: "Signed in",
    loginTab: "Sign in",
    registerTab: "Register",
    login: { email: "Email", emailPlaceholder: "you@example.com", password: "Password", passwordPlaceholder: "Enter your password", submit: "Sign in" },
    register: { fullName: "Full name", fullNamePlaceholder: "Your name", email: "Email", emailPlaceholder: "you@example.com", password: "Password", passwordPlaceholder: "At least 8 characters", submit: "Create account" },
    oauthLabel: "Or continue with",
    signedInAs: "Signed in as",
    emailLabel: "Email",
    logout: "Log out",
    messages: {
      loggingIn: "Signing in...",
      registering: "Creating account...",
      loginSuccess: "Signed in, {name}",
      registerSuccess: "Account created: {email}",
      signOut: "Signed out",
      oauthSuccess: "Signed in with {provider}",
      oauthReady: "OAuth sign in complete",
      authRequired: "Please sign in first",
      signedIn: "In the system: {email}",
    },
  },
  profile: {
    panelLabel: "Profile",
    title: "Dashboard",
    statusNotLoaded: "Profile not loaded",
    statusLoaded: "Profile updated",
    unavailable: "Profile unavailable",
    emailHint: "Sign in to view personal data.",
    memberSince: "Registration date will appear here.",
    memberSinceWithDate: "In the system since {date}",
    analyzeBtn: "Go to analysis",
    refreshBtn: "Refresh profile",
    editTitle: "Edit profile",
    editSub: "Name and avatar",
    nameLabel: "Display name",
    namePlaceholder: "Your name",
    avatarLabel: "Avatar",
    saveBtn: "Save changes",
    clearAvatarBtn: "Remove avatar",
    editHint: "You can update the name, upload an avatar, or clear the current image.",
    savedHint: "Profile updated.",
    clearHint: "The current avatar will be removed after saving.",
    readImageError: "Could not read the image",
    statsLabel: "Statistics",
    statsTitle: "Activity metrics",
    statsEmpty: "Statistics will appear after the first analysis.",
    favoritesLabel: "Favorites",
    favoritesTitle: "Saved companies",
    favoritesEmpty: "Add companies to favorites from analysis or history.",
    historyLabel: "History",
    historyTitle: "Recent analyses",
    historySearchPlaceholder: "Search by company or ticker",
    historyAll: "All analyses",
    historyFavorites: "Favorites only",
    historySummaryPrefix: "Shown",
    historyEmpty: "After the first analysis, your activity history will appear here.",
    historyFilteredEmpty: "Nothing matched the selected filter.",
    historyFromCache: "from cache",
    historyFresh: "fresh result",
    historyModelPrefix: "model",
    historyFavoriteAdd: "Add to favorites",
    historyFavoriteRemove: "Remove from favorites",
    historyAnalysisDone: "Analysis completed",
    favoritesRemove: "Remove",
    noTitle: "Untitled",
    stats: {
      totalAnalyses: "Total analyses",
      totalAnalysesSub: "All completed requests",
      analyses7d: "Last 7 days",
      analyses7dSub: "Weekly activity",
      analyses30d: "Last 30 days",
      analyses30dSub: "Monthly activity",
      analyzedCompanies: "Companies in history",
      analyzedCompaniesSub: "Unique tickers",
      avgScore: "Average score",
      avgScoreSub: "Average result across analyses",
      bestScore: "Best score",
      bestScoreSub: "Highest recorded score",
      topCompany: "Most viewed",
      topCompanySub: "{count} analyses",
      topCompanySubEmpty: "No data yet",
      cachedAnalyses: "Cached",
      cachedAnalysesSub: "How many responses came from cache",
      lastAnalysis: "Last analysis",
      lastAnalysisSub: "Time of the last request",
    },
  },
  analysis: {
    panelLabel: "Analysis",
    title: "Company analysis",
    apiReady: "API ready",
    apiLoading: "Loading data...",
    apiError: "API unavailable",
    companyLabel: "Company",
    companyPlaceholder: "Start typing the company name or ticker",
    modeLabel: "Mode",
    modeQuick: "Quick",
    modeFull: "Full",
    includeHtml: "Return HTML report",
    submit: "Analyze",
    availableTitle: "Available companies",
    companyCount: "{count} companies",
    resultLabel: "Result",
    resultEmpty: "Analysis has not been run yet",
    resultCacheWaiting: "Waiting",
    resultCacheHit: "From cache",
    resultFresh: "Fresh result",
    resultRunning: "Analysis running...",
    scoreCaption: "Score / 100",
    verdictPlaceholder: "Run an analysis to see the final verdict.",
    favoriteAdd: "Add to favorites",
    favoriteRemove: "Remove from favorites",
    metricsLabel: "Metrics",
    metricsTitle: "Key metrics",
    metricsEmpty: "Metrics will appear after the first request.",
    sectionsLabel: "Report",
    sectionsTitle: "Report sections",
    sectionsEmpty: "After analysis, report sections will appear here.",
    loadingTitle: "Analysis: {company}",
    loadingRunning: "Analysis running...",
    loadingCache: "Loading",
    loadingVerdict: "The analysis is running. Please wait.",
    loadingMetrics: "Loading",
    completed: "Analysis completed: {company}",
  },
  toasts: { error: "Error", success: "Done", info: "Info" },
  sections: {
    "СКОРИНГ": "Scoring",
    "ДОСЬЕ": "Dossier",
    "ЧТО_С_ДЕНЬГАМИ": "Finances",
    "ТРЕНД": "Trend",
    "ФИБОНАЧЧИ": "Fibonacci",
    "ОЦЕНКА_ЦЕНЫ": "Price check",
    "КАТАЛИЗАТОРЫ": "Catalysts",
    "СИЛЬНЫЕ_СТОРОНЫ": "Strengths",
    "СЛАБЫЕ_СТОРОНЫ": "Weaknesses",
    "ВОЗМОЖНОСТИ": "Opportunities",
    "УГРОЗЫ": "Threats",
    "ПРОГНОЗ": "Forecast",
    "ВЕРДИКТ": "Verdict",
    "СОВЕТЫ": "Recommendations",
    "ИТОГ": "Summary",
    "ЗЕЛЕНЫЕ_ФЛАГИ": "Green flags",
    "КРАСНЫЕ_ФЛАГИ": "Red flags",
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
    noData: "Metrics will appear after the first request.",
  },
};

UI_TEXT.uz = {
  pageTitle: "UZ Stock Analyzer",
  languageLabel: "Til",
  languageOptions: { ru: "Ruscha", en: "English", uz: "O'zbek" },
  hero: {
    eyebrow: "O'zbekistondagi ochiq kompaniyalar tahlili",
    copy:
      "Kompaniyalarni tez va tizimli tahlil qilish uchun veb-xizmat. Ro'yxatdan o'ting, kiring, kompaniyani tanlang va baho, asosiy ko'rsatkichlar hamda tuzilgan hisobot oling.",
  },
  nav: { main: "Bosh sahifa", about: "Loyiha haqida", auth: "Kirish", profile: "Profil", analysis: "Tahlil" },
  main: {
    panelLabel: "Bosh sahifa",
    title: "Xizmat nima qiladi",
    copy:
      "O'zbekiston kompaniyalarini tahlil qilish uchun ixcham veb-interfeys. Foydalanuvchi akkaunt yaratadi, tizimga kiradi, kompaniyani tanlaydi va yakuniy baho, xulosa hamda asosiy bloklar bilan tuzilgan natijani oladi.",
    features: [
      { title: "1. Ro'yxatdan o'tish", copy: "Email va parol orqali akkaunt yarating." },
      { title: "2. Kompaniyani tanlash", copy: "Ticker bo'yicha qidirish yoki ro'yxatdan tanlash." },
      { title: "3. Tahlil olish", copy: "Yakuniy baho, xulosa, metrikalar va hisobot bo'limlari." },
    ],
    sideTitle: "Nima uchun kerak",
    notes: [
      { title: "Tezkor dastlabki baho", copy: "Xizmat kompaniyani chuqur o'rganish kerakmi yoki yo'qmi, tez tushunishga yordam beradi." },
      { title: "Kirish nazorati", copy: "Tahlil faqat avtorizatsiyadan o'tgan foydalanuvchilar uchun mavjud." },
      { title: "O'qilishi oson natija", copy: "Interfeys yakuniy baho, asosiy ko'rsatkichlar va tuzilgan hisobotni ko'rsatadi." },
    ],
  },
  about: {
    panelLabel: "Loyiha haqida",
    title: "Yechim tavsifi",
    leftNotes: [
      { title: "Ma'lumot manbai", copy: "Backend tahlil yaratilishidan oldin kompaniya ma'lumotlarini yig'adi va tuzadi." },
      { title: "Backend", copy: "Railway Postgres ustidagi API, avtorizatsiya va sessiyalar bir qatlam sifatida ishlaydi." },
      { title: "Frontend", copy: "Interfeys ro'yxatdan o'tish, kirish va tahlil natijalari bilan ixcham analitik panelga aylantirilgan." },
    ],
    rightTitle: "Foydalanuvchi nimani oladi",
    rightCards: [
      { title: "Baho", copy: "Tezkor yo'nalish uchun yagona ko'rsatkich." },
      { title: "Xulosa", copy: "Kompaniya bo'yicha qisqa va professional xulosa." },
      { title: "Metrikalar", copy: "Tez o'qish uchun kartalardagi asosiy ko'rsatkichlar." },
      { title: "Hisobot", copy: "Chuqurroq ko'rib chiqish uchun batafsil bo'limlar." },
    ],
  },
  auth: {
    panelLabel: "Hisob",
    title: "Kirish",
    statusSignedOut: "Kirish yo'q",
    statusSignedIn: "Kirish amalga oshirildi",
    loginTab: "Kirish",
    registerTab: "Ro'yxatdan o'tish",
    login: { email: "Email", emailPlaceholder: "you@example.com", password: "Parol", passwordPlaceholder: "Parolingizni kiriting", submit: "Kirish" },
    register: { fullName: "Ism va familiya", fullNamePlaceholder: "Sizning ismingiz", email: "Email", emailPlaceholder: "you@example.com", password: "Parol", passwordPlaceholder: "Kamida 8 ta belgi", submit: "Akkaunt yaratish" },
    oauthLabel: "Yoki davom eting",
    signedInAs: "Kirish amalga oshirildi",
    emailLabel: "Email",
    logout: "Chiqish",
    messages: {
      loggingIn: "Kirish amalga oshirilmoqda...",
      registering: "Akkaunt yaratilmoqda...",
      loginSuccess: "Kirish amalga oshirildi, {name}",
      registerSuccess: "Akkaunt yaratildi: {email}",
      signOut: "Chiqish amalga oshirildi",
      oauthSuccess: "{provider} orqali kirish amalga oshirildi",
      oauthReady: "OAuth orqali kirish yakunlandi",
      authRequired: "Avval tizimga kiring",
      signedIn: "Tizimda: {email}",
    },
  },
  profile: {
    panelLabel: "Profil",
    title: "Shaxsiy kabinet",
    statusNotLoaded: "Profil yuklanmadi",
    statusLoaded: "Profil yangilandi",
    unavailable: "Profil mavjud emas",
    emailHint: "Shaxsiy ma'lumotlarni ko'rish uchun tizimga kiring.",
    memberSince: "Ro'yxatdan o'tish sanasi shu yerda ko'rsatiladi.",
    memberSinceWithDate: "Tizimda {date} dan beri",
    analyzeBtn: "Tahlilga o'tish",
    refreshBtn: "Profilni yangilash",
    editTitle: "Profilni tahrirlash",
    editSub: "Ism va avatar",
    nameLabel: "Ko'rinadigan ism",
    namePlaceholder: "Sizning ismingiz",
    avatarLabel: "Avatar",
    saveBtn: "O'zgarishlarni saqlash",
    clearAvatarBtn: "Avatarni o'chirish",
    editHint: "Ismni yangilash, avatar yuklash yoki joriy rasmni tozalash mumkin.",
    savedHint: "Profil yangilandi.",
    clearHint: "Saqlagandan so'ng joriy avatar o'chiriladi.",
    readImageError: "Rasmni o'qib bo'lmadi",
    statsLabel: "Statistika",
    statsTitle: "Faollik ko'rsatkichlari",
    statsEmpty: "Statistika birinchi tahlildan keyin ko'rinadi.",
    favoritesLabel: "Tanlanganlar",
    favoritesTitle: "Saqlangan kompaniyalar",
    favoritesEmpty: "Tahlil yoki tarixdan kompaniyalarni tanlanganlarga qo'shing.",
    historyLabel: "Tarix",
    historyTitle: "Oxirgi tahlillar",
    historySearchPlaceholder: "Kompaniya yoki ticker bo'yicha qidirish",
    historyAll: "Barcha tahlillar",
    historyFavorites: "Faqat tanlanganlar",
    historySummaryPrefix: "Ko'rsatilgan",
    historyEmpty: "Birinchi tahlildan keyin bu yerda faoliyat tarixi ko'rinadi.",
    historyFilteredEmpty: "Tanlangan filtr bo'yicha hech narsa topilmadi.",
    historyFromCache: "keshdan",
    historyFresh: "yangi natija",
    historyModelPrefix: "model",
    historyFavoriteAdd: "Tanlanganlarga qo'shish",
    historyFavoriteRemove: "Tanlanganlardan olib tashlash",
    historyAnalysisDone: "Tahlil yakunlandi",
    favoritesRemove: "O'chirish",
    noTitle: "Nomsiz",
    stats: {
      totalAnalyses: "Jami tahlillar",
      totalAnalysesSub: "Barcha bajarilgan so'rovlar",
      analyses7d: "7 kun ichida",
      analyses7dSub: "Haftalik faollik",
      analyses30d: "30 kun ichida",
      analyses30dSub: "Oylik faollik",
      analyzedCompanies: "Tarixdagi kompaniyalar",
      analyzedCompaniesSub: "Noyob tickerlar",
      avgScore: "O'rtacha baho",
      avgScoreSub: "Tahlillar bo'yicha o'rtacha natija",
      bestScore: "Eng yaxshi baho",
      bestScoreSub: "Eng yuqori natija",
      topCompany: "Eng ko'p ko'rilgan",
      topCompanySub: "{count} ta tahlil",
      topCompanySubEmpty: "Hozircha ma'lumot yo'q",
      cachedAnalyses: "Keshlangan",
      cachedAnalysesSub: "Qancha javob keshdan kelgan",
      lastAnalysis: "Oxirgi tahlil",
      lastAnalysisSub: "Oxirgi so'rov vaqti",
    },
  },
  analysis: {
    panelLabel: "Tahlil",
    title: "Kompaniya tahlili",
    apiReady: "API tayyor",
    apiLoading: "Ma'lumotlar olinmoqda...",
    apiError: "API mavjud emas",
    companyLabel: "Kompaniya",
    companyPlaceholder: "Kompaniya nomi yoki ticker ni kiriting",
    modeLabel: "Rejim",
    modeQuick: "Tez",
    modeFull: "To'liq",
    includeHtml: "HTML hisobotni qaytarish",
    submit: "Tahlil qilish",
    availableTitle: "Mavjud kompaniyalar",
    companyCount: "{count} ta kompaniya",
    resultLabel: "Natija",
    resultEmpty: "Tahlil hali bajarilmagan",
    resultCacheWaiting: "Kutilmoqda",
    resultCacheHit: "Keshdan",
    resultFresh: "Yangi natija",
    resultRunning: "Tahlil bajarilmoqda...",
    scoreCaption: "Baho / 100",
    verdictPlaceholder: "Yakuniy xulosani ko'rish uchun tahlilni ishga tushiring.",
    favoriteAdd: "Tanlanganlarga qo'shish",
    favoriteRemove: "Tanlanganlardan olib tashlash",
    metricsLabel: "Metrikalar",
    metricsTitle: "Asosiy ko'rsatkichlar",
    metricsEmpty: "Metrikalar birinchi so'rovdan keyin ko'rinadi.",
    sectionsLabel: "Hisobot",
    sectionsTitle: "Hisobot bo'limlari",
    sectionsEmpty: "Tahlildan keyin bu yerda hisobot bo'limlari paydo bo'ladi.",
    loadingTitle: "Tahlil: {company}",
    loadingRunning: "Tahlil bajarilmoqda...",
    loadingCache: "Yuklanmoqda",
    loadingVerdict: "Tahlil bajarilmoqda. Iltimos kuting.",
    loadingMetrics: "Yuklanmoqda",
    completed: "Tahlil yakunlandi: {company}",
  },
  toasts: { error: "Xato", success: "Tayyor", info: "Ma'lumot" },
  sections: {
    "СКОРИНГ": "Baho",
    "ДОСЬЕ": "Dossier",
    "ЧТО_С_ДЕНЬГАМИ": "Moliyaviy holat",
    "ТРЕНД": "Trend",
    "ФИБОНАЧЧИ": "Fibonachchi",
    "ОЦЕНКА_ЦЕНЫ": "Narx bahosi",
    "КАТАЛИЗАТОРЫ": "Katalizatorlar",
    "СИЛЬНЫЕ_СТОРОНЫ": "Kuchli tomonlar",
    "СЛАБЫЕ_СТОРОНЫ": "Zaif tomonlar",
    "ВОЗМОЖНОСТИ": "Imkoniyatlar",
    "УГРОЗЫ": "Tahdidlar",
    "ПРОГНОЗ": "Prognoz",
    "ВЕРДИКТ": "Xulosa",
    "СОВЕТЫ": "Tavsiyalar",
    "ИТОГ": "Yakun",
    "ЗЕЛЕНЫЕ_ФЛАГИ": "Yashil belgilar",
    "КРАСНЫЕ_ФЛАГИ": "Qizil belgilar",
  },
  metrics: {
    total_score: "Jami ball",
    piotroski_f_score: "Piotroski F-Score",
    altman_z_score: "Altman Z-Score",
    buffett_criteria: "Buffett mezonlari",
    graham_number: "Graham qiymati",
    dcf: "DCF baholash",
    industry: "Sektor",
    market_liquidity: "Likvidlik",
    momentum: "Trend",
    noData: "Metrikalar birinchi so'rovdan keyin ko'rinadi.",
  },
};

function normalizeLanguage(language) {
  return ["ru", "en", "uz"].includes(String(language || "").trim().toLowerCase())
    ? String(language).trim().toLowerCase()
    : "ru";
}

function t(path, params = {}, language = state.language) {
  const lang = normalizeLanguage(language);
  const parts = String(path).split(".");
  const getValue = (source) => {
    let value = source;
    for (const part of parts) {
      value = value?.[part];
    }
    return value;
  };
  let value = getValue(UI_TEXT[lang]);
  if (value === undefined || value === null || value === "") {
    value = getValue(UI_TEXT.ru);
  }
  if (typeof value !== "string") return "";
  return value.replace(/\{(\w+)\}/g, (_, key) => String(params[key] ?? ""));
}

function setText(selector, value) {
  const el = document.querySelector(selector);
  if (el) el.textContent = value;
}

function setPlaceholder(selector, value) {
  const el = document.querySelector(selector);
  if (el) el.placeholder = value;
}

function applyLanguage(language = state.language) {
  const lang = normalizeLanguage(language);
  state.language = lang;
  localStorage.setItem(LANGUAGE_KEY, lang);
  document.documentElement.lang = lang;
  document.title = t("pageTitle");
  const siteNav = document.querySelector(".site-nav");
  if (siteNav) {
    siteNav.setAttribute(
      "aria-label",
      lang === "en" ? "Site sections" : lang === "uz" ? "Sahifa bo'limlari" : "Разделы сайта"
    );
  }

  if (els.languageSelect && els.languageSelect.value !== lang) {
    els.languageSelect.value = lang;
  }
  setText(".language-switch label", t("languageLabel"));
  if (els.languageSelect?.options?.length >= 3) {
    els.languageSelect.options[0].textContent = t("languageOptions.ru");
    els.languageSelect.options[1].textContent = t("languageOptions.en");
    els.languageSelect.options[2].textContent = t("languageOptions.uz");
  }

  setText('.nav-btn[data-view="main"]', t("nav.main"));
  setText('.nav-btn[data-view="about"]', t("nav.about"));
  setText('.nav-btn[data-view="auth"]', t("nav.auth"));
  setText('.nav-btn[data-view="profile"]', t("nav.profile"));
  setText('.nav-btn[data-view="analysis"]', t("nav.analysis"));

  setText(".hero .eyebrow", t("hero.eyebrow"));
  setText(".hero h1", t("pageTitle"));
  setText(".hero-copy", t("hero.copy"));

  setText('#view-main .feature-panel:nth-of-type(1) .panel-label', t("main.panelLabel"));
  setText('#view-main .feature-panel:nth-of-type(1) h2', t("main.title"));
  setText('#view-main .feature-panel:nth-of-type(1) .feature-copy', t("main.copy"));
  const mainFeatures = Array.from(document.querySelectorAll('#view-main .feature-panel:nth-of-type(1) .feature-card'));
  mainFeatures.forEach((card, index) => {
    const item = t(`main.features.${index}.title`) || UI_TEXT[lang].main.features[index]?.title || "";
    const copy = t(`main.features.${index}.copy`) || UI_TEXT[lang].main.features[index]?.copy || "";
    const strong = card.querySelector("strong");
    const span = card.querySelector("span");
    if (strong) strong.textContent = item;
    if (span) span.textContent = copy;
  });
  setText('#view-main .feature-panel:nth-of-type(2) .panel-label', t("main.panelLabel"));
  setText('#view-main .feature-panel:nth-of-type(2) h2', t("main.sideTitle"));
  const mainNotes = Array.from(document.querySelectorAll('#view-main .feature-panel:nth-of-type(2) .note-card'));
  mainNotes.forEach((card, index) => {
    const item = UI_TEXT[lang].main.notes[index];
    if (!item) return;
    const strong = card.querySelector("strong");
    const p = card.querySelector("p");
    if (strong) strong.textContent = item.title;
    if (p) p.textContent = item.copy;
  });

  setText('#view-about .feature-panel:nth-of-type(1) .panel-label', t("about.panelLabel"));
  setText('#view-about .feature-panel:nth-of-type(1) h2', t("about.title"));
  const aboutNotes = Array.from(document.querySelectorAll('#view-about .feature-panel:nth-of-type(1) .note-card'));
  aboutNotes.forEach((card, index) => {
    const item = UI_TEXT[lang].about.leftNotes[index];
    if (!item) return;
    const strong = card.querySelector("strong");
    const p = card.querySelector("p");
    if (strong) strong.textContent = item.title;
    if (p) p.textContent = item.copy;
  });
  setText('#view-about .feature-panel:nth-of-type(2) .panel-label', t("about.panelLabel"));
  setText('#view-about .feature-panel:nth-of-type(2) h2', t("about.rightTitle"));
  const aboutCards = Array.from(document.querySelectorAll('#view-about .feature-panel:nth-of-type(2) .feature-card'));
  aboutCards.forEach((card, index) => {
    const item = UI_TEXT[lang].about.rightCards[index];
    if (!item) return;
    const strong = card.querySelector("strong");
    const span = card.querySelector("span");
    if (strong) strong.textContent = item.title;
    if (span) span.textContent = item.copy;
  });

  setText("#view-auth .panel-label", t("auth.panelLabel"));
  setText("#view-auth h2", t("auth.title"));
  setText("#authStatus", state.user ? t("auth.statusSignedIn") : t("auth.statusSignedOut"));
  setText('#view-auth .tab-btn[data-tab="login"]', t("auth.loginTab"));
  setText('#view-auth .tab-btn[data-tab="register"]', t("auth.registerTab"));
  const loginForm = els.loginForm;
  if (loginForm) {
    const labels = loginForm.querySelectorAll("label");
    if (labels[0]) {
      labels[0].querySelector("span").textContent = t("auth.login.email");
      labels[0].querySelector("input").placeholder = t("auth.login.emailPlaceholder");
    }
    if (labels[1]) {
      labels[1].querySelector("span").textContent = t("auth.login.password");
      labels[1].querySelector("input").placeholder = t("auth.login.passwordPlaceholder");
    }
    loginForm.querySelector('button[type="submit"]').textContent = t("auth.login.submit");
  }
  const registerForm = els.registerForm;
  if (registerForm) {
    const labels = registerForm.querySelectorAll("label");
    if (labels[0]) {
      labels[0].querySelector("span").textContent = t("auth.register.fullName");
      labels[0].querySelector("input").placeholder = t("auth.register.fullNamePlaceholder");
    }
    if (labels[1]) {
      labels[1].querySelector("span").textContent = t("auth.register.email");
      labels[1].querySelector("input").placeholder = t("auth.register.emailPlaceholder");
    }
    if (labels[2]) {
      labels[2].querySelector("span").textContent = t("auth.register.password");
      labels[2].querySelector("input").placeholder = t("auth.register.passwordPlaceholder");
    }
    registerForm.querySelector('button[type="submit"]').textContent = t("auth.register.submit");
  }
  setText(".oauth-label", t("auth.oauthLabel"));
  setText(".user-line .muted", t("auth.signedInAs"));
  const userLines = document.querySelectorAll("#userCard .user-line .muted");
  if (userLines[1]) userLines[1].textContent = t("auth.emailLabel");
  if (els.logoutBtn) els.logoutBtn.textContent = t("auth.logout");

  setText('#view-profile .panel-label', t("profile.panelLabel"));
  setText('#view-profile .profile-hero-panel h2', t("profile.title"));
  setText("#profileStatus", state.user ? t("profile.statusLoaded") : t("profile.statusNotLoaded"));
  setText("#profileEmail", state.user ? (state.user.email || "") : t("profile.emailHint"));
  setText("#profileMemberSince", t("profile.memberSince"));
  setText("#profileAnalyzeBtn", t("profile.analyzeBtn"));
  setText("#profileRefreshBtn", t("profile.refreshBtn"));
  setText('#view-profile .profile-edit-form .section-title-row h3', t("profile.editTitle"));
  setText('#view-profile .profile-edit-form .section-title-row .muted', t("profile.editSub"));
  const profileLabels = document.querySelectorAll("#profileEditForm label");
  if (profileLabels[0]) {
    profileLabels[0].querySelector("span").textContent = t("profile.nameLabel");
    profileLabels[0].querySelector("input").placeholder = t("profile.namePlaceholder");
  }
  if (profileLabels[1]) {
    profileLabels[1].querySelector("span").textContent = t("profile.avatarLabel");
  }
  setText("#profileSaveBtn", t("profile.saveBtn"));
  setText("#profileClearAvatarBtn", t("profile.clearAvatarBtn"));
  setText("#profileEditHint", t("profile.editHint"));
  setText('#view-profile .profile-stats-panel .panel-label', t("profile.statsLabel"));
  setText('#view-profile .profile-stats-panel h2', t("profile.statsTitle"));
  setText('#view-profile .profile-favorites-panel .panel-label', t("profile.favoritesLabel"));
  setText('#view-profile .profile-favorites-panel h2', t("profile.favoritesTitle"));
  setText('#view-profile .profile-history-panel .panel-label', t("profile.historyLabel"));
  setText('#view-profile .profile-history-panel h2', t("profile.historyTitle"));
  setPlaceholder("#profileHistorySearch", t("profile.historySearchPlaceholder"));
  const historyMode = els.profileHistoryMode;
  if (historyMode?.options?.length >= 2) {
    historyMode.options[0].textContent = t("profile.historyAll");
    historyMode.options[1].textContent = t("profile.historyFavorites");
  }

  setText('#view-analysis .analysis-panel .panel-label', t("analysis.panelLabel"));
  setText('#view-analysis .analysis-panel h2', t("analysis.title"));
  setText("#apiState", t("analysis.apiReady"));
  const companyLabel = document.querySelector('#analysisForm label.wide span');
  if (companyLabel) companyLabel.textContent = t("analysis.companyLabel");
  setPlaceholder("#companyInput", t("analysis.companyPlaceholder"));
  const modeLabel = document.querySelector('#analysisForm label:not(.wide) span');
  if (modeLabel) modeLabel.textContent = t("analysis.modeLabel");
  const modeSelect = document.querySelector('#analysisForm select[name="analysis_mode"]');
  if (modeSelect?.options?.length >= 2) {
    modeSelect.options[0].textContent = t("analysis.modeQuick");
    modeSelect.options[1].textContent = t("analysis.modeFull");
  }
  const htmlToggle = document.querySelector('#analysisForm .toggle-row span');
  if (htmlToggle) htmlToggle.textContent = t("analysis.includeHtml");
  const analyzeBtn = document.querySelector('#analysisForm .analyze-btn');
  if (analyzeBtn) analyzeBtn.textContent = t("analysis.submit");
  setText(".quick-list-wrap .section-title-row h3", t("analysis.availableTitle"));
  if (els.companyCount) {
    els.companyCount.textContent = t("analysis.companyCount", { count: state.companies.length });
  }
  setText("#resultHero .panel-label", t("analysis.resultLabel"));
  setText("#resultCompany", t("analysis.resultEmpty"));
  setText("#resultCache", t("analysis.resultCacheWaiting"));
  setText(".score-caption", t("analysis.scoreCaption"));
  setText("#verdictValue", t("analysis.verdictPlaceholder"));
  setText("#resultFavoriteBtn", t("analysis.favoriteAdd"));
  const analysisText = getAnalysisLocaleText();
  setText("#chartTitle", analysisText.chartTitle);
  setText("#chartMeta", analysisText.chartMetaEmpty);
  const miniLabels = document.querySelectorAll(".mini-market-label");
  if (miniLabels[0]) miniLabels[0].textContent = analysisText.signalRevenue;
  if (miniLabels[1]) miniLabels[1].textContent = analysisText.signalMargin;
  if (miniLabels[2]) miniLabels[2].textContent = analysisText.signalRisk;
  if (els.analysisChart && !state.lastResult) {
    setAnalysisChartEmpty(analysisText.chartEmpty);
  }
  setText('#view-analysis .metrics-panel .panel-label', t("analysis.metricsLabel"));
  setText('#view-analysis .metrics-panel h2', t("analysis.metricsTitle"));
  setText('#view-analysis .sections-panel .panel-label', t("analysis.sectionsLabel"));
  setText('#view-analysis .sections-panel h2', t("analysis.sectionsTitle"));

  if (state.profile) {
    renderProfile(state.profile);
  }
  if (state.lastResult) {
    renderResult(state.lastResult);
  } else {
    clearResults();
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setMessage(text, tone = "muted") {
  els.authMessage.textContent = text;
  els.authMessage.style.color = tone === "error" ? "var(--danger)" : "var(--muted)";
}

function showToast(message, tone = "info", timeoutMs = 3800) {
  if (!els.toastStack) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${tone}`;

  const label = tone === "error" ? t("toasts.error") : tone === "success" ? t("toasts.success") : t("toasts.info");
  toast.innerHTML = `
    <div class="toast-label">${label}</div>
    <div class="toast-message">${escapeHtml(message)}</div>
  `;

  els.toastStack.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("show"));

  window.setTimeout(() => {
    toast.classList.remove("show");
    window.setTimeout(() => toast.remove(), 220);
  }, timeoutMs);
}

function clearHash() {
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
}

function consumeOAuthHash() {
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const token = hash.get("token");
  const provider = hash.get("provider") || hash.get("oauth");
  const error = hash.get("oauth_error") || hash.get("error");

  if (error) {
    state.oauthMessage = decodeURIComponent(error.replace(/\+/g, " "));
    setMessage(state.oauthMessage, "error");
    showToast(state.oauthMessage, "error");
    clearHash();
    return false;
  }

  if (!token) {
    return false;
  }

  state.token = token;
  localStorage.setItem(STORAGE_KEY, token);
  const providerLabel = provider ? (provider === "google" ? "Google" : provider) : "";
  state.oauthMessage = providerLabel
    ? t("auth.messages.oauthSuccess", { provider: providerLabel })
    : t("auth.messages.oauthReady");
  showToast(state.oauthMessage, "success");
  clearHash();
  return true;
}

function setAuthState(user) {
  state.user = user;
  const signedIn = Boolean(user);

  els.userCard.classList.toggle("hidden", !signedIn);
  els.authStatus.textContent = signedIn ? t("auth.statusSignedIn") : t("auth.statusSignedOut");
  els.authStatus.className = signedIn ? "status-badge" : "status-badge muted";

  if (signedIn) {
    els.userName.textContent = user.full_name || user.email;
    els.userEmail.textContent = user.email;
    setMessage(t("auth.messages.signedIn", { email: user.email }));
  } else {
    els.userName.textContent = "-";
    els.userEmail.textContent = "-";
  }
}

function getProfileInitials(user) {
  const source = (user?.full_name || user?.email || "?").trim();
  const parts = source.split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  const first = parts[0][0] || "";
  const second = parts.length > 1 ? parts[1][0] : (parts[0][1] || "");
  return (first + second).toUpperCase();
}

function hashToHue(source) {
  const value = String(source || "").split("").reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) % 360, 47);
  return value;
}

function formatDateLabel(value) {
  if (!value) return state.language === "en" ? "No data" : state.language === "uz" ? "Ma'lumot yo'q" : "Нет данных";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return state.language === "en" ? "No data" : state.language === "uz" ? "Ma'lumot yo'q" : "Нет данных";
  const locale = state.language === "en" ? "en-US" : state.language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatCompactNumber(value, digits = 1) {
  if (value === undefined || value === null || value === "") return "—";
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const locale = state.language === "en" ? "en-US" : state.language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  const formatter = new Intl.NumberFormat(locale, {
    notation: Math.abs(num) >= 1000 ? "compact" : "standard",
    maximumFractionDigits: digits,
  });
  return formatter.format(num);
}

function formatSignedPercent(value, digits = 1) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const fixed = Number(num.toFixed(digits));
  const sign = fixed > 0 ? "+" : "";
  return `${sign}${fixed}%`;
}

function formatRatio(value, digits = 2) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const locale = state.language === "en" ? "en-US" : state.language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  }).format(num);
}

function getAnalysisLocaleText() {
  if (state.language === "en") {
    return {
      chartTitle: "Revenue and profit trend",
      chartEmpty: "The chart will appear after the first analysis.",
      chartMetaEmpty: "No data",
      chartMetaYears: "{count} annual periods",
      chartLegendRevenue: "Revenue",
      chartLegendProfit: "Net income",
      signalTrend: "Trend",
      signalLatest: "Latest",
      signalUp: "Positive",
      signalFlat: "Stable",
      signalDown: "Under pressure",
      signalNoData: "No data",
    };
  }
  if (state.language === "uz") {
    return {
      chartTitle: "Tushum va foyda dinamikasi",
      chartEmpty: "Grafik birinchi tahlildan so'ng paydo bo'ladi.",
      chartMetaEmpty: "Ma'lumot yo'q",
      chartMetaYears: "{count} yillik davr",
      chartLegendRevenue: "Tushum",
      chartLegendProfit: "Sof foyda",
      signalTrend: "Trend",
      signalLatest: "So'nggi",
      signalUp: "Ijobiy",
      signalFlat: "Barqaror",
      signalDown: "Bosim ostida",
      signalNoData: "Ma'lumot yo'q",
    };
  }
  return {
    chartTitle: "Динамика выручки и прибыли",
    chartEmpty: "График появится после первого анализа.",
    chartMetaEmpty: "Нет данных",
    chartMetaYears: "{count} годовых периодов",
    chartLegendRevenue: "Выручка",
    chartLegendProfit: "Чистая прибыль",
    signalTrend: "Тренд",
    signalLatest: "Последнее",
    signalUp: "Позитивный",
    signalFlat: "Стабильно",
    signalDown: "Под давлением",
    signalNoData: "Недостаточно данных",
  };
}

function scaleSeries(values, width, height, padding) {
  const finite = values.filter((value) => Number.isFinite(value));
  if (!finite.length) return null;

  let min = Math.min(...finite);
  let max = Math.max(...finite);
  if (min > 0) min = 0;
  if (max < 0) max = 0;

  let range = max - min;
  if (range === 0) {
    const base = Math.max(Math.abs(max), 1);
    min -= base * 0.5;
    max += base * 0.5;
    range = max - min;
  } else {
    const pad = range * 0.12;
    min -= pad;
    max += pad;
    range = max - min;
  }

  const innerWidth = Math.max(1, width - padding.left - padding.right);
  const innerHeight = Math.max(1, height - padding.top - padding.bottom);

  const x = (index, total) => padding.left + (total <= 1 ? innerWidth / 2 : (index / (total - 1)) * innerWidth);
  const y = (value) => padding.top + ((max - value) / range) * innerHeight;

  return { min, max, range, x, y, innerWidth, innerHeight };
}

function buildPath(points) {
  if (!points.length) return "";
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" ");
}

function setAnalysisChartEmpty(message = "") {
  const text = message || getAnalysisLocaleText().chartEmpty;
  if (els.analysisChart) {
    els.analysisChart.classList.add("empty-state");
    els.analysisChart.innerHTML = `<p class="empty-copy">${escapeHtml(text)}</p>`;
  }
  if (els.chartTitle) els.chartTitle.textContent = getAnalysisLocaleText().chartTitle;
  if (els.chartMeta) els.chartMeta.textContent = getAnalysisLocaleText().chartMetaEmpty;
  if (els.revenueSignal) els.revenueSignal.textContent = "—";
  if (els.revenueSignalSub) els.revenueSignalSub.textContent = getAnalysisLocaleText().signalNoData;
  if (els.marginSignal) els.marginSignal.textContent = "—";
  if (els.marginSignalSub) els.marginSignalSub.textContent = getAnalysisLocaleText().signalNoData;
  if (els.riskSignal) els.riskSignal.textContent = "—";
  if (els.riskSignalSub) els.riskSignalSub.textContent = getAnalysisLocaleText().signalNoData;
  [els.revenueSignal, els.marginSignal, els.riskSignal].forEach((el) => {
    el?.closest(".mini-market-card")?.setAttribute("data-tone", "neutral");
  });
}

function renderMiniSignal(cardEl, valueEl, subEl, { value, sub, tone = "neutral" }) {
  if (!cardEl || !valueEl || !subEl) return;
  cardEl.dataset.tone = tone;
  valueEl.textContent = value ?? "—";
  subEl.textContent = sub ?? getAnalysisLocaleText().signalNoData;
}

function renderAnalysisChart(data = {}) {
  if (!els.analysisChart) return;

  const langText = getAnalysisLocaleText();
  const series = Array.isArray(data.ifrs_snapshot?.series?.annual) ? data.ifrs_snapshot.series.annual : [];
  const points = series
    .map((row) => ({
      year: row?.year,
      revenue: Number(row?.revenue),
      profit: Number(row?.net_income),
    }))
    .filter((row) => row.year !== undefined && row.year !== null && (Number.isFinite(row.revenue) || Number.isFinite(row.profit)));

  if (points.length < 2) {
    setAnalysisChartEmpty(langText.chartEmpty);
    return;
  }

  const width = 1000;
  const height = 340;
  const padding = { left: 74, right: 24, top: 28, bottom: 44 };
  const scale = scaleSeries(points.flatMap((point) => [point.revenue, point.profit]), width, height, padding);

  if (!scale) {
    setAnalysisChartEmpty(langText.chartEmpty);
    return;
  }

  const revenuePathPoints = points.map((point, index) => ({
    x: scale.x(index, points.length),
    y: scale.y(Number.isFinite(point.revenue) ? point.revenue : scale.min),
  }));
  const profitPathPoints = points.map((point, index) => ({
    x: scale.x(index, points.length),
    y: scale.y(Number.isFinite(point.profit) ? point.profit : scale.min),
  }));

  const zeroY = scale.y(0);
  const revenuePath = buildPath(revenuePathPoints);
  const profitPath = buildPath(profitPathPoints);
  const areaPath =
    revenuePathPoints.length >= 2
      ? `${revenuePath} L ${revenuePathPoints.at(-1).x.toFixed(2)} ${zeroY.toFixed(2)} L ${revenuePathPoints[0].x.toFixed(2)} ${zeroY.toFixed(2)} Z`
      : "";

  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, index) => {
    const ratio = index / ticks;
    const value = scale.max - ratio * scale.range;
    const y = padding.top + ratio * scale.innerHeight;
    return { value, y };
  });

  const xLabels = points.map((point, index) => ({
    x: scale.x(index, points.length),
    label: String(point.year ?? ""),
  }));

  const latest = points.at(-1);
  const previous = points.at(-2) || {};
  const revenueChange = Number.isFinite(latest.revenue) && Number.isFinite(previous.revenue)
    ? ((latest.revenue - previous.revenue) / Math.abs(previous.revenue || 1)) * 100
    : null;
  const profitChange = Number.isFinite(latest.profit) && Number.isFinite(previous.profit)
    ? ((latest.profit - previous.profit) / Math.abs(previous.profit || 1)) * 100
    : null;

  const chartMeta = `${points[0].year}–${latest.year} · ${langText.chartMetaYears.replace("{count}", String(points.length))}`;
  els.chartTitle.textContent = langText.chartTitle;
  els.chartMeta.textContent = chartMeta;
  els.analysisChart.classList.remove("empty-state");
  els.analysisChart.innerHTML = `
    <svg class="result-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(langText.chartTitle)}">
      <defs>
        <linearGradient id="revenueAreaGradient" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stop-color="#6ef0c1" stop-opacity="0.42" />
          <stop offset="100%" stop-color="#6ef0c1" stop-opacity="0.02" />
        </linearGradient>
      </defs>
      ${yTicks
        .map(
          (tick) => `
            <line x1="${padding.left}" y1="${tick.y.toFixed(2)}" x2="${width - padding.right}" y2="${tick.y.toFixed(2)}" class="chart-grid-line"></line>
            <text x="${padding.left - 10}" y="${(tick.y + 4).toFixed(2)}" class="chart-axis-label chart-axis-label-y" text-anchor="end">${escapeHtml(formatCompactNumber(tick.value))}</text>
          `
        )
        .join("")}
      ${areaPath ? `<path d="${areaPath}" class="chart-area"></path>` : ""}
      <path d="${revenuePath}" class="chart-line chart-line-revenue"></path>
      <path d="${profitPath}" class="chart-line chart-line-profit"></path>
      ${points
        .map(
          (point, index) => `
            <circle cx="${scale.x(index, points.length).toFixed(2)}" cy="${scale.y(Number.isFinite(point.revenue) ? point.revenue : scale.min).toFixed(2)}" r="4.8" class="chart-dot chart-dot-revenue"></circle>
            <circle cx="${scale.x(index, points.length).toFixed(2)}" cy="${scale.y(Number.isFinite(point.profit) ? point.profit : scale.min).toFixed(2)}" r="4.8" class="chart-dot chart-dot-profit"></circle>
          `
        )
        .join("")}
      ${xLabels
        .map(
          (item) => `
            <text x="${item.x.toFixed(2)}" y="${height - 16}" class="chart-axis-label chart-axis-label-x" text-anchor="middle">${escapeHtml(item.label)}</text>
          `
        )
        .join("")}
    </svg>
    <div class="chart-legend">
      <div class="legend-chip">
        <span class="legend-swatch legend-swatch-revenue"></span>
        <span class="legend-label">${escapeHtml(langText.chartLegendRevenue)}</span>
        <strong class="legend-value">${escapeHtml(formatCompactNumber(latest.revenue))}</strong>
        <span class="legend-delta ${revenueChange === null ? "" : revenueChange >= 0 ? "is-up" : "is-down"}">${escapeHtml(revenueChange === null ? "—" : formatSignedPercent(revenueChange))}</span>
      </div>
      <div class="legend-chip">
        <span class="legend-swatch legend-swatch-profit"></span>
        <span class="legend-label">${escapeHtml(langText.chartLegendProfit)}</span>
        <strong class="legend-value">${escapeHtml(formatCompactNumber(latest.profit))}</strong>
        <span class="legend-delta ${profitChange === null ? "" : profitChange >= 0 ? "is-up" : "is-down"}">${escapeHtml(profitChange === null ? "—" : formatSignedPercent(profitChange))}</span>
      </div>
    </div>
    <div class="chart-axis-note">
      <span>${escapeHtml(xLabels[0]?.label || "")}</span>
      <span>${escapeHtml(xLabels.at(-1)?.label || "")}</span>
    </div>
  `;

  const revenueTone = revenueChange === null ? "neutral" : revenueChange >= 10 ? "good" : revenueChange >= 0 ? "warning" : "danger";
  const netMargin = Number(data.ifrs_snapshot?.income_statement?.net_margin_pct);
  const roe = Number(data.ifrs_snapshot?.quality?.roe_pct);
  const roa = Number(data.ifrs_snapshot?.quality?.roa_pct);
  const marginTone = Number.isFinite(netMargin)
    ? netMargin >= 15
      ? "good"
      : netMargin >= 5
        ? "warning"
        : "danger"
    : Number.isFinite(roe)
      ? roe >= 15
        ? "good"
        : roe >= 5
          ? "warning"
          : "danger"
      : "neutral";
  const marginValue = Number.isFinite(netMargin) ? `${formatSignedPercent(netMargin)}` : Number.isFinite(roe) ? `${formatSignedPercent(roe)}` : langText.signalNoData;
  const marginSub = [
    Number.isFinite(roe) ? `ROE ${formatSignedPercent(roe)}` : "",
    Number.isFinite(roa) ? `ROA ${formatSignedPercent(roa)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  const balanceSheet = data.ifrs_snapshot?.balance_sheet || {};
  const riskScore = Number(data.metrics?.altman_z_score?.score ?? data.ifrs_snapshot?.quality?.altman?.score);
  const debtToEquity = Number(balanceSheet.debt_to_equity);
  const currentRatio = Number(balanceSheet.current_ratio);
  let riskTone = "neutral";
  let riskValue = langText.signalNoData;
  if (Number.isFinite(riskScore)) {
    if (riskScore > 2.99) {
      riskTone = "good";
      riskValue = langText.signalUp;
    } else if (riskScore > 1.81) {
      riskTone = "warning";
      riskValue = langText.signalFlat;
    } else {
      riskTone = "danger";
      riskValue = langText.signalDown;
    }
  } else if (Number.isFinite(debtToEquity) || Number.isFinite(currentRatio)) {
    if (Number.isFinite(debtToEquity) && debtToEquity <= 0.8 && Number.isFinite(currentRatio) && currentRatio >= 1.3) {
      riskTone = "good";
      riskValue = langText.signalUp;
    } else if (Number.isFinite(debtToEquity) && debtToEquity >= 2) {
      riskTone = "danger";
      riskValue = langText.signalDown;
    } else {
      riskTone = "warning";
      riskValue = langText.signalFlat;
    }
  }

  renderMiniSignal(els.revenueSignal?.closest(".mini-market-card"), els.revenueSignal, els.revenueSignalSub, {
    value: formatCompactNumber(latest.revenue),
    sub: revenueChange === null ? langText.signalNoData : `${langText.signalTrend} ${formatSignedPercent(revenueChange)} · ${langText.signalLatest} ${latest.year}`,
    tone: revenueTone,
  });
  renderMiniSignal(els.marginSignal?.closest(".mini-market-card"), els.marginSignal, els.marginSignalSub, {
    value: marginValue,
    sub: marginSub || langText.signalNoData,
    tone: marginTone,
  });
  renderMiniSignal(els.riskSignal?.closest(".mini-market-card"), els.riskSignal, els.riskSignalSub, {
    value: riskValue,
    sub: [
      Number.isFinite(riskScore) ? `Altman ${formatRatio(riskScore, 2)}` : "",
      Number.isFinite(debtToEquity) ? `D/E ${formatRatio(debtToEquity, 2)}` : "",
      Number.isFinite(currentRatio) ? `CR ${formatRatio(currentRatio, 2)}` : "",
    ]
      .filter(Boolean)
      .join(" · ") || langText.signalNoData,
    tone: riskTone,
  });
}

function getFavoriteTickers(profile = state.profile) {
  const favorites = Array.isArray(profile?.favorites) ? profile.favorites : [];
  return new Set(
    favorites
      .map((item) => String(item?.ticker || "").trim().toUpperCase())
      .filter(Boolean)
  );
}

function isTickerFavorite(ticker, profile = state.profile) {
  if (!ticker) return false;
  return getFavoriteTickers(profile).has(String(ticker).trim().toUpperCase());
}

function renderAvatarInto(el, user) {
  if (!el) return;
  const avatar = user?.avatar_data_url;
  const initials = getProfileInitials(user);
  if (avatar) {
    el.classList.add("has-image");
    el.innerHTML = `<img src="${escapeHtml(avatar)}" alt="${escapeHtml(user?.full_name || user?.email || t("profile.noTitle"))}" />`;
    return;
  }
  el.classList.remove("has-image");
  el.innerHTML = "";
  el.textContent = initials;
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error(t("profile.readImageError")));
    reader.readAsDataURL(file);
  });
}

function setProfileEditorEnabled(enabled) {
  if (!els.profileEditForm) return;
  els.profileEditForm.querySelectorAll("input, button").forEach((control) => {
    control.disabled = !enabled;
  });
}

function renderProfile(profile = null) {
  state.profile = profile;

  if (
    !els.profileStatus ||
    !els.profileAvatar ||
    !els.profileName ||
    !els.profileEmail ||
    !els.profileMemberSince ||
    !els.profileStats ||
    !els.profileRecent ||
    !els.profileFavorites
  ) {
    return;
  }

  if (!profile || !state.user) {
    els.profileStatus.textContent = t("profile.statusNotLoaded");
    els.profileStatus.className = "status-badge muted";
    renderAvatarInto(els.profileAvatar, null);
    els.profileAvatar.style.background = "linear-gradient(135deg, rgba(245, 184, 77, 0.18), rgba(110, 240, 193, 0.16))";
    els.profileName.textContent = t("profile.unavailable");
    els.profileEmail.textContent = t("profile.emailHint");
    els.profileMemberSince.textContent = t("profile.memberSince");
    els.profileStats.classList.add("empty-state");
    els.profileStats.innerHTML = `<p class="empty-copy">${escapeHtml(t("profile.statsEmpty"))}</p>`;
    els.profileRecent.classList.add("empty-state");
    els.profileRecent.innerHTML = `<p class="empty-copy">${escapeHtml(t("profile.historyEmpty"))}</p>`;
    els.profileFavorites.classList.add("empty-state");
    els.profileFavorites.innerHTML = `<p class="empty-copy">${escapeHtml(t("profile.favoritesEmpty"))}</p>`;
    if (els.profileHistorySummary) {
      els.profileHistorySummary.textContent = "";
    }
    if (els.profileEditForm) {
      els.profileEditForm.reset();
    }
    state.profileAvatarCleared = false;
    setProfileEditorEnabled(false);
    renderResultFavoriteButton();
    return;
  }

  const user = profile.user || state.user;
  const stats = profile.stats || {};
  const recent = Array.isArray(profile.recent_analyses) ? profile.recent_analyses : [];
  const favorites = Array.isArray(profile.favorites) ? profile.favorites : [];
  const favoritesByTicker = getFavoriteTickers(profile);
  const initials = getProfileInitials(user);
  const hue = hashToHue(user.email || user.full_name || user.id);
  const accent = `hsl(${hue} 78% 62%)`;
  const accentSoft = `hsla(${hue}, 78%, 62%, 0.18)`;

  els.profileStatus.textContent = t("profile.statusLoaded");
  els.profileStatus.className = "status-badge";
  renderAvatarInto(els.profileAvatar, user);
  if (!user.avatar_data_url) {
    els.profileAvatar.style.background = `linear-gradient(135deg, ${accent}, ${accentSoft})`;
  } else {
    els.profileAvatar.style.background = "#09111d";
  }
  els.profileName.textContent = user.full_name || user.email;
  els.profileEmail.textContent = user.email;
  els.profileMemberSince.textContent = t("profile.memberSinceWithDate", { date: formatDateLabel(user.created_at) });

  if (els.profileEditForm) {
    if (els.profileFullName && document.activeElement !== els.profileFullName) {
      els.profileFullName.value = user.full_name || "";
    }
    if (els.profileEditHint) {
      els.profileEditHint.textContent = t("profile.editHint");
    }
  }
  state.profileAvatarCleared = false;
  setProfileEditorEnabled(true);

  const statsCards = [
    { label: t("profile.stats.totalAnalyses"), value: stats.total_analyses ?? 0, sub: t("profile.stats.totalAnalysesSub") },
    { label: t("profile.stats.analyses7d"), value: stats.analyses_7d ?? 0, sub: t("profile.stats.analyses7dSub") },
    { label: t("profile.stats.analyses30d"), value: stats.analyses_30d ?? 0, sub: t("profile.stats.analyses30dSub") },
    { label: t("profile.stats.analyzedCompanies"), value: stats.analyzed_companies ?? 0, sub: t("profile.stats.analyzedCompaniesSub") },
    { label: t("profile.stats.avgScore"), value: stats.avg_score != null ? Number(stats.avg_score).toFixed(1) : "—", sub: t("profile.stats.avgScoreSub") },
    { label: t("profile.stats.bestScore"), value: stats.best_score != null ? Number(stats.best_score).toFixed(1) : "—", sub: t("profile.stats.bestScoreSub") },
    {
      label: t("profile.stats.topCompany"),
      value: stats.top_company || "—",
      sub: stats.top_company_count ? t("profile.stats.topCompanySub", { count: stats.top_company_count }) : t("profile.stats.topCompanySubEmpty"),
    },
    {
      label: t("profile.stats.cachedAnalyses"),
      value: stats.cached_analyses ?? 0,
      sub: t("profile.stats.cachedAnalysesSub"),
    },
    {
      label: t("profile.stats.lastAnalysis"),
      value: stats.last_analysis_at ? formatDateLabel(stats.last_analysis_at) : "—",
      sub: t("profile.stats.lastAnalysisSub"),
    },
  ];

  els.profileStats.classList.remove("empty-state");
  els.profileStats.innerHTML = statsCards
    .map(
      (item) => `
        <article class="profile-stat-card">
          <div class="metric-label">${escapeHtml(item.label)}</div>
          <div class="profile-stat-value">${escapeHtml(item.value)}</div>
          <div class="metric-sub">${escapeHtml(item.sub)}</div>
        </article>
      `
    )
    .join("");

  if (!recent.length) {
    els.profileRecent.classList.add("empty-state");
    els.profileRecent.innerHTML = `<p class="empty-copy">${escapeHtml(t("profile.historyEmpty"))}</p>`;
  } else {
    const searchValue = String(els.profileHistorySearch?.value || "").trim().toLowerCase();
    const mode = String(els.profileHistoryMode?.value || "all");
    const filteredRecent = recent.filter((item) => {
      const haystack = [
        item.company_name,
        item.company_input,
        item.ticker,
        item.verdict,
        item.summary_text,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (searchValue && !haystack.includes(searchValue)) {
        return false;
      }
      if (mode === "favorites") {
        return isTickerFavorite(item.ticker, profile);
      }
      return true;
    });

    if (els.profileHistorySummary) {
      const totalLabel = state.language === "en"
        ? `${filteredRecent.length} of ${recent.length}`
        : state.language === "uz"
          ? `${filteredRecent.length} / ${recent.length}`
          : `${filteredRecent.length} из ${recent.length}`;
      const favoriteLabel = favorites.length
        ? state.language === "en"
          ? ` · ${favorites.length} in favorites`
          : state.language === "uz"
            ? ` · ${favorites.length} tanlangan`
            : ` · ${favorites.length} в избранном`
        : "";
      els.profileHistorySummary.textContent = `${t("profile.historySummaryPrefix")} ${totalLabel}${favoriteLabel}`;
    }

    if (!filteredRecent.length) {
      els.profileRecent.classList.add("empty-state");
      els.profileRecent.innerHTML = `<p class="empty-copy">${escapeHtml(t("profile.historyFilteredEmpty"))}</p>`;
    } else {
      els.profileRecent.classList.remove("empty-state");
      els.profileRecent.innerHTML = filteredRecent
        .map((item) => {
          const title = item.company_name || item.company_input || t("profile.noTitle");
          const modelPrefix = state.language === "en" ? "model" : state.language === "uz" ? "model" : "модель";
          const subtitle = [item.ticker ? item.ticker : "", item.from_cache ? t("profile.historyFromCache") : t("profile.historyFresh"), item.model ? `${modelPrefix} ${item.model}` : ""]
            .filter(Boolean)
            .join(" · ");
          const favorite = item.ticker && favoritesByTicker.has(String(item.ticker).trim().toUpperCase());
          return `
            <article class="profile-history-item fade-in">
              <div class="profile-history-main">
                <div>
                  <div class="profile-history-title">${escapeHtml(title)}</div>
                  <div class="profile-history-sub">${escapeHtml(item.verdict || item.summary_text || t("profile.historyAnalysisDone"))}</div>
                </div>
                <div class="profile-history-score">${escapeHtml(item.score != null ? String(item.score) : "—")}</div>
              </div>
              <div class="profile-history-meta">
                <span>${escapeHtml(subtitle)}</span>
                <span>${escapeHtml(formatDateLabel(item.created_at))}</span>
              </div>
              <div class="profile-history-actions">
                <button
                  class="ghost-btn history-favorite-btn"
                  type="button"
                  data-ticker="${escapeHtml(item.ticker || "")}"
                  data-company-name="${escapeHtml(item.company_name || item.company_input || "")}"
                >${favorite ? t("profile.historyFavoriteRemove") : t("profile.historyFavoriteAdd")}</button>
              </div>
            </article>
          `;
        })
        .join("");
    }
  }

  if (!favorites.length) {
    els.profileFavorites.classList.add("empty-state");
    els.profileFavorites.innerHTML = `<p class="empty-copy">${escapeHtml(t("profile.favoritesEmpty"))}</p>`;
  } else {
    els.profileFavorites.classList.remove("empty-state");
    els.profileFavorites.innerHTML = favorites
      .map((item) => {
        const label = item.company_name || item.ticker;
        return `
          <article class="favorite-item fade-in">
            <div class="favorite-item-main">
              <div class="favorite-item-title">${escapeHtml(label || t("profile.noTitle"))}</div>
              <div class="favorite-item-sub">${escapeHtml(item.ticker || "—")} · ${escapeHtml(formatDateLabel(item.created_at))}</div>
            </div>
            <button
              class="ghost-btn favorite-toggle-btn"
              type="button"
              data-ticker="${escapeHtml(item.ticker || "")}"
              data-company-name="${escapeHtml(item.company_name || "")}"
            >${t("profile.favoritesRemove")}</button>
          </article>
        `;
      })
      .join("");
  }

  if (els.profileHistorySearch || els.profileHistoryMode) {
    document.querySelectorAll(".history-favorite-btn, .favorite-toggle-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        toggleFavoriteFromButton(btn.dataset.ticker, btn.dataset.companyName);
      });
    });
  }

  renderResultFavoriteButton();
}

async function loadProfile() {
  if (!state.token) {
    renderProfile(null);
    return;
  }

  if (!els.profileStatus) return;

  els.profileStatus.textContent = state.language === "en" ? "Loading profile..." : state.language === "uz" ? "Profil yuklanmoqda..." : "Загрузка профиля...";
  els.profileStatus.className = "status-badge muted";

  try {
    const res = await apiFetch("/api/profile");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || (state.language === "en" ? "Could not load profile" : state.language === "uz" ? "Profil yuklanmadi" : "Не удалось загрузить профиль"));
    renderProfile(data);
  } catch (error) {
    renderProfile(null);
    els.profileStatus.textContent = t("profile.unavailable");
    setMessage(error.message, "error");
  }
}

function setView(viewName) {
  els.navButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === viewName);
  });
  els.views.forEach((view) => {
    view.classList.toggle("active", view.id === `view-${viewName}`);
  });
}

function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) {
    headers.set("Authorization", `Bearer ${state.token}`);
  }
  if (!(options.body instanceof FormData) && !headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${API_BASE}${path}`, { ...options, headers });
}

async function handleAuthResponse(res) {
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || (state.language === "en" ? "Request failed" : state.language === "uz" ? "So'rov bajarilmadi" : "Запрос не выполнен"));
  }
  if (data.token) {
    state.token = data.token;
    localStorage.setItem(STORAGE_KEY, data.token);
  }
  if (data.user) {
    setAuthState(data.user);
  }
  return data;
}

function clearResults() {
  if (loadingSkeletonTimer) {
    window.clearTimeout(loadingSkeletonTimer);
    loadingSkeletonTimer = null;
  }
  state.lastResult = null;
  if (els.resultHero) {
    els.resultHero.classList.remove("is-loading");
  }
  setAnalysisChartEmpty();
  if (els.metricsGrid) {
    els.metricsGrid.classList.add("empty-state");
    els.metricsGrid.innerHTML = `<p class="empty-copy">${escapeHtml(t("analysis.metricsEmpty"))}</p>`;
  }
  if (els.sectionsWrap) {
    els.sectionsWrap.classList.add("empty-state");
    els.sectionsWrap.innerHTML = `<p class="empty-copy">${escapeHtml(t("analysis.sectionsEmpty"))}</p>`;
  }
  renderResultFavoriteButton();
}

function setLoadingSkeleton(company) {
  if (els.resultHero) {
    els.resultHero.classList.add("is-loading");
  }
  if (els.resultCompany) {
    els.resultCompany.textContent = company ? t("analysis.loadingTitle", { company }) : t("analysis.resultRunning");
  }
  if (els.resultCache) {
    els.resultCache.textContent = t("analysis.loadingCache");
  }
  if (els.scoreValue) {
    els.scoreValue.textContent = "--";
  }
  if (els.gradeValue) {
    els.gradeValue.textContent = "—";
  }
  if (els.verdictValue) {
    els.verdictValue.textContent = t("analysis.loadingVerdict");
  }
  if (els.summaryValue) {
    els.summaryValue.textContent = "";
  }
  if (els.chartTitle) {
    els.chartTitle.textContent = getAnalysisLocaleText().chartTitle;
  }
  if (els.chartMeta) {
    els.chartMeta.textContent = t("analysis.loadingCache");
  }
  if (els.analysisChart) {
    els.analysisChart.classList.remove("empty-state");
    els.analysisChart.innerHTML = `
      <div class="chart-skeleton">
        <div class="chart-skeleton-grid">
          <span></span><span></span><span></span><span></span>
        </div>
        <div class="chart-skeleton-wave">
          <span></span><span></span><span></span>
        </div>
      </div>
    `;
  }
  const analysisText = getAnalysisLocaleText();
  if (els.revenueSignal) els.revenueSignal.textContent = "—";
  if (els.revenueSignalSub) els.revenueSignalSub.textContent = analysisText.signalNoData;
  if (els.marginSignal) els.marginSignal.textContent = "—";
  if (els.marginSignalSub) els.marginSignalSub.textContent = analysisText.signalNoData;
  if (els.riskSignal) els.riskSignal.textContent = "—";
  if (els.riskSignalSub) els.riskSignalSub.textContent = analysisText.signalNoData;
  [els.revenueSignal, els.marginSignal, els.riskSignal].forEach((el) => {
    el?.closest(".mini-market-card")?.setAttribute("data-tone", "neutral");
  });

  if (els.metricsGrid) {
    els.metricsGrid.classList.remove("empty-state");
    els.metricsGrid.innerHTML = `
      <div class="skeleton-grid">
        ${Array.from({ length: 8 })
          .map(
            () => `
              <article class="metric-card skeleton-card">
                <div class="skeleton-line skeleton-line-sm"></div>
                <div class="skeleton-line skeleton-line-lg"></div>
                <div class="skeleton-line skeleton-line-md"></div>
              </article>
            `
          )
          .join("")}
      </div>
    `;
  }

  if (els.sectionsWrap) {
    els.sectionsWrap.classList.remove("empty-state");
    els.sectionsWrap.innerHTML = `
      <div class="skeleton-sections">
        ${Array.from({ length: 3 })
          .map(
            () => `
              <article class="section-card skeleton-card">
                <div class="skeleton-line skeleton-line-lg"></div>
                <div class="skeleton-line skeleton-line-md"></div>
                <div class="skeleton-line skeleton-line-sm"></div>
              </article>
            `
          )
          .join("")}
      </div>
    `;
  }
}

function renderMetrics(metrics = {}) {
  const cards = [];

  const toneClass = (tone) => {
    if (tone === "good") return "metric-good";
    if (tone === "danger") return "metric-danger";
    return "metric-warning";
  };

  const pushCard = ({ label, value, sub = "", tone = "warning" }) => {
    if (value === undefined || value === null || value === "") return;
    cards.push(`
      <article class="metric-card fade-in">
        <div class="metric-label">${escapeHtml(label)}</div>
        <div class="metric-value ${toneClass(tone)}">${escapeHtml(value)}</div>
        <div class="metric-sub">${escapeHtml(sub)}</div>
      </article>
    `);
  };

  const total = metrics.total_score || {};
  pushCard({
    label: t("metrics.total_score"),
    value: total.score ?? "—",
    sub: total.summary || total.grade || "",
    tone: total.score >= 70 ? "good" : total.score >= 45 ? "warning" : "danger",
  });

  const piotroski = metrics.piotroski_f_score || {};
  pushCard({
    label: t("metrics.piotroski_f_score"),
    value: `${piotroski.score ?? "—"}/9`,
    sub: piotroski.verdict || "",
    tone: piotroski.score >= 7 ? "good" : piotroski.score >= 4 ? "warning" : "danger",
  });

  const altman = metrics.altman_z_score || {};
  pushCard({
    label: t("metrics.altman_z_score"),
    value: altman.score ?? "—",
    sub: altman.verdict || "",
    tone: altman.score > 2.99 ? "good" : altman.score > 1.81 ? "warning" : "danger",
  });

  const buffett = metrics.buffett_criteria || {};
  pushCard({
    label: t("metrics.buffett_criteria"),
    value: `${buffett.passed ?? "—"}/${buffett.total ?? "—"}`,
    sub: buffett.verdict || "",
    tone: buffett.passed >= 4 ? "good" : buffett.passed >= 2 ? "warning" : "danger",
  });

  const graham = metrics.graham_number || {};
  pushCard({
    label: t("metrics.graham_number"),
    value: graham.graham_number ?? graham.value ?? "—",
    sub: [graham.verdict, graham.upside_pct != null ? `${graham.upside_pct}% ${state.language === "en" ? "upside" : state.language === "uz" ? "o'sish potentsiali" : "потенциал"}` : ""]
      .filter(Boolean)
      .join(" · "),
    tone: graham.upside_pct > 0 ? "good" : "warning",
  });

  const dcf = metrics.dcf || {};
  pushCard({
    label: t("metrics.dcf"),
    value: dcf.intrinsic_value_bn ?? "—",
    sub: dcf.verdict || dcf.signal || "",
    tone: dcf.signal === "bullish" ? "good" : dcf.signal === "bearish" ? "danger" : "warning",
  });

  const industry = metrics.industry || {};
  pushCard({
    label: t("metrics.industry"),
    value: industry.sector_name ?? "—",
    sub: [industry.verdict || "", `${industry.good_count ?? 0} ${state.language === "en" ? "strong" : state.language === "uz" ? "yaxshi" : "сильных"} / ${industry.weak_count ?? 0} ${state.language === "en" ? "weak" : state.language === "uz" ? "zaif" : "слабых"}`]
      .filter(Boolean)
      .join(" · "),
    tone: industry.good_count > industry.weak_count ? "good" : "warning",
  });

  const liquidity = metrics.market_liquidity || {};
  pushCard({
    label: t("metrics.market_liquidity"),
    value: liquidity.liquidity_label ?? "—",
    sub: [
      `${state.language === "en" ? "Trades" : state.language === "uz" ? "Bitimlar" : "Сделки"}: ${liquidity.trade_days ?? "—"}/30`,
      liquidity.avg_trade_value ? `${state.language === "en" ? "Average turnover" : state.language === "uz" ? "O'rtacha aylanma" : "Средний оборот"}: ${Number(liquidity.avg_trade_value).toLocaleString()}` : "",
    ]
      .filter(Boolean)
      .join(" · "),
    tone: liquidity.liquidity_label === "high" ? "good" : "warning",
  });

  if (!cards.length) {
    els.metricsGrid.classList.add("empty-state");
    els.metricsGrid.innerHTML = `<p class="empty-copy">${escapeHtml(t("analysis.metricsEmpty"))}</p>`;
    return;
  }

  els.metricsGrid.classList.remove("empty-state");
  els.metricsGrid.innerHTML = cards.join("");
}

function renderSections(sections = {}) {
  const entries = Object.entries(sections);
  if (!entries.length) {
    els.sectionsWrap.classList.add("empty-state");
    els.sectionsWrap.innerHTML = `<p class="empty-copy">${escapeHtml(t("analysis.sectionsEmpty"))}</p>`;
    return;
  }

  els.sectionsWrap.classList.remove("empty-state");
  els.sectionsWrap.innerHTML = entries
    .map(
      ([key, value], index) => `
        <details class="section-card fade-in" ${index === 0 ? "open" : ""}>
          <summary>
            <span>${escapeHtml(t(`sections.${key}`) || key.replaceAll("_", " "))}</span>
            <span class="muted">#${String(index + 1).padStart(2, "0")}</span>
          </summary>
          <div class="section-content">${escapeHtml(value || (state.language === "en" ? "No content" : state.language === "uz" ? "Mazmun yo'q" : "Нет содержимого"))}</div>
        </details>
      `
    )
    .join("");
}

function renderResult(data) {
  state.lastResult = data;
  if (els.resultHero) {
    els.resultHero.classList.remove("is-loading");
  }
  els.resultCompany.textContent = data.company_name || data.input || t("analysis.resultEmpty");
  els.resultCache.textContent = data.from_cache ? t("analysis.resultCacheHit") : t("analysis.resultFresh");

  const score = data.summary?.score ?? data.metrics?.total_score?.score ?? null;
  const grade = data.summary?.grade ?? data.metrics?.total_score?.grade ?? "-";
  const verdict = data.summary?.verdict ?? "";
  const itog = data.summary?.itog ?? data.summary?.score_summary ?? "";

  els.scoreValue.textContent = score ?? "--";
  els.scoreValue.className = `score-value ${score != null ? renderScoreTone(score) : ""}`;
  els.gradeValue.textContent = grade || "-";
  els.verdictValue.textContent = verdict || t("analysis.verdictPlaceholder");
  els.summaryValue.textContent = itog || "";

  renderAnalysisChart(data);
  renderMetrics(data.metrics || {});
  renderSections(data.sections || {});
  renderResultFavoriteButton();
}

function renderScoreTone(score) {
  if (score >= 70) return "metric-good";
  if (score >= 45) return "metric-warning";
  return "metric-danger";
}

function renderResultFavoriteButton() {
  if (!els.resultFavoriteBtn) return;

  const ticker = state.lastResult?.ticker;
  if (!state.token || !ticker) {
    els.resultFavoriteBtn.disabled = true;
    els.resultFavoriteBtn.textContent = t("analysis.favoriteAdd");
    els.resultFavoriteBtn.classList.remove("is-active");
    return;
  }

  const favorite = isTickerFavorite(ticker);
  els.resultFavoriteBtn.disabled = false;
  els.resultFavoriteBtn.textContent = favorite ? t("analysis.favoriteRemove") : t("analysis.favoriteAdd");
  els.resultFavoriteBtn.classList.toggle("is-active", favorite);
}

async function toggleFavoriteFromButton(ticker, companyName = "") {
  const normalizedTicker = String(ticker || "").trim();
  if (!state.token) {
    showToast(t("auth.messages.authRequired"), "error");
    setView("auth");
    return;
  }
  if (!normalizedTicker) return;

  try {
    const res = await apiFetch("/api/favorites/toggle", {
      method: "POST",
      body: JSON.stringify({
        ticker: normalizedTicker,
        company_name: companyName || undefined,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || (state.language === "en" ? "Could not update favorites" : state.language === "uz" ? "Tanlanganlar yangilanmadi" : "Не удалось обновить избранное"));
    const addedText = state.language === "en"
      ? "added to favorites"
      : state.language === "uz"
        ? "tanlanganlarga qo'shildi"
        : "добавлен в избранное";
    const removedText = state.language === "en"
      ? "removed from favorites"
      : state.language === "uz"
        ? "tanlanganlardan olib tashlandi"
        : "удалён из избранного";
    showToast(data.favorited ? `${normalizedTicker} ${addedText}` : `${normalizedTicker} ${removedText}`, "success");
    await loadProfile();
    renderResultFavoriteButton();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function saveProfileChanges(event) {
  event.preventDefault();
  if (!state.token) {
    showToast(t("auth.messages.authRequired"), "error");
    return;
  }
  if (!els.profileEditForm) return;

  const form = new FormData(els.profileEditForm);
  const nextFullName = String(form.get("full_name") || "").trim();
  const currentFullName = String(state.user?.full_name || "").trim();
  const payload = {};

  if (nextFullName && nextFullName !== currentFullName) {
    payload.full_name = nextFullName;
  }

  const file = els.profileAvatarInput?.files?.[0];
  if (file) {
    payload.avatar_data_url = await readFileAsDataUrl(file);
  } else if (state.profileAvatarCleared) {
    payload.avatar_data_url = null;
  }

  if (!Object.keys(payload).length) {
    showToast(state.language === "en" ? "No changes" : state.language === "uz" ? "O'zgarish yo'q" : "Изменений нет", "info");
    return;
  }

  try {
    const res = await apiFetch("/api/profile", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || (state.language === "en" ? "Could not save profile" : state.language === "uz" ? "Profil saqlanmadi" : "Не удалось сохранить профиль"));
    state.user = data.user;
    setAuthState(data.user);
    state.profileAvatarCleared = false;
    if (els.profileAvatarInput) {
      els.profileAvatarInput.value = "";
    }
    if (els.profileEditHint) {
      els.profileEditHint.textContent = t("profile.savedHint");
    }
    showToast(t("profile.savedHint"), "success");
    await loadProfile();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function loadCompanies() {
  const res = await apiFetch("/api/companies");
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || (state.language === "en" ? "Could not load company list" : state.language === "uz" ? "Kompaniyalar ro'yxati yuklanmadi" : "Не удалось загрузить список компаний"));

  state.companies = data.companies || [];
  els.companyCount.textContent = t("analysis.companyCount", { count: data.count || state.companies.length });

  els.companiesList.innerHTML = state.companies
    .map((company) => `<option value="${company.ticker}">${company.company_name}</option>`)
    .join("");

  els.quickCompanies.innerHTML = state.companies
    .slice(0, 16)
    .map(
      (company) => `
        <button class="quick-chip" type="button" data-company="${company.ticker}">
          ${company.ticker}
        </button>
      `
    )
    .join("");

  document.querySelectorAll("[data-company]").forEach((btn) => {
    btn.addEventListener("click", () => {
      els.companyInput.value = btn.dataset.company;
      els.companyInput.focus();
    });
  });
}

async function refreshSession() {
  if (!state.token) {
    setAuthState(null);
    return;
  }

  try {
    const res = await apiFetch("/api/auth/me");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || (state.language === "en" ? "Session is invalid" : state.language === "uz" ? "Sessiya yaroqsiz" : "Сессия недействительна"));
    setAuthState(data.user);
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    state.token = "";
    setAuthState(null);
  }
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((el) => el.classList.remove("active"));
    document.querySelectorAll(".auth-form").forEach((el) => el.classList.remove("active"));
    btn.classList.add("active");
    const target = btn.dataset.tab;
    document.getElementById(`${target}Form`).classList.add("active");
  });
});

els.navButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    setView(btn.dataset.view);
  });
});

if (els.languageSelect) {
  els.languageSelect.addEventListener("change", () => {
    applyLanguage(els.languageSelect.value);
  });
}

if (els.profileAnalyzeBtn) {
  els.profileAnalyzeBtn.addEventListener("click", () => setView("analysis"));
}

if (els.profileRefreshBtn) {
  els.profileRefreshBtn.addEventListener("click", async () => {
    if (!state.token) {
      showToast(t("auth.messages.authRequired"), "error");
      return;
    }
    await loadProfile();
    showToast(t("profile.savedHint"), "success");
  });
}

if (els.profileEditForm) {
  els.profileEditForm.addEventListener("submit", saveProfileChanges);
}

if (els.profileClearAvatarBtn) {
  els.profileClearAvatarBtn.addEventListener("click", () => {
    state.profileAvatarCleared = true;
    if (els.profileAvatarInput) {
      els.profileAvatarInput.value = "";
    }
    if (els.profileEditHint) {
      els.profileEditHint.textContent = t("profile.clearHint");
    }
    showToast(t("profile.clearHint"), "info");
  });
}

if (els.profileHistorySearch) {
  els.profileHistorySearch.addEventListener("input", () => {
    if (state.profile) {
      renderProfile(state.profile);
    }
  });
}

if (els.profileHistoryMode) {
  els.profileHistoryMode.addEventListener("change", () => {
    if (state.profile) {
      renderProfile(state.profile);
    }
  });
}

if (els.resultFavoriteBtn) {
  els.resultFavoriteBtn.addEventListener("click", () => {
    if (!state.lastResult) return;
    toggleFavoriteFromButton(state.lastResult.ticker, state.lastResult.company_name || state.lastResult.input || "");
  });
}

els.googleLoginBtn.addEventListener("click", () => {
  window.location.href = `${API_BASE}/api/auth/oauth/google/start`;
});

els.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage(t("auth.messages.loggingIn"));
  const form = new FormData(els.loginForm);
  try {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: form.get("email"),
        password: form.get("password"),
      }),
    });
    const data = await handleAuthResponse(res);
    setMessage(t("auth.messages.loginSuccess", { name: data.user.full_name || data.user.email }));
    showToast(t("auth.messages.loginSuccess", { name: data.user.email }), "success");
    setView("profile");
    await loadProfile();
  } catch (error) {
    setMessage(error.message, "error");
    showToast(error.message, "error");
  }
});

els.registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage(t("auth.messages.registering"));
  const form = new FormData(els.registerForm);
  try {
    const res = await fetch(`${API_BASE}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: form.get("email"),
        password: form.get("password"),
        full_name: form.get("full_name"),
      }),
    });
    const data = await handleAuthResponse(res);
    setMessage(t("auth.messages.registerSuccess", { email: data.user.email }));
    showToast(t("auth.messages.registerSuccess", { email: data.user.email }), "success");
    document.querySelector('.tab-btn[data-tab="login"]').click();
    setView("profile");
    await loadProfile();
  } catch (error) {
    setMessage(error.message, "error");
    showToast(error.message, "error");
  }
});

els.logoutBtn.addEventListener("click", async () => {
  try {
    await apiFetch("/api/auth/logout", { method: "POST" });
  } catch {
    // ignore
  }
  localStorage.removeItem(STORAGE_KEY);
  state.token = "";
  setAuthState(null);
  renderProfile(null);
  setMessage(t("auth.messages.signOut"));
  showToast(t("auth.messages.signOut"), "info");
  setView("auth");
});

els.analysisForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (!state.token) {
    setMessage(t("auth.messages.authRequired"), "error");
    showToast(t("auth.messages.authRequired"), "error");
    return;
  }

  const form = new FormData(els.analysisForm);
  const company = String(form.get("company") || "").trim();
  if (!company) {
    setMessage(state.language === "en" ? "Select a company first." : state.language === "uz" ? "Avval kompaniyani tanlang." : "Сначала выберите компанию.", "error");
    showToast(state.language === "en" ? "Select a company first." : state.language === "uz" ? "Avval kompaniyani tanlang." : "Сначала выберите компанию.", "error");
    return;
  }

  els.apiState.textContent = t("analysis.apiLoading");
  setMessage(t("analysis.resultRunning"));
  if (loadingSkeletonTimer) {
    window.clearTimeout(loadingSkeletonTimer);
  }
  loadingSkeletonTimer = window.setTimeout(() => {
    setLoadingSkeleton(company);
    loadingSkeletonTimer = null;
  }, 220);

  try {
    const res = await apiFetch("/api/analyze", {
      method: "POST",
      body: JSON.stringify({
        company,
        language: state.language,
        include_html: els.includeHtml.checked,
        include_raw: false,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || (state.language === "en" ? "Could not complete the analysis" : state.language === "uz" ? "Tahlil bajarilmadi" : "Не удалось выполнить анализ"));
    if (loadingSkeletonTimer) {
      window.clearTimeout(loadingSkeletonTimer);
      loadingSkeletonTimer = null;
    }
    renderResult(data);
    els.apiState.textContent = t("analysis.apiReady");
    setMessage(t("analysis.completed", { company: data.company_name || company }));
    showToast(t("analysis.completed", { company: data.company_name || company }), "success");
    loadProfile().catch(() => {});
  } catch (error) {
    if (loadingSkeletonTimer) {
      window.clearTimeout(loadingSkeletonTimer);
      loadingSkeletonTimer = null;
    }
    els.apiState.textContent = t("analysis.apiReady");
    setMessage(error.message, "error");
    showToast(error.message, "error");
    clearResults();
  }
});

window.addEventListener("DOMContentLoaded", async () => {
  applyLanguage(state.language);
  const oauthReturned = consumeOAuthHash();
  setView("main");
  try {
    await loadCompanies();
  } catch (error) {
    els.companyCount.textContent = state.language === "en" ? "Unavailable" : state.language === "uz" ? "Mavjud emas" : "Недоступно";
    setMessage(error.message, "error");
  }

  await refreshSession();
  await loadProfile();
  if (oauthReturned) {
    setMessage(state.oauthMessage || t("auth.messages.oauthReady"));
    setView("profile");
  } else if (state.user) {
    setView("profile");
  }
  state.oauthMessage = "";
  clearResults();
});

