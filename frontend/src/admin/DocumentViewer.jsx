import React, { useEffect, useRef, useState } from "react";

export default function DocumentViewer({ document, apiFetch, read, params, updateFilters, navigate, t }) {
  const [preview, setPreview] = useState(null), [error, setError] = useState(""), [image, setImage] = useState(null);
  const [zoom, setZoom] = useState(100), [query, setQuery] = useState(""), [start, setStart] = useState(0), [copied, setCopied] = useState(false);
  const page = Number(params.get("page") || 1), sheet = params.get("sheet") || "";
  const selectedCell = params.get("cell"), selectedRow = Number(params.get("row") || selectedCell?.match(/\d+$/)?.[0] || 0);
  const canvas = useRef(null);
  useEffect(() => { setStart(Math.floor(Math.max(0, Math.min(1999, selectedRow - 1)) / 100) * 100); }, [document.id, sheet, selectedRow]);
  useEffect(() => { canvas.current?.querySelector(".source-selected")?.scrollIntoView({ block: "nearest", inline: "nearest" }); }, [preview, selectedCell, selectedRow]);
  useEffect(() => {
    const controller = new AbortController();
    setPreview(null); setError(""); setImage(null);
    const p = new URLSearchParams({ page, start, q: query });
    if (sheet) p.set("sheet", sheet);
    let objectUrl;
    const load = async () => {
      try {
        const result = await read(`/documents/${encodeURIComponent(document.id)}/preview?${p}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setPreview(result);
        if (result.format === "PDF") {
          const response = await apiFetch(`/api/admin/control/documents/${encodeURIComponent(document.id)}/page/${page}`, { signal: controller.signal });
          if (!response.ok) throw new Error(t("Не удалось загрузить страницу", "Sahifani yuklab bo‘lmadi", "The page could not be loaded"));
          objectUrl = URL.createObjectURL(await response.blob());
          if (controller.signal.aborted) URL.revokeObjectURL(objectUrl); else setImage(objectUrl);
        }
      } catch (exc) { if (exc.name !== "AbortError") setError(exc.message); }
    };
    load();
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [document.id, read, apiFetch, page, sheet, query, start, t]);
  const download = async () => {
    try {
      const response = await apiFetch(`/api/admin/control/documents/${encodeURIComponent(document.id)}/original`);
      if (!response.ok) throw new Error(t("Оригинал недоступен", "Asl nusxa mavjud emas", "The original is unavailable"));
      const url = URL.createObjectURL(await response.blob());
      const link = window.document.createElement("a"); link.href = url; link.download = `${document.ticker}-${document.period}.${document.detected_format?.toLowerCase() || "bin"}`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (exc) { setError(exc.message); }
  };
  return <section className="control-viewer">
    <div className="control-viewer-toolbar"><strong>{document.detected_format || t("Формат ещё не проверен", "Format tekshirilmagan", "Format not yet verified")}</strong><button className="control-button" disabled={!document.checksum} onClick={download}>{t("Скачать оригинал", "Asl nusxani yuklash", "Download original")}</button><button className="control-button" onClick={async () => { try { await navigator.clipboard.writeText(window.location.href); setCopied(true); } catch { setError("Could not copy the link"); } }}>{copied ? t("Скопировано", "Nusxalandi", "Copied") : t("Ссылка на строку", "Satrga havola", "Copy source link")}</button></div>
    <div className="control-viewer-tools"><label>{t("Поиск в документе", "Hujjatdan qidirish", "Search this document")}<input value={query} onChange={e => { setQuery(e.target.value); setStart(0); }} /></label><label>{t("Масштаб", "Masshtab", "Zoom")}<select value={zoom} onChange={e => setZoom(Number(e.target.value))}>{[75, 100, 125, 150].map(v => <option value={v} key={v}>{v}%</option>)}</select></label>
      {preview?.format === "XLSX" && <label>{t("Лист", "Varaq", "Worksheet")}<select value={preview.sheet} onChange={e => { setStart(0); updateFilters({ sheet: e.target.value, cell: "", row: "" }); }}>{preview.sheets.map(s => <option key={s}>{s}</option>)}</select></label>}
      {preview?.format === "PDF" && <label>{t("Страница", "Sahifa", "Page")}<input type="number" min={1} max={preview.pages} value={page} onChange={e => updateFilters({ page: String(Math.max(1, Math.min(preview.pages, Number(e.target.value)))) })} /><span>/ {preview.pages}</span></label>}
    </div>
    <p className="control-viewer-safety">{t("Только чтение. Макросы, формулы, скрипты и внешние ссылки не исполняются.", "Faqat o‘qish. Makros, formula, skript va tashqi havolalar bajarilmaydi.", "Read only. Macros, formulas, scripts and external links are never executed.")}</p>
    {error ? <div className="control-error" role="alert">{error}</div> : !preview ? <p role="status">{t("Загрузка документа…", "Hujjat yuklanmoqda…", "Loading document…")}</p> : <>
      <div className="control-document-canvas" ref={canvas} style={{ fontSize: `${12 * zoom / 100}px` }}>
        {preview.format === "XLSX" ? <table><tbody>{preview.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={cell.address || j} className={selectedCell === cell.address || !selectedCell && selectedRow > 0 && Number(cell.address?.match(/\d+$/)?.[0]) === selectedRow ? "source-selected" : ""}><button onClick={() => updateFilters({ sheet: preview.sheet, cell: cell.address, row: "" })} title={cell.address}><small>{cell.address}</small><span>{cell.value ?? "—"}</span></button></td>)}</tr>)}</tbody></table>
          : <>{image && <img src={image} alt={`${document.ticker} · ${t("страница", "sahifa", "page")} ${page}`} style={{ width: `${zoom}%`, maxWidth: "none" }} />}<pre>{preview.text}</pre>{query && <p>{preview.matches?.length || 0} {t("совпадений на странице", "sahifadagi natija", "matches on this page")}</p>}</>}
      </div>
      {start > 0 && <button className="control-button" onClick={() => { setStart(0); updateFilters({ row: "", cell: "" }); }}>{t("Первые строки", "Birinchi satrlar", "First rows")}</button>}
      {preview.next_row && <button className="control-button" onClick={() => setStart(preview.next_row)}>{t("Следующие строки", "Keyingi satrlar", "Next rows")} →</button>}
      {preview.format === "XLSX" && <p className="control-muted">{t("Просмотр: до 2000 строк и 100 столбцов. Полный файл доступен для скачивания.", "Ko‘rinish: 2000 satr va 100 ustungacha. To‘liq faylni yuklash mumkin.", "Preview: up to 2,000 rows and 100 columns. Download the original for the full workbook.")}</p>}
      {selectedCell && <div className="control-source-selection"><strong>{preview.sheet}!{selectedCell}</strong><button className="control-button" onClick={() => navigate("facts", { q: selectedCell, ticker: document.ticker })}>{t("Связанные факты", "Bog‘langan faktlar", "Related facts")}</button></div>}
    </>}
  </section>;
}
