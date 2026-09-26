import { Icons } from "./Icons.jsx";

function ProFeatureGate({ language, title, description, signedIn, onUpgrade }) {
  const copy = language === "en"
    ? { eyebrow: "PRO feature", signIn: "Sign in", upgrade: "View PRO access" }
    : language === "uz"
      ? { eyebrow: "PRO funksiya", signIn: "Kirish", upgrade: "PRO kirishni ko‘rish" }
      : { eyebrow: "PRO-функция", signIn: "Войти", upgrade: "Открыть PRO-доступ" };
  return (
    <section className="pro-gate panel" aria-label={title}>
      <div className="panel-label">{copy.eyebrow}</div>
      <span className="pro-gate-icon" aria-hidden="true">{Icons.lock}</span>
      <h1>{title}</h1>
      <p>{description}</p>
      <p className="muted">
        {language === "en"
          ? "The feature stays named and explained here; access is controlled by your account tier."
          : language === "uz"
            ? "Funksiya nomi va qisqa izohi saqlanadi; kirish hisobingiz tarifiga bog‘liq."
            : "Название и краткое объяснение функции сохранены; доступ зависит от тарифа аккаунта."}
      </p>
      <button type="button" className="primary-btn" onClick={onUpgrade}>
        {signedIn ? copy.upgrade : copy.signIn}
      </button>
    </section>
  );
}

export { ProFeatureGate };
