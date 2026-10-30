"""Persist the private Codex gateway settings without replacing other worker settings."""
from __future__ import annotations

import os
import argparse
import json
from pathlib import Path
import secrets
import sys


def _read(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if "=" in line and not line.lstrip().startswith("#"))


def _write(path: Path, values: dict[str, str]) -> None:
    previous = os.umask(0o077)
    try:
        temporary = path.with_suffix(".tmp")
        temporary.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        os.umask(previous)


def configure(directory: Path, *, health: dict | None = None) -> None:
    gateway_path = directory / "codex-gateway.env"
    news_path = directory / "news-collector.env"
    news = _read(news_path)
    logged_in = isinstance(health, dict) and health.get('logged_in') is True
    if health is not None and news.get('NEWS_AI_PROVIDER', 'claude').strip().lower() == 'codex' and not logged_in:
        raise ValueError('Selected Codex gateway is not logged in; collector settings were preserved')
    gateway = _read(gateway_path)
    secret = gateway.get("CODEX_GATEWAY_SECRET") or secrets.token_hex(32)
    gateway.update(CODEX_GATEWAY_SECRET=secret, CODEX_HOME="/app/codex-home")
    gateway.setdefault('CODEX_GATEWAY_CONCURRENCY', '1')
    news['CODEX_GATEWAY_SECRET'] = secret
    if logged_in:
        news.setdefault('NEWS_AI_PROVIDER', 'codex')
    # Without an explicit selection the collector defaults to its existing Claude provider.
    news.setdefault('NEWS_CLAUDE_GATEWAY_URL', 'http://uzstock-claude-gateway:8080')
    news.setdefault('NEWS_CODEX_GATEWAY_URL', 'http://uzstock-codex-gateway:8080')
    news.setdefault('NEWS_PUSH_URL', 'http://uzstock-web:8000')
    news.setdefault("NEWS_CODEX_MODEL", "gpt-6-luna")
    news.setdefault("NEWS_CODEX_FALLBACK_MODEL", "gpt-6.1-terra")
    news.setdefault("NEWS_CODEX_REASONING", "low")
    news.setdefault("NEWS_CODEX_TIMEOUT", "180")
    _write(gateway_path, gateway)
    _write(news_path, news)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--health-stdin', action='store_true', help='Apply the gateway login check from stdin')
    args = parser.parse_args()
    try:
        health = json.load(sys.stdin) if args.health_stdin else None
        if args.health_stdin and not isinstance(health, dict):
            raise ValueError('Gateway health must be a JSON object')
        configure(args.directory, health=health)
    except ValueError as exc:
        parser.exit(1, f'{exc}\n')
