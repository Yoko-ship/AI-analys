"""Page Reels keep upload recovery separate from the single public finish."""
from datetime import timedelta
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from marketing import delivery, media, permissions, store, worker
from test_marketing_core import OWNER, NOW, isolated  # noqa: F401
from test_marketing_facebook import FacebookPeer, queued, current
from test_marketing_meta import PAGE_ID, PAGE_TOKEN, SECRET

VIDEO_ID = "567890"


class ReelPeer(FacebookPeer):
    def __init__(self, monkeypatch, now=NOW):
        self.registrations, self.uploaded, self.finishes = 0, b"", []
        self.processing, self.publication, self.reported_size = "completed", "published", None
        self.upload_url = f"https://rupload.facebook.com/video-upload/v25.0/{VIDEO_ID}"
        self.upload_outcome, self.finish_outcome, self.status_mutation = None, None, None
        self.reel_description, self.reel_id, self.reel_paging = None, VIDEO_ID, None
        self.video_id = VIDEO_ID
        super().__init__(monkeypatch, now)

    def send(self, request, **options):
        url = urlsplit(request.url)
        path, query = url.path, parse_qs(url.query)
        is_reel = path.endswith("/video_reels") or path == "/v25.0/" + self.video_id or url.netloc == "rupload.facebook.com"
        if not is_reel:
            return super().send(request, **options)
        assert options["allow_redirects"] is False and options["timeout"] == (5, 30)
        self.calls.append(request)
        outcome = None
        if url.netloc == "rupload.facebook.com":
            assert request.method == "POST" and request.url == self.upload_url
            assert request.headers["Authorization"] == "OAuth " + PAGE_TOKEN
            assert request.headers["Content-Type"] == "application/octet-stream"
            assert int(request.headers["offset"]) == len(self.uploaded)
            self.reported_size = int(request.headers["file_size"])
            if self.upload_outcome:
                self.uploaded += request.body[:50002]
            else:
                self.uploaded += request.body
            outcome, value = self.upload_outcome, {"success": True}
        else:
            assert url.netloc == "graph.facebook.com" and path.startswith("/v25.0/")
            assert request.headers["Authorization"] == "Bearer " + PAGE_TOKEN
            values = query if request.method == "GET" else parse_qs(request.body)
            assert values["appsecret_proof"] == [hmac.new(SECRET.encode(), PAGE_TOKEN.encode(), hashlib.sha256).hexdigest()]
            if path == f"/v25.0/{PAGE_ID}/video_reels" and request.method == "POST":
                if values["upload_phase"] == ["start"]:
                    self.registrations += 1
                    if self.registrations > 1:
                        self.video_id = str(int(VIDEO_ID) + self.registrations - 1)
                        self.reel_id, self.uploaded, self.reported_size = self.video_id, b"", None
                        self.upload_url = f"https://rupload.facebook.com/video-upload/v25.0/{self.video_id}"
                    value = {"video_id": self.video_id, "upload_url": self.upload_url}
                else:
                    assert values["upload_phase"] == ["finish"] and values["video_id"] == [self.video_id]
                    assert values["video_state"] == ["PUBLISHED"] and values["is_ai_generated"] == ["true"]
                    assert "collaborators" not in values and "scheduled_publish_time" not in values
                    self.finishes.append(values)
                    self.reel_description = values["description"][0]
                    value, outcome = {"success": True}, self.finish_outcome
            elif path == "/v25.0/" + self.video_id:
                assert request.method == "GET" and query["fields"] == ["status"]
                upload_complete = self.reported_size is not None and len(self.uploaded) == self.reported_size
                value = {"id": self.video_id, "status": {"video_status": "ready" if self.processing == "completed" and upload_complete else "processing",
                    "uploading_phase": {"status": "completed" if upload_complete else "in_progress", "bytes_transfered": len(self.uploaded),
                                        "source_file_size": self.reported_size},
                    "processing_phase": {"status": self.processing},
                    "publishing_phase": {"status": "completed" if self.finishes else "not_started", "publish_status": self.publication if self.finishes else "draft",
                                         "publish_time": int(self.now.timestamp()) if self.finishes else None}}}
                if self.status_mutation:
                    self.status_mutation(value)
            else:
                assert request.method == "GET" and path == f"/v25.0/{PAGE_ID}/video_reels"
                value = {"data": [{"id": self.reel_id, "description": self.reel_description}] if self.finishes else []}
                if self.reel_paging:
                    value["paging"] = self.reel_paging
        if isinstance(outcome, Exception):
            raise outcome
        status, body, headers = outcome or (200, value, {})
        response = requests.Response()
        response.status_code, response.headers = status, headers
        response._content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return response


