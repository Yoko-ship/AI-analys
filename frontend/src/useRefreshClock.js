import { useEffect, useState } from "react";

// Refresh visible data every five minutes and after returning to the tab.
export default function useRefreshClock(enabled = true) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!enabled) return undefined;
    const refresh = () => { if (!document.hidden) setTick((n) => n + 1); };
    const timer = setInterval(refresh, 300000);
    document.addEventListener("visibilitychange", refresh);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", refresh); };
  }, [enabled]);
  return tick;
}
