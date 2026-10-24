export function CatalogAccessNotice({ language, pending, onBack }) {
  const text = (ru, uz, en) => language === "en" ? en : language === "uz" ? uz : ru;
  return (
    <section className="panel" style={{ textAlign: "center", padding: 32 }}>
      {pending ? (
        <p role="status">{text("Проверяем доступ…", "Kirish huquqi tekshirilmoqda…", "Checking access…")}</p>
      ) : (
        <>
          <h2 style={{ margin: "0 0 12px" }}>
            {text("Только для администраторов", "Faqat administratorlar uchun", "Administrators only")}
          </h2>
          <p className="muted" style={{ margin: "0 0 20px" }}>
            {text("Каталог доступен только администраторам.", "Katalog faqat administratorlar uchun mavjud.", "The catalog is available only to administrators.")}
          </p>
          <button type="button" className="primary-btn" onClick={onBack}>
            {text("Вернуться на сайт", "Saytga qaytish", "Back to the site")}
          </button>
        </>
      )}
    </section>
  );
}
