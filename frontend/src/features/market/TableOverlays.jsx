import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { rootZoom, zoomedViewport } from "../../shared/viewport.jsx";
import { createPortal } from "react-dom";

// A floating horizontal scrollbar for the wide market table, clung to the bottom of
// the table's visible area (the screen bottom while the table runs off the fold).
// The table's own scroll container (.market-table-wrap) has no height cap, so its
// native horizontal scrollbar sits at the very bottom of a tall table — unreachable
// without scrolling the whole page down. We hide that native bar (see CSS) and mirror
// it here so it's always reachable. Rendered via a body portal because the table's
// ancestors (.market-board overflow:hidden + backdrop-filter, .app-shell-wrap
// overflow:hidden) would otherwise clip/mis-anchor a position:fixed element.
function MarketFloatScroll({ wrapRef, colSignature, rowCount, loading }) {
  const trackRef = useRef(null);
  const [box, setBox] = useState({ show: false, left: 0, width: 0, top: 0 });
  const [thumb, setThumb] = useState({ width: 0, left: 0 });
  const drag = useRef(null);
  const MIN_THUMB = 40;

  // Track geometry + thumb size/position, derived from the table's live scroll state.
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return undefined;
    let raf = 0;
    const measure = () => {
      raf = 0;
      const el = wrapRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const sw = el.scrollWidth, cw = el.clientWidth;
      const max = sw - cw;
      // The bar is a fixed child of the zoomed root, so its geometry is written in
      // CSS pixels while the rect arrives in viewport pixels — see rootZoom().
      const { zoom, vw, vh } = zoomedViewport();
      // Clamp to the table's VISIBLE rectangle: the wrap can extend past the viewport
      // (the layout has a min-width and .app-shell-wrap clips the overflow).
      const left = Math.max(r.left / zoom, 0);
      const right = Math.min(r.right / zoom, vw);
      const trackW = right - left;
      const rTop = r.top / zoom, rBottom = r.bottom / zoom;
      // The wrap's native bar is hidden (see CSS) — this floating bar is the only
      // horizontal scrollbar. It clings to the viewport bottom while the table runs
      // below the fold, and to the table's own bottom edge once the end scrolls into
      // view, so exactly one bar is visible whenever the table is on screen.
      const inView = max > 1 && rTop < vh && rBottom > 40 && trackW > 40;
      if (!inView) {
        setBox((b) => (b.show ? { ...b, show: false } : b));
        return;
      }
      const BAR = 14;
      const top = Math.min(vh, rBottom) - BAR;
      setBox({ show: true, left, width: trackW, top });
      const tw = Math.max(trackW * (cw / sw), MIN_THUMB);
      const tl = max > 0 ? (el.scrollLeft / max) * (trackW - tw) : 0;
      setThumb({ width: tw, left: tl });
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(measure); };
    measure();
    // capture:true reaches window for the wrap's own (non-bubbling) horizontal scroll too.
    window.addEventListener("scroll", schedule, { passive: true, capture: true });
    window.addEventListener("resize", schedule);
    const ro = new ResizeObserver(schedule);
    ro.observe(wrap);
    // Table scrolled (trackpad / Shift+wheel / keyboard) -> re-derive the thumb.
    wrap.addEventListener("scroll", schedule, { passive: true });
    return () => {
      window.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
      wrap.removeEventListener("scroll", schedule);
      ro.disconnect();
      if (raf) cancelAnimationFrame(raf);
    };
    // colSignature/rowCount/loading: ResizeObserver won't fire when only scrollWidth changes.
  }, [wrapRef, colSignature, rowCount, loading]);

  // Drag the thumb -> the table scrolls (mapped by the thumb's travel range).
  useEffect(() => {
    const onMove = (e) => {
      const d = drag.current;
      const el = wrapRef.current;
      if (!d || !el) return;
      const denom = d.trackW - d.thumbW;
      const max = el.scrollWidth - el.clientWidth;
      // The track is measured in CSS pixels and the pointer reports viewport ones,
      // so the drag would run at 1.5x the thumb under a 150 % text size.
      const moved = (e.clientX - d.startX) / rootZoom();
      el.scrollLeft = denom > 0 ? d.startScroll + (moved / denom) * max : d.startScroll;
    };
    const onUp = () => { if (drag.current) { drag.current = null; document.body.classList.remove("market-float-dragging"); } };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); };
  }, [wrapRef]);

  const onThumbDown = (e) => {
    const el = wrapRef.current;
    if (!el) return;
    e.preventDefault();
    drag.current = { startX: e.clientX, startScroll: el.scrollLeft, trackW: box.width, thumbW: thumb.width };
    document.body.classList.add("market-float-dragging");
  };
  const onTrackDown = (e) => {
    if (e.target !== trackRef.current) return; // ignore clicks on the thumb
    const el = wrapRef.current;
    if (!el) return;
    const clickX = (e.clientX - trackRef.current.getBoundingClientRect().left) / rootZoom();
    const dir = clickX < thumb.left ? -1 : 1; // page toward the click
    el.scrollBy({ left: dir * el.clientWidth * 0.9, behavior: "smooth" });
  };

  return createPortal(
    <div
      className="market-float-scroll"
      ref={trackRef}
      onPointerDown={onTrackDown}
      aria-hidden="true"
      style={{ display: box.show ? "block" : "none", left: box.left, width: box.width, top: box.top }}
    >
      <div className="market-float-thumb" style={{ width: thumb.width, left: thumb.left }} onPointerDown={onThumbDown} />
    </div>,
    document.body
  );
}

