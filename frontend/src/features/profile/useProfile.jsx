import { Suspense, useEffect, useState } from "react";
import { t } from "../../shared/i18n.jsx";
import { ProfileAvatar, readFileAsDataUrl } from "./avatar.jsx";
import { formatDateLabel, formatMarketNumber, formatSignedPercent } from "../../shared/format.jsx";
import { Icons } from "../../shared/Icons.jsx";
import { ProfileGlyph } from "./ProfileGlyph.jsx";
import { profileMarketQuote } from "../../shared/marketModel.jsx";
import { ProfileAccountCenter, ProfileFavoriteEditor, ProfileNoteEditor } from "./Editors.jsx";

export function useProfile({ session: sessionModule, toasts: toastsModule, preferences: preferencesModule, navigation: navigationModule, market: marketModule, auth: authModule, favorites: favoritesModule }) {
  const { profile, token, user, saveProfile, loadProfile, profileUser, apiFetch, hasProAccess } = sessionModule;
  const { addToast } = toastsModule;
  const { language, theme, textScale, setLanguage, setTheme, setTextScale } = preferencesModule;
  const { activeView, setActiveView, openCompanyPage } = navigationModule;
  const { companies, marketRows, securitiesMap } = marketModule;
  const { handleLogout } = authModule;
  const { handleToggleFavorite } = favoritesModule;
  const [profileForm, setProfileForm] = useState({ full_name: "" });

  const [profileAvatarFile, setProfileAvatarFile] = useState(null);

  const [profileAvatarPreview, setProfileAvatarPreview] = useState("");

  const [showProfileEdit, setShowProfileEdit] = useState(false);

  const [profileSettingsTab, setProfileSettingsTab] = useState("profile");

  const [profileFavoriteEditor, setProfileFavoriteEditor] = useState(null);

  const [profileNoteEditor, setProfileNoteEditor] = useState({ open: false, note: null });

  const [profileSaving, setProfileSaving] = useState(false);

  const [profileAvatarCleared, setProfileAvatarCleared] = useState(false);

  useEffect(() => {
    if (profile?.user?.full_name || profile?.user?.email) {
      setProfileForm((prev) =>
        prev.full_name && prev.full_name !== ""
          ? prev
          : {
              full_name: profile.user.full_name || "",
            }
      );
    }
  }, [profile]);

  const handleProfileSave = async (event) => {
    event.preventDefault();
    if (!token) {
      addToast(t(language, "auth.messages.authRequired"), "error");
      return;
    }

    const payload = {};
    const nextName = profileForm.full_name.trim();
    const currentName = (profile?.user?.full_name ?? user?.full_name ?? "").trim();

    if (nextName !== currentName) {
      payload.full_name = nextName;
    }

    if (profileAvatarFile) {
      payload.avatar_data_url = await readFileAsDataUrl(profileAvatarFile);
    } else if (profileAvatarCleared) {
      payload.avatar_data_url = null;
    }

    if (!Object.keys(payload).length) {
      addToast(t(language, "profile.noChanges"), "info");
      return;
    }

    setProfileSaving(true);
    try {
      const data = await saveProfile(payload);
      if (!data) return; // The session changed while the edit was in flight.
      setProfileAvatarFile(null);
      setProfileAvatarPreview("");
      setProfileAvatarCleared(false);
      setProfileForm({ full_name: data.user.full_name || "" });
      setShowProfileEdit(false);
      addToast(t(language, "profile.save"), "success");
      await loadProfile();
    } catch (error) {
      addToast(error.message, "error");
    } finally {
      setProfileSaving(false);
    }
  };

  const profileAvatar = profileUser?.avatar_data_url;

  const profileHistory = Array.isArray(profile?.recent_analyses) ? profile.recent_analyses : [];

  const profileFavorites = Array.isArray(profile?.favorites) ? profile.favorites : [];

  const profileNotes = Array.isArray(profile?.notes) ? profile.notes : [];

  const profileSecurity = profile?.security || {};

  const profileMemberSince = profileUser?.created_at ? `${t(language, "profile.memberSince")} ${formatDateLabel(profileUser.created_at, language)}` : "";

  const displayedProfileAvatar = profileAvatarPreview || (profileAvatarCleared ? "" : profileAvatar || "");

  const onAvatarChange = async (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      setProfileAvatarFile(null);
      setProfileAvatarPreview("");
      return;
    }
    if (!/^image\/(jpeg|png|webp)$/i.test(file.type)) {
      event.target.value = "";
      setProfileAvatarFile(null);
      setProfileAvatarPreview("");
      addToast(t(language, "profile.avatarInvalid"), "error");
      return;
    }
    if (file.size > 512 * 1024) {
      event.target.value = "";
      setProfileAvatarFile(null);
      setProfileAvatarPreview("");
      addToast(t(language, "profile.avatarTooLarge"), "error");
      return;
    }
    setProfileAvatarFile(file);
    try {
      const dataUrl = await readFileAsDataUrl(file);
      setProfileAvatarPreview(dataUrl);
      setProfileAvatarCleared(false);
    } catch (error) {
      addToast(error.message, "error");
    }
  };

  const removeAvatar = () => {
    setProfileAvatarFile(null);
    setProfileAvatarPreview("");
    setProfileAvatarCleared(true);
    addToast(language === "ru" ? "Текущий аватар будет удален после сохранения" : language === "uz" ? "Joriy avatar saqlangandan so'ng o'chiriladi" : "Current avatar will be removed after saving", "info");
  };

  const moveProfileFavorite = async (index, delta) => {
    const target = index + delta;
    if (target < 0 || target >= profileFavorites.length) return;
    const reordered = [...profileFavorites];
    [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
    try {
      await Promise.all(reordered.map((item, position) => apiFetch(`/api/favorites/${encodeURIComponent(item.ticker)}`, {
        method: "PATCH",
        body: JSON.stringify({ position }),
      }).then(async (res) => {
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not reorder watchlist");
      })));
      await loadProfile();
    } catch (error) {
      addToast(error.message, "error");
    }
  };

  const openProfileSettings = (tab = "profile") => {
    setProfileSettingsTab(tab);
    setShowProfileEdit(true);
  };

  const closeProfileSettings = () => {
    setShowProfileEdit(false);
    setProfileAvatarFile(null);
    setProfileAvatarPreview("");
    setProfileAvatarCleared(false);
    setProfileForm({ full_name: profileUser?.full_name || "" });
  };
  useEffect(() => { if (profile?.user) setProfileForm({ full_name: profile.user.full_name || "" }); }, [profile]);

  const view = <>
  {activeView === "profile" && (
              <section className="profile-command-center pf" aria-labelledby="profile-page-title">
                  {!profileUser ? (
                    <div className="pf-signed-out">
                      <span className="pf-signed-out-icon" aria-hidden="true">{Icons.lock}</span>
                      <h1 id="profile-page-title">{t(language, "profile.signedOutTitle")}</h1>
                      <p>{t(language, "profile.signedOutBody")}</p>
                      <button className="pf-btn pf-btn-accent" type="button" onClick={() => setActiveView("auth")}>
                        {t(language, "profile.signIn")}
                      </button>
                    </div>
                  ) : (
                    <>
                      <header className="pf-band pf-hero">
                        <div className="pf-hero-identity">
                          <ProfileAvatar user={profileUser} src={displayedProfileAvatar} className="pf-avatar" />
                          <h1 id="profile-page-title">{profileUser.full_name || profileUser.email.split("@")[0]}</h1>
                          <div className="pf-hero-meta">
                            {profileUser.email_verified ? (
                              <span className="pf-pill"><ProfileGlyph name="check" />{t(language, "profile.command.emailVerified")}</span>
                            ) : null}
                            <span className="pf-pill">{hasProAccess ? "PRO" : t(language, "profile.command.freePlan")}</span>
                            <span className="pf-hero-note">{[profileUser.email, profileMemberSince].filter(Boolean).join(" · ")}</span>
                          </div>
                        </div>
                        <svg className="pf-horizon" viewBox="0 0 620 244" aria-hidden="true" focusable="false">
                          {[120, 150, 186, 232].map((y) => <line key={`h${y}`} x1="0" y1={y} x2="620" y2={y} />)}
                          {[40, 160, 280, 380, 480, 600].map((x) => <line key={`v${x}`} x1="380" y1="120" x2={x} y2="244" />)}
                          <circle cx="380" cy="120" r="44" />
                        </svg>
                        <div className="pf-hero-actions">
                          <button className="pf-btn" type="button" onClick={() => openProfileSettings("profile")} aria-haspopup="dialog" aria-expanded={showProfileEdit}>
                            {t(language, "profile.command.settings")}
                          </button>
                        </div>
                      </header>

                      <section id="profile-favorites" className="pf-band pf-band-ink pf-watch" aria-labelledby="profile-favorites-title">
                        <h2 id="profile-favorites-title">{t(language, "profile.command.watchlist")}</h2>
                        {profileFavorites.length ? (
                          <ul className="pf-watch-list">
                            {profileFavorites.map((item, index) => {
                              const ticker = String(item.ticker || "").toUpperCase();
                              const company = companies.find((candidate) => String(candidate.ticker || "").toUpperCase() === ticker);
                              const quote = profileMarketQuote(ticker, marketRows, securitiesMap);
                              const direction = quote.change === null || Math.abs(quote.change) < 0.005 ? "flat" : quote.change > 0 ? "up" : "down";
                              const hasAlert = item.price_alert_enabled || item.news_alert_enabled || item.report_alert_enabled || item.pattern_alert_enabled;
                              return (
                                <li className="pf-watch-item" key={`${ticker}-${item.created_at || "saved"}`}>
                                  <button className="pf-watch-main" type="button" onClick={() => openCompanyPage(ticker)}>
                                    <strong>{ticker}</strong>
                                    <span className="sr-only">{item.company_name || company?.company_name || ticker}</span>
                                    <span className="pf-watch-quote">
                                      <span>{formatMarketNumber(quote.price, language)}</span>
                                      <span className={`pf-change is-${direction}`}>
                                        <span aria-hidden="true">{direction === "up" ? "▲" : direction === "down" ? "▼" : "●"}</span> {formatSignedPercent(quote.change, 2)}
                                      </span>
                                    </span>
                                  </button>
                                  <div className="pf-watch-actions">
                                    <button className="pf-watch-move" type="button" onClick={() => moveProfileFavorite(index, -1)} disabled={index === 0} aria-label={t(language, "profile.command.moveLeft")}>‹</button>
                                    <button className="pf-watch-move" type="button" onClick={() => moveProfileFavorite(index, 1)} disabled={index === profileFavorites.length - 1} aria-label={t(language, "profile.command.moveRight")}>›</button>
                                    <button className={hasAlert ? "has-alert" : ""} type="button" onClick={() => setProfileFavoriteEditor(item)} aria-label={t(language, "profile.command.alertSettings")}>
                                      <ProfileGlyph name="bell" />
                                    </button>
                                  </div>
                                </li>
                              );
                            })}
                          </ul>
                        ) : (
                          <p className="pf-watch-empty">{t(language, "profile.favoritesEmpty")}</p>
                        )}
                        <button className="pf-btn pf-btn-on-ink" type="button" onClick={() => setActiveView("catalog")}>
                          <span aria-hidden="true">＋</span>{t(language, "profile.command.addTicker")}
                        </button>
                      </section>

                      <div className="pf-band pf-lower">
                        <section className="pf-lower-col" aria-labelledby="profile-notes-title">
                          <div className="pf-col-head">
                            <h2 id="profile-notes-title">{t(language, "profile.command.pinnedNotes")}</h2>
                            <button type="button" onClick={() => setProfileNoteEditor({ open: true, note: null })}>
                              <span aria-hidden="true">＋</span> {t(language, "profile.command.newNote")}
                            </button>
                          </div>
                          {profileNotes.length ? profileNotes.slice(0, 3).map((item) => (
                            <button type="button" className="pf-note" key={item.id} onClick={() => setProfileNoteEditor({ open: true, note: item })}>
                              <strong>{item.title || t(language, "profile.command.untitledNote")}</strong>
                              <small>{item.body}</small>
                            </button>
                          )) : (
                            <p className="pf-muted">{t(language, "profile.command.noNotes")}</p>
                          )}
                        </section>

                        <nav className="pf-lower-col pf-account" aria-labelledby="profile-account-title">
                          <h2 id="profile-account-title">{t(language, "profile.command.account")}</h2>
                          <button type="button" onClick={() => openProfileSettings("preferences")}>
                            <span>{t(language, "profile.command.interface")}</span><span aria-hidden="true">›</span>
                          </button>
                          <button type="button" onClick={() => openProfileSettings("security")}>
                            <span>{t(language, "profile.command.access")}</span>
                            {profileSecurity.two_factor_enabled ? <span aria-hidden="true">›</span> : <small>{t(language, "profile.command.twoFactorOff")}</small>}
                          </button>
                          <button type="button" onClick={() => openProfileSettings("notifications")}>
                            <span>{t(language, "profile.command.notifications")}</span><span aria-hidden="true">›</span>
                          </button>
                          <button type="button" onClick={() => openProfileSettings("data")}>
                            <span>{t(language, "profile.command.dataPrivacy")}</span><span aria-hidden="true">›</span>
                          </button>
                          <button type="button" className="pf-account-logout" onClick={handleLogout}>
                            <span>{t(language, "auth.logout")}</span><span aria-hidden="true">↪</span>
                          </button>
                        </nav>
                      </div>
                    </>
                  )}

                {profileUser ? (
                  <Suspense fallback={null}><ProfileAccountCenter
                    open={showProfileEdit}
                    initialTab={profileSettingsTab}
                    profile={profile}
                    language={language}
                    theme={theme}
                    textScale={textScale}
                    apiFetch={apiFetch}
                    onClose={closeProfileSettings}
                    onRefresh={loadProfile}
                    onLogout={handleLogout}
                    onLanguage={setLanguage}
                    onTheme={setTheme}
                    onTextScale={setTextScale}
                    avatar={<ProfileAvatar user={profileUser} src={displayedProfileAvatar} />}
                    identityForm={(
                      <form className="acct-form" onSubmit={handleProfileSave}>
                        <div className="acct-section">
                          <div className="acct-row">
                            <div className="acct-row-label">
                              <label htmlFor="profile-display-name">{t(language, "profile.name")}</label>
                              <span>{language === "en" ? "Shown in the account menu and on your notes." : language === "uz" ? "Hisob menyusida va qaydlaringizda ko'rinadi." : "Так вас видно в меню аккаунта и в заметках."}</span>
                            </div>
                            <div className="acct-row-control">
                              <input id="profile-display-name" className="acct-input" type="text" maxLength="120" autoComplete="name" value={profileForm.full_name} onChange={(event) => setProfileForm({ full_name: event.target.value })} placeholder={t(language, "profile.name")} />
                            </div>
                          </div>
                          <div className="acct-row">
                            <div className="acct-row-label">
                              <strong>{t(language, "profile.avatar")}</strong>
                              <span id="avatar-input-hint">{t(language, "profile.avatarHint")}</span>
                            </div>
                            <div className="acct-row-control">
                              <div className="acct-inline">
                                <ProfileAvatar user={profileUser} src={displayedProfileAvatar} className="profile-avatar-editor-preview acct-avatar-preview" />
                                <input type="file" className="acct-file" accept="image/jpeg,image/png,image/webp" onChange={onAvatarChange} id="avatar-input" aria-describedby="avatar-input-hint" />
                                <label htmlFor="avatar-input" className="acct-btn"><span aria-hidden="true">＋</span>{language === "en" ? "Choose image" : language === "uz" ? "Rasm tanlash" : "Выбрать изображение"}</label>
                                {displayedProfileAvatar ? <button type="button" className="acct-btn acct-btn-ghost" onClick={removeAvatar}>{t(language, "profile.clearAvatar")}</button> : null}
                              </div>
                              {profileAvatarCleared ? <span className="acct-note">{language === "en" ? "Avatar will be removed after saving" : language === "uz" ? "Avatar saqlangandan keyin o'chiriladi" : "Аватар будет удалён после сохранения"}</span> : null}
                            </div>
                          </div>
                        </div>
                        <footer className="acct-footer">
                          <span />
                          <button type="button" className="acct-btn acct-btn-ghost" onClick={closeProfileSettings}>{language === "en" ? "Cancel" : language === "uz" ? "Bekor qilish" : "Отмена"}</button>
                          <button className="acct-btn acct-btn-accent" type="submit" disabled={profileSaving}>{profileSaving ? t(language, "profile.saving") : t(language, "profile.saveChanges")}</button>
                        </footer>
                      </form>
                    )}
                  /></Suspense>
                ) : null}
                <Suspense fallback={null}>
                  <ProfileFavoriteEditor item={profileFavoriteEditor} language={language} apiFetch={apiFetch} onClose={() => setProfileFavoriteEditor(null)} onRefresh={loadProfile} onRemove={async (item) => { await handleToggleFavorite(item.ticker, item.company_name); setProfileFavoriteEditor(null); }} />
                  {profileNoteEditor.open ? <ProfileNoteEditor note={profileNoteEditor.note} analyses={profileHistory} language={language} apiFetch={apiFetch} onClose={() => setProfileNoteEditor({ open: false, note: null })} onRefresh={loadProfile} /> : null}
                </Suspense>
              </section>
            )}
  </>;
  return { view };
}
