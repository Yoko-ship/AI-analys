import { mt } from "../../shared/marketCopy.jsx";
import { TermInfo } from "../../shared/TermInfo.jsx";
export function createMarketHeaders({
  pinAt,
  sortRankOf,
  sortDirOf,
  sortKeys,
  dragCol,
  dragOverCol,
  colMenu,
  lang,
  longPress,
  onSort,
  startLongPress,
  cancelLongPress,
  setDragCol,
  setDragOverCol,
  moveCol,
  setColMenu,
  visibleOrder,
  LABEL_OF,
  NUM_COLS
}) {
  const sortTh = (key, label, opts = {}) => {
    const {
      movable = false,
      num = false,
      pinKey = null
    } = opts;
    const pin = pinKey ? pinAt(pinKey) : null;
    const rank = sortRankOf(key);
    const dir = sortDirOf(key);
    const chained = sortKeys.length > 1;
    const cls = ["market-th-sortable", num ? "market-th-num" : "", rank >= 0 ? "sorted" : "", movable ? "market-th-movable" : "", movable && dragCol === key ? "dragging" : "", movable && dragOverCol === key && dragCol && dragCol !== key ? "drag-over" : "", colMenu && colMenu.key === key ? "menu-open" : "", pin ? `market-col-pinned${pin.edge ? " market-col-pinned-edge" : ""}` : ""].filter(Boolean).join(" ");
    const menuLabel = lang === "en" ? "Column controls" : lang === "uz" ? "Ustun boshqaruvi" : "Управление столбцом";
    // ⌘ on a Mac, Ctrl elsewhere — Shift works everywhere and is the one we teach.
    const isAdditive = e => e.shiftKey || e.metaKey || e.ctrlKey;
    const hint = lang === "en" ? "Shift+click (or long-press) — add as a secondary sort" : lang === "uz" ? "Shift+bosish (yoki uzoq bosish) — qoʻshimcha saralash kaliti" : "Shift+клик (или долгое нажатие) — добавить второй ключ сортировки";
    const dragHint = lang === "en" ? "Drag to reorder · click to sort" : lang === "uz" ? "Tartibni o'zgartirish uchun torting · saralash uchun bosing" : "Перетащите, чтобы переставить · нажмите для сортировки";
    return <th key={key} className={cls} data-sort-key={key} onClick={e => {
      // The long-press already sorted; the tap that ends it must not sort again.
      if (longPress.current.fired) {
        longPress.current.fired = false;
        return;
      }
      onSort(key, isAdditive(e));
    }} onKeyDown={e => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onSort(key, isAdditive(e));
      }
    }} onTouchStart={() => startLongPress(key)} onTouchMove={cancelLongPress} onTouchEnd={cancelLongPress} onTouchCancel={cancelLongPress} onContextMenu={e => {
      if (longPress.current.fired) e.preventDefault();
    }} role="button" tabIndex={0}
    /* ARIA asks for aria-sort on ONE header at a time, so the chain's later keys
       announce their rank through the accessible name instead. */ aria-sort={rank === 0 ? dir === "asc" ? "ascending" : "descending" : "none"} aria-label={rank > 0 ? `${label} — ${lang === "en" ? "sort" : lang === "uz" ? "saralash" : "сортировка"} ${rank + 1}, ${dir === "asc" ? lang === "en" ? "ascending" : lang === "uz" ? "oʻsish" : "по возрастанию" : lang === "en" ? "descending" : lang === "uz" ? "kamayish" : "по убыванию"}` : undefined} draggable={movable} onDragStart={movable ? e => {
      setDragCol(key);
      e.dataTransfer.effectAllowed = "move";
      try {
        e.dataTransfer.setData("text/plain", key);
      } catch (_) {/* ignore */}
    } : undefined} onDragOver={movable ? e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      if (dragOverCol !== key) setDragOverCol(key);
    } : undefined} onDragEnter={movable ? e => e.preventDefault() : undefined} onDragLeave={movable ? () => {
      setDragOverCol(c => c === key ? null : c);
    } : undefined} onDrop={movable ? e => {
      e.preventDefault();
      let from = dragCol;
      if (!from) {
        try {
          from = e.dataTransfer.getData("text/plain");
        } catch (_) {
          from = null;
        }
      }
      moveCol(from, key);
      setDragCol(null);
      setDragOverCol(null);
    } : undefined} onDragEnd={movable ? () => {
      setDragCol(null);
      setDragOverCol(null);
    } : undefined} title={movable ? `${dragHint} · ${hint}` : hint} style={pin ? {
      left: pin.left
    } : undefined}>
      <span className="market-th-inner">
        {movable && <span className="market-th-grip" aria-hidden="true">⋮⋮</span>}
        <span>{label}</span>
        {/* Renders nothing for a column that is not an economic term (компания,
            UZSE) — the marker promises an explanation and must not appear
            without one. */}
        <TermInfo termId={key} lang={lang} label={label} />
        <span className="market-sort-caret">{rank >= 0 ? dir === "asc" ? "▲" : "▼" : "↕"}</span>
        {/* The rank only earns its space once the order actually has more than one
            key — a lone "1" beside a single sorted column says nothing. */}
        {chained && rank >= 0 && <span className="market-sort-rank" aria-hidden="true">{rank + 1}</span>}
        {/* The column's own controls. Only the movable columns get it: ticker and
            company cannot be moved, hidden or unfrozen, so a toolbar there would
            be six dead buttons. The header's own click still sorts — this button
            swallows every gesture that would otherwise reach it, including the
            long-press and the drag. */}
        {movable && <button type="button" className={`market-th-menu-btn${colMenu && colMenu.key === key ? " is-open" : ""}`} draggable={false} title={menuLabel} aria-label={`${label} — ${menuLabel}`} aria-haspopup="true" aria-expanded={!!(colMenu && colMenu.key === key)} onPointerDown={e => e.stopPropagation()} onMouseDown={e => e.stopPropagation()} onTouchStart={e => e.stopPropagation()} onKeyDown={e => e.stopPropagation()} onClick={e => {
          e.stopPropagation();
          e.preventDefault();
          const fromSticky = !!e.currentTarget.closest(".market-sticky-head");
          setColMenu(c => c && c.key === key ? null : {
            key,
            fromSticky
          });
        }}>
            <svg
              viewBox="0 0 16 16"
              width="12"
              height="12"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M4 6l4 4 4-4" />
            </svg>
          </button>}
      </span>
    </th>;
  };
  const headCells = [sortTh("ticker", mt(lang, "ticker"), {
    pinKey: "__ticker"
  }), sortTh("company", mt(lang, "company"), {
    pinKey: "__company"
  }), ...visibleOrder.map(k => sortTh(k, LABEL_OF[k], {
    movable: true,
    num: NUM_COLS.has(k),
    pinKey: k
  }))];
  const pinTicker = pinAt("__ticker");
  const pinCompany = pinAt("__company");
  return {
    headCells,
    pinTicker,
    pinCompany
  };
}