def reel(monkeypatch):
    return queued(monkeypatch, "video", peer_class=ReelPeer)


def test_real_reel_uploads_checked_bytes_then_waits_for_independent_page_confirmation(monkeypatch):
    peer, job, files = reel(monkeypatch)
    assert worker.tick(now=NOW)["delivery_work"]
    assert peer.uploaded == media.read_asset(files[0]) and peer.registrations == 1 and len(peer.finishes) == 1
    saved = current(job)
    assert saved["status"] == "submitted" and saved["external_id"] == VIDEO_ID
    assert saved["url"] == f"https://www.facebook.com/reel/{VIDEO_ID}/"
    assert saved["dispatch_payload"]["text"] == peer.finishes[0]["description"][0]
    assert saved["dispatch_payload"]["media_ids"] == [VIDEO_ID] and saved["dispatch_payload"]["audience"] == "PUBLIC"
    assert saved["dispatch_payload"]["is_ai_generated"] is True
    assert worker.tick(now=NOW + timedelta(seconds=60))["confirmation_work"]
    assert current(job)["status"] == "published" and current(job)["published_at"] == NOW.isoformat()
    assert not worker.tick(now=NOW + timedelta(hours=1))["delivery_work"] and len(peer.finishes) == 1


def test_processing_reel_reuses_upload_without_consuming_public_attempts(monkeypatch):
    peer, job, _ = reel(monkeypatch)
    peer.processing = "in_progress"
    worker.tick(now=NOW)
    waiting = current(job)
    assert waiting["status"] == "retry" and waiting["attempts"] == 0 and waiting["confirmed_not_sent"]
    assert permissions.timestamp(waiting["next_attempt_at"]) == NOW + timedelta(seconds=60)
    assert peer.registrations == 1 and not peer.finishes
    count = len([r for r in peer.calls if urlsplit(r.url).netloc == "rupload.facebook.com"])
    peer.processing = "completed"
    assert worker.tick(now=NOW + timedelta(seconds=60))["delivery_work"]
    assert len([r for r in peer.calls if urlsplit(r.url).netloc == "rupload.facebook.com"]) == count
    assert current(job)["status"] == "submitted" and len(peer.finishes) == 1


def test_interrupted_reel_upload_resumes_at_the_provider_confirmed_byte_offset(monkeypatch):
    peer, job, files = reel(monkeypatch)
    peer.upload_outcome = requests.Timeout("synthetic lost upload response")
    worker.tick(now=NOW)
    assert current(job)["status"] == "retry" and not peer.finishes
    assert len(peer.uploaded) == 50002 and peer.registrations == 1
    peer.upload_outcome = None
    assert worker.tick(now=NOW + timedelta(seconds=60))["delivery_work"]
    assert peer.uploaded == media.read_asset(files[0]) and peer.registrations == 1 and len(peer.finishes) == 1


def test_provider_upload_failed_state_resumes_only_its_confirmed_partial_bytes(monkeypatch):
    peer, job, files = reel(monkeypatch)
    peer.upload_outcome = requests.Timeout("synthetic interruption")
    worker.tick(now=NOW)
    peer.upload_outcome = None
    def failed_partial(value):
        if len(peer.uploaded) < peer.reported_size:
            value["status"].update(video_status="upload_failed")
            value["status"]["uploading_phase"].update(status="error", errors=[{"message": "interrupted upload"}])
    peer.status_mutation = failed_partial
    worker.tick(now=NOW + timedelta(seconds=60))
    assert current(job)["status"] == "submitted" and peer.uploaded == media.read_asset(files[0])
    assert peer.registrations == 1 and len(peer.finishes) == 1


