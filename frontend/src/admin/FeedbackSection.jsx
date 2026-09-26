import { fmtStamp } from "./adminModel.js";
export function FeedbackSection({
  feedbackData,
  t,
  feedbackFilter,
  setFeedbackFilter,
  feedbackBusy,
  updateFeedbackStatus
}) {
  const feedbackRows = feedbackData?.items || [];
  const feedbackStatusLabel = status => ({
    open: t("Новое", "Yangi", "New"),
    in_progress: t("В работе", "Jarayonda", "In progress"),
    resolved: t("Закрыто", "Yopilgan", "Resolved")
  })[status] || status;
  return <div className="admin-section">
      <div className="panel">
        <div className="admin-panel-head">
          <div><h2>{t("Входящие сообщения", "Kiruvchi xabarlar", "Incoming messages")}</h2>
            <p className="admin-muted" style={{
            margin: "4px 0 0"
          }}>{t("Отзывы, идеи и обращения из формы «Обратная связь».", "Fikrlar, g'oyalar va murojaatlar.", "Feedback, ideas, and requests sent through the Feedback form.")}</p></div>
          <div className="admin-seg">
            {[["", t("Все", "Barchasi", "All")], ["open", t("Новые", "Yangi", "New")], ["in_progress", t("В работе", "Jarayonda", "In progress")], ["resolved", t("Закрытые", "Yopilgan", "Resolved")]].map(([key, label]) => <button key={key || "all"} type="button" aria-selected={feedbackFilter === key} onClick={() => setFeedbackFilter(key)}>{label}</button>)}
          </div>
        </div>
        {!feedbackRows.length ? <div className="admin-empty">{t("Сообщений пока нет.", "Hozircha xabarlar yo'q.", "No feedback yet.")}</div> : <div className="admin-scroll"><table><thead><tr>
            <th style={{
                width: 155
              }}>{t("Когда", "Vaqt", "When")}</th>
            <th style={{
                width: 220
              }}>{t("Пользователь", "Foydalanuvchi", "User")}</th>
            <th>{t("Сообщение", "Xabar", "Message")}</th>
            <th style={{
                width: 160
              }}>{t("Статус", "Holat", "Status")}</th>
          </tr></thead><tbody>{feedbackRows.map(item => <tr key={item.id}>
            <td className="admin-num">{fmtStamp(item.created_at)}</td>
            <td><b>{item.full_name || t("Без имени", "Ismsiz", "No name")}</b><div className="admin-sub">{item.email}</div></td>
            <td><b>{item.subject}</b><div style={{
                  marginTop: 6,
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.45
                }}>{item.message}</div></td>
            <td><span className="admin-pill"><span className={`admin-dot ${item.status === "resolved" ? "ok" : item.status === "open" ? "warn" : ""}`} />{feedbackStatusLabel(item.status)}</span>
              <select aria-label={t("Изменить статус", "Holatni o'zgartirish", "Change status")} value={item.status} disabled={feedbackBusy === item.id} onChange={event => updateFeedbackStatus(item.id, event.target.value)} style={{
                  display: "block",
                  marginTop: 8,
                  width: "100%"
                }}>
                <option value="open">{feedbackStatusLabel("open")}</option><option value="in_progress">{feedbackStatusLabel("in_progress")}</option><option value="resolved">{feedbackStatusLabel("resolved")}</option>
              </select></td>
          </tr>)}</tbody></table></div>}
      </div>
    </div>;
}
