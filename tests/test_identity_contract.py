"""Behavior contracts recorded before splitting the authentication store.

The connection double checks transaction boundaries and persisted arguments;
it does not substitute for a PostgreSQL integration test.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import web_auth as auth
import identity.clock as identity_clock
import identity.credentials as identity_credentials
import identity.settings as identity_settings
import identity.sessions as identity_sessions


NOW = datetime(2026, 9, 26, 10, tzinfo=timezone.utc)
TOKEN = "example-session-token"
PASSWORD = "correct-password"


class Connection:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []
        self.exits = []

    def __enter__(self):
        return self

    def __exit__(self, exception_type, *_):
        self.exits.append(exception_type)

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))
        result = self.results.pop(0) if self.results else None
        return SimpleNamespace(fetchone=lambda: result, fetchall=lambda: result or [], rowcount=1)


def user_row(**changes):
    return dict(id=7, email="person@example.test", full_name="Person", avatar_data_url=None,
                created_at=NOW, last_login_at=None, is_active=True, tier="pro",
                email_verified=True, subscription_until=NOW + timedelta(days=5),
                password_hash=identity_credentials._password_hash(PASSWORD, salt=b"0123456789abcdef"), **changes)


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(identity_settings, "DATABASE_URL", "")
    monkeypatch.setattr(identity_clock, "_utcnow", lambda: NOW)
    monkeypatch.setattr(identity_sessions.secrets, "token_urlsafe", lambda _: TOKEN)
    return auth.WebAuthStore()


def connect(monkeypatch, store, *results):
    connection = Connection(*results)
    monkeypatch.setattr(store.database, "connect", lambda: connection)
    return connection


def test_password_encoding_roundtrip_and_rejection():
    encoded = identity_credentials._password_hash(PASSWORD, salt=b"0123456789abcdef")
    assert identity_credentials._password_verify(PASSWORD, encoded)
    assert not identity_credentials._password_verify("wrong", encoded)
    for invalid in ("", "invalid", "unknown$1$ab$cd", "pbkdf2_sha256$NaN$ab$cd"):
        assert not identity_credentials._password_verify(PASSWORD, invalid)
    assert PASSWORD not in encoded


def test_totp_known_vector_and_window():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # gitleaks:allow — public RFC 6238 test vector
    moment = datetime.fromtimestamp(59, timezone.utc)
    assert identity_credentials._totp_code(secret, moment) == "287082"
    assert identity_credentials._verify_totp(secret, "287082", moment + timedelta(seconds=30))
    assert not identity_credentials._verify_totp(secret, "287082", moment + timedelta(seconds=90))
    assert not identity_credentials._verify_totp(secret, "123", moment)


def test_login_issues_only_hashed_session_and_preserves_entitlement(monkeypatch, store):
    connection = connect(monkeypatch, store, user_row())
    user, token = store.accounts.login_user(" PERSON@EXAMPLE.TEST ", PASSWORD, user_agent="a" * 800, ip_address="b" * 200)
    assert (user.email, user.tier, token) == ("person@example.test", "pro", TOKEN)
    assert user.has_pro_access
    assert connection.calls[0][1] == ("person@example.test",)
    _, params = next(call for call in connection.calls if "INSERT INTO web_sessions" in call[0])
    assert params == (7, identity_credentials._token_hash(TOKEN), NOW + timedelta(days=identity_settings.SESSION_TTL_DAYS), "a" * 500, "b" * 120, NOW)
    assert TOKEN not in str(connection.calls)
    assert connection.exits == [None]


@pytest.mark.parametrize("kind", ["missing", "inactive", "wrong_password", "missing_otp", "wrong_otp"])
def test_rejected_login_never_issues_session(monkeypatch, store, kind):
    row = user_row()
    if kind == "missing": row = None
    elif kind == "inactive": row["is_active"] = False
    elif kind.endswith("otp"):
        row.update(two_factor_enabled=True, two_factor_secret="GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")  # gitleaks:allow — same public RFC vector
    connection = connect(monkeypatch, store, row)
    with pytest.raises(ValueError):
        store.accounts.login_user("person@example.test", "wrong" if kind == "wrong_password" else PASSWORD,
                         otp="invalid" if kind == "wrong_otp" else None)
    assert not any("INSERT INTO web_sessions" in sql for sql, _ in connection.calls)
    assert connection.exits == [None]
    if kind in {"wrong_password", "wrong_otp"}:
        assert any("failed_login_count" in sql and sql.startswith("UPDATE") for sql, _ in connection.calls)


def test_token_lookup_filters_revoked_expired_inactive_accounts(monkeypatch, store):
    connection = connect(monkeypatch, store, None)
    assert store.sessions.get_user_by_token(TOKEN) is None
    sql, params = connection.calls[0]
    assert "revoked_at IS NULL" in sql and "expires_at > %s" in sql and "u.is_active = TRUE" in sql
    assert params == (identity_credentials._token_hash(TOKEN), NOW)
    assert len(connection.calls) == 1


def test_successful_token_lookup_updates_last_seen(monkeypatch, store):
    connection = connect(monkeypatch, store, user_row())
    assert store.sessions.get_user_by_token(TOKEN).id == 7
    assert connection.calls[1][1] == (NOW, identity_credentials._token_hash(TOKEN))


def test_session_listing_never_discloses_hash(monkeypatch, store):
    connection = connect(monkeypatch, store, [dict(id=3, token_hash=identity_credentials._token_hash(TOKEN), created_at=NOW,
        expires_at=NOW + timedelta(days=1), revoked_at=None, last_seen_at=None, user_agent="Browser", ip_address=None)])
    sessions = store.sessions.list_sessions(7, TOKEN)
    assert sessions[0]["current"] is True
    assert "token_hash" not in sessions[0]
    assert connection.calls[0][1] == (7, NOW)


def test_revoke_session_restricts_owner_and_preserves_current(monkeypatch, store):
    connection = connect(monkeypatch, store)
    assert store.sessions.revoke_session(7, 4, TOKEN)
    sql, params = connection.calls[0]
    assert "id = %s AND user_id = %s" in sql
    assert params == (NOW, 4, 7, identity_credentials._token_hash(TOKEN), identity_credentials._token_hash(TOKEN))


def test_change_password_revokes_other_sessions_in_same_transaction(monkeypatch, store):
    connection = connect(monkeypatch, store, user_row())
    assert store.security.change_password(7, PASSWORD, "new-password", TOKEN) == 1
    assert identity_credentials._password_verify("new-password", connection.calls[1][1][0])
    assert connection.calls[2][1] == (NOW, 7, identity_credentials._token_hash(TOKEN))
    assert connection.exits == [None]


@pytest.mark.parametrize("updates", [{"language": "xx"}, {"theme": "neon"}, {"default_analysis_period": "all"}])
def test_invalid_preferences_do_not_touch_database(monkeypatch, store, updates):
    connection = connect(monkeypatch, store)
    with pytest.raises(ValueError): store.profile.update_preferences(7, updates)
    assert not connection.calls


def test_preferences_whitelist_and_clamp(monkeypatch, store):
    connection = connect(monkeypatch, store, {"preferences": {"text_scale": 130, "language": "en"}})
    prefs = store.profile.update_preferences(7, {"text_scale": 999, "language": "en", "tier": "pro"})
    assert prefs["text_scale"] == 130 and prefs["language"] == "en"
    assert '"tier"' not in connection.calls[0][1][0]


def test_unconfigured_auth_fails_closed(store):
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        store.sessions.get_user_by_token(TOKEN)


def test_saved_research_uses_owner_scope_and_preserves_zero_values(monkeypatch, store):
    connection = connect(monkeypatch, store, {"id": 11, "company_input": "AGBA", "score": 0,
        "cost": 0, "tags": ["review"], "created_at": NOW, "bookmarked": True})
    item = store.research.get_analysis(7, 11)
    assert item["id"] == 11 and item["score"] == 0 and item["cost"] == 0
    assert item["tags"] == ["review"] and item["bookmarked"] is True
    assert item["created_at"] == NOW.isoformat()
    assert "user_id" in connection.calls[0][0]
    assert set(connection.calls[0][1]) == {7, 11}
