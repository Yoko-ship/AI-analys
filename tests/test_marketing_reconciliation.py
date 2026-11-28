"""Platform observations can resolve a send; browser assertions cannot create proof."""
from datetime import timedelta
import json

import pytest
import requests

from marketing import channels, content, delivery, media, publishing, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, account, candidate, evidence, isolated  # noqa: F401
from test_marketing_channels import TelegramPeer, fields


class ReceiptPeer(TelegramPeer):
    def __init__(self, monkeypatch):
        super().__init__(monkeypatch, send=requests.Timeout("lost response"))
        self.updates = []
        self.webhook = ""

    def send(self, request, **options):
        method = request.url.rsplit("/", 1)[-1]
        if method in {"getWebhookInfo", "getUpdates"}:
            self.calls.append((method, fields(request), request))
            result = {"url": self.webhook} if method == "getWebhookInfo" else self.updates
            return self.response(200, {"ok": True, "result": result})
        return super().send(request, **options)


def uncertain(monkeypatch, format="post"):
    peer = ReceiptPeer(monkeypatch)
    saved = account(formats=["post", "image", "carousel", "video"])
    channels.probe(OWNER, "tg", saved["version"], NOW)
    evidence()
    item = candidate(format=format)
    if format != "post":
        media.request_candidate(OWNER, item["id"], item["version"])
        media.run_one(NOW)
    assert content.check_candidate(item["id"], NOW)["status"] == "ready"
    job = delivery.schedule(item["id"], NOW)
    assert delivery.run_one(channels.Transport(NOW), NOW)
    with store.connection() as c:
        job = store.get(c, "delivery", job["id"])
        item = store.get(c, "candidate", item["id"])
        copy = publishing.preview(c, item)["text"]
    assert job["status"] == "unknown"
    return peer, job, item, copy


def observation(copy, *, forwarded=False, message_id=81, update_id=100, format="post", album=None):
    message = {"message_id": message_id, "date": int(NOW.timestamp()),
               "chat": {"id": -100123, "type": "channel", "username": "marketing_test"}}
    message["text" if format == "post" else "caption"] = copy
    if format in {"image", "carousel"}:
        message["photo"] = [{"file_id": "photo-id", "file_unique_id": "photo-unique", "width": 1080, "height": 1350}]
    if format == "video":
        message["video"] = {"file_id": "video-id", "file_unique_id": "video-unique", "width": 1080, "height": 1350, "duration": 6}
    if album:
        message["media_group_id"] = album
    if forwarded:
        message["forward_origin"] = {"type": "channel", "chat": message["chat"], "message_id": message_id, "date": message["date"]}
        message.update(chat={"id": 555, "type": "private"}, message_id=999, date=int((NOW + timedelta(days=2)).timestamp()),
                       **{"from": {"id": 555, "first_name": "Private person"}})
    return {"update_id": update_id, "message" if forwarded else "channel_post": message}


def match(job):
    from marketing import reconciliation
    with store.connection() as c:
        return next(row for row in reconciliation.cases(c) if row["delivery_id"] == job["id"])


@pytest.mark.parametrize("forwarded", [False, True])
def test_exact_platform_observation_requires_owner_confirmation_then_never_resends(monkeypatch, forwarded):
    from marketing import reconciliation
    peer, job, item, copy = uncertain(monkeypatch)
    assert job["dispatch_payload"] == {"text": copy, "format": "post", "media_count": 0}
    peer.updates = [observation(copy, forwarded=forwarded)]
    result = reconciliation.poll(OWNER, NOW + timedelta(days=2) if forwarded else NOW)
    assert result["received"] == 1
    found = match(job)
    assert found["status"] == "matched" and found["external_ids"] == ["81"]
    with store.connection() as c:
        assert store.get(c, "delivery", job["id"])["status"] == "unknown"
        private_data = json.dumps(store.list_items(c, "telegram_receipt"))
        assert "Private person" not in private_data and '"555"' not in private_data
    with pytest.raises(MarketingError):
        reconciliation.confirm({"id": "quality", "role": "quality"}, job["id"], job["version"], found["match_digest"], NOW)
    published = reconciliation.confirm(OWNER, job["id"], job["version"], found["match_digest"], NOW + timedelta(days=2))
    assert published["status"] == "published" and published["url"] == "https://t.me/marketing_test/81"
    assert not delivery.run_one(channels.Transport(NOW), NOW)
    with store.connection() as c:
        assert store.get(c, "candidate", item["id"])["status"] == "published"
        assert store.list_items(c, "publication_watch")
        assert store.history(c, "delivery", job["id"])[-1]["actor"] == OWNER
    assert len([method for method, _, _ in peer.calls if method.startswith("send")]) == 1


