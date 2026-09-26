import { useState } from "react";

function FeedbackPage({ language, signedIn, apiFetch, onSignIn }) {
  const tx = (ru, uz, en) => language === "uz" ? uz : language === "en" ? en : ru;
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    setSending(true);
    setNotice("");
    try {
      const response = await apiFetch("/api/profile/support", {
        method: "POST",
        body: JSON.stringify({ subject: tx("Обратная связь", "Fikr-mulohaza", "Feedback"), message }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || tx("Не удалось отправить сообщение.", "Xabar yuborilmadi.", "Could not send the message."));
      setMessage("");
      setNotice(tx("Спасибо! Ваше сообщение отправлено.", "Rahmat! Xabaringiz yuborildi.", "Thank you! Your feedback was sent."));
    } catch (error) {
      setNotice(error.message || tx("Не удалось отправить сообщение.", "Xabar yuborilmadi.", "Could not send the message."));
    } finally {
      setSending(false);
    }
  };

  return <section className="feedback-page" style={{ maxWidth: 720, margin: "0 auto", padding: "42px 0" }}>
    <article className="panel" style={{ padding: "clamp(24px, 5vw, 44px)" }}>
      <div className="panel-label">UZSTOCK</div>
      <h1 style={{ margin: "8px 0 10px" }}>{tx("Обратная связь", "Fikr-mulohaza", "Feedback")}</h1>
      <p className="muted" style={{ maxWidth: "60ch", lineHeight: 1.55 }}>
        {tx("Расскажите, что стоит улучшить, чего вам не хватает или что работает особенно хорошо. Мы читаем все сообщения.", "Nimani yaxshilash kerakligi, nima yetishmasligi yoki nima ayniqsa yaxshi ishlashi haqida yozing. Biz barcha xabarlarni o'qiymiz.", "Tell us what to improve, what is missing, or what works especially well. We read every message.")}
      </p>
      {!signedIn ? <div style={{ marginTop: 24 }}>
        <p>{tx("Чтобы отправить отзыв и при необходимости получить ответ, войдите в аккаунт.", "Fikr yuborish va zarur bo'lsa javob olish uchun hisobga kiring.", "Sign in to send feedback and receive a reply if needed.")}</p>
        <button className="primary-btn" type="button" onClick={onSignIn}>{tx("Войти", "Kirish", "Sign in")}</button>
      </div> : <form onSubmit={submit} style={{ marginTop: 24 }}>
        <label className="field" style={{ display: "block" }}>
          <span>{tx("Ваше сообщение", "Xabaringiz", "Your message")}</span>
          <textarea rows="7" value={message} onChange={(event) => setMessage(event.target.value)} minLength="5" maxLength="6000" required
            placeholder={tx("Например: какую функцию вы хотели бы увидеть?", "Masalan: qaysi funksiyani ko'rishni xohlaysiz?", "For example: which feature would you like to see?")}
            style={{ width: "100%", marginTop: 8, resize: "vertical" }} />
        </label>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 18 }}>
          <button className="primary-btn" type="submit" disabled={sending}>{sending ? tx("Отправляем…", "Yuborilmoqda…", "Sending…") : tx("Отправить", "Yuborish", "Send feedback")}</button>
          {notice && <span className="muted" role="status">{notice}</span>}
        </div>
      </form>}
    </article>
  </section>;
}

export { FeedbackPage };
