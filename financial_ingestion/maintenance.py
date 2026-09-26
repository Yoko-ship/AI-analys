"""Verified local backups and durable operational incidents. No external sends."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from uuid import uuid4

from . import documents, store


def backup_root():
    from db import APP_DATA_DIR
    root = Path(os.environ.get("FINANCIAL_BACKUP_DIR") or APP_DATA_DIR / "financial_backups")
    root.mkdir(parents=True, exist_ok=True)
    return root


def backup():
    """Online SQLite snapshot + independently copied, shared immutable originals.

    Copy the database first, then exactly the artifact hashes referenced by that
    snapshot. New concurrent ingestion cannot create dangling backup references.
    Local copies protect recovery from logical errors, not loss of the VPS.
    """
    import dbx
    from catalogue.storage import _catalog_db_path
    if dbx.backend() != dbx.SQLITE:
        raise ValueError("Use a PostgreSQL-native backup for this backend")
    store.connect().close()
    root = backup_root()
    scratch = Path(tempfile.mkdtemp(prefix=".pending-", dir=root))
    source = sqlite3.connect(_catalog_db_path())
    target = sqlite3.connect(scratch / "catalog.db")
    try:
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup database failed integrity check")
        artifacts = target.execute("SELECT sha,byte_count FROM ingest_artifacts ORDER BY sha").fetchall()
    finally:
        source.close()
        target.close()
    objects = root / "objects"
    objects.mkdir(exist_ok=True)
    missing_bytes = sum(size for sha, size in artifacts if not (objects / (sha + ".pdf")).exists())
    if shutil.disk_usage(root).free < missing_bytes + 512 * 1024 * 1024:
        raise ValueError("Insufficient free space for verified financial backup")
    for sha, size in artifacts:
        destination = objects / (sha + ".pdf")
        if not destination.exists():
            payload = documents.read_artifact(sha)
            if len(payload) != size:
                raise ValueError("Original size mismatch")
            fd, name = tempfile.mkstemp(prefix=".copy-", dir=objects)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(name, destination)
                except FileExistsError:
                    pass
            finally:
                os.unlink(name)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != sha:
            raise ValueError("Backup original failed hash verification")
    manifest = {"version": 1, "created_at": store.now(), "artifacts": [sha for sha, _ in artifacts],
                "database_sha256": hashlib.sha256((scratch / "catalog.db").read_bytes()).hexdigest()}
    with (scratch / "manifest.json").open("w") as stream:
        json.dump(manifest, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    destination = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8])
    os.replace(scratch, destination)
    result = verify_backup(destination)
    with store.transaction() as c:
        store.event(c, destination.name, "backup.verified", path=str(destination), artifacts=len(artifacts))
    return result


def verify_backup(path):
    """Restore the DB into an isolated temporary directory; never touch live DB."""
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text())
    if manifest.get("version") != 1 or hashlib.sha256((path / "catalog.db").read_bytes()).hexdigest() != manifest["database_sha256"]:
        raise ValueError("Backup manifest/database mismatch")
    for sha in manifest["artifacts"]:
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("Invalid backup artifact identifier")
        if hashlib.sha256((path.parent / "objects" / (sha + ".pdf")).read_bytes()).hexdigest() != sha:
            raise ValueError("Backup artifact mismatch")
    with tempfile.TemporaryDirectory(prefix="financial-restore-check-") as scratch:
        restored = Path(scratch) / "catalog.db"
        shutil.copy2(path / "catalog.db", restored)
        c = sqlite3.connect(restored)
        try:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or c.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Restored database failed integrity checks")
            hashes = {r[0] for r in c.execute("SELECT sha FROM ingest_artifacts")}
            if hashes != set(manifest["artifacts"]):
                raise ValueError("Backup archive inventory mismatch")
            heads = c.execute("SELECT COUNT(*) FROM ingest_heads").fetchone()[0]
        finally:
            c.close()
    return {"path": str(path), "verified": True, "artifacts": len(hashes), "published_periods": heads}


def monitor():
    status = store.status()
    problems = {}
    if status["failures"]:
        problems["FAILED_JOBS"] = f"{status['jobs'].get('FAILED', 0)} failed jobs require retry or investigation"
    if status.get("discovery_errors"):
        problems["DISCOVERY_FAILED"] = f"{len(status['discovery_errors'])} annual disclosures could not be checked"
    if status["stale_publications"]:
        problems["SOURCE_REPLACED"] = f"{status['stale_publications']} published source versions changed"
    with store.transaction() as c:
        for action, code, max_age in (("worker.completed", "WORKER_STALE", 7200), ("backup.verified", "BACKUP_STALE", 93600)):
            row = c.execute("SELECT MAX(created_at) FROM ingest_events WHERE action=?", (action,)).fetchone()
            age = time.time() - datetime.fromisoformat(row[0]).timestamp() if row and row[0] else float("inf")
            if age > max_age:
                problems[code] = "No recent verified backup" if code == "BACKUP_STALE" else "No recent completed ingestion worker cycle"
        if shutil.disk_usage(documents.artifact_root()).free < 2 * 1024 ** 3:
            problems["DISK_LOW"] = "Less than 2 GiB free for catalog and original documents"
        c.execute("CREATE TABLE IF NOT EXISTS ingest_incidents (code TEXT PRIMARY KEY, detail TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, resolved_at TEXT)")
        for code, detail in problems.items():
            c.execute("INSERT INTO ingest_incidents VALUES (?,?,?,?,NULL) ON CONFLICT(code) DO UPDATE SET "
                      "detail=excluded.detail,last_seen=excluded.last_seen,first_seen=CASE WHEN ingest_incidents.resolved_at IS NOT NULL "
                      "THEN excluded.first_seen ELSE ingest_incidents.first_seen END,resolved_at=NULL", (code, detail, store.now(), store.now()))
        active = c.execute("SELECT code FROM ingest_incidents WHERE resolved_at IS NULL").fetchall()
        for row in active:
            if row["code"] not in problems:
                c.execute("UPDATE ingest_incidents SET resolved_at=? WHERE code=?", (store.now(), row["code"]))
        store.event(c, "financial-monitor", "monitor.completed", incidents=len(problems))
    return {"ok": not problems, "incidents": problems, "coverage": status}


def incidents():
    import dbx
    from catalogue.storage import get_catalog_conn
    c = get_catalog_conn()
    try:
        if "ingest_incidents" not in dbx.tables(c):
            return []
        return [dict(r) for r in c.execute("SELECT * FROM ingest_incidents WHERE resolved_at IS NULL ORDER BY first_seen")]
    finally:
        c.close()


def dashboard():
    """Read-only admin summary; failures must not look like a healthy pipeline."""
    try:
        result = {**store.status(), "incidents": incidents(), "available": True}
        c = store.connect()
        try:
            row = c.execute("SELECT MAX(created_at) FROM ingest_events WHERE action='monitor.completed'").fetchone()
            result["last_monitor_at"] = row[0] if row else None
        finally:
            c.close()
        stamp = result["last_monitor_at"]
        result["monitor_stale"] = not stamp or time.time() - datetime.fromisoformat(stamp).timestamp() > 3600
        return result
    except Exception:
        return {"available": False, "monitor_stale": True, "incidents": [], "error": "Financial pipeline status unavailable"}
