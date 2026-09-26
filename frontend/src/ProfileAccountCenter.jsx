import React, { useCallback, useEffect, useState } from "react";
import { PasswordMeter } from "./PasswordMeter.jsx";
import { passwordStrength, translateAuthError } from "./lib/passwordStrength.js";
import { CANDLE_PATTERN_TYPES, CHART_PATTERN_TYPES, patternName } from "./lib/patterns.js";

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

// Account center building blocks: a settings row (label and hint beside the
// control), pill radio groups, switches and the sticky save bar.
function AccountRow({ label, hint, htmlFor, children }) {
  return (
    <div className="acct-row">
      <div className="acct-row-label">
        {htmlFor ? <label htmlFor={htmlFor}>{label}</label> : <strong>{label}</strong>}
        {hint ? <span>{hint}</span> : null}
      </div>
      <div className="acct-row-control">{children}</div>
    </div>
  );
}

function AccountChoice({ label, options, value, onChange }) {
  return (
    <div className="acct-segmented" role="radiogroup" aria-label={label}>
      {options.map(([optionValue, optionLabel]) => (
        <button key={String(optionValue)} type="button" role="radio" aria-checked={value === optionValue} onClick={() => onChange(optionValue)}>
          {optionLabel}
        </button>
      ))}
    </div>
  );
}

/**
 * Which pattern types reach the bell. An empty choice means every chart
 * figure — the default — so it is shown as all figures ticked, and the first
 * change turns that implicit set into an explicit one.
 */
function PatternTypePicker({ language, value, onChange }) {
  const tx = (ru, en, uz) => pick(language, ru, en, uz);
  const chosen = new Set(value.length ? value : CHART_PATTERN_TYPES);
  const toggle = (type) => {
    const next = new Set(chosen);
    if (next.has(type)) next.delete(type); else next.add(type);
    onChange([...next]);
  };
  const group = (title, types) => (
    <fieldset className="acct-pattern-group">
      <legend>{title}</legend>
      {types.map((type) => (
        <label key={type} className="acct-pattern-type">
          <input type="checkbox" checked={chosen.has(type)} onChange={() => toggle(type)} />
          <span>{patternName(type, language)}</span>
        </label>
      ))}
    </fieldset>
  );
  return (
    <div className="acct-pattern-picker" data-testid="pattern-alert-types">
      {group(tx("Фигуры", "Chart figures", "Shakllar"), CHART_PATTERN_TYPES)}
      {group(tx("Свечные модели — на ликвидной бумаге появляются почти каждый день", "Candle models — near daily on a liquid share", "Sham modellari — likvid qog'ozda deyarli har kuni"), CANDLE_PATTERN_TYPES)}
      <p className="acct-pattern-note">{tx("Уведомление приходит только по бумагам из избранного, где включены паттерны, и только по ликвидным. На UZSE ни одна фигура не доходит до цели чаще случайного входа — статистика у каждого паттерна на графике.", "Alerts come only for watchlist companies with patterns switched on, and only for liquid shares. On UZSE no figure reaches its target more often than a random entry — each pattern's record is on the chart.", "Bildirishnoma faqat patternlar yoqilgan tanlangan va likvid qog'ozlar bo'yicha keladi. UZSEda hech bir shakl tasodifiy kirishdan ko'ra ko'proq maqsadga yetmaydi — har bir pattern statistikasi grafikda.")}</p>
    </div>
  );
}

function AccountSwitch({ label, hint, checked, onChange }) {
  return (
    <label className="acct-switch-row">
      <span><strong>{label}</strong>{hint ? <small>{hint}</small> : null}</span>
      <input type="checkbox" role="switch" checked={Boolean(checked)} onChange={(event) => onChange(event.target.checked)} />
      <i aria-hidden="true" />
    </label>
  );
}

function AccountFooter({ note, cancelLabel, submitLabel, busy, onCancel }) {
  return (
    <footer className="acct-footer">
      <span>{note}</span>
      <button type="button" className="acct-btn acct-btn-ghost" onClick={onCancel}>{cancelLabel}</button>
      <button type="submit" className="acct-btn acct-btn-accent" disabled={busy}>{submitLabel}</button>
    </footer>
  );
}

function CloseGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" focusable="false">
      <line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" />
    </svg>
  );
}

function ChevronGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <polyline points="9 6 15 12 9 18" />
    </svg>
  );
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
  avatar,
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

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const data = await readJson(await apiFetch("/api/profile/sessions"));
      setSessions(data.sessions || []);
    } catch (error) {
      setStatus(error.message);
      setStatusTone("error");
    } finally {
      setSessionsLoading(false);
    }
  }, [apiFetch]);

  useEffect(() => {
    if (open && tab === "security") loadSessions();
  }, [open, tab, loadSessions]);

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
      notify(translateAuthError(error.message, language), "error");
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
      notify(translateAuthError(error.message, language), "error");
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
      notify(translateAuthError(error.message, language), "error");
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
      notify(translateAuthError(error.message, language), "error");
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
      notify(translateAuthError(error.message, language), "error");
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
      notify(translateAuthError(error.message, language), "error");
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
      notify(translateAuthError(error.message, language), "error");
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
      notify(translateAuthError(error.message, language), "error");
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
      notify(translateAuthError(error.message, language), "error");
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
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  const formatDay = (value) => (value ? new Date(value).toLocaleDateString(locale, { day: "numeric", month: "long", year: "numeric" }) : "—");
  const plan = user.pro_access ? "PRO" : tx("Бесплатный тариф", "Free plan", "Bepul tarif");
  const cancelLabel = tx("Отмена", "Cancel", "Bekor qilish");
  const helpDocs = [
    ["metrics", tx("Справочник показателей", "Metrics reference", "Ko'rsatkichlar lug'ati"), tx("Формулы, термины и источники данных", "Formulas, terminology, and data sources", "Formulalar, atamalar va ma'lumot manbalari"), tx("Как читать показатели", "Reading the metrics", "Ko'rsatkichlarni o'qish")],
    ["privacy", tx("Политика конфиденциальности", "Privacy policy", "Maxfiylik siyosati"), tx("Как хранятся и обрабатываются данные аккаунта", "How account data is stored and handled", "Hisob ma'lumotlari qanday saqlanadi va ishlatiladi"), tx("Конфиденциальность", "Privacy", "Maxfiylik")],
    ["terms", tx("Условия использования", "Terms of use", "Foydalanish shartlari"), tx("Правила сервиса и ограничения аналитики", "Service rules and analysis limitations", "Xizmat qoidalari va tahlil cheklovlari"), tx("Условия", "Terms", "Shartlar")],
    ["support", tx("Написать в поддержку", "Contact support", "Yordamga yozish"), tx("Обращение уйдёт команде из вашего аккаунта", "Your request reaches the team from your account", "Murojaat hisobingizdan jamoaga yuboriladi"), tx("Новое обращение", "New support request", "Yangi murojaat")],
  ];
  const helpText = {
    metrics: tx("Оценки и коэффициенты помогают сравнивать данные, но не заменяют первичную отчётность. Наведите курсор на значок ⓘ рядом с показателем, чтобы увидеть его формулу, период и источник. Сравнивайте компании одного сектора и одинаковых отчётных периодов.", "Scores and ratios help compare data but do not replace source filings. Use the ⓘ marker beside a metric to see its formula, period, and source. Compare companies from the same sector and reporting period.", "Baholar va koeffitsiyentlar ma'lumotlarni solishtirishga yordam beradi, lekin birlamchi hisobot o'rnini bosmaydi. Formula, davr va manbani ko'rish uchun ko'rsatkich yonidagi ⓘ belgisidan foydalaning."),
    privacy: tx("Мы храним данные аккаунта, настройки, избранное, заметки и сессии для работы профиля. Пароли хранятся только в виде криптографического хеша. Данные можно скачать или удалить в разделе «Данные». Не отправляйте конфиденциальные сведения в заметках.", "We store account details, preferences, watchlists, notes, and sessions to operate your profile. Passwords are stored only as cryptographic hashes. You can export or delete your data from the Data tab. Do not place confidential information in notes.", "Profil ishlashi uchun hisob ma'lumotlari, sozlamalar, tanlanganlar, qaydlar va sessiyalar saqlanadi. Parollar faqat kriptografik xesh ko'rinishida saqlanadi. Ma'lumotlarni Ma'lumotlar bo'limida yuklash yoki o'chirish mumkin."),
    terms: tx("Платформа предоставляет информационную аналитику по публичным данным. Материалы не являются индивидуальной инвестиционной рекомендацией, гарантией результата или предложением совершить сделку. Проверяйте исходные документы и учитывайте риск потери капитала.", "The platform provides informational analytics based on public data. It is not personalized investment advice, a guarantee of results, or an offer to trade. Verify source documents and consider the risk of capital loss.", "Platforma ochiq ma'lumotlar asosida axborot tahlilini taqdim etadi. Bu shaxsiy investitsiya tavsiyasi, natija kafolati yoki savdo taklifi emas. Manba hujjatlarini tekshiring va kapital yo'qotish xavfini hisobga oling."),
  };

  return (
    <div className="profile-cmd-settings-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="profile-account-center acct" role="dialog" aria-modal="true" aria-labelledby="profile-center-title">
        <header className="acct-head">
          {avatar ? <span className="acct-head-avatar">{avatar}</span> : null}
          <div className="acct-head-text">
            <h2 id="profile-center-title">{tx("Настройки аккаунта", "Account settings", "Hisob sozlamalari")}</h2>
            <p className="acct-head-name">{user.full_name || user.email || "—"}</p>
            <p className="acct-head-meta">{[user.email, plan].filter(Boolean).join(" · ")}</p>
          </div>
          <button type="button" className="acct-close" onClick={onClose} aria-label={tx("Закрыть", "Close", "Yopish")}><CloseGlyph /></button>
        </header>

        <nav className="acct-tabs" aria-label={tx("Разделы настроек", "Settings sections", "Sozlamalar bo'limlari")}>
          {tabs.map(([key, label]) => (
            <button key={key} type="button" aria-pressed={tab === key} onClick={() => { setTab(key); setStatus(""); }}>{label}</button>
          ))}
          <button type="button" className="acct-logout" onClick={onLogout}>{tx("Выйти", "Sign out", "Chiqish")}</button>
        </nav>

        {status ? <p className={`acct-status ${statusTone}`} role="status">{status}</p> : null}

        <div className="acct-body">
          {tab === "profile" ? (
            <>
              <div className="acct-section">
                <AccountRow label="Email" hint={tx("Адрес для входа и восстановления пароля.", "Used to sign in and recover your password.", "Kirish va parolni tiklash uchun manzil.")}>
                  <div className="acct-inline">
                    <strong className="acct-value">{user.email || "—"}</strong>
                    <span className={`acct-badge ${user.email_verified ? "is-ok" : "is-warn"}`}>
                      {user.email_verified ? tx("Email подтверждён", "Email verified", "Email tasdiqlangan") : tx("Email не подтверждён", "Email not verified", "Email tasdiqlanmagan")}
                    </span>
                  </div>
                </AccountRow>
                <AccountRow label={tx("Аккаунт создан", "Member since", "Hisob yaratilgan")}>
                  <span className="acct-mono">{formatDay(user.created_at)}</span>
                </AccountRow>
              </div>
              {identityForm}
            </>
          ) : null}

          {tab === "preferences" ? (
            <form className="acct-form" onSubmit={savePreferences}>
              <div className="acct-section">
                <AccountRow label={tx("Язык", "Language", "Til")} hint={tx("Язык интерфейса на всех устройствах.", "Interface language on every device.", "Barcha qurilmalarda interfeys tili.")}>
                  <AccountChoice label={tx("Язык", "Language", "Til")} options={[["ru", "Русский"], ["uz", "O‘zbekcha"], ["en", "English"]]} value={preferences.language || language} onChange={(value) => setPreferences({ ...preferences, language: value })} />
                </AccountRow>
                <AccountRow label={tx("Тема", "Theme", "Mavzu")}>
                  <AccountChoice label={tx("Тема", "Theme", "Mavzu")} options={[["dark", tx("Тёмная", "Dark", "Qorong'i")], ["light", tx("Светлая", "Light", "Yorug'")]]} value={preferences.theme || theme} onChange={(value) => setPreferences({ ...preferences, theme: value })} />
                </AccountRow>
                <AccountRow label={tx("Размер текста", "Text size", "Matn o'lchami")} hint={tx("Масштаб всего текста на сайте.", "Scales all text on the site.", "Saytdagi barcha matn o'lchami.")}>
                  <AccountChoice label={tx("Размер текста", "Text size", "Matn o'lchami")} options={[85, 100, 115, 130].map((value) => [value, `${value}%`])} value={Number(preferences.text_scale || textScale)} onChange={(value) => setPreferences({ ...preferences, text_scale: value })} />
                </AccountRow>
                <AccountRow label={tx("Часовой пояс", "Time zone", "Vaqt mintaqasi")} hint={tx("В нём показывается время новостей и торгов.", "News and trading times are shown in it.", "Yangiliklar va savdo vaqti shu mintaqada ko'rsatiladi.")} htmlFor="acct-timezone">
                  <input id="acct-timezone" className="acct-input" value={preferences.timezone || "Asia/Tashkent"} onChange={(event) => setPreferences({ ...preferences, timezone: event.target.value })} />
                </AccountRow>
              </div>
              <AccountFooter
                note={tx("Настройки сохраняются в аккаунте и работают на всех устройствах.", "These settings follow your account across devices.", "Bu sozlamalar barcha qurilmalarda hisobingizga bog'lanadi.")}
                cancelLabel={cancelLabel}
                submitLabel={busy === "preferences" ? tx("Сохраняем…", "Saving…", "Saqlanmoqda…") : tx("Сохранить", "Save", "Saqlash")}
                busy={busy === "preferences"}
                onCancel={onClose}
              />
            </form>
          ) : null}

          {tab === "security" ? (
            <div className="acct-section">
              <AccountRow label={tx("Изменить пароль", "Change password", "Parolni o'zgartirish")} hint={tx("После смены пароля остальные сессии завершатся.", "Changing it signs out your other sessions.", "Parol o'zgarganda boshqa sessiyalar yopiladi.")}>
                <form className="acct-stack" onSubmit={changePassword}>
                  <input className="acct-input" type="password" autoComplete="current-password" aria-label={tx("Текущий пароль", "Current password", "Joriy parol")} placeholder={tx("Текущий пароль", "Current password", "Joriy parol")} value={password.current_password} onChange={(e) => setPassword({ ...password, current_password: e.target.value })} required />
                  <input className="acct-input" type="password" minLength="8" autoComplete="new-password" aria-label={tx("Новый пароль", "New password", "Yangi parol")} placeholder={tx("Новый пароль", "New password", "Yangi parol")} value={password.new_password} onChange={(e) => setPassword({ ...password, new_password: e.target.value })} required />
                  <input className="acct-input" type="password" minLength="8" autoComplete="new-password" aria-label={tx("Повторите пароль", "Confirm new password", "Parolni tasdiqlang")} placeholder={tx("Повторите новый пароль", "Confirm new password", "Yangi parolni tasdiqlang")} value={password.confirm} onChange={(e) => setPassword({ ...password, confirm: e.target.value })} required />
                  <PasswordMeter password={password.new_password} email={user.email || ""} fullName={user.full_name || ""} language={language} />
                  <div><button className="acct-btn" disabled={busy === "password" || !passwordStrength(password.new_password, { email: user.email || "", fullName: user.full_name || "" }).acceptable}>{tx("Обновить пароль", "Update password", "Parolni yangilash")}</button></div>
                </form>
              </AccountRow>
              <AccountRow label={tx("Двухфакторная защита", "Two-factor authentication", "Ikki bosqichli himoya")} hint={tx("При входе нужен код из Google Authenticator, 1Password или другого TOTP-приложения.", "Sign-in asks for a code from Google Authenticator, 1Password, or another TOTP app.", "Kirishda Google Authenticator, 1Password yoki boshqa TOTP ilovasidan kod so'raladi.")}>
                <div className="acct-inline">
                  <span className={`acct-badge ${security.two_factor_enabled ? "is-ok" : "is-warn"}`}>{security.two_factor_enabled ? tx("Включена", "Enabled", "Yoqilgan") : tx("Выключена", "Off", "O'chiq")}</span>
                  {!security.two_factor_enabled && !twoFactor ? <button className="acct-btn" type="button" onClick={beginTwoFactor} disabled={busy === "2fa"}>{tx("Настроить 2FA", "Set up 2FA", "2FA ni sozlash")}</button> : null}
                </div>
                {twoFactor ? (
                  <div className="acct-stack">
                    <p className="acct-note">{tx("Скопируйте ключ в Google Authenticator, 1Password или другое TOTP-приложение.", "Copy this key into Google Authenticator, 1Password, or another TOTP app.", "Bu kalitni Google Authenticator, 1Password yoki boshqa TOTP ilovasiga nusxalang.")}</p>
                    <code className="acct-code">{twoFactor.secret}</code>
                    <input className="acct-input acct-input-short" inputMode="numeric" autoComplete="one-time-code" aria-label={tx("Код из приложения", "Authenticator code", "Ilovadagi kod")} placeholder="000000" value={twoFactorCode} onChange={(e) => setTwoFactorCode(e.target.value)} />
                    <div><button className="acct-btn acct-btn-accent" type="button" onClick={() => confirmTwoFactor(true)} disabled={busy === "2fa" || twoFactorCode.length < 6}>{tx("Подтвердить и включить", "Verify and enable", "Tasdiqlash va yoqish")}</button></div>
                  </div>
                ) : null}
                {security.two_factor_enabled ? (
                  <div className="acct-inline">
                    <input className="acct-input acct-input-short" inputMode="numeric" autoComplete="one-time-code" aria-label={tx("Код из приложения", "Authenticator code", "Ilovadagi kod")} placeholder={tx("Код из приложения", "Authenticator code", "Ilovadagi kod")} value={twoFactorCode} onChange={(e) => setTwoFactorCode(e.target.value)} />
                    <button className="acct-btn acct-btn-danger" type="button" onClick={() => confirmTwoFactor(false)} disabled={busy === "2fa" || twoFactorCode.length < 6}>{tx("Выключить 2FA", "Disable 2FA", "2FA ni o'chirish")}</button>
                  </div>
                ) : null}
              </AccountRow>
              <AccountRow label={tx("Активные сессии", "Active sessions", "Faol sessiyalar")} hint={tx("Устройства, где выполнен вход в аккаунт.", "Devices currently signed in to your account.", "Hisobga kirilgan qurilmalar.")}>
                {sessionsLoading ? <p className="acct-note">{tx("Загрузка…", "Loading…", "Yuklanmoqda…")}</p> : (
                  <ul className="acct-sessions">
                    {sessions.map((session) => (
                      <li key={session.id}>
                        <div>
                          <strong>{session.current ? tx("Это устройство", "This device", "Bu qurilma") : (session.user_agent || tx("Неизвестное устройство", "Unknown device", "Noma'lum qurilma"))}</strong>
                          <span>{session.ip_address || "—"} · {session.last_seen_at ? new Date(session.last_seen_at).toLocaleString(locale) : "—"}</span>
                        </div>
                        {session.current
                          ? <span className="acct-badge is-ok">{tx("Текущая", "Current", "Joriy")}</span>
                          : <button type="button" className="acct-text-danger" onClick={() => revokeSession(session.id)} disabled={busy === `session-${session.id}`}>{tx("Закрыть", "Revoke", "Yopish")}</button>}
                      </li>
                    ))}
                  </ul>
                )}
                <div><button type="button" className="acct-btn" onClick={revokeOthers} disabled={busy === "sessions"}>{tx("Закрыть остальные", "Revoke others", "Boshqalarini yopish")}</button></div>
              </AccountRow>
            </div>
          ) : null}

          {tab === "notifications" ? (
            <form className="acct-form" onSubmit={savePreferences}>
              <div className="acct-section">
                <p className="acct-lead">{tx("Сигналы по компаниям из вашего избранного. Прочитанное синхронизируется между устройствами.", "Signals for the companies on your watchlist. Read state syncs across devices.", "Tanlangan kompaniyalar bo'yicha signallar. O'qilgan holat qurilmalar orasida saqlanadi.")}</p>
                <AccountSwitch label={tx("Новая отчётность", "New company reports", "Yangi hisobotlar")} hint={tx("Опубликован квартальный или годовой отчёт", "A quarterly or annual filing is published", "Choraklik yoki yillik hisobot e'lon qilindi")} checked={preferences.notify_reports ?? true} onChange={(value) => setPreferences({ ...preferences, notify_reports: value })} />
                <AccountSwitch label={tx("Новости компаний", "Company news", "Kompaniya yangiliklari")} hint={tx("Существенные факты и новости эмитента", "Material facts and issuer news", "Muhim faktlar va emitent yangiliklari")} checked={preferences.notify_news ?? true} onChange={(value) => setPreferences({ ...preferences, notify_news: value })} />
                <AccountSwitch label={tx("Ценовые уровни", "Price alerts", "Narx signallari")} hint={tx("Цена пересекла заданный вами уровень", "The price crossed a level you set", "Narx siz belgilagan darajani kesib o'tdi")} checked={preferences.notify_price ?? true} onChange={(value) => setPreferences({ ...preferences, notify_price: value })} />
                <AccountSwitch label={tx("Паттерны на графике", "Chart patterns", "Grafik patternlari")} hint={tx("На графике компании завершилась выбранная фигура — это описание, не сигнал к сделке", "A chosen figure completed on the company's chart — a description, not a trade signal", "Kompaniya grafigida tanlangan shakl yakunlandi — bu tavsif, savdo signali emas")} checked={preferences.notify_patterns ?? true} onChange={(value) => setPreferences({ ...preferences, notify_patterns: value })} />
                {(preferences.notify_patterns ?? true) ? (
                  <PatternTypePicker language={language} value={preferences.pattern_alert_types || []}
                    onChange={(types) => setPreferences({ ...preferences, pattern_alert_types: types })} />
                ) : null}
              </div>
              <AccountFooter
                note={tx("Уровни цен задаются в избранном, у каждой компании.", "Price levels are set per company on your watchlist.", "Narx darajalari tanlanganlardagi har bir kompaniya uchun belgilanadi.")}
                cancelLabel={cancelLabel}
                submitLabel={tx("Сохранить", "Save", "Saqlash")}
                busy={busy === "preferences"}
                onCancel={onClose}
              />
            </form>
          ) : null}

          {tab === "data" ? (
            <>
              <div className="acct-section">
                <AccountRow label={tx("Экспорт данных", "Export your data", "Ma'lumotlarni eksport qilish")} hint={tx("Профиль, настройки, избранное, заметки и список сессий в одном JSON-файле.", "Profile, preferences, watchlist, notes, and sessions in one JSON file.", "Profil, sozlamalar, tanlanganlar, qaydlar va sessiyalar bitta JSON faylida.")}>
                  <div><button className="acct-btn" type="button" onClick={downloadData} disabled={busy === "export"}>{tx("Скачать архив", "Download archive", "Arxivni yuklash")}</button></div>
                </AccountRow>
              </div>
              <section className="acct-danger" aria-labelledby="acct-danger-title">
                <div className="acct-row-label">
                  <strong id="acct-danger-title">{tx("Удалить аккаунт", "Delete account", "Hisobni o'chirish")}</strong>
                  <span>{tx("Профиль, избранное, заметки и сессии будут удалены без возможности восстановления.", "Your profile, watchlist, notes, and sessions are deleted for good.", "Profil, tanlanganlar, qaydlar va sessiyalar butunlay o'chiriladi.")}</span>
                </div>
                <div className="acct-stack">
                  <label htmlFor="acct-delete-confirm">{tx("Для подтверждения введите ваш email", "Type your email to confirm", "Tasdiqlash uchun emailingizni kiriting")}</label>
                  <input id="acct-delete-confirm" className="acct-input" type="email" autoComplete="off" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} placeholder={user.email || ""} />
                  <div><button className="acct-btn acct-btn-danger" type="button" onClick={deleteAccount} disabled={busy === "delete" || confirmation.toLowerCase() !== String(user.email || "").toLowerCase()}>{tx("Удалить аккаунт навсегда", "Delete account permanently", "Hisobni butunlay o'chirish")}</button></div>
                </div>
              </section>
            </>
          ) : null}

          {tab === "help" ? (
            <div className="acct-section">
              {helpDocs.map(([key, title, hint, heading]) => (
                <div className="acct-help-item" key={key}>
                  <button type="button" className="acct-link-row" aria-expanded={helpDoc === key} onClick={() => setHelpDoc(helpDoc === key ? "" : key)}>
                    <span><strong>{title}</strong><small>{hint}</small></span>
                    <ChevronGlyph />
                  </button>
                  {helpDoc === key ? (
                    <div className="acct-help-body">
                      <h4>{heading}</h4>
                      {key === "support" ? (
                        <form className="acct-stack acct-stack-wide" onSubmit={submitSupport}>
                          <label htmlFor="acct-support-subject">{tx("Тема", "Subject", "Mavzu")}</label>
                          <input id="acct-support-subject" className="acct-input" value={supportForm.subject} onChange={(event) => setSupportForm({ ...supportForm, subject: event.target.value })} minLength="2" maxLength="160" required />
                          <label htmlFor="acct-support-message">{tx("Что произошло?", "How can we help?", "Qanday yordam kerak?")}</label>
                          <textarea id="acct-support-message" className="acct-input" rows="5" value={supportForm.message} onChange={(event) => setSupportForm({ ...supportForm, message: event.target.value })} minLength="5" maxLength="6000" required />
                          <div><button className="acct-btn acct-btn-accent" disabled={busy === "support"}>{busy === "support" ? tx("Отправляем…", "Sending…", "Yuborilmoqda…") : tx("Отправить обращение", "Send request", "Murojaat yuborish")}</button></div>
                        </form>
                      ) : <p>{helpText[key]}</p>}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

export function ProfileFavoriteEditor({ item, language, apiFetch, onClose, onRefresh, onRemove }) {
  const tx = (ru, en, uz) => pick(language, ru, en, uz);
  const [form, setForm] = useState({}); const [status, setStatus] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { if (item) setForm({ position: item.position || 0, price_alert_enabled: Boolean(item.price_alert_enabled), price_alert_above: item.price_alert_above ?? "", price_alert_below: item.price_alert_below ?? "", news_alert_enabled: item.news_alert_enabled !== false, report_alert_enabled: item.report_alert_enabled !== false, pattern_alert_enabled: Boolean(item.pattern_alert_enabled) }); }, [item]);
  if (!item) return null;
  const save = async (event) => { event.preventDefault(); setBusy(true); try { await readJson(await apiFetch(`/api/favorites/${encodeURIComponent(item.ticker)}`, { method: "PATCH", body: JSON.stringify({ ...form, price_alert_above: form.price_alert_above === "" ? null : Number(form.price_alert_above), price_alert_below: form.price_alert_below === "" ? null : Number(form.price_alert_below) }) })); await onRefresh(); onClose(); } catch (error) { setStatus(error.message); } finally { setBusy(false); } };
  return <div className="profile-cmd-settings-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}><section className="profile-item-editor" role="dialog" aria-modal="true" aria-labelledby="favorite-editor-title"><header><div><span>{item.ticker}</span><h2 id="favorite-editor-title">{tx("Настройки избранного", "Watchlist settings", "Tanlanganlar sozlamasi")}</h2></div><button type="button" onClick={onClose}>×</button></header><form onSubmit={save}><SwitchRow label={tx("Ценовое уведомление", "Price alert", "Narx bildirishnomasi")} checked={form.price_alert_enabled} onChange={(value) => setForm({ ...form, price_alert_enabled: value })} /><div className="profile-center-form-grid"><label><span>{tx("Цена выше", "Price above", "Narx yuqori")}</span><input type="number" min="0" step="any" value={form.price_alert_above ?? ""} onChange={(e) => setForm({ ...form, price_alert_above: e.target.value })} /></label><label><span>{tx("Цена ниже", "Price below", "Narx past")}</span><input type="number" min="0" step="any" value={form.price_alert_below ?? ""} onChange={(e) => setForm({ ...form, price_alert_below: e.target.value })} /></label></div><SwitchRow label={tx("Новости компании", "Company news", "Kompaniya yangiliklari")} checked={form.news_alert_enabled} onChange={(value) => setForm({ ...form, news_alert_enabled: value })} /><SwitchRow label={tx("Новая отчётность", "New reports", "Yangi hisobotlar")} checked={form.report_alert_enabled} onChange={(value) => setForm({ ...form, report_alert_enabled: value })} /><SwitchRow label={tx("Паттерны на графике", "Chart patterns", "Grafik patternlari")} hint={tx("Типы паттернов выбираются в настройках уведомлений", "Pattern types are chosen in notification settings", "Pattern turlari bildirishnoma sozlamalarida tanlanadi")} checked={form.pattern_alert_enabled} onChange={(value) => setForm({ ...form, pattern_alert_enabled: value })} /><label><span>{tx("Позиция в списке", "List position", "Ro'yxat o'rni")}</span><input type="number" min="0" value={form.position ?? 0} onChange={(e) => setForm({ ...form, position: Number(e.target.value) })} /></label>{status ? <ActionStatus text={status} tone="error" /> : null}<div className="profile-item-actions"><button className="profile-cmd-primary" disabled={busy}>{tx("Сохранить", "Save", "Saqlash")}</button><button className="ghost-btn danger" type="button" onClick={() => onRemove(item)}>{tx("Убрать из избранного", "Remove from watchlist", "Tanlanganlardan o'chirish")}</button></div></form></section></div>;
}

export function ProfileNoteEditor({ note, analyses, language, apiFetch, onClose, onRefresh }) {
  const tx = (ru, en, uz) => pick(language, ru, en, uz);
  const [form, setForm] = useState({ title: "", body: "", tags: "", pinned: true, analysis_id: "" }); const [status, setStatus] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { setForm({ title: note?.title || "", body: note?.body || "", tags: (note?.tags || []).join(", "), pinned: note ? Boolean(note.pinned) : true, analysis_id: note?.analysis_id || "" }); setStatus(""); }, [note]);
  const save = async (event) => { event.preventDefault(); setBusy(true); try { const path = note ? `/api/profile/notes/${note.id}` : "/api/profile/notes"; await readJson(await apiFetch(path, { method: note ? "PATCH" : "POST", body: JSON.stringify({ ...form, analysis_id: form.analysis_id ? Number(form.analysis_id) : null, tags: form.tags.split(",").map((tag) => tag.trim()).filter(Boolean) }) })); await onRefresh(); onClose(); } catch (error) { setStatus(error.message); } finally { setBusy(false); } };
  const remove = async () => { setBusy(true); try { await readJson(await apiFetch(`/api/profile/notes/${note.id}`, { method: "DELETE" })); await onRefresh(); onClose(); } catch (error) { setStatus(error.message); } finally { setBusy(false); } };
  return <div className="profile-cmd-settings-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}><section className="profile-item-editor" role="dialog" aria-modal="true" aria-labelledby="note-editor-title"><header><div><span>{tx("Библиотека", "Library", "Kutubxona")}</span><h2 id="note-editor-title">{note ? tx("Редактировать заметку", "Edit note", "Qaydni tahrirlash") : tx("Новая заметка", "New note", "Yangi qayd")}</h2></div><button type="button" onClick={onClose}>×</button></header><form onSubmit={save}><label><span>{tx("Название", "Title", "Nomi")}</span><input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label><label><span>{tx("Текст", "Note", "Qayd")}</span><textarea rows="7" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} required /></label><div className="profile-center-form-grid"><label><span>{tx("Связать с исследованием", "Link to research", "Tahlilga bog'lash")}</span><select value={form.analysis_id} onChange={(e) => setForm({ ...form, analysis_id: e.target.value })}><option value="">—</option>{(analyses || []).map((item) => <option key={item.id} value={item.id}>{item.title || item.company_name || item.company_input}</option>)}</select></label><label><span>{tx("Теги", "Tags", "Teglar")}</span><input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} /></label></div><SwitchRow label={tx("Закрепить заметку", "Pin note", "Qaydni mahkamlash")} checked={form.pinned} onChange={(value) => setForm({ ...form, pinned: value })} />{status ? <ActionStatus text={status} tone="error" /> : null}<div className="profile-item-actions"><button className="profile-cmd-primary" disabled={busy}>{tx("Сохранить", "Save", "Saqlash")}</button>{note ? <button className="ghost-btn danger" type="button" onClick={remove}>{tx("Удалить", "Delete", "O'chirish")}</button> : null}</div></form></section></div>;
}
