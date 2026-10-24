"""Published analysis is public; creating saved comparisons requires a user."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import issuer_analysis_api


def test_ai_report_is_public(monkeypatch):
    issuer = {"id": "670", "ticker": "KFSK", "name": "Kafolat"}
    report = {"ok": True, "issuer": issuer, "period": "2025", "standard": "nsbu"}
    monkeypatch.setattr(issuer_analysis_api.financials, "resolve_issuer", lambda _: issuer)
    monkeypatch.setattr(issuer_analysis_api, "_sector_ai_report", lambda *args: report)
    app = FastAPI()
    app.include_router(issuer_analysis_api.router)
    response = TestClient(app).get("/api/v1/issuers/KFSK/ai-report?standard=nsbu&period=2025")
    assert response.status_code == 200
    assert response.json() == report


def test_creating_a_comparison_still_requires_sign_in():
    app = FastAPI()
    app.include_router(issuer_analysis_api.router)
    response = TestClient(app).post("/api/v1/comparisons", json={})
    assert response.status_code == 401
