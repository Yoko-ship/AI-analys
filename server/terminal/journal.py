"""The terminal's event journal: one append-only record of what users did and
what went wrong with the data (ТЗ «терминал каталога», section «Логирование»;
docs/catalog-terminal/04-logging-admin.md).

Before this, errors lived only in the process log, each loader kept its own
narrow table, and nothing told the PM what broke today. Every event now goes
through ``emit()``, which accepts only names from ``EVENTS``. That way the
admin screens, the alerts and the tests all speak the same fixed vocabulary.

Rules, in order:

* **Emitting never slows or breaks the caller.** ``emit`` appends to an
  in-memory buffer. A daemon thread writes it in one batched ``executemany``
  (row-at-a-time writes are the Postgres cost model). A full buffer is written
  inline instead of being dropped, and short-lived collector scripts flush at
  exit.
* **Append-only.** Database triggers refuse UPDATE and DELETE. The only delete
  is the retention purge, which opens the guard for its own transaction:
  data and error events are kept 12 months, user actions 90 days.
* **No personal data.** A user is an internal id or NULL (a guest). No name,
  email, token or IP address is stored.
* **Times are Tashkent time (UTC+5)**, the PM's day. The offset is the same on
  every row, so text order is time order.
"""
from __future__ import annotations

import atexit
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterable
import uuid

import dbx
from db import APP_DATA_DIR

logger = logging.getLogger(__name__)

TASHKENT = timezone(timedelta(hours=5))

INFO, WARNING, CRITICAL = "info", "warning", "critical"
LEVEL_LABELS = {INFO: "Инфо", WARNING: "Внимание", CRITICAL: "Критично"}

# Retention classes. ТЗ: «ошибки и события данных — 12 месяцев, действия
# пользователей — 90 дней».
USER, DATA = "user", "data"
RETENTION_DAYS = {USER: 90, DATA: 365}

# name -> (level, retention class, when it is written). The ТЗ table, plus
# api_error/api_slow (a failing or slow API request anywhere, so that 500s
# stop living only in the process log) and formula_changed (ТЗ «Шаблоны
# показателей», item 5).
EVENTS: dict[str, tuple[str, str, str]] = {
    "cmd_run": (INFO, USER, "a command was run or a function opened"),
    "cmd_unknown": (INFO, USER, "an unknown ticker or function code was entered"),
    "export": (INFO, USER, "a table was exported to Excel/CSV"),
    "ai_limit": (INFO, USER, "a user hit the AI-analysis limit"),
    "screen_error": (CRITICAL, DATA, "a terminal screen failed to build"),
    "screen_slow": (WARNING, DATA, "a terminal screen took longer than 3 s"),
    "api_error": (CRITICAL, DATA, "an API request failed with a server error"),
    "api_slow": (WARNING, DATA, "an API request took longer than 3 s"),
    "load_ok": (INFO, DATA, "a report was downloaded and parsed"),
    "load_empty": (CRITICAL, DATA, "a downloaded report file is empty"),
    "load_duplicate": (WARNING, DATA, "two reports for one period; which one was chosen"),
    "load_format_changed": (CRITICAL, DATA, "a source file no longer has the expected structure"),
    "value_quarantine": (CRITICAL, DATA, "a value failed the unit or jump check"),
    "year_backfill": (INFO, DATA, "a year was taken from the next report's prior-year column"),
    "restatement": (WARNING, DATA, "a company changed last year's figure by more than 1%"),
    "ai_published": (INFO, DATA, "an AI analysis was published"),
    "ai_blocked": (WARNING, DATA, "an AI analysis was blocked by a quality check"),
    "verdict_conflict": (CRITICAL, DATA, "risk is high but the verdict is not «Требует внимания»"),
    "ins_retention_jump": (WARNING, DATA, "insurer retention moved > 30 pp or cessions > 5x"),
    "ins_reserves_missing": (CRITICAL, DATA, "insurer annual reserves differ > 5% from the quarterly opening"),
    "pb_high": (WARNING, DATA, "P/B above 10: check the share count"),
    "formula_changed": (INFO, DATA, "a ratio formula or template was changed in ADM"),
}

FIELDS = ("id", "ts", "event", "level", "kind", "ticker", "standard", "period", "function",
          "user_id", "internal", "duration_ms", "error_id", "message", "source_url", "details")

_LIMITS = {"ticker": 16, "standard": 16, "period": 32, "function": 16, "error_id": 64,
           "message": 1000, "source_url": 1000}

_FLUSH_SECONDS = float(os.getenv("TERMINAL_JOURNAL_FLUSH_SECONDS", "2"))
_INLINE_FLUSH_AT = 500       # a buffer this full is written by the emitting caller
_MAX_RETAINED = 20000        # only when the database is unreachable: oldest rows go first
_PURGE_EVERY_SECONDS = 24 * 3600

