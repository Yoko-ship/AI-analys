export function RulesSection({
  t,
  ruleBook
}) {
  return <div className="admin-section">
      <div className="panel">
        <h3>{t("Граница ответственности", "Javobgarlik chegarasi", "The boundary")}</h3>
        <div className="admin-cols2">
          <div>
            <div className="panel-label">{t("Через панель", "Panel orqali", "Through the panel")}</div>
            <ul className="admin-list">
              {(ruleBook && ruleBook.boundary && ruleBook.boundary.panel || []).map(x => <li key={x}>{x}</li>)}
            </ul>
          </div>
          <div>
            <div className="panel-label">{t("Через PR с прогоном валидаций", "PR orqali", "Through a pull request")}</div>
            <ul className="admin-list">
              {(ruleBook && ruleBook.boundary && ruleBook.boundary.code || []).map(x => <li key={x}>{x}</li>)}
            </ul>
          </div>
        </div>
        <p className="admin-muted admin-note">{ruleBook && ruleBook.boundary && ruleBook.boundary.why}</p>
      </div>

      <div className="panel">
        <h3>{t("Пороги и диапазоны", "Chegara va oraliqlar", "Thresholds and ranges")}</h3>
        <div className="admin-table">
          <table>
            <thead>
              <tr>
                <th>{t("Параметр", "Parametr", "Parameter")}</th>
                <th className="n">{t("Значение", "Qiymat", "Value")}</th>
                <th>{t("Где задан", "Qayerda", "Owner")}</th>
                <th>{t("Что делает", "Nima qiladi", "What it does")}</th>
              </tr>
            </thead>
            <tbody>
              {(ruleBook && ruleBook.thresholds || []).map(r => <tr key={r.name}>
                  <td>{r.name}</td>
                  <td className="n">{String(r.value)}</td>
                  <td className="admin-muted">{r.owner}</td>
                  <td className="admin-muted">{r.note || "—"}</td>
                </tr>)}
            </tbody>
          </table>
        </div>
      </div>
    </div>;
}
