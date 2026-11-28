"""Personal LinkedIn consent and durable credentials, with an intercepted HTTP peer."""
from datetime import timedelta
import json
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
import pytest
import requests

from marketing import channels, permissions, store
from marketing.errors import MarketingError
from marketing.models import Account
from test_marketing_core import OWNER, NOW, account, isolated  # noqa: F401

TOKEN = "synthetic-linkedin-access-token-never-a-real-credential"
SECRET = "synthetic-linkedin-client-secret"
REDIRECT = "https://uzstock.uz/admin/ai-marketing"
PERSON = "urn:li:person:example123"


class LinkedInPeer:
    def __init__(self, monkeypatch):
        self.calls = []
        self.token = {"access_token": TOKEN, "expires_in": 5184000, "scope": "openid profile w_member_social"}
        self.profile = {"sub": "example123", "name": "Test Owner"}
        self.before = None
        self.outcome = None
        self.post_outcome = (201, "urn:li:share:123456789")
        self.retry_after = "73"
        monkeypatch.setenv("MARKETING_CREDENTIAL_KEY", Fernet.generate_key().decode())
        monkeypatch.setenv("MARKETING_LINKEDIN_CLIENT_ID", "test-app")
        monkeypatch.setenv("MARKETING_LINKEDIN_CLIENT_SECRET", SECRET)
        monkeypatch.setenv("MARKETING_LINKEDIN_REDIRECT_URI", REDIRECT)
        monkeypatch.setattr(requests.Session, "send", self.send)

    def send(self, request, **options):
        assert options["allow_redirects"] is False
        assert options["timeout"] == (5, 30)
        self.calls.append(request)
        if self.before:
            self.before(request)
        if request.url == "https://api.linkedin.com/rest/posts":
            assert request.method == "POST" and request.headers["Authorization"] == "Bearer " + TOKEN
            assert request.headers["Linkedin-Version"] == "202606"
            assert request.headers["X-Restli-Protocol-Version"] == "2.0.0"
            if isinstance(self.post_outcome, Exception):
                raise self.post_outcome
            response = requests.Response()
            response.status_code, identifier = self.post_outcome
            response.headers["x-restli-id"] = identifier
            if self.retry_after is not None:
                response.headers["Retry-After"] = self.retry_after
            response._content = b""
            return response
        if isinstance(self.outcome, Exception):
            raise self.outcome
        if self.outcome:
            status, payload = self.outcome
        elif request.url == "https://www.linkedin.com/oauth/v2/accessToken":
            assert request.method == "POST"
            form = parse_qs(request.body)
            assert form["client_secret"] == [SECRET] and form["redirect_uri"] == [REDIRECT]
            assert form["grant_type"] == ["authorization_code"]
            assert request.headers.get("Authorization") is None
            status, payload = 200, self.token
        elif request.url == "https://api.linkedin.com/v2/userinfo":
            assert request.method == "GET" and request.headers["Authorization"] == "Bearer " + TOKEN
            status, payload = 200, self.profile
        else:
            raise AssertionError("Unexpected network request")
        response = requests.Response()
        response.status_code = status
        response._content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return response


def personal(**changes):
    return account("li", platform="linkedin", external_id="", mode="draft", personal_profile=True, **changes)


def start(saved):
    from marketing import linkedin_oauth
    return linkedin_oauth.begin(OWNER, saved["id"], saved["version"], NOW)


def finish(flow, **changes):
    from marketing import linkedin_oauth
    state = parse_qs(urlsplit(flow["authorization_url"]).query)["state"][0]
    values = {"state": state, "code": "synthetic-code", "binding": flow["binding"], "now": NOW}
    return linkedin_oauth.finish(OWNER, **{**values, **changes})


def connected(monkeypatch):
    peer = LinkedInPeer(monkeypatch)
    return peer, finish(start(personal()))


