import {useCallback, useEffect, useLayoutEffect, useRef, useState} from 'react';

const limit = value => Math.max(1, Math.min(8, value));
const midpoint = touches => ({
  x: (touches[0].clientX + touches[1].clientX) / 2,
  y: (touches[0].clientY + touches[1].clientY) / 2,
});
const distance = touches => Math.hypot(
  touches[0].clientX - touches[1].clientX, touches[0].clientY - touches[1].clientY);
const pointInViewport = (viewport, point) => {
  const box = viewport.getBoundingClientRect();
  return {x: point.x - box.left, y: point.y - box.top};
};

export function useHeatmapZoom(closePreview, wheelZoom) {
  const [zoom, setZoom] = useState(1);
  const [viewport, setViewport] = useState(null);
  const currentZoom = useRef(1);
  const pendingScroll = useRef(null);
  const pinch = useRef(null);
  const suppressClick = useRef(false);

  const changeZoom = useCallback((value, point, anchor) => {
    const next = limit(value), previous = currentZoom.current;
    if (viewport) {
      const target = point || {x: viewport.clientWidth / 2, y: viewport.clientHeight / 2};
      const {left, top} = pendingScroll.current || {left: viewport.scrollLeft, top: viewport.scrollTop};
      const origin = anchor || {x: (left + target.x) / previous, y: (top + target.y) / previous};
      const scroll = next === 1 ? {left: 0, top: 0} : {
        left: origin.x * next - target.x,
        top: origin.y * next - target.y,
      };
      if (next !== previous || pendingScroll.current) pendingScroll.current = scroll;
      else viewport.scrollTo({...scroll, behavior:'instant'});
    }
    currentZoom.current = next;
    setZoom(next);
    closePreview();
  }, [viewport, closePreview]);

  useLayoutEffect(() => {
    if (pendingScroll.current && viewport) {
      viewport.scrollTo({...pendingScroll.current, behavior:'instant'});
      pendingScroll.current = null;
    }
  }, [viewport, zoom]);

  useEffect(() => {
    if (!viewport) return undefined;
    const start = event => {
      if (event.touches.length < 2) {
        if (!pinch.current) suppressClick.current = false;
        return;
      }
      if (event.cancelable) event.preventDefault();
      const span = distance(event.touches);
      if (!span) return;
      const point = pointInViewport(viewport, midpoint(event.touches));
      const scale = currentZoom.current;
      pinch.current = {span, scale, anchor: {
        x: (viewport.scrollLeft + point.x) / scale,
        y: (viewport.scrollTop + point.y) / scale,
      }};
      suppressClick.current = true;
      closePreview();
    };
    const move = event => {
      if (!pinch.current || event.touches.length < 2) return;
      if (event.cancelable) event.preventDefault();
      const point = pointInViewport(viewport, midpoint(event.touches));
      const {span, scale, anchor} = pinch.current;
      changeZoom(scale * distance(event.touches) / span, point, anchor);
    };
    const end = event => {
      // Lifting a finger after a pinch must not open the tile beneath it.
      if (suppressClick.current && event.cancelable) event.preventDefault();
      if (event.touches.length < 2) pinch.current = null;
      else start(event);
    };
    const wheel = event => {
      if (!event.cancelable || event.shiftKey) return;
      const {deltaMode, deltaX, deltaY} = event;
      if (Math.abs(deltaY) <= Math.abs(deltaX)) return;
      const unit = deltaMode === WheelEvent.DOM_DELTA_LINE ? 16
        : deltaMode === WheelEvent.DOM_DELTA_PAGE ? viewport.clientHeight : 1;
      const previous = currentZoom.current;
      const next = limit(previous * Math.exp(-deltaY * unit / 500));
      if (next === previous) return;
      event.preventDefault();
      changeZoom(next, pointInViewport(viewport, {x: event.clientX, y: event.clientY}));
    };
    const handlers = {touchstart:start, touchmove:move, touchend:end, touchcancel:end, ...(wheelZoom ? {wheel} : {})};
    for (const [name, handler] of Object.entries(handlers)) viewport.addEventListener(name, handler, {passive:false});
    return () => {
      for (const [name, handler] of Object.entries(handlers)) viewport.removeEventListener(name, handler);
    };
  }, [viewport, wheelZoom, changeZoom, closePreview]);

  return {zoom, changeZoom, setViewport,
    onClickCapture: event => {
      if (suppressClick.current && event.detail > 0) {
        event.preventDefault();
        event.stopPropagation();
      }
    },
    onPointerDownCapture: event => {
      if (event.pointerType !== 'touch') suppressClick.current = false;
    },
  };
}
