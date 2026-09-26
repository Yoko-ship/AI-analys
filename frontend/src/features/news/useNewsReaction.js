import React from "react";
import { useTranslationTick } from "./newsTranslation.js";
export function useNewsReaction({
  newsId
}) {
  const [state, setState] = React.useState({
    loading: true,
    items: []
  });
  useTranslationTick();
  React.useEffect(() => {
    let alive = true;
    setState({
      loading: true,
      items: []
    });
    fetch(`/api/news/item/${encodeURIComponent(newsId)}/reaction`).then(r => r.json()).then(d => {
      if (alive) setState({
        loading: false,
        items: d && d.ok && d.items || []
      });
    }).catch(() => {
      if (alive) setState({
        loading: false,
        items: []
      });
    });
    return () => {
      alive = false;
    };
  }, [newsId]);
  return {
    state
  };
}
