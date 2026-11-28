"""Meta owner login discovers real Pages; selection never grants release rights."""
from datetime import timedelta
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
import pytest
import requests

from marketing import channels, credentials, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, account, isolated  # noqa: F401

SECRET = "synthetic-meta-app-secret"
USER_TOKEN = "synthetic-meta-user-token"
PAGE_TOKEN = "synthetic-meta-page-token"
REDIRECT = "https://uzstock.uz/admin/ai-marketing"
APP_ID, USER_ID, PAGE_ID, IG_ID = "12345", "24680", "35790", "46801"
SCOPES = {"pages_show_list", "pages_read_engagement", "pages_manage_posts", "instagram_basic", "instagram_content_publish"}


class MetaPeer:
    def __init__(self, monkeypatch, now=NOW):
        self.now, self.calls, self.before, self.outcome = now, [], None, None
        self.debug = {"app_id": APP_ID, "type": "USER", "user_id": USER_ID, "is_valid": True,
                      "expires_at": int((now + timedelta(days=60)).timestamp()),
                      "data_access_expires_at": int((now + timedelta(days=90)).timestamp()), "scopes": sorted(SCOPES)}
        self.pages = [{"id": "99999", "name": "Another Page", "tasks": ["CREATE_CONTENT"], "access_token": "other-page-token"},
                      {"id": PAGE_ID, "name": "UZStock test", "tasks": ["CREATE_CONTENT", "MANAGE"], "access_token": PAGE_TOKEN,
                       "instagram_business_account": {"id": IG_ID, "username": "uzstock_test", "name": "UZStock test Instagram"}}]
        self.page_debug = {**self.debug, "type": "PAGE", "profile_id": PAGE_ID, "expires_at": 0}
        self.paging = None
        monkeypatch.setenv("MARKETING_CREDENTIAL_KEY", Fernet.generate_key().decode())
        for key, value in {"APP_ID": APP_ID, "APP_SECRET": SECRET, "REDIRECT_URI": REDIRECT,
                           "FACEBOOK_CONFIG_ID": "11111", "INSTAGRAM_CONFIG_ID": "22222"}.items():
            monkeypatch.setenv("MARKETING_META_" + key, value)
        monkeypatch.setattr(requests.Session, "send", self.send)

    def send(self, request, **options):
        assert options["allow_redirects"] is False and options["timeout"] == (5, 30)
        url, query = urlsplit(request.url), parse_qs(urlsplit(request.url).query)
        assert url.netloc == "graph.facebook.com" and url.path.startswith("/v25.0/") and request.method == "GET"
        self.calls.append(request)
        if self.before:
            self.before(request)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        if self.outcome:
            status, value = self.outcome
        elif url.path.endswith("/oauth/access_token"):
            assert query["client_id"] == [APP_ID] and query["client_secret"] == [SECRET]
            if "code" in query:
                assert query["redirect_uri"] == [REDIRECT]
            else:
                assert query["grant_type"] == ["fb_exchange_token"] and query["fb_exchange_token"] == [USER_TOKEN]
            status, value = 200, {"access_token": USER_TOKEN, "token_type": "bearer", "expires_in": 60 * 86400}
        elif url.path.endswith("/debug_token"):
            assert request.headers["Authorization"] == "Bearer " + APP_ID + "|" + SECRET
            token = query["input_token"][0]
            assert token in {USER_TOKEN, PAGE_TOKEN}
            status, value = 200, {"data": self.debug if token == USER_TOKEN else self.page_debug}
        elif url.path.endswith("/me/accounts"):
            assert request.headers["Authorization"] == "Bearer " + USER_TOKEN
            assert query["appsecret_proof"] == [hmac.new(SECRET.encode(), USER_TOKEN.encode(), hashlib.sha256).hexdigest()]
            status, value = 200, {"data": self.pages}
            if self.paging:
                value["paging"] = self.paging
        else:
            raise AssertionError("Unexpected request")
        response = requests.Response()
        response.status_code = status
        response._content = value if isinstance(value, bytes) else json.dumps(value).encode()
        return response


