"""Compact the admin-control SQLite database after its bounded revision purge.

This is deliberately an offline maintenance command: stop every writer before
running it.  It copies live resources, audit records and only retained revisions
to a new database, verifies the copy, then atomically replaces the source.
"""
from __future__ import annotations

import argparse
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
    args = parser.parse_args()
    if not args.confirm or args.keep < 1 or args.days < 1:
        parser.error("--confirm and positive --keep/--days are required")

    source_path = Path(args.database).resolve()
    target_path = source_path.with_suffix(source_path.suffix + ".compacting")
    if not source_path.is_file() or target_path.exists():
        raise RuntimeError("source database is missing or a previous compacting file remains")
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
        target.execute("ATTACH DATABASE ? AS source", (str(source_path),))
        for name, _ in tables:
            if name == "control_revisions":
                # The source primary key makes each object's ten newest
                # revisions inexpensive to select without materialising a
                # multi-gigabyte temporary sort.
                keys = target.execute(
                    "SELECT environment, collection, id FROM source.control_revisions "
                    "WHERE created_at >= ? GROUP BY environment, collection, id",
                    (cutoff,),
                ).fetchall()
                copied = 0
                for env, collection, entity_id in keys:
                    target.execute(
                        "INSERT INTO control_revisions "
                        "SELECT environment, collection, id, version, created_at, payload "
                        "FROM source.control_revisions WHERE environment=? AND collection=? AND id=? "
                        "AND created_at >= ? ORDER BY version DESC LIMIT ?",
                        (env, collection, entity_id, cutoff, args.keep),
                    )
                    copied += target.execute("SELECT changes()").fetchone()[0]
                print(f"retained_revisions={copied}")
            else:
                target.execute(f"INSERT INTO {quote(name)} SELECT * FROM source.{quote(name)}")
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
