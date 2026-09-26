"""Open catalogue connections; database location is configurable for isolated runs."""
from __future__ import annotations

from db import APP_DATA_DIR
from db import sqlite_connect
from pathlib import Path
import catalogue.schema as catalogue_schema
import dbx
import os
import sqlite3


def _catalog_db_path() -> str:
    """Where the catalogue lives — ``CATALOG_DB_PATH`` overrides the data dir.

    The override is not a convenience. Four tests in test_balance_block set
    CATALOG_DB_PATH to a tmp_path and, because nothing read it, wrote their
    fixtures into the real catalogue instead: a synthetic «KSCM 2025Q4, revenue
    900» and two rows under the tickers "X" and "Y" were sitting in
    data/reports_catalog.db on 2026-08-17. That store is what the collector's
    backfills read and push to production, so a test fixture was one sweep away
    from being served as a filing.
    """
    override = os.getenv("CATALOG_DB_PATH")
    path = Path(override) if override else (APP_DATA_DIR / "reports_catalog.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_catalog_conn() -> sqlite3.Connection:
    conn = sqlite_connect(_catalog_db_path())
    dbx.ensure_schema(conn, "catalog", catalogue_schema._init_schema)
    return conn