@pytest.mark.parametrize("problem", ["text", "channel", "date", "future", "format", "ordinary_message", "duplicate_matches"])
def test_nonmatching_or_ambiguous_observations_cannot_mark_a_release_published(monkeypatch, problem):
    from marketing import reconciliation
    peer, job, _, copy = uncertain(monkeypatch)
    update = observation(copy)
    message = update["channel_post"]
    if problem == "text":
        message["text"] += " changed"
    elif problem == "channel":
        message["chat"]["id"] = -100999
    elif problem == "date":
        message["date"] -= 3600
    elif problem == "future":
        message["date"] += 3600
    elif problem == "format":
        message["photo"] = [{"file_unique_id": "other"}]
    elif problem == "ordinary_message":
        update = {"update_id": 100, "message": {**message, "chat": {"id": 555, "type": "private"}}}
    peer.updates = [update]
    if problem == "duplicate_matches":
        peer.updates.append(observation(copy, message_id=82, update_id=101))
    reconciliation.poll(OWNER, NOW + timedelta(hours=2))
    assert match(job)["status"] != "matched"
    with pytest.raises(MarketingError):
        reconciliation.confirm(OWNER, job["id"], job["version"], "browser-made-up-proof", NOW)
    with store.connection() as c:
        assert store.get(c, "delivery", job["id"])["status"] == "unknown"


@pytest.mark.parametrize("format", ["image", "video", "carousel"])
def test_media_requires_the_complete_platform_bundle_and_exact_caption(monkeypatch, format):
    from marketing import reconciliation
    peer, job, item, copy = uncertain(monkeypatch, format)
    peer.updates = [observation(copy, format=format, album="album-one" if format == "carousel" else None)]
    reconciliation.poll(OWNER, NOW)
    if format == "carousel":
        assert match(job)["status"] == "incomplete_media"
        peer.updates = [observation("", format=format, album="album-one", message_id=81 + i, update_id=100 + i)
                        for i in range(1, len(item["assets"]))]
        reconciliation.poll(OWNER, NOW + timedelta(seconds=5))
    found = match(job)
    assert found["status"] == "matched" and len(found["external_ids"]) == len(item["assets"])
    confirmed = reconciliation.confirm(OWNER, job["id"], job["version"], found["match_digest"], NOW)
    assert confirmed["status"] == "published"


def test_cursor_only_acknowledges_saved_updates_and_active_webhook_is_never_removed(monkeypatch):
    from marketing import reconciliation
    peer, job, _, copy = uncertain(monkeypatch)
    peer.webhook = "https://example.org/private-webhook"
    with pytest.raises(MarketingError, match="webhook"):
        reconciliation.poll(OWNER, NOW)
    assert not any(method in {"getUpdates", "deleteWebhook"} for method, _, _ in peer.calls)
    peer.webhook = ""
    peer.updates = [observation(copy)]
    reconciliation.poll(OWNER, NOW + timedelta(seconds=5))
    reconciliation.poll(OWNER, NOW + timedelta(seconds=10))
    calls = [data for method, data, _ in peer.calls if method == "getUpdates"]
    assert int(calls[0].get("offset", 0)) == 0 and int(calls[1]["offset"]) == 101
    with store.connection() as c:
        assert len(store.list_items(c, "telegram_receipt")) == 1
    assert match(job)["status"] == "matched"


def test_edited_observation_invalidates_a_previously_offered_match(monkeypatch):
    from marketing import reconciliation
    peer, job, _, copy = uncertain(monkeypatch)
    peer.updates = [observation(copy)]
    reconciliation.poll(OWNER, NOW)
    found = match(job)
    changed = observation(copy + " edited", update_id=101)
    peer.updates = [{"update_id": 101, "edited_channel_post": changed["channel_post"]}]
    reconciliation.poll(OWNER, NOW + timedelta(seconds=5))
    with pytest.raises(MarketingError):
        reconciliation.confirm(OWNER, job["id"], job["version"], found["match_digest"], NOW)


def test_one_observed_post_cannot_confirm_two_identical_pending_candidates(monkeypatch):
    from marketing import reconciliation
    peer, job, _, copy = uncertain(monkeypatch)
    second = candidate("separate-event-with-identical-copy")
    content.check_candidate(second["id"], NOW)
    delivery.schedule(second["id"], NOW)
    with store.connection(write=True) as c:
        row = store.get(c, "delivery", second["id"])
        store.put(c, "delivery", {**row, "status": "unknown", "claimed_at": NOW.isoformat(), "attempts": 1}, actor=OWNER, action="ambiguous_peer_fixture", expected_version=row["version"])
        row = store.get(c, "candidate", second["id"])
        store.put(c, "candidate", {**row, "status": "unknown"}, actor=OWNER, action="ambiguous_peer_fixture", expected_version=row["version"])
    peer.updates = [observation(copy)]
    reconciliation.poll(OWNER, NOW)
    assert match(job)["status"] == "ambiguous"


