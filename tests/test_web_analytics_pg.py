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


def test_one_day_reads_only_that_day_and_the_daily_table_names_its_leaders(traffic):
    # move the Google reader's visit to yesterday (Tashkent days)
    with wa._conn() as conn:
        conn.execute("UPDATE web_events SET ts = ts - INTERVAL '1 day' WHERE visitor_id = 'visitorBBB1'")
    yesterday = (wa.datetime.now(wa.TASHKENT) - wa.timedelta(days=1)).date().isoformat()
    today = wa.datetime.now(wa.TASHKENT).date().isoformat()

    one = wa.audience(30, yesterday)
    assert one["day"] == yesterday and one["totals"]["visitors"] == 1
    assert [c["channel"] for c in one["channels"]] == ["search"]
    assert len(one["hourly"]) == 24 and sum(h["visitors"] for h in one["hourly"]) == 1
    # "new" looks past the window: the reader was first seen yesterday
    assert one["totals"]["new_visitors"] == 1
    assert wa.engagement(30, yesterday)["reading"][0]["view"] == "news"

    rows = {r["day"]: r for r in wa.audience(7)["daily"]}
    assert rows[yesterday]["top_channel"] == {"name": "search", "sessions": 1}
    assert rows[yesterday]["top_site"] == {"name": "google.com", "sessions": 1}
    assert rows[yesterday]["bounce_rate"] == 1.0 and rows[yesterday]["avg_seconds"] == 3.0
    assert rows[today]["visitors"] == 4 and rows[today]["new_visitors"] == 4

    # a malformed or future day falls back to the range instead of an empty screen
    assert wa.audience(7, "2999-01-01")["day"] is None
    assert wa.audience(7, "not-a-date")["totals"]["visitors"] == 5


@pytest.fixture
def product_traffic(traffic):
    """Two complete weeks, UZTL interest and a campaign registration after arrival."""
    from datetime import datetime, timedelta, timezone
    end = wa._day_start(datetime.now(timezone.utc))
    start = end - timedelta(days=7)
    with wa._conn() as conn:
        conn.execute("DELETE FROM web_events")
        conn.execute("UPDATE web_users SET created_at = %s WHERE id=2", (start + timedelta(hours=1, minutes=2),))
        conn.execute("DELETE FROM web_analysis_history")

    def hit(vid, sid, at, path="/company/UZTL", event="pageview", **extra):
        traffic(vid, path, "company", "198.51.100.1", sid=sid, ticker=extra.pop("ticker", "UZTL"), event=event, **extra)
        row = list(wa._buffer[-1])
        row[0] = at
        wa._buffer[-1] = tuple(row)

    # Prior history makes both complete periods observable.
    hit("visitorOLD1", "sessionOLD1", start - timedelta(days=8))
    hit("visitorAAA1", "sessionPREV", start - timedelta(days=2))
    # A returning browser, two visits, three clicks: repeat use counts visits, not clicks.
    hit("visitorAAA1", "sessionAAA1", start, us="telegram", uc="uztl-post", tv=1)
    hit("visitorAAA1", "sessionAAA1", start + timedelta(seconds=20), event="feature_financials", tv=1)
    hit("visitorAAA1", "sessionAAA1", start + timedelta(seconds=21), event="feature_financials", tv=1)
    hit("visitorAAA1", "sessionAAA2", start + timedelta(days=1), tv=1)
    hit("visitorAAA1", "sessionAAA2", start + timedelta(days=1, seconds=10), event="feature_financials", tv=1)
    # Anonymous arrival, then a trusted signed-in event. Only the new account counts.
    hit("visitorBBB1", "sessionBBB1", start + timedelta(hours=1), ref="https://www.google.com/search?q=uztl")
    wa._buffer[-1] = tuple(None if i == 3 else value for i, value in enumerate(wa._buffer[-1]))
    hit("visitorBBB1", "sessionBBB1", start + timedelta(hours=1, minutes=3), event="leave", ms=45000)
    hit("visitorBBB1", "sessionBBB2", start + timedelta(days=2))
    # Unmeasured historical visitor: no feature events must remain unknown.
    hit("visitorNET0", "sessionNET0", start + timedelta(hours=3), path="/company/HMKB", ticker="HMKB")
    # Current partial day and internal browsers must not enter the report.
    hit("visitorTODAY", "sessionTODAY", end)
    hit("visitorTEAM", "sessionTEAM", start, int=1)
    assert wa.flush() == 13
    return start, end, hit


