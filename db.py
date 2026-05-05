import os
import sqlite3
from pathlib import Path


DATABASE_BACKEND = os.getenv("DATABASE_BACKEND", "sqlite").strip().lower()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
APP_DATA_DIR = Path(
    os.getenv("APP_DATA_DIR")
    or os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    or "data"
).expanduser()


def _resolve_path(raw_path: str, default_name: str) -> Path:
    value = (raw_path or "").strip() or default_name
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = APP_DATA_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_users_db_path() -> str:
    return str(_resolve_path(os.getenv("USERS_DB_PATH", ""), "users.db"))


def get_cache_db_path() -> str:
    return str(_resolve_path(os.getenv("CACHE_DB_PATH", ""), "analysis_cache.db"))


def get_org_cache_path() -> Path:
    return _resolve_path(os.getenv("ORG_CACHE_PATH", ""), "org_cache.json")


def get_output_path() -> str:
    return str(_resolve_path(os.getenv("OUTPUT_PATH", ""), "report.html"))


def sqlite_connect(db_path: str) -> sqlite3.Connection:
    if DATABASE_BACKEND != "sqlite":
        raise RuntimeError(
            f"DATABASE_BACKEND={DATABASE_BACKEND!r} пока не поддерживается. "
            "Сейчас проект подготовлен к миграции, но работает только с sqlite."
        )

    if DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL задан, но backend-слой для PostgreSQL ещё не подключён. "
            "Пока оставь DATABASE_URL пустым и используй sqlite."
        )

    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn
