"""Exercise real request serialization with a local, non-network Telegram peer."""
from datetime import timedelta
from email import policy
from email.parser import BytesParser
import json
from urllib.parse import parse_qs

import pytest
import requests

from marketing import content, delivery, permissions, store, worker
from test_marketing_core import OWNER, NOW, account, candidate, evidence, isolated  # noqa: F401

TOKEN = "123456:TEST_ONLY_abcdefghijklmnopqrstuvwxyz"


def fields(request):
    if request.headers.get("Content-Type", "").startswith("multipart/"):
        message = BytesParser(policy=policy.default).parsebytes(b"Content-Type: " + request.headers["Content-Type"].encode() + b"\r\n\r\n" + request.body)
        return {part.get_param("name", header="content-disposition"): part.get_payload(decode=True) for part in message.iter_parts()}
    return {key: value[0] for key, value in parse_qs(request.body).items()}


class TelegramPeer:
    def __init__(self, monkeypatch, *, send=None, member=None, chat=None):
        self.calls = []
        self.outcome = send
        self.member = member or {"status": "administrator", "user": {"id": 123456}, "can_post_messages": True}
        self.chat = chat or {"id": -100123, "type": "channel", "title": "Test channel", "username": "marketing_test"}
        monkeypatch.setenv("MARKETING_TELEGRAM_BOT_TOKEN", TOKEN)
        monkeypatch.setattr(requests.Session, "send", self.send)

    def send(self, request, **options):
        assert request.url.startswith("https://api.telegram.org/bot" + TOKEN + "/")
        assert options.get("allow_redirects") is False
        self.calls.append((request.url.rsplit("/", 1)[-1], fields(request), request))
        method = self.calls[-1][0]
        if method == "getMe":
            result = {"id": 123456, "is_bot": True, "username": "marketing_test_bot"}
        elif method == "getChat":
            result = self.chat
        elif method == "getChatMember":
            result = self.member
        else:
            if isinstance(self.outcome, Exception):
                raise self.outcome
            if self.outcome is not None:
                status, payload = self.outcome
                return self.response(status, payload)
            message = {"message_id": 81, "chat": self.chat}
            if method == "sendMediaGroup":
                media = json.loads(self.calls[-1][1]["media"])
                result = [{**message, "message_id": 81 + i, "media_group_id": "album-1"} for i in range(len(media))]
            else:
                result = message
        return self.response(200, {"ok": True, "result": result})

    @staticmethod
    def response(status, payload):
        response = requests.Response()
        response.status_code = status
        response._content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        response.headers["Content-Type"] = "application/json"
        return response


def connected(monkeypatch, **peer_options):
    from marketing import channels
    peer = TelegramPeer(monkeypatch, **peer_options)
    saved = account(formats=["post", "image", "carousel", "video", "story"])
    proof = channels.probe(OWNER, saved["id"], saved["version"], NOW)
    assert proof["connection_status"] == "connected"
    return peer, proof


def queued(**changes):
    evidence()
    item = candidate(**changes)
    assert content.check_candidate(item["id"], NOW)["status"] == "ready"
    return delivery.schedule(item["id"], NOW)


def test_setup_requires_dedicated_credentials_without_reusing_the_existing_bot(monkeypatch):
    from marketing import channels
    monkeypatch.delenv("MARKETING_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_TOKEN", "unrelated-private-bot")
    saved = account()
    state = channels.setup(saved)
    assert state["implemented"] is True and state["configured"] is False and state["ready"] is False
    assert "unrelated-private-bot" not in json.dumps(state)
    with pytest.raises(Exception, match="configured"):
        channels.probe(OWNER, saved["id"], saved["version"], NOW)


@pytest.mark.parametrize("bad", ["private", "wrong_chat", "no_right", "string_right", "wrong_bot"])
def test_probe_checks_numeric_channel_identity_and_actual_bot_rights(monkeypatch, bad):
    from marketing import channels
    peer = TelegramPeer(monkeypatch)
    if bad == "private":
        peer.chat["type"] = "private"
    elif bad == "wrong_chat":
        peer.chat["id"] = -100456
    elif bad == "no_right":
        peer.member["can_post_messages"] = False
    elif bad == "string_right":
        peer.member["can_post_messages"] = "true"
    else:
        peer.member["user"]["id"] = 765432
    saved = account()
    result = channels.probe(OWNER, saved["id"], saved["version"], NOW)
    assert result["connection_status"] == "error"
    assert all(method.startswith("get") for method, _, _ in peer.calls)
    assert TOKEN not in json.dumps(result)


def test_worker_uses_the_configured_adapter_and_saves_confirmed_message_identity(monkeypatch):
    peer, saved = connected(monkeypatch)
    job = queued()
    assert worker.tick(now=NOW)["delivery_work"]
    assert not worker.tick(now=NOW + timedelta(minutes=1))["delivery_work"]
    sent = [value for value in peer.calls if value[0] == "sendMessage"]
    assert len(sent) == 1
    assert sent[0][1]["chat_id"] == saved["external_id"]
    assert "120" in sent[0][1]["text"] and "https://openinfo.uz/facts/123" in sent[0][1]["text"]
    assert "https://uzstock.uz/news/decision-123" in sent[0][1]["text"]
    assert "parse_mode" not in sent[0][1] and "allow_paid_broadcast" not in sent[0][1]
    with store.connection() as c:
        published = store.get(c, "delivery", job["id"])
        assert published["status"] == "published" and published["external_id"] == "81"
        assert published["external_ids"] == ["81"] and published["url"] == "https://t.me/marketing_test/81"
        assert TOKEN not in json.dumps(store.history(c, "account", saved["id"]))


