import {useEffect, useLayoutEffect, useMemo, useRef, useState} from "react";
import {earningsReport} from "./earningsReport.js";
import {drawEarningsCard} from "./earningsCard.js";
import {posterBackground} from "./marketPoster.js";

function EarningsDraft({data, background, t}) {
  const [end,setEnd] = useState(data.periods[0].end);
  const report = useMemo(() => earningsReport(data,end), [data,end]);
  const [edits,setEdits] = useState({});
  const [notice,setNotice] = useState("");
  const caption = edits[end] ?? report.text;
  const canvas = useRef(null), textarea = useRef(null);
  useLayoutEffect(() => {
    if (background) drawEarningsCard(canvas.current,report,background);
  },[background,report]);
  async function copy() {
    try {
      await navigator.clipboard.writeText(caption);
      setNotice(t("Скопировано","Nusxalandi","Copied"));
    } catch {
      textarea.current.select();
      setNotice(t("Скопируйте выделенный текст.","Belgilangan matnni nusxalang.","Copy the selected text."));
    }
  }
  function download() {
    const link = document.createElement("a");
    link.href = canvas.current.toDataURL("image/png");
    link.download = `uzstock-${report.ticker}-${end}.png`;
    link.click();
  }
  return <>
    <label>{t("Отчётный период","Hisobot davri","Reporting period")}
      <select value={end} onChange={event => {setEnd(event.target.value); setNotice("");}}>
        {data.periods.map(row => <option key={row.end}>{row.end}</option>)}
      </select>
    </label>
    <div className="market-poster-editor">
      <div>
        {background && <canvas width="1080" height="1350" ref={canvas} role="img" lang="ru"
          aria-label={[report.ticker,end,"UZS",...report.cards.map(card => [card.label,card.value,card.change].join(" "))].join(" · ")}/>}
        {background === false && <p role="alert">{t("Иллюстрация недоступна.","Rasmni yuklab bo‘lmadi.","Poster artwork unavailable.")}</p>}
      </div>
      <div className="market-poster-controls">
        <label>{t("Двуязычный пост","Ikki tildagi post","Bilingual post")}
          <textarea rows={16} ref={textarea} value={caption} onChange={event => {
            setEdits({...edits,[end]:event.target.value}); setNotice("");
          }}/>
        </label>
        <div className="marketing-actions">
          <button type="button" className="admin-btn accent" onClick={copy} disabled={!caption.trim()}>{t("Скопировать пост","Postni nusxalash","Copy bilingual post")}</button>
          <button type="button" className="admin-btn" onClick={download} disabled={!background}>{t("Скачать PNG","PNG yuklash","Download PNG")}</button>
          <span role="status">{notice}</span>
        </div>
        <details><summary>{t("Исходные отчёты","Manba hisobotlari","Source filings")}</summary>
          {report.sources.map(({end:date,url}) => <p key={date+url}><a href={url} target="_blank" rel="noreferrer">Openinfo · {date}</a></p>)}
        </details>
      </div>
    </div>
  </>;
}

export function EarningsPoster({apiFetch,t}) {
  const title = t("Отчёт эмитента","Emitent hisoboti","Earnings report");
  const [open,setOpen] = useState(false);
  const [ticker,setTicker] = useState("QZSM");
  const [request,setRequest] = useState(null);
  const [result,setResult] = useState(null);
  const [background,setBackground] = useState(null);
  useEffect(() => {
    if (!request) return;
    let live = true;
    const controller = new AbortController();
    apiFetch("/api/admin/marketing/earnings/" + encodeURIComponent(request.ticker),{signal:controller.signal})
      .then(response => {if (!response.ok) throw Error(); return response.json();})
      .then(data => {if (live) setResult({data});})
      .catch(() => {if (live) setResult({error:true});});
    posterBackground().then(img => {if (live) setBackground(img);}).catch(() => {if (live) setBackground(false);});
    return () => {live = false; controller.abort();};
  },[request,apiFetch]);
  function load() {
    setResult(null);
    setRequest({ticker:ticker.trim().toUpperCase()});
  }
  return <section className="panel marketing-module market-poster" aria-label={title}>
    <h3><button type="button" className="market-poster-toggle" aria-label={title} aria-controls="issuer-earnings-editor" aria-expanded={open}
      onClick={() => {if (!request) load(); setOpen(!open);}}>
      <span className="market-poster-thumb" aria-hidden="true"/><span>{title}</span>
      <span className="market-poster-chevron" aria-hidden="true">{open ? "−" : "+"}</span>
    </button></h3>
    <div hidden={!open} id="issuer-earnings-editor">
      <form className="earnings-lookup" onSubmit={event => {event.preventDefault(); load();}}>
        <label>{t("Тикер","Tiker","Ticker")}<input required maxLength={32} value={ticker} onChange={event=>setTicker(event.target.value)} /></label>
        <button className="admin-btn" disabled={!ticker.trim()}>{t("Загрузить отчёты","Hisobotlarni yuklash","Load filings")}</button>
      </form>
      {result?.error ? <p role="alert">{t("Не удалось загрузить отчёты.","Hisobotlarni yuklab bo‘lmadi.","Could not load filings.")}</p>
        : result?.data?.periods?.length ? <EarningsDraft data={result.data} {...{background,t}}/>
        : <p role="status">{result ? t("Нет доступных отчётов для этого тикера.","Ushbu tiker uchun hisobot mavjud emas.","No usable filings for this ticker.")
          : t("Загрузка…","Yuklanmoqda…","Loading…")}</p>}
    </div>
  </section>;
}
