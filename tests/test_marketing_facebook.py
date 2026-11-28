"""Facebook Page posts: exact media, durable preparation and independent reads."""
from datetime import timedelta
from email.parser import BytesParser
from email.policy import default
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from marketing import content, delivery, media, meta_oauth, permissions, publishing, store, visibility, worker
from marketing.models import Account
from test_marketing_core import OWNER, NOW, candidate, evidence, isolated  # noqa: F401
from test_marketing_meta import MetaPeer, PAGE_ID, PAGE_TOKEN, SECRET, USER_TOKEN, begin, finish, target

POST_ID = PAGE_ID + "_78901"


class FacebookPeer(MetaPeer):
    def __init__(self, monkeypatch, now=NOW):
        self.uploads, self.posts, self.receipt = [], [], None
        self.upload_outcome, self.post_outcome, self.read_outcome = None, None, None
        self.before_publish, self.before_read = None, None
        super().__init__(monkeypatch, now)

    def send(self, request, **options):
        path = urlsplit(request.url).path
        if path.endswith(("/oauth/access_token", "/debug_token", "/me/accounts")):
            return super().send(request, **options)
        assert options["allow_redirects"] is False and options["timeout"] == (5, 30)
        assert urlsplit(request.url).netloc == "graph.facebook.com" and path.startswith("/v25.0/")
        assert request.headers["Authorization"] == "Bearer " + PAGE_TOKEN
        query = parse_qs(urlsplit(request.url).query)
        self.calls.append(request)
        if request.method == "GET":
            assert path == "/v25.0/" + POST_ID
            assert {"id", "from", "message", "is_published", "is_hidden", "created_time"} <= set(query["fields"][0].split(","))
            values, outcome, result = query, self.read_outcome, self.receipt
            if self.before_read:
                self.before_read()
        elif path.endswith("/photos"):
            assert request.method == "POST" and path == f"/v25.0/{PAGE_ID}/photos"
            message = BytesParser(policy=default).parsebytes(
                ("Content-Type: " + request.headers["Content-Type"] + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + request.body)
            parts = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True) for part in message.iter_parts()}
            values = {key: [value.decode()] for key, value in parts.items() if key != "source"}
            assert values["published"] == ["false"] and "message" not in values
            self.uploads.append(parts)
            outcome, result = self.upload_outcome, {"id": str(90000 + len(self.uploads))}
        else:
            assert request.method == "POST" and path == f"/v25.0/{PAGE_ID}/feed"
            values = parse_qs(request.body)
            assert values["published"] == ["true"]
            media_ids = [row["media_fbid"] for row in json.loads(values.get("attached_media", ["[]"])[0])]
            self.posts.append(values)
            self.receipt = {"id": POST_ID, "from": {"id": PAGE_ID}, "message": values["message"][0],
                            "is_published": True, "is_hidden": False, "created_time": self.now.isoformat()}
            if media_ids:
                children = [{"media_type": "photo", "target": {"id": identifier}} for identifier in media_ids]
                self.receipt["attachments"] = {"data": children if len(children) == 1 else [
                    {"media_type": "album", "subattachments": {"data": children}}]}
            if self.before_publish:
                self.before_publish()
            outcome, result = self.post_outcome, {"id": POST_ID}
        assert values["appsecret_proof"] == [hmac.new(SECRET.encode(), PAGE_TOKEN.encode(), hashlib.sha256).hexdigest()]
        if isinstance(outcome, Exception):
            raise outcome
        status, body, headers = outcome or (200, result, {})
        response = requests.Response()
        response.status_code, response.headers = status, headers
        response._content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return response


def queued(monkeypatch, format="post", *, peer_class=FacebookPeer):
    peer = peer_class(monkeypatch)
    saved = target()
    selection = finish(begin(saved))
    saved = meta_oauth.select(OWNER, saved["id"], saved["version"], selection["selection_id"], PAGE_ID, NOW)
    permissions.save_account(OWNER, saved["id"], {**{k: v for k, v in saved.items() if k in Account.model_fields},
        "mode": "automatic", "formats": ["post", "image", "carousel", "video", "story"]}, saved["version"])
    evidence()
    item = candidate(target="facebook", format=format)
    if format != "post":
        media.request_candidate(OWNER, item["id"], item["version"])
        assert media.run_one(NOW)
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "ready", checked["check"]["reason"]
    job = delivery.schedule(item["id"], NOW)
    with store.connection() as c:
        files = [store.get(c, "asset", ref["id"]) for ref in checked["assets"]]
    return peer, job, files


def current(job):
    with store.connection() as c:
        return store.get(c, "delivery", job["id"])


