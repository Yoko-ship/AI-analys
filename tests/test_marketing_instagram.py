"""Instagram uses actual reviewed JPEGs and a single public publish boundary."""
from datetime import timedelta
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import pytest
import requests

import api
from marketing import content, delivery, media, meta_oauth, permissions, store, worker
from marketing.models import Account
from test_marketing_core import OWNER, NOW, candidate, evidence, isolated  # noqa: F401
from test_marketing_facebook import current
from test_marketing_meta import MetaPeer, IG_ID, USER_TOKEN, SECRET, begin, finish, target

MEDIA_ID = "987654321"


class InstagramPeer(MetaPeer):
    def __init__(self, monkeypatch, now=NOW):
        self.containers, self.publishes, self.fetched = {}, [], []
        self.processing, self.receipt, self.publish_outcome = "FINISHED", None, None
        self.quota = {"data": [{"quota_usage": 0, "config": {"quota_total": 100, "quota_duration": 86400}}]}
        self.before_publish, self.after_fetch = None, None
        self.story_ids, self.story_paging = [MEDIA_ID], None
        self.profile = {"id": IG_ID, "website": "https://uzstock.uz/news/decision-123"}
        super().__init__(monkeypatch, now)
        from marketing import public_media
        monkeypatch.setattr(public_media, "now", lambda: self.now + timedelta(seconds=30))

    def send(self, request, **options):
        path = urlsplit(request.url).path
        if path.endswith(("/oauth/access_token", "/debug_token", "/me/accounts")):
            return super().send(request, **options)
        assert options["allow_redirects"] is False and options["timeout"] == (5, 30)
        assert urlsplit(request.url).netloc == "graph.facebook.com" and path.startswith("/v25.0/")
        assert request.headers["Authorization"] == "Bearer " + USER_TOKEN
        values = parse_qs(urlsplit(request.url).query if request.method == "GET" else request.body)
        assert values["appsecret_proof"] == [hmac.new(SECRET.encode(), USER_TOKEN.encode(), hashlib.sha256).hexdigest()]
        self.calls.append(request)
        outcome = None
        if request.method == "GET" and path == f"/v25.0/{IG_ID}":
            assert values["fields"] == ["id,website"]
            result = self.profile
        elif path.endswith("/content_publishing_limit"):
            assert request.method == "GET" and values["fields"] == ["quota_usage,config"]
            result = self.quota
        elif path == f"/v25.0/{IG_ID}/stories":
            assert request.method == "GET" and values["fields"] == ["id"]
            result = {"data": [{"id": key} for key in self.story_ids]}
            if self.story_paging:
                result["paging"] = self.story_paging
        elif request.method == "POST" and path == f"/v25.0/{IG_ID}/media":
            if "image_url" in values or "video_url" in values:
                video = "video_url" in values
                response = TestClient(api.app).get(urlsplit(values["video_url" if video else "image_url"][0]).path)
                assert response.status_code == 200 and response.headers["content-type"] == ("video/mp4" if video else "image/jpeg")
                if video:
                    assert values["media_type"] == ["REELS"] and values["share_to_feed"] == ["false"] and "alt_text" not in values
                if values.get("media_type") == ["STORIES"]:
                    assert "caption" not in values and "alt_text" not in values and "user_tags" not in values
                self.fetched.append(response.content)
                if self.after_fetch:
                    self.after_fetch()
            else:
                assert values["media_type"] == ["CAROUSEL"]
                assert all(key in self.containers for key in values["children"][0].split(","))
            key = str(70001 + len(self.containers))
            self.containers[key] = values
            result = {"id": key}
        elif request.method == "GET" and path.rsplit("/", 1)[-1] in self.containers:
            result = {"id": path.rsplit("/", 1)[-1], "status_code": self.processing}
        elif request.method == "POST" and path == f"/v25.0/{IG_ID}/media_publish":
            key = values["creation_id"][0]
            container = self.containers[key]
            self.publishes.append(values)
            story = container.get("media_type") == ["STORIES"]
            self.receipt = {"id": MEDIA_ID, "owner": {"id": IG_ID}, **({} if story else {"caption": container["caption"][0]}),
                "media_type": "VIDEO" if "video_url" in container else "CAROUSEL_ALBUM" if "children" in container else "IMAGE",
                "media_product_type": "STORY" if story else "REELS" if "video_url" in container else "FEED",
                "timestamp": self.now.isoformat(), "permalink": "https://www.instagram.com/stories/uzstock_test/456789/" if story else
                    "https://www.instagram.com/" + ("reel" if "video_url" in container else "p") + "/Checked_Post/"}
            if "children" in container:
                self.receipt["children"] = {"data": [{"id": str(81000 + i), "media_type": "IMAGE", "alt_text": self.containers[child]["alt_text"][0]}
                    for i, child in enumerate(container["children"][0].split(","))]}
            elif "video_url" not in container and not story:
                self.receipt["alt_text"] = container["alt_text"][0]
            if self.before_publish:
                self.before_publish()
            outcome, result = self.publish_outcome, {"id": MEDIA_ID}
        else:
            assert request.method == "GET" and path == "/v25.0/" + MEDIA_ID
            result = self.receipt
        if isinstance(outcome, Exception):
            raise outcome
        status, body, headers = outcome or (200, result, {})
        response = requests.Response()
        response.status_code, response.headers = status, headers
        response._content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return response


