

/**
 * The root's zoom factor, and the viewport measured in the units a FIXED child of
 * that root is positioned in.
 *
 * Every overlay on this page is portaled to <body> and placed by hand from a
 * `getBoundingClientRect()` — the column picker, the column menu, the sticky
 * header, the float scrollbar, the ⓘ tooltip. A client rect is in VIEWPORT
 * pixels; a `left: 1214px` written onto a fixed element inside a zoomed root is
 * in CSS pixels, which the zoom then multiplies. At 150 % the column picker was
 * placed at left 1214 and rendered at 1821 — entirely outside a 1526px viewport,
 * invisible, with nothing on screen to say why.
 *
 * So: divide a measured coordinate by the zoom before writing it, and clamp
 * against the viewport expressed in the same units.
 */
function rootZoom() {
  if (typeof document === "undefined") return 1;
  const raw = Number(document.documentElement.style.zoom);
  return Number.isFinite(raw) && raw > 0 ? raw : 1;
}

/** {zoom, vw, vh} — the viewport in the units a fixed child of the root uses. */
function zoomedViewport() {
  const zoom = rootZoom();
  return { zoom, vw: window.innerWidth / zoom, vh: window.innerHeight / zoom };
}

export { rootZoom, zoomedViewport };
