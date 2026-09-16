from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import soliq_company


class _Response:
    status_code = 200
    ok = True

    def json(self):
        return {
            "company": {
                "tin": "200833833", "name": "O'ZBEKISTON POCHTASI AJ",
                "soato": 1726269, "kfs": 100, "taxpayerType": 3,
                "taxMode": 1, "vatNumber": 326020005438, "businessFund": 3163843598548.2,
            },
            "director": {"firstName": "ALISHER"},
        }


def _index():
    entry = {"org_id": "667", "name": "O'zbekiston pochtasi"}
    return {"by_ticker": {"UPOS": entry, "UPOSP": entry}, "by_inn": {"200833833": entry}}


def test_resolves_inn_and_calls_full_soliq_only_for_requested_ticker(monkeypatch):
    calls = []
    monkeypatch.setenv("SOLIQ_API_KEY", "server-secret")
    monkeypatch.setattr(soliq_company, "get_org_index", lambda force=False: _index())

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response()

    monkeypatch.setattr(soliq_company.requests, "get", fake_get)
    result = soliq_company.fetch_company_registry("upos")

    assert result["ticker"] == "UPOS"
    assert result["tin"] == "200833833"
    assert result["type"] == "full"
    assert result["registry"]["company"]["tin"] == "200833833"
    assert not set(soliq_company._UNRELIABLE_COMPANY_FIELDS) & set(result["registry"]["company"])
    assert result["location"] is None
    assert len(calls) == 1
    url, options = calls[0]
    assert url.endswith("/company/info/200833833")
    assert options["params"] == {"type": "full"}
    assert options["headers"]["X-API-KEY"] == "server-secret"


def test_registry_coordinates_are_normalised_without_geocoding(monkeypatch):
    monkeypatch.setenv("SOLIQ_API_KEY", "server-secret")
    monkeypatch.setattr(soliq_company, "get_org_index", lambda force=False: _index())

    class _LocatedResponse(_Response):
        def json(self):
            return {
                "company": {"tin": "200833833", "name": "O'ZBEKISTON POCHTASI AJ"},
                "companyBillingAddress": {"lat": "41.311081", "lng": "69.240562"},
            }

    monkeypatch.setattr(soliq_company.requests, "get", lambda *args, **kwargs: _LocatedResponse())
    result = soliq_company.fetch_company_registry("UPOS")

    assert result["location"] == {"latitude": 41.311081, "longitude": 69.240562}


@pytest.mark.parametrize(
    "address",
    [
        {"latitude": 0, "longitude": 0},
        {"latitude": 69.240562, "longitude": 41.311081},
        {"latitude": "not-a-number", "longitude": 69.240562},
    ],
)
def test_untrusted_registry_coordinates_are_rejected(address):
    assert soliq_company._registry_location({"companyBillingAddress": address}) is None


def test_preferred_share_uses_the_same_issuer_inn(monkeypatch):
    monkeypatch.setattr(soliq_company, "get_org_index", lambda force=False: _index())
    assert soliq_company.resolve_company_tin("UPOSP")["tin"] == "200833833"


def test_missing_server_key_stops_before_openinfo_or_soliq(monkeypatch):
    monkeypatch.delenv("SOLIQ_API_KEY", raising=False)
    monkeypatch.setattr(
        soliq_company,
        "get_org_index",
        lambda force=False: pytest.fail("OpenInfo must not be called without server configuration"),
    )
    with pytest.raises(soliq_company.SoliqConfigurationError):
        soliq_company.fetch_company_registry("UPOS")


def test_company_registry_route_is_lazy_and_normalises_ticker(monkeypatch):
    api = importlib.import_module("api")
    calls = []

    def fake_fetch(ticker):
        calls.append(ticker)
        return {
            "ticker": "UPOS",
            "tin": "200833833",
            "org_id": "667",
            "type": "full",
            "registry": _Response().json(),
        }

    monkeypatch.setattr(api.soliq_company, "fetch_company_registry", fake_fetch)
    client = TestClient(api.app)
    assert calls == []
    response = client.get("/api/company/upos/registry")
    assert response.status_code == 200
    assert response.json()["registry"]["company"]["tin"] == "200833833"
    assert calls == ["UPOS"]
