"""Unpublished historical IFRS constants must not overwrite an NSBU feed."""
from fastapi.testclient import TestClient

import api
from catalogue import facts, filings, snapshots


def test_urts_2015_ifrs_constants_are_not_injected_into_nsbu(monkeypatch, tmp_path):
    # The saved historical module contains IFRS figures, without a reviewed
    # publication. A ticker-specific overlay would mix accounting standards.
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    monkeypatch.setattr(filings, "get_company_index", lambda _: {"org_id": 1})
    monkeypatch.setattr(filings, "get_company_reports", lambda _: [])
    monkeypatch.setattr(facts, "get_facts", lambda *args: [
        {"field": "net_revenue", "period": "2015", "value_num": 27_231_954.0},
        {"field": "net_profit", "period": "2015", "value_num": 6_595_795.0},
    ])
    monkeypatch.setattr(snapshots, "get_financials_series", lambda *args: {})
    response = TestClient(api.app).get("/api/company/URTS/financials?form=NSBU")
    assert response.status_code == 200
    body = response.json()
    assert body["standard"] == "NSBU"
    assert body["periods"] == ["2015"]
    assert body["series"]["net_profit"]["values"]["2015"] == 6_595_795_000.0
    assert "gross_profit" not in body["series"]
    assert "operating_income" not in body["series"]
    assert body["availability"] == "PARTIAL"
    assert any(gap["code"] == "MISSING_FINANCIAL_FIELDS" for gap in body["data_gaps"])
