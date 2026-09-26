import { QualitySection } from "./QualitySection.jsx";
import { Icon, IconSprite } from "./icons.jsx";
import RailwayPanel from "./RailwayPanel.jsx";
import "./admin.css";
import { lang3, fmtInt, fmtStamp, SECTIONS, SYSTEM_SECTIONS } from "./adminModel.js";
import { Skeleton } from "./AdminWidgets.jsx";
import { FeedbackSection } from "./FeedbackSection.jsx";
import { SourceSection } from "./SourceSection.jsx";
import { RulesSection } from "./RulesSection.jsx";
import { IssuerLedgerSection } from "./IssuerLedgerSection.jsx";
import { IntakeSection } from "./IntakeSection.jsx";
import { FindingsSection } from "./FindingsSection.jsx";
import { StreamsSection } from "./StreamsSection.jsx";
import { CompanyImportsSection } from "./CompanyImportsSection.jsx";
import { DataHealthSection } from "./DataHealthSection.jsx";
import { UsersSection } from "./UsersSection.jsx";
import { AnalysisUsageSection } from "./AnalysisUsageSection.jsx";
import { EngagementSection } from "./EngagementSection.jsx";
import { AudienceSection } from "./AudienceSection.jsx";
import { ProductOverviewSection } from "./ProductOverviewSection.jsx";
import { useAdminData } from "./useAdminData.js";
export default function AdminPanel({
  apiFetch,
  language = "ru",
  section = "overview",
  onSectionChange
}) {
  const {
    qualityState,
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
    rules,
    findings,
    filters,
    setFilters,
    intake,
    intakeState,
    setIntakeState,
    ledger,
    ledgerTicker,
    setLedgerTicker,
    ruleBook,
    source,
    companyImports,
    companyLookup,
    setCompanyLookup,
    companyFilter,
    setCompanyFilter,
    companyDraft,
    setCompanyDraft,
    companyNotice,
    companyBusy,
    selected,
    error,
    loading,
    busy,
    readJson,
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
    runAudit,
    acceptFindings,
    toggleSelected,
    catalog,
    news,
    streams,
    latest,
    openCounts,
    history,
    queue,
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
    railway: t("Состояние сервисов Railway, ошибки из логов и безопасный перезапуск после сбоя.", "Railway xizmatlari holati, loglardagi xatolar va nosozlikdan keyin xavfsiz qayta ishga tushirish.", "Railway service status, errors from logs, and controlled recovery after a failure."),
    overview: t("Сколько людей открыло сайт сегодня, живёт ли аудитория и работает ли продукт — прежде чем смотреть на таблицы.", "Bugun saytni nechta odam ochgani va mahsulot ishlayotgani.", "How many people opened the site today, whether the audience is alive and the product is used — before the plumbing."),
    audience: t("Кто приходит: сколько, откуда, на чём и на каком языке. Ответ на буквальный вопрос «сколько человек открыло сайт».", "Kim kelmoqda: qancha, qayerdan va qaysi tilda.", "Who comes: how many, from where, on what device and in which language."),
    engagement: t("Что они на самом деле смотрят: страницы, бумаги, новости. Топ бумаг — самая коммерчески интересная таблица панели.", "Ular aslida nimani ko'rmoqda: sahifalar, qog'ozlar, yangiliklar.", "What they actually look at: pages, tickers, stories. The ticker ranking is the most commercially interesting table here."),
    analysis: t("Кто запускает AI-анализ, что анализируют и во сколько это обходится. Доля кэша — это напрямую счёт за LLM.", "Kim AI-tahlil ishga tushiradi va bu qancha turadi.", "Who runs the AI analysis, what they analyse and what it costs. The cache share is directly the LLM bill."),
    users: t("Зарегистрированные: список, воронка от визита до возврата, безопасные действия поддержки и их постоянный журнал.", "Ro'yxatdan o'tganlar: ro'yxat, voronka, xavfsiz amallar va ularning jurnali.", "Registered users: the visit-to-return funnel, safe support actions and their durable audit trail."),
    feedback: t("Отзывы и обращения пользователей. Сообщения видны только администраторам и остаются привязанными к аккаунту для ответа.", "Foydalanuvchi fikrlari va murojaatlari. Xabarlarni faqat administratorlar ko'radi.", "User feedback and support requests. Messages are visible only to administrators and remain linked to an account for follow-up."),
    system: t("Состояние данных: что собрано, что требует решения. Служебная половина панели — один взгляд, когда карточка крона красная.", "Ma'lumotlar holati: nima yig'ilgan, nima qaror kutmoqda.", "The state of the data: what was collected, what needs a decision. The operations half, one look when a cron card goes red."),
    companies: t("Новые бумаги приходят с UZSE и OpenInfo автоматически. Здесь администратор проверяет точное соответствие эмитента и публикует компанию без правки кода.", "Yangi qog'ozlar UZSE va OpenInfo'dan avtomatik keladi; administrator ularni tekshiradi va e'lon qiladi.", "New securities arrive automatically from UZSE and OpenInfo. Review the issuer match here and publish without a code change."),
    streams: t("Показана последняя запись в таблице, которую пишет служба, а не её код возврата: сборщики работают отдельными сервисами и в этот процесс не отчитываются.", "Xizmat yozadigan jadvaldagi oxirgi yozuv ko'rsatilgan.", "The last write in the table each service fills, not its exit code: the collectors run as separate services and do not report here."),
    intake: t("Что конвейер принял на вход. Пока статус записи не виден, любая правка расчёта делается наугад: половина найденных дефектов — не ошибка формулы, а то, какая запись до неё доехала.", "Konveyer nimani qabul qilgani.", "What the pipeline took in. While a record's status is invisible, every fix to the calculation is made blind."),
    issuer: t("Расчёт разложен построчно: каждое слагаемое двенадцатимесячной базы со своим периодом и знаком, капитализация по классам, остатки, из которых берутся знаменатели, и все прошедшие проверки.", "Hisob-kitob qatorma-qator yoyilgan.", "The calculation laid out line by line: every component of the twelve-month base with its period and sign, the capitalisation by class, the balances the denominators come from."),
    source: t("Кто должен был отчитаться, кто отчитался и кто молчит. Просрочка — это факт об эмитенте, а не о нашем сборщике, и тот же список — основа публичного индекса раскрытия.", "Kim hisobot berishi kerak edi, kim berdi va kim jim.", "Who was due to file, who did, and who has gone quiet. Being late is a fact about the issuer, not about our collector."),
    rules: t("Параметры расчёта и граница ответственности: панель задаёт пороги и исключения, код задаёт вычисления.", "Hisob parametrlari va javobgarlik chegarasi.", "The calculation's parameters and the boundary: the panel sets thresholds and exceptions, the code holds the computation."),
    findings: t("Аудитор пересчитывает те же величины независимым путём и сравнивает их с опубликованным. Блокирующая находка снимает число с публикации.", "Auditor qiymatlarni mustaqil qayta hisoblab, e'lon qilingani bilan solishtiradi.", "The auditor recomputes the same quantities by an independent route and compares them with what was published.")
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
  const overviewBody = <ProductOverviewSection metrics={metrics} t={t} overview={overview} streams={streams} staleStreams={staleStreams} openCounts={openCounts} />;

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
  const analysisBody = <AnalysisUsageSection analysisData={analysisData} readJson={readJson} language={language} rangeDays={rangeDays} setRangeDays={setRangeDays} t={t} />;

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

  /* ══════════════════════════════════════════════════════════════════════════
     СИСТЕМА · Данные (the old data overview)
     ════════════════════════════════════════════════════════════════════════ */
  const dataBody = <DataHealthSection
    t={t}
    catalog={catalog}
    openCounts={openCounts}
    news={news}
    streams={streams}
    staleStreams={staleStreams}
    history={history}
    latest={latest}
    queue={queue}
    onSectionChange={onSectionChange}
    rules={rules}
    selected={selected}
    toggleSelected={toggleSelected}
    acceptFindings={acceptFindings}
    busy={busy}
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
  const findingsBody = <FindingsSection
    filters={filters}
    setFilters={setFilters}
    t={t}
    openCounts={openCounts}
    loading={loading}
    findings={findings}
    rules={rules}
    selected={selected}
    toggleSelected={toggleSelected}
    acceptFindings={acceptFindings}
    busy={busy}
  />;

  /* ── Система · Отчёты (intake) ──────────────────────────────────────────── */
  const intakeBody = <IntakeSection
    intake={intake}
    intakeState={intakeState}
    t={t}
    setIntakeState={setIntakeState}
    setLedgerTicker={setLedgerTicker}
    loadLedger={loadLedger}
    onSectionChange={onSectionChange}
  />;

  /* ── Система · Эмитент (the TTM ledger) ─────────────────────────────────── */
  const issuerBody = <IssuerLedgerSection t={t} ledgerTicker={ledgerTicker} setLedgerTicker={setLedgerTicker} loadLedger={loadLedger} ledger={ledger} />;

  /* ── Система · Правила ──────────────────────────────────────────────────── */
  const rulesBody = <RulesSection t={t} ruleBook={ruleBook} />;

  /* ── Система · Источник ─────────────────────────────────────────────────── */
  const sourceBody = <SourceSection source={source} t={t} setLedgerTicker={setLedgerTicker} loadLedger={loadLedger} onSectionChange={onSectionChange} />;
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
    system: dataBody,
    railway: <RailwayPanel readJson={readJson} t={t} />,
    companies: companiesBody,
    streams: streamsBody,
    findings: findingsBody,
    intake: intakeBody,
    issuer: issuerBody,
    rules: rulesBody,
    quality: <QualitySection {...qualityState} t={t} />,
    source: sourceBody
  };
  return <div className="admin-view">
      <IconSprite />

      <div className="admin-head">
        <div className="admin-head-copy">
          <div className="panel-label">{t("Служебное", "Xizmat", "Internal")}</div>
          <h1>{t("Администрирование", "Administratsiya", "Administration")}</h1>
          <p>{SECTION_LEDE[section] || SECTION_LEDE.overview}</p>
        </div>
        {isSystem && section !== "railway" ? <div className="admin-head-actions">
            {latest && latest.finished_at ? <span className="admin-btn" style={{
          pointerEvents: "none"
        }}>
                <Icon name="clock" />
                {fmtStamp(latest.finished_at)}
              </span> : null}
            <button type="button" className="admin-btn accent" disabled={busy} onClick={runAudit}>
              <Icon name={busy ? "clock" : "play"} />
              {busy ? t("Идёт прогон…", "Ishlamoqda…", "Running…") : t("Прогнать аудит", "Auditni ishga tushirish", "Run the audit")}
            </button>
          </div> : null}
      </div>

      <nav className="admin-tabs">
        {SECTIONS.map(item => {
        const active = activeTab === item.key;
        const badge = item.key === "system" && openCounts.blocking ? openCounts.blocking : null;
        return <button
          key={item.key}
          type="button"
          className={`admin-tab${active ? " active" : ""}`}
          aria-current={active ? "page" : undefined}
          onClick={() => onSectionChange && onSectionChange(item.key)}
        >
              <Icon name={item.icon} />
              {item.title[lang3(language)]}
              {badge ? <span className="n hot">{fmtInt(badge)}</span> : null}
            </button>;
      })}
      </nav>

      {isSystem ? <div className="admin-subtabs">
          <div className="admin-seg">
            {SYSTEM_SECTIONS.map(item => <button key={item.key} type="button" aria-selected={section === item.key} onClick={() => onSectionChange && onSectionChange(item.key)}>
                {item.title[lang3(language)]}
                {item.key === "findings" && openCounts.blocking ? <span className="n">{fmtInt(openCounts.blocking)}</span> : null}
              </button>)}
          </div>
        </div> : null}

      {error ? <div className="admin-error" style={{
      marginBottom: 16
    }}>{error}</div> : null}
      {loading && !(isSystem && overview) ? <Skeleton rows={4} /> : bodyBySection[section] || overviewBody}
    </div>;
}
