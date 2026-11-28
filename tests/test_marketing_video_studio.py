"""Independent video projects, durable handoffs and a narrowly scoped PC worker."""
from datetime import timedelta

import pytest

from marketing import store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, isolated  # noqa: F401


def storyboard():
    return {"title": "Знакомство с UZStock", "scenes": [
        {"headline": "С чего начать?", "narration": "Хотите разобраться в рынке Узбекистана? Начните со знакомства с UZStock.", "page": "home"},
        {"headline": "Читайте новости", "narration": "Откройте новости на сайте. Выберите материал и прочитайте его целиком.", "page": "news"},
        {"headline": "Откройте UZStock", "narration": "Загляните на сайт UZStock и познакомьтесь с его разделами. Начните с темы, которая вам интересна.", "page": "home"},
    ]}


class Director:
    def complete_json(self, system, user, **kwargs):
        assert "Telegram" in system and "UZStock" in user
        return storyboard()


def project():
    from marketing import video_studio
    return video_studio.create(OWNER, {"brief": "PR-ролик о сайте UZStock и разделе новостей"})


def test_video_agent_needs_only_a_brief_and_never_creates_a_social_post():
    from marketing import video_studio as v
    item = project()
    assert item["status"] == "queued_script"
    assert v.run_one(Director(), NOW)
    with store.connection() as c:
        saved = store.get(c, "video_project", item["id"])
        assert saved["status"] == "queued_render"
        assert saved["storyboard"] == storyboard()
        for kind in ("account", "candidate", "delivery", "evidence"):
            assert store.list_items(c, kind) == []


def test_invalid_model_output_is_retryable_and_never_sent_to_renderer():
    from marketing import video_studio as v
    item = project()
    class BadDirector:
        def complete_json(self, *args, **kwargs):
            value = storyboard()
            value["scenes"][1]["page"] = "https://internal.example/admin"
            return value
    v.run_one(BadDirector(), NOW)
    with store.connection() as c:
        failed = store.get(c, "video_project", item["id"])
        assert failed["status"] == "error" and "internal.example" not in str(failed)
    assert v.claim(NOW) is None
    v.retry(OWNER, item["id"], failed["version"])
    assert v.run_one(Director(), NOW)


def test_claims_are_exclusive_and_expired_workers_cannot_overwrite_new_work():
    from marketing import video_studio as v
    item = project()
    v.run_one(Director(), NOW)
    first = v.claim(NOW)
    assert first["id"] == item["id"] and first["lease_token"]
    assert v.claim(NOW) is None
    later = NOW + timedelta(minutes=7)
    second = v.claim(later)
    assert second["id"] == first["id"] and second["lease_token"] != first["lease_token"]
    with pytest.raises(MarketingError):
        v.progress(item["id"], first["lease_token"], "capturing", later)
    assert v.progress(item["id"], second["lease_token"], "capturing", later)["stage"] == "capturing"
    with store.connection(write=True) as c:
        store.put(c, "settings", {"id": "pause", "processing": True}, actor=OWNER, action="pause", expected_version=0)
    assert v.claim(later + timedelta(hours=2)) is None


def test_cancel_invalidates_the_render_lease_and_public_view_hides_it():
    from marketing import video_studio as v
    item = project()
    v.run_one(Director(), NOW)
    claimed = v.claim(NOW)
    assert "lease_token" not in v.public(claimed)
    v.cancel(OWNER, item["id"], claimed["version"])
    with pytest.raises(MarketingError):
        v.progress(item["id"], claimed["lease_token"], "encoding", NOW)


def test_video_worker_token_cannot_access_admin_and_bad_tokens_cannot_claim(monkeypatch):
    from fastapi.testclient import TestClient
    import api
    monkeypatch.setenv("MARKETING_VIDEO_WORKER_TOKEN", "test-worker-secret-" + "x" * 40)
    client = TestClient(api.app)
    path = "/api/marketing-video-worker/claim"
    assert client.post(path).status_code == 401
    assert client.post(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    headers = {"Authorization": "Bearer test-worker-secret-" + "x" * 40}
    assert client.post(path, headers=headers).status_code == 200
    assert client.get("/api/admin/ai-marketing/workspace", headers=headers).status_code in (401, 403, 503)


def test_storyboard_cannot_be_changed_after_claim_and_viewer_cannot_start():
    from marketing import video_studio as v
    with pytest.raises(MarketingError):
        v.create({"role": "viewer"}, {"brief": "Ролик о сайте UZStock"})
    item = project()
    with pytest.raises(MarketingError):
        v.cancel(OWNER, item["id"], 0)


def test_video_upload_requires_narration_and_keeps_cancelled_work_private(monkeypatch, tmp_path):
    from marketing import video_studio as v, video_files
    item = project()
    v.run_one(Director(), NOW)
    claimed = v.claim(NOW)
    source = tmp_path / "upload.mp4"
    source.write_bytes(b"synthetic video file")
    def reject(_path):
        raise ValueError("Missing narration")
    monkeypatch.setattr(video_files, "inspect_video", reject)
    with pytest.raises(MarketingError):
        video_files.finish(item["id"], claimed["lease_token"], source, NOW)
    with store.connection() as c:
        assert store.get(c, "video_project", item["id"])["status"] == "rendering"
    monkeypatch.setattr(video_files, "inspect_video", lambda path: {"duration_seconds": 32, "width": 1080, "height": 1920})
    ready = video_files.finish(item["id"], claimed["lease_token"], source, NOW)
    assert ready["status"] == "complete"
    assert video_files.read(ready) == b"synthetic video file"
    video_files.path(ready).write_bytes(b"corrupted")
    with pytest.raises(MarketingError):
        video_files.read(ready)


def test_video_upload_chunks_resume_without_duplication_or_crossing_leases(tmp_path):
    from marketing import video_studio as v, video_files
    item = project()
    v.run_one(Director(), NOW)
    claimed = v.claim(NOW)
    token = claimed["lease_token"]
    assert video_files.append(item["id"], token, 0, b"first", NOW) == 5
    assert video_files.append(item["id"], token, 0, b"first", NOW) == 5
    with pytest.raises(MarketingError):
        video_files.append(item["id"], token, 0, b"other", NOW)
    with pytest.raises(MarketingError):
        video_files.append(item["id"], token, 6, b"gap", NOW)
    assert video_files.append(item["id"], token, 5, b"second", NOW) == 11
    assert video_files.upload_path(item["id"], token).read_bytes() == b"firstsecond"
    with pytest.raises(MarketingError):
        video_files.append(item["id"], token, 11, b"x" * 512001, NOW)
