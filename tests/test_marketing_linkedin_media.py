"""Real rendered bytes through intercepted LinkedIn upload and post contracts."""
from datetime import timedelta
import json
import hashlib
from urllib.parse import unquote, urlsplit

import pytest
import requests

from marketing import channels, content, delivery, founder, media, permissions, store, worker
from marketing.models import Account
from test_marketing_core import OWNER, NOW, candidate, evidence, isolated  # noqa: F401
from test_marketing_founder import fact_data
from test_marketing_linkedin import LinkedInPeer, PERSON, TOKEN, finish, personal, start

UPLOAD_SECRET = "synthetic-private-upload-ticket"


class MediaPeer(LinkedInPeer):
    def __init__(self, monkeypatch, now=NOW):
        super().__init__(monkeypatch)
        self.now = now
        self.images = 0
        self.video_status = "AVAILABLE"
        self.video_owner = PERSON
        self.video_id = "urn:li:video:video1"
        self.change_registration = None
        self.upload_outcome = None
        self.finalize_outcome = None

    def response(self, status, value=None, headers=None):
        response = requests.Response()
        response.status_code = status
        response._content = json.dumps(value).encode() if value is not None else b""
        response.headers.update(headers or {})
        return response

    def send(self, request, **options):
        url = urlsplit(request.url)
        if not (url.path.startswith("/rest/images") or url.path.startswith("/rest/videos") or url.path.startswith("/dms-uploads/")):
            return super().send(request, **options)
        assert options["allow_redirects"] is False and options["timeout"] == (5, 30)
        self.calls.append(request)
        if self.before:
            self.before(request)
        expires = int((self.now + timedelta(days=1)).timestamp() * 1000)
        if url.path.startswith("/dms-uploads/"):
            assert request.method == "PUT" and isinstance(request.body, bytes)
            is_image = "uploaded-image" in url.path
            assert request.headers.get("Authorization") == ("Bearer " + TOKEN if is_image else None)
            assert request.headers["Content-Type"] == "application/octet-stream"
            if isinstance(self.upload_outcome, Exception):
                raise self.upload_outcome
            if self.upload_outcome:
                return self.response(*self.upload_outcome)
            return self.response(201 if is_image else 200, headers={"ETag": '"part-' + url.path.rsplit("/", 1)[-1] + '"'})
        assert url.netloc == "api.linkedin.com" and request.headers["Authorization"] == "Bearer " + TOKEN
        assert request.headers["Linkedin-Version"] == "202606" and request.headers["X-Restli-Protocol-Version"] == "2.0.0"
        if request.method == "GET":
            assert url.path.startswith("/rest/videos/")  # w_member_social cannot GET versioned images.
            assert unquote(url.path.rsplit("/", 1)[-1]) == "urn:li:video:video1"
            return self.response(200, {"id": self.video_id, "owner": self.video_owner, "status": self.video_status})
        body = json.loads(request.body)
        if url.query == "action=finalizeUpload":
            assert body["finalizeUploadRequest"] == {"video": "urn:li:video:video1", "uploadToken": UPLOAD_SECRET,
                "uploadedPartIds": ["part-0", "part-1"]}
            if isinstance(self.finalize_outcome, Exception):
                raise self.finalize_outcome
            return self.response(200)
        assert url.query == "action=initializeUpload"
        request_data = body["initializeUploadRequest"]
        assert request_data["owner"] == PERSON and "mediaLibraryMetadata" not in request_data
        if url.path == "/rest/images":
            self.images += 1
            identifier = "image" + str(self.images)
            value = {"image": "urn:li:image:" + identifier, "uploadUrlExpiresAt": expires,
                     "uploadUrl": f"https://www.linkedin.com/dms-uploads/{identifier}/uploaded-image/0?ticket={UPLOAD_SECRET}"}
        else:
            assert request_data["uploadCaptions"] is False and request_data["uploadThumbnail"] is False
            size = request_data["fileSizeBytes"]
            middle = size // 2
            value = {"video": "urn:li:video:video1", "uploadUrlsExpireAt": expires, "uploadToken": UPLOAD_SECRET,
                     "uploadInstructions": [{"firstByte": begin, "lastByte": end,
                        "uploadUrl": f"https://www.linkedin.com/dms-uploads/video1/uploadedVideo/{index}?ticket={UPLOAD_SECRET}"}
                        for index, (begin, end) in enumerate([(0, middle - 1), (middle, size - 1)])]}
        if self.change_registration:
            self.change_registration(value)
        return self.response(200, {"value": value})


