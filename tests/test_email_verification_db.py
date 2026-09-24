"""Email verification and password reset against a real Postgres.

Skipped unless ``TEST_DATABASE_URL`` points at a disposable database — every
test drops and recreates the web_* tables.  Never point it at production.
"""
from __future__ import annotations

import os
from datetime import timedelta

import pytest

import web_auth

URL = os.getenv("TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not set")

EMAIL = "reader@example.test"


@pytest.fixture
def store():
    from psycopg import connect
    with connect(URL, autocommit=True) as conn:
        tables = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'web_%'"
        ).fetchall()
        for (table,) in tables:
            conn.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    return web_auth.WebAuthStore(URL)


def _code_row(store, email=EMAIL, purpose="verify"):
    with store._conn() as conn:
        return conn.execute(
            """
            SELECT c.* FROM web_email_codes c JOIN web_users u ON u.id = c.user_id
            WHERE u.email = %s AND c.purpose = %s
            """,
            (email, purpose),
        ).fetchone()


def _age_code(store, seconds, purpose="verify"):
    """Pretend the last code was sent ``seconds`` ago (clears the resend cooldown)."""
    with store._conn() as conn:
        conn.execute(
            "UPDATE web_email_codes SET sent_at = sent_at - %s WHERE purpose = %s",
            (timedelta(seconds=seconds), purpose),
        )


def _sessions(store, email=EMAIL):
    with store._conn() as conn:
        return conn.execute(
            """
            SELECT s.* FROM web_sessions s JOIN web_users u ON u.id = s.user_id
            WHERE u.email = %s AND s.revoked_at IS NULL
            """,
            (email,),
        ).fetchall()


# ── registration ────────────────────────────────────────────────────────────

def test_registration_creates_an_unverified_account_without_a_session(store):
    code = store.start_registration(EMAIL, "long-password", "Reader")
    assert len(code) == 6
    user = store.get_user_by_email(EMAIL)
    assert user is not None and not user.email_verified
    assert _sessions(store) == []
    row = _code_row(store)
    assert code not in str(row["code_hash"])  # only the hash is stored


def test_correct_code_verifies_and_signs_in(store):
    code = store.start_registration(EMAIL, "long-password", "Reader")
    user, token = store.verify_email_code(EMAIL, code)
    assert user.email_verified and token
    assert store.get_user_by_token(token).id == user.id
    assert _code_row(store) is None  # single use


def test_code_cannot_be_used_twice(store):
    code = store.start_registration(EMAIL, "long-password")
    store.verify_email_code(EMAIL, code)
    with pytest.raises(ValueError):
        store.verify_email_code(EMAIL, code)


def test_wrong_codes_lock_the_code_after_the_attempt_limit(store):
    code = store.start_registration(EMAIL, "long-password")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(web_auth.EMAIL_CODE_MAX_ATTEMPTS):
        with pytest.raises(ValueError):
            store.verify_email_code(EMAIL, wrong)
    with pytest.raises(ValueError):
        store.verify_email_code(EMAIL, code)  # right code, too late
    assert not store.get_user_by_email(EMAIL).email_verified


def test_expired_code_is_refused(store):
    code = store.start_registration(EMAIL, "long-password")
    with store._conn() as conn:
        conn.execute("UPDATE web_email_codes SET expires_at = NOW() - INTERVAL '1 second'")
    with pytest.raises(ValueError):
        store.verify_email_code(EMAIL, code)


def test_registering_a_verified_address_is_refused(store):
    code = store.start_registration(EMAIL, "long-password")
    store.verify_email_code(EMAIL, code)
    with pytest.raises(ValueError, match="already registered"):
        store.start_registration(EMAIL, "another-password")


def test_a_stranger_cannot_squat_an_address_they_do_not_own(store):
    """Someone registers the address first but never proves the inbox.  The real
    owner can still register; the browser that enters the code sets the
    password, and the squatter's password and sessions stop working."""
    _, squatter_token = store.register_user(EMAIL, "Kettle-Moon-58", "Squatter")
    owner_code = store.start_registration(EMAIL, "Violin-Lamp-Tree-77", "Owner")
    user, token = store.verify_email_code(EMAIL, owner_code, password="Violin-Lamp-Tree-77", full_name="Owner")
    assert token and user.full_name == "Owner"
    assert store.get_user_by_token(squatter_token) is None
    store.login_user(EMAIL, "Violin-Lamp-Tree-77", require_verified_email=True)
    with pytest.raises(ValueError):
        store.login_user(EMAIL, "Kettle-Moon-58", require_verified_email=True)


