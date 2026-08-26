import React, { useEffect, useState } from "react";

const pick = (language, ru, en, uz) => (language === "en" ? en : language === "uz" ? uz : ru);

async function readJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Request failed");
  return data;
}

function SwitchRow({ label, hint, checked, onChange }) {
  return (
    <label className="profile-center-switch">
      <span><strong>{label}</strong>{hint ? <small>{hint}</small> : null}</span>
      <input type="checkbox" checked={Boolean(checked)} onChange={(event) => onChange(event.target.checked)} />
      <i aria-hidden="true" />
    </label>
  );
}

function ActionStatus({ text, tone = "" }) {
  return text ? <p className={`profile-center-status ${tone}`}>{text}</p> : null;
}

export function ProfileAccountCenter({
  open,
  initialTab,
  profile,
  language,
  theme,
  textScale,
  apiFetch,
  onClose,
  onRefresh,
  onLogout,
  onLanguage,
  onTheme,
  onTextScale,
  identityForm,
}) {
  const [tab, setTab] = useState(initialTab || "profile");
  const [preferences, setPreferences] = useState(profile?.preferences || {});
  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [password, setPassword] = useState({ current_password: "", new_password: "", confirm: "" });
  const [twoFactor, setTwoFactor] = useState(null);
  const [twoFactorCode, setTwoFactorCode] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [helpDoc, setHelpDoc] = useState("");
  const [supportForm, setSupportForm] = useState({ subject: "", message: "" });
  const [status, setStatus] = useState("");
  const [statusTone, setStatusTone] = useState("");
  const [busy, setBusy] = useState("");

  const tx = (ru, en, uz) => pick(language, ru, en, uz);
  const security = profile?.security || {};
  const user = profile?.user || {};

  const notify = (message, tone = "success") => {
    setStatus(message);
    setStatusTone(tone);
  };

  useEffect(() => {
    if (!open) return;
    setTab(initialTab || "profile");
    setPreferences(profile?.preferences || {});
    setStatus("");
    setConfirmation("");
    setTwoFactor(null);
    setTwoFactorCode("");
  }, [open, initialTab, profile]);

  const loadSessions = async () => {
    setSessionsLoading(true);
    try {
      const data = await readJson(await apiFetch("/api/profile/sessions"));
      setSessions(data.sessions || []);
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setSessionsLoading(false);
    }
  };

  useEffect(() => {
    if (open && tab === "security") loadSessions();
    // apiFetch is recreated by the app render; tab/open are the intentional triggers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tab]);

  if (!open) return null;

  const savePreferences = async (event) => {
    event.preventDefault();
    setBusy("preferences");
    try {
      const data = await readJson(await apiFetch("/api/profile/preferences", {
        method: "PATCH",
        body: JSON.stringify(preferences),
      }));
      setPreferences(data.preferences || preferences);
      if (data.preferences?.language) onLanguage(data.preferences.language);
      if (data.preferences?.theme) onTheme(data.preferences.theme);
      if (data.preferences?.text_scale) onTextScale(Number(data.preferences.text_scale));
      await onRefresh();
      notify(tx("Настройки сохранены", "Preferences saved", "Sozlamalar saqlandi"));
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy("");
    }
  };

  const changePassword = async (event) => {
    event.preventDefault();
    if (password.new_password !== password.confirm) {
      notify(tx("Новые пароли не совпадают", "New passwords do not match", "Yangi parollar mos emas"), "error");
      return;
    }
    setBusy("password");
    try {
      const data = await readJson(await apiFetch("/api/profile/password", {
        method: "POST",
        body: JSON.stringify({ current_password: password.current_password, new_password: password.new_password }),
      }));
      setPassword({ current_password: "", new_password: "", confirm: "" });
      await loadSessions();
      notify(`${tx("Пароль изменён", "Password changed", "Parol o'zgartirildi")} · ${data.revoked_sessions || 0} ${tx("сессий закрыто", "sessions closed", "sessiya yopildi")}`);
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy("");
    }
  };

  const beginTwoFactor = async () => {
    setBusy("2fa");
    try {
      const data = await readJson(await apiFetch("/api/profile/2fa/setup", { method: "POST" }));
      setTwoFactor(data);
      notify(tx("Добавьте ключ в приложение-аутентификатор", "Add the key to your authenticator app", "Kalitni autentifikator ilovasiga qo'shing"), "info");
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy("");
    }
  };

  const confirmTwoFactor = async (enabled) => {
    setBusy("2fa");
    try {
      await readJson(await apiFetch(`/api/profile/2fa/${enabled ? "enable" : "disable"}`, {
        method: "POST",
        body: JSON.stringify({ code: twoFactorCode }),
      }));
      setTwoFactor(null);
      setTwoFactorCode("");
      await onRefresh();
      notify(enabled
        ? tx("Двухфакторная защита включена", "Two-factor authentication enabled", "Ikki bosqichli himoya yoqildi")
        : tx("Двухфакторная защита выключена", "Two-factor authentication disabled", "Ikki bosqichli himoya o'chirildi"));
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy("");
    }
  };

  const revokeSession = async (id) => {
    setBusy(`session-${id}`);
    try {
      await readJson(await apiFetch(`/api/profile/sessions/${id}`, { method: "DELETE" }));
      await loadSessions();
      notify(tx("Сессия закрыта", "Session revoked", "Sessiya yopildi"));
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy("");
    }
  };

  const revokeOthers = async () => {
    setBusy("sessions");
    try {
      const data = await readJson(await apiFetch("/api/profile/sessions/revoke-others", { method: "POST" }));
      await loadSessions();
      notify(`${data.revoked_sessions || 0} ${tx("сессий закрыто", "sessions revoked", "sessiya yopildi")}`);
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy("");
    }
  };

  const downloadData = async () => {
    setBusy("export");
    try {
      const response = await apiFetch("/api/profile/export");
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Export failed");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "uz-stock-profile-data.json";
      link.click();
      URL.revokeObjectURL(url);
      notify(tx("Архив данных скачан", "Data archive downloaded", "Ma'lumotlar arxivi yuklandi"));
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy("");
    }
  };

  const clearHistory = async () => {
    setBusy("clear");
    try {
      const data = await readJson(await apiFetch("/api/profile/history", {
        method: "DELETE",
        body: JSON.stringify({ confirmation }),
      }));
      setConfirmation("");
      await onRefresh();
      notify(`${data.deleted_analyses || 0} ${tx("исследований удалено", "analyses deleted", "tahlil o'chirildi")}`);
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy("");
    }
  };

  const deleteAccount = async () => {
    setBusy("delete");
    try {
      await readJson(await apiFetch("/api/profile/account", {
        method: "DELETE",
        body: JSON.stringify({ confirmation }),
      }));
      onLogout();
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy("");
    }
  };

  const submitSupport = async (event) => {
    event.preventDefault();
    setBusy("support");
    try {
      const data = await readJson(await apiFetch("/api/profile/support", {
        method: "POST",
        body: JSON.stringify(supportForm),
      }));
      setSupportForm({ subject: "", message: "" });
      notify(`${tx("Обращение принято", "Request received", "Murojaat qabul qilindi")} #${data.request?.id || ""}`);
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy("");
    }
  };

  const tabs = [
    ["profile", tx("Профиль", "Profile", "Profil")],
    ["preferences", tx("Интерфейс", "Preferences", "Sozlamalar")],
    ["security", tx("Безопасность", "Security", "Xavfsizlik")],
    ["notifications", tx("Уведомления", "Notifications", "Bildirishnomalar")],
    ["data", tx("Данные", "Data & privacy", "Ma'lumotlar")],
    ["help", tx("Помощь", "Help", "Yordam")],
  ];

  return (
    <div className="profile-cmd-settings-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="profile-cmd-settings profile-account-center" role="dialog" aria-modal="true" aria-labelledby="profile-center-title">
        <header>
          <div>
            <span>{tx("Центр аккаунта", "Account center", "Hisob markazi")}</span>
            <h2 id="profile-center-title">{tabs.find(([key]) => key === tab)?.[1]}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label={tx("Закрыть", "Close", "Yopish")}>×</button>
        </header>
        <div className="profile-center-layout">
          <nav className="profile-center-tabs" aria-label={tx("Настройки аккаунта", "Account settings", "Hisob sozlamalari")}>
            {tabs.map(([key, label]) => (
              <button key={key} type="button" className={tab === key ? "active" : ""} onClick={() => { setTab(key); setStatus(""); }}>
                <span aria-hidden="true">{({ profile: "○", preferences: "◐", security: "◇", notifications: "◌", data: "⇩", help: "?" })[key]}</span>
                {label}
              </button>
            ))}
            <button type="button" className="profile-center-logout" onClick={onLogout}><span aria-hidden="true">↪</span>{tx("Выйти", "Sign out", "Chiqish")}</button>
          </nav>

          <div className="profile-center-content">
            {tab === "profile" ? (
              <section className="profile-center-section">
                <div className="profile-center-section-head">
                  <div><h3>{tx("Личные данные", "Personal details", "Shaxsiy ma'lumotlar")}</h3><p>{tx("Имя, аватар и данные входа.", "Your name, avatar, and sign-in identity.", "Ism, avatar va kirish ma'lumotlari.")}</p></div>
                  <span className={`profile-center-badge ${user.email_verified ? "verified" : ""}`}>{user.email_verified ? tx("Email подтверждён", "Email verified", "Email tasdiqlangan") : tx("Email не подтверждён", "Email not verified", "Email tasdiqlanmagan")}</span>
                </div>
                <div className="profile-center-readonly"><span>Email</span><strong>{user.email || "—"}</strong></div>
                <div className="profile-center-readonly"><span>{tx("Аккаунт создан", "Member since", "Hisob yaratilgan")}</span><strong>{user.created_at ? new Date(user.created_at).toLocaleDateString(language) : "—"}</strong></div>
                {identityForm}
              </section>
            ) : null}

            {tab === "preferences" ? (
              <form className="profile-center-section" onSubmit={savePreferences}>
                <div className="profile-center-section-head"><div><h3>{tx("Интерфейс и отчёты", "Interface & reports", "Interfeys va hisobotlar")}</h3><p>{tx("Эти настройки сохраняются в аккаунте и работают на всех устройствах.", "These settings follow your account across devices.", "Bu sozlamalar barcha qurilmalarda hisobingizga bog'lanadi.")}</p></div></div>
                <div className="profile-center-form-grid">
                  <label><span>{tx("Язык", "Language", "Til")}</span><select value={preferences.language || language} onChange={(e) => setPreferences({ ...preferences, language: e.target.value })}><option value="ru">Русский</option><option value="uz">O‘zbekcha</option><option value="en">English</option></select></label>
                  <label><span>{tx("Тема", "Theme", "Mavzu")}</span><select value={preferences.theme || theme} onChange={(e) => setPreferences({ ...preferences, theme: e.target.value })}><option value="dark">{tx("Тёмная", "Dark", "Qorong'i")}</option><option value="light">{tx("Светлая", "Light", "Yorug'")}</option></select></label>
                  <label><span>{tx("Размер текста", "Text size", "Matn o'lchami")}</span><select value={preferences.text_scale || textScale} onChange={(e) => setPreferences({ ...preferences, text_scale: Number(e.target.value) })}>{[85, 100, 115, 130].map((value) => <option key={value} value={value}>{value}%</option>)}</select></label>
                  <label><span>{tx("Часовой пояс", "Time zone", "Vaqt mintaqasi")}</span><input value={preferences.timezone || "Asia/Tashkent"} onChange={(e) => setPreferences({ ...preferences, timezone: e.target.value })} /></label>
                  <label><span>{tx("Язык отчёта", "Report language", "Hisobot tili")}</span><select value={preferences.default_report_language || language} onChange={(e) => setPreferences({ ...preferences, default_report_language: e.target.value })}><option value="ru">Русский</option><option value="uz">O‘zbekcha</option><option value="en">English</option></select></label>
                  <label><span>{tx("Период анализа", "Default analysis period", "Tahlil davri")}</span><select value={preferences.default_analysis_period || "latest"} onChange={(e) => setPreferences({ ...preferences, default_analysis_period: e.target.value })}><option value="latest">{tx("Последние данные", "Latest data", "So'nggi ma'lumot")}</option><option value="quarterly">{tx("Квартал", "Quarterly", "Chorak")}</option><option value="annual">{tx("Год", "Annual", "Yillik")}</option></select></label>
                </div>
                <button className="profile-cmd-primary" disabled={busy === "preferences"}>{busy === "preferences" ? tx("Сохраняем…", "Saving…", "Saqlanmoqda…") : tx("Сохранить настройки", "Save preferences", "Sozlamalarni saqlash")}</button>
              </form>
            ) : null}

            {tab === "security" ? (
              <div className="profile-center-section profile-center-security">
                <div className="profile-center-section-head"><div><h3>{tx("Пароль и доступ", "Password & access", "Parol va kirish")}</h3><p>{tx("Управляйте паролем, 2FA и активными устройствами.", "Manage your password, 2FA, and active devices.", "Parol, 2FA va faol qurilmalarni boshqaring.")}</p></div></div>
                <form className="profile-center-subsection" onSubmit={changePassword}>
                  <h4>{tx("Изменить пароль", "Change password", "Parolni o'zgartirish")}</h4>
                  <div className="profile-center-form-grid">
                    <label><span>{tx("Текущий пароль", "Current password", "Joriy parol")}</span><input type="password" autoComplete="current-password" value={password.current_password} onChange={(e) => setPassword({ ...password, current_password: e.target.value })} required /></label>
                    <label><span>{tx("Новый пароль", "New password", "Yangi parol")}</span><input type="password" minLength="8" autoComplete="new-password" value={password.new_password} onChange={(e) => setPassword({ ...password, new_password: e.target.value })} required /></label>
                    <label><span>{tx("Повторите пароль", "Confirm new password", "Parolni tasdiqlang")}</span><input type="password" minLength="8" autoComplete="new-password" value={password.confirm} onChange={(e) => setPassword({ ...password, confirm: e.target.value })} required /></label>
                  </div>
                  <button className="ghost-btn" disabled={busy === "password"}>{tx("Обновить пароль", "Update password", "Parolni yangilash")}</button>
                </form>
                <div className="profile-center-subsection">
                  <div className="profile-center-inline-head"><div><h4>{tx("Двухфакторная защита", "Two-factor authentication", "Ikki bosqichli himoya")}</h4><p>{security.two_factor_enabled ? tx("Включена", "Enabled", "Yoqilgan") : tx("Не включена", "Not enabled", "Yoqilmagan")}</p></div><span className={`profile-center-badge ${security.two_factor_enabled ? "verified" : ""}`}>2FA</span></div>
                  {!security.two_factor_enabled && !twoFactor ? <button className="ghost-btn" type="button" onClick={beginTwoFactor} disabled={busy === "2fa"}>{tx("Настроить 2FA", "Set up 2FA", "2FA ni sozlash")}</button> : null}
                  {twoFactor ? <div className="profile-center-2fa"><p>{tx("Скопируйте ключ в Google Authenticator, 1Password или другое TOTP-приложение.", "Copy this key into Google Authenticator, 1Password, or another TOTP app.", "Bu kalitni Google Authenticator, 1Password yoki boshqa TOTP ilovasiga nusxalang.")}</p><code>{twoFactor.secret}</code><input inputMode="numeric" autoComplete="one-time-code" placeholder="000000" value={twoFactorCode} onChange={(e) => setTwoFactorCode(e.target.value)} /><button className="profile-cmd-primary" type="button" onClick={() => confirmTwoFactor(true)} disabled={busy === "2fa" || twoFactorCode.length < 6}>{tx("Подтвердить и включить", "Verify and enable", "Tasdiqlash va yoqish")}</button></div> : null}
                  {security.two_factor_enabled ? <div className="profile-center-2fa"><input inputMode="numeric" autoComplete="one-time-code" placeholder={tx("Код из приложения", "Authenticator code", "Ilovadagi kod")} value={twoFactorCode} onChange={(e) => setTwoFactorCode(e.target.value)} /><button className="ghost-btn danger" type="button" onClick={() => confirmTwoFactor(false)} disabled={busy === "2fa" || twoFactorCode.length < 6}>{tx("Выключить 2FA", "Disable 2FA", "2FA ni o'chirish")}</button></div> : null}
                </div>
                <div className="profile-center-subsection">
                  <div className="profile-center-inline-head"><div><h4>{tx("Активные сессии", "Active sessions", "Faol sessiyalar")}</h4><p>{tx("Устройства, где выполнен вход в аккаунт.", "Devices currently signed in to your account.", "Hisobga kirilgan qurilmalar.")}</p></div><button type="button" className="ghost-btn" onClick={revokeOthers} disabled={busy === "sessions"}>{tx("Закрыть остальные", "Revoke others", "Boshqalarini yopish")}</button></div>
                  {sessionsLoading ? <p className="muted">{tx("Загрузка…", "Loading…", "Yuklanmoqda…")}</p> : <div className="profile-center-sessions">{sessions.map((session) => <article key={session.id}><div><strong>{session.current ? tx("Это устройство", "This device", "Bu qurilma") : (session.user_agent || tx("Неизвестное устройство", "Unknown device", "Noma'lum qurilma"))}</strong><small>{session.ip_address || "—"} · {session.last_seen_at ? new Date(session.last_seen_at).toLocaleString(language) : "—"}</small></div>{session.current ? <span>{tx("Текущая", "Current", "Joriy")}</span> : <button type="button" onClick={() => revokeSession(session.id)} disabled={busy === `session-${session.id}`}>{tx("Закрыть", "Revoke", "Yopish")}</button>}</article>)}</div>}
                </div>
              </div>
            ) : null}

            {tab === "notifications" ? (
              <form className="profile-center-section" onSubmit={savePreferences}>
                <div className="profile-center-section-head"><div><h3>{tx("Какие события присылать", "Notification preferences", "Bildirishnoma sozlamalari")}</h3><p>{tx("Выберите полезные сигналы. Состояние уведомлений синхронизируется между устройствами.", "Choose the signals that matter. Read state syncs across devices.", "Kerakli signallarni tanlang. O'qilgan holat qurilmalar orasida saqlanadi.")}</p></div></div>
                <div className="profile-center-switches">
                  <SwitchRow label={tx("Новая отчётность", "New company reports", "Yangi hisobotlar")} hint={tx("Документы по компаниям из избранного", "Filings for watchlist companies", "Tanlangan kompaniya hujjatlari")} checked={preferences.notify_reports ?? true} onChange={(value) => setPreferences({ ...preferences, notify_reports: value })} />
                  <SwitchRow label={tx("Новости компаний", "Company news", "Kompaniya yangiliklari")} checked={preferences.notify_news ?? true} onChange={(value) => setPreferences({ ...preferences, notify_news: value })} />
                  <SwitchRow label={tx("Ценовые уровни", "Price alerts", "Narx signallari")} checked={preferences.notify_price ?? true} onChange={(value) => setPreferences({ ...preferences, notify_price: value })} />
                  <SwitchRow label={tx("Готовые анализы", "Analysis updates", "Tahlil yangilanishlari")} checked={preferences.notify_analysis ?? true} onChange={(value) => setPreferences({ ...preferences, notify_analysis: value })} />
                </div>
                <button className="profile-cmd-primary" disabled={busy === "preferences"}>{tx("Сохранить уведомления", "Save notifications", "Bildirishnomalarni saqlash")}</button>
              </form>
            ) : null}

            {tab === "data" ? (
              <div className="profile-center-section">
                <div className="profile-center-section-head"><div><h3>{tx("Данные и приватность", "Data & privacy", "Ma'lumotlar va maxfiylik")}</h3><p>{tx("Скачайте свои данные или удалите то, что больше не нужно.", "Download your data or remove what you no longer need.", "Ma'lumotlarni yuklab oling yoki keraksizini o'chiring.")}</p></div></div>
                <div className="profile-center-data-action"><div><h4>{tx("Экспорт данных", "Export your data", "Ma'lumotlarni eksport qilish")}</h4><p>{tx("Профиль, настройки, избранное, исследования, заметки и список сессий в JSON.", "Profile, preferences, watchlist, analyses, notes, and sessions in JSON.", "Profil, sozlamalar, tanlanganlar, tahlillar, qaydlar va sessiyalar JSON formatida.")}</p></div><button className="ghost-btn" type="button" onClick={downloadData} disabled={busy === "export"}>{tx("Скачать", "Download", "Yuklash")}</button></div>
                <div className="profile-center-danger-zone">
                  <h4>{tx("Опасная зона", "Danger zone", "Xavfli hudud")}</h4>
                  <p>{tx("Для очистки истории введите CLEAR. Для удаления аккаунта введите свой email.", "Enter CLEAR to erase history. Enter your email to delete the account.", "Tarixni o'chirish uchun CLEAR, hisobni o'chirish uchun emailingizni kiriting.")}</p>
                  <input value={confirmation} onChange={(e) => setConfirmation(e.target.value)} placeholder={tx("CLEAR или email", "CLEAR or your email", "CLEAR yoki email")} />
                  <div><button className="ghost-btn danger" type="button" onClick={clearHistory} disabled={busy === "clear" || confirmation !== "CLEAR"}>{tx("Очистить историю", "Clear analysis history", "Tahlil tarixini tozalash")}</button><button className="ghost-btn danger" type="button" onClick={deleteAccount} disabled={busy === "delete" || confirmation.toLowerCase() !== String(user.email || "").toLowerCase()}>{tx("Удалить аккаунт", "Delete account", "Hisobni o'chirish")}</button></div>
                </div>
              </div>
            ) : null}

            {tab === "help" ? (
              <div className="profile-center-section">
                <div className="profile-center-section-head"><div><h3>{tx("Помощь и документы", "Help & legal", "Yordam va hujjatlar")}</h3><p>{tx("Справка по показателям и быстрый канал связи с командой.", "Product guidance and a direct way to reach the team.", "Ko'rsatkichlar bo'yicha yordam va jamoa bilan aloqa.")}</p></div></div>
                <div className="profile-center-links">
                  <button type="button" onClick={() => setHelpDoc(helpDoc === "metrics" ? "" : "metrics")}><span>?</span><div><strong>{tx("Справочник показателей", "Metrics reference", "Ko'rsatkichlar lug'ati")}</strong><small>{tx("Формулы, термины и источники", "Formulas, terminology, and sources", "Formulalar, atamalar va manbalar")}</small></div><b>›</b></button>
                  <button type="button" onClick={() => setHelpDoc(helpDoc === "support" ? "" : "support")}><span>✉</span><div><strong>{tx("Написать в поддержку", "Contact support", "Yordamga yozish")}</strong><small>{tx("Создать обращение внутри аккаунта", "Create an account support request", "Hisob ichida murojaat yaratish")}</small></div><b>›</b></button>
                  <button type="button" onClick={() => setHelpDoc(helpDoc === "privacy" ? "" : "privacy")}><span>◇</span><div><strong>{tx("Политика конфиденциальности", "Privacy policy", "Maxfiylik siyosati")}</strong><small>{tx("Как обрабатываются данные аккаунта", "How account data is handled", "Hisob ma'lumotlari qanday ishlatiladi")}</small></div><b>›</b></button>
                  <button type="button" onClick={() => setHelpDoc(helpDoc === "terms" ? "" : "terms")}><span>§</span><div><strong>{tx("Условия использования", "Terms of use", "Foydalanish shartlari")}</strong><small>{tx("Правила сервиса и ограничения аналитики", "Service rules and analysis limitations", "Xizmat qoidalari va tahlil cheklovlari")}</small></div><b>›</b></button>
                </div>
                {helpDoc ? <article className="profile-center-help-doc"><h4>{helpDoc === "privacy" ? tx("Конфиденциальность", "Privacy", "Maxfiylik") : helpDoc === "terms" ? tx("Условия", "Terms", "Shartlar") : helpDoc === "support" ? tx("Новое обращение", "New support request", "Yangi murojaat") : tx("Как читать показатели", "Reading the metrics", "Ko'rsatkichlarni o'qish")}</h4>{helpDoc === "support" ? <form className="profile-center-support-form" onSubmit={submitSupport}><label><span>{tx("Тема", "Subject", "Mavzu")}</span><input value={supportForm.subject} onChange={(event) => setSupportForm({ ...supportForm, subject: event.target.value })} minLength="2" maxLength="160" required /></label><label><span>{tx("Что произошло?", "How can we help?", "Qanday yordam kerak?")}</span><textarea rows="5" value={supportForm.message} onChange={(event) => setSupportForm({ ...supportForm, message: event.target.value })} minLength="5" maxLength="6000" required /></label><button className="profile-cmd-primary" disabled={busy === "support"}>{busy === "support" ? tx("Отправляем…", "Sending…", "Yuborilmoqda…") : tx("Отправить обращение", "Send request", "Murojaat yuborish")}</button></form> : <p>{helpDoc === "privacy" ? tx("Мы храним данные аккаунта, настройки, избранное, историю исследований, заметки и сессии для работы профиля. Пароли хранятся только в виде криптографического хеша. Данные можно скачать или удалить в разделе «Данные». Не отправляйте конфиденциальные сведения в заметках.", "We store account details, preferences, watchlists, research history, notes, and sessions to operate your profile. Passwords are stored only as cryptographic hashes. You can export or delete your data from the Data tab. Do not place confidential information in notes.", "Profil ishlashi uchun hisob ma'lumotlari, sozlamalar, tanlanganlar, tahlil tarixi, qaydlar va sessiyalar saqlanadi. Parollar faqat kriptografik xesh ko'rinishida saqlanadi. Ma'lumotlarni Ma'lumotlar bo'limida yuklash yoki o'chirish mumkin.") : helpDoc === "terms" ? tx("Платформа предоставляет информационную аналитику по публичным данным. Материалы не являются индивидуальной инвестиционной рекомендацией, гарантией результата или предложением совершить сделку. Проверяйте исходные документы и учитывайте риск потери капитала.", "The platform provides informational analytics based on public data. It is not personalized investment advice, a guarantee of results, or an offer to trade. Verify source documents and consider the risk of capital loss.", "Platforma ochiq ma'lumotlar asosida axborot tahlilini taqdim etadi. Bu shaxsiy investitsiya tavsiyasi, natija kafolati yoki savdo taklifi emas. Manba hujjatlarini tekshiring va kapital yo'qotish xavfini hisobga oling.") : tx("Оценки и коэффициенты помогают сравнивать данные, но не заменяют первичную отчётность. Наведите курсор на значок ⓘ рядом с показателем, чтобы увидеть его формулу, период и источник. Сравнивайте компании одного сектора и одинаковых отчётных периодов.", "Scores and ratios help compare data but do not replace source filings. Use the ⓘ marker beside a metric to see its formula, period, and source. Compare companies from the same sector and reporting period.", "Baholar va koeffitsiyentlar ma'lumotlarni solishtirishga yordam beradi, lekin birlamchi hisobot o'rnini bosmaydi. Formula, davr va manbani ko'rish uchun ko'rsatkich yonidagi ⓘ belgisidan foydalaning.")}</p>}</article> : null}
              </div>
            ) : null}
            <ActionStatus text={status} tone={statusTone} />
          </div>
        </div>
      </section>
    </div>
  );
}

export function ProfileResearchEditor({ item, language, apiFetch, onClose, onRefresh, onRepeat }) {
  const tx = (ru, en, uz) => pick(language, ru, en, uz);
  const [form, setForm] = useState({ title: "", folder: "", tags: "", pinned_note: "", archived: false, bookmarked: false });
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!item) return;
    setForm({ title: item.title || item.company_name || item.company_input || "", folder: item.folder || "", tags: (item.tags || []).join(", "), pinned_note: item.pinned_note || "", archived: Boolean(item.archived), bookmarked: Boolean(item.bookmarked) });
    setStatus("");
  }, [item]);
  if (!item) return null;
  const save = async (event) => {
    event.preventDefault(); setBusy(true);
    try {
      await readJson(await apiFetch(`/api/profile/analyses/${item.id}`, { method: "PATCH", body: JSON.stringify({ ...form, tags: form.tags.split(",").map((tag) => tag.trim()).filter(Boolean) }) }));
      await onRefresh(); onClose();
    } catch (error) { setStatus(error.message); } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!window.confirm(tx("Удалить это исследование без возможности восстановления?", "Permanently delete this research?", "Bu tahlil butunlay o'chirilsinmi?"))) return;
    setBusy(true);
    try { await readJson(await apiFetch(`/api/profile/analyses/${item.id}`, { method: "DELETE" })); await onRefresh(); onClose(); } catch (error) { setStatus(error.message); } finally { setBusy(false); }
  };
  const download = async (format) => {
    setBusy(true);
    try {
      const response = await apiFetch(`/api/profile/analyses/${item.id}/export?format=${format}&language=${language}`);
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Export failed");
      const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `${item.ticker || "analysis"}.${format}`; link.click(); URL.revokeObjectURL(url);
    } catch (error) { setStatus(error.message); } finally { setBusy(false); }
  };
  return (
    <div className="profile-cmd-settings-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <section className="profile-item-editor" role="dialog" aria-modal="true" aria-labelledby="research-editor-title">
        <header><div><span>{item.ticker || tx("Исследование", "Research", "Tahlil")}</span><h2 id="research-editor-title">{tx("Управление исследованием", "Manage research", "Tahlilni boshqarish")}</h2></div><button type="button" onClick={onClose}>×</button></header>
        <form onSubmit={save}>
          <label><span>{tx("Название", "Title", "Nomi")}</span><input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
          <div className="profile-center-form-grid"><label><span>{tx("Папка", "Folder", "Papka")}</span><input value={form.folder} onChange={(e) => setForm({ ...form, folder: e.target.value })} placeholder={tx("Например, Банки", "e.g. Banks", "Masalan, Banklar")} /></label><label><span>{tx("Теги через запятую", "Comma-separated tags", "Teglar vergul bilan")}</span><input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} /></label></div>
          <label><span>{tx("Закреплённая заметка", "Pinned takeaway", "Mahkamlangan qayd")}</span><textarea rows="5" value={form.pinned_note} onChange={(e) => setForm({ ...form, pinned_note: e.target.value })} /></label>
          <div className="profile-item-checks"><SwitchRow label={tx("Добавить в закладки", "Bookmark", "Xatcho'pga qo'shish")} checked={form.bookmarked} onChange={(value) => setForm({ ...form, bookmarked: value })} /><SwitchRow label={tx("Переместить в архив", "Archive", "Arxivlash")} checked={form.archived} onChange={(value) => setForm({ ...form, archived: value })} /></div>
          {status ? <ActionStatus text={status} tone="error" /> : null}
          <div className="profile-item-actions"><button className="profile-cmd-primary" disabled={busy}>{tx("Сохранить", "Save", "Saqlash")}</button><button className="ghost-btn" type="button" onClick={() => onRepeat(item)}>{tx("Повторить анализ", "Run again", "Qayta tahlil")}</button><button className="ghost-btn" type="button" onClick={() => download("pdf")}>PDF</button><button className="ghost-btn" type="button" onClick={() => download("csv")}>CSV</button><button className="ghost-btn danger" type="button" onClick={remove}>{tx("Удалить", "Delete", "O'chirish")}</button></div>
        </form>
      </section>
    </div>
  );
}