def test_rotating_a_token_invalidates_the_probe_without_consuming_a_send(monkeypatch):
    from marketing import channels
    peer, saved = connected(monkeypatch)
    job = queued()
    monkeypatch.setenv("MARKETING_TELEGRAM_BOT_TOKEN", TOKEN + "rotated")
    assert channels.setup(saved)["ready"] is False
    assert not worker.tick(now=NOW)["delivery_work"]
    assert all(method.startswith("get") for method, _, _ in peer.calls)
    with store.connection() as c:
        assert store.get(c, "delivery", job["id"])["attempts"] == 0


@pytest.mark.parametrize("outcome", [requests.Timeout("secret:" + TOKEN), (502, b"upstream unavailable"), (200, b"not json"),
    (200, {"ok": True, "result": {"message_id": 81, "chat": {"id": -100456}}})])
def test_ambiguous_acceptance_or_wrong_receipt_stays_unknown_without_replay(monkeypatch, outcome):
    peer, _ = connected(monkeypatch, send=outcome)
    job = queued()
    assert worker.tick(now=NOW)["delivery_work"]
    assert not worker.tick(now=NOW + timedelta(hours=1))["delivery_work"]
    assert len([call for call in peer.calls if call[0].startswith("send")]) == 1
    with store.connection() as c:
        result = store.get(c, "delivery", job["id"])
        assert result["status"] == "unknown" and TOKEN not in json.dumps(result)


@pytest.mark.parametrize("delay", [73, 172800])
def test_explicit_flood_rejection_respects_provider_delay_without_sleeping(monkeypatch, delay):
    peer, _ = connected(monkeypatch, send=(429, {"ok": False, "error_code": 429, "parameters": {"retry_after": delay}}))
    job = queued()
    assert worker.tick(now=NOW)["delivery_work"]
    with store.connection() as c:
        result = store.get(c, "delivery", job["id"])
        assert result["status"] == "retry" and permissions.timestamp(result["next_attempt_at"]) == NOW + timedelta(seconds=delay)
    assert not worker.tick(now=NOW + timedelta(seconds=delay - 1))["delivery_work"]
    peer.outcome = None
    worked = worker.tick(now=NOW + timedelta(seconds=max(1800, delay)))["delivery_work"]
    assert worked is (delay == 73)  # A two-day delay outlives this original's validity.


@pytest.mark.parametrize("format,method", [("image", "sendPhoto"), ("carousel", "sendMediaGroup"), ("video", "sendVideo")])
def test_real_rendered_media_is_uploaded_in_one_request_with_all_confirmed_ids(monkeypatch, format, method):
    from marketing import media
    peer, _ = connected(monkeypatch)
    evidence()
    item = candidate(format=format)
    media.request_candidate(OWNER, item["id"], item["version"])
    assert media.run_one(NOW)
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "ready", checked["check"]
    delivery.schedule(item["id"], NOW)
    assert worker.tick(now=NOW)["delivery_work"]
    sends = [call for call in peer.calls if call[0].startswith("send")]
    assert len(sends) == 1 and sends[0][0] == method
    assert b"https://uzstock.uz/news/decision-123" in sends[0][2].body
    with store.connection() as c:
        job = store.get(c, "delivery", item["id"])
        assert job["status"] == "published" and len(job["external_ids"]) == len(checked["assets"])


def test_final_check_includes_actual_telegram_payload_size_and_supported_format(monkeypatch):
    connected(monkeypatch)
    evidence()
    for index, changes in enumerate([{"body": "Текст " * 680}, {"format": "story"}]):
        item = candidate(event=f"limits-{index}", **changes)
        checked = content.check_candidate(item["id"], NOW)
        assert checked["status"] == "skipped" and "Telegram" in checked["check"]["reason"]


def test_account_edit_during_read_only_probe_cannot_verify_the_new_recipient(monkeypatch):
    from marketing import channels
    peer = TelegramPeer(monkeypatch)
    saved = account()
    original_send = peer.send
    def changed_send(session, request, **options):
        if request.url.endswith("/getChatMember"):
            permissions.save_account(OWNER, "tg", {**{key: saved[key] for key in permissions.Account.model_fields}, "external_id": "-100456"}, saved["version"])
        return original_send(request, **options)
    monkeypatch.setattr(requests.Session, "send", changed_send)
    with pytest.raises(Exception):
        channels.probe(OWNER, "tg", saved["version"], NOW)
    with store.connection() as c:
        current = store.get(c, "account", "tg")
        assert current["external_id"] == "-100456" and current["connection_status"] == "not_connected"


@pytest.mark.parametrize("change", ["evidence", "pause", "credential", "recipient"])
def test_changes_during_provider_preparation_are_checked_before_the_mutating_request(monkeypatch, change):
    peer, saved = connected(monkeypatch)
    job = queued()
    original_send = peer.send
    def change_during_probe(session, request, **options):
        result = original_send(request, **options)
        if request.url.endswith("/getChatMember"):
            if change == "evidence":
                from test_marketing_incidents import amend
                amend(99)
            elif change == "pause":
                delivery.set_pause(OWNER, publications=True)
            elif change == "credential":
                monkeypatch.setenv("MARKETING_TELEGRAM_BOT_TOKEN", TOKEN + "rotated")
            else:
                permissions.save_account(OWNER, "tg", {**{key: saved[key] for key in permissions.Account.model_fields}, "external_id": "-100456"}, saved["version"])
        return result
    monkeypatch.setattr(requests.Session, "send", change_during_probe)
    assert worker.tick(now=NOW)["delivery_work"]
    assert not any(method.startswith("send") for method, _, _ in peer.calls)
    with store.connection() as c:
        result = store.get(c, "delivery", job["id"])
        assert result["confirmed_not_sent"] is True
        item = store.get(c, "candidate", job["id"])
        assert item["status"] == ("skipped" if change == "evidence" else "error")