def queued_media(monkeypatch, format="image"):
    peer = MediaPeer(monkeypatch)
    saved = finish(start(personal()))
    permissions.save_account(OWNER, "li", {**{k: v for k, v in saved.items() if k in Account.model_fields},
        "mode": "automatic", "formats": ["image", "carousel", "video", "story"]}, saved["version"])
    evidence()
    founder.save(OWNER, "founder-role", fact_data(), 0)
    item = candidate(target="li", format=format, founder_fact_ids=["founder-role"])
    media.request_candidate(OWNER, item["id"], item["version"])
    assert media.run_one(NOW)
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "ready", checked["check"]["reason"]
    job = delivery.schedule(item["id"], NOW)
    with store.connection() as c:
        files = [store.get(c, "asset", ref["id"]) for ref in checked["assets"]]
    return peer, job, files


def posts(peer):
    return [request for request in peer.calls if request.url.endswith("/rest/posts")]


@pytest.mark.parametrize("format", ["image", "carousel", "video"])
def test_linkedin_media_uploads_exact_rendered_bytes_and_creates_one_personal_post(monkeypatch, format):
    peer, job, files = queued_media(monkeypatch, format)
    assert worker.tick(now=NOW)["delivery_work"]
    assert len(posts(peer)) == 1
    body = json.loads(posts(peer)[0].body)
    assert body["author"] == PERSON and "adContext" not in body
    uploads = [r for r in peer.calls if r.method == "PUT"]
    assert b"".join(r.body for r in uploads) == b"".join(media.read_asset(file) for file in files)
    entries = body["content"]["multiImage"]["images"] if format == "carousel" else [body["content"]["media"]]
    assert len(entries) == len(files)
    assert all(entry["id"].startswith("urn:li:video:" if format == "video" else "urn:li:image:") for entry in entries)
    if format != "video":
        assert all(entry["altText"] == file["alt_text"] for entry, file in zip(entries, files))
    with store.connection() as c:
        result = store.get(c, "delivery", job["id"])
        progress = store.list_items(c, "provider_upload")
        public = json.dumps([result, progress, store.history(c, "delivery", job["id"])])
    assert result["status"] == "submitted"  # Created ID does not prove asynchronous visibility.
    assert result["external_id"] == "urn:li:share:123456789" and result["dispatch_payload"]["media_count"] == len(files)
    assert len(progress) == len(files) and all(row["status"] in {"uploaded", "ready"} for row in progress)
    assert TOKEN not in public and UPLOAD_SECRET not in public and "uploadToken" not in public
    assert not worker.tick(now=NOW + timedelta(hours=1))["delivery_work"]


def test_video_processing_resumes_confirmed_upload_without_sleeping_or_consuming_post_attempts(monkeypatch):
    peer, job, _ = queued_media(monkeypatch, "video")
    peer.video_status = "PROCESSING"
    assert worker.tick(now=NOW)["delivery_work"]
    with store.connection() as c:
        waiting = store.get(c, "delivery", job["id"])
        assert store.get(c, "candidate", job["candidate_id"])["status"] == "scheduled"
    assert waiting["status"] == "retry" and waiting["confirmed_not_sent"] is True
    assert waiting["attempts"] == 0 and permissions.timestamp(waiting["next_attempt_at"]) == NOW + timedelta(seconds=60)
    assert not worker.tick(now=NOW + timedelta(seconds=59))["delivery_work"]
    peer.video_status = "AVAILABLE"
    assert worker.tick(now=NOW + timedelta(seconds=60))["delivery_work"]
    assert len(posts(peer)) == 1
    assert len([r for r in peer.calls if r.url.endswith("action=initializeUpload")]) == 1
    assert len([r for r in peer.calls if r.method == "PUT"]) == 2
    assert len([r for r in peer.calls if r.url.endswith("action=finalizeUpload")]) == 1


def test_failed_video_processing_is_recorded_separately_and_never_posts(monkeypatch):
    peer, job, _ = queued_media(monkeypatch, "video")
    peer.video_status = "PROCESSING_FAILED"
    assert worker.tick(now=NOW)["delivery_work"]
    assert not posts(peer)
    with store.connection() as c:
        assert store.get(c, "delivery", job["id"])["status"] == "error"
        assert store.list_items(c, "provider_upload")[0]["status"] == "failed"