def test_a_squatter_re_registering_cannot_plant_a_password(store):
    """The owner's inbox receives the squatter's code too, but entering it sets
    the owner's own password, never the squatter's."""
    store.start_registration(EMAIL, "Violin-Lamp-Tree-77", "Owner")
    _age_code(store, web_auth.EMAIL_CODE_RESEND_SECONDS)
    latest = store.start_registration(EMAIL, "Kettle-Moon-58", "Squatter")
    store.verify_email_code(EMAIL, latest, password="Violin-Lamp-Tree-77", full_name="Owner")
    store.login_user(EMAIL, "Violin-Lamp-Tree-77", require_verified_email=True)
    with pytest.raises(ValueError):
        store.login_user(EMAIL, "Kettle-Moon-58")


def test_re_registering_does_not_change_the_password_before_verification(store):
    store.start_registration(EMAIL, "first-password")
    _age_code(store, web_auth.EMAIL_CODE_RESEND_SECONDS)
    store.start_registration(EMAIL, "second-password")
    # Unverified logins are refused, but the password check itself runs first:
    with pytest.raises(web_auth.EmailNotVerified):
        store.login_user(EMAIL, "first-password", require_verified_email=True)
    with pytest.raises(ValueError, match="Invalid email or password"):
        store.login_user(EMAIL, "second-password", require_verified_email=True)


def test_resend_is_throttled(store):
    store.start_registration(EMAIL, "long-password")
    with pytest.raises(web_auth.EmailCodeThrottled) as exc:
        store.issue_email_code(EMAIL, "verify")
    assert 0 < exc.value.retry_after <= web_auth.EMAIL_CODE_RESEND_SECONDS


def test_hourly_send_cap(store):
    store.start_registration(EMAIL, "long-password")
    for _ in range(web_auth.EMAIL_CODE_MAX_SENDS_PER_HOUR - 1):
        _age_code(store, web_auth.EMAIL_CODE_RESEND_SECONDS)
        assert store.issue_email_code(EMAIL, "verify")
    _age_code(store, web_auth.EMAIL_CODE_RESEND_SECONDS)
    with pytest.raises(web_auth.EmailCodeThrottled):
        store.issue_email_code(EMAIL, "verify")


def test_a_new_code_replaces_the_old_one(store):
    first = store.start_registration(EMAIL, "long-password")
    _age_code(store, web_auth.EMAIL_CODE_RESEND_SECONDS)
    second = store.issue_email_code(EMAIL, "verify")
    if first != second:
        with pytest.raises(ValueError):
            store.verify_email_code(EMAIL, first)
    store.verify_email_code(EMAIL, second)


def test_no_verify_code_for_unknown_or_verified_accounts(store):
    assert store.issue_email_code("nobody@example.test", "verify") is None
    code = store.start_registration(EMAIL, "long-password")
    store.verify_email_code(EMAIL, code)
    assert store.issue_email_code(EMAIL, "verify") is None


# ── login ───────────────────────────────────────────────────────────────────

def test_unverified_login_is_refused_only_when_required(store):
    store.start_registration(EMAIL, "long-password")
    with pytest.raises(web_auth.EmailNotVerified):
        store.login_user(EMAIL, "long-password", require_verified_email=True)
    user, token = store.login_user(EMAIL, "long-password")
    assert token and not user.email_verified


def test_unverified_login_with_a_wrong_password_is_a_plain_failure(store):
    store.start_registration(EMAIL, "long-password")
    with pytest.raises(ValueError, match="Invalid email or password"):
        store.login_user(EMAIL, "wrong-password", require_verified_email=True)


def test_legacy_register_user_still_works_when_mail_is_off(store):
    user, token = store.register_user(EMAIL, "long-password")
    assert token and not user.email_verified


# ── two-factor accounts are never signed in by a code alone ────────────────

def _enable_totp(store, email=EMAIL):
    with store._conn() as conn:
        conn.execute(
            "UPDATE web_users SET two_factor_enabled = TRUE, two_factor_secret = 'JBSWY3DPEHPK3PXP' WHERE email = %s",
            (email,),
        )


def test_verify_with_a_short_password_is_refused_before_spending_the_code(store):
    code = store.start_registration(EMAIL, "long-password")
    with pytest.raises(ValueError, match="at least 8"):
        store.verify_email_code(EMAIL, code, password="short")
    store.verify_email_code(EMAIL, code, password="long-password")