@pytest.mark.parametrize("format", ["post", "image", "carousel"])
def test_facebook_exact_post_is_accepted_then_confirmed_by_an_independent_read(monkeypatch, format):
    peer, job, files = queued(monkeypatch, format)
    assert worker.tick(now=NOW)["delivery_work"]
    saved = current(job)
    assert saved["status"] == "submitted" and saved["external_id"] == POST_ID
    assert saved["url"] == f"https://www.facebook.com/{PAGE_ID}/posts/78901/"
    assert len(peer.posts) == 1 and len(peer.uploads) == len(files)
    assert [row["source"] for row in peer.uploads] == [media.read_asset(asset) for asset in files]
    assert [row["alt_text_custom"].decode() for row in peer.uploads] == [asset["alt_text"] for asset in files]
    assert saved["dispatch_payload"]["text"] == peer.posts[0]["message"][0]
    assert saved["dispatch_payload"]["media_ids"] == [str(90001 + i) for i in range(len(files))]
    with store.connection() as c:
        assert visibility.pending(c) == []
        public = json.dumps([saved, store.list_items(c, "provider_upload"), store.history(c, "delivery", job["id"])])
    for secret in [SECRET, PAGE_TOKEN, USER_TOKEN]:
        assert secret not in public
    result = worker.tick(now=NOW + timedelta(seconds=60))
    assert result["confirmation_work"] and not result["delivery_work"]
    confirmed = current(job)
    assert confirmed["status"] == "published" and confirmed["published_at"] == NOW.isoformat()
    assert confirmed["visibility_confirmation"]["method"] == "provider_read"
    assert len(peer.posts) == 1
    assert not worker.tick(now=NOW + timedelta(hours=1))["delivery_work"]


@pytest.mark.parametrize("outcome", [requests.Timeout("private-token"), (503, {"error": {"code": 2}}, {}),
    (200, {}, {}), (200, {"id": "99999_78901"}, {}), (302, {}, {"Location": "https://evil.example"})])
def test_facebook_uncertain_public_write_never_replays(monkeypatch, outcome):
    peer, job, _ = queued(monkeypatch)
    peer.post_outcome = outcome
    assert worker.tick(now=NOW)["delivery_work"]
    assert current(job)["status"] == "unknown"
    assert not worker.tick(now=NOW + timedelta(hours=1))["delivery_work"]
    assert len(peer.posts) == 1


@pytest.mark.parametrize("code", [4, 17, 32, 613, 80001])
def test_explicit_meta_rate_rejection_observes_full_provider_delay(monkeypatch, code):
    peer, job, _ = queued(monkeypatch)
    peer.post_outcome = (400, {"error": {"code": code}}, {"Retry-After": "3661", "x-business-use-case-usage":
        json.dumps({PAGE_ID: [{"type": "pages", "estimated_time_to_regain_access": 70}]})})
    worker.tick(now=NOW)
    saved = current(job)
    assert saved["status"] == "retry"
    assert permissions.timestamp(saved["next_attempt_at"]) == NOW + timedelta(minutes=70)
    assert not worker.tick(now=NOW + timedelta(minutes=69))["delivery_work"]
    peer.post_outcome = None
    assert worker.tick(now=NOW + timedelta(minutes=70))["delivery_work"]
    assert current(job)["status"] == "submitted" and len(peer.posts) == 2


def test_photo_preparation_resumes_saved_images_after_an_interruption(monkeypatch):
    peer, job, _ = queued(monkeypatch, "carousel")
    original = peer.send
    def interrupt(_session, request, **options):
        if request.url.endswith("/photos") and len(peer.uploads) == 1:
            raise requests.Timeout("lost second upload")
        return original(request, **options)
    monkeypatch.setattr(requests.Session, "send", interrupt)
    worker.tick(now=NOW)
    assert current(job)["status"] == "retry" and current(job)["confirmed_not_sent"] is True
    assert not peer.posts and len(peer.uploads) == 1
    monkeypatch.setattr(requests.Session, "send", peer.send)
    worker.tick(now=NOW + timedelta(seconds=60))
    assert len(peer.uploads) == 2 and len(peer.posts) == 1
    assert current(job)["status"] == "submitted"


def test_repeated_provider_photo_id_cannot_replace_a_carousel_slide(monkeypatch):
    peer, job, _ = queued(monkeypatch, "carousel")
    peer.upload_outcome = (200, {"id": "90001"}, {})
    worker.tick(now=NOW)
    assert current(job)["status"] == "error" and not peer.posts


