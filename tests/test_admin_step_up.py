"""Admin mutations require an authorized session. Google sign-in honors account two-factor settings."""
from __future__ import annotations

import re
import time

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import api
import server.auth.oauth as oauth
import web_auth


HUMAN_ADMIN_GATES = {"_admin_gate", "_admin_panel_gate", "_control_gate",
                     "_sector_analysis_gate", "_require_admin_user"}
ADMIN = "owner@example.test"
LOGIN_OTP = "123456"


class _User:
    def __init__(self, user_id: int = 41, email: str = ADMIN) -> None:
        self.id = user_id
        self.email = email
        self.email_verified = True


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    users = {"reader": _User(41, "reader@example.test")}
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


def test_every_human_admin_change_is_found() -> None:
    # The sweep below proves nothing if it finds nothing.
    assert len(_human_admin_changes()) >= 40


@pytest.mark.parametrize("method,path", _human_admin_changes())
def test_admin_writes_require_a_session_and_an_administrative_role(admin, method, path) -> None:
    for headers, expected in [({}, 401), ({"Authorization": "Bearer reader"}, 403)]:
        response = admin.request(method, path, headers=headers, json={})
        assert response.status_code == expected, response.text


class TestGoogleSignInTwoFactor:
    @pytest.fixture
    def google(self, monkeypatch):
        import server.auth.limits as limits
        for key in [k for k in limits._rate_limiter._events if k.startswith("oauth-exchange:")]:
            limits._rate_limiter._events.pop(key, None)  # the per-IP sign-in limit is not under test
        revoked = []
        user = _User(7, "person@example.test")
        state = {"two_factor": True}
        store = web_auth.web_auth_store
        monkeypatch.setattr(store.security, "verify_admin_two_factor", lambda user_id, code: code == LOGIN_OTP)
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
        assert exchange(code, LOGIN_OTP).json()["token"] == "sess"
        assert exchange(code, LOGIN_OTP).status_code == 400  # spent

    def test_repeated_wrong_codes_revoke_the_session(self, google) -> None:
        exchange, revoked, _ = google
        code = oauth._issue_oauth_code("google", "sess")
        for _ in range(5):
            assert exchange(code, "000000").status_code == 401
        assert revoked == ["sess"]
        assert exchange(code, LOGIN_OTP).status_code == 400

    def test_asking_again_never_extends_the_wait(self, google) -> None:
        exchange, _, _ = google
        code = oauth._issue_oauth_code("google", "sess")
        exchange(code)
        deadline = oauth._oauth_codes[code].expires_at
        exchange(code)
        exchange(code, "000000")
        assert oauth._oauth_codes[code].expires_at == deadline
        assert deadline <= time.monotonic() + oauth._OAUTH_TWO_FACTOR_TTL_SECONDS
