import { useState, useSyncExternalStore } from "react";
import { answerStepUp, getStepUp, subscribeStepUp } from "./stepUp.js";

const TEXT = {
  ru: { title: "Подтвердите действие", body: "Введите код из приложения-аутентификатора. Следующие 15 минут он не понадобится.", submit: "Подтвердить", cancel: "Отмена", invalid: "Неверный код. Попробуйте ещё раз." },
  uz: { title: "Amalni tasdiqlang", body: "Autentifikator ilovasidagi kodni kiriting. Keyingi 15 daqiqa u kerak bo‘lmaydi.", submit: "Tasdiqlash", cancel: "Bekor qilish", invalid: "Kod noto‘g‘ri. Qayta urinib ko‘ring." },
  en: { title: "Confirm this action", body: "Enter the code from your authenticator app. You won't be asked again for 15 minutes.", submit: "Confirm", cancel: "Cancel", invalid: "Invalid code. Try again." },
};

/** Asks for the authenticator code when an admin change needs it (session.js). */
export function StepUpDialog({ language }) {
  const request = useSyncExternalStore(subscribeStepUp, getStepUp);
  const [code, setCode] = useState("");
  if (!request) return null;
  const text = TEXT[language] || TEXT.en;
  const close = (value) => { setCode(""); answerStepUp(value); };
  return (
    <div className="profile-cmd-settings-backdrop" role="presentation"
      onMouseDown={(event) => { if (event.target === event.currentTarget) close(null); }}>
      <section className="profile-item-editor" role="dialog" aria-modal="true" aria-labelledby="step-up-title">
        <header><div><h2 id="step-up-title">{text.title}</h2></div>
          <button type="button" aria-label={text.cancel} onClick={() => close(null)}>×</button></header>
        <form onSubmit={(event) => { event.preventDefault(); close(code); }}>
          <p>{text.body}</p>
          <label>
            <input type="text" inputMode="numeric" autoComplete="one-time-code" maxLength="6" placeholder="000000"
              value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))} autoFocus required />
          </label>
          {request.message ? <p role="alert">{text.invalid}</p> : null}
          <div className="profile-item-actions">
            <button className="profile-cmd-primary" disabled={code.length !== 6}>{text.submit}</button>
            <button className="ghost-btn" type="button" onClick={() => close(null)}>{text.cancel}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