def test_consent_uses_minimal_scopes_and_binds_the_actual_person_without_granting_release(monkeypatch):
    from marketing import linkedin_oauth
    peer = LinkedInPeer(monkeypatch)
    saved = personal()
    flow = start(saved)
    url = urlsplit(flow["authorization_url"])
    query = parse_qs(url.query)
    assert url.netloc == "www.linkedin.com" and url.path == "/oauth/v2/authorization"
    assert set(query["scope"][0].split()) == {"openid", "profile", "w_member_social"}
    assert query["redirect_uri"] == [REDIRECT] and query["response_type"] == ["code"]
    assert SECRET not in flow["authorization_url"] and flow["binding"] not in flow["authorization_url"]
    result = finish(flow)
    assert result["external_id"] == PERSON and result["mode"] == "draft"
    assert result["connection_status"] == "connected"
    assert result["connection_identity"]["title"] == "Test Owner"
    assert channels.setup(result, NOW)["ready"] is True
    with store.connection() as c:
        public = json.dumps(store.history(c, "account", "li"))
        encrypted = c.execute("SELECT ciphertext FROM marketing_credentials").fetchone()["ciphertext"]
    assert TOKEN not in encrypted and TOKEN not in public and SECRET not in public
    assert len(peer.calls) == 2
    with pytest.raises(MarketingError, match="expired|used"):
        finish(flow)
    assert len(peer.calls) == 2
    assert linkedin_oauth.setup(result, NOW + timedelta(days=60))["ready"] is False


@pytest.mark.parametrize("problem", ["owner", "cookie", "state", "expired", "account", "config"])
def test_changed_or_unbound_login_cannot_exchange_a_code(monkeypatch, problem):
    from marketing import linkedin_oauth
    peer = LinkedInPeer(monkeypatch)
    saved = personal()
    flow = start(saved)
    args = {"state": parse_qs(urlsplit(flow["authorization_url"]).query)["state"][0],
            "code": "synthetic-code", "binding": flow["binding"], "now": NOW}
    owner = OWNER
    if problem == "owner":
        owner = {**OWNER, "id": 2}
    elif problem == "cookie":
        args["binding"] = "different-browser"
    elif problem == "state":
        args["state"] = "li_invented"
    elif problem == "expired":
        args["now"] += timedelta(minutes=11)
    elif problem == "account":
        permissions.save_account(OWNER, "li", {**{k: v for k, v in saved.items() if k in Account.model_fields}, "label": "Changed"}, saved["version"])
    else:
        monkeypatch.setenv("MARKETING_LINKEDIN_CLIENT_SECRET", SECRET + "rotated")
    with pytest.raises(MarketingError):
        linkedin_oauth.finish(owner, **args)
    assert peer.calls == []


@pytest.mark.parametrize("problem", ["other_person", "organization", "scope", "expiry", "profile", "token", "denied", "redirect", "timeout", "oversized"])
def test_invalid_provider_evidence_never_connects_and_never_leaks_secrets(monkeypatch, problem):
    peer = LinkedInPeer(monkeypatch)
    saved = personal()
    if problem == "other_person":
        saved = permissions.save_account(OWNER, "li", {**{k: v for k, v in saved.items() if k in Account.model_fields}, "external_id": "urn:li:person:different"}, saved["version"])
    elif problem == "organization":
        peer.profile["sub"] = "urn:li:organization:123"
    elif problem == "scope":
        peer.token["scope"] = "openid profile"
    elif problem == "expiry":
        peer.token["expires_in"] = True
    elif problem == "profile":
        peer.profile = {"name": TOKEN}
    elif problem == "token":
        peer.token["access_token"] = "bad\r\nheader"
    elif problem == "denied":
        peer.outcome = (401, {"message": TOKEN + SECRET})
    elif problem == "redirect":
        peer.outcome = (302, b"redirect " + TOKEN.encode())
    elif problem == "timeout":
        peer.outcome = requests.Timeout(TOKEN + SECRET)
    else:
        peer.outcome = (200, b" " * 1_000_001)
    with pytest.raises(MarketingError) as caught:
        finish(start(saved))
    assert TOKEN not in str(caught.value) and SECRET not in str(caught.value)
    with store.connection() as c:
        assert store.get(c, "account", "li")["connection_status"] == "not_connected"
        assert c.execute("SELECT COUNT(*) AS n FROM marketing_credentials").fetchone()["n"] == 0