def queued_instagram(monkeypatch, format="image", **changes):
    peer = InstagramPeer(monkeypatch)
    saved = target("instagram")
    selection = finish(begin(saved))
    saved = meta_oauth.select(OWNER, saved["id"], saved["version"], selection["selection_id"], IG_ID, NOW)
    permissions.save_account(OWNER, saved["id"], {**{k: v for k, v in saved.items() if k in Account.model_fields},
        "mode": "automatic", "formats": [format], "languages": [changes.get("language", "ru")], "instagram_link_ready": True}, saved["version"])
    evidence()
    item = candidate(target="instagram", format=format, **changes)
    media.request_candidate(OWNER, item["id"], item["version"])
    assert media.run_one(NOW)
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "ready", checked["check"]["reason"]
    job = delivery.schedule(item["id"], NOW)
    with store.connection() as c:
        files = [store.get(c, "asset", ref["id"]) for ref in checked["assets"]]
    return peer, job, files


@pytest.mark.parametrize("format", ["image", "carousel", "video", "story"])
def test_instagram_exact_media_and_caption_are_accepted_then_independently_confirmed(monkeypatch, format):
    peer, job, files = queued_instagram(monkeypatch, format)
    assert worker.tick(now=NOW)["delivery_work"]
    saved = current(job)
    assert saved["status"] == "submitted" and saved["external_id"] == MEDIA_ID
    assert peer.fetched == [media.read_asset(asset) for asset in files]
    assert len(peer.publishes) == 1
    assert saved["dispatch_payload"]["text"] == peer.receipt.get("caption", "")
    assert saved["dispatch_payload"]["alt_texts"] == ([] if format in {"video", "story"} else [asset["alt_text"] for asset in files])
    parent = peer.containers[peer.publishes[0]["creation_id"][0]]
    assert parent["is_ai_generated"] == ["true"]
    if format == "video":
        assert parent["share_to_feed"] == ["false"]
        assert saved["dispatch_payload"]["share_to_feed"] is False
    if format == "carousel":
        assert len(set(asset["alt_text"] for asset in files)) == len(files)
        assert len(peer.containers) == len(files) + 1
        for value in list(peer.containers.values())[:-1]:
            assert value["is_carousel_item"] == ["true"] and "caption" not in value and "is_ai_generated" not in value
    assert worker.tick(now=NOW + timedelta(seconds=60))["confirmation_work"]
    saved = current(job)
    assert saved["status"] == "published" and saved["published_at"] == NOW.isoformat()
    assert saved["url"] == peer.receipt["permalink"]
    assert saved["visibility_confirmation"]["method"] == "provider_read"
    assert len(peer.publishes) == 1
    if format == "story":
        assert saved["visibility_expires_at"] == (NOW + timedelta(hours=24)).isoformat()


