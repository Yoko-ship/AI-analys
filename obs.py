"""obs.py — chain logging: how a number on the screen was arrived at.

ТЗ v1.2 §12. Every derived figure can be replayed step by step under one
``trace_id``: the input, the decision taken and why, and the output. A refusal is
logged in more detail than a success, because a value explains itself and a dash
does not.

The store is an in-process ring buffer, not a table. That is a deliberate scope
choice: the point is to answer "where did this number come from" while the
process is up, not to build an audit database. Persisting it is the auditor
module's job (ТЗ v1.3 §12), and the interface here is the one it would read.

Nothing in the calculation path may depend on tracing being enabled — the
recorder is a no-op sink when it is off, and no formula reads back what it wrote.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

_MAX_TRACES = int(os.getenv("TRACE_BUFFER", "512"))
_lock = threading.Lock()
_traces: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

# Tracing is on by default in development and off in production unless asked
# for: the buffer is small and bounded, but recording every market request is
# still work nobody asked for.
ENABLED = os.getenv("TRACE_CHAINS", "1").strip().lower() not in {"0", "false", "no"}


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


class Trace:
    """Recorder for one chain. Safe to use when tracing is off."""

    __slots__ = ("trace_id", "_steps", "_started", "_meta")

    def __init__(self, trace_id: str | None = None, **meta: Any) -> None:
        self.trace_id = trace_id or new_trace_id()
        self._steps: list[dict[str, Any]] = []
        self._started = time.time()
        self._meta = meta

    def step(self, name: str, *, decision: str | None = None, reason: str | None = None,
             **payload: Any) -> None:
        """One link: what went in, what was decided and why, what came out."""
        if not ENABLED:
            return
        self._steps.append({
            "step": len(self._steps) + 1,
            "name": name,
            "decision": decision,
            "reason": reason,
            **{k: v for k, v in payload.items() if v is not None},
        })

    def reject(self, name: str, reason: str, **payload: Any) -> None:
        """A refusal, recorded in full — this is the case a reader needs explained."""
        self.step(name, decision="reject", reason=reason, **payload)

    def close(self) -> dict[str, Any]:
        record = {
            "trace_id": self.trace_id,
            "duration_ms": round((time.time() - self._started) * 1000, 1),
            "started_at": self._started,
            **self._meta,
            "steps": self._steps,
        }
        if ENABLED:
            with _lock:
                _traces[self.trace_id] = record
                while len(_traces) > _MAX_TRACES:
                    _traces.popitem(last=False)
        return record


def get_trace(trace_id: str) -> dict[str, Any] | None:
    with _lock:
        return _traces.get(trace_id)


def recent_traces(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        items = list(_traces.values())[-limit:]
    return [{k: v for k, v in t.items() if k != "steps"} | {"steps": len(t["steps"])}
            for t in reversed(items)]


def clear() -> None:
    with _lock:
        _traces.clear()
