"""Recovery rehearsals use a separate empty environment and actual media files."""
import hashlib
import json
import zipfile

import pytest

from marketing import content, delivery, media, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, account, candidate, evidence, isolated  # noqa: F401
from test_marketing_delivery import Platform


def snapshot(tmp_path):
    from marketing import backup
    account(formats=["post", "image"])
    evidence()
    item = candidate(format="image")
    media.request_candidate(OWNER, item["id"], item["version"])
    assert media.run_one(NOW)
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "ready"
    delivery.schedule(item["id"], NOW)
    with store.connection() as c:
        a = store.get(c, "account", "tg")
    delivery.record_connection("tg", a["version"], external_id=a["external_id"], verified=True, now=NOW)
    assert delivery.run_one(Platform(), NOW)
    queued = candidate("not-yet-dispatched")
    content.check_candidate(queued["id"], NOW)
    delivery.schedule(queued["id"], NOW)
    inflight = delivery._claim(NOW.replace(hour=9))
    assert inflight
    with store.connection() as c:
        history = store.history(c, "candidate", item["id"])
        asset = store.list_items(c, "asset")[0]
    path = tmp_path / "backup.zip"
    result = backup.create(path)
    assert result["records"] > 0 and path.exists()
    return path, item, queued, asset, history


def test_restore_preserves_history_and_media_but_pauses_and_invalidates_connections(monkeypatch, tmp_path):
    from marketing import backup
    path, item, queued, asset, history = snapshot(tmp_path)
    monkeypatch.setenv("MARKETING_ENVIRONMENT", "recovery-rehearsal")
    inspected = backup.inspect(path)
    assert inspected["source_environment"] == "test" and inspected["media_files"] == 1
    restored = backup.restore(path)
    assert restored["environment"] == "recovery-rehearsal"
    with store.connection() as c:
        assert store.history(c, "candidate", item["id"]) == history
        assert store.get(c, "delivery", item["id"])["status"] == "published"
        assert store.get(c, "delivery", queued["id"])["status"] == "unknown"
        assert store.get(c, "candidate", queued["id"])["status"] == "unknown"
        assert store.get(c, "account", "tg")["connection_status"] == "not_connected"
        pause = store.get(c, "settings", "pause")
        assert pause["publications"] is True and pause["processing"] is True
        assert media.valid_asset(store.get(c, "asset", asset["id"]))
    assert hashlib.sha256(media.asset_path(asset).read_bytes()).hexdigest() == asset["sha256"]
    delivery.set_pause(OWNER, publications=False)
    transport = Platform()
    assert not delivery.run_one(transport, NOW.replace(hour=10))
    assert transport.calls == []
    monkeypatch.setenv("MARKETING_ENVIRONMENT", "test")
    with store.connection() as c:
        assert store.get(c, "delivery", queued["id"])["status"] == "sending"


@pytest.mark.parametrize("present", ["records", "credential", "oauth_intent"])
def test_restore_refuses_existing_environment_and_backup_never_overwrites(tmp_path, monkeypatch, present):
    from marketing import backup
    path, *_ = snapshot(tmp_path)
    before = path.read_bytes()
    with pytest.raises(MarketingError, match="exists"):
        backup.create(path)
    assert path.read_bytes() == before
    if present != "records":
        from cryptography.fernet import Fernet
        from marketing import credentials
        monkeypatch.setenv("MARKETING_ENVIRONMENT", "orphaned-connection")
        monkeypatch.setenv("MARKETING_CREDENTIAL_KEY", Fernet.generate_key().decode())
        with store.connection(write=True) as c:
            if present == "credential":
                credentials.save(c, "personal", "linkedin", {"access_token": "synthetic-orphaned-grant"})
            else:
                credentials.remember(c, "synthetic-state", {"started_at": NOW.isoformat(), "expires_at": "2026-11-23T09:00:00+00:00"})
    with pytest.raises(MarketingError, match="empty"):
        backup.restore(path)


