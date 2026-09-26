import { useEffect, useState } from "react";
import { REMEMBER_KEY as AUTH_REMEMBER_KEY } from "../../session/session.js";
import { t } from "../../shared/i18n.jsx";
import { passwordStrength, translateAuthError } from "../../lib/passwordStrength.js";
import { authPageText } from "./copy.jsx";
import { profileMarketQuote } from "../../shared/marketModel.jsx";
import { formatSignedPercent } from "../../shared/format.jsx";
import { BrandIcon } from "../../shared/BrandIcon.jsx";
import { PasswordMeter } from "../../PasswordMeter.jsx";

export function useAuthentication({ navigation: navigationModule, session: sessionModule, toasts: toastsModule, preferences: preferencesModule, market: marketModule }) {
  const { activeView, setActiveView } = navigationModule;
  const { acceptSession, loadProfile, endSession, token, profileUser } = sessionModule;
  const { addToast } = toastsModule;
  const { language } = preferencesModule;
  const { marketRows, securitiesMap } = marketModule;
  const [authTab, setAuthTab] = useState("login");

  const [loginForm, setLoginForm] = useState({ email: "", password: "", otp: "" });

  const [authOtpRequired, setAuthOtpRequired] = useState(false);

  const [authFlow, setAuthFlow] = useState(null);

  const [authCode, setAuthCode] = useState("");

  const [resetNewPassword, setResetNewPassword] = useState("");

  const [resendAt, setResendAt] = useState(0);

  const [resendTick, setResendTick] = useState(0);

  const [emailCodesEnabled, setEmailCodesEnabled] = useState(false);

  useEffect(() => {
    if (activeView !== "auth") return undefined;
    let alive = true;
    fetch("/api/auth/options")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => { if (alive && data) setEmailCodesEnabled(Boolean(data.email_codes)); })
      .catch(() => {});
    return () => { alive = false; };
  }, [activeView]);

  useEffect(() => {
    if (!authFlow || resendAt <= Date.now()) return undefined;
    const timer = window.setTimeout(() => setResendTick((n) => n + 1), 1000);
    return () => window.clearTimeout(timer);
  }, [authFlow, resendAt, resendTick]);

  const [registerForm, setRegisterForm] = useState({ full_name: "", email: "", password: "" });

  const [authMessage, setAuthMessage] = useState("");

  const [rememberLogin, setRememberLogin] = useState(() => localStorage.getItem(AUTH_REMEMBER_KEY) !== "0");

  const [showLoginPassword, setShowLoginPassword] = useState(false);

  const [showRegisterPassword, setShowRegisterPassword] = useState(false);

  useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const oauthError = hash.get("oauth_error") || hash.get("error");
    const oauthCode = hash.get("oauth_code");
    const provider = hash.get("provider") || hash.get("oauth");

    const finishLogin = (newToken, providerName) => {
      acceptSession({ token: newToken }, { remember: rememberLogin });
      const providerLabel = providerName === "google" ? "Google" : providerName || "";
      addToast(providerLabel ? `${providerLabel}: ${t(language, "auth.messages.loginOk")}` : t(language, "auth.messages.loginOk"), "success");
      setActiveView("profile");
    };

    if (oauthError) {
      addToast(decodeURIComponent(oauthError.replace(/\+/g, " ")), "error");
      clearHash();
    } else if (oauthCode) {
      // The redirect carries a short-lived one-time code, never the token
      // itself (a token in the URL survives in history/logs). Exchange it.
      clearHash();
      fetch("/api/auth/oauth/exchange", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: oauthCode }),
      })
        .then((r) => r.json())
        .then((d) => {
          if (d.ok && d.token) finishLogin(d.token, d.provider || provider);
          else addToast(d.detail || "Sign-in failed", "error");
        })
        .catch(() => addToast("Sign-in failed", "error"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const clearHash = () => {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  };

  const setAuthSuccess = (data) => {
    acceptSession(data, { remember: rememberLogin });
    setAuthMessage(t(language, "auth.messages.loginOk"));
    setAuthOtpRequired(false);
    setLoginForm((current) => ({ ...current, otp: "" }));
    addToast(t(language, "auth.messages.loginOk"), "success");
    setActiveView("profile");
  };

  const handleLogin = async (event) => {
    event.preventDefault();
    setAuthMessage("...");
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...loginForm, language }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Request failed");
      if (data.verification_required) {
        startEmailVerification(data, loginForm.password, "");
        return;
      }
      setAuthSuccess(data);
      setAuthMessage(t(language, "auth.messages.loginOk"));
      await loadProfile();
    } catch (error) {
      if (/two-factor code required/i.test(error.message)) setAuthOtpRequired(true);
      const message = translateAuthError(error.message, language);
      setAuthMessage(message);
      addToast(message, "error");
    }
  };

  const handleRegister = async (event) => {
    event.preventDefault();
    setAuthMessage("...");
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...registerForm, language }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Request failed");
      if (data.verification_required) {
        startEmailVerification(data, registerForm.password, registerForm.full_name);
        return;
      }
      setAuthSuccess(data);
      setAuthMessage(t(language, "auth.messages.registerOk"));
      await loadProfile();
    } catch (error) {
      const message = translateAuthError(error.message, language);
      setAuthMessage(message);
      addToast(message, "error");
    }
  };

  const postAuthJson = async (path, body) => {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed");
    return data;
  };

  const authFlowFailed = (error) => {
    const message = translateAuthError(error.message, language);
    setAuthMessage(message);
    addToast(message, "error");
  };

  const startEmailVerification = (data, password, fullName) => {
    setAuthFlow({ kind: "verify", email: data.email, password, full_name: fullName });
    setAuthCode("");
    setResendAt(Date.now() + (data.retry_after || 60) * 1000);
    setAuthMessage("");
  };

  const leaveAuthFlow = (message = "") => {
    setAuthFlow(null);
    setAuthCode("");
    setResetNewPassword("");
    setAuthTab("login");
    setAuthMessage(message);
  };

  const finishCodeSignIn = async (data, signInMessage) => {
    if (data.token) {
      leaveAuthFlow();
      setAuthSuccess(data);
      await loadProfile();
      return;
    }
    leaveAuthFlow(signInMessage);
    setAuthOtpRequired(true);
  };

  const handleVerifyEmail = async (event) => {
    event.preventDefault();
    setAuthMessage("...");
    try {
      const data = await postAuthJson("/api/auth/email/verify", {
        email: authFlow.email,
        code: authCode,
        password: authFlow.password || undefined,
        full_name: authFlow.full_name || undefined,
      });
      await finishCodeSignIn(data, authCopy.verifiedSignIn);
    } catch (error) {
      authFlowFailed(error);
    }
  };

  const handleResendCode = async () => {
    try {
      const path = authFlow.kind === "forgot" ? "/api/auth/password/forgot" : "/api/auth/email/resend";
      await postAuthJson(path, { email: authFlow.email, language });
      setResendAt(Date.now() + 60 * 1000);
      setAuthMessage(authCopy.resent);
    } catch (error) {
      authFlowFailed(error);
    }
  };

  const handleForgotRequest = async (event) => {
    event.preventDefault();
    setAuthMessage("...");
    try {
      await postAuthJson("/api/auth/password/forgot", { email: authFlow.email, language });
      setAuthFlow({ kind: "forgot", step: "code", email: authFlow.email.trim().toLowerCase() });
      setAuthCode("");
      setResendAt(Date.now() + 60 * 1000);
      setAuthMessage("");
    } catch (error) {
      authFlowFailed(error);
    }
  };

  const handlePasswordReset = async (event) => {
    event.preventDefault();
    setAuthMessage("...");
    try {
      const data = await postAuthJson("/api/auth/password/reset", {
        email: authFlow.email,
        code: authCode,
        new_password: resetNewPassword,
      });
      await finishCodeSignIn(data, authCopy.resetDone);
    } catch (error) {
      authFlowFailed(error);
    }
  };

  const handleGoogleLogin = () => {
    localStorage.setItem(AUTH_REMEMBER_KEY, rememberLogin ? "1" : "0");
    window.location.href = "/api/auth/oauth/google/start";
  };

  const handleLogout = async () => {
    const revoked = endSession();
    setActiveView("auth");
    addToast(t(language, "auth.messages.logoutOk"), "info");
    await revoked;
  };

  const authCopy = authPageText(language);

  const authMarketItems = (Array.isArray(marketRows) ? marketRows : [])
    .map((row) => {
      const ticker = String(row?.ticker || "").trim().toUpperCase();
      if (!ticker) return null;
      return { ticker, ...profileMarketQuote(ticker, marketRows, securitiesMap) };
    })
    .filter(Boolean)
    .slice(0, 5);

  const view = <>
  {activeView === "auth" && (
              <section className="auth-hub-page" aria-labelledby="auth-page-title">
                <div className="auth-market-strip" aria-label={authCopy.market}>
                  <span className="auth-market-label">{authCopy.market}</span>
                  {authMarketItems.length ? authMarketItems.map((item) => (
                    <span className="auth-market-item" key={item.ticker}>
                      <strong>{item.ticker}</strong>
                      {item.change !== null ? (
                        <span className={item.change > 0 ? "is-up" : item.change < 0 ? "is-down" : "is-flat"}>
                          {formatSignedPercent(item.change, 2)}
                        </span>
                      ) : null}
                    </span>
                  )) : <span className="auth-market-fallback">{authCopy.marketFallback}</span>}
                </div>

                <article className="auth-hub-card">
                  <BrandIcon className="auth-hub-logo" decorative />

                  {token && profileUser ? (
                    <div className="auth-signed-in">
                      <div className="auth-hub-heading">
                        <h1 id="auth-page-title">{authCopy.signedInTitle}</h1>
                        <p>{authCopy.signedInSubtitle}</p>
                      </div>
                      <div className="auth-account-summary">
                        <strong>{profileUser.full_name || profileUser.email}</strong>
                        <span>{profileUser.email}</span>
                      </div>
                      <button className="auth-primary-button" type="button" onClick={() => setActiveView("profile")}>
                        {authCopy.openProfile}
                        <span aria-hidden="true">→</span>
                      </button>
                      <button className="auth-secondary-button" type="button" onClick={handleLogout}>
                        {t(language, "auth.logout")}
                      </button>
                    </div>
                  ) : authFlow ? (
                    <div className="auth-code-flow">
                      <div className="auth-hub-heading">
                        <h1 id="auth-page-title">{authFlow.kind === "verify" ? authCopy.verifyTitle : authCopy.forgotTitle}</h1>
                        <p>
                          {authFlow.kind === "verify"
                            ? authCopy.verifySubtitle.replace("{email}", authFlow.email)
                            : authFlow.step === "code"
                              ? authCopy.resetSubtitle.replace("{email}", authFlow.email)
                              : authCopy.forgotSubtitle}
                        </p>
                      </div>

                      {authFlow.kind === "forgot" && authFlow.step === "email" ? (
                        <form className="auth-hub-form" onSubmit={handleForgotRequest}>
                          <label className="auth-field">
                            <span>{t(language, "auth.login.email")}</span>
                            <input
                              type="email"
                              autoComplete="email"
                              value={authFlow.email}
                              onChange={(event) => setAuthFlow({ ...authFlow, email: event.target.value })}
                              placeholder="name@example.com"
                              required
                            />
                          </label>
                          <button className="auth-primary-button" type="submit">
                            {authCopy.forgotSubmit}
                            <span aria-hidden="true">→</span>
                          </button>
                        </form>
                      ) : (
                        <form className="auth-hub-form" onSubmit={authFlow.kind === "verify" ? handleVerifyEmail : handlePasswordReset}>
                          <label className="auth-field">
                            <span>{authCopy.codeLabel}</span>
                            <input
                              className="auth-code-input"
                              type="text"
                              inputMode="numeric"
                              autoComplete="one-time-code"
                              value={authCode}
                              onChange={(event) => setAuthCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                              placeholder="000000"
                              autoFocus
                              required
                            />
                          </label>
                          {authFlow.kind === "forgot" ? (
                            <label className="auth-field">
                              <span>{authCopy.newPassword}</span>
                              <input
                                type="password"
                                autoComplete="new-password"
                                minLength={8}
                                value={resetNewPassword}
                                onChange={(event) => setResetNewPassword(event.target.value)}
                                placeholder="••••••••"
                                required
                              />
                            </label>
                          ) : null}
                          {authFlow.kind === "forgot" ? (
                            <PasswordMeter password={resetNewPassword} email={authFlow.email} language={language} />
                          ) : null}
                          <button className="auth-primary-button" type="submit"
                            disabled={authCode.length !== 6 || (authFlow.kind === "forgot" && !passwordStrength(resetNewPassword, { email: authFlow.email }).acceptable)}>
                            {authFlow.kind === "verify" ? authCopy.verifySubmit : authCopy.resetSubmit}
                            <span aria-hidden="true">→</span>
                          </button>
                          {(() => {
                            const wait = Math.max(0, Math.ceil((resendAt - Date.now()) / 1000));
                            return (
                              <button className="auth-link-button" type="button" disabled={wait > 0} onClick={handleResendCode}>
                                {wait > 0 ? authCopy.resendIn.replace("{seconds}", wait) : authCopy.resend}
                              </button>
                            );
                          })()}
                        </form>
                      )}

                      <button className="auth-secondary-button auth-code-back" type="button" onClick={() => leaveAuthFlow()}>
                        {authCopy.back}
                      </button>
                      <div className="auth-message" role="status" aria-live="polite">{authMessage}</div>
                    </div>
                  ) : (
                    <>
                      <div className="auth-hub-heading">
                        <h1 id="auth-page-title">{authTab === "login" ? authCopy.title : authCopy.registerTitle}</h1>
                        <p>{authTab === "login" ? authCopy.subtitle : authCopy.registerSubtitle}</p>
                      </div>

                      <div className="auth-mode-tabs" role="tablist" aria-label={t(language, "auth.title")}>
                        <button type="button" role="tab" aria-selected={authTab === "login"} className={authTab === "login" ? "is-active" : ""} onClick={() => { setAuthTab("login"); setAuthMessage(""); }}>
                          {t(language, "auth.loginTab")}
                        </button>
                        <button type="button" role="tab" aria-selected={authTab === "register"} className={authTab === "register" ? "is-active" : ""} onClick={() => { setAuthTab("register"); setAuthMessage(""); }}>
                          {t(language, "auth.registerTab")}
                        </button>
                      </div>

                      {authTab === "login" ? (
                        <form className="auth-hub-form" onSubmit={handleLogin}>
                          <label className="auth-field">
                            <span>{t(language, "auth.login.email")}</span>
                            <input
                              type="email"
                              autoComplete="email"
                              value={loginForm.email}
                              onChange={(event) => setLoginForm({ ...loginForm, email: event.target.value })}
                              placeholder="name@example.com"
                              required
                            />
                          </label>
                          <label className="auth-field">
                            <span>{t(language, "auth.login.password")}</span>
                            <span className="auth-password-field">
                              <input
                                type={showLoginPassword ? "text" : "password"}
                                autoComplete="current-password"
                                value={loginForm.password}
                                onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })}
                                placeholder="••••••••"
                                required
                              />
                              <button type="button" className="auth-password-toggle" aria-label={showLoginPassword ? authCopy.hidePassword : authCopy.showPassword} aria-pressed={showLoginPassword} onClick={() => setShowLoginPassword((shown) => !shown)}>
                                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                  <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />
                                  <circle cx="12" cy="12" r="2.5" />
                                </svg>
                              </button>
                            </span>
                          </label>
                          {authOtpRequired ? (
                            <label className="auth-field">
                              <span>{language === "en" ? "Authenticator code" : language === "uz" ? "Autentifikator kodi" : "Код из приложения"}</span>
                              <input
                                type="text"
                                inputMode="numeric"
                                autoComplete="one-time-code"
                                maxLength="6"
                                value={loginForm.otp}
                                onChange={(event) => setLoginForm({ ...loginForm, otp: event.target.value.replace(/\D/g, "") })}
                                placeholder="000000"
                                required
                              />
                            </label>
                          ) : null}
                          <div className="auth-row">
                            <label className="auth-remember">
                              <input type="checkbox" checked={rememberLogin} onChange={(event) => setRememberLogin(event.target.checked)} />
                              <span>{authCopy.remember}</span>
                            </label>
                            {emailCodesEnabled ? (
                              <button className="auth-link-button" type="button"
                                onClick={() => { setAuthFlow({ kind: "forgot", step: "email", email: loginForm.email }); setAuthMessage(""); }}>
                                {authCopy.forgotLink}
                              </button>
                            ) : null}
                          </div>
                          <button className="auth-primary-button" type="submit">
                            {t(language, "auth.login.submit")}
                            <span aria-hidden="true">→</span>
                          </button>
                        </form>
                      ) : (
                        <form className="auth-hub-form" onSubmit={handleRegister}>
                          <label className="auth-field">
                            <span>{t(language, "auth.register.fullName")}</span>
                            <input
                              type="text"
                              autoComplete="name"
                              value={registerForm.full_name}
                              onChange={(event) => setRegisterForm({ ...registerForm, full_name: event.target.value })}
                              placeholder={t(language, "auth.register.fullName")}
                            />
                          </label>
                          <label className="auth-field">
                            <span>{t(language, "auth.register.email")}</span>
                            <input
                              type="email"
                              autoComplete="email"
                              value={registerForm.email}
                              onChange={(event) => setRegisterForm({ ...registerForm, email: event.target.value })}
                              placeholder="name@example.com"
                              required
                            />
                          </label>
                          <label className="auth-field">
                            <span>{t(language, "auth.register.password")}</span>
                            <span className="auth-password-field">
                              <input
                                type={showRegisterPassword ? "text" : "password"}
                                autoComplete="new-password"
                                value={registerForm.password}
                                onChange={(event) => setRegisterForm({ ...registerForm, password: event.target.value })}
                                placeholder="••••••••"
                                aria-describedby="register-password-meter"
                                required
                              />
                              <button type="button" className="auth-password-toggle" aria-label={showRegisterPassword ? authCopy.hidePassword : authCopy.showPassword} aria-pressed={showRegisterPassword} onClick={() => setShowRegisterPassword((shown) => !shown)}>
                                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                  <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />
                                  <circle cx="12" cy="12" r="2.5" />
                                </svg>
                              </button>
                            </span>
                          </label>
                          <div id="register-password-meter">
                            <PasswordMeter password={registerForm.password} email={registerForm.email} fullName={registerForm.full_name} language={language} />
                          </div>
                          <button className="auth-primary-button" type="submit"
                            disabled={!passwordStrength(registerForm.password, { email: registerForm.email, fullName: registerForm.full_name }).acceptable}>
                            {t(language, "auth.register.submit")}
                            <span aria-hidden="true">→</span>
                          </button>
                        </form>
                      )}

                      <div className="auth-divider"><span>{authCopy.divider}</span></div>
                      <button className="auth-google-button" type="button" onClick={handleGoogleLogin}>
                        <span className="auth-google-mark" aria-hidden="true">G</span>
                        {authCopy.google}
                      </button>
                      <div className="auth-message" role="status" aria-live="polite">{authMessage}</div>
                    </>
                  )}
                </article>

                <p className="auth-privacy-note">{authCopy.privacy}</p>
              </section>
            )}
  </>;
  return { handleLogout, view };
}