@pytest.mark.parametrize("problem", ["account", "config", "login_expired", "grant_expired"])
def test_changes_during_exchange_are_rechecked_before_saving_a_grant(monkeypatch, problem):
    from marketing import linkedin_oauth
    peer = LinkedInPeer(monkeypatch)
    elapsed = [0]
    monkeypatch.setattr(linkedin_oauth, "monotonic", lambda: elapsed[0], raising=False)
    if problem == "grant_expired":
        peer.token["expires_in"] = 120
    saved = personal()
    flow = start(saved)
    def mutate(request):
        if request.url.endswith("/userinfo"):
            if problem == "account":
                permissions.save_account(OWNER, "li", {**{k: v for k, v in saved.items() if k in Account.model_fields}, "external_id": "urn:li:person:other"}, saved["version"])
            elif problem == "config":
                monkeypatch.setenv("MARKETING_LINKEDIN_CLIENT_SECRET", "rotated")
            else:
                elapsed[0] = 601 if problem == "login_expired" else 121
    peer.before = mutate
    with pytest.raises(MarketingError):
        finish(flow)
    with store.connection() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM marketing_credentials").fetchone()["n"] == 0


def test_disconnect_and_key_or_recipient_rotation_invalidate_current_connection(monkeypatch):
    from marketing import linkedin_oauth
    peer, saved = connected(monkeypatch)
    key = __import__("os").environ["MARKETING_CREDENTIAL_KEY"]
    monkeypatch.setenv("MARKETING_CREDENTIAL_KEY", Fernet.generate_key().decode())
    assert not channels.setup(saved, NOW)["ready"]
    monkeypatch.setenv("MARKETING_CREDENTIAL_KEY", key)
    assert not channels.setup({**saved, "external_id": "urn:li:person:other"}, NOW)["ready"]
    monkeypatch.setenv("MARKETING_ENVIRONMENT", "other-environment")
    assert not channels.setup(saved, NOW)["ready"]
    monkeypatch.setenv("MARKETING_ENVIRONMENT", "test")
    result = linkedin_oauth.disconnect(OWNER, "li", saved["version"])
    assert not channels.setup(result, NOW)["ready"] and result["mode"] == saved["mode"]
    assert len(peer.calls) == 2  # Local disconnect does not send posts or invoke an invented revocation API.
    with store.connection() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM marketing_credentials").fetchone()["n"] == 0


def test_cancelled_consent_is_single_use_and_never_calls_linkedin(monkeypatch):
    peer = LinkedInPeer(monkeypatch)
    flow = start(personal())
    with pytest.raises(MarketingError, match="cancelled"):
        finish(flow, code=None, error="user_cancelled_authorize")
    with pytest.raises(MarketingError, match="expired|used"):
        finish(flow)
    assert not peer.calls


def test_setup_does_not_treat_draft_or_company_authorization_as_personal_consent(monkeypatch):
    from marketing import linkedin_oauth
    peer = LinkedInPeer(monkeypatch)
    saved = personal()
    for change in [{"personal_profile": False}, {"external_id": "urn:li:organization:1"}]:
        current = permissions.save_account(OWNER, "li", {**{k: v for k, v in saved.items() if k in Account.model_fields}, **change}, saved["version"])
        with pytest.raises(MarketingError):
            start(current)
        saved = current
    monkeypatch.delenv("MARKETING_CREDENTIAL_KEY")
    assert linkedin_oauth.setup(saved)["configured"] is False
    assert peer.calls == []


def queued(monkeypatch):
    from marketing import content, delivery, founder
    from test_marketing_core import evidence, candidate
    from test_marketing_founder import fact_data
    peer, saved = connected(monkeypatch)
    permissions.save_account(OWNER, "li", {**{k: v for k, v in saved.items() if k in Account.model_fields}, "mode": "automatic"}, saved["version"])
    evidence()
    founder.save(OWNER, "founder-role", fact_data(), 0)
    item = candidate(target="li", title="Решение (HMKB) [дивиденды] #новости", founder_fact_ids=["founder-role"])
    assert content.check_candidate(item["id"], NOW)["status"] == "ready"
    return peer, delivery.schedule(item["id"], NOW)


def test_verified_personal_text_post_preserves_literal_copy_and_original_links(monkeypatch):
    from marketing import worker
    peer, job = queued(monkeypatch)
    assert worker.tick(now=NOW)["delivery_work"]
    assert not worker.tick(now=NOW + timedelta(minutes=1))["delivery_work"]
    sent = [json.loads(r.body) for r in peer.calls if r.url.endswith("/rest/posts")]
    assert len(sent) == 1
    body = sent[0]
    assert body["author"] == PERSON and body["visibility"] == "PUBLIC" and body["lifecycleState"] == "PUBLISHED"
    assert body["distribution"]["feedDistribution"] == "MAIN_FEED" and "adContext" not in body
    assert r"\(HMKB\) \[дивиденды\] \#новости" in body["commentary"]
    assert "https://openinfo.uz/facts/123" in body["commentary"] and "https://uzstock.uz/news/decision-123" in body["commentary"]
    with store.connection() as c:
        result = store.get(c, "delivery", job["id"])
    assert result["status"] == "submitted" and result["external_id"] == "urn:li:share:123456789"
    assert result["url"] == "https://www.linkedin.com/feed/update/urn:li:share:123456789/"
    assert "(HMKB) [дивиденды] #новости" in result["dispatch_payload"]["text"]