def target(platform="facebook", **changes):
    return account(platform, **{"platform": platform, "external_id": "", "mode": "draft", **changes})


def begin(saved):
    from marketing import meta_oauth
    return meta_oauth.begin(OWNER, saved["id"], saved["version"], NOW)


def finish(flow, **changes):
    from marketing import meta_oauth
    return meta_oauth.finish(OWNER, **{"state": parse_qs(urlsplit(flow["authorization_url"]).query)["state"][0],
        "code": "synthetic-meta-code", "binding": flow["binding"], "now": NOW, **changes})


@pytest.mark.parametrize("platform,identifier", [("facebook", PAGE_ID), ("instagram", IG_ID)])
def test_login_requires_explicit_target_selection_and_preserves_draft_permissions(monkeypatch, platform, identifier):
    from marketing import meta_oauth
    peer = MetaPeer(monkeypatch)
    saved = target(platform)
    flow = begin(saved)
    url = urlsplit(flow["authorization_url"])
    query = parse_qs(url.query)
    assert url.netloc == "www.facebook.com" and url.path == "/v25.0/dialog/oauth"
    assert query["config_id"] == ["11111" if platform == "facebook" else "22222"]
    assert query["response_type"] == ["code"] and query["redirect_uri"] == [REDIRECT] and "scope" not in query
    selection = finish(flow)
    assert any(row["target_id"] == identifier for row in selection["choices"])
    with store.connection() as c:
        assert store.get(c, "account", platform)["connection_status"] == "not_connected"
    chosen = meta_oauth.select(OWNER, platform, saved["version"], selection["selection_id"], identifier, NOW)
    assert chosen["external_id"] == identifier and chosen["mode"] == "draft" and chosen["connection_status"] == "connected"
    assert chosen["connection_identity"]["page_id"] == PAGE_ID
    assert channels.setup(chosen, NOW)["ready"]
    assert channels.setup(chosen, NOW)["formats"] == (["post", "image", "carousel", "video"] if platform == "facebook" else ["image", "carousel", "video", "story"])
    with store.connection() as c:
        encrypted = c.execute("SELECT ciphertext FROM marketing_credentials").fetchall()
        public = json.dumps([store.history(c, "account", platform), channels.setup(chosen, NOW, c)])
        assert credentials.read(c, platform, "meta_pending") is None
    for secret in [SECRET, USER_TOKEN, PAGE_TOKEN, "other-page-token"]:
        assert secret not in json.dumps(encrypted) and secret not in public and secret not in json.dumps(selection)
    assert peer.calls
    with pytest.raises(MarketingError):
        finish(flow)
    with pytest.raises(MarketingError):
        meta_oauth.select(OWNER, platform, saved["version"], selection["selection_id"], identifier, NOW)


@pytest.mark.parametrize("failure", ["wrong_app", "invalid", "expired", "data_expired", "scope", "system_user", "bool_expiry", "missing_expiry"])
def test_unverified_user_grants_never_expose_account_choices(monkeypatch, failure):
    peer = MetaPeer(monkeypatch)
    mutations = {"wrong_app": {"app_id": "different"}, "invalid": {"is_valid": False}, "expired": {"expires_at": 1},
                 "data_expired": {"data_access_expires_at": 1}, "scope": {"scopes": ["pages_show_list"]},
                 "system_user": {"type": "SYSTEM_USER"}, "bool_expiry": {"expires_at": True}, "missing_expiry": {"expires_at": None}}
    peer.debug.update(mutations[failure])
    with pytest.raises(MarketingError):
        finish(begin(target()))
    assert not any(urlsplit(r.url).path.endswith("/me/accounts") for r in peer.calls)


