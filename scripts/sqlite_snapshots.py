#!/usr/bin/env python3
"""Consistent copies of every SQLite database under a data directory.

A live SQLite file copied byte by byte can be mid-transaction, so the off-site
backup never uploads one: it uploads these snapshots, taken with SQLite's own
backup API and checked with PRAGMA integrity_check. Every database is found by
its file header rather than a list of names, so one added later is covered
without anyone remembering to add it here.

    python sqlite_snapshots.py /app/data /app/data/offsite-staging/sqlite

Prints one line per database; exits 1 if any snapshot fails its check.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

SQLITE_HEADER = b"SQLite format 3\x00"
# Directories that already hold backups or are this script's own output.
SKIP_DIRS = {"financial_backups", "offsite-staging"}


def databases(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if name.endswith(("-wal", "-shm", "-journal")):
                continue
            try:
                with path.open("rb") as handle:
                    if handle.read(16) == SQLITE_HEADER:
                        yield path
            except OSError:
                continue


def snapshot(source: Path, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=60)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        # A copy in WAL mode would grow -wal/-shm files beside it whenever it is
        # opened; a backup should be one self-contained file.
        dst.execute("PRAGMA journal_mode=DELETE")
        return dst.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        dst.close()
        src.close()


def main(root: Path, out: Path) -> int:
    failed = 0
    for path in sorted(databases(root)):
        target = out / path.relative_to(root)
        try:
            verdict = snapshot(path, target)
        except sqlite3.Error as exc:
            verdict = f"error: {exc}"
        ok = verdict == "ok"
        failed += not ok
        print(f"{'ok ' if ok else 'BAD'} {path.relative_to(root)} ({target.stat().st_size if target.exists() else 0} bytes) {'' if ok else verdict}")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: sqlite_snapshots.py DATA_DIR OUT_DIR")
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
