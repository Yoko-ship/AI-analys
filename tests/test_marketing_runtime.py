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
