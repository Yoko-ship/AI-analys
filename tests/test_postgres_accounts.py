"""Real PostgreSQL contracts. Each test owns a fresh, disposable schema.

Set TEST_POSTGRES_URL to a local test server; no production DB is used.
"""
import os
import uuid

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
    fresh = WebAuthStore(pg_store.database.database_url)
    assert fresh.sessions.get_user_by_token(token).id == user.id
    logged_in, second = fresh.accounts.login_user(user.email, "example-pass-123")
    assert logged_in.id == user.id and second != token
    with fresh.database.connect() as conn:
        row = conn.execute("SELECT password_hash FROM web_users WHERE id = %s", (user.id,)).fetchone()
    assert row["password_hash"] != "example-pass-123"
    with pytest.raises(ValueError):
        fresh.accounts.login_user(user.email, "wrong-password")
    with pytest.raises(ValueError, match="already registered"):
        fresh.accounts.register_user(user.email.upper(), "example-pass-123")


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
