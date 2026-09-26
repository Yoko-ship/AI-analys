"""News settings operations with explicit dependencies."""
from __future__ import annotations

from pathlib import Path
import logging
import os


logger = logging.getLogger(__name__)


SOURCES_FILE = Path(__file__).resolve().parents[2] / "news_sources.json"


DEFAULT_PUSH_URL = os.getenv(
    "NEWS_PUSH_URL",
    os.getenv("FINANCIALS_PUSH_URL", "https://uzstock.uz"),
).rstrip("/")


DEFAULT_UA = "Mozilla/5.0 (compatible; UZSE-Analytics-NewsBot/1.0)"
