"""Shared HTTP layer for all openinfo.uz traffic.

Every fetcher (collector, resolvers, probe) builds its session here so openinfo
traffic behaves the same from any host — a local PC, the Railway deployment, or
a proxy relay:

- polite pacing: a global minimum interval between requests
  (OPENINFO_MIN_INTERVAL_MS, default 350) so bulk syncs never hammer the source
  and get the host IP blocked — this is what makes ingestion sustainable
  directly from a datacenter IP;
- resilience: automatic retries with exponential backoff on 429/5xx and
  connection errors (OPENINFO_RETRIES, default 3), honoring Retry-After;
- TLS verification ON by default (certificates are valid; set
  OPENINFO_VERIFY_SSL=0 only as a temporary escape hatch);
- OPENINFO_PROXY (or HTTPS_PROXY/HTTP_PROXY) as an optional relay for hosts
  that are blocked.
"""
from __future__ import annotations

import os
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

VERIFY_SSL = os.getenv("OPENINFO_VERIFY_SSL", "1").strip().lower() not in {"0", "false", "no"}
OPENINFO_PROXY = (os.getenv("OPENINFO_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or "").strip()
MIN_INTERVAL_SECONDS = max(0.0, int(os.getenv("OPENINFO_MIN_INTERVAL_MS", "350")) / 1000.0)
RETRIES = int(os.getenv("OPENINFO_RETRIES", "3"))
TIMEOUT = int(os.getenv("OPENINFO_TIMEOUT", "30"))

if not VERIFY_SSL:
    try:
        from urllib3.exceptions import InsecureRequestWarning
        requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)
    except Exception:  # pragma: no cover
        pass

_PACE_LOCK = threading.Lock()
_next_slot = 0.0


def _pace() -> None:
    """Global rate gate: at most one outgoing request per MIN_INTERVAL, across threads."""
    global _next_slot
    if MIN_INTERVAL_SECONDS <= 0:
        return
    with _PACE_LOCK:
        now = time.monotonic()
        wait = _next_slot - now
        _next_slot = max(now, _next_slot) + MIN_INTERVAL_SECONDS
    if wait > 0:
        time.sleep(wait)


class PacedSession(requests.Session):
    def request(self, method, url, **kwargs):  # type: ignore[override]
        _pace()
        kwargs.setdefault("timeout", TIMEOUT)
        return super().request(method, url, **kwargs)


def make_session() -> requests.Session:
    session = PacedSession()
    retry = Retry(
        total=RETRIES,
        connect=RETRIES,
        read=max(1, RETRIES - 1),
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    session.verify = VERIFY_SSL
    if OPENINFO_PROXY:
        session.proxies.update({"http": OPENINFO_PROXY, "https": OPENINFO_PROXY})
    return session


_shared: requests.Session | None = None
_SHARED_LOCK = threading.Lock()


def shared_session() -> requests.Session:
    global _shared
    with _SHARED_LOCK:
        if _shared is None:
            _shared = make_session()
        return _shared


def get(url: str, params: dict | None = None, timeout: int | None = None, **kwargs) -> requests.Response:
    """Paced, retrying GET on the shared session — drop-in for raw requests.get."""
    return shared_session().get(url, params=params, timeout=timeout or TIMEOUT, **kwargs)
