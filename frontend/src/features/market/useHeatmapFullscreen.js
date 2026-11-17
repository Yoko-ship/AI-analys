import {useCallback, useEffect, useRef, useState} from 'react';

export function useHeatmapFullscreen() {
  const element = useRef(null);
  const button = useRef(null);
  const native = useRef(false);
  const [expanded, setExpanded] = useState(false);
  const restore = useCallback(() => {
    setExpanded(false);
    if (document.fullscreenElement === element.current) document.exitFullscreen?.().catch(() => {});
  }, []);

  useEffect(() => {
    const changed = () => {
      if (document.fullscreenElement === element.current) native.current = true;
      else if (native.current) { native.current = false; setExpanded(false); }
    };
    document.addEventListener('fullscreenchange', changed);
    return () => document.removeEventListener('fullscreenchange', changed);
  }, []);

  useEffect(() => {
    if (!expanded) return undefined;
    const node = element.current;
    const trigger = button.current;
    const viewport = node.querySelector('.heatmap-viewport');
    const previousOverflow = document.body.style.overflow;
    // The treemap recalculates labels and tile positions from its real size.
    const measure = () => node.style.setProperty('--heatmap-base-height', `${viewport.clientHeight}px`);
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    measure();
    document.body.style.overflow = 'hidden';
    trigger?.focus({preventScroll: true});
    const keydown = event => {
      if (event.key === 'Escape') { event.preventDefault(); restore(); }
      if (event.key !== 'Tab') return;
      const controls = [...node.querySelectorAll('button, [tabindex]')]
        .filter(control => !control.disabled && control.tabIndex >= 0 && control.getClientRects().length);
      if (document.activeElement === (event.shiftKey ? controls[0] : controls.at(-1))) {
        event.preventDefault();
        (event.shiftKey ? controls.at(-1) : controls[0])?.focus();
      }
    };
    document.addEventListener('keydown', keydown);
    return () => {
      observer.disconnect();
      node.style.removeProperty('--heatmap-base-height');
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', keydown);
      trigger?.focus({preventScroll: true});
    };
  }, [expanded, restore]);

  const toggle = () => {
    if (expanded) { restore(); return; }
    setExpanded(true);
    // Mobile and embedded browsers may omit or reject the native API.
    try { element.current?.requestFullscreen?.()?.catch?.(() => {}); } catch { /* viewport fallback */ }
  };
  return {element, button, expanded, toggle};
}
