"""logo_store.py — logos live here, not on somebody else's CDN.

ТЗ Дополнение 1 §Б.7: "логотипы скачиваются один раз в своё хранилище: внешний
сервис фавиконок из интерфейса убирается".

Thirty-three of the sixty-one logos are Google favicon URLs, fetched by the
browser on every render of every page that shows a company. Three things wrong
with that, in increasing order of seriousness: it is a request per logo per
visitor for a file that never changes; it tells a third party which securities
each of our readers is looking at; and it makes the interface depend on a
service nobody here controls, so the day it rate-limits us the badges vanish
and no deploy of ours will bring them back.

Downloading them once is the whole fix. The mapping then points at our own
``/logos`` mount, which is already served with a long cache header.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

LOGO_DIR = Path(__file__).with_name("logos")
MAPPING = Path(__file__).with_name("company_logos.json")

_EXTENSIONS = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg",
    "image/webp": ".webp", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico",
}
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def _load() -> dict[str, str]:
    try:
        return json.loads(MAPPING.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.exception("logo mapping unreadable")
        return {}


def _save(mapping: dict[str, str]) -> None:
    MAPPING.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")


def is_external(url: Any) -> bool:
    return str(url or "").startswith(("http://", "https://"))


def local_path(ticker: str) -> str | None:
    """The stored file for a ticker, if we already have one."""
    for path in sorted(LOGO_DIR.glob(f"{ticker.upper()}.*")):
        if path.is_file() and path.stat().st_size > 0:
            return f"/logos/{path.name}"
    return None


def materialise(ticker: str, url: str, session: requests.Session | None = None,
                timeout: int = 15) -> str | None:
    """Download one logo into our own storage and return its local path.

    Returns None on any failure — the caller keeps the external URL, because a
    missing badge is worse than a slow one. Nothing here deletes anything.
    """
    ticker = ticker.upper().strip()
    if not ticker or not is_external(url):
        return None
    existing = local_path(ticker)
    if existing:
        return existing
    client = session or requests.Session()
    try:
        response = client.get(url, headers={"User-Agent": _UA}, timeout=timeout)
        response.raise_for_status()
    except Exception:  # noqa: BLE001 — one unreachable logo is not a failure
        logger.warning("logo fetch failed for %s: %s", ticker, url)
        return None
    body = response.content
    if not body or len(body) < 64:
        # Favicon services answer 200 with a placeholder rather than 404; a file
        # this small is that placeholder, and storing it would freeze a blank.
        logger.warning("logo for %s looks like a placeholder (%d bytes)", ticker, len(body))
        return None
    content_type = str(response.headers.get("content-type", "")).split(";")[0].strip().lower()
    suffix = _EXTENSIONS.get(content_type)
    if suffix is None:
        match = re.search(r"\.(png|jpe?g|svg|webp|ico)(?:$|\?)", url, re.I)
        suffix = f".{match.group(1).lower()}" if match else ".png"
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    target = LOGO_DIR / f"{ticker}{suffix}"
    target.write_bytes(body)
    return f"/logos/{target.name}"


def materialise_all(limit: int | None = None) -> dict[str, Any]:
    """Pull every externally hosted logo into ``logos/`` and rewrite the mapping."""
    mapping = _load()
    external = [(t, u) for t, u in mapping.items() if is_external(u)]
    session = requests.Session()
    stored: list[str] = []
    failed: list[str] = []
    for ticker, url in (external[:limit] if limit else external):
        path = materialise(ticker, url, session)
        if path:
            mapping[ticker] = path
            stored.append(ticker)
        else:
            failed.append(ticker)
    if stored:
        _save(mapping)
    remaining = sum(1 for u in mapping.values() if is_external(u))
    return {"external_before": len(external), "stored": len(stored),
            "failed": len(failed), "failed_tickers": failed[:20],
            "external_remaining": remaining}


def audit() -> dict[str, Any]:
    """How much of the interface still depends on someone else's service."""
    mapping = _load()
    external = sorted(t for t, u in mapping.items() if is_external(u))
    return {"total": len(mapping), "local": len(mapping) - len(external),
            "external": len(external), "external_tickers": external}