def test_changed_source_after_send_does_not_rewrite_the_original_reconciliation_basis(monkeypatch):
    from marketing import reconciliation
    from test_marketing_incidents import amend
    peer, job, _, copy = uncertain(monkeypatch)
    amend(99)
    peer.updates = [observation(copy)]
    reconciliation.poll(OWNER, NOW)
    found = match(job)
    assert found["status"] == "matched"
    confirmed = reconciliation.confirm(OWNER, job["id"], job["version"], found["match_digest"], NOW)
    assert confirmed["status"] == "published"
    from marketing import incidents
    incidents.scan(NOW)
    with store.connection() as c:
        assert store.list_items(c, "incident")[0]["status"] == "open"


def test_late_transport_failure_cannot_overwrite_owner_confirmed_reconciliation(monkeypatch):
    from marketing import reconciliation
    peer = ReceiptPeer(monkeypatch)
    saved = account()
    channels.probe(OWNER, "tg", saved["version"], NOW)
    evidence()
    item = candidate()
    content.check_candidate(item["id"], NOW)
    job = delivery.schedule(item["id"], NOW)
    class LateReply:
        def publish(self, account, item, key):
            assert delivery.recover_inflight(NOW + timedelta(minutes=10)) == 1
            with store.connection() as c:
                copy = publishing.preview(c, store.get(c, "candidate", item["id"]))["text"]
                unknown = store.get(c, "delivery", key)
            peer.updates = [observation(copy)]
            reconciliation.poll(OWNER, NOW + timedelta(minutes=10))
            found = match(job)
            reconciliation.confirm(OWNER, key, unknown["version"], found["match_digest"], NOW + timedelta(minutes=10))
            raise TimeoutError("late lost reply")
    assert delivery.run_one(LateReply(), NOW)
    with store.connection() as c:
        assert store.get(c, "delivery", job["id"])["status"] == "published"
        assert store.get(c, "candidate", job["id"])["status"] == "published"


def test_complete_album_and_another_matching_partial_album_remain_ambiguous(monkeypatch):
    from marketing import reconciliation
    peer, job, item, copy = uncertain(monkeypatch, "carousel")
    peer.updates = [observation(copy if i == 0 else "", format="carousel", album="complete", message_id=81+i, update_id=100+i)
                    for i in range(len(item["assets"]))]
    peer.updates.append(observation(copy, format="carousel", album="partial", message_id=90, update_id=110))
    reconciliation.poll(OWNER, NOW)
    assert match(job)["status"] == "ambiguous"


def test_saved_update_cursor_does_not_advance_if_receipt_storage_fails(monkeypatch):
    from marketing import reconciliation
    peer, job, _, copy = uncertain(monkeypatch)
    peer.updates = [observation(copy)]
    original = store.put
    def failed_put(c, kind, *args, **kwargs):
        if kind == "telegram_receipt":
            raise OSError("storage fixture failure")
        return original(c, kind, *args, **kwargs)
    with monkeypatch.context() as broken:
        broken.setattr(store, "put", failed_put)
        with pytest.raises(MarketingError):
            reconciliation.poll(OWNER, NOW)
    with store.connection() as c:
        assert store.get(c, "settings", "telegram_updates")["cursor"] == 0
        assert store.list_items(c, "telegram_receipt") == []
    reconciliation.poll(OWNER, NOW + timedelta(seconds=5))
    assert match(job)["status"] == "matched"


@pytest.mark.parametrize("problem", ["not_list", "bad_id", "duplicate_id"])
def test_invalid_provider_batch_does_not_create_proof_or_acknowledge_updates(monkeypatch, problem):
    from marketing import reconciliation
    peer, job, _, copy = uncertain(monkeypatch)
    peer.updates = "invalid" if problem == "not_list" else [observation(copy, update_id=True)] if problem == "bad_id" else [observation(copy), observation(copy, message_id=82)]
    with pytest.raises(MarketingError):
        reconciliation.poll(OWNER, NOW)
    with store.connection() as c:
        assert store.get(c, "settings", "telegram_updates")["cursor"] == 0
        assert store.list_items(c, "telegram_receipt") == []
    assert match(job)["status"] == "no_confirmation"


def test_poll_credential_rotation_discards_uncommitted_observations(monkeypatch):
    from marketing import reconciliation
    peer, job, _, copy = uncertain(monkeypatch)
    peer.updates = [observation(copy)]
    original = peer.send
    def rotated(session, request, **options):
        response = original(request, **options)
        if request.url.endswith("/getUpdates"):
            monkeypatch.setenv("MARKETING_TELEGRAM_BOT_TOKEN", "rotated")
        return response
    monkeypatch.setattr(requests.Session, "send", rotated)
    with pytest.raises(MarketingError):
        reconciliation.poll(OWNER, NOW)
    assert match(job)["status"] == "no_confirmation"
