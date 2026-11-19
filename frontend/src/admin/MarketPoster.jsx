import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { drawPoster, posterAssets, posterCaption, sessionPoster } from "./marketPoster.js";
import "./marketPoster.css";

async function getJson(apiFetch, path) {
  const response = await apiFetch(path);
  if (!response.ok) throw new Error("Market data request failed");
  return response.json();
}

function PosterEditor({poster, assets, language, t}) {
  const canvas = useRef(null);
  const captionField = useRef(null);
  const [edition, setEdition] = useState(language === "ru" ? "ru" : "uz");
  const [edits, setEdits] = useState({});
  const [notice, setNotice] = useState("");
  const caption = edits[edition] ?? posterCaption(poster, edition);
  useLayoutEffect(() => {
    drawPoster(canvas.current, poster, assets, edition);
  }, [poster, assets, edition]);

  function download() {
    const link = document.createElement("a");
    link.href = canvas.current.toDataURL("image/png");
    link.download = `uzstock-bozor-sharhi-${poster.day}-${edition}.png`;
    link.click();
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(caption);
      setNotice(t("Скопировано", "Nusxalandi", "Copied"));
    } catch {
      captionField.current.select();
      setNotice(t("Скопируйте выделенный текст.", "Belgilangan matnni nusxalang.", "Copy the selected text."));
    }
  }
  const describe = (rows, field) => rows.map(row => row.ticker + " " + row[field]).join(", ");
  return <div className="market-poster-editor">
    <canvas ref={canvas} width="1080" height="1350" role="img"
      aria-label={`Bozor sharhi · ${poster.day} · ${t("Оборот","Aylanma","Turnover")} (UZS): ${describe(poster.turnover,"turnover")} · ${t("Сделки","Bitimlar","Trades")}: ${describe(poster.trades,"trades")}`}/>
    <div className="market-poster-controls">
      <label>{t("Язык подписи","Izoh tili","Caption language")}
        <select value={edition} onChange={event => {setEdition(event.target.value); setNotice("");}}>
          <option value="uz">O‘zbekcha</option><option value="ru">Русский</option>
        </select>
      </label>
      <label>{t("Подпись","Izoh","Caption")}
        <textarea ref={captionField} lang={edition} value={caption} rows={8} onChange={event => {
          setEdits({...edits, [edition]:event.target.value}); setNotice("");
        }}/>
      </label>
      <div className="marketing-actions">
        <button type="button" className="admin-btn accent" onClick={download}>{t("Скачать PNG","PNG yuklash","Download PNG")}</button>
        <button type="button" className="admin-btn" onClick={copy} disabled={!caption.trim()}>{t("Скопировать подпись","Izohni nusxalash","Copy caption")}</button>
      </div>
      <span role="status">{notice}</span>
    </div>
  </div>;
}

export function MarketPoster({apiFetch, language, t}) {
  const [open, setOpen] = useState(false);
  const [started, setStarted] = useState(false);
  const [result, setResult] = useState(null);
  const [attempt, retry] = useState(0);
  useEffect(() => {
    if (!started) return;
    let current = true;
    async function load() {
      try {
        const [board, statistics, directory] = await Promise.all([
          getJson(apiFetch, "/api/market/stocks?type=stock"), getJson(apiFetch, "/api/market/trade-stats"),
          getJson(apiFetch, "/api/securities").catch(() => ({})),
        ]);
        const poster = sessionPoster(board.stocks, statistics, directory.securities || {});
        const assets = poster && await posterAssets(poster);
        if (current) setResult({poster, assets});
      } catch {
        if (current) setResult({error:true});
      }
    }
    load();
    return () => { current = false; };
  }, [apiFetch, started, attempt]);

  return <section className="panel marketing-module market-poster" aria-label="Bozor sharhi">
    <h3><button type="button" className="market-poster-toggle" aria-expanded={open} aria-controls="market-poster-content"
      onClick={() => {setStarted(true); setOpen(!open);}}>
      <span className="market-poster-thumb" aria-hidden="true"/><span>Bozor sharhi</span>
      <span className="market-poster-chevron" aria-hidden="true">{open ? "−" : "+"}</span>
    </button></h3>
    <div id="market-poster-content" hidden={!open}>
      {result?.poster ? <PosterEditor {...result} {...{language,t}}/> : open && <div>
        <p role="status">{!result ? t("Загрузка…","Yuklanmoqda…","Loading…") : result.error
          ? t("Не удалось загрузить карточку.","Kartani yuklab bo‘lmadi.","Could not load the poster.")
          : t("Рейтинги за эту сессию недоступны.","Ushbu sessiya reytinglari mavjud emas.","Rankings unavailable for this session.")}</p>
        {result && <button className="admin-btn" onClick={() => {setResult(null); retry(n => n + 1);}}>{t("Обновить","Yangilash","Refresh")}</button>}
      </div>}
    </div>
  </section>;
}
