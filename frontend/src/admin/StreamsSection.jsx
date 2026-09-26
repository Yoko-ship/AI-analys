import { fmtInt, fmtStamp, fmtAge } from "./adminModel.js";
export function StreamsSection({
  t,
  streams
}) {
  return <div className="admin-section">
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
