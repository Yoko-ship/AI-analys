"""A session token is not enough to change anything as an admin, or to sign in
past two-factor through Google.

Two gaps closed here:
  * the authenticator step-up guarded only admin_control's own mutations; user
    deletion, PRO grants, data corrections and rollbacks ran on the 30-day
    Bearer token alone, so a copied token was the whole panel.
  * a Google sign-in issued a full session to an account with two-factor on
    without ever asking for the code.
"""
from __future__ import annotations

import re
import time

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import api
import server.auth.access as access
import server.auth.oauth as oauth
import web_auth
from tests.conftest import ADMIN_OTP

HUMAN_ADMIN_GATES = {"_admin_gate", "_admin_panel_gate", "_control_gate",
                     "_sector_analysis_gate", "_require_admin_user"}
ADMIN = "owner@example.test"


class _User:
    def __init__(self, user_id: int = 41, email: str = ADMIN) -> None:
        self.id = user_id
        self.email = email
        self.email_verified = True


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    users = {"tok-a": _User(41), "tok-b": _User(41)}
    monkeypatch.setattr(web_auth.web_auth_store.sessions, "get_user_by_token", users.get)
    return TestClient(api.app)


def _gates(route: APIRoute) -> set[str]:
    found, stack = set(), list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        found.add(getattr(dep.call, "__name__", ""))
        stack.extend(dep.dependencies)
    return found & HUMAN_ADMIN_GATES


def _human_admin_changes() -> list[tuple[str, str]]:
    routes = []
    for route in api.app.routes:
        if isinstance(route, APIRoute) and _gates(route):
            for method in sorted(route.methods - {"GET", "HEAD", "OPTIONS"}):
                routes.append((method, re.sub(r"\{[^}]+\}", "1", route.path)))
    return routes


def _refusal_code(response) -> str | None:
    body = response.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        return detail.get("code")
    return (body.get("error") or {}).get("code")


def test_every_human_admin_change_is_found() -> None:
    # The sweep below proves nothing if it finds nothing.
    assert len(_human_admin_changes()) >= 40


@pytest.mark.parametrize("method,path", _human_admin_changes())
def test_a_bearer_token_alone_changes_nothing(admin, admin_authenticator, method, path) -> None:
    response = admin.request(method, path, headers={"Authorization": "Bearer tok-a"}, json={})
    assert response.status_code == 403 and _refusal_code(response) == "MFA_REQUIRED", response.text


def test_reads_need_no_step_up(admin, monkeypatch) -> None:
    import admin_overview
    monkeypatch.setattr(admin_overview, "build_overview", lambda **kw: {"ok": True})
    assert admin.get("/api/admin/users", headers={"Authorization": "Bearer tok-a"}).status_code != 403


def test_a_code_on_the_request_passes_the_gate(admin, admin_authenticator) -> None:
    response = admin.post("/api/admin/users/77/action", json={"action": "nope"},
                          headers={"Authorization": "Bearer tok-a", **admin_authenticator})
    assert response.status_code == 400  # past the gate, refused by the handler


def test_step_up_covers_this_session_only_and_expires(admin, admin_authenticator, monkeypatch) -> None:
    change = lambda token: admin.post("/api/admin/users/77/action", json={"action": "nope"},
                                      headers={"Authorization": f"Bearer {token}"})
    proved = admin.post("/api/auth/admin/step-up", json={"code": ADMIN_OTP},
                        headers={"Authorization": "Bearer tok-a"})
    assert proved.status_code == 200 and proved.json()["expires_in"] == access.ADMIN_STEP_UP_SECONDS
    assert change("tok-a").status_code == 400
    # The same person's other session (another browser, or a copied token) did not prove anything.
    assert _refusal_code(change("tok-b")) == "MFA_REQUIRED"
    key = next(iter(access._step_ups))
    access._step_ups[key] = (41, time.monotonic() - 1)
    assert _refusal_code(change("tok-a")) == "MFA_REQUIRED"