_buffer: list[tuple] = []
_lock = threading.Lock()
_flusher: threading.Thread | None = None
_dropped = 0
_last_purge = 0.0


class UnknownEvent(ValueError):
    """A name outside ``EVENTS``. This is a programming error, so it is loud."""


def now() -> datetime:
    return datetime.now(TASHKENT)


def stamp(moment: datetime) -> str:
    return moment.astimezone(TASHKENT).isoformat(timespec="milliseconds")


def _clip(name: str, value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:_LIMITS[name]] if text else None


def emit(event: str, *, ticker: str | None = None, standard: str | None = None,
         period: str | None = None, function: str | None = None, user_id: int | None = None,
         internal: bool = False, duration_ms: int | float | None = None,
         error_id: str | None = None, message: str = "", source_url: str | None = None,
         details: dict[str, Any] | None = None, at: datetime | None = None,
         dedupe_key: str | None = None) -> None:
    """Record one event. Never raises for I/O; raises ``UnknownEvent`` for a bad name."""
    spec = EVENTS.get(event)
    if spec is None:
        raise UnknownEvent(event)
    level, kind, _ = spec
    row = (
        uuid.uuid5(uuid.NAMESPACE_URL, event+":"+dedupe_key).hex if dedupe_key is not None else uuid.uuid4().hex, stamp(at or now()), event, level, kind,
        (_clip("ticker", ticker) or "").upper() or None, _clip("standard", standard),
        _clip("period", period), _clip("function", function),
        int(user_id) if user_id is not None else None, 1 if internal else 0,
        int(round(duration_ms)) if duration_ms is not None else None,
        _clip("error_id", error_id), _clip("message", message) or "",
        _clip("source_url", source_url),
        json.dumps(details, ensure_ascii=False, default=str) if details else None,
    )
    with _lock:
        _buffer.append(row)
        inline = len(_buffer) >= _INLINE_FLUSH_AT
    if inline:
        flush()
    else:
        _ensure_flusher()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _path() -> str:
    path = Path(os.getenv("TERMINAL_JOURNAL_DB") or APP_DATA_DIR / "terminal_journal.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def schema(c) -> None:
    c.executescript("""
        CREATE TABLE IF NOT EXISTS terminal_events (
          id TEXT PRIMARY KEY, ts TEXT NOT NULL, event TEXT NOT NULL, level TEXT NOT NULL,
          kind TEXT NOT NULL, ticker TEXT, standard TEXT, period TEXT, function TEXT,
          user_id INTEGER, internal INTEGER NOT NULL DEFAULT 0, duration_ms INTEGER,
          error_id TEXT, message TEXT NOT NULL DEFAULT '', source_url TEXT, details TEXT);
        CREATE INDEX IF NOT EXISTS terminal_events_ts ON terminal_events(ts);
        CREATE INDEX IF NOT EXISTS terminal_events_level_ts ON terminal_events(level, ts);
        CREATE INDEX IF NOT EXISTS terminal_events_ticker_ts ON terminal_events(ticker, ts);
        CREATE INDEX IF NOT EXISTS terminal_events_event_ts ON terminal_events(event, ts);
        CREATE TABLE IF NOT EXISTS terminal_events_guard (id INTEGER PRIMARY KEY, purge INTEGER NOT NULL);
    """)
    # Same protection as control_audit (admin_control/store.py): the database
    # itself refuses to rewrite history, whatever the application does.
    if dbx.backend() == dbx.SQLITE:
        c.execute("INSERT INTO terminal_events_guard(id, purge) VALUES (1, 0) ON CONFLICT(id) DO NOTHING")
        c.execute("CREATE TRIGGER IF NOT EXISTS terminal_events_update BEFORE UPDATE ON terminal_events "
                  "BEGIN SELECT RAISE(ABORT, 'append-only journal'); END")
        c.execute("CREATE TRIGGER IF NOT EXISTS terminal_events_delete BEFORE DELETE ON terminal_events "
                  "WHEN COALESCE((SELECT purge FROM terminal_events_guard WHERE id=1), 0) <> 1 "
                  "BEGIN SELECT RAISE(ABORT, 'append-only journal'); END")
    else:
        c.execute("CREATE OR REPLACE FUNCTION terminal_events_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ "
                  "BEGIN IF TG_OP = 'DELETE' AND current_setting('app.journal_purge', true) = 'on' "
                  "THEN RETURN OLD; END IF; RAISE EXCEPTION 'append-only journal'; END; $$")
        c.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'terminal_events_immutable' "
            "AND NOT tgisinternal) THEN CREATE TRIGGER terminal_events_immutable BEFORE UPDATE OR DELETE "
            "ON terminal_events FOR EACH ROW EXECUTE FUNCTION terminal_events_immutable(); END IF; END $$"
        )
    c.commit()


