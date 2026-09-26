"""Keep report preparation usable by HTTP handlers and background workers alike."""
import ast
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import issuer_analysis_api as routes
import issuer_financials as financials


@pytest.mark.parametrize("module", [
    "issuer_financials.py", "sector_report_service.py", "analysis_service.py",
    "analysis_monitor.py", "admin_control/worker.py", "admin_control/adapters.py",
])
def test_reporting_services_do_not_depend_on_http_routes(module):
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / module).read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append((node.module or "").split(".")[0])
    assert "issuer_analysis_api" not in imports, "Depend on the reporting module, never route internals"
    assert "api" not in imports
    if module == "issuer_financials.py":
        assert "fastapi" not in imports
        assert "sector_report_service" not in imports


def test_issuer_identity_is_shared_across_ticker_isin_and_registry_id(monkeypatch):
    monkeypatch.setattr(financials, "get_securities_map", lambda: {
        "TEST": {"isin": "UZ123", "name": "Test issuer", "sector": "industry"},
    })
    monkeypatch.setattr(financials, "get_company_index", lambda ticker: {
        "org_id": "123", "company_name": "Test issuer", "tickers": ["TEST", "TESTP"],
    })
    issuer = financials.resolve_issuer("test")
    assert issuer["id"] == "123"
    assert issuer["tickers"] == ["TEST", "TESTP"]
    assert financials.resolve_issuer("uz123") == issuer
    assert financials.resolve_issuer("123") == issuer
    assert financials.resolve_issuer("Test issuer") == issuer
    with pytest.raises(financials.IssuerNotFoundError):
        financials.resolve_issuer("missing")


def test_http_adapter_preserves_public_report_and_missing_issuer_contracts(monkeypatch):
    monkeypatch.setattr(financials, "get_securities_map", lambda: {})
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    response = client.get("/api/v1/issuers/missing/profile")
    assert response.status_code == 404
    assert response.json() == {"detail": "issuer not found"}
    assert client.get("/api/v1/issuers/missing/ai-report?standard=nsbu").status_code == 404
    assert client.get("/api/v1/issuers/missing/ai-report?standard=nsbu", headers={"Authorization": "Bearer test"}).status_code == 404