def test_lost_finalize_response_reads_the_same_video_before_any_post_or_repeat(monkeypatch):
    peer, job, _ = queued_media(monkeypatch, "video")
    peer.finalize_outcome = requests.Timeout(UPLOAD_SECRET)
    assert worker.tick(now=NOW)["delivery_work"] and not posts(peer)
    peer.finalize_outcome = None
    assert worker.tick(now=NOW + timedelta(seconds=60))["delivery_work"]
    assert len(posts(peer)) == 1
    assert len([r for r in peer.calls if r.url.endswith("action=finalizeUpload")]) == 1


@pytest.mark.parametrize("identity", ["owner", "id"])
def test_video_status_from_a_different_owner_or_video_cannot_authorize_posting(monkeypatch, identity):
    peer, _, _ = queued_media(monkeypatch, "video")
    if identity == "owner":
        peer.video_owner = "urn:li:person:different"
    else:
        peer.video_id = "urn:li:video:different"
    assert worker.tick(now=NOW)["delivery_work"] and not posts(peer)


@pytest.mark.parametrize("problem", ["host", "scheme", "port", "credentials", "path", "expiry", "urn"])
def test_untrusted_image_upload_destination_is_rejected_before_bytes_or_credentials_leave(monkeypatch, problem):
    peer, job, _ = queued_media(monkeypatch)
    def change(value):
        if problem == "expiry":
            value["uploadUrlExpiresAt"] = int(NOW.timestamp() * 1000)
        elif problem == "urn":
            value["image"] = "urn:li:video:wrong"
        else:
            value["uploadUrl"] = {"host": "https://example.test/dms-uploads/image1/uploaded-image/0",
                "scheme": "http://www.linkedin.com/dms-uploads/image1/uploaded-image/0",
                "port": "https://www.linkedin.com:8443/dms-uploads/image1/uploaded-image/0",
                "credentials": "https://secret@www.linkedin.com/dms-uploads/image1/uploaded-image/0",
                "path": "https://www.linkedin.com/oauth/v2/authorization"}[problem]
    peer.change_registration = change
    assert worker.tick(now=NOW)["delivery_work"]
    assert not any(r.method == "PUT" for r in peer.calls) and not posts(peer)
    with store.connection() as c:
        assert store.get(c, "delivery", job["id"])["status"] == "error"


@pytest.mark.parametrize("problem", ["gap", "overlap", "truncated", "reversed", "boolean", "extra"])
def test_video_parts_must_cover_the_whole_file_once_in_order(monkeypatch, problem):
    peer, _, _ = queued_media(monkeypatch, "video")
    def change(value):
        parts = value["uploadInstructions"]
        if problem == "gap":
            parts[1]["firstByte"] += 1
        elif problem == "overlap":
            parts[1]["firstByte"] -= 1
        elif problem == "truncated":
            parts[-1]["lastByte"] -= 1
        elif problem == "reversed":
            parts.reverse()
        elif problem == "boolean":
            parts[0]["firstByte"] = False
        else:
            parts.append(parts[-1])
    peer.change_registration = change
    assert worker.tick(now=NOW)["delivery_work"]
    assert not any(r.method == "PUT" for r in peer.calls) and not posts(peer)


@pytest.mark.parametrize("change", ["pause", "disconnect", "evidence", "file", "asset_revision"])
def test_changes_during_media_upload_prevent_the_post_request(monkeypatch, change):
    from marketing import linkedin_oauth
    peer, job, files = queued_media(monkeypatch)
    def mutate(request):
        if request.method != "PUT":
            return
        if change == "pause":
            delivery.set_pause(OWNER, publications=True)
        elif change == "disconnect":
            with store.connection() as c:
                saved = store.get(c, "account", "li")
            linkedin_oauth.disconnect(OWNER, "li", saved["version"])
        elif change in {"file", "asset_revision"}:
            media.asset_path(files[0]).write_bytes(b"changed after validation")
            if change == "asset_revision":
                with store.connection(write=True) as c:
                    asset = store.get(c, "asset", files[0]["id"])
                    store.put(c, "asset", {**asset, "sha256": hashlib.sha256(b"changed after validation").hexdigest()},
                              actor=OWNER, action="replacement_render", expected_version=asset["version"])
        else:
            with store.connection(write=True) as c:
                original = store.get(c, "evidence", "decision")
                store.put(c, "evidence", {**original, "status": "unavailable"}, actor=OWNER, action="source_withdrawn", expected_version=original["version"])
    peer.before = mutate
    assert worker.tick(now=NOW)["delivery_work"]
    assert not posts(peer)
    with store.connection() as c:
        result = store.get(c, "delivery", job["id"])
    assert result["status"] in {"retry", "blocked"} and result["confirmed_not_sent"] is True


