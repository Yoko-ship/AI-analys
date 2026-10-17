"""The terminal event journal (docs/catalog-terminal/04-logging-admin.md)."""
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

import api
import server.auth.limits as auth_limits
import server.hardening as hardening
from server.terminal import journal
from server.terminal.timing import JournalTimingMiddleware, ticker_of


def _all(**filters):
    return journal.events(limit=1000, **filters)["items"]


def test_unknown_event_names_are_refused_loudly():
    with pytest.raises(journal.UnknownEvent):
        journal.emit("cmd_ran")


def test_every_event_has_a_known_level_and_retention():
    for name, (level, kind, text) in journal.EVENTS.items():
        assert level in journal.LEVEL_LABELS and kind in journal.RETENTION_DAYS and text, name
    # The ТЗ's catalogue is present in full.
    for name in ("cmd_run", "cmd_unknown", "screen_error", "screen_slow", "ai_limit", "export",
                 "load_ok", "load_empty", "load_duplicate", "value_quarantine", "year_backfill",
                 "restatement", "ai_published", "ai_blocked", "verdict_conflict",
                 "ins_retention_jump", "ins_reserves_missing", "pb_high", "load_format_changed"):
        assert name in journal.EVENTS, name


def test_an_event_round_trips_with_its_fields_in_tashkent_time():
    journal.emit("load_empty", ticker="sqbn", standard="NSBU", period="2024", user_id=None,
                 message="file is empty", source_url="https://openinfo.uz/x", details={"bytes": 0})
    [item] = _all()
    assert item["event"] == "load_empty" and item["level"] == "critical"
    assert item["level_label"] == "Критично" and item["ticker"] == "SQBN"
    assert item["user_id"] is None and item["details"] == {"bytes": 0}
    assert item["ts"].endswith("+05:00")


def test_the_journal_refuses_to_rewrite_history():
    journal.emit("cmd_run", ticker="AGBA", function="FA")
    journal.flush()
    with journal.connection() as c:
        with pytest.raises(Exception):
            c.execute("UPDATE terminal_events SET ticker = 'X'")
        c.rollback()
        with pytest.raises(Exception):
            c.execute("DELETE FROM terminal_events")
        c.rollback()
    assert len(_all()) == 1


def test_retention_keeps_user_actions_90_days_and_data_events_a_year():
    now = journal.now()
    journal.emit("cmd_run", at=now - timedelta(days=91))         # user action, expired
    journal.emit("cmd_run", at=now - timedelta(days=89))         # user action, kept
    journal.emit("load_empty", at=now - timedelta(days=200))     # data event, kept
    journal.emit("screen_error", at=now - timedelta(days=366))   # error, expired
    journal.flush()
    assert journal.purge(now) == 2
    assert sorted(i["event"] for i in _all()) == ["cmd_run", "load_empty"]
    # The guard closes again after the purge.
    with journal.connection() as c:
        with pytest.raises(Exception):
            c.execute("DELETE FROM terminal_events")
        c.rollback()


def test_filters_by_level_ticker_and_day():
    now = journal.now()
    journal.emit("cmd_run", ticker="AGBA", at=now - timedelta(days=2))
    journal.emit("value_quarantine", ticker="KVTS", at=now)
    journal.emit("screen_slow", ticker="KVTS", at=now)
    assert [i["event"] for i in _all(levels=["critical"])] == ["value_quarantine"]
    assert {i["event"] for i in _all(ticker="kvts")} == {"value_quarantine", "screen_slow"}
    day = (now - timedelta(days=2)).date().isoformat()
    assert [i["ticker"] for i in _all(since=day, until=day)] == ["AGBA"]


