"""Password rules, hashing strength and the API contract around them.

Before 2026-09-24 the only rule was «at least 8 characters», so `12345678`
and `password` were accepted.  Following NIST SP 800-63B the policy blocks
known-bad passwords (a 100k common-password list, sequences, repeats, the
user's own email/name, the site name) instead of demanding character classes.
"""
from __future__ import annotations

import email_delivery as subject_email_delivery
import server.auth.limits as subject_server_auth_limits
import web_auth as subject_web_auth

import pytest
from fastapi.testclient import TestClient

import api
import password_policy as policy
import web_auth


# ── what is refused ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("password", [
    "12345678", "123456789", "password", "Password1", "qwertyui", "qwerty123", "1q2w3e4r",
    "11111111", "aaaaaaaa", "abababab", "abcdefgh", "87654321", "asdfghjk", "йцукенгш",
    "iloveyou", "dragon12345", "sunshine!!", "Tashkent2024", "toshkent123", "uzbekistan1",
    "uzstock2026", "UZSTOCK!!",
])
def test_weak_passwords_are_refused(password):
    assert policy.check_password(password) is not None, password


@pytest.mark.parametrize("password,code", [
    ("1234567", "too_short"),
    ("x" * 129, "too_long"),
    ("12345678", "common"),
    ("mnopqrstu", "sequence"),
    ("q9q9q9q9q9", "sequence"),
    ("uzstock-2026", "context"),
])
def test_each_refusal_names_its_reason(password, code):
    assert policy.check_password(password) == code


def test_personal_details_are_refused():
    assert policy.check_password("gapparov2005", email="azam.gapparov@gmail.com") == "personal"
    assert policy.check_password("azamxon1990!", email="x@y.uz", full_name="Azamxon Gapparov") == "personal"
    # Short fragments are ignored — a 3-letter name must not ban every password containing it.
    assert policy.check_password("Tree-Lamp-Violin-42", email="al@y.uz", full_name="Al Bo") is None


# ── what is accepted ────────────────────────────────────────────────────────

@pytest.mark.parametrize("password", [
    "correct horse battery staple",
    "Tr0ub4dor&3x?",
    "mening-sevimli-mushugim-7",
    "zR9!vK2#pL",
    "Kitob va choy 2026",
])
def test_reasonable_passwords_are_accepted(password):
    assert policy.check_password(password, email="reader@example.uz", full_name="Reader") is None


def test_validate_raises_a_value_error_with_a_readable_message():
    with pytest.raises(ValueError) as exc:
        policy.validate_new_password("12345678")
    assert isinstance(exc.value, policy.WeakPassword)
    assert exc.value.code == "common"
    assert "too common" in str(exc.value)


def test_the_common_list_is_loaded():
    assert policy.common_password_count() > 50_000


# ── hashing strength ────────────────────────────────────────────────────────

def test_new_hashes_use_600k_rounds_and_old_ones_still_verify():
    assert web_auth.PBKDF2_ITERATIONS >= 600_000
    fresh = web_auth._password_hash("correct horse battery staple")
    assert fresh.split("$")[1] == str(web_auth.PBKDF2_ITERATIONS)
    assert web_auth._password_verify("correct horse battery staple", fresh)
    old = web_auth._password_hash("correct horse battery staple", iterations=210_000)
    assert web_auth._password_verify("correct horse battery staple", old)
    assert web_auth.password_needs_rehash(old)
    assert not web_auth.password_needs_rehash(fresh)


# ── HTTP contract ───────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(subject_server_auth_limits, '_enforce_auth_rate_limit', lambda request, scope: None)
    monkeypatch.setattr(subject_email_delivery, "verification_enabled", lambda: True)
    return TestClient(api.app)


def test_register_refuses_a_weak_password_before_touching_the_store(client, monkeypatch):
    monkeypatch.setattr(subject_web_auth.web_auth_store, "start_registration",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not register")))
    response = client.post("/api/auth/register", json={"email": "reader@example.uz", "password": "12345678"})
    assert response.status_code == 400
    assert response.json()["detail"] == policy.MESSAGES["common"]


def test_password_reset_refuses_a_weak_password(client, monkeypatch):
    monkeypatch.setattr(subject_web_auth.web_auth_store, "reset_password_with_code",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not reset")))
    response = client.post("/api/auth/password/reset", json={
        "email": "reader@example.uz", "code": "123456", "new_password": "qwertyuiop"})
    assert response.status_code == 400
    assert response.json()["detail"] == policy.MESSAGES["common"]


def test_locked_login_is_429_with_retry_after_and_notifies_the_owner_once(client, monkeypatch):
    sent = []
    monkeypatch.setattr(subject_email_delivery, "send_notice", lambda to, kind, language="ru", **kw: sent.append((to, kind, language)))

    def locked(*args, **kwargs):
        raise web_auth.AccountLocked("reader@example.uz", retry_after=900, newly_locked=True, language="uz")
    monkeypatch.setattr(subject_web_auth.web_auth_store, "login_user", locked)
    response = client.post("/api/auth/login", json={"email": "reader@example.uz", "password": "whatever-1"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "900"
    assert "Too many failed sign-in attempts" in response.json()["detail"]
    assert sent == [("reader@example.uz", "login_locked", "uz")]

    def still_locked(*args, **kwargs):
        raise web_auth.AccountLocked("reader@example.uz", retry_after=600, newly_locked=False, language="uz")
    monkeypatch.setattr(subject_web_auth.web_auth_store, "login_user", still_locked)
    assert client.post("/api/auth/login", json={"email": "reader@example.uz", "password": "whatever-1"}).status_code == 429
    assert len(sent) == 1  # no email for every blocked attempt
