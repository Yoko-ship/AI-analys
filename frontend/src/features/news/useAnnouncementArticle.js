import React from "react";
export function useAnnouncementArticle({
  announcementId,
  lang
}) {
  const [state, setState] = React.useState({
    loading: true,
    error: "",
    item: null
  });
  React.useEffect(() => {
    let alive = true;
    setState({
      loading: true,
      error: "",
      item: null
    });
    window.scrollTo({
      top: 0,
      behavior: "auto"
    });
    fetch(`/api/news/calendar/announcements/${encodeURIComponent(announcementId)}?language=${lang}`).then(async r => ({
      status: r.status,
      body: await r.json().catch(() => null)
    })).then(({
      status,
      body
    }) => {
      if (!alive) return;
      if (body && body.ok && body.item) {
        setState({
          loading: false,
          error: "",
          item: body.item
        });
      } else {
        setState({
          loading: false,
          error: status === 404 || status === 422 ? "notFound" : "error",
          item: null
        });
      }
    }).catch(() => {
      if (alive) setState({
        loading: false,
        error: "error",
        item: null
      });
    });
    return () => {
      alive = false;
    };
  }, [announcementId, lang]);
  return {
    state
  };
}
