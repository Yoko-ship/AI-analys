"""uzse.uz is off unless ``UZSE_ENABLED=1``.

uzse.uz has refused the server since 2026-09-24 (a 502 in 50 ms from its
gateway) after ~30 full crawls a day. The collectors kept asking anyway: the
trade feed, a quote page per security, the listings walk's share counts, the
bond registry — and every uzse session retries a 502 three times with backoff,
so each refused read was four requests to a host that had already said no.
openinfo's execution archive now carries the board (collectors/openinfo/
market_fallback.py), so nothing here needs uzse.uz to run.

One gate for every caller: ``install()`` wraps the transport adapter, so a
request to uzse.uz fails before a socket is opened, whichever module made it.
It raises a ``requests.ConnectionError`` subclass — the failure every caller
already handles as "uzse did not answer", which is exactly what it has been
answering for days — so no code path changes behaviour, it just stops sending.

Turn it back on (``UZSE_ENABLED=1``) only once UZSE has lifted the block, and
count the requests a schedule adds before adding one.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger(__name__)

HOSTS = ("uzse.uz",)


def enabled() -> bool:
    return os.getenv("UZSE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


class UzseDisabled(requests.ConnectionError):
    """uzse.uz is switched off (UZSE_ENABLED is not set)."""


def is_uzse(url: str) -> bool:
    host = (urlsplit(str(url)).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in HOSTS)


_original_send = HTTPAdapter.send
_warned = False


def _gated_send(self, request, *args, **kwargs):
    global _warned
    if not enabled() and is_uzse(request.url):
        if not _warned:
            log.warning("uzse.uz is switched off (UZSE_ENABLED=0); not requesting %s", request.url)
            _warned = True
        raise UzseDisabled(f"uzse.uz is switched off (UZSE_ENABLED=0): {request.url}", request=request)
    return _original_send(self, request, *args, **kwargs)


def install() -> None:
    """Idempotent: route every requests transport through the gate."""
    if HTTPAdapter.send is not _gated_send:
        HTTPAdapter.send = _gated_send


install()
