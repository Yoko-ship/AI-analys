"""geoip.py — country / region / city for a visitor's IP, looked up offline.

uzstock.uz is served straight from the VPS, so no proxy (Cloudflare and the
like) hands the API a country header: before this module the audience's
geography was all «(unknown)». The lookup now runs against DB-IP's free
"IP to City Lite" database (CC BY 4.0 — the admin panel carries the
attribution), a ~125 MB MaxMind-format file kept in the data volume:

* **Never on the request path's critical section.** ``lookup`` is a memory
  read; when the file is missing or unreadable it answers ``None`` and the
  visit is stored without a place, exactly as before.
* **The IP is still never stored.** Only the resolved place names are kept;
  the address itself is hashed by ``web_analytics`` as it always was.
* **The file refreshes itself.** DB-IP publishes a new month on the 1st; a
  background thread downloads it when the local copy is missing or older than
  ``_MAX_AGE_DAYS``. Several API workers share one data volume, so a lock file
  keeps them from downloading the same 60 MB at once.
"""
from __future__ import annotations

import gzip
import ipaddress
import logging
import os
import shutil
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(os.getenv("APP_DATA_DIR", "data"))
DB_PATH = Path(os.getenv("GEOIP_DB_PATH", "") or (_DATA_DIR / "geoip" / "dbip-city-lite.mmdb"))
_URL = "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"
_MAX_AGE_DAYS = 35
_LOCK_STALE_SECONDS = 3600
_RECHECK_SECONDS = 600  # how often a worker notices a refreshed file
_DISABLED = os.getenv("GEOIP_DISABLED", "").strip().lower() in {"1", "true", "yes"}

_reader: Any = None
_reader_mtime: float | None = None
_checked_at = 0.0
_reader_lock = threading.Lock()
_refresher_started = False


def _open_reader(path: Path):
    import maxminddb

    return maxminddb.open_database(str(path))


def _current_reader():
    """The open database, reopened when the file on disk has been replaced."""
    global _reader, _reader_mtime, _checked_at
    now = time.monotonic()
    if _reader is not None and now - _checked_at < _RECHECK_SECONDS:
        return _reader
    with _reader_lock:
        _checked_at = now
        try:
            mtime = DB_PATH.stat().st_mtime
        except OSError:
            return _reader
        if _reader is None or mtime != _reader_mtime:
            try:
                fresh = _open_reader(DB_PATH)
            except Exception:
                logger.warning("geoip: cannot open %s", DB_PATH, exc_info=True)
                return _reader
            old, _reader, _reader_mtime = _reader, fresh, mtime
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
    return _reader


def _public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return False
    return addr.is_global


def _name(node: Any) -> Optional[str]:
    if not isinstance(node, dict):
        return None
    names = node.get("names") or {}
    value = names.get("en") or next(iter(names.values()), None) if isinstance(names, dict) else None
    value = str(value or "").strip()
    return value[:80] or None


def lookup(ip: str) -> Optional[dict[str, Optional[str]]]:
    """{country, region, city} for a public IP, or None when it cannot be placed."""
    if _DISABLED or not _public_ip(ip):
        return None
    reader = _current_reader()
    if reader is None:
        return None
    try:
        record = reader.get(ip.strip())
    except Exception:
        return None
    if not isinstance(record, dict):
        return None
    country = str((record.get("country") or {}).get("iso_code") or "").strip().upper()[:2] or None
    subdivisions = record.get("subdivisions") or []
    region = _name(subdivisions[0]) if subdivisions else None
    city = _name(record.get("city"))
    if not (country or region or city):
        return None
    return {"country": country, "region": region, "city": city}


# ---------------------------------------------------------------------------
# Keeping the file current
# ---------------------------------------------------------------------------

def _months_to_try(today: date) -> list[str]:
    """This month first; on the 1st DB-IP may not have published it yet."""
    previous = date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)
    return [today.strftime("%Y-%m"), previous.strftime("%Y-%m")]


def _download(url: str, target: Path) -> None:
    import requests

    tmp_gz = target.with_name(f"{target.name}.{os.getpid()}.gz.part")
    tmp = target.with_name(f"{target.name}.{os.getpid()}.part")
    try:
        with requests.get(url, stream=True, timeout=(10, 120)) as response:
            response.raise_for_status()
            with open(tmp_gz, "wb") as out:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    out.write(chunk)
        with gzip.open(tmp_gz, "rb") as src, open(tmp, "wb") as out:
            shutil.copyfileobj(src, out, length=1 << 20)
        _open_reader(tmp).close()  # never install a file that cannot be read
        os.replace(tmp, target)
    finally:
        for leftover in (tmp_gz, tmp):
            try:
                leftover.unlink()
            except OSError:
                pass


def needs_refresh(path: Path = DB_PATH, now: float | None = None) -> bool:
    try:
        age = (now or time.time()) - path.stat().st_mtime
    except OSError:
        return True
    return age > _MAX_AGE_DAYS * 86400


def ensure_database(path: Path = DB_PATH, today: date | None = None,
                    download: Callable[[str, Path], None] = _download) -> bool:
    """Download the current month when the local copy is missing or old.

    Returns True when a usable file is in place afterwards. Safe to call from
    several processes: only the one holding the lock downloads.
    """
    if _DISABLED:
        return False
    if not needs_refresh(path):
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    try:
        if time.time() - lock.stat().st_mtime > _LOCK_STALE_SECONDS:
            lock.unlink()
    except OSError:
        pass
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return path.exists()
    try:
        os.close(fd)
        for month in _months_to_try(today or date.today()):
            try:
                download(_URL.format(month=month), path)
                logger.info("geoip: installed DB-IP city lite %s", month)
                return True
            except Exception as exc:
                logger.warning("geoip: download for %s failed: %s", month, exc)
        return path.exists()
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _refresh_loop() -> None:
    while True:
        try:
            ensure_database()
        except Exception:
            logger.exception("geoip refresh failed")
        time.sleep(86400)


def start_background_refresh() -> None:
    """Fetch the database in the background so the API boots without waiting."""
    global _refresher_started
    # GEOIP_REFRESH=0 keeps tests and one-off scripts from fetching 60 MB.
    if _DISABLED or _refresher_started or os.getenv("GEOIP_REFRESH", "1").strip() == "0":
        return
    _refresher_started = True
    threading.Thread(target=_refresh_loop, name="geoip-refresh", daemon=True).start()
