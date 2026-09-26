import "./admin.css";
import { DASH } from "./adminModel.js";
import { fmtInt } from "./adminModel.js";
import { fmtNum } from "./adminModel.js";

export function QualitySection({ quality, qualitySelectedTicker, qualityCorrections, t, setQualityDraft, setQualityBusy, setError, readJson, alive, qualityTicker, setQualityTicker, setQualitySelectedTicker, setQualitySuggestionsOpen, qualitySuggestions, qualitySuggestionsOpen, qualitySearchLoading, qualityBusy, refreshQualityCompanyReporting, scanQualityCompany, qualityNotice, qualityDraft, submitQualityCorrection, fixIssuerMapping, autoApplyUnitScale, autoApplyQualityIssue, reviewQualityCorrection }) {
const qualityIssueRecords = quality?.items || [];

const qualityOpenIssues = qualityIssueRecords.filter(item => item.status === "open");

const qualityIssues = qualitySelectedTicker
    ? qualityOpenIssues.filter((item) => (item.issuer_tickers || [item.ticker])
      .some((ticker) => String(ticker).toUpperCase() === qualitySelectedTicker))
    : qualityOpenIssues;

const qualityCorrectionsRows = qualityCorrections?.items || [];

const qualityIssuerNames = Object.fromEntries(qualityIssueRecords.map(item => [item.ticker, item.issuer_name || item.ticker]));

const fixedQualityCompanies = Object.values(qualityCorrectionsRows
    .filter(record => record.status === "approved")
    .reduce((groups, record) => {
      const key = `${record.ticker}:${record.year}:${record.quarter || 0}`;
      const group = groups[key] || {
        key, ticker: record.ticker, issuerName: qualityIssuerNames[record.ticker] || record.ticker,
        year: record.year, quarter: record.quarter || 0, fields: [], reviewedAt: record.reviewed_at || record.created_at,
      };
      group.fields.push(record.field);
      if (String(record.reviewed_at || record.created_at || "") > String(group.reviewedAt || "")) group.reviewedAt = record.reviewed_at || record.created_at;
      groups[key] = group;
      return groups;
    }, {}))
    .sort((a, b) => String(b.reviewedAt || "").localeCompare(String(a.reviewedAt || "")))
    .slice(0, 6);

const qualityIssueExplanation = (issue) => {
    const details = issue.details && typeof issue.details === "object" ? issue.details : {};
    const values = details.observed_values || {};
    if (issue.rule_code === "BALANCE_MISMATCH" && ["total_assets", "total_equity", "total_liabilities"].every(key => values[key] !== null && values[key] !== undefined)) {
      const difference = Number(details.difference_thousands_uzs ?? (Number(values.total_assets) - Number(values.total_equity) - Number(values.total_liabilities)));
      const direction = difference > 0
        ? t("Активы больше суммы капитала и обязательств", "Aktivlar kapital va majburiyatlar yig'indisidan katta", "Assets exceed equity plus liabilities")
        : t("Активы меньше суммы капитала и обязательств", "Aktivlar kapital va majburiyatlar yig'indisidan kichik", "Assets are below equity plus liabilities");
      return t(`Активы: ${fmtNum(values.total_assets)}; капитал: ${fmtNum(values.total_equity)}; обязательства: ${fmtNum(values.total_liabilities)} тыс. UZS. ${direction} на ${fmtNum(Math.abs(difference))} тыс. UZS.`,
        `Aktivlar: ${fmtNum(values.total_assets)}; kapital: ${fmtNum(values.total_equity)}; majburiyatlar: ${fmtNum(values.total_liabilities)} ming UZS. Farq: ${fmtNum(Math.abs(difference))} ming UZS.`,
        `Assets: ${fmtNum(values.total_assets)}; equity: ${fmtNum(values.total_equity)}; liabilities: ${fmtNum(values.total_liabilities)} thousand UZS. Difference: ${fmtNum(Math.abs(difference))} thousand UZS.`);
    }
    if (issue.rule_code === "MISSING_FINANCIAL_FIELD") return t(`В распознанном отчёте нет значения поля «${issue.field}».`, `Tanib olingan hisobotda «${issue.field}» maydoni qiymati yo'q.`, `The parsed filing has no value for “${issue.field}”.`);
    if (issue.rule_code === "UNRESOLVED_ISSUER") return t("Для тикера не найдена привязка к эмитенту.", "Tiker uchun emitent bog'lanishi topilmadi.", "No issuer mapping was found for this ticker.");
    if (issue.rule_code === "MISSING_FINANCIAL_COVERAGE") return t("В каталоге нет финансового отчёта NSBU.", "Katalogda NSBU moliyaviy hisoboti yo'q.", "No NSBU financial record is available in the catalog.");
    if (issue.rule_code === "MISSING_REPORT_COVERAGE") return t("К тикеру не прикреплён исходный отчёт.", "Tikerga manba hisoboti biriktirilmagan.", "No source report is linked to this ticker.");
    return String(details.message || t("Требуется проверка источника.", "Manbani tekshirish kerak.", "Source verification is required."));
  };

const beginCorrection = (issue = {}) => setQualityDraft({
    ticker: issue.ticker || "", form: issue.form || "NSBU", year: issue.year || new Date().getFullYear(),
    quarter: issue.quarter || 0, field: issue.field || "", value_thousands_uzs: "",
    source_url: "", source_reference: "", reason: "", evidenceMissing: true,
  });

const openSuggestedCorrection = async (issue) => {
    const busyKey = `suggest:${issue.id}`;
    setQualityBusy(busyKey); setError("");
    try {
      const proposal = await readJson(`/api/admin/data-quality/issues/${encodeURIComponent(issue.id)}/suggestion`);
      const recommended = proposal.recommended;
      const evidence = proposal.evidence || {};
      setQualityDraft({
        ticker: issue.ticker || "", form: issue.form || "NSBU", year: issue.year || new Date().getFullYear(),
        quarter: issue.quarter || 0, field: recommended?.field || issue.field || "",
        value_thousands_uzs: recommended ? String(recommended.value_thousands_uzs) : "",
        source_url: evidence.source_url || "", source_reference: evidence.source_reference || "",
        reason: proposal.reason || "", suggestion: proposal.message || "", evidenceMissing: !evidence.available,
        alternatives: proposal.alternatives || [],
      });
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  };

const qualityCompanyUrl = (issue) => {
    const params = new URLSearchParams({
      tab: "financials", freq: "quarterly", qualityIssue: String(issue.rule_code || ""),
      qualityPeriod: issue.year ? `${issue.year}Q${issue.quarter || 4}` : "",
      qualityField: String(issue.field || ""),
    });
    return `/company/${encodeURIComponent(issue.ticker)}?${params.toString()}`;
  };

return (<div className="admin-section">
      <div className="panel admin-panel-head">
        <div><h2>{t("Очередь качества данных", "Ma'lumotlar sifati navbati", "Data-quality queue")}</h2>
          <p className="admin-muted" style={{ margin: "4px 0 0" }}>{t("Выберите компанию: «Обновить отчёты» повторно импортирует официальный источник, «Исправить» меняет только проверенное значение с записью в журнале.", "Kompaniyani tanlang: «Hisobotlarni yangilash» rasmiy manbani qayta import qiladi, «Tuzatish» esa faqat tekshirilgan qiymatni jurnalga yozib o'zgartiradi.", "Choose a company: “Refresh reports” re-imports the official source; “Correct” changes only a verified value with an audit record.")}</p></div>
        <div className="admin-head-actions"><div className="admin-quality-picker"><input className="admin-input" value={qualityTicker} onChange={e => { setQualityTicker(e.target.value); setQualitySelectedTicker(""); setQualitySuggestionsOpen(true); }} onFocus={() => qualityTicker.trim() && setQualitySuggestionsOpen(true)} onKeyDown={(event) => { if (event.key === "Enter" && qualitySuggestions[0]) { event.preventDefault(); const match = qualitySuggestions[0]; setQualityTicker(match.ticker); setQualitySelectedTicker(match.ticker); setQualitySuggestionsOpen(false); } }} placeholder={t("Тикер или компания", "Tiker yoki kompaniya", "Ticker or company")} aria-label={t("Поиск компании", "Kompaniya qidiruvi", "Company search")} autoComplete="off" />
          {qualitySuggestionsOpen && (qualitySearchLoading || qualitySuggestions.length > 0) && <div className="admin-quality-suggestions" role="listbox">{qualitySearchLoading && <div className="admin-quality-search-state">{t("Поиск…", "Qidirilmoqda…", "Searching…")}</div>}{qualitySuggestions.map(company => <button type="button" role="option" key={company.ticker} onMouseDown={event => event.preventDefault()} onClick={() => { setQualityTicker(company.ticker); setQualitySelectedTicker(company.ticker); setQualitySuggestionsOpen(false); }}><b>{company.ticker}</b><span>{company.company_name || company.ticker}</span></button>)}</div>}</div>
          <button type="button" className="admin-btn accent" disabled={!qualitySelectedTicker || qualityBusy === `refresh:${qualitySelectedTicker}`} onClick={() => refreshQualityCompanyReporting(qualitySelectedTicker)}>{qualityBusy === `refresh:${qualitySelectedTicker}` ? t("Обновление отчётов…", "Hisobotlar yangilanmoqda…", "Refreshing reports…") : t("Обновить отчёты", "Hisobotlarni yangilash", "Refresh reports")}</button><button type="button" className="admin-btn" disabled={!qualitySelectedTicker || qualityBusy === `analysis:${qualitySelectedTicker}`} onClick={() => scanQualityCompany(qualitySelectedTicker)}>{qualityBusy === `analysis:${qualitySelectedTicker}` ? t("Проверка…", "Tekshirilmoqda…", "Checking…") : t("Проверить компанию", "Kompaniyani tekshirish", "Check company")}</button><button type="button" className="admin-btn" onClick={() => beginCorrection()}>{t("Новое исправление", "Yangi tuzatish", "New correction")}</button>
        </div>
      </div>
      {qualityNotice && <div className="admin-quality-fixed" role="status"><div className="admin-quality-fixed-title">✓ {t("Официальные данные обновлены", "Rasmiy ma'lumotlar yangilandi", "Official data refreshed")}</div><div>{qualityNotice}</div></div>}

      {qualityDraft && <form className="panel admin-company-form" onSubmit={submitQualityCorrection}>
        <div className="admin-panel-head"><div><h2>{t("Черновик исправления", "Tuzatish qoralamasi", "Correction draft")}</h2><p className="admin-muted">{qualityDraft.evidenceMissing ? t("Для этого периода в каталоге нет ссылки на официальный отчёт — добавьте её вручную.", "Bu davr uchun katalogda rasmiy hisobot havolasi yo'q — uni qo'lda qo'shing.", "No official-report link is stored for this period; add one manually.") : t("Значение, источник и обоснование подставлены автоматически. При необходимости их можно изменить.", "Qiymat, manba va asos avtomatik to'ldirildi. Zarur bo'lsa, o'zgartirish mumkin.", "Value, source and rationale were filled automatically. You can edit them if needed.")}</p></div><button type="button" className="admin-btn" onClick={() => setQualityDraft(null)}>{t("Закрыть", "Yopish", "Close")}</button></div>
        {qualityDraft.suggestion && <div className="admin-note"><b>{t("Автоподсказка — требуется подтверждение", "Avto-taklif — tasdiqlash kerak", "Automatic proposal — confirmation required")}</b><br />{qualityDraft.suggestion}<br /><span className="admin-muted">{t("Поле и значение ниже можно изменить вручную. Официальный источник обязателен.", "Quyidagi maydon va qiymatni qo'lda o'zgartirish mumkin. Rasmiy manba majburiy.", "You can edit the field and value below. Official evidence is still required.")}</span>{qualityDraft.alternatives?.length > 1 && <div className="admin-company-row-actions" style={{ marginTop: 10 }}>{qualityDraft.alternatives.map(option => <button type="button" className="admin-btn" key={option.field} onClick={() => setQualityDraft(old => ({ ...old, field: option.field, value_thousands_uzs: String(option.value_thousands_uzs) }))}>{option.field}: {fmtNum(option.value_thousands_uzs)}</button>)}</div>}</div>}
        {[['ticker', t("Тикер", "Tiker", "Ticker")], ['year', t("Год", "Yil", "Year")], ['quarter', t("Квартал (0=годовой)", "Chorak (0=yillik)", "Quarter (0=annual)")], ['field', t("Поле", "Maydon", "Field")], ['value_thousands_uzs', t("Значение, тыс. UZS", "Qiymat, ming UZS", "Value, thousand UZS")], ['source_url', t("Ссылка на источник", "Manba havolasi", "Evidence URL")], ['source_reference', t("Строка / страница источника", "Manba qatori / sahifasi", "Source line / page")], ['reason', t("Причина", "Sabab", "Reason")]].map(([key, label]) => <label className={['source_url', 'source_reference', 'reason'].includes(key) ? 'wide' : ''} key={key}><span>{label}</span>{key === 'field' ? <select required value={qualityDraft.field} onChange={e => setQualityDraft(old => ({ ...old, field: e.target.value }))}><option value="" disabled>{t("Выберите поле", "Maydonni tanlang", "Choose field")}</option>{['revenue', 'gross_profit', 'cash', 'total_liabilities', 'net_income', 'operating_income', 'total_assets', 'total_equity', 'current_assets', 'current_liabilities', 'inventories'].map(field => <option key={field}>{field}</option>)}</select> : key === 'reason' ? <textarea required value={qualityDraft[key]} onChange={e => setQualityDraft(old => ({ ...old, [key]: e.target.value }))} /> : <input required={key !== 'quarter'} type={['year', 'quarter', 'value_thousands_uzs'].includes(key) ? 'number' : key === 'source_url' ? 'url' : 'text'} step={key === 'value_thousands_uzs' ? 'any' : undefined} value={qualityDraft[key]} onChange={e => setQualityDraft(old => ({ ...old, [key]: e.target.value }))} />}</label>)}
        <div className="admin-company-actions"><button className="admin-btn accent" disabled={qualityBusy === 'create'}>{qualityBusy === 'create' ? t("Исправление…", "Tuzatilmoqda…", "Applying…") : t("Применить исправление", "Tuzatishni qo'llash", "Apply correction")}</button></div>
      </form>}

      {!!fixedQualityCompanies.length && <div className="admin-quality-fixed" role="status">
        <div className="admin-quality-fixed-title">✓ {t("Недавно исправлено", "Yaqinda tuzatildi", "Recently fixed")}</div>
        <div className="admin-quality-fixed-list">{fixedQualityCompanies.map(company => <div className="admin-quality-fixed-item" key={company.key}>
          <b>{company.issuerName}</b> <span className="admin-muted">· {company.ticker} · {company.year}Q{company.quarter || 4}</span>
          <div>{t("Исправлены поля", "Tuzatilgan maydonlar", "Corrected fields")}: {company.fields.join(", ")}. {t("Значения уже используются на сайте.", "Qiymatlar saytda allaqachon qo'llanmoqda.", "The corrected values are already used on the site.")}</div>
        </div>)}</div>
      </div>}

      <div className="panel"><div className="admin-panel-head"><h3>{t("Открытые проверки", "Ochiq tekshiruvlar", "Open checks")} <span className="admin-muted">· {fmtInt(qualityIssues.length)}</span></h3>{qualitySelectedTicker && <div className="admin-company-row-actions"><span className="admin-muted">{t(`Показана компания: ${qualitySelectedTicker}`, `Ko'rsatilgan kompaniya: ${qualitySelectedTicker}`, `Showing company: ${qualitySelectedTicker}`)}</span><button type="button" className="admin-btn" onClick={() => { setQualityTicker(""); setQualitySelectedTicker(""); }}>{t("Сбросить", "Tozalash", "Clear")}</button></div>}</div>
        {!qualityIssues.length ? <div className="admin-empty"><b>{t("Очередь пуста", "Navbat bo'sh", "The queue is empty")}</b>{t("Запустите сканирование после синхронизации каталога.", "Katalog sinxronlangach skanerlashni ishga tushiring.", "Run a scan after catalog synchronization.")}</div> : <div className="admin-scroll"><table><thead><tr><th>{t("Эмитент / тикеры", "Emitent / tikerlar", "Issuer / tickers")}</th><th>{t("Период", "Davr", "Period")}</th><th>{t("Проверка", "Tekshiruv", "Check")}</th><th>{t("Что не так", "Nima noto'g'ri", "What is wrong")}</th><th>{t("Поле", "Maydon", "Field")}</th><th>{t("Приоритет", "Ustuvorlik", "Severity")}</th><th /></tr></thead><tbody>{qualityIssues.map(issue => <tr key={issue.id}><td><b>{issue.issuer_name || issue.ticker}</b><div className="admin-muted">{(issue.issuer_tickers || [issue.ticker]).join(" · ")}</div></td><td>{issue.year ? `${issue.year}Q${issue.quarter || 4}` : DASH}</td><td>{issue.rule_code}</td><td className="admin-muted">{qualityIssueExplanation(issue)}</td><td>{issue.field || DASH}</td><td><span className="admin-pill"><span className={`admin-dot ${issue.severity === 'blocking' ? 'err' : 'warn'}`} />{issue.severity}</span></td><td className="admin-company-row-actions">{issue.details?.source_url && <a className="admin-btn" href={issue.details.source_url} target="_blank" rel="noreferrer">{t("Исходный отчёт", "Asl hisobot", "Source report")}</a>}<a className="admin-btn" href={qualityCompanyUrl(issue)} target="_blank" rel="noreferrer">{t("Открыть на сайте", "Saytda ochish", "Open on site")}</a>{["financials", "coverage"].includes(issue.dataset) && <button type="button" className="admin-btn accent" disabled={qualityBusy === `refresh:${issue.ticker}`} onClick={() => refreshQualityCompanyReporting(issue.ticker)}>{qualityBusy === `refresh:${issue.ticker}` ? t("Обновление…", "Yangilanmoqda…", "Refreshing…") : t("Обновить отчёт", "Hisobotni yangilash", "Refresh report")}</button>}{issue.rule_code === 'UNRESOLVED_ISSUER' && <button type="button" className="admin-btn accent" disabled={qualityBusy === `issuer:${issue.id}`} onClick={() => fixIssuerMapping(issue)}>{qualityBusy === `issuer:${issue.id}` ? t("Открытие…", "Ochilyapti…", "Opening…") : t("Исправить эмитента", "Emitentni tuzatish", "Fix issuer")}</button>}{issue.rule_code === 'BLOCKED_UNIT_MISMATCH' && <button type="button" className="admin-btn accent" disabled={qualityBusy === `scale:${issue.id}`} onClick={() => autoApplyUnitScale(issue)}>{qualityBusy === `scale:${issue.id}` ? t("Исправление…", "Tuzatilmoqda…", "Applying…") : t("Исправить масштаб", "Masshtabni tuzatish", "Fix scale")}</button>}{issue.dataset === 'financials' && <button type="button" className="admin-btn accent" disabled={qualityBusy === `apply:${issue.id}`} onClick={() => autoApplyQualityIssue(issue)}>{qualityBusy === `apply:${issue.id}` ? t("Исправление…", "Tuzatilmoqda…", "Applying…") : t("Исправить", "Tuzatish", "Correct")}</button>}<button type="button" className="admin-btn" disabled={qualityBusy === `analysis:${issue.ticker}`} onClick={() => scanQualityCompany(issue.ticker)}>{qualityBusy === `analysis:${issue.ticker}` ? t("Проверка…", "Tekshirilmoqda…", "Checking…") : t("Проверить компанию", "Kompaniyani tekshirish", "Check company")}</button></td></tr>)}</tbody></table></div>}
      </div>

      <div className="panel"><h3>{t("Журнал исправлений", "Tuzatishlar jurnali", "Correction history")}</h3>
        {!qualityCorrectionsRows.length ? <p className="admin-muted">{t("Пока нет исправлений.", "Hali tuzatishlar yo'q.", "No corrections yet.")}</p> : <div className="admin-scroll"><table><thead><tr><th>{t("Эмитент", "Emitent", "Ticker")}</th><th>{t("Период", "Davr", "Period")}</th><th>{t("Поле", "Maydon", "Field")}</th><th>{t("Статус", "Holat", "Status")}</th><th>{t("Источник", "Manba", "Evidence")}</th><th /></tr></thead><tbody>{qualityCorrectionsRows.map(record => <tr key={record.id}><td>{record.ticker}</td><td>{record.year}Q{record.quarter || 4}</td><td>{record.field}</td><td>{record.status}</td><td><a className="admin-link" href={record.source_url} target="_blank" rel="noreferrer">{record.source_reference}</a></td><td className="admin-company-row-actions">{record.status === 'draft' && <><button className="admin-btn accent" disabled={qualityBusy === record.id} onClick={() => reviewQualityCorrection(record.id, 'approved')}>{t("Подтвердить", "Tasdiqlash", "Approve")}</button><button className="admin-btn" disabled={qualityBusy === record.id} onClick={() => reviewQualityCorrection(record.id, 'rejected')}>{t("Отклонить", "Rad etish", "Reject")}</button></>}{record.status === 'approved' && <button className="admin-btn danger" disabled={qualityBusy === record.id} onClick={() => reviewQualityCorrection(record.id, 'reverted')}>{t("Отменить", "Bekor qilish", "Revert")}</button>}</td></tr>)}</tbody></table></div>}
      </div>
    </div>);
}
