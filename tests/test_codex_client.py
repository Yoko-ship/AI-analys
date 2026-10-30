from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys

import pytest

import codex_client as cc
import news_classifier as nc
from llm_client import Usage


@pytest.mark.skipif(os.name != 'posix', reason='Production uses POSIX process groups')
@pytest.mark.parametrize('ignore_term', [False, True])
def test_timeout_stops_cli_descendants_before_fallback(monkeypatch, tmp_path, ignore_term):
    """The npm launcher spawns the native CLI; timing out just the launcher leaks it."""
    launcher = tmp_path / 'codex'
    launcher.write_text(f'#!{sys.executable}\n' + '''import json, subprocess, sys
if sys.argv[sys.argv.index('--model') + 1] == 'gpt-6.1-terra':
    print(json.dumps({'type':'item.completed', 'item':{'type':'agent_message', 'text':'{"pass":true}'}}))
else:
    child = subprocess.Popen([sys.executable, '-S', '-c', ''' + repr(
        'import os, signal; '
        + ('signal.signal(signal.SIGTERM, signal.SIG_IGN); ' if ignore_term else '')
        + 'print(os.getpid(), flush=True); signal.pause()'
    ) + '''])
    child.wait()
''')
    launcher.chmod(0o700)
    popen = subprocess.Popen
    processes, child_pids, cleanup_timeouts = [], [], []

    def running(pid):
        # Orphan zombies may await init's reap; they no longer execute or hold pipes.
        with popen(['ps', '-p', str(pid), '-o', 'stat='], stdout=subprocess.PIPE, text=True) as probe:
            state = probe.communicate(timeout=5)[0].strip()
        return bool(state) and not state.startswith('Z')

    def start(command, **kwargs):
        if processes:
            assert not running(child_pids[0]), 'native CLI survived into the fallback attempt'
        process = popen(command, **kwargs)
        processes.append(process)
        if len(processes) == 1:
            communicate = process.communicate
            calls = 0

            def simulated_deadline(input=None, timeout=None):
                nonlocal calls
                calls += 1
                if calls == 1:
                    # Wait for a real child to start, then advance directly to the deadline.
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        assert selector.select(timeout=10), 'fixture child failed to start'
                    child_pids.append(int(process.stdout.readline().strip()))
                    raise subprocess.TimeoutExpired(command, timeout)
                if ignore_term and calls == 2:
                    cleanup_timeouts.append(timeout)
                    raise subprocess.TimeoutExpired(command, timeout)
                return communicate(input=input, timeout=timeout)

            process.communicate = simulated_deadline
        return process

    monkeypatch.setattr(cc.subprocess, 'Popen', start)
    try:
        result = cc.CodexClient(executable=str(launcher)).complete_json('Classify', 'Issuer disclosure')
        assert result == {'pass': True}
        assert not running(child_pids[0])
        if ignore_term:
            assert cleanup_timeouts == [5]
    finally:
        for pid in child_pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


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
    monkeypatch.setattr(cc, "_run_codex", fake_run)
    monkeypatch.setenv("CODEX_HOME", "/home/appuser/.codex")
    monkeypatch.setenv("DATABASE_URL", "must-not-reach-codex")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-codex")
    monkeypatch.setenv("CODEX_AUTH_JSON_B64", "must-not-reach-codex")
    usage = Usage()

    result = cc.CodexClient(
        model="gpt-6-luna",
        reasoning_effort="low",
        fallback_model=None,
    ).complete_json(
        "Return a triage verdict.",
        "TITLE: Market news",
        usage=usage,
        response_schema=nc._TRIAGE_SCHEMA,
    )

    assert result == {"pass": True, "score": 0.91}
    assert seen["command"][seen["command"].index("--model") + 1] == "gpt-6-luna"
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
    assert usage.model == "gpt-6-luna"
    assert usage.subscription_tokens == 129
    assert usage.est_cost_usd() == 0.0


def test_codex_accepts_a_fenced_json_final_message(monkeypatch) -> None:
    monkeypatch.setattr(cc.shutil, "which", lambda _name: "/usr/local/bin/codex")
    monkeypatch.setattr(
        cc,
        "_run_codex",
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
    monkeypatch.setattr(cc, "_run_codex", fake_run)
    client = cc.CodexClient(
        model="gpt-6-luna",
        fallback_model="gpt-6.1-terra",
    )

    result = client.complete_json("Judge", "News")

    assert result == {"pass": False, "score": 0.1}
    assert [command[command.index("--model") + 1] for command in commands] == [
        "gpt-6-luna", "gpt-6.1-terra"]


def test_classifier_provider_builds_configured_codex_client(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_AI_PROVIDER", "codex")
    captured = {}

    class _Codex:
        model = "gpt-6-luna"

        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(nc, "_client", None)
    monkeypatch.setattr(nc, "_CODEX_MODEL", "gpt-6-luna")
    monkeypatch.setattr(nc, "_CODEX_REASONING", "low")
    monkeypatch.setattr(nc, "_CODEX_FALLBACK_MODEL", "gpt-6.1-terra")
    monkeypatch.setattr(nc, "_CODEX_TIMEOUT", 90.0)
    monkeypatch.setattr(nc, "CodexClient", _Codex)

    client = nc.get_classifier_client()

    assert isinstance(client, _Codex)
    assert captured["model"] == "gpt-6-luna"
    assert captured["reasoning_effort"] == "low"
    assert captured["fallback_model"] == "gpt-6.1-terra"
    assert captured["timeout"] == 90.0
    assert nc.classifier_model_name() == "gpt-6-luna"


@pytest.mark.parametrize("reasoning", ["none", "ultra", "fast"])
def test_invalid_reasoning_level_is_rejected(reasoning) -> None:
    with pytest.raises(ValueError, match="reasoning effort"):
        cc.CodexClient(reasoning_effort=reasoning)
