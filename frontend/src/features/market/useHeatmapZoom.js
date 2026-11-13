import {useCallback, useEffect, useLayoutEffect, useRef, useState} from 'react';

const limit = value => Math.max(1, Math.min(8, value));
const midpoint = touches => ({
  x: (touches[0].clientX + touches[1].clientX) / 2,
  y: (touches[0].clientY + touches[1].clientY) / 2,
});
const distance = touches => Math.hypot(
  touches[0].clientX - touches[1].clientX, touches[0].clientY - touches[1].clientY);

export function useHeatmapZoom(closePreview) {
  const [zoom, setZoom] = useState(1);
  const viewportRef = useRef(null);
  const currentZoom = useRef(1);
  const pendingScroll = useRef(null);
  const pinch = useRef(null);
  const suppressClick = useRef(false);

  const changeZoom = useCallback((value, anchoredScroll) => {
    const next = limit(value), previous = currentZoom.current;
    const viewport = viewportRef.current;
    if (viewport) {
      const scroll = next === 1 ? {left: 0, top: 0} : anchoredScroll || {
        left: (viewport.scrollLeft + viewport.clientWidth / 2) * next / previous - viewport.clientWidth / 2,
        top: (viewport.scrollTop + viewport.clientHeight / 2) * next / previous - viewport.clientHeight / 2,
      };
      if (next === previous) viewport.scrollTo({...scroll, behavior:'instant'});
      else pendingScroll.current = scroll;
    }
    currentZoom.current = next;
    setZoom(next);
    closePreview();
  }, [closePreview]);

  useLayoutEffect(() => {
    if (pendingScroll.current && viewportRef.current) {
      viewportRef.current.scrollTo({...pendingScroll.current, behavior:'instant'});
      pendingScroll.current = null;
    }
  }, [zoom]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return undefined;
    const start = event => {
      if (event.touches.length < 2) {
        if (!pinch.current) suppressClick.current = false;
        return;
      }
      if (event.cancelable) event.preventDefault();
      const span = distance(event.touches);
      if (!span) return;
      const point = midpoint(event.touches), box = viewport.getBoundingClientRect();
      const scale = currentZoom.current;
      pinch.current = {span, scale,
        x: (viewport.scrollLeft + point.x - box.left) / scale,
        y: (viewport.scrollTop + point.y - box.top) / scale};
      suppressClick.current = true;
      closePreview();
    };
    const move = event => {
      if (!pinch.current || event.touches.length < 2) return;
      if (event.cancelable) event.preventDefault();
      const point = midpoint(event.touches), box = viewport.getBoundingClientRect();
      const gesture = pinch.current;
      const scale = limit(gesture.scale * distance(event.touches) / gesture.span);
      changeZoom(scale, {left: gesture.x * scale - (point.x - box.left),
        top: gesture.y * scale - (point.y - box.top)});
    };
    const end = event => {
      // Lifting a finger after a pinch must not open the tile beneath it.
      if (suppressClick.current && event.cancelable) event.preventDefault();
      if (event.touches.length < 2) pinch.current = null;
      else start(event);
    };
    const handlers = {touchstart:start, touchmove:move, touchend:end, touchcancel:end};
    for (const [name, handler] of Object.entries(handlers)) viewport.addEventListener(name, handler, {passive:false});
    return () => {
      for (const [name, handler] of Object.entries(handlers)) viewport.removeEventListener(name, handler);
    };
  }, [changeZoom, closePreview]);

  return {zoom, changeZoom, viewportRef,
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