def test_wrong_codes_are_refused_and_then_throttled(admin, admin_authenticator) -> None:
    attempt = lambda: admin.post("/api/auth/admin/step-up", json={"code": "000000"},
                                 headers={"Authorization": "Bearer tok-a"})
    assert [attempt().status_code for _ in range(access.STEP_UP_ATTEMPTS_PER_MINUTE)] == [400] * 5
    assert attempt().status_code == 429
    # The throttle covers codes sent on admin requests too, not just the endpoint.
    response = admin.post("/api/admin/users/77/action", json={"action": "nope"},
                          headers={"Authorization": "Bearer tok-a", **admin_authenticator})
    assert _refusal_code(response) == "MFA_REQUIRED"


def test_step_up_needs_a_session(admin) -> None:
    assert admin.post("/api/auth/admin/step-up", json={"code": ADMIN_OTP}).status_code == 401


def test_the_machine_secret_is_not_asked(admin, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_SECRET", "collector-secret")
    response = admin.post("/api/audit/run", headers={"X-Admin-Secret": "collector-secret"}, json={})
    assert _refusal_code(response) != "MFA_REQUIRED"


class TestGoogleSignInTwoFactor:
    @pytest.fixture
    def google(self, monkeypatch, admin_authenticator):
        import server.auth.limits as limits
        for key in [k for k in limits._rate_limiter._events if k.startswith("oauth-exchange:")]:
            limits._rate_limiter._events.pop(key, None)  # the per-IP sign-in limit is not under test
        revoked = []
        user = _User(7, "person@example.test")
        state = {"two_factor": True}
        store = web_auth.web_auth_store
        monkeypatch.setattr(store.sessions, "get_user_by_token", lambda token: user if token == "sess" else None)
        monkeypatch.setattr(store.sessions, "revoke_token", lambda token: revoked.append(token) or True)
        monkeypatch.setattr(store.security, "two_factor_enabled", lambda user_id: state["two_factor"])
        client = TestClient(api.app)
        exchange = lambda code, otp=None: client.post(
            "/api/auth/oauth/exchange", json={"code": code, **({"otp": otp} if otp else {})})
        return exchange, revoked, state

    def test_without_two_factor_the_token_is_handed_over(self, google) -> None:
        exchange, _, state = google
        state["two_factor"] = False
        assert exchange(oauth._issue_oauth_code("google", "sess")).json()["token"] == "sess"

    def test_the_code_waits_for_the_authenticator(self, google) -> None:
        exchange, _, _ = google
        code = oauth._issue_oauth_code("google", "sess")
        asked = exchange(code)
        assert asked.status_code == 401 and asked.json()["detail"] == "Two-factor code required"
        assert "token" not in asked.json()
        wrong = exchange(code, "000000")
        assert wrong.status_code == 401 and wrong.json()["detail"] == "Invalid two-factor code"
        assert exchange(code, ADMIN_OTP).json()["token"] == "sess"
        assert exchange(code, ADMIN_OTP).status_code == 400  # spent

    def test_repeated_wrong_codes_revoke_the_session(self, google) -> None:
        exchange, revoked, _ = google
        code = oauth._issue_oauth_code("google", "sess")
        for _ in range(5):
            assert exchange(code, "000000").status_code == 401
        assert revoked == ["sess"]
        assert exchange(code, ADMIN_OTP).status_code == 400

    def test_asking_again_never_extends_the_wait(self, google) -> None:
        exchange, _, _ = google
        code = oauth._issue_oauth_code("google", "sess")
        exchange(code)
        deadline = oauth._oauth_codes[code].expires_at
        exchange(code)
        exchange(code, "000000")
        assert oauth._oauth_codes[code].expires_at == deadline
        assert deadline <= time.monotonic() + oauth._OAUTH_TWO_FACTOR_TTL_SECONDS