@pytest.mark.parametrize("proof", ["absent", "wrong_surface", "expired", "expired_disconnected"])
def test_story_visibility_requires_current_membership_and_the_story_surface(monkeypatch, proof):
    peer, job, _ = queued_instagram(monkeypatch, "story")
    worker.tick(now=NOW)
    if proof == "absent":
        peer.story_ids = []
    elif proof == "wrong_surface":
        peer.receipt["media_product_type"] = "FEED"
    if proof == "expired_disconnected":
        from marketing import credentials
        with store.connection(write=True) as c:
            credentials.delete(c, "instagram", "meta")
    at = NOW + (timedelta(hours=25) if proof.startswith("expired") else timedelta(seconds=60))
    worker.tick(now=at)
    assert current(job)["status"] == "submitted" and len(peer.publishes) == 1
    if proof.startswith("expired"):
        assert current(job)["confirmation"]["status"] == "expired_unverified"
        assert not worker.tick(now=at + timedelta(hours=1))["confirmation_work"]


def test_story_without_a_permalink_can_be_confirmed_from_its_id_owner_and_active_story_edge(monkeypatch):
    peer, job, _ = queued_instagram(monkeypatch, "story")
    worker.tick(now=NOW)
    peer.receipt.pop("permalink")
    worker.tick(now=NOW + timedelta(seconds=60))
    assert current(job)["status"] == "published" and not current(job).get("url")


def test_story_preview_does_not_promise_an_unsent_caption_or_link_sticker(monkeypatch):
    from marketing import publishing
    _, job, _ = queued_instagram(monkeypatch, "story")
    with store.connection() as c:
        item = store.get(c, "candidate", job["candidate_id"])
        preview = publishing.preview(c, item)
    assert preview["media_only"] is True and preview["text"] == ""


@pytest.mark.parametrize("format", ["carousel", "video"])
def test_processing_resumes_saved_containers_without_refetching_or_consuming_public_attempts(monkeypatch, format):
    peer, job, files = queued_instagram(monkeypatch, format)
    peer.processing = "IN_PROGRESS"
    assert worker.tick(now=NOW)["delivery_work"]
    assert current(job)["status"] == "retry" and current(job)["attempts"] == 0
    assert len(peer.containers) == 1 and not peer.publishes
    peer.processing = "FINISHED"
    peer.now = NOW + timedelta(seconds=61)
    assert worker.tick(now=NOW + timedelta(seconds=61))["delivery_work"]
    assert current(job)["status"] == "submitted" and len(peer.fetched) == len(files)


@pytest.mark.parametrize("outcome", [requests.Timeout("private token"), (503, {}, {}), (200, {}, {}), (200, {"id": True}, {})])
@pytest.mark.parametrize("format", ["image", "video"])
def test_uncertain_instagram_publish_never_replays_or_guesses_a_receipt(monkeypatch, outcome, format):
    peer, job, _ = queued_instagram(monkeypatch, format)
    peer.publish_outcome = outcome
    worker.tick(now=NOW)
    assert current(job)["status"] == "unknown"
    worker.tick(now=NOW + timedelta(hours=1))
    assert current(job)["status"] == "unknown" and len(peer.publishes) == 1


@pytest.mark.parametrize("field,value", [("owner", {"id": "555"}), ("caption", "changed"), ("media_type", "VIDEO"),
    ("alt_text", "different file"), ("timestamp", "2020-01-01T00:00:00Z"), ("permalink", "https://evil.example/p/post/")])
def test_instagram_readback_must_match_owner_caption_media_and_time(monkeypatch, field, value):
    peer, job, _ = queued_instagram(monkeypatch)
    worker.tick(now=NOW)
    peer.receipt[field] = value
    worker.tick(now=NOW + timedelta(seconds=60))
    assert current(job)["status"] == "submitted" and len(peer.publishes) == 1


def test_reordered_carousel_cannot_be_confirmed(monkeypatch):
    peer, job, _ = queued_instagram(monkeypatch, "carousel")
    worker.tick(now=NOW)
    peer.receipt["children"]["data"].reverse()
    worker.tick(now=NOW + timedelta(seconds=60))
    assert current(job)["status"] == "submitted"


