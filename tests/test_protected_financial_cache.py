"""Published statements and their evidence remain public across login/logout."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api
from server.auth.access import _require_user
from server.company import financials


@pytest.mark.parametrize("prefix", ["/api", "/api/v2"])
@pytest.mark.parametrize("resource", ["financials", "financials/passport?period=2025&field=net_profit"])
def test_public_financial_responses_remain_available_after_logout(monkeypatch, prefix, resource):
    async def payload(*args):
        return {"ticker": "TEST", "period": "2025", "value": 120}

    monkeypatch.setattr(financials, "financial_series", payload)
    monkeypatch.setattr(financials, "financial_passport", payload)
    path = f"{prefix}/company/TEST/{resource}"
    client = TestClient(api.app)
    anonymous = client.get(path)
    assert anonymous.status_code == 200
    assert anonymous.json()["value"] == 120
    with monkeypatch.context() as signed_in:
        signed_in.setitem(api.app.dependency_overrides, _require_user, lambda: SimpleNamespace(id=1))
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["value"] == 120
        assert response.json() == anonymous.json()
    logged_out = client.get(path)
    assert logged_out.status_code == 200
    assert logged_out.json() == anonymous.json()
    if resource == "financials":
        assert "public" in logged_out.headers["cache-control"]
        assert client.get(path, headers={"If-None-Match": logged_out.headers["etag"]}).status_code == 304


def test_deliberately_public_configuration_remains_cacheable():
    client = TestClient(api.app)
    response = client.get("/api/config")
    assert response.status_code == 200
    assert "public" in response.headers["cache-control"]
    assert client.get("/api/config", headers={"If-None-Match": response.headers["etag"]}).status_code == 304
