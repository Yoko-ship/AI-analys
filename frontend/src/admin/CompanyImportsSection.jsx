import { Icon } from "./icons.jsx";
import { fmtInt, fmtStamp, companyDraftOf } from "./adminModel.js";
import { Stat } from "./AdminWidgets.jsx";
export function CompanyImportsSection({
  companyImports,
  t,
  companyBusy,
  discoverCompanies,
  previewCompany,
  companyLookup,
  setCompanyLookup,
  companyNotice,
  companyDraft,
  setCompanyDraft,
  approveCompany,
  rejectCompany,
  companyFilter,
  setCompanyFilter,
  loadCompanyImports,
  setCompanyVisibility,
  syncCompany
}) {
  const companyItems = companyImports && companyImports.items || [];
  const companySummary = companyImports && companyImports.summary || {};
  const sectorTitles = {
    finance: t("Финансы", "Moliya", "Finance"),
    manufacturing: t("Промышленность", "Sanoat", "Manufacturing"),
    mining: t("Добыча", "Konchilik", "Mining"),
    transport: t("Транспорт", "Transport", "Transport"),
    logistics: t("Логистика", "Logistika", "Logistics"),
    telecom: t("Телеком", "Telekom", "Telecom"),
    professional: t("Профессиональные услуги", "Professional xizmatlar", "Professional services"),
    trade: t("Торговля", "Savdo", "Trade"),
    funds: t("Фонды", "Fondlar", "Funds"),
    other: t("Прочее", "Boshqa", "Other")
  };
  const syncTitle = value => ({
    queued: t("в очереди", "navbatda", "queued"),
    running: t("синхронизация", "sinxronlash", "syncing"),
    complete: t("готово", "tayyor", "complete"),
    failed: t("ошибка", "xato", "failed")
  })[value] || t("не запускалась", "ishga tushmagan", "not started");
  return <div className="admin-section">
      <div className="admin-stats">
        <Stat label={t("Ждут проверки", "Tekshiruv kutilmoqda", "Awaiting review")} value={fmtInt(companySummary.pending)} warn={Boolean(companySummary.pending)} line1={t("Обнаружены UZSE/OpenInfo", "UZSE/OpenInfo topdi", "Discovered by UZSE/OpenInfo")} />
        <Stat label={t("Опубликованы", "E'lon qilingan", "Published")} value={fmtInt(companySummary.approved)} line1={t("Доступны без деплоя", "Deploysiz mavjud", "Available without a deploy")} />
        <Stat label={t("Отклонены", "Rad etilgan", "Rejected")} value={fmtInt(companySummary.rejected)} line1={t("Сохраняются в журнале", "Jurnalda saqlanadi", "Kept in the audit trail")} />
        <Stat label={t("Без OpenInfo ID", "OpenInfo ID yo'q", "Missing OpenInfo ID")} value={fmtInt(companyImports && companyImports.unresolved)} warn={Boolean(companyImports && companyImports.unresolved)} line1={t("Нельзя публиковать", "E'lon qilib bo'lmaydi", "Cannot be published")} />
      </div>

      <div className="panel admin-company-intake">
        <div className="admin-panel-head">
          <div>
            <h2>{t("Импортировать компанию", "Kompaniyani import qilish", "Import a company")}</h2>
            <p className="admin-muted admin-note">
              {t("Введите тикер — название, ISIN и эмитент будут взяты из UZSE и OpenInfo.", "Tickerni kiriting — nom, ISIN va emitent UZSE va OpenInfo'dan olinadi.", "Enter a ticker; name, ISIN, and issuer are read from UZSE and OpenInfo.")}
            </p>
          </div>
          <button type="button" className="admin-btn" disabled={Boolean(companyBusy)} onClick={discoverCompanies}>
            <Icon name={companyBusy === "discover" ? "clock" : "refresh"} />
            {companyBusy === "discover" ? t("Проверяем источники…", "Manbalar tekshirilmoqda…", "Checking sources…") : t("Найти новые", "Yangilarini topish", "Discover new")}
          </button>
        </div>
        <form className="admin-company-lookup" onSubmit={event => {
        event.preventDefault();
        previewCompany(companyLookup, true);
      }}>
          <label>
            <span>{t("Тикер", "Ticker", "Ticker")}</span>
            <input
              className="admin-input"
              value={companyLookup}
              onChange={event => setCompanyLookup(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
              placeholder="UZTL"
              maxLength={40}
            />
          </label>
          <button type="submit" className="admin-btn accent" disabled={!companyLookup || Boolean(companyBusy)}>
            <Icon name={companyBusy.startsWith("preview:") ? "clock" : "search"} />
            {t("Проверить OpenInfo", "OpenInfo'ni tekshirish", "Check OpenInfo")}
          </button>
        </form>
        {companyNotice ? <div className="admin-company-notice"><span className="admin-dot ok" />{companyNotice}</div> : null}
      </div>

      {companyDraft ? <div className="panel admin-company-review">
          <div className="admin-panel-head">
            <div>
              <div className="panel-label">{t("Предпросмотр источника", "Manba ko'rinishi", "Source preview")}</div>
              <h2>{companyDraft.ticker} · {companyDraft.company_name || t("Без названия", "Nomsiz", "Unnamed")}</h2>
            </div>
            <span className="admin-pill">
              <span className={`admin-dot ${companyDraft.org_id ? "ok" : "err"}`} />
              {companyDraft.org_id ? `OpenInfo ${companyDraft.org_id}` : t("OpenInfo не найден", "OpenInfo topilmadi", "OpenInfo unresolved")}
            </span>
          </div>

          {companyDraft.warnings.length ? <div className="admin-company-warnings">
              {companyDraft.warnings.map(warning => <span key={warning}><span className="admin-dot warn" />{warning}</span>)}
            </div> : null}

          <div className="admin-company-form">
            <label className="wide"><span>{t("Официальное название", "Rasmiy nomi", "Official name")}</span>
              <input value={companyDraft.company_name} onChange={event => setCompanyDraft({
            ...companyDraft,
            company_name: event.target.value
          })} /></label>
            <label><span>{t("OpenInfo org ID", "OpenInfo org ID", "OpenInfo org ID")}</span>
              <input value={companyDraft.org_id} onChange={event => setCompanyDraft({
            ...companyDraft,
            org_id: event.target.value
          })} /></label>
            <label><span>ISIN</span>
              <input value={companyDraft.isin} onChange={event => setCompanyDraft({
            ...companyDraft,
            isin: event.target.value.toUpperCase()
          })} /></label>
            <label><span>{t("Сектор", "Sektor", "Sector")}</span>
              <select value={companyDraft.sector} onChange={event => setCompanyDraft({
            ...companyDraft,
            sector: event.target.value
          })}>
                {Object.entries(sectorTitles).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select></label>
            <label><span>{t("Тип бумаги", "Qog'oz turi", "Security type")}</span>
              <select value={companyDraft.security_type} onChange={event => setCompanyDraft({
            ...companyDraft,
            security_type: event.target.value
          })}>
                <option value="stock">{t("Акция", "Aksiya", "Stock")}</option>
                <option value="bond">{t("Облигация", "Obligatsiya", "Bond")}</option>
                <option value="fund">{t("Фонд", "Fond", "Fund")}</option>
                <option value="other">{t("Прочее", "Boshqa", "Other")}</option>
              </select></label>
            <label className="wide"><span>{t("Логотип из OpenInfo", "OpenInfo logotipi", "OpenInfo logo")}</span>
              <div className="admin-company-logo-field">
                {companyDraft.logo_url ? <img src={companyDraft.logo_url} alt="" /> : <span className="admin-company-logo-empty">{companyDraft.ticker.slice(0, 2)}</span>}
                <input value={companyDraft.logo_url} onChange={event => setCompanyDraft({
              ...companyDraft,
              logo_url: event.target.value
            })} placeholder="https://…" />
              </div></label>
            <label className="wide"><span>{t("Причина ручной коррекции", "Qo'lda tuzatish sababi", "Reason for a manual correction")}</span>
              <textarea rows="3" value={companyDraft.review_note} onChange={event => setCompanyDraft({
            ...companyDraft,
            review_note: event.target.value
          })} placeholder={t("Оставьте пустым, если данные источника верны", "Manba to'g'ri bo'lsa bo'sh qoldiring", "Leave blank when the source is correct")} /></label>
          </div>

          <div className="admin-company-actions">
            <button type="button" className="admin-btn accent" disabled={!companyDraft.org_id || Boolean(companyBusy)} onClick={approveCompany}>
              <Icon name={companyBusy.startsWith("approve:") ? "clock" : "check"} />
              {companyDraft.status === "approved" ? t("Сохранить и синхронизировать", "Saqlash va sinxronlash", "Save and synchronize") : t("Опубликовать и синхронизировать", "E'lon qilish va sinxronlash", "Publish and synchronize")}
            </button>
            {companyDraft.status !== "approved" ? <button type="button" className="admin-btn danger" disabled={Boolean(companyBusy)} onClick={() => rejectCompany(companyDraft)}>
                {t("Отклонить", "Rad etish", "Reject")}
              </button> : null}
            <button type="button" className="admin-btn" onClick={() => setCompanyDraft(null)}>
              {t("Закрыть", "Yopish", "Close")}
            </button>
          </div>
        </div> : null}

      <div className="panel">
        <div className="admin-panel-bar">
          <div className="admin-seg">
            {["pending", "approved", "rejected", "all"].map(status => <button type="button" key={status} aria-selected={companyFilter === status} onClick={() => setCompanyFilter(status)}>
                {status === "pending" ? t("На проверке", "Tekshiruvda", "Pending") : status === "approved" ? t("Опубликованы", "E'lon qilingan", "Published") : status === "rejected" ? t("Отклонены", "Rad etilgan", "Rejected") : t("Все", "Barchasi", "All")}
                {status !== "all" ? <span className="n">{fmtInt(companySummary[status])}</span> : null}
              </button>)}
          </div>
          <span className="admin-sp" />
          <button type="button" className="admin-btn sm" onClick={() => loadCompanyImports(companyFilter)} disabled={Boolean(companyBusy)}>
            <Icon name="refresh" />{t("Обновить", "Yangilash", "Refresh")}
          </button>
        </div>
        <div className="admin-scroll">
          <table className="admin-company-table">
            <thead><tr>
              <th>{t("Компания", "Kompaniya", "Company")}</th>
              <th>{t("Идентификаторы", "Identifikatorlar", "Identifiers")}</th>
              <th>{t("Разрешение", "Moslik", "Resolution")}</th>
              <th>{t("В каталоге", "Katalogda", "In catalog")}</th>
              <th>{t("Синхронизация", "Sinxronlash", "Synchronization")}</th>
              <th className="r">{t("Действие", "Amal", "Action")}</th>
            </tr></thead>
            <tbody>
              {!companyItems.length ? <tr><td colSpan={6}><div className="admin-empty"><b>{t("Список пуст", "Ro'yxat bo'sh", "Nothing here")}</b>{companyFilter === "pending" ? t("Запустите поиск новых компаний.", "Yangi kompaniyalarni qidiring.", "Run discovery to find new companies.") : ""}</div></td></tr> : null}
              {companyItems.map(item => <tr key={item.ticker}>
                  <td><div className="admin-rule"><code>{item.ticker}</code>{item.company_name}</div><div className="admin-sub">{sectorTitles[item.sector] || item.sector}</div></td>
                  <td className="admin-num"><b>{item.isin || "—"}</b><div className="admin-sub">OpenInfo {item.org_id || "—"}</div></td>
                  <td><span className="admin-pill"><span className={`admin-dot ${item.org_id ? "ok" : "err"}`} />{item.resolved_by || t("не найдено", "topilmadi", "unresolved")}</span></td>
                  <td>
                    {item.status === "approved" ? <label className="admin-catalog-toggle" title={t("Показывать компанию в публичном каталоге", "Kompaniyani ochiq katalogda ko'rsatish", "Show company in the public catalog")}>
                        <input type="checkbox" checked={item.catalog_visible !== 0} disabled={Boolean(companyBusy)} onChange={event => setCompanyVisibility(item, event.target.checked)} />
                        <span>{item.catalog_visible !== 0 ? t("Показана", "Ko'rsatilgan", "Visible") : t("Скрыта", "Yashirilgan", "Hidden")}</span>
                      </label> : <span className="admin-sub">—</span>}
                  </td>
                  <td><span className="admin-pill" title={item.sync_error || item.catalog_sync_error || ""}><span className={`admin-dot ${item.sync_status === "complete" ? "ok" : item.sync_status === "failed" ? "err" : item.sync_status ? "warn" : ""}`} />{syncTitle(item.sync_status)}</span><div className="admin-sub">{fmtStamp(item.catalog_last_synced_at)}</div></td>
                  <td className="r"><div className="admin-company-row-actions">
                    <button type="button" className="admin-btn sm" disabled={Boolean(companyBusy)} onClick={() => {
                    setCompanyDraft(companyDraftOf(item));
                    setCompanyLookup(item.ticker);
                  }}>{item.status === "approved" ? t("Изменить", "O'zgartirish", "Edit") : t("Проверить", "Tekshirish", "Review")}</button>
                    {item.status === "approved" ? <button type="button" className="admin-btn sm" disabled={Boolean(companyBusy)} onClick={() => syncCompany(item.ticker)}>{t("Синхр.", "Sinxr.", "Sync")}</button> : null}
                  </div></td>
                </tr>)}
            </tbody>
          </table>
        </div>
      </div>
    </div>;
}