def test_product_sources_tickers_and_repeat_feature_usage(product_traffic):
    import product_analytics
    report = product_analytics.product_report(7)
    assert report["totals"] == {"visitors": 3, "sessions": 5, "engaged_sessions": 3, "registrations": 1}
    assert report["coverage"]["measured_sessions"] == 2
    assert report["coverage"]["previous_complete"] is True
    google = next(r for r in report["sources"] if r["source"] == "google.com")
    assert (google["sessions"], google["registrations"], google["engaged_sessions"]) == (1, 1, 1)
    telegram = next(r for r in report["sources"] if r["source"] == "telegram")
    assert telegram["campaign"] == "uztl-post" and telegram["engaged_sessions"] == 1
    uztl = next(r for r in report["companies"] if r["ticker"] == "UZTL")
    assert (uztl["visitors"], uztl["previous_visitors"], uztl["change_pct"], uztl["returning_visitors"]) == (2, 1, 100.0, 1)
    financials = next(r for r in report["features"] if r["feature"] == "financials")
    assert (financials["users"], financials["sessions"], financials["actions"], financials["repeat_users"]) == (1, 2, 3, 1)
    assert financials["adoption_rate"] == 1.0
    assert next(r for r in report["features"] if r["feature"] == "chart")["users"] == 0


def test_product_unmeasured_features_and_incomplete_history_are_not_zero(traffic):
    import product_analytics
    from datetime import datetime, timedelta, timezone
    yesterday = wa._day_start(datetime.now(timezone.utc)) - timedelta(hours=2)
    with wa._conn() as conn:
        conn.execute("UPDATE web_events SET ts=%s", (yesterday,))
    report = product_analytics.product_report(7)
    assert report["coverage"]["previous_complete"] is False
    assert report["coverage"]["measured_sessions"] == 0
    assert all(r["change_pct"] is None for r in report["companies"])
    assert all(r["users"] is None for r in report["features"] if r["measurement"] == "interaction")
    assert next(r for r in report["features"] if r["feature"] == "news")["users"] == 1


def test_product_session_attribution_keeps_original_source_across_period_boundary(product_traffic):
    import product_analytics
    from datetime import timedelta
    start, end, hit = product_traffic
    hit("visitorCROSS", "sessionCROSS", start - timedelta(minutes=5), us="telegram", uc="before-week")
    hit("visitorCROSS", "sessionCROSS", start + timedelta(minutes=5), event="leave", ms=60000)
    assert wa.flush() == 2
    report = product_analytics.product_report(7)
    # Source report counts visits by their start, not a trailing leave beacon.
    assert report["totals"]["sessions"] == 5
    assert not any(r["campaign"] == "before-week" for r in report["sources"])


def test_product_registration_conversion_counts_converted_visits_not_accounts(product_traffic):
    import product_analytics
    from datetime import timedelta
    start, _, hit = product_traffic
    with wa._conn() as conn:
        conn.execute("INSERT INTO web_users(id,email,created_at) VALUES(3,'second@example.test',%s)",
                     (start + timedelta(hours=1, minutes=2),))
    hit("visitorBBB1", "sessionBBB1", start + timedelta(hours=1, minutes=4), event="leave", ms=1000)
    row = list(wa._buffer[-1]); row[3] = 3; wa._buffer[-1] = tuple(row)
    wa.flush()
    google = next(r for r in product_analytics.product_report(7)["sources"] if r["source"] == "google.com")
    assert google["registrations"] == 2
    assert google["registration_rate"] == 1.0


def test_product_empty_database_has_no_invented_history(traffic):
    import product_analytics
    with wa._conn() as conn:
        conn.execute("DELETE FROM web_events")
    report = product_analytics.product_report(7)
    assert report["coverage"]["history_since"] is None
    assert report["sources"] == [] and report["companies"] == []
    assert report["totals"]["sessions"] == 0
    assert all(r["adoption_rate"] is None for r in report["features"])