@pytest.mark.parametrize("always_expired", [False, True])
def test_expired_unpublished_upload_restarts_with_a_new_id_and_a_bounded_session_count(monkeypatch, always_expired):
    peer, job, files = reel(monkeypatch)
    def expired(value):
        if always_expired or value["id"] == VIDEO_ID:
            value["status"]["video_status"] = "expired"
    peer.status_mutation = expired
    worker.tick(now=NOW)
    assert current(job)["status"] == "retry" and not peer.finishes
    for index in range(1, 4 if always_expired else 2):
        worker.tick(now=NOW + timedelta(seconds=index * 60))
    if always_expired:
        assert current(job)["status"] == "error" and peer.registrations == 3 and not peer.finishes
    else:
        assert current(job)["status"] == "submitted" and current(job)["external_id"] != VIDEO_ID
        assert peer.registrations == 2 and len(peer.finishes) == 1 and peer.uploaded == media.read_asset(files[0])


@pytest.mark.parametrize("change", ["offset", "size", "video", "processing_error", "published_before_finish"])
def test_invalid_reel_status_never_reuploads_or_publishes_blindly(monkeypatch, change):
    peer, job, _ = reel(monkeypatch)
    peer.processing = "in_progress"
    worker.tick(now=NOW)
    assert not peer.finishes
    count = len([r for r in peer.calls if urlsplit(r.url).netloc == "rupload.facebook.com"])
    def mutate(value):
        if change == "offset":
            value["status"]["uploading_phase"]["bytes_transfered"] = True
        elif change == "size":
            value["status"]["uploading_phase"]["source_file_size"] += 1
        elif change == "video":
            value["id"] = "99999"
        elif change == "processing_error":
            value["status"]["processing_phase"]["error"] = {"message": "private provider text"}
        else:
            value["status"]["publishing_phase"].update(status="completed", publish_status="published")
    peer.status_mutation = mutate
    worker.tick(now=NOW + timedelta(seconds=60))
    assert current(job)["status"] == "error" and not peer.finishes
    assert len([r for r in peer.calls if urlsplit(r.url).netloc == "rupload.facebook.com"]) == count
    assert "private provider text" not in json.dumps(current(job))


@pytest.mark.parametrize("url", ["https://evil.example/video-upload/567890", "http://rupload.facebook.com/video-upload/567890",
    "https://rupload.facebook.com/video-upload/99999", "https://rupload.facebook.com:444/video-upload/567890",
    "https://rupload.facebook.com/video-upload/v27.0/567890"])
def test_reel_upload_url_must_bind_the_known_video_host_and_version(monkeypatch, url):
    peer, job, _ = reel(monkeypatch)
    peer.upload_url = url
    worker.tick(now=NOW)
    assert current(job)["status"] == "error" and not peer.uploaded and not peer.finishes


@pytest.mark.parametrize("outcome", [requests.Timeout("lost accepted finish"), (503, {"error": {"code": 2}}, {}),
    (200, {"success": False}, {}), (200, {}, {})], ids=["timeout", "server-error", "false", "missing"])
def test_uncertain_reel_finish_is_never_replayed(monkeypatch, outcome):
    peer, job, _ = reel(monkeypatch)
    peer.finish_outcome = outcome
    worker.tick(now=NOW)
    assert current(job)["status"] == "unknown" and len(peer.finishes) == 1
    assert not worker.tick(now=NOW + timedelta(hours=1))["delivery_work"]
    assert len(peer.finishes) == 1


def test_lost_finish_response_can_be_reconciled_by_known_video_and_page_reads(monkeypatch):
    peer, job, _ = reel(monkeypatch)
    peer.finish_outcome = requests.Timeout("lost accepted finish")
    worker.tick(now=NOW)
    assert current(job)["status"] == "unknown"
    assert worker.tick(now=NOW + timedelta(seconds=60))["confirmation_work"]
    saved = current(job)
    assert saved["status"] == "published" and saved["external_id"] == VIDEO_ID and saved["provider"] == "facebook"
    assert saved["visibility_confirmation"]["method"] == "provider_read" and len(peer.finishes) == 1


