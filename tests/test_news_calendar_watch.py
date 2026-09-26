"""Automatic refresh for the source-backed news calendars."""
from __future__ import annotations

import server.news.jobs as subject_server_news_jobs

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import dividends  # noqa: E402
import meetings  # noqa: E402


def test_watch_refreshes_meetings_and_dividends(monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(meetings, "refresh", lambda *, force=False: calls.append(("meetings", force)) or {"ok": True})
    monkeypatch.setattr(dividends, "refresh", lambda *, force=False: calls.append(("dividends", force)) or {"ok": True})

    result = subject_server_news_jobs._news_calendar_watch_once()

    assert result["ok"] is True
    assert calls == [("meetings", True), ("dividends", True)]


def test_one_calendar_failure_does_not_stop_the_other(monkeypatch) -> None:
    calls: list[str] = []

    def fail_meetings(*, force=False):
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(meetings, "refresh", fail_meetings)
    monkeypatch.setattr(dividends, "refresh", lambda *, force=False: calls.append("dividends") or {"ok": True})

    result = subject_server_news_jobs._news_calendar_watch_once()

    assert result["ok"] is False
    assert result["meetings"]["ok"] is False
    assert calls == ["dividends"]
