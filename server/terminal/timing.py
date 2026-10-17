"""Server-side half of the journal's error and speed events.

A pure ASGI middleware over every ``/api/`` request:

* a response of 500 or more, or an exception escaping the app, is written as
  ``api_error`` with the same ``error_id`` the client was shown
  (server/hardening.py puts it on ``request.state``), so one id leads from a
  user's report to the journal row;
* a GET answered after more than ``TERMINAL_SLOW_MS`` (3 s, the ТЗ's
  threshold) is written as ``api_slow``. Writes are left out because some of
  them are slow by design: AI analysis, admin syncs.

The time measured runs to the first response byte, which is what the user
waits for. Beacon endpoints are skipped so that the journal does not record
itself.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any
import uuid

from server.terminal import journal

SLOW_MS = int(os.getenv("TERMINAL_SLOW_MS", "3000"))

_SKIP = ("/api/track", "/api/terminal/events", "/api/health", "/api/ready")

# The ticker a request is about, when its path names one.
_TICKER_PATH = re.compile(
    r"^/api/(?:v\d+/)?(?:company|catalog/(?:peers|index|company)|dividends|news/ticker|issuers)/([A-Za-z0-9]{2,12})(?:/|$)")


def ticker_of(path: str) -> str | None:
    match = _TICKER_PATH.match(path)
    return match.group(1).upper() if match else None


class JournalTimingMiddleware:
    def __init__(self, app: Any, slow_ms: int | None = None) -> None:
        self.app = app
        self.slow_ms = SLOW_MS if slow_ms is None else slow_ms

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if not path.startswith("/api/") or path.startswith(_SKIP):
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = {"code": None, "ms": None}

        async def timed_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                status["ms"] = (time.perf_counter() - started) * 1000
            await send(message)

        try:
            await self.app(scope, receive, timed_send)
        except Exception as exc:
            self._record(scope, path, 500, (time.perf_counter() - started) * 1000,
                         uuid.uuid4().hex[:12], f"{type(exc).__name__}")
            raise
        if status["code"] is not None:
            error_id = (scope.get("state") or {}).get("error_id")
            self._record(scope, path, status["code"], status["ms"], error_id, "")

    def _record(self, scope: dict, path: str, code: int, ms: float, error_id: str | None,
                reason: str) -> None:
        method = scope.get("method", "GET")
        try:
            if code >= 500:
                journal.emit("api_error", ticker=ticker_of(path), duration_ms=ms, error_id=error_id,
                             message=f"{method} {path} → {code}" + (f" ({reason})" if reason else ""),
                             details={"path": path, "method": method, "status": code})
            elif method == "GET" and ms > self.slow_ms:
                journal.emit("api_slow", ticker=ticker_of(path), duration_ms=ms,
                             message=f"{method} {path}: {ms / 1000:.1f} s",
                             details={"path": path, "method": method, "status": code})
        except Exception:
            # The journal must never turn a served response into a failure.
            pass
