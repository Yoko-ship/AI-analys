from __future__ import annotations

from typing import Any
import asyncio
import os
import server.http as http


# Keep the public news calendar current even when nobody has the page open.
# Client reads still have a stale-while-revalidate guard, but a scheduler is
# what makes a newly published meeting or dividend appear without depending on
# visitor traffic or the once-daily collector.
NEWS_CALENDAR_WATCH = os.getenv("NEWS_CALENDAR_WATCH", "1").strip().lower() not in {"0", "false", "no"}


NEWS_CALENDAR_WATCH_INTERVAL_MIN = int(os.getenv("NEWS_CALENDAR_WATCH_INTERVAL_MIN", "60"))


def _news_calendar_watch_once() -> dict[str, Any]:
    """Refresh both source-backed news calendars without visitor traffic."""
    import dividends as dividends_store
    import meetings as meetings_store

    result: dict[str, Any] = {"ok": True}
    for name, refresh in (("meetings", meetings_store.refresh),
                          ("dividends", dividends_store.refresh)):
        try:
            result[name] = refresh(force=True)
        except Exception as exc:  # one source must not stop the other
            http.logger.exception("news calendar watch failed for %s", name)
            result["ok"] = False
            result[name] = {"ok": False, "error": str(exc)}
    return result


async def _news_calendar_watch_loop() -> None:
    """Refresh after boot and then hourly (configurable) for the process lifetime."""
    loop = asyncio.get_running_loop()
    await asyncio.sleep(60)
    while True:
        await loop.run_in_executor(None, _news_calendar_watch_once)
        await asyncio.sleep(max(300, NEWS_CALENDAR_WATCH_INTERVAL_MIN * 60))