def test_verify_does_not_bypass_two_factor(store):
    code = store.start_registration(EMAIL, "long-password")
    _enable_totp(store)
    user, token = store.verify_email_code(EMAIL, code)
    assert user.email_verified and token is None


def test_reset_does_not_bypass_two_factor(store):
    store.start_registration(EMAIL, "long-password")
    _enable_totp(store)
    code = store.issue_email_code(EMAIL, "reset")
    user, token = store.reset_password_with_code(EMAIL, code, "brand-new-pass")
    assert token is None


# ── password reset ──────────────────────────────────────────────────────────

def test_reset_changes_the_password_revokes_sessions_and_signs_in(store):
    user, old_token = store.register_user(EMAIL, "old-password")
    code = store.issue_email_code(EMAIL, "reset")
    user, token = store.reset_password_with_code(EMAIL, code, "brand-new-pass")
    assert token and user.email_verified
    assert store.get_user_by_token(old_token) is None
    assert store.get_user_by_token(token) is not None
    store.login_user(EMAIL, "brand-new-pass", require_verified_email=True)
    with pytest.raises(ValueError):
        store.login_user(EMAIL, "old-password")


def test_reset_code_is_not_a_verify_code(store):
    store.start_registration(EMAIL, "long-password")
    reset_code = store.issue_email_code(EMAIL, "reset")
    verify_row = _code_row(store, purpose="verify")
    if web_auth.check_email_code(verify_row, reset_code, web_auth._utcnow()) != "ok":
        with pytest.raises(ValueError):
            store.verify_email_code(EMAIL, reset_code)


def test_reset_for_unknown_or_inactive_accounts_sends_nothing(store):
    assert store.issue_email_code("nobody@example.test", "reset") is None
    store.register_user(EMAIL, "long-password")
    with store._conn() as conn:
        conn.execute("UPDATE web_users SET is_active = FALSE WHERE email = %s", (EMAIL,))
    assert store.issue_email_code(EMAIL, "reset") is None


def test_reset_with_a_wrong_code_changes_nothing(store):
    store.register_user(EMAIL, "old-password")
    code = store.issue_email_code(EMAIL, "reset")
    wrong = "000000" if code != "000000" else "111111"
    with pytest.raises(ValueError):
        store.reset_password_with_code(EMAIL, wrong, "brand-new-pass")
    store.login_user(EMAIL, "old-password")


# ── Google sign-in and unproven accounts ────────────────────────────────────

def test_google_takeover_of_an_unverified_account_evicts_the_squatter(store):
    """The pre-hijack: a stranger registered the address with a password; the real
    owner then signs in with Google.  The owner gets the account, and the
    stranger's password and sessions stop working."""
    _, squatter_token = store.register_user(EMAIL, "Kettle-Moon-58")
    user, token = store.oauth_login("google", "g-1", EMAIL, "Owner", email_verified=True)
    assert user.email_verified and token
    assert store.get_user_by_token(squatter_token) is None
    with pytest.raises(ValueError):
        store.login_user(EMAIL, "Kettle-Moon-58")


def test_google_joins_a_verified_account_without_touching_its_password(store):
    code = store.start_registration(EMAIL, "long-password")
    _, first_token = store.verify_email_code(EMAIL, code)
    store.oauth_login("google", "g-1", EMAIL, "Owner", email_verified=True)
    assert store.get_user_by_token(first_token) is not None
    store.login_user(EMAIL, "long-password", require_verified_email=True)


def test_google_with_an_unverified_email_does_not_join_an_existing_account(store):
    store.register_user(EMAIL, "long-password")
    with pytest.raises(ValueError):
        store.oauth_login("google", "g-2", EMAIL, "Someone", email_verified=False)


def test_google_with_an_unverified_email_creates_an_unverified_account(store):
    user, token = store.oauth_login("google", "g-3", "new@example.test", "New", email_verified=False)
    assert token and not user.email_verified


def test_returning_google_user_still_signs_in(store):
    store.oauth_login("google", "g-4", EMAIL, "Owner", email_verified=True)
    user, token = store.oauth_login("google", "g-4", EMAIL, "Owner", email_verified=True)
    assert token and user.email_verified


def test_deleting_an_account_removes_its_codes(store):
    store.start_registration(EMAIL, "long-password")
    with store._conn() as conn:
        conn.execute("DELETE FROM web_users WHERE email = %s", (EMAIL,))
        left = conn.execute("SELECT COUNT(*) AS n FROM web_email_codes").fetchone()["n"]
    assert left == 0
