"""cache_layer.py — responses cached by REVISION, not by a clock (ТЗ §10.9).

"While the revision has not changed, the answer may be served from cache for as
long as you like." That is the rule, and it is the reason the cache key carries
a revision rather than a TTL: a five-minute expiry either serves stale numbers
for five minutes or throws away a perfectly good answer, and which of the two
you get is luck.

Redis when it is configured, an in-process dictionary when it is not. The
interface is the same either way, so nothing above this module knows or cares —
and a Redis outage degrades to the local cache rather than to an error, because
a cache that can fail the request it was meant to speed up is worse than none.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

_REDIS_URL = os.getenv("REDIS_URL", "").strip()
_DEFAULT_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))
_MAX_LOCAL_ENTRIES = 512

_lock = threading.Lock()
_local: dict[str, tuple[float, Any]] = {}
_redis: Any = None
_redis_checked = False


def _client() -> Any:
    """The Redis client, or None. Probed once — a missing package or an
    unreachable server is a configuration fact, not a per-call decision."""
    global _redis, _redis_checked
    if _redis_checked:
        return _redis
    _redis_checked = True
    if not _REDIS_URL:
        return None
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(_REDIS_URL, socket_timeout=1.5,
                                      socket_connect_timeout=1.5, decode_responses=True)
        client.ping()
        _redis = client
        logger.info("cache: redis at %s", _REDIS_URL.split("@")[-1])
    except Exception:  # noqa: BLE001 — degrade to local, never fail startup
        logger.warning("cache: redis unavailable, using in-process cache")
        _redis = None
    return _redis


def key(scope: str, revision: Any, *parts: Any) -> str:
    """`market:multiples:rev=1487:months=12`.

    The revision is IN the key, so a new revision does not invalidate anything —
    it simply misses, and the old entry ages out on its own. There is no
    invalidation step to forget to call.
    """
    tail = ":".join(str(p) for p in parts if p is not None)
    return f"{scope}:rev={revision}" + (f":{tail}" if tail else "")


def get(name: str) -> Any:
    client = _client()
    if client is not None:
        try:
            raw = client.get(name)
            return json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001 — a cache read must never break a request
            logger.warning("cache: redis read failed for %s", name)
    with _lock:
        hit = _local.get(name)
        if not hit:
            return None
        expires, value = hit
        if expires < time.time():
            _local.pop(name, None)
            return None
        return value


def set(name: str, value: Any, ttl: int | None = None) -> None:  # noqa: A001
    ttl = ttl or _DEFAULT_TTL
    client = _client()
    if client is not None:
        try:
            client.setex(name, ttl, json.dumps(value, default=str, ensure_ascii=False))
            return
        except Exception:  # noqa: BLE001
            logger.warning("cache: redis write failed for %s", name)
    with _lock:
        if len(_local) >= _MAX_LOCAL_ENTRIES:
            oldest = min(_local, key=lambda k: _local[k][0])
            _local.pop(oldest, None)
        _local[name] = (time.time() + ttl, value)


def cached(name: str, produce: Callable[[], Any], ttl: int | None = None) -> Any:
    """Return the cached value, or produce, store and return it."""
    hit = get(name)
    if hit is not None:
        return hit
    value = produce()
    if value is not None:
        set(name, value, ttl)
    return value


def clear() -> None:
    with _lock:
        _local.clear()
    client = _client()
    if client is not None:
        try:
            client.flushdb()
        except Exception:  # noqa: BLE001
            pass


def backend() -> str:
    return "redis" if _client() is not None else "memory"