@pytest.mark.parametrize("change", ["owner", "browser", "expired", "account", "config", "new_login"])
def test_login_intent_is_bound_before_any_code_exchange(monkeypatch, change):
    from marketing import meta_oauth
    peer = MetaPeer(monkeypatch)
    saved = target()
    flow, values = begin(saved), {}
    if change == "owner":
        with pytest.raises(MarketingError):
            meta_oauth.begin({"id": "model", "role": "cmo"}, saved["id"], saved["version"], NOW)
        values["binding"] = ""
    elif change == "browser":
        values["binding"] = "wrong-browser"
    elif change == "expired":
        values["now"] = NOW + timedelta(seconds=601)
    elif change == "account":
        with store.connection(write=True) as c:
            store.put(c, "account", {**saved, "label": "Changed"}, actor=OWNER, action="rename", expected_version=saved["version"])
    elif change == "config":
        monkeypatch.setenv("MARKETING_META_FACEBOOK_CONFIG_ID", "33333")
    else:
        begin(saved)
    with pytest.raises(MarketingError):
        finish(flow, **values)
    assert peer.calls == []


@pytest.mark.parametrize("change", ["target", "task", "page_token", "page_app", "page_invalid", "selection", "expiry", "account", "config"])
def test_selection_rechecks_current_target_permissions_and_exact_owner_choice(monkeypatch, change):
    from marketing import meta_oauth
    peer = MetaPeer(monkeypatch)
    saved = target()
    selection = finish(begin(saved))
    selection_id, identifier, at = selection["selection_id"], PAGE_ID, NOW
    if change == "target":
        identifier = "invented"
    elif change == "task":
        peer.pages[1]["tasks"] = ["ANALYZE"]
    elif change == "page_token":
        peer.page_debug["profile_id"] = "11111"
    elif change == "page_app":
        peer.page_debug["app_id"] = "11111"
    elif change == "page_invalid":
        peer.page_debug["is_valid"] = False
    elif change == "selection":
        selection_id = "old-choice"
    elif change == "expiry":
        at += timedelta(seconds=601)
    elif change == "account":
        with store.connection(write=True) as c:
            store.put(c, "account", {**saved, "external_id": "123456"}, actor=OWNER, action="retarget", expected_version=saved["version"])
    else:
        monkeypatch.setenv("MARKETING_META_APP_SECRET", "rotated")
    with pytest.raises(MarketingError):
        meta_oauth.select(OWNER, saved["id"], saved["version"], selection_id, identifier, at)
    with store.connection() as c:
        assert credentials.read(c, saved["id"], "meta") is None


def test_preconfigured_instagram_cannot_be_replaced_by_a_different_linked_profile(monkeypatch):
    peer = MetaPeer(monkeypatch)
    saved = target("instagram", external_id=IG_ID)
    peer.pages[1]["instagram_business_account"]["id"] = "987654"
    with pytest.raises(MarketingError):
        finish(begin(saved))


@pytest.mark.parametrize("outcome", [requests.Timeout(SECRET), (302, {"access_token": USER_TOKEN}), (200, b"x" * 1_000_001), (200, [])])
def test_provider_failures_never_echo_secrets_or_claim_a_connection(monkeypatch, outcome):
    peer = MetaPeer(monkeypatch)
    peer.outcome = outcome
    with pytest.raises(MarketingError) as error:
        finish(begin(target()))
    assert SECRET not in str(error.value) and USER_TOKEN not in str(error.value)


def test_probe_disconnect_expiry_and_local_grant_do_not_depend_on_browser_claims(monkeypatch):
    from marketing import meta_oauth
    peer = MetaPeer(monkeypatch)
    saved = target()
    selection = finish(begin(saved))
    chosen = meta_oauth.select(OWNER, saved["id"], saved["version"], selection["selection_id"], PAGE_ID, NOW)
    assert not channels.setup(chosen, NOW + timedelta(days=61))["ready"]
    peer.pages[1]["tasks"] = ["ANALYZE"]
    checked = channels.probe(OWNER, chosen["id"], chosen["version"], NOW)
    assert checked["connection_status"] == "error" and not channels.setup(checked, NOW)["ready"]
    disconnected = meta_oauth.disconnect(OWNER, checked["id"], checked["version"])
    assert disconnected["connection_status"] == "not_connected"
    with store.connection() as c:
        assert credentials.read(c, checked["id"], "meta") is None


