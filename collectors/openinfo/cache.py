"""Openinfo cache operations with explicit dependencies."""
from __future__ import annotations
import copy
from typing import Any

from pathlib import Path
import collectors.openinfo.settings as collectors_openinfo_settings
import json
import os
import threading
import time


_EXCEL_CACHE_LOCK = threading.Lock()


def _excel_cache_file() -> Path:
    path = collectors_openinfo_settings.EXCEL_CACHE_PATH
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_excel_cache() -> dict[str, Any]:

    """A private top-level copy for a writer to modify and save."""

    return dict(_shared_excel_cache())


def _save_excel_cache(cache: dict[str, Any]) -> None:
    """Write the parse cache atomically.

    This file reaches ~14 MB. A plain ``write_text`` truncates it first, so a crash,
    an OOM kill, or a container restart mid-write leaves a half-written JSON that
    ``_load_excel_cache`` cannot parse — the whole cache silently evaporates and
    every report is re-fetched and re-parsed from openinfo. Writing to a sibling
    temp file and renaming makes the swap a single atomic operation: readers see
    either the old complete file or the new one, never a partial one.
    """
    path = _excel_cache_file()
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())  # rename is only atomic once the bytes are down
        os.replace(tmp, path)  # atomic within a filesystem, and overwrites on Windows
    except Exception:
        collectors_openinfo_settings.logger.exception("excel cache write failed; keeping the previous file")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _get_excel_cache(url: str) -> dict[str, Any] | None:

    if not url or collectors_openinfo_settings.EXCEL_CACHE_TTL_SECONDS <= 0:

        return None

    with _EXCEL_CACHE_LOCK:

        item = _shared_excel_cache().get(url)

    if not item:

        return None

    if time.time() - float(item.get("cached_at") or 0) > collectors_openinfo_settings.EXCEL_CACHE_TTL_SECONDS:

        return None

    payload = item.get("payload")

    if isinstance(payload, dict):

        # A deep copy: callers used to receive a freshly parsed object and may

        # change it; the shared parse must stay as it is on disk.

        payload = copy.deepcopy(payload)

        payload["from_cache"] = True

        return payload

    return None


def _set_excel_cache(url: str, payload: dict[str, Any]) -> None:
    if not url or collectors_openinfo_settings.EXCEL_CACHE_TTL_SECONDS <= 0:
        return
    cached_payload = dict(payload)
    cached_payload["from_cache"] = False
    with _EXCEL_CACHE_LOCK:
        cache = _load_excel_cache()
        cache[url] = {"cached_at": time.time(), "payload": cached_payload}
        # Keep the cache small; parsed snapshots are enough for analysis.
        if len(cache) > 500:
            cache = dict(sorted(cache.items(), key=lambda pair: pair[1].get("cached_at", 0))[-500:])
        _save_excel_cache(cache)


_EXCEL_CACHE_MEMO: tuple[tuple[str, int, int], dict[str, Any]] | None = None


def _shared_excel_cache() -> dict[str, Any]:
    """The parsed cache, re-read only when the file changes. Never mutate it."""
    global _EXCEL_CACHE_MEMO
    path = _excel_cache_file()
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {}
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _EXCEL_CACHE_MEMO is not None and _EXCEL_CACHE_MEMO[0] == key:
        return _EXCEL_CACHE_MEMO[1]
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(cache, dict):
        return {}
    _EXCEL_CACHE_MEMO = (key, cache)
    return cache
