from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import codex_client as cc
import news_classifier as nc
from llm_client import Usage


def _success(message: str, *, model_tokens: bool = True) -> subprocess.CompletedProcess:
    events = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": message}},
    ]
    if model_tokens:
        events.append({
            "type": "turn.completed",
            "usage": {"input_tokens": 120, "cached_input_tokens": 20, "output_tokens": 9},
        })
    stdout = "\n".join(json.dumps(event) for event in events)
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def test_codex_uses_selected_model_schema_and_isolated_environment(monkeypatch) -> None:
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen.update(kwargs)
        return _success('{"pass": true, "score": 0.91}')

    monkeypatch.setattr(cc.shutil, "which", lambda _name: "/usr/local/bin/codex")
    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    monkeypatch.setenv("CODEX_HOME", "/home/appuser/.codex")
    monkeypatch.setenv("DATABASE_URL", "must-not-reach-codex")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-codex")
    monkeypatch.setenv("CODEX_AUTH_JSON_B64", "must-not-reach-codex")
    usage = Usage()

    result = cc.CodexClient(
        model="gpt-5.6-luna",
        reasoning_effort="low",
        fallback_model=None,
    ).complete_json(
        "Return a triage verdict.",
        "TITLE: Market news",
        usage=usage,
        response_schema=nc._TRIAGE_SCHEMA,
    )

    assert result == {"pass": True, "score": 0.91}
    assert seen["command"][seen["command"].index("--model") + 1] == "gpt-5.6-luna"
    assert "features.shell_tool=false" in seen["command"]
    assert 'web_search="disabled"' in seen["command"]
    assert "agents.enabled=false" in seen["command"]
    assert "--output-schema" in seen["command"]
    assert "Do not inspect files" in seen["input"]
    assert seen["env"]["CODEX_HOME"] == "/home/appuser/.codex"
    assert "DATABASE_URL" not in seen["env"]
    assert "OPENAI_API_KEY" not in seen["env"]
    assert "CODEX_AUTH_JSON_B64" not in seen["env"]
    assert (usage.prompt_tokens, usage.cached_prompt_tokens, usage.completion_tokens) == (120, 20, 9)
    assert usage.calls == 1
    assert usage.model == "gpt-5.6-luna"
    assert usage.subscription_tokens == 129
    assert usage.est_cost_usd() == 0.0


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


def test_codex_accepts_a_fenced_json_final_message(monkeypatch) -> None:
    monkeypatch.setattr(cc.shutil, "which", lambda _name: "/usr/local/bin/codex")
    monkeypatch.setattr(
        cc.subprocess,
        "run",
        lambda *a, **k: _success('```json\n{"summary_en": "A", "summary_uz": "B"}\n```'),
    )

    result = cc.CodexClient(fallback_model=None).complete_json("Translate", "Text")

    assert result == {"summary_en": "A", "summary_uz": "B"}


def test_codex_tries_the_second_subscription_model(monkeypatch) -> None:
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if len(commands) == 1:
            return subprocess.CompletedProcess([], 1, stdout="", stderr="model unavailable")
        return _success('{"pass": false, "score": 0.1}')

    monkeypatch.setattr(cc.shutil, "which", lambda _name: "/usr/local/bin/codex")
    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    client = cc.CodexClient(
        model="gpt-5.6-luna",
        fallback_model="gpt-5.6-terra",
    )

    result = client.complete_json("Judge", "News")

    assert result == {"pass": False, "score": 0.1}
    assert [command[command.index("--model") + 1] for command in commands] == [
        "gpt-5.6-luna", "gpt-5.6-terra"]


def test_classifier_provider_builds_configured_codex_client(monkeypatch) -> None:
    captured = {}

    class _Codex:
        model = "gpt-5.6-luna"

        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(nc, "_client", None)
    monkeypatch.setattr(nc, "_CODEX_MODEL", "gpt-5.6-luna")
    monkeypatch.setattr(nc, "_CODEX_REASONING", "low")
    monkeypatch.setattr(nc, "_CODEX_FALLBACK_MODEL", "gpt-5.6-terra")
    monkeypatch.setattr(nc, "_CODEX_TIMEOUT", 90.0)
    monkeypatch.setattr(nc, "CodexClient", _Codex)

    client = nc.get_classifier_client()

    assert isinstance(client, _Codex)
    assert captured["model"] == "gpt-5.6-luna"
    assert captured["reasoning_effort"] == "low"
    assert captured["fallback_model"] == "gpt-5.6-terra"
    assert captured["timeout"] == 90.0
    assert nc.classifier_model_name() == "gpt-5.6-luna"


@pytest.mark.parametrize("reasoning", ["none", "ultra", "fast"])
def test_invalid_reasoning_level_is_rejected(reasoning) -> None:
    with pytest.raises(ValueError, match="reasoning effort"):
        cc.CodexClient(reasoning_effort=reasoning)