function MarketColsPopover({ anchorRef, onClose, title, closeLabel, children }) {
  const [pos, setPos] = useState(null);
  const [sheet, setSheet] = useState(() => window.matchMedia("(max-width: 760px)").matches);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 760px)");
    const onChange = () => setSheet(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // Desktop geometry only — the sheet is pinned to the viewport bottom by CSS
  // and has nothing to measure.
  useLayoutEffect(() => {
    if (sheet) { setPos(null); return undefined; }
    let raf = 0;
    const place = () => {
      raf = 0;
      const btn = anchorRef.current;
      if (!btn) return;
      const r = btn.getBoundingClientRect();
      // In the units a fixed child of the (possibly zoomed) root is placed in —
      // see rootZoom(). Measured pixels come in from the rect, CSS pixels go out.
      const { zoom, vw, vh } = zoomedViewport();
      const anchorRight = r.right / zoom, anchorBottom = r.bottom / zoom;
      const width = Math.min(300, vw - 24);
      // Right-aligned to the button, but never off either edge of the viewport.
      const left = Math.max(12, Math.min(anchorRight - width, vw - width - 12));
      const top = Math.max(8, Math.min(anchorBottom + 8, vh - 200));
      setPos({ top, left, width, maxHeight: Math.max(200, vh - top - 16) });
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(place); };
    place();
    // capture:true so an inner scrollport's (non-bubbling) scroll re-anchors too.
    window.addEventListener("scroll", schedule, { passive: true, capture: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [anchorRef, sheet]);

  // Esc closes. On the sheet the page behind is frozen as well, so the scroll
  // gesture belongs to the sheet alone — the complaint that "scroll gets in the
  // way" on a phone was the page scrolling under an open filter panel.
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    if (!sheet) return () => window.removeEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose, sheet]);

  return createPortal(
    <>
      <div className={`market-cols-backdrop${sheet ? " is-sheet" : ""}`} onClick={onClose} />
      <div
        className={`market-cols-dropdown${sheet ? " market-cols-sheet" : ""}`}
        role="menu"
        style={sheet || !pos ? undefined : { top: pos.top, left: pos.left, width: pos.width, maxHeight: pos.maxHeight }}
      >
        {sheet && (
          <div className="market-cols-sheet-head">
            <span className="market-cols-sheet-grip" aria-hidden="true" />
            <span className="market-cols-sheet-title">{title}</span>
            <button type="button" className="market-cols-sheet-close" onClick={onClose} aria-label={closeLabel}>×</button>
          </div>
        )}
        {children}
      </div>
    </>,
    document.body
  );
}

// The board's column headers, pinned under the topbar while the rows scroll past.
// The real <thead> can't simply be `position: sticky`: its nearest scrollport is
// .market-table-wrap, which `overflow-x: auto` turns into a scroll container on
// BOTH axes, and that box never scrolls vertically — a sticky th would stay glued
// to the top of the table and ride the page up with it. So the header row is
// mirrored into a fixed bar: the SAME <th> elements (same sort and drag-reorder
// handlers), the column widths measured off the live table, and the wrap's own
// horizontal scroll offset, so the two read and behave as one header. Portaled to
// <body> for the same reason as MarketFloatScroll — the table's ancestors
// (.market-board overflow:hidden, .app-shell-wrap) would otherwise clip it.
function MarketStickyHead({ wrapRef, cells, colSignature, rowCount, loading }) {
  const scrollerRef = useRef(null);
  const [box, setBox] = useState({ show: false, left: 0, width: 0, top: 0, tableWidth: 0, cols: [] });
  const lastKey = useRef("");
  const measureRef = useRef(() => {});

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return undefined;
    let raf = 0;
    const hide = () => {
      if (lastKey.current === "hidden") return;
      lastKey.current = "hidden";
      setBox((b) => ({ ...b, show: false }));
    };
    // The bar mirrors the slice of the table the viewport actually shows, so its
    // own scroll offset is the table's scrollLeft plus whatever the wrap has run
    // off the left edge of the screen.
    const syncScroll = (el, wrapLeft) => {
      const sc = scrollerRef.current;
      if (sc) sc.scrollLeft = el.scrollLeft + (Math.max(wrapLeft, 0) - wrapLeft);
    };
    const measure = () => {
      raf = 0;
      const el = wrapRef.current;
      const table = el && el.querySelector(".market-table");
      const headRow = table && table.querySelector("thead tr");
      if (!el || !table || !headRow || loading || !rowCount) { hide(); return; }
      // Pin under the sticky topbar, whose height differs per breakpoint. The
      // filter bar above the table scrolls away with the page (by request), so
      // the topbar is the only thing this has to clear.
      // The bar is fixed inside the (possibly zoomed) root, so every measured
      // coordinate is divided into the CSS pixels it will be written back as —
      // see rootZoom(). The column WIDTHS go through the same division, or the
      // mirrored header's cells would be 1.5x their columns at a 150 % text size
      // and the labels would walk off their own columns to the right.
      const { zoom, vw } = zoomedViewport();
      const topbar = document.querySelector(".topbar");
      const pin = topbar
        ? Math.max(0, Math.round(topbar.getBoundingClientRect().bottom / zoom)) : 0;
      const headRect = headRow.getBoundingClientRect();
      const tableRect = table.getBoundingClientRect();
      const wrapRect = el.getBoundingClientRect();
      const left = Math.max(wrapRect.left / zoom, 0);
      const width = Math.min(wrapRect.right / zoom, vw) - left;
      // Only while the real header sits above the pin line and rows are still
      // under it — otherwise the bar would hang over a table that has scrolled by.
      if (headRect.bottom / zoom > pin + 1
          || tableRect.bottom / zoom < pin + headRect.height / zoom + 24
          || width < 60) { hide(); return; }
      // Half-pixel rounding: enough to keep the labels over their columns, coarse
      // enough that sub-pixel noise doesn't re-render the bar on every frame.
      const round = (v) => Math.round(v * 2) / 2;
      const cols = Array.from(headRow.children)
        .map((th) => round(th.getBoundingClientRect().width / zoom));
      const tableWidth = round(tableRect.width / zoom);
      const key = `${round(left)}|${round(width)}|${pin}|${tableWidth}|${cols.join(",")}`;
      syncScroll(el, wrapRect.left / zoom);
      if (key === lastKey.current) return;
      lastKey.current = key;
      setBox({ show: true, left, width, top: pin, tableWidth, cols });
    };
    measureRef.current = measure;
    const schedule = () => { if (!raf) raf = requestAnimationFrame(measure); };
    measure();
    // capture:true reaches window for the wrap's own (non-bubbling) horizontal scroll too.
    window.addEventListener("scroll", schedule, { passive: true, capture: true });
    window.addEventListener("resize", schedule);
    const ro = new ResizeObserver(schedule);
    ro.observe(wrap);
    wrap.addEventListener("scroll", schedule, { passive: true });
    return () => {
      measureRef.current = () => {};
      window.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
      wrap.removeEventListener("scroll", schedule);
      ro.disconnect();
      if (raf) cancelAnimationFrame(raf);
    };
  }, [wrapRef, colSignature, rowCount, loading]);

  // Column widths also move on things no observer reports — a sort caret, a
  // language switch, a font finishing its load. Re-measuring after every render
  // is cheap because `lastKey` swallows the no-op ones.
  useLayoutEffect(() => { measureRef.current(); });

  // A column CSS has hidden (mobile drops the company name) measures 0 wide.
  // It has to be left out of BOTH the colgroup and the row: a `display: none`
  // cell drops out of the row entirely under fixed table layout, so every
  // following header would shift one column to the left.
  const mirrored = box.cols
    .map((w, i) => ({ w, i }))
    .filter(({ w, i }) => w > 0 && cells[i]);

  // Nothing in the DOM until it is actually pinned — a second copy of the header
  // row hanging around would double every `.market-table thead` query.
  if (!box.show || !mirrored.length) return null;

  return createPortal(
    <div
      className="market-sticky-head"
      aria-hidden="true"
      style={{ left: box.left, width: box.width, top: box.top }}
    >
      <div className="market-sticky-head__scroller" ref={scrollerRef}>
        <table
          className="market-table market-sticky-head__table"
          style={{ width: box.tableWidth || undefined, minWidth: box.tableWidth || undefined }}
        >
          <colgroup>
            {mirrored.map(({ i, w }) => <col key={i} style={{ width: w }} />)}
          </colgroup>
          <thead>
            <tr>
              {mirrored.map(({ i }) => React.cloneElement(cells[i], {
                // The bar is aria-hidden (the real header is the one screen
                // readers and Tab travel through), so its copies stay unfocusable.
                tabIndex: -1,
              }))}
            </tr>
          </thead>
        </table>
      </div>
    </div>,
    document.body
  );
}

