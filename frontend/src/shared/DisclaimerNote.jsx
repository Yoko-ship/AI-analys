

// Mandatory legal disclaimer (ТЗ §3.2) — shown on every page and forced into every report.
const DISCLAIMER = {
  ru: "Аналитические материалы, прогнозы и оценки, представленные на платформе, носят исключительно информационный характер и подготовлены на основе публично доступных данных. Они не являются инвестиционными рекомендациями, офертой или призывом к совершению каких-либо операций с ценными бумагами. Платформа не несёт ответственности за инвестиционные решения, принятые пользователями на основе представленной информации.",
  uz: "Platformada taqdim etilgan tahliliy materiallar, prognozlar va baholar faqat ma'lumot berish maqsadida tayyorlangan bo'lib, ommaviy ma'lumotlar asosida shakllantirilgan. Ular investitsiya tavsiyasi, taklif yoki qimmatli qog'ozlar bilan biron-bir operatsiyani amalga oshirishga undov hisoblanmaydi. Platforma foydalanuvchilar tomonidan taqdim etilgan ma'lumotlar asosida qabul qilingan investitsiya qarorlari uchun javobgar emas.",
  en: "The analytical materials, forecasts, and assessments provided on the platform are for informational purposes only and are based on publicly available data. They do not constitute investment advice, an offer, or a solicitation to conduct any transactions with securities. The platform bears no responsibility for investment decisions made by users based on the information provided.",
};

function DisclaimerNote({ language, variant = "footer" }) {
  const text = DISCLAIMER[language] || DISCLAIMER.ru;
  const label = language === "uz" ? "Ogohlantirish" : language === "en" ? "Disclaimer" : "Дисклеймер";
  return (
    <div className={`disclaimer-note disclaimer-note--${variant}`} role="note">
      <span className="disclaimer-note__label">{label}</span>
      <p className="disclaimer-note__text">{text}</p>
    </div>
  );
}

export { DisclaimerNote };
