import os
import sqlite3
import tempfile
from pathlib import Path


DATABASE_BACKEND = os.getenv("DATABASE_BACKEND", "sqlite").strip().lower()
# The data dir is anchored to THIS file, not the working directory — a process
# launched from any CWD must find the same databases. (A relative path used to
# silently create a fresh empty DB tree when started from elsewhere.)
_PREFERRED_DATA_DIR = Path(
    os.getenv("APP_DATA_DIR")
    or os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    or "data"
).expanduser()
if not _PREFERRED_DATA_DIR.is_absolute():
    _PREFERRED_DATA_DIR = Path(__file__).resolve().parent / _PREFERRED_DATA_DIR


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _pick_app_data_dir() -> Path:
    candidates = [_PREFERRED_DATA_DIR]
    candidates.append(Path(tempfile.gettempdir()) / "uz-stock-analyzer")

    for candidate in candidates:
        if _is_writable_dir(candidate):
            return candidate

    raise RuntimeError(
        "Не удалось найти доступную для записи папку для runtime-файлов."
    )


APP_DATA_DIR = _pick_app_data_dir()


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


def sqlite_connect(db_path: str):
    """A connection to whichever backend `DATABASE_BACKEND` names.

    This is the single chokepoint the whole application goes through, which is
    why the switch works at all: routing it through `dbx` makes every caller
    backend-agnostic without any of them knowing. The name is kept because
    seventy-odd call sites use it and renaming them would be churn for nothing —
    what it returns is a `dbx.Connection`, which behaves as `sqlite3` did:
    rows addressable by name and by index, `with conn:` commits, `close()`
    returns the connection to the pool.

    The PRAGMAs that used to be here now live in dbx's SQLite factory, where
    they belong — they are how you configure SQLite, not how you configure a
    database.
    """
    import dbx

    if dbx.backend() == dbx.SQLITE:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return dbx.connect(db_path)
