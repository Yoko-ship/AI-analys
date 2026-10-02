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
  that are blocked;
- a circuit breaker: once openinfo answers 403/429 OPENINFO_BLOCK_STREAK times
  in a row (default 3), every process stops asking for OPENINFO_COOLDOWN_MIN
  minutes (default 60) — ``OpeninfoPaused``, a ConnectionError, which callers
  already treat as "openinfo did not answer". uzse.uz blocked this server after
  ~30 crawls a day, and our collectors went on asking it — four requests per
  refused read, with retries — for days. The pause is recorded in the data
  directory, so the web app and every collector honour one decision;
- a daily request count per host in the data directory
  (openinfo-requests-YYYY-MM-DD.json), logged at exit, so the volume we send is
  a number we can read instead of a guess — split by job and by endpoint, and
  counting urllib3's retries, each of which reached openinfo too.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import re
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

VERIFY_SSL = os.getenv("OPENINFO_VERIFY_SSL", "1").strip().lower() not in {"0", "false", "no"}
OPENINFO_PROXY = (os.getenv("OPENINFO_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or "").strip()
MIN_INTERVAL_SECONDS = max(0.0, int(os.getenv("OPENINFO_MIN_INTERVAL_MS", "350")) / 1000.0)
RETRIES = int(os.getenv("OPENINFO_RETRIES", "3"))
TIMEOUT = int(os.getenv("OPENINFO_TIMEOUT", "30"))
BLOCK_STREAK = max(1, int(os.getenv("OPENINFO_BLOCK_STREAK", "3")))
COOLDOWN_SECONDS = max(60, int(os.getenv("OPENINFO_COOLDOWN_MIN", "60")) * 60)
BLOCK_STATUSES = (403, 429)

log = logging.getLogger(__name__)

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


class OpeninfoPaused(requests.ConnectionError):
    """openinfo refused us repeatedly; requests are paused until the cooldown ends."""


def _state_dir() -> Path:
    try:
        from db import APP_DATA_DIR
        return Path(APP_DATA_DIR)
    except Exception:  # noqa: BLE001 — a bare script still gets a breaker in memory
        return Path(os.getenv("APP_DATA_DIR") or Path(__file__).with_name("data"))


_PAUSE_FILE = "openinfo-paused-until"
_STATE_LOCK = threading.Lock()
_block_streak = 0
_paused_until = 0.0          # epoch seconds; mirrors the shared file
_run_count = 0
_unflushed: Counter = Counter()  # endpoint -> requests not yet in the shared count
# Which job sent them: the script and its flags (`collector_financials.py
# --trades-only`), so the daily count says where its requests came from.
_JOB = " ".join([Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "python"]
                + [a for a in sys.argv[1:] if a.startswith("--")])
_ID_SEGMENT = re.compile(r"^(\d+|[0-9a-f-]{32,36})$", re.I)


def _endpoint(url: str) -> str:
    """The request's path with ids and file names folded: /org/{id}/reports/, /media/{file}."""
    parts = urlsplit(url)
    path = re.sub(r"^/api/v\d+", "", parts.path)
    path = "/".join("{id}" if _ID_SEGMENT.match(seg) else "{file}" if "." in seg else seg
                    for seg in path.split("/"))
    return path if parts.hostname == "new-api.openinfo.uz" else f"{parts.hostname}{path}"


def paused_until() -> float:
    """The shared pause, if any process has tripped it (epoch seconds, 0 = none)."""
    global _paused_until
    try:
        _paused_until = max(_paused_until, float((_state_dir() / _PAUSE_FILE).read_text().strip() or 0))
    except (OSError, ValueError):
        pass
    return _paused_until if _paused_until > time.time() else 0.0


def _trip(status: int, url: str) -> None:
    global _paused_until
    _paused_until = time.time() + COOLDOWN_SECONDS
    try:
        path = _state_dir() / _PAUSE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(_paused_until))
    except OSError:
        pass
    log.error("openinfo answered %s %d times in a row (last: %s) — pausing every openinfo "
              "request for %d min", status, BLOCK_STREAK, url, COOLDOWN_SECONDS // 60)


def _record(status: int | None, url: str, tries: int = 1) -> None:
    """Count one call — ``tries`` requests, with urllib3's retries — and move the breaker."""
    global _block_streak, _run_count
    with _STATE_LOCK:
        _run_count += tries
        _unflushed[_endpoint(url)] += tries
        if status in BLOCK_STATUSES:
            _block_streak += 1
            if _block_streak >= BLOCK_STREAK:
                _block_streak = 0
                _trip(status, url)
        elif status is not None:
            _block_streak = 0
        flush = sum(_unflushed.values()) >= 50
    if flush:
        _flush_count()


def _flush_count() -> None:
    """Add this process's unflushed requests to today's shared count (UTC day)."""
    with _STATE_LOCK:
        counts = Counter(_unflushed)
        _unflushed.clear()
    n = sum(counts.values())
    if not n:
        return
    path = _state_dir() / f"openinfo-requests-{datetime.now(timezone.utc):%Y-%m-%d}.json"
    try:
        import fcntl
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            try:
                data = json.loads(fh.read() or "{}")
            except ValueError:
                data = {}
            data["requests"] = int(data.get("requests") or 0) + n
            jobs = data.setdefault("by_job", {})
            jobs[_JOB] = int(jobs.get(_JOB) or 0) + n
            endpoints = data.setdefault("by_endpoint", {})
            for endpoint, k in counts.items():
                endpoints[endpoint] = int(endpoints.get(endpoint) or 0) + k
            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps(data))
    except Exception:  # noqa: BLE001 — counting must never cost a request
        pass


@atexit.register
def _report_run() -> None:
    _flush_count()
    if _run_count:
        log.info("openinfo: %d requests from this process", _run_count)


class PacedSession(requests.Session):
    def request(self, method, url, **kwargs):  # type: ignore[override]
        if not (urlsplit(str(url)).hostname or "").endswith("openinfo.uz"):
            # Some collectors send uzse.uz through this session. Those are not
            # openinfo's requests to pace, pause or count: a gated uzse call
            # (UZSE_ENABLED=0) opens no socket and counted four times as a
            # failed openinfo request.
            kwargs.setdefault("timeout", TIMEOUT)
            return super().request(method, url, **kwargs)
        until = paused_until()
        if until:
            raise OpeninfoPaused(
                f"openinfo requests are paused until "
                f"{datetime.fromtimestamp(until, timezone.utc):%Y-%m-%d %H:%M} UTC after repeated 403/429")
        _pace()
        kwargs.setdefault("timeout", TIMEOUT)
        try:
            response = super().request(method, url, **kwargs)
        except requests.exceptions.RetryError as exc:
            # urllib3 gave up retrying a 429/5xx: still an answer, and a 429 counts.
            _record(429 if "429" in str(exc) else None, url, tries=RETRIES + 1)
            raise
        except requests.exceptions.RequestException:
            # Timeouts and refused connections, after urllib3's own retries: they
            # reached openinfo too (an upper bound — the retry budget is spent).
            _record(None, url, tries=RETRIES + 1)
            raise
        # A 5xx or a timeout urllib3 retried and then got past is several requests.
        history = getattr(getattr(response.raw, "retries", None), "history", None) or ()
        _record(response.status_code, url, tries=1 + len(history))
        return response


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
