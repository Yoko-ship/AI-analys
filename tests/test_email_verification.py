"""Email-code verification and password reset: rules, mail delivery, API contract.

Why this exists: registration used to create a live, logged-in account for any
typed address.  That let a stranger pre-register someone else's email and keep
a password on the account after the real owner later arrived through Google,
and it left no way to recover a forgotten password.  These tests pin the pure
rules (code shape, expiry, attempt and resend limits), the SMTP hand-off, and
the HTTP contract the frontend relies on.  The SQL itself is exercised against
a real Postgres in ``test_email_verification_db.py``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api
import email_delivery
import web_auth
from web_auth import WebUser

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _user(*, verified: bool = True, email: str = "reader@example.test") -> WebUser:
    return WebUser(
        id=101, email=email, full_name="Reader", avatar_data_url=None,
        created_at=NOW, last_login_at=None, is_active=True, email_verified=verified,
    )


# ── pure code rules ─────────────────────────────────────────────────────────

def test_codes_are_six_random_digits():
    codes = {web_auth.new_email_code() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 150  # not a constant, not a tiny space


def test_code_hash_is_salted_and_verifiable():
    salt_a, salt_b = "aa" * 16, "bb" * 16
    assert web_auth.email_code_hash(salt_a, "123456") != web_auth.email_code_hash(salt_b, "123456")
    assert web_auth.email_code_hash(salt_a, "123456") == web_auth.email_code_hash(salt_a, "123456")
    assert "123456" not in web_auth.email_code_hash(salt_a, "123456")


def _row(code="123456", *, attempts=0, expires_in=600, sent_ago=10, sends=1, window_ago=10):
    salt = "cd" * 16
    return {
        "salt": salt,
        "code_hash": web_auth.email_code_hash(salt, code),
        "attempts": attempts,
        "expires_at": NOW + timedelta(seconds=expires_in),
        "sent_at": NOW - timedelta(seconds=sent_ago),
        "send_count": sends,
        "window_started_at": NOW - timedelta(seconds=window_ago),
    }


def test_correct_code_is_accepted():
    assert web_auth.check_email_code(_row(), "123456", NOW) == "ok"


def test_code_check_ignores_spaces_and_dashes_the_user_types():
    assert web_auth.check_email_code(_row(), " 123-456 ", NOW) == "ok"


def test_wrong_code_is_rejected():
    assert web_auth.check_email_code(_row(), "654321", NOW) == "invalid"


def test_expired_code_is_rejected_even_if_correct():
    assert web_auth.check_email_code(_row(expires_in=-1), "123456", NOW) == "expired"


def test_code_is_dead_after_max_attempts_even_if_correct():
    row = _row(attempts=web_auth.EMAIL_CODE_MAX_ATTEMPTS)
    assert web_auth.check_email_code(row, "123456", NOW) == "locked"


def test_missing_code_row_is_invalid():
    assert web_auth.check_email_code(None, "123456", NOW) == "invalid"


def test_first_send_is_allowed():
    assert web_auth.email_code_send_wait(None, NOW) == 0


def test_resend_within_cooldown_waits_for_the_remainder():
    wait = web_auth.email_code_send_wait(_row(sent_ago=20), NOW)
    assert wait == web_auth.EMAIL_CODE_RESEND_SECONDS - 20


def test_resend_after_cooldown_is_allowed():
    assert web_auth.email_code_send_wait(_row(sent_ago=web_auth.EMAIL_CODE_RESEND_SECONDS), NOW) == 0


def test_hourly_send_cap_blocks_until_the_window_ends():
    row = _row(sent_ago=600, sends=web_auth.EMAIL_CODE_MAX_SENDS_PER_HOUR, window_ago=1800)
    assert web_auth.email_code_send_wait(row, NOW) == 3600 - 1800


def test_hourly_send_cap_resets_after_the_window():
    row = _row(sent_ago=600, sends=web_auth.EMAIL_CODE_MAX_SENDS_PER_HOUR, window_ago=3601)
    assert web_auth.email_code_send_wait(row, NOW) == 0


# ── mail delivery ───────────────────────────────────────────────────────────

class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, **kwargs):
        self.host, self.port, self.timeout = host, port, timeout
        self.started_tls = False
        self.login_args = None
        self.sent = []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, message):
        self.sent.append(message)


@pytest.fixture
def smtp_env(monkeypatch):
    _FakeSMTP.instances = []
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "secret-value")
    monkeypatch.setenv("SMTP_FROM", "UZ Stock <no-reply@uzstock.uz>")
    monkeypatch.delenv("SMTP_SECURITY", raising=False)
    monkeypatch.delenv("EMAIL_VERIFICATION", raising=False)
    monkeypatch.setattr(email_delivery.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(email_delivery.smtplib, "SMTP_SSL", _FakeSMTP)


def test_verification_is_off_without_smtp_settings(monkeypatch):
    for key in ("SMTP_HOST", "SMTP_FROM"):
        monkeypatch.delenv(key, raising=False)
    assert not email_delivery.is_configured()
    assert not email_delivery.verification_enabled()


def test_verification_turns_on_with_smtp_settings(smtp_env):
    assert email_delivery.is_configured()
    assert email_delivery.verification_enabled()


def test_verification_can_be_switched_off_explicitly(smtp_env, monkeypatch):
    monkeypatch.setenv("EMAIL_VERIFICATION", "off")
    assert not email_delivery.verification_enabled()


def test_send_code_uses_starttls_login_and_carries_the_code(smtp_env):
    email_delivery.send_code("reader@example.test", "verify", "482913", "ru")
    smtp = _FakeSMTP.instances[-1]
    assert (smtp.host, smtp.port) == ("smtp.example.test", 587)
    assert smtp.started_tls
    assert smtp.login_args == ("mailer", "secret-value")
    message = smtp.sent[-1]
    assert message["To"] == "reader@example.test"
    assert "no-reply@uzstock.uz" in message["From"]
    assert "482913" in message["Subject"]
    assert "482913" in message.get_body(("plain",)).get_content()
    assert "482913" in message.get_body(("html",)).get_content()


def test_ssl_mode_skips_starttls(smtp_env, monkeypatch):
    monkeypatch.setenv("SMTP_SECURITY", "ssl")
    monkeypatch.setenv("SMTP_PORT", "465")
    email_delivery.send_code("reader@example.test", "verify", "482913", "en")
    assert not _FakeSMTP.instances[-1].started_tls


@pytest.mark.parametrize("purpose", ["verify", "reset"])
@pytest.mark.parametrize("language", ["ru", "uz", "en", "xx"])
def test_every_language_and_purpose_renders_the_code(purpose, language):
    subject, text, html = email_delivery.render_code_email(purpose, "123456", language)
    assert "123456" in subject and "123456" in text and "123456" in html


def test_reset_and_verify_mails_are_worded_differently():
    verify = email_delivery.render_code_email("verify", "123456", "en")
    reset = email_delivery.render_code_email("reset", "123456", "en")
    assert verify[0] != reset[0]


def test_smtp_failure_raises_a_delivery_error(smtp_env, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("connection refused")
    monkeypatch.setattr(email_delivery.smtplib, "SMTP", boom)
    with pytest.raises(email_delivery.EmailDeliveryError):
        email_delivery.send_code("reader@example.test", "verify", "123456", "ru")


# ── HTTP contract ───────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "_enforce_auth_rate_limit", lambda request, scope: None)
    return TestClient(api.app)


@pytest.fixture
def mail(monkeypatch):
    """Verification on; capture outgoing codes instead of sending them."""
    sent: list[tuple[str, str, str, str]] = []
    monkeypatch.setattr(api.email_delivery, "verification_enabled", lambda: True)
    monkeypatch.setattr(api.email_delivery, "send_code",
                        lambda to, purpose, code, language="ru": sent.append((to, purpose, code, language)))
    return sent


def test_register_without_mail_configured_keeps_the_old_instant_login(client, monkeypatch):
    monkeypatch.setattr(api.email_delivery, "verification_enabled", lambda: False)
    monkeypatch.setattr(api.web_auth_store, "register_user",
                        lambda *args, **kwargs: (_user(verified=False), "tok-1"))
    response = client.post("/api/auth/register",
                           json={"email": "reader@example.test", "password": "long-password"})
    assert response.status_code == 200
    assert response.json()["token"] == "tok-1"


def test_register_sends_a_code_and_issues_no_session(client, mail, monkeypatch):
    calls = {}

    def start(email, password, full_name=""):
        calls["args"] = (email, password, full_name)
        return "123456"
    monkeypatch.setattr(api.web_auth_store, "start_registration", start)
    monkeypatch.setattr(api.web_auth_store, "register_user",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not log in")))

    response = client.post("/api/auth/register", json={
        "email": "Reader@Example.test", "password": "long-password", "full_name": "R", "language": "uz"})

    assert response.status_code == 200
    body = response.json()
    assert body["verification_required"] is True
    assert body["email"] == "reader@example.test"
    assert "token" not in body
    assert calls["args"] == ("Reader@Example.test", "long-password", "R")
    assert mail == [("reader@example.test", "verify", "123456", "uz")]


def test_register_of_a_verified_address_is_a_conflict(client, mail, monkeypatch):
    def start(*args, **kwargs):
        raise ValueError("Email already registered")
    monkeypatch.setattr(api.web_auth_store, "start_registration", start)
    response = client.post("/api/auth/register",
                           json={"email": "reader@example.test", "password": "long-password"})
    assert response.status_code == 409
    assert mail == []


def test_register_during_resend_cooldown_still_points_to_the_code_screen(client, mail, monkeypatch):
    def start(*args, **kwargs):
        raise web_auth.EmailCodeThrottled(42)
    monkeypatch.setattr(api.web_auth_store, "start_registration", start)
    response = client.post("/api/auth/register",
                           json={"email": "reader@example.test", "password": "long-password"})
    assert response.status_code == 200
    assert response.json()["verification_required"] is True
    assert response.json()["retry_after"] == 42
    assert mail == []


def test_register_reports_mail_outage_as_503(client, monkeypatch):
    monkeypatch.setattr(api.email_delivery, "verification_enabled", lambda: True)
    monkeypatch.setattr(api.web_auth_store, "start_registration", lambda *a, **k: "123456")

    def fail(*args, **kwargs):
        raise email_delivery.EmailDeliveryError("smtp down")
    monkeypatch.setattr(api.email_delivery, "send_code", fail)
    response = client.post("/api/auth/register",
                           json={"email": "reader@example.test", "password": "long-password"})
    assert response.status_code == 503


def test_login_with_an_unverified_email_sends_a_code_instead_of_a_session(client, mail, monkeypatch):
    seen = {}

    def login(email, password, otp=None, user_agent=None, ip_address=None, *, require_verified_email=False):
        seen["require"] = require_verified_email
        raise web_auth.EmailNotVerified("reader@example.test")
    monkeypatch.setattr(api.web_auth_store, "login_user", login)
    monkeypatch.setattr(api.web_auth_store, "issue_email_code", lambda email, purpose: "777111")

    response = client.post("/api/auth/login",
                           json={"email": "reader@example.test", "password": "long-password"})

    assert response.status_code == 200
    body = response.json()
    assert body["verification_required"] is True and "token" not in body
    assert seen["require"] is True
    assert mail == [("reader@example.test", "verify", "777111", "ru")]


def test_login_of_a_verified_user_is_unchanged(client, mail, monkeypatch):
    monkeypatch.setattr(api.web_auth_store, "login_user", lambda *a, **k: (_user(), "tok-2"))
    response = client.post("/api/auth/login",
                           json={"email": "reader@example.test", "password": "long-password"})
    assert response.status_code == 200
    assert response.json()["token"] == "tok-2"
    assert mail == []


def test_verify_returns_a_session_and_forwards_the_chosen_password(client, mail, monkeypatch):
    seen = {}

    def verify(email, code, password=None, full_name=None, user_agent=None, ip_address=None):
        seen["args"] = (email, code, password, full_name)
        return _user(), "tok-3"
    monkeypatch.setattr(api.web_auth_store, "verify_email_code", verify)
    response = client.post("/api/auth/email/verify", json={
        "email": "reader@example.test", "code": "123456", "password": "long-password", "full_name": "R"})
    assert response.status_code == 200
    assert response.json()["token"] == "tok-3"
    assert response.json()["user"]["email_verified"] is True
    assert seen["args"] == ("reader@example.test", "123456", "long-password", "R")


def test_verify_for_a_two_factor_account_asks_to_sign_in_again(client, mail, monkeypatch):
    monkeypatch.setattr(api.web_auth_store, "verify_email_code",
                        lambda *a, **k: (_user(), None))
    response = client.post("/api/auth/email/verify",
                           json={"email": "reader@example.test", "code": "123456"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "verified": True, "sign_in_required": True}


def test_verify_with_a_bad_code_is_400(client, mail, monkeypatch):
    def bad(*args, **kwargs):
        raise ValueError("Invalid or expired code")
    monkeypatch.setattr(api.web_auth_store, "verify_email_code", bad)
    response = client.post("/api/auth/email/verify",
                           json={"email": "reader@example.test", "code": "000000"})
    assert response.status_code == 400


def test_resend_never_reveals_whether_an_account_exists(client, mail, monkeypatch):
    monkeypatch.setattr(api.web_auth_store, "issue_email_code", lambda email, purpose: None)
    unknown = client.post("/api/auth/email/resend", json={"email": "nobody@example.test"})
    monkeypatch.setattr(api.web_auth_store, "issue_email_code",
                        lambda email, purpose: (_ for _ in ()).throw(web_auth.EmailCodeThrottled(30)))
    throttled = client.post("/api/auth/email/resend", json={"email": "reader@example.test"})
    assert unknown.status_code == throttled.status_code == 200
    assert unknown.json() == throttled.json() == {"ok": True}
    assert mail == []


def test_forgot_password_sends_a_reset_code_and_reveals_nothing(client, mail, monkeypatch):
    monkeypatch.setattr(api.web_auth_store, "issue_email_code",
                        lambda email, purpose: "246810" if email == "reader@example.test" else None)
    known = client.post("/api/auth/password/forgot", json={"email": "reader@example.test", "language": "en"})
    unknown = client.post("/api/auth/password/forgot", json={"email": "nobody@example.test"})
    assert known.json() == unknown.json() == {"ok": True}
    assert mail == [("reader@example.test", "reset", "246810", "en")]


def test_forgot_password_without_mail_is_unavailable(client, monkeypatch):
    monkeypatch.setattr(api.email_delivery, "verification_enabled", lambda: False)
    response = client.post("/api/auth/password/forgot", json={"email": "reader@example.test"})
    assert response.status_code == 503


def test_password_reset_returns_a_fresh_session(client, mail, monkeypatch):
    seen = {}

    def reset(email, code, new_password, user_agent=None, ip_address=None):
        seen["args"] = (email, code, new_password)
        return _user(), "tok-4"
    monkeypatch.setattr(api.web_auth_store, "reset_password_with_code", reset)
    response = client.post("/api/auth/password/reset", json={
        "email": "reader@example.test", "code": "246810", "new_password": "brand-new-pass"})
    assert response.status_code == 200
    assert response.json()["token"] == "tok-4"
    assert seen["args"] == ("reader@example.test", "246810", "brand-new-pass")


def test_password_reset_rejects_a_short_password(client, mail):
    response = client.post("/api/auth/password/reset", json={
        "email": "reader@example.test", "code": "246810", "new_password": "short"})
    assert response.status_code == 422


def test_password_reset_with_a_bad_code_is_400(client, mail, monkeypatch):
    def bad(*args, **kwargs):
        raise ValueError("Invalid or expired code")
    monkeypatch.setattr(api.web_auth_store, "reset_password_with_code", bad)
    response = client.post("/api/auth/password/reset", json={
        "email": "reader@example.test", "code": "000000", "new_password": "brand-new-pass"})
    assert response.status_code == 400


# ── admin access needs a proven inbox ───────────────────────────────────────

def test_unverified_admin_email_gets_no_admin_role_when_verification_is_on(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.test")
    monkeypatch.setattr(api.email_delivery, "verification_enabled", lambda: True)
    assert api._admin_role(_user(verified=True, email="boss@example.test")) == "administrator"
    assert api._admin_role(_user(verified=False, email="boss@example.test")) is None


def test_admin_role_is_unchanged_while_verification_is_off(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.test")
    monkeypatch.setattr(api.email_delivery, "verification_enabled", lambda: False)
    assert api._admin_role(_user(verified=False, email="boss@example.test")) == "administrator"


def test_unverified_admin_is_refused_by_the_admin_panel(client, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.test")
    monkeypatch.setattr(api.email_delivery, "verification_enabled", lambda: True)
    monkeypatch.setattr(api.web_auth_store, "get_user_by_token",
                        lambda token: _user(verified=False, email="boss@example.test"))
    response = client.get("/api/admin/users", headers={"Authorization": "Bearer t"})
    assert response.status_code == 403


def test_auth_options_tell_the_page_whether_email_codes_work(client, monkeypatch):
    monkeypatch.setattr(api.email_delivery, "verification_enabled", lambda: True)
    assert client.get("/api/auth/options").json() == {"ok": True, "email_codes": True}
    monkeypatch.setattr(api.email_delivery, "verification_enabled", lambda: False)
    assert client.get("/api/auth/options").json() == {"ok": True, "email_codes": False}
