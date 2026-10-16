"""Sign-in hardening: one use per authenticator code, no account oracle in
sign-in or registration, a way back from a lockout, and deletion that needs
the person rather than a copied session.

The rules run against a real PostgreSQL (TEST_POSTGRES_URL, as
test_postgres_accounts.py); the source guard and the HTTP pacing run anywhere.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import identity.credentials as credentials
from identity.credentials import _totp_code

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "Violin-Lamp-Tree-77"


def test_no_one_admits_a_person_with_the_reusable_check() -> None:
    # _verify_totp accepts a code again for ~90 s; only consume_totp records it.
    tracked = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.split()
    callers = [path for path in tracked
               if not path.startswith("tests/") and path != "identity/credentials.py"
               and "_verify_totp(" in (ROOT / path).read_text(encoding="utf-8", errors="replace")]
    assert callers == []


@pytest.fixture
def store():
    dsn = os.environ.get("TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("TEST_POSTGRES_URL is not configured")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    schema = "qa_hardening_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        from web_auth import WebAuthStore
        yield WebAuthStore(make_conninfo(dsn, options=f"-c search_path={schema}"))
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _with_two_factor(store, email="mfa@example.test"):
    user, token = store.accounts.register_user(email, PASSWORD)
    secret = store.security.begin_two_factor(user.id)["secret"]
    with store.database.connect() as conn:  # enabled directly, so no step is spent yet
        conn.execute("UPDATE web_users SET two_factor_enabled = TRUE WHERE id = %s", (user.id,))
    return user, token, secret


@pytest.fixture
def pbkdf2_calls(monkeypatch):
    calls = []
    real = hashlib.pbkdf2_hmac
    monkeypatch.setattr(hashlib, "pbkdf2_hmac", lambda *a, **k: calls.append(1) or real(*a, **k))
    return calls


class TestCodeIsUsedOnce:
    def test_a_sign_in_code_cannot_sign_in_twice(self, store) -> None:
        user, _, secret = _with_two_factor(store)
        code = _totp_code(secret)
        store.accounts.login_user(user.email, PASSWORD, code)
        with pytest.raises(ValueError, match="Invalid two-factor code"):
            store.accounts.login_user(user.email, PASSWORD, code)

    def test_a_step_up_code_cannot_be_replayed_but_the_next_one_works(self, store) -> None:
        user, _, secret = _with_two_factor(store)
        now = datetime.now(timezone.utc)
        assert store.security.verify_admin_two_factor(user.id, _totp_code(secret, now))
        assert not store.security.verify_admin_two_factor(user.id, _totp_code(secret, now))
        # An earlier step than one already accepted is refused too.
        assert not store.security.verify_admin_two_factor(user.id, _totp_code(secret, now - timedelta(seconds=30)))
        assert store.security.verify_admin_two_factor(user.id, _totp_code(secret, now + timedelta(seconds=30)))

    def test_one_code_cannot_serve_two_purposes(self, store) -> None:
        user, _, secret = _with_two_factor(store)
        code = _totp_code(secret)
        store.accounts.login_user(user.email, PASSWORD, code)
        assert not store.security.verify_admin_two_factor(user.id, code)
        with pytest.raises(ValueError):
            store.security.disable_two_factor(user.id, code)

    def test_a_wrong_code_is_still_refused(self, store) -> None:
        user, _, secret = _with_two_factor(store)
        wrong = "000000" if _totp_code(secret) != "000000" else "111111"
        assert not store.security.verify_admin_two_factor(user.id, wrong)


class TestNoAccountOracle:
    def test_an_unknown_address_costs_what_a_wrong_password_costs(self, store, pbkdf2_calls) -> None:
        store.accounts.register_user("member@example.test", PASSWORD)
        pbkdf2_calls.clear()
        with pytest.raises(ValueError, match="Invalid email or password"):
            store.accounts.login_user("member@example.test", "wrong-password-1")
        wrong_password = len(pbkdf2_calls)
        pbkdf2_calls.clear()
        with pytest.raises(ValueError, match="Invalid email or password"):
            store.accounts.login_user("stranger@example.test", "wrong-password-1")
        assert len(pbkdf2_calls) == wrong_password == 1

    def test_every_registration_path_spends_one_password_hash(self, store, pbkdf2_calls) -> None:
        def let_a_minute_pass():  # the resend gap is not under test
            with store.database.connect() as conn:
                conn.execute("UPDATE web_email_codes SET sent_at = sent_at - INTERVAL '2 minutes'")

        def cost(email):
            let_a_minute_pass()
            pbkdf2_calls.clear()
            store.accounts.start_registration(email, PASSWORD)
            return len(pbkdf2_calls)

        assert cost("new@example.test") == 1             # a new account
        assert cost("new@example.test") == 1             # re-claimed before anyone proved it
        let_a_minute_pass()
        code = store.accounts.issue_email_code("new@example.test", "verify")
        store.accounts.verify_email_code("new@example.test", code)
        assert cost("new@example.test") == 1             # a member: nothing changes, same work


class TestLockoutHasAWayBack:
    def test_a_locked_member_resets_and_is_signed_in(self, store) -> None:
        import identity.settings as settings
        user, _ = store.accounts.register_user("locked@example.test", PASSWORD)
        for _ in range(settings.LOGIN_FAILURE_LIMIT):
            try:
                store.accounts.login_user(user.email, "wrong-password-1")
            except Exception:  # noqa: BLE001 - the last one locks
                pass
        from identity.users import AccountLocked
        with pytest.raises(AccountLocked):
            store.accounts.login_user(user.email, PASSWORD)
        code = store.accounts.issue_email_code(user.email, "reset")
        _, token = store.accounts.reset_password_with_code(user.email, code, "Kettle-Moon-58-new")
        assert token and store.sessions.get_user_by_token(token).id == user.id
        store.accounts.login_user(user.email, "Kettle-Moon-58-new")


class TestDeletionNeedsThePerson:
    def test_a_session_and_the_email_are_not_enough(self, store) -> None:
        user, token = store.accounts.register_user("del@example.test", PASSWORD)
        with pytest.raises(ValueError, match="current password"):
            store.profile.delete_account(user.id, user.email, session_token=token)
        with pytest.raises(ValueError, match="current password"):
            store.profile.delete_account(user.id, user.email, password="wrong-password-1", session_token=token)
        assert store.profile.delete_account(user.id, user.email, password=PASSWORD, session_token=token)

    def test_an_authenticator_code_proves_it_once(self, store) -> None:
        user, token, secret = _with_two_factor(store, "del-mfa@example.test")
        code = _totp_code(secret)
        assert store.security.verify_admin_two_factor(user.id, code)  # spent elsewhere first
        with pytest.raises(ValueError):
            store.profile.delete_account(user.id, user.email, otp=code, session_token=token)
        later = _totp_code(secret, datetime.now(timezone.utc) + timedelta(seconds=30))
        assert store.profile.delete_account(user.id, user.email, otp=later, session_token=token)

    def test_a_google_account_proves_it_by_signing_in_again(self, store) -> None:
        user, token = store.oauth.oauth_login("google", "g-123", "gdel@example.test", "G", email_verified=True)
        with store.database.connect() as conn:
            conn.execute("UPDATE web_sessions SET created_at = NOW() - INTERVAL '11 minutes'")
        with pytest.raises(ValueError):
            store.profile.delete_account(user.id, user.email, session_token=token)
        _, fresh = store.oauth.oauth_login("google", "g-123", "gdel@example.test", "G", email_verified=True)
        assert store.profile.delete_account(user.id, user.email, session_token=fresh)

    def test_a_fresh_session_is_not_proof_without_google(self, store) -> None:
        user, token = store.accounts.register_user("plain@example.test", PASSWORD)
        with pytest.raises(ValueError):
            store.profile.delete_account(user.id, user.email, session_token=token)

    def test_the_profile_tells_the_page_which_proof_to_offer(self, store) -> None:
        google, _ = store.oauth.oauth_login("google", "g-9", "gp@example.test", "G", email_verified=True)
        plain, _ = store.accounts.register_user("pp@example.test", PASSWORD)
        assert store.profile.get_profile(google.id)["security"]["google_linked"] is True
        assert store.profile.get_profile(plain.id)["security"]["google_linked"] is False


def test_deletion_guesses_are_paced_and_the_session_is_passed(monkeypatch) -> None:
    import api
    import server.accounts.routes as routes
    import server.auth.limits as limits
    import web_auth
    user = type("User", (), {"id": 9001, "email": "x@example.test"})()
    monkeypatch.setattr(web_auth.web_auth_store.sessions, "get_user_by_token", lambda token: user)
    seen = []

    def delete(user_id, confirmation, **proof):
        seen.append(proof)
        raise ValueError("Confirm with your current password or authenticator code")
    monkeypatch.setattr(web_auth.web_auth_store.profile, "delete_account", delete)
    limits._rate_limiter._events.pop("account-delete:9001", None)
    client = TestClient(api.app)
    send = lambda: client.request("DELETE", "/api/profile/account", headers={"Authorization": "Bearer tok-9"},
                                  json={"confirmation": "x@example.test", "password": "guess"})
    statuses = [send().status_code for _ in range(routes.ACCOUNT_DELETE_ATTEMPTS + 1)]
    assert statuses == [400] * routes.ACCOUNT_DELETE_ATTEMPTS + [429]
    assert seen[0] == {"password": "guess", "otp": None, "session_token": "tok-9"}
    limits._rate_limiter._events.pop("account-delete:9001", None)
