"""Portable, environment-scoped backups. Restore only into an empty destination.

Run with the service's database environment, with its worker stopped for a
restore: python -m marketing.backup create|inspect|restore PATH.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

from . import backup_archive as archive_format, media, store as s
from .errors import MarketingError

ACTOR = {"id": "restore", "role": "operator"}
RECORD_COLUMNS = ("kind", "id", "version", "status", "updated_at", "payload")
REVISION_COLUMNS = ("kind", "id", "version", "created_at", "actor", "action", "payload")


def _rows(c, table, columns):
    rows = c.execute(f"SELECT {','.join(columns)} FROM {table} WHERE environment=? ORDER BY kind,id,version", (s.environment(),)).fetchall()
    return [{key: row[key] for key in columns} for row in rows]


def create(path):
    path = Path(path)
    if path.exists():
        raise MarketingError("BACKUP_EXISTS", "Backup destination already exists.")
    with s.connection(write=True) as c:
        manifest = {"format": archive_format.FORMAT, "schema": "marketing-v1", "environment": s.environment(), "created_at": s.now(),
                    "records": _rows(c, "marketing_records", RECORD_COLUMNS), "revisions": _rows(c, "marketing_revisions", REVISION_COLUMNS)}
        files = archive_format.validate_records(manifest)
        raw = s.encode(manifest).encode("utf-8")
        if len(raw) > archive_format.MAX_MANIFEST:
            raise MarketingError("BACKUP_SIZE", "Archive manifest exceeds the portable backup limit; use database-native backup.")
        total = len(raw)
        created = False
        try:
            # Exclusive creation also protects against a concurrent backup writer.
            with path.open("xb") as target:
                created = True
                with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("manifest.json", raw)
                    for name, asset in files.items():
                        try:
                            data = media.read_asset(asset)
                        except MarketingError:
                            raise MarketingError("BACKUP_MEDIA", "Backup requires every referenced historical media file.") from None
                        total += len(data)
                        if total > archive_format.MAX_TOTAL:
                            raise MarketingError("BACKUP_SIZE", "Archive exceeds the portable backup limit; use database-native backup.")
                        archive.writestr(name, data)
                target.flush()
                os.fsync(target.fileno())
        except FileExistsError:
            raise MarketingError("BACKUP_EXISTS", "Backup destination already exists.") from None
        except Exception:
            if created:
                path.unlink(missing_ok=True)
            raise
    return archive_format.summary(manifest, files)


def inspect(path):
    try:
        with zipfile.ZipFile(path) as archive:
            return archive_format.summary(*archive_format.read(archive))
    except (OSError, zipfile.BadZipFile):
        raise archive_format.invalid() from None


def _insert(c, table, columns, row):
    c.execute(f"INSERT INTO {table}(environment,{','.join(columns)}) VALUES ({','.join('?' for _ in range(len(columns) + 1))})",
              (s.environment(), *(row[key] for key in columns)))


def _safe_restart(c, manifest):
    from .recovery import recipient_scopes
    pause = s.get(c, "settings", "pause", required=False) or {"id": "pause", "version": 0}
    s.put(c, "settings", {**pause, "publications": True, "processing": True}, actor=ACTOR,
          action="restore_paused", expected_version=pause["version"])
    recovery = s.get(c, "settings", "recovery", required=False) or {"id": "recovery", "version": 0}
    s.put(c, "settings", {**recovery, "status": "requires_reconciliation", "restored_at": s.now(),
          'recipient_scopes': recipient_scopes(c),
          "backup_created_at": manifest["created_at"], "source_environment": manifest["environment"],
          "reason": "Reconcile external publications since the backup cut before enabling dispatch"}, actor=ACTOR,
          action="restore_reconciliation_required", expected_version=recovery["version"])
    for account in s.list_items(c, "account"):
        s.put(c, "account", {**account, "connection_status": "not_connected", "connection_fingerprint": None,
              "connection_identity": None, "connection_checked_at": None, "connection_reason": "Restored account requires new connection verification"},
              actor=ACTOR, action="restore_connection_invalidated", expected_version=account["version"])
    # A snapshot may predate completion in the original process. Never replay a
    # claimed send, including one that later succeeded after this backup cut.
    for job in s.list_items(c, "delivery", status="sending"):
        s.put(c, "delivery", {**job, "status": "unknown", "reason": "Restored in-flight dispatch requires reconciliation"},
              actor=ACTOR, action="restore_dispatch_unknown", expected_version=job["version"])
        item = s.get(c, "candidate", job["candidate_id"])
        s.put(c, "candidate", {**item, "status": "unknown"}, actor=ACTOR,
              action="restore_dispatch_unknown", expected_version=item["version"])
    heartbeat = s.get(c, "runtime", "worker", required=False)
    if heartbeat:
        s.put(c, "runtime", {**heartbeat, "status": "restored", "reason": "Worker has not completed a cycle in this restored environment"},
              actor=ACTOR, action="restore_runtime", expected_version=heartbeat["version"])


def restore(path):
    written = []
    try:
        with zipfile.ZipFile(path) as archive:
            manifest, files = archive_format.read(archive)
            root = media.directory()
            with s.connection(write=True) as c:
                # Credentials/intents are intentionally absent from the archive,
                # but an existing connection still makes the destination nonempty.
                populated = any(c.execute(f"SELECT 1 FROM {table} WHERE environment=? LIMIT 1", (s.environment(),)).fetchone()
                                for table in ("marketing_records", "marketing_revisions", "marketing_credentials", "marketing_oauth_states"))
                if populated or any(root.iterdir()):
                    raise MarketingError("RESTORE_NOT_EMPTY", "Restore requires an empty environment and empty media directory.")
                with tempfile.TemporaryDirectory(prefix="marketing-restore-", dir=root.parent) as staging:
                    for name in files:
                        destination = Path(staging) / name.removeprefix("media/")
                        with archive.open(name) as source, destination.open("xb") as target:
                            shutil.copyfileobj(source, target, length=1_048_576)
                            target.flush()
                            os.fsync(target.fileno())
                    for row in manifest["records"]:
                        _insert(c, "marketing_records", RECORD_COLUMNS, row)
                    for row in manifest["revisions"]:
                        _insert(c, "marketing_revisions", REVISION_COLUMNS, row)
                    _safe_restart(c, manifest)
                    for name in files:
                        source = Path(staging) / name.removeprefix("media/")
                        destination = root / source.name
                        # Do not overwrite a concurrently created file.
                        with destination.open("xb") as target, source.open("rb") as stream:
                            written.append(destination)
                            shutil.copyfileobj(stream, target, length=1_048_576)
                            target.flush()
                            os.fsync(target.fileno())
            return {**archive_format.summary(manifest, files), "environment": s.environment(), "paused": True}
    except Exception as exc:
        for destination in written:
            destination.unlink(missing_ok=True)
        if isinstance(exc, zipfile.BadZipFile):
            raise archive_format.invalid() from None
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "inspect", "restore"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        result = {"create": create, "inspect": inspect, "restore": restore}[args.action](args.path)
    except MarketingError as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