export function ProfileFavoriteEditor({ item, language, apiFetch, onClose, onRefresh, onRemove }) {
  const tx = (ru, en, uz) => pick(language, ru, en, uz);
  const [form, setForm] = useState({}); const [status, setStatus] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { if (item) setForm({ position: item.position || 0, price_alert_enabled: Boolean(item.price_alert_enabled), price_alert_above: item.price_alert_above ?? "", price_alert_below: item.price_alert_below ?? "", news_alert_enabled: item.news_alert_enabled !== false, report_alert_enabled: item.report_alert_enabled !== false }); }, [item]);
  if (!item) return null;
  const save = async (event) => { event.preventDefault(); setBusy(true); try { await readJson(await apiFetch(`/api/favorites/${encodeURIComponent(item.ticker)}`, { method: "PATCH", body: JSON.stringify({ ...form, price_alert_above: form.price_alert_above === "" ? null : Number(form.price_alert_above), price_alert_below: form.price_alert_below === "" ? null : Number(form.price_alert_below) }) })); await onRefresh(); onClose(); } catch (error) { setStatus(error.message); } finally { setBusy(false); } };
  return <div className="profile-cmd-settings-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}><section className="profile-item-editor" role="dialog" aria-modal="true" aria-labelledby="favorite-editor-title"><header><div><span>{item.ticker}</span><h2 id="favorite-editor-title">{tx("Настройки избранного", "Watchlist settings", "Tanlanganlar sozlamasi")}</h2></div><button type="button" onClick={onClose}>×</button></header><form onSubmit={save}><SwitchRow label={tx("Ценовое уведомление", "Price alert", "Narx bildirishnomasi")} checked={form.price_alert_enabled} onChange={(value) => setForm({ ...form, price_alert_enabled: value })} /><div className="profile-center-form-grid"><label><span>{tx("Цена выше", "Price above", "Narx yuqori")}</span><input type="number" min="0" step="any" value={form.price_alert_above ?? ""} onChange={(e) => setForm({ ...form, price_alert_above: e.target.value })} /></label><label><span>{tx("Цена ниже", "Price below", "Narx past")}</span><input type="number" min="0" step="any" value={form.price_alert_below ?? ""} onChange={(e) => setForm({ ...form, price_alert_below: e.target.value })} /></label></div><SwitchRow label={tx("Новости компании", "Company news", "Kompaniya yangiliklari")} checked={form.news_alert_enabled} onChange={(value) => setForm({ ...form, news_alert_enabled: value })} /><SwitchRow label={tx("Новая отчётность", "New reports", "Yangi hisobotlar")} checked={form.report_alert_enabled} onChange={(value) => setForm({ ...form, report_alert_enabled: value })} /><label><span>{tx("Позиция в списке", "List position", "Ro'yxat o'rni")}</span><input type="number" min="0" value={form.position ?? 0} onChange={(e) => setForm({ ...form, position: Number(e.target.value) })} /></label>{status ? <ActionStatus text={status} tone="error" /> : null}<div className="profile-item-actions"><button className="profile-cmd-primary" disabled={busy}>{tx("Сохранить", "Save", "Saqlash")}</button><button className="ghost-btn danger" type="button" onClick={() => onRemove(item)}>{tx("Убрать из избранного", "Remove from watchlist", "Tanlanganlardan o'chirish")}</button></div></form></section></div>;
}

