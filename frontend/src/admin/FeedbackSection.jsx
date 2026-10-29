import { fmtStamp } from "./adminModel.js";
export function FeedbackSection({
  feedbackData,
  t,
  feedbackFilter,
  setFeedbackFilter,
  feedbackBusy,
  updateFeedbackStatus
}) {
  const ratings = feedbackData?.ratings;
  const ratingLabel = value => ({
    1: t("Есть проблемы", "Yaxshilash kerak", "Needs work"),
    2: t("Нормально", "Qoniqarli", "Okay"),
    3: t("Отлично", "Ajoyib", "Great"),
  })[value];
  const feedbackRows = feedbackData?.items || [];
  const feedbackStatusLabel = status => ({
    open: t("Новое", "Yangi", "New"),
    in_progress: t("В работе", "Jarayonda", "In progress"),
    resolved: t("Закрыто", "Yopilgan", "Resolved")
  })[status] || status;
  return <div className="admin-section">
      <section className="panel" aria-label={t("Оценки сайта", "Sayt baholari", "Site ratings")}>
        <div className="admin-panel-head"><div>
          <h2>{t("Оценки сайта", "Sayt baholari", "Site ratings")}</h2>
          <p className="admin-muted">{ratings && !ratings.error && <>{ratings.total || 0} {t("ответов", "ta javob", "responses")} · </>} {t("За всё время · без привязки к аккаунту", "Barcha vaqt · hisobga bog‘lanmagan", "All time · anonymous")}</p>
        </div></div>
        {ratings?.error ? <p className="admin-empty" role="alert">{ratings.error}</p> : !ratings ? <p className="admin-empty" role="status">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</p> : <>
        <div className="admin-scroll"><table><thead><tr>{[1, 2, 3].map(value => <th key={value}>{value} · {ratingLabel(value)}</th>)}</tr></thead>
          <tbody><tr>{[1, 2, 3].map(value => <td className="admin-num" key={value}>{ratings?.counts?.[value] || 0}</td>)}</tr></tbody>
        </table></div>
        {!ratings?.items?.length ? <p className="admin-empty">{t("Оценок пока нет.", "Hozircha baholar yo‘q.", "No ratings yet.")}</p> : <div className="admin-scroll"><table>
          <caption>{t("Последние 50 ответов", "Oxirgi 50 ta javob", "Latest 50 responses")}</caption>
          <thead><tr><th>{t("Когда", "Vaqt", "When")}</th><th>{t("Оценка", "Baho", "Rating")}</th><th>{t("Страница", "Sahifa", "Page")}</th><th>{t("Язык", "Til", "Language")}</th></tr></thead>
          <tbody>{ratings.items.map((item, index) => <tr key={index}>
            <td className="admin-num">{fmtStamp(item.created_at)}</td>
            <td>{ratingLabel(item.rating)}<div className="admin-sub">{t("Анонимно", "Anonim", "Anonymous")}</div></td>
            <td>{item.page_path}</td><td>{item.language.toUpperCase()}</td>
          </tr>)}</tbody>
        </table></div>}
        </>}
      </section>
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
