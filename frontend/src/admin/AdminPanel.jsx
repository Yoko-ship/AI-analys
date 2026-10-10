import { Icon, IconSprite } from "./icons.jsx";
import "./admin.css";
import { useEffect } from "react";
import { lang3, SECTIONS, SYSTEM_SECTIONS, ADMIN_SECTION_KEYS } from "./adminModel.js";
import { Skeleton } from "./AdminWidgets.jsx";
import { FeedbackSection } from "./FeedbackSection.jsx";
import { IssuerLedgerSection } from "./IssuerLedgerSection.jsx";
import { StreamsSection } from "./StreamsSection.jsx";
import { CompanyImportsSection } from "./CompanyImportsSection.jsx";
import { UsersSection } from "./UsersSection.jsx";
import { AnalysisUsageSection } from "./AnalysisUsageSection.jsx";
import { EngagementSection } from "./EngagementSection.jsx";
import { AudienceSection } from "./AudienceSection.jsx";
import { ProductOverviewSection } from "./ProductOverviewSection.jsx";
import { useAdminData } from "./useAdminData.js";
export default function AdminPanel({
  apiFetch,
  language = "ru",
  section: requestedSection = "overview",
  onSectionChange
}) {
  // Old links (/admin/documents, /admin/audit, …) point at screens that no
  // longer exist; they land on the overview instead of an empty body.
  // «Система» itself is a group, not a screen: it opens on its first sub-tab.
  const section = requestedSection === "system" ? SYSTEM_SECTIONS[0].key
    : ADMIN_SECTION_KEYS.includes(requestedSection) ? requestedSection : "overview";
  useEffect(() => {
    if (section !== requestedSection && onSectionChange) onSectionChange(section);
  }, [section, requestedSection, onSectionChange]);
  const {
    t,
    isSystem,
    metrics,
    audienceData,
    engagementData,
    analysisData,
    rangeDays,
    setRangeDays,
    usersData,
    funnel,
    adminLog,
    usersQuery,
    setUsersQuery,
    usersOnly,
    setUsersOnly,
    userDetail,
    setUserDetail,
    confirmAction,
    setConfirmAction,
    feedbackData,
    feedbackFilter,
    setFeedbackFilter,
    feedbackBusy,
    overview,
    ledger,
    ledgerTicker,
    setLedgerTicker,
    companyImports,
    companyLookup,
    setCompanyLookup,
    companyFilter,
    setCompanyFilter,
    companyDraft,
    setCompanyDraft,
    companyNotice,
    companyBusy,
    error,
    loading,
    busy,
    loadUsers,
    updateFeedbackStatus,
    openUser,
    runUserAction,
    loadCompanyImports,
    discoverCompanies,
    previewCompany,
    approveCompany,
    rejectCompany,
    syncCompany,
    setCompanyVisibility,
    loadLedger,
    streams,
    staleStreams,
    activeTab
  } = useAdminData({
    language,
    section,
    apiFetch,
    onSectionChange
  });

  /* product half */

  // {id, action}

  /* operations half */

  // React Strict Mode replays effect setup/cleanup once in development. Reset
  // the guard in setup so that replay does not leave this mounted panel
  // permanently "dead" and discard every API response.

  /* ── loads: product ─────────────────────────────────────────────────────── */

  /* ── loads: operations ──────────────────────────────────────────────────── */

  // The rule book is public and cacheable; a failure there must not blank the page.

  const SECTION_LEDE = {
    overview: t("Сколько людей открыло сайт сегодня, живёт ли аудитория и работает ли продукт — прежде чем смотреть на таблицы.", "Bugun saytni nechta odam ochgani va mahsulot ishlayotgani.", "How many people opened the site today, whether the audience is alive and the product is used — before the plumbing."),
    audience: t("Кто приходит: сколько, откуда, на чём и на каком языке. Ответ на буквальный вопрос «сколько человек открыло сайт».", "Kim kelmoqda: qancha, qayerdan va qaysi tilda.", "Who comes: how many, from where, on what device and in which language."),
    engagement: t("Что они на самом деле смотрят: страницы, бумаги, новости. Топ бумаг — самая коммерчески интересная таблица панели.", "Ular aslida nimani ko'rmoqda: sahifalar, qog'ozlar, yangiliklar.", "What they actually look at: pages, tickers, stories. The ticker ranking is the most commercially interesting table here."),
    analysis: t("Кто запускает AI-анализ, что анализируют и во сколько это обходится. Доля кэша — это напрямую счёт за LLM.", "Kim AI-tahlil ishga tushiradi va bu qancha turadi.", "Who runs the AI analysis, what they analyse and what it costs. The cache share is directly the LLM bill."),
    users: t("Зарегистрированные: список, воронка от визита до возврата, безопасные действия поддержки и их постоянный журнал.", "Ro'yxatdan o'tganlar: ro'yxat, voronka, xavfsiz amallar va ularning jurnali.", "Registered users: the visit-to-return funnel, safe support actions and their durable audit trail."),
    feedback: t("Отзывы и обращения пользователей. Сообщения видны только администраторам и остаются привязанными к аккаунту для ответа.", "Foydalanuvchi fikrlari va murojaatlari. Xabarlarni faqat administratorlar ko'radi.", "User feedback and support requests. Messages are visible only to administrators and remain linked to an account for follow-up."),
    companies: t("Новые бумаги приходят с UZSE и OpenInfo автоматически. Здесь администратор проверяет точное соответствие эмитента и публикует компанию без правки кода.", "Yangi qog'ozlar UZSE va OpenInfo'dan avtomatik keladi; administrator ularni tekshiradi va e'lon qiladi.", "New securities arrive automatically from UZSE and OpenInfo. Review the issuer match here and publish without a code change."),
    streams: t("Показана последняя запись в таблице, которую пишет служба, а не её код возврата: сборщики работают отдельными сервисами и в этот процесс не отчитываются.", "Xizmat yozadigan jadvaldagi oxirgi yozuv ko'rsatilgan.", "The last write in the table each service fills, not its exit code: the collectors run as separate services and do not report here."),
    issuer: t("Расчёт разложен построчно: каждое слагаемое двенадцатимесячной базы со своим периодом и знаком, капитализация по классам, остатки, из которых берутся знаменатели, и все прошедшие проверки.", "Hisob-kitob qatorma-qator yoyilgan.", "The calculation laid out line by line: every component of the twelve-month base with its period and sign, the capitalisation by class, the balances the denominators come from."),
  };

  /* labels shared by the product bodies */
  const VIEW_LABELS = {
    main: t("Главная", "Bosh sahifa", "Home"),
    market: t("Рынок", "Bozor", "Market"),
    company: t("Карточка компании", "Kompaniya sahifasi", "Company page"),
    chart: t("График", "Grafik", "Chart"),
    bond: t("Облигация", "Obligatsiya", "Bond"),
    news: t("Новости", "Yangiliklar", "News"),
    newsArticle: t("Новость", "Yangilik", "Story"),
    heatmap: t("Карта рынка", "Bozor xaritasi", "Heat map"),
    catalog: t("Каталог отчётов", "Hisobotlar katalogi", "Reports catalog"),
    bankfx: t("Курсы банков", "Bank kurslari", "Bank FX"),
    analysis: t("AI-анализ", "AI-tahlil", "AI analysis"),
    compare: t("Сравнение", "Taqqoslash", "Compare"),
    profile: t("Профиль", "Profil", "Profile"),
    auth: t("Вход", "Kirish", "Sign in"),
    "(other)": t("Прочее", "Boshqa", "Other")
  };
  const DEVICE_LABELS = {
    mobile: t("Телефон", "Telefon", "Mobile"),
    tablet: t("Планшет", "Planshet", "Tablet"),
    desktop: t("Компьютер", "Kompyuter", "Desktop"),
    "(unknown)": t("Неизвестно", "Noma'lum", "Unknown")
  };
  const KIND_LABELS = {
    direct: t("прямые", "to'g'ridan-to'g'ri", "direct"),
    search: t("поиск", "qidiruv", "search"),
    social: t("соцсети", "ijtimoiy", "social"),
    referral: t("переход", "havola", "referral"),
    internal: t("внутренний", "ichki", "internal")
  };
  const LANG_LABELS = {
    ru: "Русский",
    uz: "O'zbekcha",
    en: "English",
    "(unknown)": t("Не выбран", "Tanlanmagan", "Not chosen")
  };

  /* ══════════════════════════════════════════════════════════════════════════
     PRODUCT · Обзор
     ════════════════════════════════════════════════════════════════════════ */
  const overviewBody = <ProductOverviewSection metrics={metrics} t={t} overview={overview} streams={streams} staleStreams={staleStreams} />;

  // The product overview also wants the two operations numbers above; load them
  // lazily once the section is open so the screen never blocks on them.

  /* ══════════════════════════════════════════════════════════════════════════
     PRODUCT · Аудитория
     ════════════════════════════════════════════════════════════════════════ */
  const audienceBody = <AudienceSection
    audienceData={audienceData}
    rangeDays={rangeDays}
    setRangeDays={setRangeDays}
    t={t}
    KIND_LABELS={KIND_LABELS}
    DEVICE_LABELS={DEVICE_LABELS}
    LANG_LABELS={LANG_LABELS}
  />;

  /* ══════════════════════════════════════════════════════════════════════════
     PRODUCT · Вовлечённость
     ════════════════════════════════════════════════════════════════════════ */
  const engagementBody = <EngagementSection engagementData={engagementData} rangeDays={rangeDays} setRangeDays={setRangeDays} t={t} VIEW_LABELS={VIEW_LABELS} />;

  /* ══════════════════════════════════════════════════════════════════════════
     PRODUCT · AI-анализ
     ════════════════════════════════════════════════════════════════════════ */
  const analysisBody = <AnalysisUsageSection analysisData={analysisData} rangeDays={rangeDays} setRangeDays={setRangeDays} t={t} />;

  /* ══════════════════════════════════════════════════════════════════════════
     PRODUCT · Пользователи
     ════════════════════════════════════════════════════════════════════════ */
  const usersBody = <UsersSection
    t={t}
    usersData={usersData}
    userDetail={userDetail}
    adminLog={adminLog}
    confirmAction={confirmAction}
    busy={busy}
    setConfirmAction={setConfirmAction}
    runUserAction={runUserAction}
    funnel={funnel}
    usersQuery={usersQuery}
    setUsersQuery={setUsersQuery}
    loadUsers={loadUsers}
    usersOnly={usersOnly}
    setUsersOnly={setUsersOnly}
    openUser={openUser}
    setUserDetail={setUserDetail}
  />;


  /* ── Система · Компании (OpenInfo import review) ─────────────────────── */
  const companiesBody = <CompanyImportsSection
    companyImports={companyImports}
    t={t}
    companyBusy={companyBusy}
    discoverCompanies={discoverCompanies}
    previewCompany={previewCompany}
    companyLookup={companyLookup}
    setCompanyLookup={setCompanyLookup}
    companyNotice={companyNotice}
    companyDraft={companyDraft}
    setCompanyDraft={setCompanyDraft}
    approveCompany={approveCompany}
    rejectCompany={rejectCompany}
    companyFilter={companyFilter}
    setCompanyFilter={setCompanyFilter}
    loadCompanyImports={loadCompanyImports}
    setCompanyVisibility={setCompanyVisibility}
    syncCompany={syncCompany}
  />;
  const streamsBody = <StreamsSection t={t} streams={streams} />;


  /* ── Система · Эмитент (the TTM ledger) ─────────────────────────────────── */
  const issuerBody = <IssuerLedgerSection t={t} ledgerTicker={ledgerTicker} setLedgerTicker={setLedgerTicker} loadLedger={loadLedger} ledger={ledger} />;

  const feedbackBody = <FeedbackSection
    feedbackData={feedbackData}
    t={t}
    feedbackFilter={feedbackFilter}
    setFeedbackFilter={setFeedbackFilter}
    feedbackBusy={feedbackBusy}
    updateFeedbackStatus={updateFeedbackStatus}
  />;
  const bodyBySection = {
    overview: overviewBody,
    audience: audienceBody,
    engagement: engagementBody,
    analysis: analysisBody,
    users: usersBody,
    feedback: feedbackBody,
    companies: companiesBody,
    streams: streamsBody,
    issuer: issuerBody,
  };
  return <div className="admin-view">
      <IconSprite />

      <div className="admin-head">
        <div className="admin-head-copy">
          <div className="panel-label">{t("Служебное", "Xizmat", "Internal")}</div>
          <h1>{t("Администрирование", "Administratsiya", "Administration")}</h1>
          <p>{SECTION_LEDE[section] || SECTION_LEDE.overview}</p>
        </div>
      </div>

      <nav className="admin-tabs">
        {SECTIONS.map(item => {
        const active = activeTab === item.key;
        return <button
          key={item.key}
          type="button"
          className={`admin-tab${active ? " active" : ""}`}
          aria-current={active ? "page" : undefined}
          onClick={() => onSectionChange && onSectionChange(item.key)}
        >
              <Icon name={item.icon} />
              {item.title[lang3(language)]}
            </button>;
      })}
      </nav>

      {isSystem ? <div className="admin-subtabs">
          <div className="admin-seg">
            {SYSTEM_SECTIONS.map(item => <button key={item.key} type="button" aria-selected={section === item.key} onClick={() => onSectionChange && onSectionChange(item.key)}>
                {item.title[lang3(language)]}
              </button>)}
          </div>
        </div> : null}

      {error ? <div className="admin-error" style={{
      marginBottom: 16
    }}>{error}</div> : null}
      {loading ? <Skeleton rows={4} /> : bodyBySection[section] || overviewBody}
    </div>;
}
