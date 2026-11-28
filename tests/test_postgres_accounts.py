"""Real PostgreSQL contracts. Each test owns a fresh, disposable schema.

Set TEST_POSTGRES_URL to a local test server; no production DB is used.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest


@pytest.fixture
def pg_store():
    dsn = os.environ.get("TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("TEST_POSTGRES_URL is not configured")
    config = conninfo_to_dict(dsn)
    if config.get("host") not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("TEST_POSTGRES_URL must point to a local disposable test server")
    schema = "qa_accounts_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        from web_auth import WebAuthStore
        yield WebAuthStore(make_conninfo(dsn, options=f"-c search_path={schema}"))
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_registration_login_and_reinitialization(pg_store):
    from web_auth import WebAuthStore
    user, token = pg_store.accounts.register_user(" Investor@Example.test ", "example-pass-123", "Investor")
    assert user.email == "investor@example.test"
    registration = _registration_record(pg_store, user.email)
    assert registration['registration_started_at'] == user.created_at
    assert registration['registration_completed_at'] >= user.created_at
    fresh = WebAuthStore(pg_store.database.database_url)
    assert fresh.sessions.get_user_by_token(token).id == user.id
    logged_in, second = fresh.accounts.login_user(user.email, "example-pass-123")
    assert logged_in.id == user.id and second != token
    assert _registration_record(fresh, user.email)['registration_completed_at'] == registration['registration_completed_at']
    with fresh.database.connect() as conn:
        row = conn.execute("SELECT password_hash FROM web_users WHERE id = %s", (user.id,)).fetchone()
    assert row["password_hash"] != "example-pass-123"
    with pytest.raises(ValueError):
        fresh.accounts.login_user(user.email, "wrong-password")
    with pytest.raises(ValueError, match="already registered"):
        fresh.accounts.register_user(user.email.upper(), "example-pass-123")


def _registration_record(store, email):
    with store.database.connect() as conn:
        return conn.execute(
            "SELECT email_verified, created_at, registration_started_at, registration_completed_at FROM web_users WHERE email = %s",
            (email,),
        ).fetchone()


def test_registration_completion_uses_first_proof_not_account_creation(pg_store, monkeypatch):
    from identity import clock
    started = datetime(2026, 11, 23, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(clock, '_utcnow', lambda: started)
    email = 'registration-timing@example.test'
    code = pg_store.accounts.start_registration(email, 'example-pass-123')
    row = _registration_record(pg_store, email)
    assert row['created_at'] == row['registration_started_at'] == started
    assert row['registration_completed_at'] is None
    wrong = '000000' if code != '000000' else '111111'
    with pytest.raises(ValueError):
        pg_store.accounts.verify_email_code(email, wrong)
    assert _registration_record(pg_store, email)['registration_completed_at'] is None

    completed = started + timedelta(minutes=5)
    monkeypatch.setattr(clock, '_utcnow', lambda: completed)
    user, token = pg_store.accounts.verify_email_code(email, code)
    assert user.email_verified and token
    assert _registration_record(pg_store, email)['registration_completed_at'] == completed

    monkeypatch.setattr(clock, '_utcnow', lambda: started + timedelta(days=1))
    reset = pg_store.accounts.issue_email_code(email, 'reset')
    pg_store.accounts.reset_password_with_code(email, reset, 'replacement-pass-456')
    pg_store.oauth.oauth_login('google', 'timing-1', email, email_verified=True)
    pg_store.oauth.oauth_login('google', 'timing-1', email, email_verified=True)
    assert _registration_record(pg_store, email)['registration_completed_at'] == completed


@pytest.mark.parametrize('path', ['new_oauth', 'pending_email', 'password_reset'])
def test_registration_completion_records_each_first_verification_path(pg_store, monkeypatch, path):
    from identity import clock
    started = datetime(2026, 11, 23, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(clock, '_utcnow', lambda: started)
    email = 'first-proof@example.test'
    if path in {'pending_email', 'password_reset'}:
        pg_store.accounts.start_registration(email, 'example-pass-123')
    if path != 'new_oauth':
        assert _registration_record(pg_store, email)['registration_completed_at'] is None
    completed = started + timedelta(minutes=2)
    monkeypatch.setattr(clock, '_utcnow', lambda: completed)
    if path == 'password_reset':
        code = pg_store.accounts.issue_email_code(email, 'reset')
        pg_store.accounts.reset_password_with_code(email, code, 'replacement-pass-456')
    else:
        pg_store.oauth.oauth_login('google', 'proof-1', email, email_verified=True)
    row = _registration_record(pg_store, email)
    assert row['email_verified'] and row['registration_completed_at'] == completed


def test_oauth_registration_completes_on_provider_identity_even_without_email_proof(pg_store, monkeypatch):
    from identity import clock
    started = datetime(2026, 11, 23, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(clock, '_utcnow', lambda: started)
    email = 'oauth-identity@example.test'
    user, token = pg_store.oauth.oauth_login('google', 'identity-1', email, email_verified=False)
    assert token and not user.email_verified
    row = _registration_record(pg_store, email)
    assert row['registration_started_at'] == row['registration_completed_at'] == started
    monkeypatch.setattr(clock, '_utcnow', lambda: started + timedelta(days=1))
    pg_store.oauth.oauth_login('google', 'identity-1', email, email_verified=True)
    assert _registration_record(pg_store, email)['registration_completed_at'] == started


@pytest.mark.parametrize('path', ['direct', 'oauth'])
def test_registration_completion_clock_is_sampled_after_account_and_session_creation(pg_store, monkeypatch, path):
    from itertools import count
    from identity import clock
    started = datetime(2026, 11, 23, 8, tzinfo=timezone.utc)
    ticks = count()
    monkeypatch.setattr(clock, '_utcnow', lambda: started + timedelta(seconds=next(ticks)))
    email = 'clock-order@example.test'
    if path == 'direct':
        user, _ = pg_store.accounts.register_user(email, 'example-pass-123')
    else:
        user, _ = pg_store.oauth.oauth_login('google', 'clock-1', email, email_verified=True)
    row = _registration_record(pg_store, email)
    assert row['registration_completed_at'] > row['registration_started_at'] == user.created_at


@pytest.mark.parametrize('path', ['password_reset', 'oauth_link', 'oauth_login'])
def test_legacy_verified_registration_is_not_redated_by_later_sign_in(pg_store, path):
    email = 'legacy-proof@example.test'
    if path == 'oauth_login':
        user, _ = pg_store.oauth.oauth_login('google', 'legacy-1', email, email_verified=True)
    else:
        code = pg_store.accounts.start_registration(email, 'example-pass-123')
        user, _ = pg_store.accounts.verify_email_code(email, code)
    with pg_store.database.connect() as conn:
        conn.execute('UPDATE web_users SET registration_started_at = NULL, registration_completed_at = NULL WHERE id = %s', (user.id,))
    if path == 'password_reset':
        code = pg_store.accounts.issue_email_code(email, 'reset')
        pg_store.accounts.reset_password_with_code(email, code, 'replacement-pass-456')
    else:
        pg_store.oauth.oauth_login('google', 'legacy-1', email, email_verified=True)
    assert _registration_record(pg_store, email)['registration_completed_at'] is None


@pytest.mark.parametrize('path', ['email_code', 'oauth_login'])
def test_legacy_unverified_account_does_not_get_a_guessed_registration_date(pg_store, path):
    email = 'legacy-unverified@example.test'
    if path == 'email_code':
        user, _ = pg_store.accounts.register_user(email, 'example-pass-123')
        code = pg_store.accounts.start_registration(email, 'example-pass-123')
    else:
        user, _ = pg_store.oauth.oauth_login('google', 'unknown-1', email, email_verified=False)
    with pg_store.database.connect() as conn:
        conn.execute('UPDATE web_users SET registration_started_at = NULL, registration_completed_at = NULL WHERE id = %s', (user.id,))
    if path == 'email_code':
        pg_store.accounts.verify_email_code(email, code)
    else:
        pg_store.oauth.oauth_login('google', 'unknown-1', email, email_verified=True)
    row = _registration_record(pg_store, email)
    assert row['email_verified'] and row['registration_completed_at'] is None


@pytest.mark.parametrize('path', ['email', 'oauth'])
def test_failed_sign_in_transaction_does_not_record_registration(pg_store, monkeypatch, path):
    email = 'rollback-proof@example.test'
    code = pg_store.accounts.start_registration(email, 'example-pass-123')

    def fail_session(*args, **kwargs):
        raise RuntimeError('simulated session persistence failure')

    monkeypatch.setattr(pg_store.sessions, '_issue_session', fail_session)
    with pytest.raises(RuntimeError, match='simulated session'):
        if path == 'email':
            pg_store.accounts.verify_email_code(email, code)
        else:
            pg_store.oauth.oauth_login('google', 'rollback-1', email, email_verified=True)
    row = _registration_record(pg_store, email)
    assert not row['email_verified'] and row['registration_completed_at'] is None


def test_registration_timestamp_migration_keeps_legacy_history_unknown(pg_store):
    from web_auth import WebAuthStore
    email = 'migration-proof@example.test'
    code = pg_store.accounts.start_registration(email, 'example-pass-123')
    pg_store.accounts.verify_email_code(email, code)
    with pg_store.database.connect() as conn:
        conn.execute('ALTER TABLE web_users DROP COLUMN registration_started_at, DROP COLUMN registration_completed_at')
    fresh = WebAuthStore(pg_store.database.database_url)
    assert _registration_record(fresh, email)['registration_completed_at'] is None
    assert _registration_record(fresh, email)['registration_started_at'] is None
    again = WebAuthStore(pg_store.database.database_url)
    assert _registration_record(again, email)['registration_completed_at'] is None


def test_saved_comparisons_persist_across_sessions_and_accounts_are_isolated(pg_store):
    from web_auth import WebAuthStore
    alice, token = pg_store.accounts.register_user('comparisons@example.test', 'example-pass-123')
    bob, _ = pg_store.accounts.register_user('other-comparisons@example.test', 'example-pass-123')
    payload = {'name': 'Bank coverage', 'tickers': ['hmkb', 'IPKY'], 'period': 'latest',
               'standard': 'NSBU', 'scope': 'separate', 'unit': 'billion'}
    saved = pg_store.comparisons.save(alice.id, payload)
    fresh = WebAuthStore(pg_store.database.database_url)
    assert fresh.sessions.get_user_by_token(token).id == alice.id
    assert fresh.comparisons.list(alice.id)[0]['id'] == saved['id']
    assert fresh.comparisons.list(alice.id)[0]['selection']['tickers'] == ['HMKB', 'IPKY']
    assert fresh.comparisons.list(bob.id) == []
    assert not fresh.comparisons.delete(bob.id, int(saved['id']))
    renamed = fresh.comparisons.save(alice.id, {**payload, 'name': 'Updated coverage'})
    assert renamed['id'] == saved['id'] and renamed['name'] == 'Updated coverage'
    assert len(fresh.comparisons.list(alice.id)) == 1
    exported = fresh.profile.export_user_data(alice.id, token)
    assert exported['saved_comparisons'][0]['id'] == saved['id']
    assert fresh.comparisons.delete(alice.id, int(saved['id']))
    assert pg_store.comparisons.list(alice.id) == []


def test_saved_comparison_limit_and_account_deletion_cascade(pg_store):
    user, _ = pg_store.accounts.register_user('comparison-limit@example.test', 'example-pass-123')
    payload = {'name': 'Coverage', 'tickers': ['HMKB', 'IPKY'], 'period': 'latest',
               'standard': 'NSBU', 'scope': 'separate', 'unit': 'billion'}
    for year in range(2000, 2050):
        pg_store.comparisons.save(user.id, {**payload, 'period': str(year)})
    with pytest.raises(ValueError, match='50'):
        pg_store.comparisons.save(user.id, payload)
    assert len(pg_store.comparisons.list(user.id)) == 50
    pg_store.comparisons.save(user.id, {**payload, 'period': '2000', 'name': 'Rename at limit'})
    assert pg_store.profile.delete_account(user.id, user.email, password='example-pass-123')
    with pg_store.database.connect() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM web_saved_comparisons WHERE user_id = %s', (user.id,)).fetchone()['n'] == 0


def test_comparison_last_seen_persists_and_stale_devices_cannot_overwrite_it(pg_store):
    from identity.comparisons import ComparisonChanged, snapshot_key
    user, _ = pg_store.accounts.register_user('seen-comparison@example.test', 'example-pass-123')
    other, _ = pg_store.accounts.register_user('seen-other@example.test', 'example-pass-123')
    payload = {'name': 'Coverage', 'tickers': ['HMKB', 'IPKY'], 'period': 'latest',
               'standard': 'NSBU', 'scope': 'separate', 'unit': 'billion'}
    first, second, third = {'version': 1}, {'version': 2}, {'version': 3}
    saved = pg_store.comparisons.save(user.id, payload, first)
    identifier = int(saved['id'])
    assert saved['has_baseline'] is True and saved['last_seen_at']
    assert pg_store.comparisons.get(other.id, identifier) is None
    assert pg_store.comparisons.mark_seen(other.id, identifier, second, snapshot_key(first)) is None
    pg_store.comparisons.mark_seen(user.id, identifier, second, snapshot_key(first))
    # Renaming the same selection must not erase unread changes.
    pg_store.comparisons.save(user.id, {**payload, 'name': 'Renamed'}, third)
    assert pg_store.comparisons.get(user.id, identifier)['seen_snapshot'] == second
    # The timestamp means last viewed, including views with unchanged figures.
    previous_view = pg_store.comparisons.get(user.id, identifier)['seen_at']
    pg_store.comparisons.mark_seen(user.id, identifier, second, snapshot_key(second))
    assert pg_store.comparisons.get(user.id, identifier)['seen_at'] > previous_view
    with pytest.raises(ComparisonChanged):
        pg_store.comparisons.mark_seen(user.id, identifier, third, snapshot_key(first))
    # Repeated acknowledgements are safe and leave the saved selection intact.
    assert pg_store.comparisons.mark_seen(user.id, identifier, second, snapshot_key(first))
    assert pg_store.comparisons.get(user.id, identifier)['seen_snapshot'] == second


def test_saved_comparisons_real_http_ownership_and_concurrent_devices(pg_store, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    import api
    import web_auth
    from server.comparison import service
    monkeypatch.setattr(service, 'compare', lambda *args, **kw: {'companies': [], 'currency': 'UZS'})
    monkeypatch.setattr(web_auth, 'web_auth_store', pg_store)
    alice, token = pg_store.accounts.register_user('comparison-http@example.test', 'example-pass-123')
    bob, other = pg_store.accounts.register_user('comparison-http-other@example.test', 'example-pass-123')
    payload = {'name': 'Bank coverage', 'tickers': ['HMKB', 'IPKY'], 'period': 'latest',
               'standard': 'NSBU', 'scope': 'separate', 'unit': 'billion'}
    client = TestClient(api.app)
    headers = {'Authorization': 'Bearer ' + token}
    stranger = {'Authorization': 'Bearer ' + other}
    first = client.post('/api/saved-comparisons', json=payload, headers=headers)
    assert first.status_code == 200
    identifier = first.json()['comparison']['id']
    assert client.get('/api/v2/saved-comparisons', headers=stranger).json()['comparisons'] == []
    assert client.delete('/api/saved-comparisons/' + identifier, headers=stranger).status_code == 404
    assert client.get('/api/v2/saved-comparisons', headers=headers).json()['comparisons'][0]['id'] == identifier
    # Simultaneous device saves of one selection produce one account entry.
    with ThreadPoolExecutor(max_workers=3) as pool:
        entries = list(pool.map(lambda _: pg_store.comparisons.save(alice.id, payload), range(3)))
    assert {e['id'] for e in entries} == {identifier}
    assert len(pg_store.comparisons.list(alice.id)) == 1
    assert client.delete('/api/v2/saved-comparisons/' + identifier, headers=headers).status_code == 200
    assert pg_store.comparisons.list(alice.id) == []


def test_password_change_revocation_expiry_and_inactive_user(pg_store):
    user, current = pg_store.accounts.register_user("sessions@example.test", "example-pass-123")
    _, other = pg_store.accounts.login_user(user.email, "example-pass-123")
    assert pg_store.security.change_password(user.id, "example-pass-123", "replacement-456", current) == 1
    assert pg_store.sessions.get_user_by_token(current).id == user.id
    assert pg_store.sessions.get_user_by_token(other) is None
    with pytest.raises(ValueError):
        pg_store.accounts.login_user(user.email, "example-pass-123")
    _, token = pg_store.accounts.login_user(user.email, "replacement-456")
    with pg_store.database.connect() as conn:
        conn.execute("UPDATE web_sessions SET expires_at = NOW() - INTERVAL '1 second' WHERE user_id = %s", (user.id,))
    assert pg_store.sessions.get_user_by_token(token) is None
    _, token = pg_store.accounts.login_user(user.email, "replacement-456")
    with pg_store.database.connect() as conn:
        conn.execute("UPDATE web_users SET is_active = FALSE WHERE id = %s", (user.id,))
    assert pg_store.sessions.get_user_by_token(token) is None


def test_registration_refuses_an_address_that_is_not_one_mailbox(pg_store):
    for email in ("a@example.test,victim@example.test", "Name <a@example.test>", "a b@example.test"):
        with pytest.raises(ValueError, match="valid email"):
            pg_store.accounts.register_user(email, "example-pass-123")
        with pytest.raises(ValueError, match="valid email"):
            pg_store.accounts.start_registration(email, "example-pass-123")
    with pg_store.database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM web_users").fetchone()["n"] == 0


@pytest.mark.parametrize("replay_delay", [0, 1], ids=["same-step", "across-rollover"])
def test_two_factor_setup_cannot_replace_an_active_secret(pg_store, monkeypatch, replay_delay):
    import identity.clock as identity_clock
    from identity.credentials import _totp_code
    enabled_at = datetime(2026, 10, 28, 16, 19, 29, tzinfo=timezone.utc)
    moment = enabled_at
    monkeypatch.setattr(identity_clock, "_utcnow", lambda: moment)
    user, _ = pg_store.accounts.register_user("mfa@example.test", "example-pass-123")
    first = pg_store.security.begin_two_factor(user.id)["secret"]
    # A pending, unconfirmed secret may be reissued.
    secret = pg_store.security.begin_two_factor(user.id)["secret"]
    assert secret != first
    activation_code = _totp_code(secret)
    assert pg_store.security.enable_two_factor(user.id, activation_code)

    with pytest.raises(ValueError, match="already enabled"):
        pg_store.security.begin_two_factor(user.id)
    with pg_store.database.connect() as conn:
        row = conn.execute(
            "SELECT two_factor_enabled, two_factor_secret FROM web_users WHERE id = %s", (user.id,),
        ).fetchone()
    assert row["two_factor_enabled"] is True and row["two_factor_secret"] == secret
    # Replay the actual activation code, even if verification crosses a 30-second
    # boundary. Regenerating it here would test a fresh code instead of a replay.
    moment = enabled_at + timedelta(seconds=replay_delay)
    assert not pg_store.security.verify_admin_two_factor(user.id, activation_code)
    moment = enabled_at + timedelta(seconds=30)
    assert pg_store.security.verify_admin_two_factor(user.id, _totp_code(secret))

    # Re-enrolment requires proving the current code first, a minute later.
    moment = enabled_at + timedelta(seconds=60)
    assert pg_store.security.disable_two_factor(user.id, _totp_code(secret))
    assert pg_store.security.begin_two_factor(user.id)["secret"] != secret


def test_jsonb_preferences_research_zero_values_and_ownership(pg_store):
    user, _ = pg_store.accounts.register_user("research@example.test", "example-pass-123")
    stranger, _ = pg_store.accounts.register_user("stranger@example.test", "example-pass-123")
    pg_store.profile.update_preferences(user.id, {"language": "uz", "theme": "dark"})
    merged = pg_store.profile.update_preferences(user.id, {"text_scale": 110})
    assert merged["language"] == "uz" and merged["theme"] == "dark" and merged["text_scale"] == 110
    pg_store.research.record_analysis(user.id, {"company": "AGBA"}, {
        "ticker": "AGBA", "company_name": "Агробанк", "summary": {"score": 0}, "cost": 0,
    })
    profile = pg_store.profile.get_profile(user.id)
    analysis = profile["recent_analyses"][0]
    assert analysis["score"] == 0 and analysis["cost"] == 0
    assert profile["stats"]["avg_score"] == 0 and profile["stats"]["total_analyses"] == 1
    updated = pg_store.research.update_analysis(user.id, analysis["id"], {"tags": ["банк", "zero"], "bookmarked": True})
    assert updated["tags"] == ["банк", "zero"] and updated["bookmarked"]
    note = pg_store.notes.save_note(user.id, None, {"title": "Заметка", "body": "Нулевая оценка", "analysis_id": analysis["id"], "tags": ["проверено"]})
    assert note["tags"] == ["проверено"]
    with pytest.raises(ValueError, match="not found"):
        pg_store.research.get_analysis(stranger.id, analysis["id"])
    with pytest.raises(ValueError, match="not found"):
        pg_store.notes.save_note(stranger.id, None, {"body": "foreign", "analysis_id": analysis["id"]})
    assert pg_store.notes.delete_note(stranger.id, note["id"]) is False
    assert pg_store.notes.list_notes(user.id)[0]["id"] == note["id"]


def test_registration_rolls_back_when_session_creation_fails(pg_store, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("simulated session failure")
    monkeypatch.setattr(pg_store.sessions, "_issue_session", fail)
    with pytest.raises(RuntimeError, match="simulated"):
        pg_store.accounts.register_user("rollback@example.test", "example-pass-123")
    assert pg_store.accounts.get_user_by_email("rollback@example.test") is None


def test_http_register_profile_login_logout_against_postgres(pg_store, monkeypatch):
    from fastapi.testclient import TestClient
    import api
    import web_auth
    monkeypatch.setattr(web_auth, "web_auth_store", pg_store)
    client = TestClient(api.app)
    account = {"email": "http@example.test", "password": "example-pass-123", "full_name": "HTTP Investor"}
    response = client.post("/api/auth/register", json=account)
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).json()["user"]["email"] == account["email"]
    profile = client.get("/api/profile", headers=headers)
    assert profile.status_code == 200, profile.text
    assert profile.json()["user"]["full_name"] == account["full_name"]
    assert client.post("/api/auth/register", json=account).status_code == 409
    assert client.post("/api/auth/login", json={**account, "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json=account).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).json()["revoked"] is True
    assert client.get("/api/auth/me", headers=headers).status_code == 401


@pytest.fixture
def pg_catalogue(pg_store, monkeypatch, tmp_path):
    import dbx
    dsn = pg_store.database.database_url
    schema = conninfo_to_dict(dsn)["options"].split("search_path=", 1)[1]
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("DATABASE_SCHEMA", schema)
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    monkeypatch.setenv("SECTOR_ANALYSIS_DB", str(tmp_path / "reports.db"))
    dbx.reset_pools()
    try:
        yield
    finally:
        dbx.reset_pools()


def test_catalogue_quote_upsert_and_news_feed_use_real_postgres(pg_catalogue):
    from datetime import datetime, timezone
    import catalogue.market_store as market
    import news_store
    quote = {"ticker": "AGBA", "isin": "QA-PG-AGBA", "name": "Агробанк", "market": "STK",
             "trade_date": "20260925", "close_price": 120, "quantity": 0, "turnover": 0}
    assert market.bulk_upsert_quotes([quote]) == 1
    assert market.bulk_upsert_quotes([{**quote, "close_price": 125}]) == 1
    stored = market.get_all_quotes()[quote["isin"]]
    assert stored["close_price"] == 125 and stored["turnover"] == 0
    item = {"url": "https://example.test/pg-news", "title": "Тестовая новость", "source": "QA", "source_id": "qa",
            "lang": "ru", "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "type": "market", "tone": "neutral", "tone_score": 0, "relevant": 1, "relevance_score": 1,
            "tickers": ["AGBA"], "sectors": []}
    assert news_store.upsert_news([item]) == 1
    feed = news_store.get_news_feed(limit=5, days=30, order="recent")
    assert len(feed) == 1 and feed[0]["title"] == item["title"] and feed[0]["tickers"] == ["AGBA"]
    assert news_store.get_news_item(feed[0]["id"])["url"] == item["url"]


def test_report_queue_is_idempotent_and_claims_once_on_postgres(pg_catalogue):
    from reporting import store
    job = store.enqueue("AGBA", "qa-pg-event")
    assert store.enqueue("AGBA", "qa-pg-event") == job
    assert [row["id"] for row in store.due_jobs()] == [job]
    assert store.claim_job(job) is True
    assert store.claim_job(job) is False
    store.finish_job(job, "completed", 1, None)
    assert store.due_jobs() == []


def test_verified_uzas_balance_repair_is_atomic_on_postgres(pg_catalogue, monkeypatch, tmp_path):
    from catalogue import balance_repair, financial_store
    from tests.test_balance_repair import correction, FILING
    from catalogue import parsing
    import data_quality

    financial_store.upsert_financials_cache('UZAS', 'NSBU', 2026, 2, {
        'total_assets': 332548245.7, 'total_equity': 147661927.4, 'total_liabilities': 80360618.0})
    correction('Автоматическая подсказка по формуле: Assets = equity + liabilities.')
    values = parsing.compute_filing_values(**{k + '_data': v for k, v in FILING['workbook'].items()
                                             if k in ('income', 'balance')})['source_values']
    monkeypatch.setattr(balance_repair, 'verified_balance', lambda **_: {
        **values, 'source_url': 'https://openinfo.uz/uzas-2026q2.xlsx'})
    result = balance_repair.repair(tickers=['UZAS'], apply=True, backup_dir=tmp_path / 'backup')
    assert result['skipped'] == []
    assert result['changed'] == 1
    assert data_quality.approved_corrections_for('UZAS', 'NSBU', 2026, 2) == {}
    assert balance_repair.repair(tickers=['UZAS'], apply=True, backup_dir=tmp_path / 'backup')['changed'] == 0
    def unverified(**_):
        raise ValueError('Filing balance does not reconcile')
    monkeypatch.setattr(balance_repair, 'verified_balance', unverified)
    assert balance_repair.rollback_unverified(backup_dir=tmp_path/'backup', apply=True)['restored'] == 1
    assert data_quality.approved_corrections_for('UZAS', 'NSBU', 2026, 2)['total_assets'] == 228022545.4
