from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import claude_client as cc
import news_classifier as nc
from llm_client import Usage

_RATE_LIMIT = {
    "type": "rate_limit_event",
    "rate_limit_info": {
        "status": "allowed",
        "unifiedWindows": {
            "five_hour": {"utilization": 0.12, "resetsAt": 1791364800},
            "seven_day": {"utilization": 0.14, "resetsAt": 1791813600},
        },
    },
}


def _success(structured=None, *, text: str = "", rate_limit: dict | None = None) -> subprocess.CompletedProcess:
    events = [{"type": "system", "subtype": "init", "tools": ["StructuredOutput"]}]
    if rate_limit is not None:
        events.append(rate_limit)
    events.append({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": text or json.dumps(structured),
        "structured_output": structured,
        "usage": {
            "input_tokens": 100,
            "cache_read_input_tokens": 20,
            "cache_creation_input_tokens": 0,
            "output_tokens": 9,
        },
    })
    stdout = "\n".join(json.dumps(event) for event in events)
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    cc.reset_observed_rate_limits()
    yield
    cc.reset_observed_rate_limits()


def test_claude_uses_selected_model_schema_and_isolated_environment(monkeypatch) -> None:
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen.update(kwargs)
        return _success({"pass": True, "score": 0.91})

    monkeypatch.setattr(cc.shutil, "which", lambda _name: "/usr/local/bin/claude")
    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-test")
    monkeypatch.setenv("DATABASE_URL", "must-not-reach-claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-claude")
    monkeypatch.setenv("ADMIN_API_SECRET", "must-not-reach-claude")
    usage = Usage()

    result = cc.ClaudeCodeClient(
        model="claude-haiku-4-5",
        effort="low",
        fallback_model=None,
    ).complete_json(
        "Return a triage verdict.",
        "TITLE: Market news",
        usage=usage,
        response_schema=nc._TRIAGE_SCHEMA,
    )

    command = seen["command"]
    assert result == {"pass": True, "score": 0.91}
    assert command[command.index("--model") + 1] == "claude-haiku-4-5"
    assert command[command.index("--effort") + 1] == "low"
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in command
    assert "--no-session-persistence" in command
    assert json.loads(command[command.index("--json-schema") + 1]) == nc._TRIAGE_SCHEMA
    assert "Return a triage verdict." in command[command.index("--system-prompt") + 1]
    assert "TITLE: Market news" in seen["input"]
    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat-test"
    assert seen["env"]["DISABLE_AUTOUPDATER"] == "1"
    assert "DATABASE_URL" not in seen["env"]
    assert "ANTHROPIC_API_KEY" not in seen["env"]
    assert "ADMIN_API_SECRET" not in seen["env"]
    assert (usage.prompt_tokens, usage.cached_prompt_tokens, usage.completion_tokens) == (120, 20, 9)
    assert usage.calls == 1
    assert usage.model == "claude-haiku-4-5"
    assert usage.subscription_tokens == 129
    assert usage.est_cost_usd() == 0.0


def test_claude_accepts_a_fenced_json_result_without_structured_output(monkeypatch) -> None:
    monkeypatch.setattr(cc.shutil, "which", lambda _name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        cc.subprocess,
        "run",
        lambda *a, **k: _success(None, text='```json\n{"summary_en": "A", "summary_uz": "B"}\n```'),
    )

    result = cc.ClaudeCodeClient(fallback_model=None).complete_json("Translate", "Text")

    assert result == {"summary_en": "A", "summary_uz": "B"}


def test_claude_error_result_is_raised(monkeypatch) -> None:
    error = {"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}
    monkeypatch.setattr(cc.shutil, "which", lambda _name: "/usr/local/bin/claude")
    monkeypatch.setattr(cc.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        [], 1, stdout=json.dumps(error), stderr=""))

    with pytest.raises(cc.LLMError, match="Not logged in"):
        cc.ClaudeCodeClient(fallback_model=None).complete_json("Judge", "News")


def test_claude_tries_the_second_subscription_model(monkeypatch) -> None:
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if len(commands) == 1:
            return subprocess.CompletedProcess([], 1, stdout="", stderr="model unavailable")
        return _success({"pass": False, "score": 0.1})

    monkeypatch.setattr(cc.shutil, "which", lambda _name: "/usr/local/bin/claude")
    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    client = cc.ClaudeCodeClient(
        model="claude-haiku-4-5",
        fallback_model="claude-sonnet-5-5",
    )

    result = client.complete_json("Judge", "News")

    assert result == {"pass": False, "score": 0.1}
    assert [command[command.index("--model") + 1] for command in commands] == [
        "claude-haiku-4-5", "claude-sonnet-5-5"]


def test_rate_limit_events_record_first_and_latest_reading(monkeypatch) -> None:
    later = json.loads(json.dumps(_RATE_LIMIT))
    later["rate_limit_info"]["unifiedWindows"]["five_hour"]["utilization"] = 0.15
    responses = iter([_success({"a": 1}, rate_limit=_RATE_LIMIT), _success({"a": 2}, rate_limit=later)])
    monkeypatch.setattr(cc.shutil, "which", lambda _name: "/usr/local/bin/claude")
    monkeypatch.setattr(cc.subprocess, "run", lambda *a, **k: next(responses))
    client = cc.ClaudeCodeClient(fallback_model=None)

    client.complete_json("A", "B")
    client.complete_json("A", "B")
    first, last = cc.observed_rate_limits()

    assert first == {
        "limit_id": "five_hour",
        "used_percent": 12.0,
        "window_minutes": 300,
        "resets_at": 1791364800,
        "seven_day_used_percent": 14.0,
        "status": "allowed",
    }
    assert last["used_percent"] == 15.0


