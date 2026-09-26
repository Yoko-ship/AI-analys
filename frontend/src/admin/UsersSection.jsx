import { Icon } from "./icons.jsx";
import { DASH, fmtInt, fmtStamp } from "./adminModel.js";
import { Funnel } from "./AdminWidgets.jsx";
export function UsersSection({
  t,
  usersData,
  userDetail,
  adminLog,
  confirmAction,
  busy,
  setConfirmAction,
  runUserAction,
  funnel,
  usersQuery,
  setUsersQuery,
  loadUsers,
  usersOnly,
  setUsersOnly,
  openUser,
  setUserDetail
}) {
  const FUNNEL_LABELS = {
    visited: t("Зашли на сайт", "Saytga kirdi", "Visited"),
    registered: t("Зарегистрировались", "Ro'yxatdan o'tdi", "Registered"),
    activated: t("Запустили анализ", "Tahlil ishga tushirdi", "Ran an analysis"),
    returned: t("Вернулись позже", "Keyinroq qaytdi", "Came back later")
  };
  const userRows = usersData && usersData.items || [];
  const detailUser = userDetail && userDetail.ok ? userDetail : null;
  const adminLogRows = adminLog && adminLog.items || [];
  const USER_ACTION_LABELS = {
    deactivate: t("Отключил", "O'chirdi", "Deactivated"),
    reactivate: t("Включил", "Yoqdi", "Reactivated"),
    revoke_sessions: t("Отозвал сессии", "Seanslarni bekor qildi", "Revoked sessions"),
    delete: t("Удалил", "O'chirib tashladi", "Deleted")
  };
  const actionButton = (id, action, label, danger, disabled = false) => {
    const armed = confirmAction && confirmAction.id === id && confirmAction.action === action;
    return <button type="button" className={`admin-btn sm${armed ? " danger" : ""}`} disabled={busy || disabled} title={disabled ? t("Сначала удалите адрес из ADMIN_EMAILS", "Avval manzilni ADMIN_EMAILS dan olib tashlang", "Remove the address from ADMIN_EMAILS first") : undefined} onClick={() => {
      if (danger && !armed) {
        setConfirmAction({
          id,
          action
        });
        return;
      }
      runUserAction(id, action);
    }}>
        {armed ? t("Точно?", "Aniqmi?", "Sure?") : label}
      </button>;
  };
  return <div className="admin-section">
      <div className="panel">
        <h3>{t("Воронка за 30 дней", "30 kunlik voronka", "30-day funnel")}</h3>
        {funnel && funnel.ok ? <Funnel steps={funnel.steps} labels={FUNNEL_LABELS} /> : <div className="admin-empty">{DASH}</div>}
        <p className="admin-muted admin-note">
          {t("«Вернулись» — вход спустя сутки и больше после регистрации. Процент у шага — доля от предыдущего.", "«Qaytdi» — ro'yxatdan keyin bir kundan so'ng kirish.", "\u201cCame back\u201d means a sign-in a day or more after registering. The percentage is of the previous step.")}
        </p>
      </div>

      <div className="panel">
        <div className="admin-filters" style={{
        padding: 0,
        marginBottom: 14
      }}>
          <input className="admin-input" placeholder={t("Почта или имя…", "Pochta yoki ism…", "Email or name…")} value={usersQuery} onChange={e => setUsersQuery(e.target.value)} onKeyDown={e => {
          if (e.key === "Enter") loadUsers(usersQuery, usersOnly);
        }} />
          <button type="button" className="admin-btn sm" onClick={() => loadUsers(usersQuery, usersOnly)}>
            <Icon name="search" />{t("Найти", "Qidirish", "Search")}
          </button>
          <span className="admin-sp" />
          <div className="admin-seg">
            {[["", t("Все", "Barchasi", "All")], ["active", t("Активные", "Faol", "Active")], ["inactive", t("Отключённые", "O'chirilgan", "Deactivated")], ["analysed", t("С анализами", "Tahlili borlar", "With analyses")]].map(([key, label]) => <button key={key || "all"} type="button" aria-selected={usersOnly === key} onClick={() => setUsersOnly(key)}>
                {label}
              </button>)}
          </div>
        </div>

        <div className="admin-scroll">
          <table>
            <thead>
              <tr>
                <th>{t("Пользователь", "Foydalanuvchi", "User")}</th>
                <th style={{
                width: 140
              }}>{t("Регистрация", "Ro'yxatdan o'tgan", "Registered")}</th>
                <th style={{
                width: 140
              }}>{t("Последний вход", "Oxirgi kirish", "Last sign-in")}</th>
                <th className="r" style={{
                width: 90
              }}>{t("Анализов", "Tahlillar", "Analyses")}</th>
                <th className="r" style={{
                width: 96
              }}>{t("Избранных", "Sevimlilar", "Favourites")}</th>
                <th style={{
                width: 105
              }}>{t("Тариф", "Tarif", "Tier")}</th>
                <th style={{
                width: 120
              }}>{t("Статус", "Holat", "State")}</th>
              </tr>
            </thead>
            <tbody>
              {!userRows.length ? <tr>
                  <td colSpan={7} className="admin-muted" style={{
                padding: "24px 0",
                textAlign: "center"
              }}>
                    {t("Никого не найдено.", "Hech kim topilmadi.", "Nobody found.")}
                  </td>
                </tr> : null}
              {userRows.map(u => <tr key={u.id}>
                  <td>
                    <button type="button" className="admin-link" onClick={() => openUser(u.id)}>
                      {u.email}
                    </button>
                    {u.is_admin ? <span className="admin-pill" style={{
                  marginLeft: 8
                }}>
                        <span className="admin-dot ok" />admin
                      </span> : null}
                    {u.full_name ? <div className="admin-sub">{u.full_name}{u.oauth_providers ? ` · ${u.oauth_providers}` : ""}</div> : u.oauth_providers ? <div className="admin-sub">{u.oauth_providers}</div> : null}
                  </td>
                  <td className="admin-num">{fmtStamp(u.created_at, {
                  withTime: false
                })}</td>
                  <td className="admin-num">{fmtStamp(u.last_login_at, {
                  withTime: false
                })}</td>
                  <td className="r admin-num">{fmtInt(u.analyses)}</td>
                  <td className="r admin-num">{fmtInt(u.favorites)}</td>
                  <td>
                    <span className="admin-pill">
                      <span className={`admin-dot ${u.tier === "pro" ? "ok" : ""}`} />
                      {u.tier === "pro" ? "PRO" : t("бесплатный", "bepul", "free")}
                    </span>
                  </td>
                  <td>
                    <span className="admin-pill">
                      <span className={`admin-dot ${u.is_active ? "ok" : "err"}`} />
                      {u.is_active ? t("активен", "faol", "active") : t("отключён", "o'chirilgan", "off")}
                    </span>
                  </td>
                </tr>)}
            </tbody>
          </table>
        </div>
        <div className="admin-table-foot">
          <span>
            {t(`Показано ${userRows.length} из ${fmtInt(usersData && usersData.total)}`, `${fmtInt(usersData && usersData.total)} tadan ${userRows.length} ta`, `Showing ${userRows.length} of ${fmtInt(usersData && usersData.total)}`)}
          </span>
        </div>
      </div>

      {detailUser ? <div className="panel">
          <div className="admin-panel-head">
            <h2>{detailUser.user.email}</h2>
            <span className="admin-muted">
              {detailUser.user.full_name || DASH} · {t("зарегистрирован", "ro'yxatdan o'tgan", "registered")} {fmtStamp(detailUser.user.created_at, {
            withTime: false
          })}
            </span>
          </div>

          <div className="admin-filters" style={{
        padding: 0
      }}>
            {detailUser.user.is_active ? actionButton(detailUser.user.id, "deactivate", t("Отключить", "O'chirish", "Deactivate"), true, detailUser.user.is_admin) : actionButton(detailUser.user.id, "reactivate", t("Включить", "Yoqish", "Reactivate"), false)}
            {actionButton(detailUser.user.id, "revoke_sessions", t("Разлогинить везде", "Hamma joydan chiqarish", "Revoke sessions"), false)}
            {actionButton(detailUser.user.id, "delete", t("Удалить аккаунт", "Hisobni o'chirish", "Delete account"), true, detailUser.user.is_admin)}
            <span className="admin-sp" />
            <button type="button" className="admin-btn sm" onClick={() => {
          setUserDetail(null);
          setConfirmAction(null);
        }}>
              {t("Свернуть", "Yopish", "Close")}
            </button>
          </div>
          <p className="admin-muted admin-note">
            {detailUser.user.is_admin ? t("Администратор защищён от отключения и удаления. Сначала уберите адрес из ADMIN_EMAILS — это намеренное изменение контура доступа.", "Administrator o'chirish va o'chirib tashlashdan himoyalangan. Avval manzilni ADMIN_EMAILS dan olib tashlang.", "This administrator is protected from deactivation and deletion. Remove the address from ADMIN_EMAILS first—an explicit access-control change.") : t("Удаление уносит и историю анализов, и избранное — это право пользователя на удаление данных, а не уборка. Отключение мгновенно разрывает все сессии.", "O'chirish tahlil tarixini ham olib ketadi.", "Deletion takes the analysis history and favourites with it—the user's right to erasure, not housekeeping. Deactivation severs every session immediately.")}
          </p>

          <div className="admin-cols3" style={{
        marginTop: 14
      }}>
            <div>
              <div className="panel-label">{t("Сессии", "Sessiyalar", "Sessions")}</div>
              <table className="admin-kv">
                <tbody>
                  {detailUser.sessions.slice(0, 6).map((s, i) => <tr key={i}>
                      <td>{fmtStamp(s.created_at)}</td>
                      <td className="n">{s.revoked ? t("отозвана", "bekor qilingan", "revoked") : t("живая", "faol", "live")}</td>
                    </tr>)}
                  {!detailUser.sessions.length ? <tr><td className="admin-muted">{t("Сессий не было", "Sessiyalar bo'lmagan", "No sessions")}</td><td /></tr> : null}
                </tbody>
              </table>
            </div>
            <div>
              <div className="panel-label">{t("Анализы", "Tahlillar", "Analyses")}</div>
              <table className="admin-kv">
                <tbody>
                  {detailUser.analyses.slice(0, 6).map((a, i) => <tr key={i}>
                      <td>{a.ticker || a.company}</td>
                      <td className="n">{a.grade || DASH} · {fmtStamp(a.created_at, {
                    withTime: false
                  })}</td>
                    </tr>)}
                  {!detailUser.analyses.length ? <tr><td className="admin-muted">{t("Анализов не было", "Tahlillar bo'lmagan", "No analyses")}</td><td /></tr> : null}
                </tbody>
              </table>
            </div>
            <div>
              <div className="panel-label">{t("Избранное", "Sevimlilar", "Favourites")}</div>
              <table className="admin-kv">
                <tbody>
                  {detailUser.favorites.slice(0, 6).map((f, i) => <tr key={i}>
                      <td>{f.ticker}</td>
                      <td className="n">{fmtStamp(f.created_at, {
                    withTime: false
                  })}</td>
                    </tr>)}
                  {!detailUser.favorites.length ? <tr><td className="admin-muted">{t("Пусто", "Bo'sh", "Empty")}</td><td /></tr> : null}
                </tbody>
              </table>
            </div>
          </div>
        </div> : null}

      <div className="panel">
        <div className="admin-panel-head">
          <h2>{t("Журнал действий", "Amallar jurnali", "Administrative activity")}</h2>
          <span className="admin-muted">
            {t("Кто, что, над кем и когда", "Kim, nima, kimga va qachon", "Who did what, to whom, and when")}
          </span>
        </div>
        <div className="admin-scroll">
          <table>
            <thead>
              <tr>
                <th style={{
                width: 165
              }}>{t("Время", "Vaqt", "Time")}</th>
                <th>{t("Администратор", "Administrator", "Administrator")}</th>
                <th style={{
                width: 170
              }}>{t("Действие", "Amal", "Action")}</th>
                <th>{t("Объект", "Obyekt", "Target")}</th>
                <th style={{
                width: 120
              }}>{t("Результат", "Natija", "Outcome")}</th>
              </tr>
            </thead>
            <tbody>
              {!adminLogRows.length ? <tr>
                  <td colSpan={5} className="admin-muted" style={{
                padding: "24px 0",
                textAlign: "center"
              }}>
                    {t("Действий пока не было.", "Hali amallar bo'lmagan.", "No administrative actions yet.")}
                  </td>
                </tr> : null}
              {adminLogRows.map(entry => <tr key={entry.id}>
                  <td className="admin-num">{fmtStamp(entry.created_at)}</td>
                  <td>{entry.actor_email}</td>
                  <td>{USER_ACTION_LABELS[entry.action] || entry.action}</td>
                  <td>
                    {entry.target_label || `${entry.target_type} ${entry.target_id || ""}`}
                    {entry.target_id ? <div className="admin-sub">ID {entry.target_id}</div> : null}
                  </td>
                  <td>
                    <span className="admin-pill">
                      <span className={`admin-dot ${entry.outcome === "success" ? "ok" : "err"}`} />
                      {entry.outcome === "success" ? t("выполнено", "bajarildi", "success") : t("отклонено", "rad etildi", "denied")}
                    </span>
                  </td>
                </tr>)}
            </tbody>
          </table>
        </div>
        <p className="admin-muted admin-note">
          {t("Журнал хранится в базе отдельно от серверных логов; удаление пользователя не удаляет запись о действии.", "Jurnal server loglaridan alohida bazada saqlanadi.", "This trail is stored in the database separately from server logs; deleting a user does not delete the action record.")}
        </p>
      </div>
    </div>;
}