def test_the_beacon_accepts_only_browser_events_and_never_trusts_a_user_id():
    client = TestClient(api.app)
    response = client.post("/api/terminal/events", json={"events": [
        {"event": "cmd_unknown", "message": "SQBX FA", "user_id": 1},
        {"event": "load_empty", "ticker": "SQBN"},            # server-only: refused
        {"event": "cmd_run", "ticker": "SQBN", "function": "fa", "standard": "msfo",
         "duration_ms": 420},
        {"event": "cmd_run", "ticker": "<script>"},           # bad ticker: kept without it
    ]})
    assert response.status_code == 204
    items = {(i["event"], i["ticker"]): i for i in _all()}
    assert set(items) == {("cmd_unknown", None), ("cmd_run", "SQBN"), ("cmd_run", None)}
    assert items[("cmd_unknown", None)]["user_id"] is None
    assert items[("cmd_unknown", None)]["message"] == "SQBX FA"
    run = items[("cmd_run", "SQBN")]
    assert (run["function"], run["standard"], run["duration_ms"]) == ("FA", "MSFO", 420)


@pytest.mark.parametrize("body", [b"", b"not json", b"[]", b'{"events": "x"}', b"x" * 9000])
def test_a_malformed_beacon_is_ignored_quietly(body):
    assert TestClient(api.app).post("/api/terminal/events", content=body).status_code == 204
    assert _all() == []


def test_admin_journal_reads_are_behind_the_admin_gate():
    client = TestClient(api.app)
    assert client.get("/api/admin/terminal/events").status_code == 401
    assert client.get("/api/admin/terminal/catalogue").status_code == 401


def _timed_app(slow_ms):
    app = FastAPI()
    hardening.install(app, Path("missing-index.html"))
    app.add_middleware(JournalTimingMiddleware, slow_ms=slow_ms)

    @app.get("/api/company/{ticker}/financials")
    def financials(ticker: str):
        return {"ticker": ticker}

    @app.post("/api/catalog/analyze")
    def analyze():
        return {}

    @app.get("/api/boom")
    def boom():
        raise HTTPException(status_code=500, detail="db host secret")

    @app.get("/api/crash")
    def crash():
        raise RuntimeError("unhandled")

    return app


def test_a_server_error_is_journalled_under_the_id_the_client_was_shown():
    client = TestClient(_timed_app(slow_ms=60_000), raise_server_exceptions=False)
    response = client.get("/api/boom")
    assert response.status_code == 500
    [item] = _all(event="api_error")
    assert item["error_id"] == response.json()["error_id"]
    assert "db host secret" not in item["message"]
    assert client.get("/api/crash").status_code == 500
    assert len(_all(event="api_error")) == 2


def test_slow_reads_are_journalled_and_slow_writes_are_not():
    client = TestClient(_timed_app(slow_ms=0))
    client.get("/api/company/sqbn/financials")
    client.post("/api/catalog/analyze")
    [item] = _all()
    assert item["event"] == "api_slow" and item["ticker"] == "SQBN"
    assert item["details"]["path"] == "/api/company/sqbn/financials"


def test_fast_successful_requests_leave_no_trace():
    TestClient(_timed_app(slow_ms=60_000)).get("/api/company/AGBA/financials")
    assert _all() == []


def test_ticker_is_read_from_the_paths_that_name_one():
    assert ticker_of("/api/company/SQBN/financials") == "SQBN"
    assert ticker_of("/api/catalog/peers/agba") == "AGBA"
    assert ticker_of("/api/dividends/ORFI") == "ORFI"
    assert ticker_of("/api/market/stocks") is None


def test_hitting_the_ai_quota_is_journalled(monkeypatch):
    user = SimpleNamespace(id=987654, email="someone@example.com")
    monkeypatch.setattr(auth_limits, "LLM_RATE_LIMIT_PER_MINUTE", 1)
    for key in [k for k in auth_limits._rate_limiter._events if k.endswith(":987654")]:
        auth_limits._rate_limiter._events.pop(key)
    auth_limits._enforce_llm_quota(user)
    with pytest.raises(HTTPException):
        auth_limits._enforce_llm_quota(user)
    [item] = _all(event="ai_limit")
    assert item["user_id"] == 987654 and item["details"] == {"limit": "window"}
    assert "someone@example.com" not in str(item)
