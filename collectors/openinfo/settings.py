"""Openinfo settings operations with explicit dependencies."""
from __future__ import annotations

from db import APP_DATA_DIR as _APP_DATA_DIR
from pathlib import Path
import logging
import os


logger = logging.getLogger(__name__)


OPENINFO_API_BASE = "https://new-api.openinfo.uz/api/v2"


OPENINFO_WEB_BASE = "https://openinfo.uz"


REQUEST_TIMEOUT = int(os.getenv("OPENINFO_TIMEOUT", "30"))


EXCEL_PARSE_ENABLED = os.getenv("OPENINFO_EXCEL_PARSE_ENABLED", "1").strip().lower() not in {"0", "false", "no"}


EXCEL_MAX_BYTES = int(os.getenv("OPENINFO_EXCEL_MAX_BYTES", "3000000"))


EXCEL_MAX_REPORTS = int(os.getenv("OPENINFO_EXCEL_MAX_REPORTS", "3"))


EXCEL_MAX_ANNUAL_REPORTS = int(os.getenv("OPENINFO_EXCEL_MAX_ANNUAL_REPORTS", "1"))


EXCEL_MAX_QUARTER_REPORTS = int(os.getenv("OPENINFO_EXCEL_MAX_QUARTER_REPORTS", "2"))


EXCEL_ABSOLUTE_MAX_REPORTS = int(os.getenv("OPENINFO_EXCEL_ABSOLUTE_MAX_REPORTS", "100"))


EXCEL_MAX_TABLE_ROWS_PER_SHEET = int(os.getenv("OPENINFO_EXCEL_MAX_TABLE_ROWS_PER_SHEET", "240"))


EXCEL_CACHE_TTL_SECONDS = int(os.getenv("OPENINFO_EXCEL_CACHE_TTL_DAYS", "30")) * 24 * 60 * 60


EXCEL_CACHE_PATH = Path(
    os.getenv("OPENINFO_EXCEL_CACHE_PATH") or (_APP_DATA_DIR / "openinfo_excel_cache.json")
).expanduser()


EXCEL_PARSER_VERSION = "openinfo-excel-source-cells-v4"
