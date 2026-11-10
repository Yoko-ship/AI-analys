import { fmtInt, fmtStamp, fmtAge } from "./adminModel.js";
import { CollectionRuns } from "./CollectionRuns.jsx";
import { mt } from "../shared/marketCopy.jsx";
export function StreamsSection({
  t,
  streams,
  language,
  tradeValidation,
  apiFetch
}) {
  return <div className="admin-section">
      {tradeValidation?.partial && <p className="product-coverage" role="status">
        {mt(language, "partialRefresh")}: {(tradeValidation.withheld || []).map(r => r.ticker || r.isin).join(", ")}.
        {" "}{mt(language, "partialRefreshDetail")}
      </p>}
      <CollectionRuns apiFetch={apiFetch} t={t} />
      <h3>{t("Свежесть данных", "Ma’lumotlar yangiligi", "Data freshness")}</h3>
      <p className="muted">{t("Последняя запись в таблице — это отдельная проверка, а не результат запуска.", "Jadvaldagi oxirgi yozuv — ishga tushirish natijasi emas, alohida tekshiruv.", "The last table write is a separate check from the outcome of a run.")}</p>
      <div className="panel">
        <div className="admin-scroll">
          <table>
            <thead>
              <tr>
                <th>{t("Поток", "Oqim", "Stream")}</th>
                <th style={{
                width: 190
              }}>{t("Служба", "Xizmat", "Service")}</th>
                <th style={{
                width: 176
              }}>{t("Расписание", "Jadval", "Schedule")}</th>
                <th style={{
                width: 140
              }}>{t("Состояние", "Holat", "State")}</th>
                <th className="r" style={{
                width: 96
              }}>{t("Строк", "Qatorlar", "Rows")}</th>
                <th className="r" style={{
                width: 190
              }}>{t("Последняя запись", "Oxirgi yozuv", "Last write")}</th>
              </tr>
            </thead>
            <tbody>
              {streams.map(stream => <tr key={stream.key}>
                  <td>
                    <div className="admin-rule">{stream.title}</div>
                    <div className="admin-sub"><code>{stream.table}</code></div>
                  </td>
                  <td className="admin-num">{stream.service}</td>
                  <td className="admin-num">{stream.schedule}</td>
                  <td>
                    <span className="admin-pill">
                      <span className={`admin-dot ${stream.state === "fresh" ? "ok" : stream.state === "stale" ? "warn" : ""}`} />
                      {stream.state === "fresh" ? t("Свежий", "Yangi", "Fresh") : stream.state === "stale" ? t("Устарел", "Eskirgan", "Stale") : t("Нет записей", "Yozuv yo'q", "Never written")}
                    </span>
                  </td>
                  <td className="r admin-num">{fmtInt(stream.rows)}</td>
                  <td className="r admin-num">
                    {fmtStamp(stream.last_write)}
                    <div className="admin-sub">{fmtAge(stream.age_hours, t)}</div>
                  </td>
                </tr>)}
            </tbody>
          </table>
        </div>
      </div>
    </div>;
}