@contextmanager
def connection():
    c = dbx.connect(_path())
    try:
        dbx.ensure_schema(c, "terminal-journal-v1", schema)
        yield c
    finally:
        c.close()


def flush() -> int:
    """Write everything buffered. Returns the number of rows written."""
    global _dropped
    with _lock:
        batch = list(_buffer)
        _buffer.clear()
    if not batch:
        return 0
    try:
        with connection() as c:
            c.executemany(f"INSERT INTO terminal_events({','.join(FIELDS)}) "
                          f"VALUES ({','.join('?' * len(FIELDS))}) ON CONFLICT(id) DO NOTHING", batch)
            c.commit()
        return len(batch)
    except Exception:
        logger.exception("terminal journal flush failed; %d events kept for retry", len(batch))
        with _lock:
            _buffer[:0] = batch
            excess = len(_buffer) - _MAX_RETAINED
            if excess > 0:
                del _buffer[:excess]
                _dropped += excess
                logger.error("terminal journal unreachable: %d oldest events dropped so far", _dropped)
        return 0


def _ensure_flusher() -> None:
    global _flusher
    with _lock:
        if _flusher is not None and _flusher.is_alive():
            return
        _flusher = threading.Thread(target=_flush_loop, name="terminal-journal-flush", daemon=True)
        _flusher.start()


def _flush_loop() -> None:
    global _last_purge
    while True:
        time.sleep(_FLUSH_SECONDS)
        flush()
        if time.monotonic() - _last_purge >= _PURGE_EVERY_SECONDS or not _last_purge:
            _last_purge = time.monotonic()
            try:
                purge()
            except Exception:
                logger.exception("terminal journal retention purge failed")


atexit.register(flush)


def purge(at: datetime | None = None) -> int:
    """Delete what retention allows, and nothing else. Returns rows deleted."""
    moment = at or now()
    deleted = 0
    with connection() as c:
        if c.target == dbx.POSTGRES:
            c.execute("SELECT set_config('app.journal_purge', 'on', true)")
        else:
            c.execute("UPDATE terminal_events_guard SET purge=1 WHERE id=1")
        try:
            for kind, days in RETENTION_DAYS.items():
                cur = c.execute("DELETE FROM terminal_events WHERE kind = ? AND ts < ?",
                                (kind, stamp(moment - timedelta(days=days))))
                deleted += max(cur.rowcount or 0, 0)
            if c.target != dbx.POSTGRES:
                c.execute("UPDATE terminal_events_guard SET purge=0 WHERE id=1")
            c.commit()
        except Exception:
            c.rollback()
            raise
    if deleted:
        logger.info("terminal journal retention purge: %d events", deleted)
    return deleted


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _row(row) -> dict[str, Any]:
    item = {name: row[name] for name in FIELDS}
    item["internal"] = bool(item["internal"])
    item["level_label"] = LEVEL_LABELS.get(item["level"], item["level"])
    item["details"] = json.loads(item["details"]) if item["details"] else None
    return item


def events(*, levels: Iterable[str] | None = None, event: str | None = None,
           ticker: str | None = None, function: str | None = None, since: str | None = None,
           until: str | None = None, limit: int = 100, offset: int = 0,
           standard: str | None = None, period: str | None = None) -> dict[str, Any]:
    """Newest first. ``since``/``until`` are ISO dates or timestamps (Tashkent)."""
    flush()
    where, params = [], []
    levels = [lv for lv in (levels or []) if lv in LEVEL_LABELS]
    if levels:
        where.append(f"level IN ({','.join('?' * len(levels))})")
        params += levels
    for column, value in (("event", event), ("function", function), ("standard", standard), ("period", period)):
        if value:
            where.append(f"{column} = ?")
            params.append(value)
    if ticker:
        where.append("ticker = ?")
        params.append(ticker.upper())
    if since:
        where.append("ts >= ?")
        params.append(since)
    if until:
        # A bare date means the whole of that day.
        where.append("ts < ?" if "T" in until else "ts <= ?")
        params.append(until if "T" in until else until + "T99")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    with connection() as c:
        total = c.execute(f"SELECT COUNT(*) AS n FROM terminal_events{clause}", params).fetchone()["n"]
        rows = c.execute(f"SELECT {','.join(FIELDS)} FROM terminal_events{clause} "
                         "ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
    return {"total": total, "limit": limit, "offset": offset, "items": [_row(r) for r in rows]}


def catalogue() -> list[dict[str, str]]:
    return [{"event": name, "level": level, "level_label": LEVEL_LABELS[level],
             "retention_days": RETENTION_DAYS[kind], "description": text}
            for name, (level, kind, text) in EVENTS.items()]
