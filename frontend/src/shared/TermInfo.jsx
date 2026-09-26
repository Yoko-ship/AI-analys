import { termFor } from "../lib/glossary.js";
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { zoomedViewport } from "./viewport.jsx";
import { createPortal } from "react-dom";

// The column picker ("Обзор / Объёмы / Фин. показатели / Мультипликаторы").
// It used to be an absolutely-positioned child of the toolbar, which meant it
// rode the page up on the first scroll gesture and — now that the toolbar is
// sticky and .market-board clips — would have been cut off at the board edge.
// Portaled to <body> instead: a fixed popover re-anchored to its button on
// every scroll/resize, and on a phone a bottom sheet with its own scrollport,
// so a thumb drag moves the list of columns and not the page behind it.
/**
 * The ⓘ beside an economic label: what this term means, on hover, at the point
 * the reader met it. Definitions come from lib/glossary.js by id.
 *
 * It is portaled to <body> for the same reason the column picker is — inside the
 * board's horizontal scrollport a positioned child is clipped by the scroll box,
 * so a tooltip on the rightmost header would be cut in half or scroll away from
 * the header that opened it.
 *
 * Hover opens it on a mouse; tap toggles it on a phone, where there is no hover
 * at all. Every pointer event stops at the marker: the header underneath sorts on
 * click and drags to reorder, and asking what a column means must do neither.
 */