def mutate_archive(path, change):
    with zipfile.ZipFile(path) as archive:
        files = {info.filename: archive.read(info) for info in archive.infolist()}
    manifest = json.loads(files["manifest.json"])
    change(manifest, files)
    files["manifest.json"] = json.dumps(manifest).encode()
    changed = path.with_name("changed.zip")
    with zipfile.ZipFile(changed, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    return changed


@pytest.mark.parametrize("problem", ["media", "missing_media", "history", "record", "path", "schema"])
def test_corrupt_or_unsafe_archive_is_rejected_before_any_restore_write(monkeypatch, tmp_path, problem):
    from marketing import backup
    path, *_ = snapshot(tmp_path)
    def change(manifest, files):
        if problem == "media":
            files[next(name for name in files if name.startswith("media/"))] = b"changed bytes"
        elif problem == "missing_media":
            del files[next(name for name in files if name.startswith("media/"))]
        elif problem == "history":
            manifest["revisions"].pop(0)
        elif problem == "record":
            manifest["records"][0]["payload"] = '{}'
        elif problem == "path":
            files["media/../../outside.txt"] = b"no"
        else:
            manifest["format"] = 999
    changed = mutate_archive(path, change)
    monkeypatch.setenv("MARKETING_ENVIRONMENT", "empty-target")
    with pytest.raises(MarketingError, match="archive"):
        backup.restore(changed)
    with store.connection() as c:
        assert store.list_items(c, "candidate") == []
        assert store.list_items(c, "settings") == []
    assert not list(media.directory().iterdir())
    assert not (tmp_path / "outside.txt").exists()


def test_backup_requires_every_referenced_historical_asset(tmp_path):
    from marketing import backup
    path, _, _, asset, _ = snapshot(tmp_path)
    media.asset_path(asset).unlink()
    failed = path.with_name("missing.zip")
    with pytest.raises(MarketingError, match="media"):
        backup.create(failed)
    assert not failed.exists()


def test_restore_does_not_overwrite_existing_media_directory(monkeypatch, tmp_path):
    from marketing import backup
    path, *_ = snapshot(tmp_path)
    monkeypatch.setenv("MARKETING_ENVIRONMENT", "occupied-media")
    existing = media.directory() / "existing.txt"
    existing.write_text("keep", encoding="utf-8")
    with pytest.raises(MarketingError, match="empty"):
        backup.restore(path)
    assert existing.read_text() == "keep"
    with store.connection() as c:
        assert store.list_items(c, "candidate") == []


def test_old_snapshot_queue_cannot_replay_work_completed_after_the_backup_cut(monkeypatch, tmp_path):
    from marketing import backup
    from test_marketing_delivery import prepare
    job = prepare()
    path = tmp_path / "before-send.zip"
    backup.create(path)
    assert delivery.run_one(Platform(), NOW)  # Original system sent after the cut.
    monkeypatch.setenv("MARKETING_ENVIRONMENT", "restore-old-cut")
    backup.restore(path)
    delivery.set_pause(OWNER, publications=False, processing=False)
    with store.connection() as c:
        a = store.get(c, "account", "tg")
    delivery.record_connection("tg", a["version"], external_id=a["external_id"], verified=True, now=NOW)
    transport = Platform()
    assert not delivery.run_one(transport, NOW)
    assert transport.calls == []
    with store.connection() as c:
        guard = store.get(c, "settings", "recovery")
        assert guard["status"] == "requires_reconciliation"
        assert store.get(c, "delivery", job["id"])["attempts"] == 0


@pytest.mark.parametrize("name", ["../escape.png", ".. ", "CON", "con.png", "a:stream.png", "back\\slash.png", "a.", "/absolute.png"])
def test_archive_media_names_are_safe_on_windows_and_linux(name):
    from marketing.backup_archive import media_name
    with pytest.raises(MarketingError):
        media_name(name)
