import React from "react";
import { useBrowserHeadline } from "./newsTranslation.js";
export function useNewsArticle({
  language,
  newsId
}) {
  const [state, setState] = React.useState({
    loading: true,
    error: "",
    data: null
  });
  const [imgOk, setImgOk] = React.useState(true);
  const [imgSmall, setImgSmall] = React.useState(false);
  const browser = useBrowserHeadline(state.data ? state.data.item : null, language);
  React.useEffect(() => {
    let alive = true;
    setState({
      loading: true,
      error: "",
      data: null
    });
    setImgOk(true);
    setImgSmall(false);
    window.scrollTo({
      top: 0,
      behavior: "auto"
    });
    fetch(`/api/news/item/${encodeURIComponent(newsId)}`).then(async r => ({
      status: r.status,
      body: await r.json().catch(() => null)
    })).then(({
      status,
      body
    }) => {
      if (!alive) return;
      if (body && body.ok) setState({
        loading: false,
        error: "",
        data: body
      });
      // 422 = a hand-typed /news/{something-that-is-not-an-id}: still "no such story".
      else setState({
        loading: false,
        error: status === 404 || status === 422 ? "notFound" : "error",
        data: null
      });
    }).catch(() => {
      if (alive) setState({
        loading: false,
        error: "error",
        data: null
      });
    });
    return () => {
      alive = false;
    };
  }, [newsId]);
  return {
    state,
    imgOk,
    setImgOk,
    imgSmall,
    setImgSmall,
    browser
  };
}
