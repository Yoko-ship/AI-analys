import { useEffect, useRef, useState } from "react";
export function useMarketSorting() {
  const [sortKeys, setSortKeys] = useState([]);
  const defaultSortDir = key => ["ticker", "company"].includes(key) ? "asc" : "desc";
  const sortRankOf = key => sortKeys.findIndex(s => s.key === key);
  const sortDirOf = key => sortKeys.find(s => s.key === key)?.dir || null;
  const onSort = (key, additive = false) => {
    setSortKeys(prev => {
      const i = prev.findIndex(s => s.key === key);
      if (!additive) {
        // Re-clicking the only active key flips it; anything else starts over.
        if (prev.length === 1 && i === 0) return [{
          key,
          dir: prev[0].dir === "asc" ? "desc" : "asc"
        }];
        return [{
          key,
          dir: defaultSortDir(key)
        }];
      }
      if (i < 0) return [...prev, {
        key,
        dir: defaultSortDir(key)
      }];
      const next = [...prev];
      if (next[i].dir === defaultSortDir(key)) {
        next[i] = {
          key,
          dir: next[i].dir === "asc" ? "desc" : "asc"
        };
        return next;
      }
      next.splice(i, 1);
      return next;
    });
  };
  const clearSort = () => setSortKeys([]);
  const longPress = useRef({
    timer: null,
    fired: false
  });
  const startLongPress = key => {
    longPress.current.fired = false;
    clearTimeout(longPress.current.timer);
    longPress.current.timer = setTimeout(() => {
      longPress.current.fired = true;
      onSort(key, true);
    }, 500);
  };
  const cancelLongPress = () => clearTimeout(longPress.current.timer);
  useEffect(() => () => clearTimeout(longPress.current.timer), []);
  const [sortHintSeen, setSortHintSeen] = useState(() => {
    try {
      return localStorage.getItem("uz_market_sort_hint") === "seen";
    } catch (e) {
      return false;
    }
  });
  const dismissSortHint = () => {
    setSortHintSeen(true);
    try {
      localStorage.setItem("uz_market_sort_hint", "seen");
    } catch (e) {/* ignore */}
  };
  useEffect(() => {
    if (sortKeys.length > 1 && !sortHintSeen) dismissSortHint();
  }, [sortKeys.length, sortHintSeen]);
  const coarsePointer = typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
  return {
    sortKeys,
    setSortKeys,
    sortRankOf,
    sortDirOf,
    onSort,
    clearSort,
    longPress,
    startLongPress,
    cancelLongPress,
    sortHintSeen,
    dismissSortHint,
    coarsePointer
  };
}
