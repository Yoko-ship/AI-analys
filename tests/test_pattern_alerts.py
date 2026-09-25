"""Pattern alerts in the notification bell (ТЗ §3 «Оповещения»).

A figure completed in the last few sessions on a watchlist company whose
pattern alert is on, of a type the reader chose (every chart figure when they
chose none), becomes one bell item. The item carries only the event's own
facts, so it keeps its read state between polls.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api
from web_auth import DEFAULT_PROFILE_PREFERENCES, WebUser


def _pro() -> WebUser:
    return WebUser(id=7, email="person@example.com", full_name="Person", avatar_data_url=None,
                   created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), last_login_at=None, is_active=True,
                   tier="pro", subscription_until=datetime(2099, 1, 1, tzinfo=timezone.utc))


TODAY = date.today().isoformat()
OLD = (date.today() - timedelta(days=30)).isoformat()


@pytest.fixture()
def bell(monkeypatch):
    state = {"favorites": [{"ticker": "TEST", "pattern_alert_enabled": True, "report_alert_enabled": False}],
             "preferences": {**DEFAULT_PROFILE_PREFERENCES, "notify_reports": False, "notify_price": False},
             "read": {}}

    async def fake_resolve(ticker):
        return "UZ0000000001"

    async def fake_history(isin, months=60):
        return {"points": [{"date": TODAY, "close": 1.0}]}

    async def fake_analysis(isin, points, level="medium"):
        return {"status": "AVAILABLE", "signals": [
            {"type": "double_top", "family": "chart", "direction": "bearish", "signal_date": TODAY},
            {"type": "hammer", "family": "candle", "direction": "bullish", "signal_date": TODAY},
            {"type": "double_bottom", "family": "chart", "direction": "bullish", "signal_date": OLD},
        ]}

    import formulas
    monkeypatch.setattr(api.web_auth_store, "get_user_by_token", lambda token: _pro())
    monkeypatch.setattr(api.web_auth_store, "list_favorites", lambda uid: state["favorites"])
    monkeypatch.setattr(api.web_auth_store, "get_preferences", lambda uid: state["preferences"])
    monkeypatch.setattr(api.web_auth_store, "notification_states", lambda uid: state["read"])
    monkeypatch.setattr(api, "_admin_role", lambda user: None)
    monkeypatch.setattr(api, "get_all_listings", lambda: {})
    monkeypatch.setattr(api, "_resolve_isin", fake_resolve)
    monkeypatch.setattr(api, "_full_history", fake_history)
    monkeypatch.setattr(api, "_pattern_analysis", fake_analysis)
    monkeypatch.setattr(formulas, "data_quality", lambda points: {"data_tier": "full"})
    client = TestClient(api.app)

    def items():
        body = client.get("/api/notifications", headers={"Authorization": "Bearer token"}).json()
        return [i for i in body["items"] if i["kind"] == "pattern"]
    items.state = state
    return items


def test_recent_chart_figures_reach_the_bell_by_default(bell):
    got = bell()
    assert [(i["ticker"], i["pattern"], i["signal_date"]) for i in got] == [("TEST", "double_top", TODAY)]
    assert got[0]["href"] == "/company/TEST" and got[0]["direction"] == "bearish"


def test_candle_models_only_when_chosen(bell):
    bell.state["preferences"]["pattern_alert_types"] = ["hammer"]
    assert [i["pattern"] for i in bell()] == ["hammer"]


def test_nothing_without_the_watchlist_switch_or_the_preference(bell):
    bell.state["favorites"][0]["pattern_alert_enabled"] = False
    assert bell() == []
    bell.state["favorites"][0]["pattern_alert_enabled"] = True
    bell.state["preferences"]["notify_patterns"] = False
    assert bell() == []


def test_the_item_id_is_stable_between_polls(bell):
    first, again = bell(), bell()
    assert first[0]["id"] == again[0]["id"]
    bell.state["read"] = {first[0]["id"]: {"read": True}}
    assert bell()[0]["read"] is True


def test_preference_validation_rejects_unknown_pattern_types():
    # Rejected before any database work: the check is on the values alone.
    with pytest.raises(ValueError, match="pattern type"):
        api.web_auth_store.update_preferences(7, {"pattern_alert_types": ["not_a_pattern"]})
