import { useMemo } from "react";
import { fmtInt } from "./adminModel.js";
import { Stat } from "./AdminWidgets.jsx";
export function IntakeSection({
  intake,
  intakeState,
  t,
  setIntakeState,
  setLedgerTicker,
  loadLedger,
  onSectionChange
}) {
  const intakeRows = useMemo(() => {
    const items = intake && intake.items || [];
    return intakeState === "all" ? items : items.filter(r => r.state === intakeState);
  }, [intake, intakeState]);
  const STATE_TITLE = {
    used: t("в расчёте", "hisobda", "in the calculation"),
    superseded: t("вытеснена свежей", "yangisi bilan almashtirilgan", "superseded"),
    ineligible: t("не допущена", "qabul qilinmagan", "ineligible")
  };
  return <div className="admin-section">
      <div className="admin-stats">
        <Stat label={t("Записей отчётности", "Hisobot yozuvlari", "Statement records")} value={fmtInt(intake && intake.count)} line1={intake ? t(`${fmtInt(intake.issuers)} эмитентов`, `${fmtInt(intake.issuers)} emitent`, `${fmtInt(intake.issuers)} issuers`) : null} />
        <Stat label={t("Легли в расчёт", "Hisobga kirdi", "Used")} value={fmtInt(intake && intake.used)} line1={t("по одной на эмитента", "har emitentga bittadan", "one per issuer")} />
        <Stat label={t("Вытеснены свежей", "Almashtirilgan", "Superseded")} value={fmtInt(intake && intake.superseded)} line1={t("нормальное состояние, не дефект", "normal holat", "normal, not a defect")} />
        <Stat label={t("Не допущены к расчёту", "Qabul qilinmagan", "Ineligible")} value={fmtInt(intake && intake.ineligible)} warn={!!(intake && intake.ineligible)} line1={t("отбрасываются молча — здесь видно", "jimgina tashlab yuboriladi", "dropped silently — visible here")} />
      </div>

      {intake && intake.by_flag && intake.by_flag.length ? <div className="panel admin-flagbar">
          {intake.by_flag.map(f => <span key={f.flag} className="admin-pill"><span className="admin-dot warn" />{f.title}: {fmtInt(f.count)}</span>)}
        </div> : null}

      <div className="panel">
        <div className="admin-filters">
          {["ineligible", "used", "superseded", "all"].map(key => <button key={key} type="button" className={`admin-btn sm${intakeState === key ? " accent" : ""}`} onClick={() => setIntakeState(key)}>
              {key === "all" ? t("Все записи", "Barchasi", "All") : STATE_TITLE[key]}
            </button>)}
          <span className="admin-sp" />
          <span className="admin-muted">{t(`Показано ${intakeRows.length}`, `${intakeRows.length} ta`, `Showing ${intakeRows.length}`)}</span>
        </div>
        <div className="admin-table">
          <table>
            <thead>
              <tr>
                <th>{t("Эмитент", "Emitent", "Issuer")}</th>
                <th>{t("Форма", "Shakl", "Form")}</th>
                <th>{t("Период", "Davr", "Period")}</th>
                <th className="n">{t("Мес.", "Oy", "Mo")}</th>
                <th className="n">{t("Выручка", "Tushum", "Revenue")}</th>
                <th className="n">{t("Прибыль", "Foyda", "Profit")}</th>
                <th className="n">{t("Активы", "Aktivlar", "Assets")}</th>
                <th>{t("Состояние", "Holat", "State")}</th>
                <th>{t("Отметки", "Belgilar", "Flags")}</th>
              </tr>
            </thead>
            <tbody>
              {!intakeRows.length ? <tr>
                  <td colSpan={9} className="admin-muted" style={{
                padding: "24px 0",
                textAlign: "center"
              }}>
                    {intakeState === "ineligible" ? t("Ни одна запись не отброшена — весь приём дошёл до расчёта.", "Hech bir yozuv tashlab yuborilmagan.", "No record was dropped — the whole intake reached the calculation.") : t("Записей нет.", "Yozuvlar yo'q.", "No records.")}
                  </td>
                </tr> : null}
              {intakeRows.slice(0, 400).map((r, i) => <tr key={`${r.ticker}-${r.year}-${r.quarter}-${i}`}>
                  <td>
                    <button type="button" className="admin-link" onClick={() => {
                  setLedgerTicker(r.ticker);
                  loadLedger(r.ticker);
                  onSectionChange && onSectionChange("issuer");
                }}>
                      {r.ticker}
                    </button>
                  </td>
                  <td className="admin-muted">{r.org_type || r.form || "—"}</td>
                  <td>{r.period || "—"}</td>
                  <td className="n">{r.months == null ? "—" : r.months}</td>
                  <td className="n">{r.revenue == null ? "—" : fmtInt(r.revenue)}</td>
                  <td className="n">{r.net_income == null ? "—" : fmtInt(r.net_income)}</td>
                  <td className="n">{r.total_assets == null ? "—" : fmtInt(r.total_assets)}</td>
                  <td>
                    <span className="admin-pill">
                      <span className={`admin-dot ${r.state === "ineligible" ? "err" : r.state === "used" ? "ok" : ""}`} />
                      {STATE_TITLE[r.state]}
                    </span>
                  </td>
                  <td className="admin-muted">
                    {r.flags.length ? r.flags.map(f => (intake.by_flag.find(x => x.flag === f) || {}).title || f).join(" · ") : "—"}
                  </td>
                </tr>)}
            </tbody>
          </table>
        </div>
        {intakeRows.length > 400 ? <div className="admin-table-foot">
            <span>{t(`Показаны первые 400 из ${intakeRows.length}`, `${intakeRows.length} tadan birinchi 400 tasi`, `First 400 of ${intakeRows.length}`)}</span>
          </div> : null}
      </div>
      <p className="admin-muted admin-note">
        {t("Суммы — в тысячах сум, как они хранятся: экран печатает то, что лежит в базе, а не то, на что делит витрина. «Не допущена» означает, что путь чтения отбрасывает запись в SQL и до расчёта она не доходит.", "Summalar ming so'mda, bazada saqlanganidek.", "Sums are in thousands of UZS, as stored: the screen prints what is in the database, not what the market screen divides by.")}
      </p>
    </div>;
}
