"""Compact the admin-control SQLite database after its bounded revision purge.

This is deliberately an offline maintenance command: stop every writer before
running it.  It copies live resources, audit records and only retained revisions
to a new database, verifies the copy, then atomically replaces the source.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import sys


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=os.getenv("ADMIN_CONTROL_DB", "/app/data/admin_control.sqlite3"))
    parser.add_argument("--keep", type=int, default=int(os.getenv("ADMIN_REVISION_KEEP", "10")))
    parser.add_argument("--days", type=int, default=int(os.getenv("ADMIN_REVISION_KEEP_DAYS", "90")))
    parser.add_argument("--confirm", action="store_true", help="required acknowledgement for the atomic replacement")
    parser.add_argument("--discard-stale-target", action="store_true",
                        help="remove only an abandoned .compacting file from an earlier failed run")
    args = parser.parse_args()
    if not args.confirm or args.keep < 1 or args.days < 1:
        parser.error("--confirm and positive --keep/--days are required")

    source_path = Path(args.database).resolve()
    target_path = source_path.with_suffix(source_path.suffix + ".compacting")
    if not source_path.is_file():
        raise RuntimeError("source database is missing")
    if target_path.exists():
        if not args.discard_stale_target or not target_path.is_file():
            raise RuntimeError("a previous compacting file remains; inspect it or pass --discard-stale-target")
        target_path.unlink()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    source_uri = f"{source_path.as_uri()}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    target = sqlite3.connect(target_path)
    try:
        source.execute("PRAGMA query_only=ON")
        target.execute("PRAGMA journal_mode=DELETE")
        target.execute("PRAGMA synchronous=FULL")
        tables = source.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        objects = source.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE type IN ('index','trigger') "
            "AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY type, name"
        ).fetchall()
        if "control_revisions" not in {name for name, _ in tables}:
            raise RuntimeError("not an admin-control database: control_revisions is absent")
        for _, sql in tables:
            target.execute(sql)
        # The destination connection was opened by filename, so attach the
        # source by filename too; its separate inspection connection remains
        # read-only and the command never writes to the attached schema.
        for name, _ in tables:
            if name == "control_revisions":
                # Read the source's primary-key order once.  The previous
                # implementation performed one query per object (millions in
                # production), which turned an offline safety operation into
                # a multi-hour outage. This needs no temporary sort or second
                # copy of the database: rows for an object are consecutive in
                # the primary-key order, and a fixed ten-row deque retains its
                # newest values as that group passes.
                copied = 0
                scanned = 0
                current_key: tuple[str, str, str] | None = None
                batch: list[tuple] = []
                retained: deque[tuple] = deque(maxlen=args.keep)

                def flush_batch() -> None:
                    nonlocal copied
                    if batch:
                        target.executemany("INSERT INTO control_revisions VALUES (?,?,?,?,?,?)", batch)
                        copied += len(batch)
                        batch.clear()

                rows = source.execute(
                    "SELECT environment, collection, id, version, created_at, payload "
                    "FROM control_revisions ORDER BY environment, collection, id, version"
                )
                for row in rows:
                    scanned += 1
                    key = (row[0], row[1], row[2])
                    if key != current_key:
                        batch.extend(retained)
                        retained.clear()
                        current_key = key
                    if row[4] >= cutoff:
                        retained.append(row)
                    if len(batch) >= 1000:
                        flush_batch()
                    if scanned % 1_000_000 == 0:
                        print(f"scanned_revisions={scanned} retained_revisions={copied + len(batch) + len(retained)}", flush=True)
                batch.extend(retained)
                flush_batch()
                print(f"retained_revisions={copied}")
            else:
                # ``source`` is an explicit read-only connection, so no writer
                # can ever accidentally change the live database during copy.
                columns = ", ".join(quote(row[1]) for row in source.execute(f"PRAGMA table_info({quote(name)})"))
                target.executemany(
                    f"INSERT INTO {quote(name)} ({columns}) VALUES ({','.join('?' for _ in columns.split(', '))})",
                    source.execute(f"SELECT {columns} FROM {quote(name)}"),
                )
        for _, name, sql in objects:
            # The deployed v2 schema replaces this legacy trigger at startup.
            if name != "control_revisions_delete":
                target.execute(sql)
        target.commit()
        check = target.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"compacted database failed integrity check: {check}")
        for table in ("control_resources", "control_audit", "control_commands"):
            before = source.execute(f"SELECT COUNT(*) FROM {quote(table)}").fetchone()[0]
            after = target.execute(f"SELECT COUNT(*) FROM {quote(table)}").fetchone()[0]
            if before != after:
                raise RuntimeError(f"row-count mismatch for {table}: {before} != {after}")
        target.close()
        source.close()
        backup_path = source_path.with_suffix(source_path.suffix + ".precompact")
        if backup_path.exists():
            raise RuntimeError("refusing to overwrite an existing precompact backup")
        os.replace(source_path, backup_path)
        os.replace(target_path, source_path)
        # The compacted file is now the live database.  The source was retained
        # until validation completed; remove it only after the atomic swap.
        backup_path.unlink()
        print(f"compacted_database={source_path}")
        return 0
    except Exception:
        target.close()
        source.close()
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"admin-control compaction failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
