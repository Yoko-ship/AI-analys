import { useEffect, useRef, useState } from "react";
import { Skeleton } from "./AdminWidgets.jsx";

function PostEditor({ idea, edition, t }) {
  const [edits, setEdits] = useState({});
  const [notice, setNotice] = useState(null);
  const field = useRef(null);
  const draft = edits[edition] ?? idea[edition].text;

  async function copy() {
    try {
      await navigator.clipboard.writeText(draft);
      setNotice({ edition, draft, copied: true });
    } catch {
      field.current?.select();
      setNotice({ edition, draft, copied: false });
    }
  }

  const message = notice?.edition === edition && notice.draft === draft && (
    notice.copied
      ? t("Скопировано", "Nusxalandi", "Copied")
      : t("Выделите и скопируйте текст вручную.", "Matnni belgilang va nusxalang.", "Select the text and copy it manually.")
  );
  return <article className="panel marketing-pitch">
    <div className="marketing-copy">
      <label>
        <strong>{t("Пост для Telegram", "Telegram posti", "Telegram post")}</strong>
        <textarea ref={field} lang={edition} value={draft} rows={9} maxLength={4096}
          onChange={event => {
            setEdits({ ...edits, [edition]: event.target.value });
            setNotice(null);
          }} />
      </label>
      <div className="marketing-actions">
        <button type="button" className="admin-btn accent" disabled={!draft.trim()} onClick={copy}>
          {t("Скопировать для Telegram", "Telegram uchun nusxalash", "Copy for Telegram")}
        </button>
        <span role="status">{message}</span>
      </div>
    </div>
    <aside className="marketing-evidence">
      <h3>{t("Кому это интересно", "Kimga qiziq", "Who would share this")}</h3>
      <p lang={edition}>{idea[edition].reason}</p>
      <h3>{t("Источник", "Manba", "Source")}</h3>
      <blockquote>{idea.excerpt}</blockquote>
      <a href={idea.url} target="_blank" rel="noreferrer">{idea.source || idea.title}</a>
      {idea.published_at && <time dateTime={idea.published_at}>{idea.published_at.slice(0, 10)}</time>}
    </aside>
  </article>;
}

export function MarketingSection({ apiFetch, language, t }) {
  const [edition, setEdition] = useState(language === "uz" ? "uz" : "ru");
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    setError(false);
    (async () => {
      try {
        const response = await apiFetch("/api/admin/marketing");
        if (!response.ok) throw Error();
        const { items } = await response.json();
        if (current) setData(items);
      } catch {
        if (current) setError(true);
      }
    })();
    return () => { current = false; };
  }, [apiFetch, attempt]);
  return <section className="admin-section marketing-desk">
    <header className="marketing-toolbar">
      <h2>{t("Идеи постов на сегодня", "Bugungi post g‘oyalari", "Today’s post ideas")}</h2>
      <div className="admin-seg" role="group" aria-label={t("Язык поста", "Post tili", "Post language")}>
        {[["uz", "O‘zbekcha"], ["ru", "Русский"]].map(([code, name]) =>
          <button type="button" key={code} lang={code} aria-pressed={edition === code}
            onClick={() => setEdition(code)}>{name}</button>)}
      </div>
    </header>
    {error ? <div className="admin-error" role="alert">
      <p>{t("Не удалось загрузить посты.", "Postlarni yuklab bo‘lmadi.", "Could not load posts.")}</p>
      <button type="button" className="admin-btn" onClick={() => setAttempt(n => n + 1)}>
        {t("Повторить", "Qayta urinish", "Retry")}
      </button>
    </div> : !data ? <Skeleton rows={3} /> : data.length ? data.map(idea =>
      <PostEditor key={idea.id} idea={idea} edition={edition} t={t} />)
      : <p className="admin-muted">{t("Пока нет свежих постов. Идеи обновляются после сбора новостей.",
        "Hozircha yangi post yo‘q. G‘oyalar yangiliklar yig‘ilgach yangilanadi.",
        "No recent posts are ready. Ideas refresh after news collection.")}</p>}
  </section>;
}
