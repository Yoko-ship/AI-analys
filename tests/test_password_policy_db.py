"""Account lockout, silent rehash and stored-password policy against a real Postgres.

Skipped unless ``TEST_DATABASE_URL`` points at a disposable database — every
test drops and recreates the web_* tables.  Never point it at production.
"""
from __future__ import annotations

import os

import pytest

import password_policy
import web_auth

URL = os.getenv("TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not set")

EMAIL = "reader@example.test"
GOOD = "Tree-Lamp-Violin-42"


@pytest.fixture
def store():
    from psycopg import connect
    with connect(URL, autocommit=True) as conn:
        for (table,) in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'web_%'"
        ).fetchall():
            conn.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    return web_auth.WebAuthStore(URL)


def _column(store, column):
    with store._conn() as conn:
        return conn.execute(f"SELECT {column} FROM web_users WHERE email = %s", (EMAIL,)).fetchone()[column]


def _fail(store, times):
    for _ in range(times):
        with pytest.raises(ValueError):
            store.login_user(EMAIL, "wrong-password-9")


# ── the store enforces the policy too, not only the API ─────────────────────

def test_weak_passwords_are_refused_by_every_setter(store):
    with pytest.raises(password_policy.WeakPassword):
        store.register_user(EMAIL, "12345678")
    with pytest.raises(password_policy.WeakPassword):
        store.start_registration(EMAIL, "password1")
    store.register_user(EMAIL, GOOD, "Azamxon Gapparov")
    code = store.issue_email_code(EMAIL, "reset")
    with pytest.raises(password_policy.WeakPassword):
        store.reset_password_with_code(EMAIL, code, "qwertyuiop")
    with pytest.raises(password_policy.WeakPassword) as exc:
        store.change_password(_column(store, "id"), GOOD, "azamxon-2026", "no-token")
    assert exc.value.code == "personal"


# ── stronger hashing, applied silently at the next login ────────────────────

def test_login_upgrades_an_old_hash(store):
    store.register_user(EMAIL, GOOD)
    with store._conn() as conn:
        conn.execute("UPDATE web_users SET password_hash = %s WHERE email = %s",
                     (web_auth._password_hash(GOOD, iterations=210_000), EMAIL))
    assert _column(store, "password_hash").split("$")[1] == "210000"
    store.login_user(EMAIL, GOOD)
    assert _column(store, "password_hash").split("$")[1] == str(web_auth.PBKDF2_ITERATIONS)
    store.login_user(EMAIL, GOOD)  # the upgraded hash still verifies


# ── per-account lockout ─────────────────────────────────────────────────────

def test_ten_wrong_passwords_lock_the_account(store):
    store.register_user(EMAIL, GOOD)
    _fail(store, web_auth.LOGIN_FAILURE_LIMIT - 1)
    with pytest.raises(web_auth.AccountLocked) as exc:
        store.login_user(EMAIL, "wrong-password-9")
    assert exc.value.newly_locked
    assert 0 < exc.value.retry_after <= web_auth.LOGIN_LOCK_MINUTES * 60
    # While locked even the right password is refused, and no new notice is due.
    with pytest.raises(web_auth.AccountLocked) as again:
        store.login_user(EMAIL, GOOD)
    assert not again.value.newly_locked


def test_the_lock_expires_and_a_success_clears_the_counter(store):
    store.register_user(EMAIL, GOOD)
    _fail(store, web_auth.LOGIN_FAILURE_LIMIT - 1)
    with pytest.raises(web_auth.AccountLocked):
        store.login_user(EMAIL, "wrong-password-9")
    with store._conn() as conn:
        conn.execute("UPDATE web_users SET locked_until = NOW() - INTERVAL '1 second' WHERE email = %s", (EMAIL,))
    store.login_user(EMAIL, GOOD)
    assert _column(store, "failed_login_count") == 0
    _fail(store, web_auth.LOGIN_FAILURE_LIMIT - 1)  # a fresh budget, not one attempt left


def test_old_failures_fall_out_of_the_window(store):
    store.register_user(EMAIL, GOOD)
    _fail(store, web_auth.LOGIN_FAILURE_LIMIT - 1)
    with store._conn() as conn:
        conn.execute("UPDATE web_users SET failed_login_started = NOW() - INTERVAL '16 minutes' WHERE email = %s", (EMAIL,))
    _fail(store, 1)
    assert _column(store, "failed_login_count") == 1


def test_password_reset_unlocks_the_account(store):
    store.register_user(EMAIL, GOOD)
    _fail(store, web_auth.LOGIN_FAILURE_LIMIT - 1)
    with pytest.raises(web_auth.AccountLocked):
        store.login_user(EMAIL, "wrong-password-9")
    code = store.issue_email_code(EMAIL, "reset")
    store.reset_password_with_code(EMAIL, code, "Violin-Lamp-Tree-77")
    store.login_user(EMAIL, "Violin-Lamp-Tree-77")


def test_the_lock_notice_uses_the_owners_language(store):
    store.register_user(EMAIL, GOOD)
    store.update_preferences(_column(store, "id"), {"language": "uz"})
    _fail(store, web_auth.LOGIN_FAILURE_LIMIT - 1)
    with pytest.raises(web_auth.AccountLocked) as exc:
        store.login_user(EMAIL, "wrong-password-9")
    assert exc.value.language == "uz"


def test_unknown_addresses_fail_like_wrong_passwords(store):
    with pytest.raises(ValueError, match="Invalid email or password"):
        store.login_user("nobody@example.test", "wrong-password-9")