@pytest.mark.parametrize("outcome", [requests.Timeout(TOKEN), (503, ""), (201, ""), (201, "urn:li:person:123"), (302, ""), (200, "urn:li:share:1")])
def test_uncertain_linkedin_post_is_never_replayed(monkeypatch, outcome):
    from marketing import worker
    peer, job = queued(monkeypatch)
    peer.post_outcome = outcome
    assert worker.tick(now=NOW)["delivery_work"]
    assert not worker.tick(now=NOW + timedelta(minutes=1))["delivery_work"]
    with store.connection() as c:
        result = store.get(c, "delivery", job["id"])
    assert result["status"] == "unknown" and TOKEN not in json.dumps(result)
    assert len([r for r in peer.calls if r.url.endswith("/rest/posts")]) == 1


@pytest.mark.parametrize("status,expected", [(429, "retry"), (403, "error"), (422, "error")])
def test_explicit_linkedin_rejection_is_distinct_from_unknown_acceptance(monkeypatch, status, expected):
    from marketing import worker
    peer, job = queued(monkeypatch)
    peer.post_outcome = (status, "")
    assert worker.tick(now=NOW)["delivery_work"]
    with store.connection() as c:
        result = store.get(c, "delivery", job["id"])
    assert result["status"] == expected
    if status == 429:
        assert permissions.timestamp(result["next_attempt_at"]) == NOW + timedelta(seconds=73)


@pytest.mark.parametrize("header,delay", [(None, 57600), ("not a date", 57600),
    ("Tue, 24 Nov 2026 08:00:00 GMT", 86400), ("172800", 172800), ("999999999999", None)])
def test_linkedin_throttling_waits_for_the_full_retry_date_or_daily_reset(monkeypatch, header, delay):
    from marketing import worker
    peer, job = queued(monkeypatch)
    peer.post_outcome, peer.retry_after = (429, ""), header
    assert worker.tick(now=NOW)["delivery_work"]
    with store.connection() as c:
        result = store.get(c, "delivery", job["id"])
    if delay is None:
        assert result["status"] == "error"  # The requested delay cannot fit a datetime; never retry early.
    else:
        assert result["status"] == "retry"
        assert permissions.timestamp(result["next_attempt_at"]) == NOW + timedelta(seconds=delay)


@pytest.mark.parametrize("change", ["disconnect", "pause", "profile"])
def test_pre_send_profile_check_cannot_bypass_disconnect_pause_or_recipient_change(monkeypatch, change):
    from marketing import delivery, worker, linkedin_oauth
    peer, job = queued(monkeypatch)
    def mutate(request):
        if request.url.endswith("/userinfo"):
            if change == "pause":
                delivery.set_pause(OWNER, publications=True)
            elif change == "disconnect":
                with store.connection() as c:
                    saved = store.get(c, "account", "li")
                linkedin_oauth.disconnect(OWNER, "li", saved["version"])
            else:
                peer.profile["sub"] = "different"
    peer.before = mutate
    assert worker.tick(now=NOW)["delivery_work"]
    assert not any(r.url.endswith("/rest/posts") for r in peer.calls)
    with store.connection() as c:
        result = store.get(c, "delivery", job["id"])
    assert result["status"] in {"retry", "error"} and result["status"] != "unknown"


def test_portable_backup_excludes_grants_and_login_states(monkeypatch, tmp_path):
    import zipfile
    from marketing import backup
    _, saved = connected(monkeypatch)
    flow = start(saved)
    archive = tmp_path / "portable.zip"
    backup.create(archive)
    with zipfile.ZipFile(archive) as z:
        text = b"".join(z.read(name) for name in z.namelist()).decode()
    assert TOKEN not in text and SECRET not in text
    assert flow["binding"] not in text and "state_hash" not in text and "ciphertext" not in text