// ── A column's own controls ───────────────────────────────────────────────────
// Sort, move, freeze, hide — everything a reader does TO a column rather than
// with its numbers, in one strip under the header that opened it. The board is
// wider than any screen, and until now the only way to move a column was to drag
// its header: impossible with a thumb, and awkward when the destination is six
// columns off the right edge. These buttons say the same thing in one press.
//
// Portaled to <body>: a <th> is a table cell, and a popover inside one is both
// clipped by the wrap's overflow and duplicated into the mirrored sticky header.
// It re-finds its own header every frame instead of remembering a rectangle, so
// it follows the column it belongs to when a move actually moves it.
function MarketColMenu({ colKey, fromSticky, lang, state, actions, onClose }) {
  const ref = useRef(null);
  const [pos, setPos] = useState(null);
  const placeRef = useRef(() => {});

  useLayoutEffect(() => {
    let raf = 0;
    const place = () => {
      raf = 0;
      const scope = fromSticky ? ".market-sticky-head" : ".market-table-wrap";
      const sel = `.market-table thead th[data-sort-key="${colKey}"]`;
      const th = document.querySelector(`${scope} ${sel}`) || document.querySelector(`.market-table-wrap ${sel}`);
      // The header went away — the column was hidden, the view switched, or the
      // page scrolled it off. A toolbar for a column nobody can see is noise.
      if (!th) { onClose(); return; }
      const r = th.getBoundingClientRect();
      // CSS pixels of the zoomed root, as everywhere a fixed overlay is placed
      // from a measured rectangle — see rootZoom().
      const { zoom, vw, vh } = zoomedViewport();
      const thLeft = r.left / zoom, thBottom = r.bottom / zoom, thTop = r.top / zoom;
      if (thBottom < 0 || thTop > vh) { onClose(); return; }
      const w = (ref.current && ref.current.offsetWidth) || 300;
      const left = Math.round(Math.max(8, Math.min(thLeft, vw - w - 8)));
      const top = Math.round(thBottom + 6);
      // Re-placed after every render, so a position that did not change must not
      // reach state: a fresh object each time is an infinite render loop.
      setPos((prev) => (prev && prev.top === top && prev.left === left ? prev : { top, left }));
    };
    placeRef.current = place;
    const schedule = () => { if (!raf) raf = requestAnimationFrame(place); };
    place();
    // capture:true so the wrap's own (non-bubbling) horizontal scroll re-anchors too.
    window.addEventListener("scroll", schedule, { passive: true, capture: true });
    window.addEventListener("resize", schedule);
    return () => {
      placeRef.current = () => {};
      window.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [colKey, fromSticky, onClose]);

  // A move re-lays the header row out without any scroll or resize to observe.
  useLayoutEffect(() => { placeRef.current(); });

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown, true);
    };
  }, [onClose]);

  const L = {
    asc: lang === "en" ? "Sort ascending" : lang === "uz" ? "O'sish bo'yicha saralash" : "Сортировать по возрастанию",
    desc: lang === "en" ? "Sort descending" : lang === "uz" ? "Kamayish bo'yicha saralash" : "Сортировать по убыванию",
    start: lang === "en" ? "Move to start" : lang === "uz" ? "Boshiga ko'chirish" : "Переместить в начало",
    left: lang === "en" ? "Move left" : lang === "uz" ? "Chapga ko'chirish" : "Переместить влево",
    right: lang === "en" ? "Move right" : lang === "uz" ? "O'ngga ko'chirish" : "Переместить вправо",
    end: lang === "en" ? "Move to end" : lang === "uz" ? "Oxiriga ko'chirish" : "Переместить в конец",
    pin: lang === "en" ? "Freeze column" : lang === "uz" ? "Ustunni mahkamlash" : "Закрепить столбец",
    unpin: lang === "en" ? "Unfreeze column" : lang === "uz" ? "Mahkamlashni bekor qilish" : "Открепить столбец",
    hide: lang === "en" ? "Hide column" : lang === "uz" ? "Ustunni yashirish" : "Скрыть столбец",
    hideLocked: lang === "en" ? "The price column always stays"
      : lang === "uz" ? "Narx ustuni doim qoladi" : "Столбец с ценой всегда остаётся",
    menu: lang === "en" ? "Column controls" : lang === "uz" ? "Ustun boshqaruvi" : "Управление столбцом",
  };

  const Btn = ({ label, onClick, disabled, active, danger, children }) => (
    <button
      type="button"
      className={`market-colmenu-btn${active ? " is-active" : ""}${danger ? " is-danger" : ""}`}
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
  // 16px stroke glyphs, drawn inline: an icon font is one more thing to load for
  // eight marks, and the board already pays for its fonts.
  const Svg = ({ children }) => (
    <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );

  return createPortal(
    <div
      ref={ref}
      className="market-colmenu"
      role="toolbar"
      aria-label={L.menu}
      style={pos ? { top: pos.top, left: pos.left } : { top: -9999, left: -9999 }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <Btn label={L.asc} active={state.dir === "asc"} onClick={() => actions.sort("asc")}>
        <Svg><path d="M3 4h4" /><path d="M3 8h7" /><path d="M3 12h10" /></Svg>
      </Btn>
      <Btn label={L.desc} active={state.dir === "desc"} onClick={() => actions.sort("desc")}>
        <Svg><path d="M3 4h10" /><path d="M3 8h7" /><path d="M3 12h4" /></Svg>
      </Btn>
      <span className="market-colmenu-sep" aria-hidden="true" />
      <Btn label={L.start} disabled={!state.canLeft} onClick={() => actions.move("start")}>
        <Svg><path d="M3 3v10" /><path d="M14 8H6.5" /><path d="M9.5 5 6.5 8l3 3" /></Svg>
      </Btn>
      <Btn label={L.left} disabled={!state.canLeft} onClick={() => actions.move(-1)}>
        <Svg><path d="M13 8H4" /><path d="M7 5 4 8l3 3" /></Svg>
      </Btn>
      <Btn label={L.right} disabled={!state.canRight} onClick={() => actions.move(1)}>
        <Svg><path d="M3 8h9" /><path d="M9 5l3 3-3 3" /></Svg>
      </Btn>
      <Btn label={L.end} disabled={!state.canRight} onClick={() => actions.move("end")}>
        <Svg><path d="M13 3v10" /><path d="M2 8h7.5" /><path d="M6.5 5l3 3-3 3" /></Svg>
      </Btn>
      <span className="market-colmenu-sep" aria-hidden="true" />
      <Btn label={state.pinned ? L.unpin : L.pin} active={state.pinned} onClick={actions.pin}>
        <Svg><path d="M6 2h4l-.6 3.4 2.1 2.1H4.5l2.1-2.1z" /><path d="M8 7.5V14" /></Svg>
      </Btn>
      <Btn label={state.canHide ? L.hide : L.hideLocked} disabled={!state.canHide} danger onClick={actions.hide}>
        <Svg><path d="M3 4.5h10" /><path d="M6.5 4.5V3h3v1.5" /><path d="M4.5 4.5 5 13.5h6l.5-9" /></Svg>
      </Btn>
    </div>,
    document.body
  );
}

export { MarketColMenu, MarketColsPopover, MarketFloatScroll, MarketStickyHead };