export function ProfileNoteEditor({ note, analyses, language, apiFetch, onClose, onRefresh }) {
  const tx = (ru, en, uz) => pick(language, ru, en, uz);
  const [form, setForm] = useState({ title: "", body: "", tags: "", pinned: true, analysis_id: "" }); const [status, setStatus] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { setForm({ title: note?.title || "", body: note?.body || "", tags: (note?.tags || []).join(", "), pinned: note ? Boolean(note.pinned) : true, analysis_id: note?.analysis_id || "" }); setStatus(""); }, [note]);
  const save = async (event) => { event.preventDefault(); setBusy(true); try { const path = note ? `/api/profile/notes/${note.id}` : "/api/profile/notes"; await readJson(await apiFetch(path, { method: note ? "PATCH" : "POST", body: JSON.stringify({ ...form, analysis_id: form.analysis_id ? Number(form.analysis_id) : null, tags: form.tags.split(",").map((tag) => tag.trim()).filter(Boolean) }) })); await onRefresh(); onClose(); } catch (error) { setStatus(error.message); } finally { setBusy(false); } };
  const remove = async () => { setBusy(true); try { await readJson(await apiFetch(`/api/profile/notes/${note.id}`, { method: "DELETE" })); await onRefresh(); onClose(); } catch (error) { setStatus(error.message); } finally { setBusy(false); } };
  return <div className="profile-cmd-settings-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}><section className="profile-item-editor" role="dialog" aria-modal="true" aria-labelledby="note-editor-title"><header><div><span>{tx("Библиотека", "Library", "Kutubxona")}</span><h2 id="note-editor-title">{note ? tx("Редактировать заметку", "Edit note", "Qaydni tahrirlash") : tx("Новая заметка", "New note", "Yangi qayd")}</h2></div><button type="button" onClick={onClose}>×</button></header><form onSubmit={save}><label><span>{tx("Название", "Title", "Nomi")}</span><input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label><label><span>{tx("Текст", "Note", "Qayd")}</span><textarea rows="7" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} required /></label><div className="profile-center-form-grid"><label><span>{tx("Связать с исследованием", "Link to research", "Tahlilga bog'lash")}</span><select value={form.analysis_id} onChange={(e) => setForm({ ...form, analysis_id: e.target.value })}><option value="">—</option>{(analyses || []).map((item) => <option key={item.id} value={item.id}>{item.title || item.company_name || item.company_input}</option>)}</select></label><label><span>{tx("Теги", "Tags", "Teglar")}</span><input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} /></label></div><SwitchRow label={tx("Закрепить заметку", "Pin note", "Qaydni mahkamlash")} checked={form.pinned} onChange={(value) => setForm({ ...form, pinned: value })} />{status ? <ActionStatus text={status} tone="error" /> : null}<div className="profile-item-actions"><button className="profile-cmd-primary" disabled={busy}>{tx("Сохранить", "Save", "Saqlash")}</button>{note ? <button className="ghost-btn danger" type="button" onClick={remove}>{tx("Удалить", "Delete", "O'chirish")}</button> : null}</div></form></section></div>;
}