def test_current_data_access_expiry_limits_the_selected_connection(monkeypatch):
    from marketing import meta_oauth
    peer = MetaPeer(monkeypatch)
    saved = target()
    selection = finish(begin(saved))
    expires = NOW + timedelta(minutes=5)
    peer.debug["data_access_expires_at"] = int(expires.timestamp())
    chosen = meta_oauth.select(OWNER, saved["id"], saved["version"], selection["selection_id"], PAGE_ID, NOW)
    assert channels.setup(chosen, NOW)["expires_at"] == expires.isoformat()
    assert not channels.setup(chosen, expires)["ready"]


@pytest.mark.parametrize("stage", ["finish", "select"])
def test_account_changes_during_network_io_cannot_install_a_stale_grant(monkeypatch, stage):
    from marketing import meta_oauth
    peer = MetaPeer(monkeypatch)
    saved = target()
    flow = begin(saved)
    selection = finish(flow) if stage == "select" else None
    def change(request):
        peer.before = None
        with store.connection(write=True) as c:
            current = store.get(c, "account", saved["id"])
            store.put(c, "account", {**current, "external_id": "876543"}, actor=OWNER, action="retarget", expected_version=current["version"])
    peer.before = change
    with pytest.raises(MarketingError):
        if stage == "finish":
            finish(flow)
        else:
            meta_oauth.select(OWNER, saved["id"], saved["version"], selection["selection_id"], PAGE_ID, NOW)
    with store.connection() as c:
        assert credentials.read(c, saved["id"], "meta") is None


def test_pagination_rebuilds_fixed_host_requests_instead_of_following_next_urls(monkeypatch):
    peer = MetaPeer(monkeypatch)
    pages = peer.pages[:]
    def paginate(request):
        query = parse_qs(urlsplit(request.url).query)
        if urlsplit(request.url).path.endswith("/me/accounts"):
            if "after" in query:
                assert query["after"] == ["next-page"]
                peer.pages, peer.paging = [pages[1]], None
            else:
                peer.pages, peer.paging = [pages[0]], {"next": "https://untrusted.invalid/?access_token=" + USER_TOKEN, "cursors": {"after": "next-page"}}
    peer.before = paginate
    selection = finish(begin(target()))
    assert {row["target_id"] for row in selection["choices"]} == {"99999", PAGE_ID}
    assert all(urlsplit(request.url).netloc == "graph.facebook.com" for request in peer.calls)


@pytest.mark.parametrize("field,value", [("scopes", [{}]), ("data_access_expires_at", True)])
def test_malformed_inspection_is_a_safe_rejection(monkeypatch, field, value):
    peer = MetaPeer(monkeypatch)
    peer.debug[field] = value
    with pytest.raises(MarketingError):
        finish(begin(target()))


@pytest.mark.parametrize("stage", ["finish", "select"])
@pytest.mark.parametrize("deadline", ["pending", "grant"])
def test_pending_login_or_choice_cannot_expire_during_network_io_and_still_connect(monkeypatch, stage, deadline):
    from marketing import meta_oauth
    peer = MetaPeer(monkeypatch)
    if deadline == "grant":
        peer.debug["expires_at"] = int((NOW + timedelta(seconds=180)).timestamp())
    saved = target()
    flow = begin(saved)
    selection = finish(flow) if stage == "select" else None
    elapsed = [0]
    monkeypatch.setattr(meta_oauth, "monotonic", lambda: elapsed[0], raising=False)
    def delayed(request):
        elapsed[0] = 601 if deadline == "pending" else 181
    peer.before = delayed
    with pytest.raises(MarketingError):
        if stage == "finish":
            finish(flow)
        else:
            meta_oauth.select(OWNER, saved["id"], saved["version"], selection["selection_id"], PAGE_ID, NOW)
    with store.connection() as c:
        assert credentials.read(c, saved["id"], "meta") is None


@pytest.mark.parametrize("paging", [{"next": "ignored", "cursors": ["invalid"]}, {"next": "ignored", "cursors": {"after": []}}])
def test_malformed_pagination_is_rejected_without_exposing_provider_values(monkeypatch, paging):
    peer = MetaPeer(monkeypatch)
    peer.paging = paging
    with pytest.raises(MarketingError):
        finish(begin(target()))
