import { DASH, fmtInt } from "./adminModel.js";
import { Stat } from "./AdminWidgets.jsx";
export function SourceSection({
  source,
  t,
  setLedgerTicker,
  loadLedger,
  onSectionChange
}) {
  const cal = source && source.calendar || null;
  const probe = source && source.probe || null;
  return <div className="admin-section">
      <div className="admin-stats">
        <Stat label={t("Ожидаемый период", "Kutilayotgan davr", "Expected period")} value={cal && cal.expected || DASH} line1={cal ? t(`окно ${cal.window_opens} — ${cal.window_closes}`, `oyna ${cal.window_opens} — ${cal.window_closes}`, `window ${cal.window_opens} — ${cal.window_closes}`) : null} />
        <Stat label={t("Сдали", "Topshirdi", "Filed")} value={fmtInt(cal && cal.filed)} line1={cal ? t(`из ${fmtInt(cal.issuers)} эмитентов`, `${fmtInt(cal.issuers)} tadan`, `of ${fmtInt(cal.issuers)} issuers`) : null} />
        <Stat label={t("Просрочили", "Kechikdi", "Late")} value={fmtInt(cal && cal.late)} warn={!!(cal && cal.late)} line1={cal && cal.overdue_days ? t(`окно закрылось ${cal.overdue_days} дн. назад`, `${cal.overdue_days} kun oldin`, `window closed ${cal.overdue_days} d ago`) : t("окно ещё открыто", "oyna ochiq", "the window is still open")} />
        <Stat label={t("Молчат больше года", "Bir yildan ortiq jim", "Quiet over a year")} value={fmtInt(cal && cal.silent)} warn={!!(cal && cal.silent)} line1={t("это факт об эмитенте", "bu emitent haqidagi fakt", "a fact about the issuer")} />
      </div>

      <div className="panel">
        <h3>{t("Доступность источника", "Manba mavjudligi", "Source availability")}</h3>
        <p className="admin-muted admin-note" style={{
        marginTop: 0
      }}>
          {probe ? `${probe.verdict} · ${t("доступно", "mavjud", "reachable")} ${probe.reachable}, ${t("недоступно", "mavjud emas", "failed")} ${probe.failed}` : t("Проба не выполнялась.", "Sinov bajarilmadi.", "The probe did not run.")}
        </p>
        <div className="admin-table">
          <table>
            <thead>
              <tr>
                <th>{t("Класс запроса", "So'rov sinfi", "Endpoint class")}</th>
                <th className="n">{t("Ответ, мс", "Javob, ms", "Response, ms")}</th>
                <th className="n">{t("Код", "Kod", "Code")}</th>
                <th>{t("Состояние", "Holat", "State")}</th>
              </tr>
            </thead>
            <tbody>
              {(probe && probe.steps || []).map(sres => <tr key={sres.name}>
                  <td className="mono">{sres.name}</td>
                  <td className="n">{fmtInt(sres.elapsed_ms)}</td>
                  <td className="n">{sres.status_code || DASH}</td>
                  <td>
                    <span className="admin-pill" title={sres.error || ""}>
                      <span className={`admin-dot ${sres.ok ? "ok" : "err"}`} />
                      {sres.ok ? t("ок", "ok", "ok") : sres.error ? String(sres.error).slice(0, 48) : t("сбой", "xato", "failed")}
                    </span>
                  </td>
                </tr>)}
            </tbody>
          </table>
        </div>
        <p className="admin-muted admin-note">
          {t("Проба идёт с этого же хоста и тем же клиентом, что и сборщик, — иначе она отвечала бы на другой вопрос. Недоступность одного класса при доступности остальных означает не «openinfo лежит», а что отвалился конкретный эндпоинт.", "Sinov kollektor bilan bir xil xost va mijozdan boradi.", "The probe runs from the same host and with the same client as the collector — otherwise it would be answering a different question.")}
        </p>
      </div>

      <div className="panel">
        <h3>{t("Календарь отчётности", "Hisobot taqvimi", "The reporting calendar")}</h3>
        <div className="admin-table">
          <table>
            <thead>
              <tr>
                <th>{t("Эмитент", "Emitent", "Issuer")}</th>
                <th>{t("Ожидается", "Kutilmoqda", "Expected")}</th>
                <th>{t("Последний поданный", "Oxirgi topshirilgan", "Latest filed")}</th>
                <th className="n">{t("Кварталов позади", "Chorak orqada", "Quarters behind")}</th>
                <th className="n">{t("Просрочка, дн.", "Kechikish, kun", "Overdue, d")}</th>
                <th>{t("Статус", "Holat", "State")}</th>
              </tr>
            </thead>
            <tbody>
              {(cal && cal.items || []).map(r => <tr key={r.ticker}>
                  <td>
                    <button type="button" className="admin-link" onClick={() => {
                  setLedgerTicker(r.ticker);
                  loadLedger(r.ticker);
                  onSectionChange && onSectionChange("issuer");
                }}>
                      {r.ticker}
                    </button>
                  </td>
                  <td>{r.expected}</td>
                  <td>{r.latest}</td>
                  <td className="n">{r.quarters_behind || DASH}</td>
                  <td className="n">{r.overdue_days || DASH}</td>
                  <td>
                    <span className="admin-pill">
                      <span className={`admin-dot ${r.state === "сдан" ? "ok" : r.state === "молчит" ? "err" : r.state === "просрочен" ? "warn" : ""}`} />
                      {r.state}
                    </span>
                  </td>
                </tr>)}
            </tbody>
          </table>
        </div>
        <p className="admin-muted admin-note">
          {t("Окно раскрытия открывается на 25-й день после закрытия квартала и держится 45 дней. Пока оно открыто, отсутствие отчёта — «ожидается», а не «просрочен»: между «ещё не подал» и «перестал подавать» разница принципиальная, и складывать их в одну кучу значит прятать второе за первым.", "Oshkoralik oynasi chorak yopilgandan 25 kun keyin ochiladi va 45 kun turadi.", "The disclosure window opens on the 25th day after the quarter closes and runs 45 days. While it is open, a missing report is «expected», not «late».")}
        </p>
      </div>
    </div>;
}
