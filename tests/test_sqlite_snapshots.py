"""Every SQLite database in the data volume is snapshotted for the off-site backup."""
from __future__ import annotations

import sqlite3

import scripts.sqlite_snapshots as snapshots


def _database(path, value: str, wal: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    if wal:
        db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE t (x)")
    db.execute("INSERT INTO t VALUES (?)", (value,))
    db.commit()
    return db


def test_every_database_is_found_by_its_header_not_its_name(tmp_path) -> None:
    data, out = tmp_path / "data", tmp_path / "out"
    _database(data / "admin_control.sqlite3", "a").close()
    _database(data / "nested" / "named-anything.bin", "b").close()
    (data / "notes.db").write_text("not a database")
    _database(data / "financial_backups" / "copy.db", "already a backup").close()
    assert snapshots.main(data, out) == 0
    found = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert found == ["admin_control.sqlite3", "nested/named-anything.bin"]


def test_a_live_wal_database_snapshots_with_its_committed_rows(tmp_path) -> None:
    data, out = tmp_path / "data", tmp_path / "out"
    live = _database(data / "sector_analysis.sqlite3", "committed", wal=True)
    live.execute("INSERT INTO t VALUES ('also committed')")
    live.commit()  # still in the -wal file, not yet checkpointed into the main file
    try:
        assert snapshots.main(data, out) == 0
    finally:
        live.close()
    rows = sqlite3.connect(out / "sector_analysis.sqlite3").execute("SELECT x FROM t ORDER BY rowid").fetchall()
    assert rows == [("committed",), ("also committed",)]
    assert not (out / "sector_analysis.sqlite3-wal").exists()
