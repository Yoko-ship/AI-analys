"""The audience queries against a real PostgreSQL.

Set TEST_POSTGRES_URL to a local disposable server; each test owns a schema.
One small, hand-built day of traffic pins what the admin's «Аудитория» and
«Вовлечённость» answer: the team never counts, places and channels are
attributed to the visit's first page, and reading time comes from ``leave``.
"""
import os
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

import web_analytics as wa

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "Version/17.0 Mobile/15E148 Safari/604.1")
PLACES = {
    "198.51.100.1": {"country": "UZ", "region": "Toshkent", "city": "Tashkent"},
    "198.51.100.2": {"country": "UZ", "region": "Samarqand", "city": "Samarkand"},
    "198.51.100.3": {"country": "DE", "region": "Hesse", "city": "Frankfurt am Main"},
}
USERS = {"visitorBBB1": 2, "visitorADM1": 1}


@pytest.fixture
def traffic(monkeypatch):
    dsn = os.environ.get("TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("TEST_POSTGRES_URL is not configured")
    if conninfo_to_dict(dsn).get("host") not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("TEST_POSTGRES_URL must point to a local disposable test server")
    schema = "qa_analytics_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    monkeypatch.setattr(wa, "DATABASE_URL", make_conninfo(dsn, options=f"-c search_path={schema}"))
    monkeypatch.setattr(wa, "_ensure_flusher", lambda: None)
    monkeypatch.setattr(wa, "_place", lambda ip: PLACES.get(ip))
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.test")
    wa._buffer.clear()
    try:
        with wa._conn() as conn:
            conn.execute("CREATE TABLE web_users (id BIGINT PRIMARY KEY, email TEXT, "
                         "created_at TIMESTAMPTZ DEFAULT now())")
            conn.execute("CREATE TABLE web_sessions (user_id BIGINT, created_at TIMESTAMPTZ)")
            conn.execute("CREATE TABLE web_analysis_history (id BIGSERIAL, user_id BIGINT, "
                         "created_at TIMESTAMPTZ DEFAULT now())")
            conn.execute("INSERT INTO web_users (id, email) VALUES (1, 'boss@example.test'), "
                         "(2, 'reader@example.test')")
            conn.execute("INSERT INTO web_analysis_history (user_id) VALUES (2)")
        assert wa.init_db() and wa.init_db()  # the migration is idempotent

        def hit(vid, path, view, ip, **extra):
            data = {"vid": vid, "sid": "s" + vid, "path": path, "view": view, **extra}
            assert wa.record_pageview(data, user_agent=UA, ip=ip)
            row = list(wa._buffer[-1])
            row[3] = USERS.get(vid)  # the API resolves uid from the session, never the body
            wa._buffer[-1] = tuple(row)

        # A: a Telegram campaign reader in Tashkent — market, then a company page read to the end
        hit("visitorAAA1", "/market", "market", "198.51.100.1", us="telegram", uc="launch-oct")
        hit("visitorAAA1", "/market", "market", "198.51.100.1", event="leave", ms=5000, sp=60)
        hit("visitorAAA1", "/company/UZTL", "company", "198.51.100.1", ticker="UZTL")
        hit("visitorAAA1", "/company/UZTL", "company", "198.51.100.1", event="leave", ms=40000, sp=90)
        # B: from Google in Samarkand, signed in, ran an analysis, left the news after 3 s
        hit("visitorBBB1", "/news", "news", "198.51.100.2", ref="https://www.google.com/search?q=uztl")
        hit("visitorBBB1", "/news", "news", "198.51.100.2", event="leave", ms=3000, sp=10)
        # the team: an administrator's browser and one flagged with «Не считать этот браузер»
        hit("visitorADM1", "/market", "market", "198.51.100.1")
        hit("visitorTEAM", "/market", "market", "198.51.100.1", int=1)
        # three browsers behind one network
        for n in range(3):
            hit(f"visitorNET{n}", "/", "main", "198.51.100.3")
        assert wa.flush() == 11
        yield hit
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_the_team_never_counts(traffic):
    assert wa.overview()["visitors"]["today"] == 5
    audience = wa.audience(30)
    assert audience["totals"]["visitors"] == 5
    assert audience["quality"]["team_excluded"] == 2
    assert wa.users_funnel(30)["steps"][0]["count"] == 5


def test_channels_campaigns_and_landings(traffic):
    audience = wa.audience(30)
    channels = {c["channel"]: c for c in audience["channels"]}
    assert channels["telegram"] == {"channel": "telegram", "sessions": 1, "bounce_rate": 0.0, "avg_seconds": 45.0}
    assert channels["search"]["bounce_rate"] == 1.0 and channels["search"]["avg_seconds"] == 3.0
    assert channels["direct"]["sessions"] == 3 and channels["direct"]["avg_seconds"] is None
    assert audience["campaigns"] == [{"source": "telegram", "medium": None, "campaign": "launch-oct",
                                      "sessions": 1, "bounce_rate": 0.0, "avg_seconds": 45.0}]
    landing = {row["path"]: row for row in audience["landings"]}
    assert landing["/market"]["sessions"] == 1 and landing["/"]["sessions"] == 3
    assert audience["totals"]["engaged_session_seconds"] == 24.0


def test_places_journey_and_networks(traffic):
    audience = wa.audience(30)
    assert {c["name"]: c["visitors"] for c in audience["countries"]} == {"DE": 3, "UZ": 2}
    assert {c["name"] for c in audience["cities"]} == {"Tashkent", "Samarkand", "Frankfurt am Main"}
    assert [s["count"] for s in audience["journey"]] == [5, 1, 1, 1]
    quality = audience["quality"]
    assert (quality["visitors"], quality["networks"]) == (5, 3)
    assert [n["visitors"] for n in quality["crowded_networks"]] == [3]


def test_reading_time_scroll_and_exits(traffic):
    engagement = wa.engagement(30)
    reading = {r["view"]: r for r in engagement["reading"]}
    assert reading["company"] == {"view": "company", "measured": 1, "avg_seconds": 40.0,
                                  "avg_scroll": 90, "quick_share": 0.0}
    assert reading["news"]["quick_share"] == 1.0
    exits = {r["path"]: r for r in engagement["exits"]}
    assert exits["/company/UZTL"]["exits"] == 1 and "/market" not in exits
    assert exits["/"]["exits"] == 3 and exits["/"]["exit_rate"] == 1.0
    assert all(e["event"] != "leave" for e in engagement["events"])


def test_referring_sites_name_the_site_and_the_page_when_sent(traffic):
    hit = traffic
    # a reader from a news site that passes the page, and one from the Telegram Android app
    hit("visitorCCC1", "/company/UZTL", "company", "198.51.100.2",
        ref="https://www.kun.uz/news/2026/10/09/uztl?utm_x=1#top")
    hit("visitorDDD1", "/market", "market", "198.51.100.2", ref="android-app://org.telegram.messenger/")
    assert wa.flush() == 2
    sites = {s["host"]: s for s in wa.audience(30)["sites"]}
    assert set(sites) == {"kun.uz", "google.com", "org.telegram.messenger"}
    kun = sites["kun.uz"]
    assert kun["channel"] == "referral" and kun["sessions"] == 1
    # scheme, www, query and fragment are dropped; the page is kept
    assert kun["pages"] == [{"path": "/news/2026/10/09/uztl", "sessions": 1}]
    # a search engine's page (the query) is never listed
    assert sites["google.com"]["channel"] == "search" and sites["google.com"]["pages"] == []
    assert sites["org.telegram.messenger"]["channel"] == "telegram"
