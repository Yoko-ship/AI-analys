import { useCallback, useEffect, useRef } from 'react';
import { trackProductAction } from './productActions.js';

/** Observe once when successful content is on screen, including a background-tab reveal. */
export function useProductObserver(action) {
  const key = JSON.stringify(action), last = useRef('');
  return useCallback(element => {
    if (!element || last.current === key || typeof IntersectionObserver !== 'function') return () => {};
    let inView = false, frame = 0, retries = 0, cancelled = false;
    const report = () => {
      if (cancelled || last.current === key || !inView || document.visibilityState !== 'visible') return;
      if (trackProductAction(JSON.parse(key))) last.current = key;
      else if (retries++ < 3) frame = requestAnimationFrame(report);
    };
    const observer = new IntersectionObserver(entries => { inView = entries.some(e => e.isIntersecting); report(); });
    observer.observe(element);
    document.addEventListener('visibilitychange', report);
    return () => { cancelled = true; observer.disconnect(); cancelAnimationFrame(frame); document.removeEventListener('visibilitychange', report); };
  }, [key]);
}

export function useProductObservation(ref, action, ready = true) {
  const observe = useProductObserver(action);
  useEffect(() => ready ? observe(ref.current) : undefined, [ref, observe, ready]);
}
