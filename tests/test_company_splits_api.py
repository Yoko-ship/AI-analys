"""/api/company/{ticker}/splits — the register behind the «Сплиты» sub-tab.

The endpoint serves corporate_actions.CORPORATE_ACTIONS verbatim — the same
entries every price series on the site is back-adjusted by, so the table a
reader sees and the chart above it can never disagree. What is pinned here:
the order (oldest first, as the story reads), the compounding (ALKB's two
rows multiply to the 205× the unadjusted chart actually stepped by), and
that a ticker with no events answers ok-empty rather than 404 — «сплитов не
зафиксировано» is the honest content for ~100 of the ~110 securities.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

api = importlib.import_module("api")
pytestmark = pytest.mark.usefixtures("authenticated_reader")


@pytest.fixture()
def client():
    return TestClient(api.app)


def test_alkb_carries_both_events_oldest_first(client):
    d = client.get("/api/company/alkb/splits").json()
    assert d["ok"] is True
    assert d["ticker"] == "ALKB"
    assert [i["kind"] for i in d["items"]] == ["split", "bonus"]
    assert d["items"][0]["ex_date"] < d["items"][1]["ex_date"]
    total = 1.0
    for item in d["items"]:
        total *= item["ratio"]
    # 121 × 205/121: the product, not either row alone, explains the step.
    assert round(total) == 205
    for item in d["items"]:
        assert item["factor"] == pytest.approx(1.0 / item["ratio"], rel=1e-6)
        assert item["source"].startswith("https://")


def test_no_events_is_an_ok_empty_list_not_a_404(client):
    resp = client.get("/api/company/UVGT/splits")
    assert resp.status_code == 200
    d = resp.json()
    assert d["ok"] is True
    assert d["items"] == []
