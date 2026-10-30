import json
import subprocess

import pytest
from fastapi.testclient import TestClient

import codex_client as cc
import codex_gateway as gw
import news_classifier as nc
from llm_client import Usage


def test_gateway_rejects_missing_secret_and_missing_subscription(monkeypatch):
    monkeypatch.setattr(gw, "_SECRET", "test-secret")
    monkeypatch.setattr(gw, "auth_status", lambda **kw: {"logged_in": False})
    client = TestClient(gw.app)
    body = {"system": "Classify", "user": "A filing"}
    assert client.post("/v1/json", json=body).status_code == 401
    assert client.post("/v1/json", json=body, headers={"Authorization": "Bearer test-secret"}).status_code == 502


def test_gateway_classifies_real_agmk_filing_and_returns_usage(monkeypatch):
    monkeypatch.setattr(gw, "_SECRET", "test-secret")
    monkeypatch.setattr(gw, "auth_status", lambda **kw: {"logged_in": True})
    verdict = {"tone": "neutral", "tone_score": 0, "impact": "low", "direction": "unclear",
               "summary_ru": "Олмалык КМК раскрыл решения собрания 29 сентября 2026 года.",
               "summary_en": "Olmaliq KMK disclosed decisions of its September 29, 2026 meeting.",
               "summary_uz": "Olmaliq KMK 2026 yil 29 sentabrdagi yig‘ilish qarorlarini oshkor qildi.",
               "reason": "Issuer disclosure"}
    def complete(self, system, user, **kwargs):
        assert "29.09.2026" in user
        assert kwargs["response_schema"] == nc._FILING_SCHEMA
        kwargs["usage"].calls = 1
        kwargs["usage"].model = "gpt-6-luna"
        kwargs["usage"].prompt_tokens = 100
        return verdict
    monkeypatch.setattr(cc.CodexClient, "complete_json", complete)
    client = TestClient(gw.app)
    response = client.post("/v1/json", headers={"Authorization": "Bearer test-secret"}, json={
        "system": "Classify issuer disclosure", "user": '"Olmaliq KMK" AJ: собрание 29.09.2026, кворум 100.00%',
        "response_schema": nc._FILING_SCHEMA,
    })
    assert response.status_code == 200
    assert response.json()["data"] == verdict
    assert response.json()["usage"]["model"] == "gpt-6-luna"
    assert response.json()["usage"]["calls"] == 1


@pytest.mark.parametrize("status,expected", [("Logged in using ChatGPT", True), ("Logged in using an API key", False)])
def test_health_accepts_only_subscription_auth(monkeypatch, status, expected):
    monkeypatch.setattr(gw.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess([], 0, stdout="", stderr=status))
    assert gw.auth_status(max_age=0)["logged_in"] is expected


def test_provider_selects_codex_gateway(monkeypatch):
    monkeypatch.setenv("NEWS_AI_PROVIDER", "codex")
    monkeypatch.setenv("NEWS_CODEX_GATEWAY_URL", "http://codex:8080")
    monkeypatch.setenv("CODEX_GATEWAY_SECRET", "test-secret")
    monkeypatch.setattr(nc, "_client", None)
    client = nc.get_classifier_client()
    assert isinstance(client, cc.CodexGatewayClient)
    assert client.url == "http://codex:8080"
    assert nc.classifier_model_name() == "gpt-6-luna"


def test_gateway_transport_accounts_subscription_tokens(monkeypatch):
    import requests
    class Response:
        status_code = 200
        def json(self):
            return {"data": {"pass": True}, "usage": {"calls": 1, "prompt_tokens": 100,
                    "completion_tokens": 10, "cached_prompt_tokens": 20, "model": "gpt-6-luna"}}
    def post(url, **kw):
        assert kw["headers"] == {"Authorization": "Bearer test-secret"}
        assert kw["json"]["model"] == "gpt-6-luna"
        return Response()
    monkeypatch.setattr(requests, "post", post)
    usage = Usage()
    client = cc.CodexGatewayClient("http://codex:8080", "test-secret")
    assert client.complete_json("Classify", "News", usage=usage) == {"pass": True}
    assert usage.subscription_tokens == 110
    assert usage.est_cost_usd() == 0
