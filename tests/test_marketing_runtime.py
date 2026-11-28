import json

import pytest

from marketing import model_runtime
from llm_client import LLMError
from test_marketing_core import isolated  # noqa: F401


def test_local_model_uses_structured_no_tool_chat(monkeypatch):
    calls = []
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"done": True, "message": {"content": json.dumps({"summary": "actual local response"})}}
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr("requests.post", post)
    client = model_runtime.OllamaModel("http://127.0.0.1:11434", "installed-model")
    result = client.complete_json("role", "context", response_schema={"type": "object"})
    assert result["summary"] == "actual local response"
    payload = calls[0][1]["json"]
    assert payload["stream"] is False and payload["format"] == {"type": "object"}
    assert "tools" not in payload


def test_unconfigured_model_has_no_fake_success(monkeypatch):
    monkeypatch.setenv("MARKETING_MODEL_PROVIDER", "disabled")
    assert model_runtime.status()["configured"] is False
    with pytest.raises(LLMError):
        model_runtime.get_model().complete_json("role", "context")


def test_local_model_error_does_not_expose_private_url(monkeypatch):
    import requests
    def fail(*args, **kwargs):
        raise requests.ConnectionError("private-host-and-secret")
    monkeypatch.setattr(requests, "post", fail)
    with pytest.raises(LLMError) as error:
        model_runtime.OllamaModel("http://127.0.0.1:11434", "installed-model").complete_json("role", "context")
    assert "private-host-and-secret" not in str(error.value)


@pytest.fixture
def news_codex(monkeypatch):
    monkeypatch.delenv("MARKETING_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("MARKETING_MODEL", raising=False)
    monkeypatch.delenv("MARKETING_CODEX_REASONING", raising=False)
    monkeypatch.setenv("NEWS_AI_PROVIDER", "codex")
    monkeypatch.setenv("NEWS_CODEX_GATEWAY_URL", "http://codex.internal:8080")
    monkeypatch.setenv("CODEX_GATEWAY_SECRET", "test-gateway-secret")
    monkeypatch.setenv("NEWS_CODEX_MODEL", "configured-news-model")
    monkeypatch.setenv("NEWS_CODEX_REASONING", "low")
    monkeypatch.setenv("NEWS_CODEX_FALLBACK_MODEL", "configured-fallback")
    monkeypatch.setenv("NEWS_CODEX_TIMEOUT", "240")


@pytest.mark.parametrize("empty_override", [None, "", "  "])
def test_marketing_reuses_the_news_codex_gateway(monkeypatch, news_codex, empty_override):
    from codex_client import CodexGatewayClient

    if empty_override is not None:
        monkeypatch.setenv("MARKETING_MODEL", empty_override)
        monkeypatch.setenv("MARKETING_CODEX_REASONING", empty_override)
    status = model_runtime.status()
    assert status["provider"] == "codex"
    assert status["model"] == "gpt-6.1-terra"
    assert status["configured"] is True
    assert status["execution"] == "configured_gateway"
    assert "codex.internal" not in json.dumps(status)
    assert "test-gateway-secret" not in json.dumps(status)
    client = model_runtime.get_model()
    assert isinstance(client, CodexGatewayClient)
    assert client.url == "http://codex.internal:8080"
    assert client.secret == "test-gateway-secret"
    assert client.model == "gpt-6.1-terra"
    assert client.effort == "medium"
    assert client.fallback_model == "configured-fallback"
    assert client.model_timeout == 240
    assert client.retries == 1


def test_marketing_can_select_codex_and_its_own_model(monkeypatch, news_codex):
    monkeypatch.setenv("NEWS_AI_PROVIDER", "claude")
    monkeypatch.setenv("MARKETING_MODEL_PROVIDER", "codex")
    monkeypatch.setenv("MARKETING_MODEL", "configured-marketing-model")
    monkeypatch.setenv("MARKETING_CODEX_REASONING", "high")
    client = model_runtime.get_model()
    assert client.model == "configured-marketing-model"
    assert client.effort == "high"


@pytest.mark.parametrize("missing", ["NEWS_CODEX_GATEWAY_URL", "CODEX_GATEWAY_SECRET"])
def test_incomplete_codex_gateway_never_uses_another_login(monkeypatch, news_codex, missing):
    monkeypatch.setenv(missing, "  ")
    monkeypatch.setattr(model_runtime.shutil, "which", lambda _name: "/installed/codex")
    assert model_runtime.status()["configured"] is False
    with pytest.raises(LLMError, match="not configured"):
        model_runtime.get_model().complete_json("role", "context")


@pytest.mark.parametrize("provider", ["disabled", "ollama", "claude"])
def test_explicit_marketing_provider_takes_priority(monkeypatch, news_codex, provider):
    monkeypatch.setenv("MARKETING_MODEL_PROVIDER", provider)
    assert model_runtime.status()["provider"] == provider


def test_codex_accepts_the_actual_marketing_role_schema(monkeypatch, news_codex):
    from marketing.agents import RoleResult
    from test_marketing_agents import output

    schema = RoleResult.model_json_schema()
    reply = output("Ask the owner for a measured baseline", questions=["Which period was measured?"])

    class Response:
        status_code = 200

        def json(self):
            return {"data": {"result_json": json.dumps(reply)}}

    def post(url, **options):
        payload = options["json"]
        wire_schema = payload["response_schema"]
        assert wire_schema["required"] == list(wire_schema["properties"])
        assert wire_schema["additionalProperties"] is False
        assert wire_schema["properties"]["result_json"]["type"] == "string"
        assert json.dumps(schema, ensure_ascii=False) in payload["system"]
        return Response()

    monkeypatch.setattr("requests.post", post)
    result = model_runtime.get_model().complete_json("CMO role", "Owner brief", response_schema=schema)
    assert result == reply
    assert RoleResult.model_validate(result).questions == reply["questions"]


@pytest.mark.parametrize("encoded", ["[]", "invalid private upstream response"])
def test_codex_rejects_invalid_role_json_without_exposing_it(monkeypatch, news_codex, encoded):
    class Response:
        status_code = 200

        def json(self):
            return {"data": {"result_json": encoded}}

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: Response())
    with pytest.raises(LLMError) as error:
        model_runtime.get_model().complete_json("CMO role", "Owner brief", response_schema={"type": "object"})
    assert encoded not in str(error.value)
