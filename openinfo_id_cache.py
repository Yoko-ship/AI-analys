"""Openinfo answers that are kept by id between runs, so a run asks only for what is new.

A filed report or material fact does not change under its id: a correction is
a NEW filing with its own id and a later pub_date, which every reader here
already picks by date. So the daily collector does not need to download the
same filing every morning — it did, ~1 000+ requests a day of identical
answers. Nothing proves openinfo never edits a filing in place, though, so an
entry is trusted for 4–7 days only (spread by key, so the whole cache does not
expire on one morning) and is then fetched again: an in-place edit reaches the
site within a week at worst.

OPENINFO_CACHE=0 bypasses every cache (reads nothing, writes nothing): the
first run of the day is then what the collector did before this module.

The file lives in the data directory (the volume the collectors share). Saving
is atomic — a temp file renamed over the old one — so a killed run leaves the
previous cache, never half a file.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TTL_MIN_DAYS = 4
TTL_SPREAD_DAYS = 3  # 4..7 days by key


def enabled() -> bool:
    return os.getenv("OPENINFO_CACHE", "1").strip().lower() not in {"0", "false", "no", "off"}


def _state_dir() -> Path:
    try:
        from db import APP_DATA_DIR
        return Path(APP_DATA_DIR)
    except Exception:  # noqa: BLE001 — a bare script caches next to the module
        return Path(os.getenv("APP_DATA_DIR") or Path(__file__).with_name("data"))


def ttl_seconds(key: str) -> float:
    """4–7 days, fixed per key: a whole cache filled in one run expires over four mornings."""
    spread = int(hashlib.sha1(key.encode()).hexdigest(), 16) % (TTL_SPREAD_DAYS + 1)
    return (TTL_MIN_DAYS + spread) * 86400.0


class IdCache:
    """``{key: (fetched_at, value)}`` in ``openinfo-cache-<name>.json``."""

    def __init__(self, name: str):
        self.name = name
        self._entries: dict[str, list] | None = None
        self._dirty = False
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    @property
    def path(self) -> Path:
        return _state_dir() / f"openinfo-cache-{self.name}.json"

    def _load(self) -> dict[str, list]:
        if self._entries is None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._entries = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._entries = {}
        return self._entries

    def get(self, key: Any) -> Any | None:
        """The kept value while it is fresh, else None (the caller fetches)."""
        if not enabled():
            return None
        key = str(key)
        with self._lock:
            entry = self._load().get(key)
        if (isinstance(entry, list) and len(entry) == 2
                and time.time() - float(entry[0]) < ttl_seconds(f"{self.name}:{key}")):
            self.hits += 1
            return entry[1]
        self.misses += 1
        return None

    def put(self, key: Any, value: Any) -> None:
        if not enabled() or value is None:
            return
        with self._lock:
            self._load()[str(key)] = [time.time(), value]
            self._dirty = True

    def replace(self, key: Any, value: Any) -> None:
        """Update a kept value but keep its age: it still expires when first fetched + TTL."""
        if not enabled() or value is None:
            return
        with self._lock:
            entry = self._load().get(str(key))
            fetched = float(entry[0]) if isinstance(entry, list) and len(entry) == 2 else time.time()
            self._entries[str(key)] = [fetched, value]
            self._dirty = True

    def drop(self, key: Any) -> None:
        with self._lock:
            if self._load().pop(str(key), None) is not None:
                self._dirty = True

    def save(self) -> None:
        """Write the cache atomically; expired entries are left out."""
        with self._lock:
            if not self._dirty or self._entries is None:
                return
            now = time.time()
            keep = {k: v for k, v in self._entries.items()
                    if isinstance(v, list) and len(v) == 2
                    and now - float(v[0]) < ttl_seconds(f"{self.name}:{k}")}
            try:
                path = self.path
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(f".{os.getpid()}.tmp")
                tmp.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, path)
                self._dirty = False
            except OSError:
                log.warning("openinfo cache %s could not be saved", self.name, exc_info=True)
        log.info("openinfo cache %s: %d hits, %d fetched, %d kept",
                 self.name, self.hits, self.misses, len(keep))