def test_worker_crash_after_reel_finish_recovers_by_reading_without_a_completion_timestamp(monkeypatch):
    peer, job, _ = reel(monkeypatch)
    original = peer.send
    def crash(_session, request, **options):
        response = original(request, **options)
        if request.method == "POST" and urlsplit(request.url).path.endswith("/video_reels") and parse_qs(request.body)["upload_phase"] == ["finish"]:
            raise KeyboardInterrupt("synthetic process death")
        return response
    monkeypatch.setattr(requests.Session, "send", crash)
    with pytest.raises(KeyboardInterrupt):
        worker.tick(now=NOW)
    assert current(job)["status"] == "sending" and "finished_at" not in current(job)
    monkeypatch.setattr(requests.Session, "send", peer.send)
    assert worker.tick(now=NOW + timedelta(seconds=delivery.LEASE_SECONDS + 5))["confirmation_work"]
    assert current(job)["status"] == "published" and len(peer.finishes) == 1


@pytest.mark.parametrize("change", ["id", "description", "not_published", "time"])
def test_reel_confirmation_requires_both_published_status_and_exact_page_membership(monkeypatch, change):
    peer, job, _ = reel(monkeypatch)
    worker.tick(now=NOW)
    if change == "id":
        peer.reel_id = "99999"
    elif change == "description":
        peer.reel_description += " unapproved"
    elif change == "not_published":
        peer.publication = "draft"
    else:
        peer.status_mutation = lambda value: value["status"]["publishing_phase"].update(publish_time=int((NOW - timedelta(days=1)).timestamp()))
    worker.tick(now=NOW + timedelta(seconds=60))
    assert current(job)["status"] == "submitted" and len(peer.finishes) == 1


def test_reels_limit_counts_the_page_across_accounts_and_keeps_unknown_writes_reserved(monkeypatch):
    peer, job, _ = reel(monkeypatch)
    with store.connection(write=True) as c:
        for index in range(30):
            at = (NOW - timedelta(hours=23) + timedelta(seconds=index)).isoformat()
            store.put(c, "delivery", {**job, "id": f"earlier-reel-{index}", "account_id": "same-page-another-account",
                "status": "unknown" if index % 2 else "published", "dispatch_phase": "request_started",
                "claimed_at": (NOW - timedelta(days=2)).isoformat(), "provider_requested_at": at,
                "dispatch_payload": {"format": "video"}}, actor=OWNER, action="synthetic_reel", expected_version=0)
    assert not worker.tick(now=NOW)["delivery_work"]
    assert not peer.registrations and not peer.finishes
    assert permissions.timestamp(current(job)["next_attempt_at"]) == NOW + timedelta(hours=1)
    assert not worker.tick(now=NOW + timedelta(seconds=3599))["delivery_work"]
    assert worker.tick(now=NOW + timedelta(hours=1))["delivery_work"]
    assert len(peer.finishes) == 1


def test_reserved_inflight_reel_uses_the_last_available_page_slot(monkeypatch):
    peer, job, _ = reel(monkeypatch)
    with store.connection(write=True) as c:
        for index in range(30):
            at = (NOW - timedelta(hours=1)).isoformat()
            store.put(c, "delivery", {**job, "id": f"parallel-reel-{index}", "account_id": "another-account",
                "candidate_id": job["candidate_id"], "status": "sending" if index == 29 else "published",
                "format": "video", "dispatch_phase": "preparing" if index == 29 else "request_started",
                "claimed_at": at, "provider_requested_at": at, "heartbeat_at": NOW.isoformat()},
                actor=OWNER, action="synthetic_reel", expected_version=0)
    assert not worker.tick(now=NOW)["delivery_work"] and not peer.registrations
    assert permissions.timestamp(current(job)["next_attempt_at"]) == NOW + timedelta(seconds=60)
