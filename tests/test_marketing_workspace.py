from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api
from server.auth.access import _admin_panel_gate


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "desk.db"))
    monkeypatch.setitem(api.app.dependency_overrides, _admin_panel_gate, lambda: None)
    return TestClient(api.app)


BASE = "/api/admin/marketing"


def test_plan_edit_approve_and_experiment(desk, monkeypatch):
    from server.news import marketing_workspace_routes as workspace
    plan = dict(audience="New investors", channel="Telegram", destination="/market",
                schedule=["Monday: introduce price changes", "Friday: review market activity"])
    class Model:
        def complete_json(self, system, user, **kwargs):
            assert "read the market" in user and kwargs["response_schema"]
            return plan
    monkeypatch.setattr(workspace, "get_classifier_client", lambda: Model())
    record = desk.post(BASE + "/plans", json={"goal": "Help beginners read the market", "language": "en"}).json()
    assert record["status"] == "draft"
    path = BASE + "/plans/" + record["id"]
    assert desk.put(path, json={**plan, "destination": "https://example.com", "approve": True}).status_code == 422
    saved = desk.put(path, json={**plan, "audience": "First-time readers", "approve": True}).json()
    assert saved["status"] == "approved" and "utm_campaign=" in saved["link"]
    assert desk.get(BASE + "/workspace").json()["plans"][0]["audience"] == "First-time readers"
    experiment = desk.post(BASE + "/experiments", json={"name": "Landing page", "a": "/market", "b": "/heatmap"}).json()
    link = experiment["link"].split("uzstock.uz")[1]
    visit = desk.get(link, follow_redirects=False)
    assert visit.status_code in (302, 307) and "utm_campaign=exp-" in visit.headers["location"]
    assert desk.get(link, follow_redirects=False).headers["location"] == visit.headers["location"]


def test_report_counts_sessions_paths_returns_and_avoids_premature_winners():
    from server.news.marketing_metrics import summarize, compare
    now = datetime.now(timezone.utc)
    rows = [dict(visitor_id="reader", session_id=session, path=path, utm_campaign=tag, ts=now+timedelta(minutes=i))
            for i, (session, path, tag) in enumerate([
                ("one", "/market", "p"), ("one", "/market", "p"), ("one", "/news", "p"),
                ("two", "/issuers", None), ("two", "/news", "p")])]
    result = summarize(rows, {"p"}, now)["p"]
    assert result == dict(visits=1, readers=1, pages=2, continued=1, returned=1)
    assert compare([True]*9, [False]*9) == "collecting"
    assert compare([True]*100, [False]*100) == "a"
    assert compare([True]*50+[False]*50, [True]*51+[False]*49) == "inconclusive"
