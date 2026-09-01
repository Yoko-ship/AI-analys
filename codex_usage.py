"""Best-effort account-limit snapshots for subscription-backed Codex jobs.

The Codex CLI's app-server protocol reports the account's own rolling-window
percentage.  Reading it consumes no model call.  This module deliberately fails
open: news collection must still run if a CLI version or account cannot expose
the snapshot.
"""
from __future__ import annotations

import json
import logging
import queue
import shutil
import subprocess
import threading
import time
from typing import Any

from codex_client import safe_codex_environment

logger = logging.getLogger(__name__)


def _parse_rate_limit(result: dict[str, Any]) -> dict[str, Any] | None:
    limits = result.get("rateLimitsByLimitId") or {}
    selected_id = "codex" if "codex" in limits else None
    selected = limits.get(selected_id) if selected_id else result.get("rateLimits")
    if not isinstance(selected, dict):
        return None
    primary = selected.get("primary")
    if not isinstance(primary, dict) or primary.get("usedPercent") is None:
        return None
    return {
        "limit_id": selected_id or "default",
        "used_percent": float(primary["usedPercent"]),
        "window_minutes": int(primary["windowDurationMins"])
        if primary.get("windowDurationMins") is not None else None,
        "resets_at": int(primary["resetsAt"]) if primary.get("resetsAt") is not None else None,
        "plan_type": selected.get("planType"),
    }


def read_codex_rate_limit(*, executable: str = "codex", timeout: float = 15.0) -> dict[str, Any] | None:
    """Return the account's main Codex limit snapshot, or ``None`` if unavailable."""
    resolved = shutil.which(executable)
    if not resolved:
        logger.warning("Codex usage snapshot unavailable: executable %r was not found", executable)
        return None

    process: subprocess.Popen[str] | None = None
    messages: queue.Queue[str | None] = queue.Queue()
    try:
        process = subprocess.Popen(
            [resolved, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=safe_codex_environment(),
        )
        assert process.stdin is not None and process.stdout is not None

        def read_stdout() -> None:
            try:
                for line in process.stdout:
                    messages.put(line)
            finally:
                messages.put(None)

        threading.Thread(target=read_stdout, daemon=True).start()
        requests = (
            {"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "news-usage-tracker", "version": "1.0"},
                "capabilities": {"experimentalApi": True},
            }},
            {"id": 2, "method": "account/rateLimits/read"},
        )
        for request in requests:
            process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        process.stdin.flush()

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = messages.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == 2 and isinstance(message.get("result"), dict):
                return _parse_rate_limit(message["result"])
        logger.warning("Codex usage snapshot unavailable: app-server did not reply in %.0fs", timeout)
    except (OSError, ValueError, BrokenPipeError) as exc:
        logger.warning("Codex usage snapshot unavailable: %s", exc)
    finally:
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
    return None
