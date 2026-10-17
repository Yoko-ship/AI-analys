from __future__ import annotations

from fastapi import HTTPException
from fastapi import Request
import os
import server.http as http
import threading
import time
import web_auth as identity
import identity.users as identity_users


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
        # Each bucket's own window. Eviction must judge a bucket by it, not by the
        # window of whichever call happened to trigger the sweep: a 60 s login call
        # would otherwise drop every 24 h LLM bucket, the global spend cap included.
        self._windows: dict[str, float] = {}
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
            self._windows[key] = window_seconds
            if len(self._events) > _LIMITER_MAX_KEYS:
                self._evict_expired(now)
            return True

    def retry_after(self, key: str, window_seconds: float) -> int:
        """Whole seconds until the bucket admits its next request."""
        now = time.monotonic()
        with self._lock:
            events = [t for t in self._events.get(key, []) if now - t < window_seconds]
        if not events:
            return 1
        return max(1, int(window_seconds - (now - min(events)) + 0.999))

    def _evict_expired(self, now: float) -> None:
        """Drop buckets with nothing left in the window (caller holds the lock).

        Without this the dict grows one entry per distinct key forever, which on a
        long-lived single-worker process is an unbounded memory leak driven by
        untrusted input (one bucket per client IP that ever hit an auth endpoint).
        """
        stale = [k for k, ts in self._events.items()
                 if not ts or now - ts[-1] >= self._windows.get(k, 0.0)]
        for k in stale:
            self._events.pop(k, None)
            self._windows.pop(k, None)


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
# entirely. In production the provider's proxy terminates TLS and appends the
# visitor; the VPS's nginx resolves that with realip (scripts/nginx_edge.py), so
# whatever nginx then appends or forwards, the last entry is the visitor: one
# hop. Set this to the real number of trusted proxies if the topology changes,
# or 0 to ignore the header. This is the one place a client address is derived.
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


def _seconds_word(seconds: int) -> str:
    """«1 секунду», «2 секунды», «5 секунд», «21 секунду»."""
    if seconds % 10 == 1 and seconds % 100 != 11:
        return "секунду"
    if seconds % 10 in (2, 3, 4) and seconds % 100 not in (12, 13, 14):
        return "секунды"
    return "секунд"


# Every 429 the limiter raises is worded here, in the reader's language when the
# request says which it is, and always carries Retry-After so a client can word
# it itself. The English fallback is what clients that send no language get.
_LIMIT_MESSAGES = {
    "window": {
        "ru": lambda n: f"Превышен лимит запросов. Попробуйте через {n} {_seconds_word(n)}.",
        "uz": lambda n: f"So‘rovlar chegarasidan oshildi. {n} soniyadan so‘ng qayta urinib ko‘ring.",
        "en": lambda n: f"Request limit exceeded. Try again in {n} seconds.",
    },
    "daily": {
        "ru": lambda n: "Дневной лимит анализов исчерпан. Попробуйте завтра.",
        "uz": lambda n: "Kunlik tahlillar chegarasi tugadi. Ertaga qayta urinib ko‘ring.",
        "en": lambda n: "Daily analysis limit reached — try again tomorrow",
    },
    "capacity": {
        "ru": lambda n: "Сервис исчерпал дневной лимит анализов. Попробуйте завтра.",
        "uz": lambda n: "Xizmatning kunlik tahlil imkoniyati tugadi. Ertaga qayta urinib ko‘ring.",
        "en": lambda n: "The service reached its daily analysis capacity — please try again tomorrow",
    },
}


def request_language(request: Request | None) -> str | None:
    """The interface language a request states: X-UI-Language, then Accept-Language."""
    if request is None:
        return None
    explicit = str(request.headers.get("x-ui-language") or "").strip().lower()[:2]
    if explicit in ("ru", "uz", "en"):
        return explicit
    for part in str(request.headers.get("accept-language") or "").split(","):
        tag = part.split(";")[0].strip().lower()[:2]
        if tag in ("ru", "uz", "en"):
            return tag
    return None


def _rate_limited(kind: str, seconds: int, language: str | None) -> HTTPException:
    words = _LIMIT_MESSAGES[kind]
    return HTTPException(status_code=429, detail=words.get(language or "en", words["en"])(seconds),
                         headers={"Retry-After": str(seconds)})


def _enforce_auth_rate_limit(request: Request, scope: str) -> None:
    """Per-IP limit on credential endpoints — blocks brute force and mass signup."""
    key = f"{scope}:{_client_ip(request)}"
    if not _rate_limiter.allow(key, AUTH_RATE_LIMIT_PER_MINUTE, 60.0):
        raise _rate_limited("window", _rate_limiter.retry_after(key, 60.0), request_language(request))


def _enforce_llm_quota(user: identity_users.WebUser, language: str | None = None) -> None:
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
        _journal_ai_limit(user, "global")
        raise _rate_limited("capacity", _rate_limiter.retry_after("llm-day:__global__", 86400.0), language)
    if not _rate_limiter.allow(f"llm-min:{user.id}", LLM_RATE_LIMIT_PER_MINUTE, 60.0):
        _journal_ai_limit(user, "window")
        raise _rate_limited("window", _rate_limiter.retry_after(f"llm-min:{user.id}", 60.0), language)
    if not _rate_limiter.allow(f"llm-day:{user.id}", LLM_DAILY_LIMIT, 86400.0):
        _journal_ai_limit(user, "daily")
        raise _rate_limited("daily", _rate_limiter.retry_after(f"llm-day:{user.id}", 86400.0), language)


def _journal_ai_limit(user: identity_users.WebUser, kind: str) -> None:
    """ТЗ event ai_limit: the PM sees who runs into the AI quota, by internal id only."""
    try:
        from server.terminal import journal

        journal.emit("ai_limit", user_id=user.id, message=f"AI-analysis {kind} limit reached",
                     details={"limit": kind})
    except Exception:
        http.logger.debug("ai_limit journal write failed", exc_info=True)