@pytest.mark.parametrize(
    "config_path",
    [
        "railway.json",
        "railway.news.json",
        "railway.collector.json",
        "railway.bank-fx.json",
        "railway.reports-watch.json",
    ],
)
def test_railway_start_overrides_preserve_the_secure_entrypoint(config_path) -> None:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))

    assert config["deploy"]["startCommand"].startswith(
        "/usr/local/bin/docker-entrypoint.sh "
    )


def test_classifier_provider_builds_configured_claude_client(monkeypatch) -> None:
    captured = {}

    class _Claude:
        model = "claude-haiku-4-5"

        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(nc, "_client", None)
    monkeypatch.setattr(nc, "_CLAUDE_MODEL", "claude-haiku-4-5")
    monkeypatch.setattr(nc, "_CLAUDE_EFFORT", "low")
    monkeypatch.setattr(nc, "_CLAUDE_FALLBACK_MODEL", "claude-sonnet-5-5")
    monkeypatch.setattr(nc, "_CLAUDE_TIMEOUT", 90.0)
    monkeypatch.setattr(nc, "ClaudeCodeClient", _Claude)

    client = nc.get_classifier_client()

    assert isinstance(client, _Claude)
    assert captured["model"] == "claude-haiku-4-5"
    assert captured["effort"] == "low"
    assert captured["fallback_model"] == "claude-sonnet-5-5"
    assert captured["timeout"] == 90.0
    assert nc.classifier_model_name() == "claude-haiku-4-5"


@pytest.mark.parametrize("effort", ["none", "minimal", "ultra"])
def test_invalid_effort_level_is_rejected(effort) -> None:
    with pytest.raises(ValueError, match="effort"):
        cc.ClaudeCodeClient(effort=effort)


def test_gateway_client_posts_settings_and_collects_usage(monkeypatch) -> None:
    import requests

    seen = {}

    class _Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "data": {"pass": True, "score": 0.8},
                "usage": {"prompt_tokens": 50, "completion_tokens": 5, "cached_prompt_tokens": 10,
                          "calls": 1, "model": "claude-haiku-4-5"},
                "rate_limit": {"limit_id": "five_hour", "used_percent": 20.0, "resets_at": 1},
            }

    def fake_post(url, *, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return _Response()

    monkeypatch.setattr(requests, "post", fake_post)
    usage = Usage()
    client = cc.ClaudeGatewayClient("http://gw:8080/", "s3cret", model="claude-haiku-4-5",
                                    fallback_model="claude-sonnet-5-5")

    result = client.complete_json("Judge", "News", usage=usage, response_schema={"type": "object"})

    assert result == {"pass": True, "score": 0.8}
    assert seen["url"] == "http://gw:8080/v1/json"
    assert seen["headers"] == {"Authorization": "Bearer s3cret"}
    assert seen["json"]["model"] == "claude-haiku-4-5"
    assert seen["json"]["fallback_model"] == "claude-sonnet-5-5"
    assert seen["json"]["response_schema"] == {"type": "object"}
    assert (usage.prompt_tokens, usage.cached_prompt_tokens, usage.calls) == (50, 10, 1)
    assert cc.observed_rate_limits()[1]["used_percent"] == 20.0


def test_gateway_client_retries_while_the_gateway_restarts(monkeypatch) -> None:
    import requests

    calls = []

    class _Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"data": {"ok": True}, "usage": {}}

    def fake_post(url, **kwargs):
        calls.append(url)
        if len(calls) < 3:
            raise requests.ConnectionError("refused")
        return _Response()

    monkeypatch.setattr(requests, "post", fake_post)
    client = cc.ClaudeGatewayClient("http://gw:8080", "s", retry_delay=0)

    assert client.complete_json("A", "B") == {"ok": True}
    assert len(calls) == 3


def test_gateway_requires_its_secret_and_a_login(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import claude_gateway as gw

    monkeypatch.setattr(gw, "_SECRET", "s3cret")
    monkeypatch.setattr(gw, "auth_status", lambda **_: {"logged_in": False, "auth_method": "none"})
    client = TestClient(gw.app)
    body = {"system": "Judge", "user": "News"}

    assert client.post("/v1/json", json=body).status_code == 401
    assert client.post("/v1/json", json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
    refused = client.post("/v1/json", json=body, headers={"Authorization": "Bearer s3cret"})
    assert refused.status_code == 502
    assert "auth login" in refused.json()["detail"]
    assert client.get("/health").json()["logged_in"] is False


def test_gateway_serves_a_classification(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import claude_gateway as gw

    monkeypatch.setattr(gw, "_SECRET", "s3cret")
    monkeypatch.setattr(gw, "auth_status", lambda **_: {"logged_in": True, "auth_method": "claude.ai"})
    monkeypatch.setattr(cc.shutil, "which", lambda _name: "/usr/local/bin/claude")
    monkeypatch.setattr(cc.subprocess, "run",
                        lambda *a, **k: _success({"pass": True, "score": 0.9}, rate_limit=_RATE_LIMIT))

    response = TestClient(gw.app).post("/v1/json", json={"system": "Judge", "user": "News"},
                                       headers={"Authorization": "Bearer s3cret"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"pass": True, "score": 0.9}
    assert body["usage"]["calls"] == 1
    assert body["rate_limit"]["used_percent"] == 12.0