@pytest.mark.parametrize("change", ["permissions", "disconnect", "page-rights", "file"])
def test_changed_permissions_identity_or_file_stop_after_preparation_before_public_write(monkeypatch, change):
    peer, job, files = queued(monkeypatch, "image")
    original = peer.send
    def changed(_session, request, **options):
        response = original(request, **options)
        if urlsplit(request.url).path.endswith("/photos"):
            with store.connection() as c:
                account = store.get(c, "account", "facebook")
            if change == "permissions":
                permissions.save_account(OWNER, "facebook", {**{k: v for k, v in account.items() if k in Account.model_fields},
                    "mode": "draft"}, account["version"])
            elif change == "disconnect":
                meta_oauth.disconnect(OWNER, "facebook", account["version"])
            elif change == "page-rights":
                peer.pages[1]["tasks"] = ["ANALYZE"]
            else:
                media.asset_path(files[0]).write_bytes(b"changed-file")
        return response
    monkeypatch.setattr(requests.Session, "send", changed)
    worker.tick(now=NOW)
    saved = current(job)
    assert saved["status"] in {"retry", "blocked"} and saved["confirmed_not_sent"] is True
    assert len(peer.uploads) == 1 and not peer.posts


@pytest.mark.parametrize("change", ["hidden", "unpublished", "page", "text", "photo", "order", "partial", "extra", "time", "network"])
def test_meta_confirmation_requires_exact_visible_page_copy_and_complete_ordered_media(monkeypatch, change):
    peer, job, _ = queued(monkeypatch, "carousel")
    worker.tick(now=NOW)
    receipt = peer.receipt
    assert receipt is not None
    children = receipt["attachments"]["data"][0]["subattachments"]["data"]
    if change == "hidden":
        receipt["is_hidden"] = True
    elif change == "unpublished":
        receipt["is_published"] = False
    elif change == "page":
        receipt["from"]["id"] = "99999"
    elif change == "text":
        receipt["message"] += " unapproved"
    elif change == "photo":
        children[0]["target"]["id"] = "99999"
    elif change == "order":
        children.reverse()
    elif change == "partial":
        receipt["attachments"]["data"][0]["subattachments"]["paging"] = {"next": "https://evil.example/private"}
    elif change == "extra":
        children.append(children[0])
    elif change == "time":
        receipt["created_time"] = (NOW - timedelta(days=1)).isoformat()
    else:
        peer.read_outcome = requests.Timeout("private-token")
    assert worker.tick(now=NOW + timedelta(seconds=60))["confirmation_work"]
    assert current(job)["status"] == "submitted" and len(peer.posts) == 1
    assert not worker.tick(now=NOW + timedelta(seconds=61))["confirmation_work"]


def test_confirmation_can_finish_while_publications_are_paused(monkeypatch):
    peer, job, _ = queued(monkeypatch)
    worker.tick(now=NOW)
    with store.connection(write=True) as c:
        store.put(c, "settings", {"id": "pause", "publications": True}, actor=OWNER, action="pause", expected_version=0)
    assert worker.tick(now=NOW + timedelta(seconds=60))["confirmation_work"]
    assert current(job)["status"] == "published" and len(peer.posts) == 1


def test_late_confirmation_cannot_overwrite_a_concurrent_delivery_change(monkeypatch):
    peer, job, _ = queued(monkeypatch)
    worker.tick(now=NOW)
    def changed():
        with store.connection(write=True) as c:
            saved = store.get(c, "delivery", job["id"])
            store.put(c, "delivery", {**saved, "reason": "review changed"}, actor=OWNER, action="review", expected_version=saved["version"])
    peer.before_read = changed
    assert worker.tick(now=NOW + timedelta(seconds=60))["confirmation_work"]
    assert current(job)["status"] == "submitted" and current(job)["reason"] == "review changed"


@pytest.mark.parametrize("group_type", ["album", "multiple"])
def test_photo_groups_use_the_attachment_type_and_preserve_child_order(monkeypatch, group_type):
    peer, job, _ = queued(monkeypatch, "carousel")
    worker.tick(now=NOW)
    # StoryAttachment.type describes the group, independently of media_type.
    group = peer.receipt["attachments"]["data"][0]
    group.update(type=group_type, media_type="photo")
    worker.tick(now=NOW + timedelta(seconds=60))
    assert current(job)["status"] == "published" and len(peer.posts) == 1


@pytest.mark.parametrize("text", ["@[12345]", "x" * 63207], ids=["mention-syntax", "long-copy"])
def test_facebook_plain_copy_is_checked_before_any_upload(monkeypatch, text):
    peer, job, _ = queued(monkeypatch)
    with store.connection() as c:
        item = store.get(c, "candidate", job["candidate_id"])
        account = store.get(c, "account", "facebook")
    assert publishing.check(account, {**item, "body": text}, {})
    assert not peer.posts
