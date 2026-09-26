"""Catalogue limits, freshness policy, and shared synchronization locks."""
from __future__ import annotations

from company_catalog import COMPANY_CATALOG
import logging
import os
import threading


logger = logging.getLogger(__name__)


CATALOG_SYNC_TTL_HOURS = int(os.getenv("CATALOG_SYNC_TTL_HOURS", "6"))


_SYNC_LOCK = threading.Lock()


_FIN_LOCK = threading.Lock()


FINANCIALS_TTL_DAYS = int(os.getenv("FINANCIALS_TTL_DAYS", "14"))


FINANCIALS_BATCH = int(os.getenv("FINANCIALS_BATCH", "12"))


FINANCIALS_ANNUAL_FRESH_DAYS = int(os.getenv("FINANCIALS_ANNUAL_FRESH_DAYS", "210"))


FINANCIALS_SYNC_BATCH = int(os.getenv("FINANCIALS_SYNC_BATCH", "8"))


_TICKER_TO_NAME: dict[str, str] = {}


for _name, _ticker in COMPANY_CATALOG.items():
    if _ticker not in _TICKER_TO_NAME:
        _TICKER_TO_NAME[_ticker] = _name
