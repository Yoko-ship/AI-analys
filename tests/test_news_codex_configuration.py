from pathlib import Path
import json
import subprocess
import sys

import pytest

from scripts.configure_news_codex import configure


def read_env(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def configure_after_health(directory, status):
    return subprocess.run(
        [sys.executable, 'scripts/configure_news_codex.py', str(directory), '--health-stdin'],
        input=json.dumps(status), text=True, capture_output=True, check=False,
    )


def test_switch_preserves_settings_and_persists_the_gateway_secret(tmp_path):
    news = tmp_path / "news-collector.env"
    news.write_text("CLAUDE_GATEWAY_SECRET=existing-secret\nNEWS_BATCH_SIZE=7\n")
    configure(tmp_path)
    gateway = tmp_path / "codex-gateway.env"
    settings = read_env(news)
    # Preparing the volume must not switch a working legacy collector before login.
    assert settings.get("NEWS_AI_PROVIDER", "claude") == "claude"
    assert settings["NEWS_CLAUDE_GATEWAY_URL"] == "http://uzstock-claude-gateway:8080"
    assert settings["NEWS_CODEX_GATEWAY_URL"] == "http://uzstock-codex-gateway:8080"
    assert settings["NEWS_PUSH_URL"] == "http://uzstock-web:8000"
    assert settings["NEWS_BATCH_SIZE"] == "7"
    assert settings["CLAUDE_GATEWAY_SECRET"] == "existing-secret"
    secret = read_env(gateway)["CODEX_GATEWAY_SECRET"]
    assert len(secret) >= 32
    assert settings["CODEX_GATEWAY_SECRET"] == secret
    assert gateway.stat().st_mode & 0o777 == 0o600
    assert news.stat().st_mode & 0o777 == 0o600
    configure(tmp_path)
    assert read_env(gateway)["CODEX_GATEWAY_SECRET"] == secret
    assert configure_after_health(tmp_path, {"logged_in": True}).returncode == 0
    assert read_env(news)["NEWS_AI_PROVIDER"] == "codex"
    assert read_env(gateway)["CODEX_GATEWAY_SECRET"] == secret


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_deployment_preserves_explicit_provider_and_endpoints(tmp_path, provider):
    news = tmp_path / 'news-collector.env'
    news.write_text(f'NEWS_AI_PROVIDER={provider}\nNEWS_PUSH_URL=http://custom-web:8000\n'
                    'NEWS_CODEX_GATEWAY_URL=http://custom-codex:8080\n')
    configure(tmp_path)
    assert configure_after_health(tmp_path, {'logged_in': True}).returncode == 0
    settings = read_env(news)
    assert settings['NEWS_AI_PROVIDER'] == provider
    assert settings['NEWS_PUSH_URL'] == 'http://custom-web:8000'
    assert settings['NEWS_CODEX_GATEWAY_URL'] == 'http://custom-codex:8080'


@pytest.mark.parametrize('status', [{'logged_in': False}, {}, {'logged_in': 'false'}])
def test_unavailable_login_never_activates_codex(tmp_path, status):
    assert configure_after_health(tmp_path, status).returncode == 0
    assert read_env(tmp_path / 'news-collector.env').get('NEWS_AI_PROVIDER', 'claude') == 'claude'


def test_selected_codex_without_login_fails_deployment_without_rewriting_settings(tmp_path):
    news = tmp_path / 'news-collector.env'
    original = 'NEWS_AI_PROVIDER=codex\nNEWS_BATCH_SIZE=7\n'
    news.write_text(original)
    result = configure_after_health(tmp_path, {'logged_in': False})
    assert result.returncode != 0
    assert 'not logged in' in result.stderr
    assert news.read_text() == original
