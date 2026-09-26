import { useNewsAgent } from "./useNewsAgent.js";
export const NEWS_ADMIN_TX = {
  ru: {
    title: "Новостной агент (Grok)",
    ph: "Компания, тикер или тема…",
    days: "Дней",
    save: "Сохранять в ленту",
    run: "Найти",
    running: "Поиск…",
    found: "найдено",
    nw: "новых",
    rel: "релевантных",
    stored: "сохранено",
    empty: "Ничего не найдено",
    err: "Ошибка поиска",
    note: "Заметка",
    hint: "Каждый запуск — платный поиск Grok (web + X). Виден только администраторам."
  },
  en: {
    title: "News agent (Grok)",
    ph: "Company, ticker, or topic…",
    days: "Days",
    save: "Save to feed",
    run: "Search",
    running: "Searching…",
    found: "found",
    nw: "new",
    rel: "relevant",
    stored: "stored",
    empty: "Nothing found",
    err: "Search failed",
    note: "Note",
    hint: "Each run triggers a billed Grok web + X search. Admin-only."
  },
  uz: {
    title: "Yangiliklar agenti (Grok)",
    ph: "Kompaniya, ticker yoki mavzu…",
    days: "Kun",
    save: "Lentaga saqlash",
    run: "Qidirish",
    running: "Qidirilmoqda…",
    found: "topildi",
    nw: "yangi",
    rel: "tegishli",
    stored: "saqlandi",
    empty: "Hech narsa topilmadi",
    err: "Qidiruvda xatolik",
    note: "Izoh",
    hint: "Har bir qidiruv — pullik Grok (web + X). Faqat administratorlar uchun."
  }
};
export const NEWS_ADMIN_TONE = {
  positive: "#2f9e5f",
  negative: "#c0504d",
  neutral: "#8a8a8a"
};
export function NewsAdminPanel({
  language,
  apiFetch,
  onStored
}) {
  const tx = NEWS_ADMIN_TX[language] || NEWS_ADMIN_TX.ru;
  const {
    q,
    setQ,
    days,
    setDays,
    store,
    setStore,
    loading,
    res,
    err,
    open,
    setOpen,
    run
  } = useNewsAgent({
    apiFetch,
    tx,
    onStored
  });
  const border = "1px solid rgba(128,128,128,.28)";
  const box = {
    border,
    borderRadius: 10,
    background: "rgba(128,128,128,.06)"
  };
  const field = {
    padding: "8px 10px",
    borderRadius: 8,
    border,
    background: "transparent",
    color: "inherit",
    font: "inherit"
  };
  return <section style={{
    ...box,
    margin: "0 0 22px",
    overflow: "hidden"
  }}>
      <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open} style={{
      width: "100%",
      display: "flex",
      alignItems: "center",
      gap: 8,
      padding: "10px 14px",
      background: "transparent",
      border: "none",
      cursor: "pointer",
      font: "inherit",
      color: "inherit",
      textAlign: "left"
    }}>
        <span style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: ".08em",
        padding: "2px 6px",
        borderRadius: 4,
        background: "rgba(192,80,77,.15)",
        color: "#c0504d"
      }}>ADMIN</span>
        <strong style={{
        flex: 1
      }}>{tx.title}</strong>
        <span style={{
        opacity: .6
      }} aria-hidden="true">{open ? "▲" : "▼"}</span>
      </button>
      {open && <div style={{
      padding: "4px 14px 14px"
    }}>
          <div style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 8,
        alignItems: "center"
      }}>
            <input type="text" value={q} placeholder={tx.ph} onChange={e => setQ(e.target.value)} onKeyDown={e => {
          if (e.key === "Enter") run();
        }} style={{
          ...field,
          flex: "1 1 240px",
          minWidth: 180
        }} />
            <label style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          fontSize: 13,
          opacity: .85
        }}>
              {tx.days}
              <input type="number" min="1" max="30" value={days} onChange={e => setDays(Math.max(1, Math.min(30, Number(e.target.value) || 7)))} style={{
            ...field,
            width: 58
          }} />
            </label>
            <label style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          fontSize: 13,
          opacity: .85
        }}>
              <input type="checkbox" checked={store} onChange={e => setStore(e.target.checked)} /> {tx.save}
            </label>
            <button type="button" onClick={run} disabled={loading || !q.trim()} style={{
          padding: "8px 18px",
          borderRadius: 8,
          border: "none",
          color: "#fff",
          font: "inherit",
          fontWeight: 600,
          cursor: loading || !q.trim() ? "default" : "pointer",
          background: loading || !q.trim() ? "rgba(128,128,128,.4)" : "#2f6fed"
        }}>
              {loading ? tx.running : tx.run}
            </button>
          </div>
          <div style={{
        fontSize: 11,
        opacity: .55,
        marginTop: 6
      }}>{tx.hint}</div>
          {err && <div style={{
        marginTop: 10,
        color: "#c0504d",
        fontSize: 13
      }}>{err}</div>}
          {res && <div style={{
        marginTop: 12
      }}>
              <div style={{
          fontSize: 13,
          fontWeight: 600
        }}>
                {res.found} {tx.found} · {res.new} {tx.nw} · {res.relevant} {tx.rel}
                {store ? ` · ${res.stored} ${tx.stored}` : ""}{res.backend ? ` · ${res.backend}` : ""}
              </div>
              {res.note && <div style={{
          fontSize: 12,
          opacity: .7,
          marginTop: 2
        }}>{tx.note}: {res.note}</div>}
              {!res.items || res.items.length === 0 ? <div style={{
          marginTop: 10,
          opacity: .6,
          fontSize: 13
        }}>{tx.empty}</div> : <ul style={{
          listStyle: "none",
          margin: "10px 0 0",
          padding: 0,
          display: "grid",
          gap: 8
        }}>
                  {res.items.map((it, i) => <li key={i} style={{
            ...box,
            padding: "10px 12px"
          }}>
                      <a href={it.url} target="_blank" rel="noopener noreferrer" style={{
              fontWeight: 600,
              color: "inherit",
              textDecoration: "none"
            }}>{it.title || it.url}</a>
                      <div style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 8,
              alignItems: "center",
              marginTop: 6,
              fontSize: 12,
              opacity: .9
            }}>
                        {it.source && <span>{it.source}</span>}
                        {it.type && <span className={`news-tag-mini cat-${it.type}`}>{it.type}</span>}
                        {it.tone && <span style={{
                fontWeight: 600,
                color: NEWS_ADMIN_TONE[it.tone] || "inherit"
              }}>{it.tone}</span>}
                        {it.impact && it.impact !== "none" && <span>impact: {it.impact}</span>}
                        {it.direction && it.direction !== "unclear" && <span>{it.direction}</span>}
                        {Array.isArray(it.tickers) && it.tickers.length > 0 && <span style={{
                fontWeight: 600
              }}>{it.tickers.join(", ")}</span>}
                        <span title="relevant" style={{
                marginLeft: "auto"
              }} aria-hidden="true">{it.relevant ? "★" : "☆"}</span>
                      </div>
                      {it.summary_ru && <div style={{
              marginTop: 6,
              fontSize: 13,
              opacity: .92
            }}>{it.summary_ru}</div>}
                    </li>)}
                </ul>}
            </div>}
        </div>}
    </section>;
}