@pytest.mark.parametrize("change", [{"media_product_type": "FEED"}, {"media_type": "IMAGE"},
    {"children": {"data": [{"id": "123"}]}}, {"permalink": "https://www.instagram.com/p/Checked_Post/"}])
def test_reel_confirmation_requires_the_reel_surface_and_single_video(monkeypatch, change):
    peer, job, _ = queued_instagram(monkeypatch, "video")
    worker.tick(now=NOW)
    peer.receipt.update(change)
    worker.tick(now=NOW + timedelta(seconds=60))
    assert current(job)["status"] == "submitted" and len(peer.publishes) == 1


def test_provider_reported_quota_blocks_before_creating_any_container(monkeypatch):
    peer, job, _ = queued_instagram(monkeypatch)
    peer.quota["data"][0].update(quota_usage=50, config={"quota_total": 50, "quota_duration": 86400})
    worker.tick(now=NOW)
    assert current(job)["status"] == "retry" and current(job)["attempts"] == 0
    assert not peer.containers and not peer.publishes


def test_withdrawn_permission_after_provider_fetch_prevents_publication(monkeypatch):
    peer, job, _ = queued_instagram(monkeypatch)
    def withdraw():
        with store.connection(write=True) as c:
            account = store.get(c, "account", "instagram")
            store.put(c, "account", {**account, "paused": True}, actor=OWNER, action="test", expected_version=account["version"])
    peer.after_fetch = withdraw
    worker.tick(now=NOW)
    assert current(job)["status"] == "retry" and current(job)["confirmed_not_sent"] and not peer.publishes
    worker.tick(now=NOW + timedelta(hours=1))
    assert not peer.publishes


def test_explicit_rate_rejection_reuses_the_finished_container_after_the_full_delay(monkeypatch):
    peer, job, _ = queued_instagram(monkeypatch)
    peer.publish_outcome = (429, {"error": {"code": 4}}, {"Retry-After": "7200"})
    worker.tick(now=NOW)
    assert current(job)["status"] == "retry"
    assert current(job)["next_attempt_at"] == (NOW + timedelta(seconds=7200)).isoformat()
    assert not worker.tick(now=NOW + timedelta(seconds=7199))["delivery_work"]
    peer.publish_outcome, peer.now = None, NOW + timedelta(seconds=7200)
    worker.tick(now=peer.now)
    assert current(job)["status"] == "submitted" and len(peer.containers) == 1 and len(peer.fetched) == 1
    assert len(peer.publishes) == 2


def test_unpublished_expired_container_is_replaced_but_never_republished(monkeypatch):
    peer, job, _ = queued_instagram(monkeypatch, "carousel")
    peer.processing = "EXPIRED"
    worker.tick(now=NOW)
    assert current(job)["status"] == "retry" and not peer.publishes
    old = set(peer.containers)
    peer.processing, peer.now = "FINISHED", NOW + timedelta(seconds=61)
    worker.tick(now=peer.now)
    assert current(job)["status"] == "submitted"
    assert peer.publishes[0]["creation_id"][0] not in old
    assert len(peer.publishes) == 1


@pytest.mark.parametrize("status", ["PUBLISHED", "ERROR", "UNRECOGNIZED"])
def test_unexpected_container_state_never_triggers_a_public_request(monkeypatch, status):
    peer, job, _ = queued_instagram(monkeypatch)
    peer.processing = status
    worker.tick(now=NOW)
    assert current(job)["status"] == "error" and not peer.publishes


@pytest.mark.parametrize("quota", [{}, {"data": []}, {"data": [{"quota_usage": True, "config": {"quota_total": 100, "quota_duration": 86400}}]}])
def test_missing_or_malformed_quota_keeps_images_private(monkeypatch, quota):
    peer, job, _ = queued_instagram(monkeypatch)
    peer.quota = quota
    worker.tick(now=NOW)
    assert current(job)["status"] == "retry" and not peer.fetched and not peer.publishes