@pytest.mark.parametrize("outcome", [requests.Timeout(UPLOAD_SECRET), (201, "")])
def test_media_post_unknown_receipt_never_replays_completed_upload_or_post(monkeypatch, outcome):
    peer, job, _ = queued_media(monkeypatch, "carousel")
    peer.post_outcome = outcome
    assert worker.tick(now=NOW)["delivery_work"]
    assert not worker.tick(now=NOW + timedelta(hours=1))["delivery_work"]
    assert len(posts(peer)) == 1
    with store.connection() as c:
        assert store.get(c, "delivery", job["id"])["status"] == "unknown"


def test_crash_between_video_parts_resumes_only_after_the_confirmed_part(monkeypatch):
    peer, job, _ = queued_media(monkeypatch, "video")
    class WorkerStopped(BaseException):
        pass
    def crash(request):
        if request.method == "PUT" and urlsplit(request.url).path.endswith("/1"):
            raise WorkerStopped()
    peer.before = crash
    with pytest.raises(WorkerStopped):
        worker.tick(now=NOW)
    peer.before = None
    assert delivery.recover_inflight(NOW + timedelta(seconds=301)) == 1
    with store.connection() as c:
        recovered = store.get(c, "delivery", job["id"])
    assert recovered["status"] == "retry" and recovered["confirmed_not_sent"] is True
    assert worker.tick(now=NOW + timedelta(seconds=301))["delivery_work"]
    parts = [urlsplit(r.url).path.rsplit("/", 1)[-1] for r in peer.calls if r.method == "PUT"]
    assert parts == ["0", "1", "1"] and len(posts(peer)) == 1
    assert len([r for r in peer.calls if r.url.endswith("action=initializeUpload")]) == 1


def test_a_recovered_preparation_claim_fences_the_old_worker_before_upload_or_post(monkeypatch):
    peer, job, _ = queued_media(monkeypatch)
    replacement = []
    def recover(request):
        if request.url.endswith("action=initializeUpload"):
            peer.before = None
            at = NOW + timedelta(seconds=301)
            assert delivery.recover_inflight(at) == 1
            replacement.append(delivery._claim(at, channels.Transport(at)))
    peer.before = recover
    assert worker.tick(now=NOW)["delivery_work"]
    assert replacement[0] and not posts(peer) and not any(r.method == "PUT" for r in peer.calls)
    with store.connection() as c:
        current = store.get(c, "delivery", job["id"])
    assert current["status"] == "sending" and current["claim_token"] == replacement[0][0]["claim_token"]


def test_owner_can_confirm_visible_created_post_but_cannot_revise_or_resend_it(monkeypatch):
    from marketing import visibility
    from marketing.errors import MarketingError
    peer, job, _ = queued_media(monkeypatch)
    worker.tick(now=NOW)
    with store.connection() as c:
        pending = store.get(c, "delivery", job["id"])
        item = store.get(c, "candidate", job["candidate_id"])
        review = visibility.pending(c)[0]
    with pytest.raises(MarketingError):
        content.revise_candidate(OWNER, item["id"], {"body": "Different"}, item["version"])
    with pytest.raises(MarketingError):
        visibility.confirm({"id": "model", "role": "cmo"}, job["id"], pending["version"], review["review_digest"], NOW)
    with pytest.raises(MarketingError):
        visibility.confirm(OWNER, job["id"], pending["version"], "invented", NOW)
    result = visibility.confirm(OWNER, job["id"], pending["version"], review["review_digest"], NOW + timedelta(minutes=1))
    assert result["status"] == "published" and result["visibility_confirmation"]["method"] == "owner_visual_review"
    with pytest.raises(MarketingError):
        visibility.confirm(OWNER, job["id"], pending["version"], review["review_digest"], NOW)
    assert not worker.tick(now=NOW + timedelta(hours=1))["delivery_work"] and len(posts(peer)) == 1