function TermInfo({ termId, lang, label }) {
  const entry = termFor(termId, lang);
  const btnRef = useRef(null);
  const popRef = useRef(null);
  const [open, setOpen] = useState(false);
  // A hovered tooltip is `pointer-events: none` — the pointer cannot enter it,
  // which is what keeps it from flickering, and also what made its text
  // impossible to select. A CLICK pins it: it stops following the pointer, takes
  // events, and can be read, selected and copied like any other text on the page.
  const [pinned, setPinned] = useState(false);
  const [copied, setCopied] = useState(false);
  const [pos, setPos] = useState(null);
  const close = React.useCallback(() => { setOpen(false); setPinned(false); setCopied(false); }, []);

  useEffect(() => {
    if (!copied) return undefined;
    const t = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(t);
  }, [copied]);

  useLayoutEffect(() => {
    if (!open) { setPos(null); return undefined; }
    let raf = 0;
    const place = () => {
      raf = 0;
      const btn = btnRef.current;
      if (!btn) return;
      const r = btn.getBoundingClientRect();
      // CSS pixels of the zoomed root, not viewport pixels — see rootZoom().
      const { zoom, vw, vh } = zoomedViewport();
      const mid = (r.left + r.width / 2) / zoom;
      const markerTop = r.top / zoom, markerBottom = r.bottom / zoom;
      const width = Math.min(320, vw - 24);
      const left = Math.max(12, Math.min(mid - width / 2, vw - width - 12));
      // Below the marker by default; above it when the viewport bottom is closer
      // than the tooltip is tall, so it is never half off-screen.
      const below = vh - markerBottom;
      setPos({ left, width, top: below > 190 ? markerBottom + 8 : null,
               bottom: below > 190 ? null : vh - markerTop + 8 });
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(place); };
    place();
    // capture:true — the table's own scrollport does not bubble its scroll event.
    window.addEventListener("scroll", schedule, { passive: true, capture: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
      if (raf) cancelAnimationFrame(raf);
    };
    // Pinning adds the actions row, which changes the height the placement
    // above/below the marker is decided on.
  }, [open, pinned]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") close(); };
    // A press inside the pinned tooltip is the start of a text selection or the
    // copy button — it must not be read as "clicked away".
    const onDocDown = (e) => {
      const inside = (btnRef.current && btnRef.current.contains(e.target))
        || (popRef.current && popRef.current.contains(e.target));
      if (!inside) close();
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDocDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDocDown);
    };
  }, [open, close]);

  // A term with no entry yet renders nothing rather than an ⓘ that explains nothing.
  if (!entry) return null;

  const stop = (e) => { e.stopPropagation(); };
  // What a reader pastes into a chat is the term AND its definition — a bare
  // definition arrives without saying what it defines.
  const copyText = `${entry.term} — ${entry.def}`;
  // The selection + execCommand path every browser still honours, for when the
  // async clipboard is missing, denied, or simply never answers.
  const legacyCopy = () => {
    try {
      const ta = document.createElement("textarea");
      ta.value = copyText;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      const done = document.execCommand("copy");
      ta.remove();
      return done;
    } catch (_) { return false; }
  };
  const copy = async (e) => {
    e.stopPropagation();
    e.preventDefault();
    // navigator.clipboard is the right API and is tried first — but its promise
    // is NOT guaranteed to settle: where the permission is withheld or the
    // window is not the focused one it can hang, and an awaited hang leaves the
    // button saying nothing at all. So it races a short deadline, and anything
    // other than a resolve falls through to the legacy path. The click's user
    // activation outlives the race, so the fallback is still allowed to run.
    const viaApi = navigator.clipboard && navigator.clipboard.writeText
      ? await Promise.race([
          navigator.clipboard.writeText(copyText).then(() => true, () => false),
          new Promise((resolve) => { setTimeout(() => resolve(null), 400); }),
        ])
      : false;
    setCopied(viaApi === true ? true : legacyCopy());
  };
  const tt = (ru, uz, en) => (lang === "en" ? en : lang === "uz" ? uz : ru);
  return (
    <>
      <button
        type="button"
        ref={btnRef}
        className={`term-info-btn${open ? " open" : ""}`}
        aria-label={`${label || entry.term} — ${lang === "en" ? "what this means" : lang === "uz" ? "bu nimani anglatadi" : "что это значит"}`}
        aria-expanded={open}
        // Hover reads, click keeps: the second press unpins, and the tooltip
        // stays up while the pointer is still on the marker.
        onClick={(e) => { e.stopPropagation(); e.preventDefault(); setOpen(true); setPinned((v) => !v); setCopied(false); }}
        onMouseDown={stop}
        onPointerDown={stop}
        onTouchStart={stop}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => { if (!pinned) setOpen(false); }}
        onFocus={() => setOpen(true)}
        onBlur={() => { if (!pinned) setOpen(false); }}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.stopPropagation(); } }}
        onDragStart={(e) => { e.preventDefault(); e.stopPropagation(); }}
      >ℹ</button>
      {open && pos && createPortal(
        <div
          ref={popRef}
          className={`term-tooltip${pinned ? " is-pinned" : ""}`}
          role="tooltip"
          /* Pinned, the tooltip sits over a sortable header and a draggable
             one; nothing that happens inside it belongs to the table. */
          onPointerDown={stop}
          onMouseDown={stop}
          onClick={stop}
          style={{ left: pos.left, width: pos.width, ...(pos.top != null ? { top: pos.top } : { bottom: pos.bottom }) }}
        >
          <div className="term-tooltip-term">{entry.term}</div>
          <div className="term-tooltip-def">{entry.def}</div>
          {pinned ? (
            <div className="term-tooltip-actions">
              <button
                type="button"
                className={`term-tooltip-copy${copied ? " is-done" : ""}`}
                onClick={copy}
              >
                {copied ? tt("Скопировано", "Nusxalandi", "Copied") : tt("Копировать", "Nusxalash", "Copy")}
              </button>
              <span className="term-tooltip-hint">{tt("Esc — закрыть", "Esc — yopish", "Esc to close")}</span>
            </div>
          ) : (
            /* A tooltip that vanishes when approached teaches nobody that it
               can be kept. Said once, quietly, where the question is asked. */
            <div className="term-tooltip-teach">
              {tt("Нажмите, чтобы выделить и скопировать",
                  "Ajratib nusxalash uchun bosing",
                  "Click to select and copy")}
            </div>
          )}
        </div>,
        document.body,
      )}
    </>
  );
}

export { TermInfo };
