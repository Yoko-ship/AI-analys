"""Provider fetch URLs expose only the exact file of an active approved release."""
from datetime import timedelta
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

import api
from marketing import channels, credentials, delivery, media, meta_oauth, store
from test_marketing_core import OWNER, NOW, isolated  # noqa: F401
from test_marketing_facebook import queued
from test_marketing_meta import PAGE_TOKEN, USER_TOKEN, SECRET


def ticket(monkeypatch, format="image"):
    from marketing import public_media
    _, job, files = queued(monkeypatch, format)
    job, account, item = delivery._claim(NOW, channels.Transport(NOW))
    grant = meta_oauth.current_grant(account, NOW)
    url = public_media.issue(account, item, files[0], job["id"], job["claim_token"], grant, NOW)
    monkeypatch.setattr(public_media, "now", lambda: NOW)
    return TestClient(api.app), urlsplit(url), job, account, item, files[0]


def test_exact_approved_bytes_can_be_fetched_without_a_session_and_without_public_secrets(monkeypatch):
    client, url, job, _, _, asset = ticket(monkeypatch)
    assert url.scheme == "https" and url.netloc == "uzstock.uz" and not url.query
    response = client.get(url.path)
    assert response.status_code == 200
    assert response.content == media.read_asset(asset)
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    head = client.head(url.path)
    assert head.status_code == 200 and not head.content
    assert head.headers["content-length"] == str(len(response.content))
    with store.connection() as c:
        public = store.encode(store.history(c, "delivery", job["id"]))
    for secret in [PAGE_TOKEN, USER_TOKEN, SECRET, url.path.split("/")[-1]]:
        assert secret not in public
    assert client.get(url.path.replace("/api/", "/api/v2/", 1)).content == response.content


@pytest.mark.parametrize("change", ["expiry", "tamper", "environment", "key", "disconnect", "account", "asset", "file", "candidate", "pause", "cancel"])
def test_download_ticket_cannot_survive_expiry_corruption_or_withdrawn_authority(monkeypatch, change):
    from marketing import public_media
    client, url, job, account, item, asset = ticket(monkeypatch)
    path = url.path
    if change == "expiry":
        monkeypatch.setattr(public_media, "now", lambda: NOW + timedelta(hours=24))
    elif change == "tamper":
        path = path[:-8] + "XXXXXXXX"
    elif change == "environment":
        monkeypatch.setenv("MARKETING_ENVIRONMENT", "another")
    elif change == "key":
        monkeypatch.setenv("MARKETING_CREDENTIAL_KEY", Fernet.generate_key().decode())
    elif change == "file":
        media.asset_path(asset).write_bytes(b"different bytes")
    else:
        with store.connection(write=True) as c:
            if change == "disconnect":
                credentials.delete(c, account["id"], "meta")
            elif change == "account":
                store.put(c, "account", {**account, "external_id": "99999"}, actor=OWNER, action="test", expected_version=account["version"])
            elif change == "asset":
                store.put(c, "asset", {**asset, "alt_text": "changed"}, actor=OWNER, action="test", expected_version=asset["version"])
            elif change in {"candidate", "cancel"}:
                current = store.get(c, "candidate", item["id"])
                updates = {"body": "changed"} if change == "candidate" else {"status": "cancelled"}
                store.put(c, "candidate", {**current, **updates}, actor=OWNER, action="test", expected_version=current["version"])
            elif change == "pause":
                store.put(c, "settings", {"id": "pause", "publications": True}, actor=OWNER, action="test", expected_version=0)
    response = client.get(path)
    assert response.status_code == 404 and response.json() == {"detail": "Media unavailable"}


def test_only_the_active_dispatch_claim_can_mint_a_download_url(monkeypatch):
    from marketing import public_media
    from marketing.delivery import StoppedBeforeSend
    _, _, job, account, item, asset = ticket(monkeypatch)
    grant = meta_oauth.current_grant(account, NOW)
    with pytest.raises(StoppedBeforeSend):
        public_media.issue(account, item, asset, job["id"], "stale-claim", grant, NOW)
    with store.connection(write=True) as c:
        current = store.get(c, "delivery", job["id"])
        store.put(c, "delivery", {**current, "dispatch_phase": "request_started"}, actor=OWNER, action="test", expected_version=current["version"])
    with pytest.raises(StoppedBeforeSend):
        public_media.issue(account, item, asset, job["id"], job["claim_token"], grant, NOW)


@pytest.mark.parametrize("header,start,end", [("bytes=0-255", 0, 256), ("bytes=500-", 500, None), ("bytes=-32", -32, None)])
def test_provider_can_fetch_an_exact_byte_range(monkeypatch, header, start, end):
    client, url, _, _, _, asset = ticket(monkeypatch, "video")
    raw = media.read_asset(asset)
    response = client.get(url.path, headers={"Range": header})
    assert response.status_code == 206 and response.content == raw[start:end]
    assert response.headers["content-range"] == f"bytes {start if start >= 0 else len(raw) + start}-{(end or len(raw)) - 1}/{len(raw)}"
    assert response.headers["accept-ranges"] == "bytes"
    invalid = client.get(url.path, headers={"Range": f"bytes={len(raw)}-"})
    assert invalid.status_code == 416 and invalid.headers["content-range"] == f"bytes */{len(raw)}"
