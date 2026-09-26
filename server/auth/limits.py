from __future__ import annotations

from fastapi import HTTPException
from fastapi import Request
import os
import server.http as http
import threading
import time
import web_auth as identity


# ---------------------------------------------------------------------------
# Abuse limits (in-memory; prod runs a single uvicorn worker).
# ---------------------------------------------------------------------------

AUTH_RATE_LIMIT_PER_MINUTE = int(os.getenv("AUTH_RATE_LIMIT_PER_MINUTE", "10"))


LLM_RATE_LIMIT_PER_MINUTE = int(os.getenv("LLM_RATE_LIMIT_PER_MINUTE", "5"))


LLM_DAILY_LIMIT = int(os.getenv("LLM_DAILY_LIMIT", "50"))


# Deployment-wide daily ceiling on paid LLM calls. Registration is open and
# unverified, so a per-user cap bounds nothing on its own — N accounts buy N
# quotas. Raise deliberately; 0 disables the ceiling.
LLM_GLOBAL_DAILY_LIMIT = int(os.getenv("LLM_GLOBAL_DAILY_LIMIT", "500"))


class _SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            events = [t for t in self._events.get(key, []) if now - t < window_seconds]
            if len(events) >= limit:
                self._events[key] = events
                return False
            events.append(now)
            self._events[key] = events
            if len(self._events) > _LIMITER_MAX_KEYS:
                self._evict_expired(now, window_seconds)
            return True

    def _evict_expired(self, now: float, window_seconds: float) -> None:
        """Drop buckets with nothing left in the window (caller holds the lock).

        Without this the dict grows one entry per distinct key forever, which on a
        long-lived single-worker process is an unbounded memory leak driven by
        untrusted input (one bucket per client IP that ever hit an auth endpoint).
        """
        stale = [k for k, ts in self._events.items()
                 if not ts or now - ts[-1] >= window_seconds]
        for k in stale:
            self._events.pop(k, None)


# Guard-rail before eviction runs — high enough that normal traffic never pays
# for the sweep, low enough that the dict cannot grow without bound.
_LIMITER_MAX_KEYS = int(os.getenv("RATE_LIMIT_MAX_KEYS", "20000"))


_rate_limiter = _SlidingWindowLimiter()


# How many reverse proxies sit in front of this process. X-Forwarded-For is
# APPEND-only: each hop adds the address it saw, so the last entry is the one
# added by our own edge proxy and the leftmost entries are whatever the client
# chose to send. Trusting the leftmost entry — as this did — let any client
# supply "X-Forwarded-For: <random>" and get a brand-new rate-limit bucket on
# every request, which defeats login brute-force and mass-signup protection
# entirely. Railway terminates TLS and adds exactly one hop; set this to the real
# number of trusted proxies if the topology changes, or 0 to ignore the header.
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "1"))


def _client_ip(request: Request) -> str:
    """The client address, taken only from hops we actually trust.

    Counts ``TRUSTED_PROXY_HOPS`` entries in from the RIGHT of X-Forwarded-For.
    Anything further left is client-supplied and is never used. With no header (or
    a shorter one than the configured hop count) this falls back to the peer
    address, which cannot be spoofed.
    """
    peer = request.client.host if request.client else "unknown"
    if TRUSTED_PROXY_HOPS <= 0:
        return peer
    forwarded = request.headers.get("x-forwarded-for") or ""
    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    if len(chain) < TRUSTED_PROXY_HOPS:
        # Fewer hops than configured: the request did not traverse the expected
        # proxy chain, so no entry in it is trustworthy.
        return peer
    return chain[-TRUSTED_PROXY_HOPS]


def _enforce_auth_rate_limit(request: Request, scope: str) -> None:
    """Per-IP limit on credential endpoints — blocks brute force and mass signup."""
    if not _rate_limiter.allow(f"{scope}:{_client_ip(request)}", AUTH_RATE_LIMIT_PER_MINUTE, 60.0):
        raise HTTPException(status_code=429, detail="Too many attempts — try again in a minute")


def _enforce_llm_quota(user: identity.WebUser) -> None:
    """Per-user pacing + daily cap, and a deployment-wide daily ceiling.

    A per-user cap alone does not bound spend: registration is open and
    unverified, so N accounts buy N times the quota. The global bucket is the
    actual budget guard-rail — it turns "unbounded paid LLM spend" into a number
    someone chose (LLM_GLOBAL_DAILY_LIMIT), and it is enforced before the
    per-user checks so a burst of fresh accounts cannot walk past it.
    """
    if not _rate_limiter.allow("llm-day:__global__", LLM_GLOBAL_DAILY_LIMIT, 86400.0):
        http.logger.warning("global daily LLM cap (%d) reached — refusing paid analysis requests",
                       LLM_GLOBAL_DAILY_LIMIT)
        raise HTTPException(
            status_code=429,
            detail="The service reached its daily analysis capacity — please try again tomorrow",
        )
    if not _rate_limiter.allow(f"llm-min:{user.id}", LLM_RATE_LIMIT_PER_MINUTE, 60.0):
        raise HTTPException(status_code=429, detail="Too many analysis requests — try again in a minute")
    if not _rate_limiter.allow(f"llm-day:{user.id}", LLM_DAILY_LIMIT, 86400.0):
        raise HTTPException(status_code=429, detail="Daily analysis limit reached — try again tomorrow")
