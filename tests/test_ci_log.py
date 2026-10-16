"""Production output reaches the public CI log only redacted (scripts/ci_log.py).

Both directions matter: what identifies a person or opens a door must go, and
what a failure is diagnosed by must stay readable.
"""
from __future__ import annotations

import io
import sys

import pytest

import scripts.ci_log as ci_log


# Secret-shaped values are assembled at run time: written out whole they are
# exactly what the repository's secret scan exists to refuse.
_MIXED = "".join(("Xk4m", "P9qR", "2sT7", "vW1y", "Z3bC", "5dF8"))
_HEX = "".join(("0f9e", "8d7c", "6b5a"))


@pytest.mark.parametrize("line,gone", [
    ('login failed for reader@example.com', "reader@example.com"),
    ('84.54.70.12 - "GET /api/me HTTP/1.1" 401', "84.54.70.12"),
    ("client 2a02:4780:1:2::5 dropped", "2a02:4780:1:2::5"),
    (f"Authorization: Bearer {_MIXED}", _MIXED),
    (f"CLAUDE_GATEWAY_SECRET={_HEX}", _HEX),
    ('{"password": "hunter2-hunter2"}', "hunter2-hunter2"),
    (f"session {_MIXED}", _MIXED),
    (f"GET /?oauth_code={_MIXED} HTTP/1.1", _MIXED),
])
def test_what_identifies_or_opens_is_removed(line, gone) -> None:
    assert gone not in ci_log.redact(line)


@pytest.mark.parametrize("line", [
    "uzstock-web.service: Main process exited, code=exited, status=1/FAILURE",
    'File "/app/server/market/routes.py", line 212, in api_market_board',
    "connect to 10.100.0.201:8000 refused; upstream 127.0.0.1:8001",
    "image sha256:4f9c1e0b2a7d3e5f6a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f",
    "deployed commit 53256cf0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
    "2026-10-16T09:51:31Z INFO psycopg.OperationalError: connection timeout expired",
    "RuntimeError: SOLIQ_API_KEY is not configured",
])
def test_what_diagnoses_a_failure_stays(line) -> None:
    assert ci_log.redact(line) == line


def test_the_full_log_stays_on_the_server_and_only_a_tail_is_shown(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(ci_log, "LOG_DIR", tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO("".join(f"line {i} reader@example.com\n" for i in range(10))))
    assert ci_log.main(["web-start", "3"]) == 0
    shown = capsys.readouterr().out
    assert "reader@example.com" not in shown and "line 9 [email]" in shown and "line 6" not in shown
    saved = list(tmp_path.glob("web-start-*.log"))
    assert len(saved) == 1 and "line 0 reader@example.com" in saved[0].read_text()
    assert saved[0].stat().st_mode & 0o777 == 0o600


def test_old_logs_are_pruned(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ci_log, "LOG_DIR", tmp_path)
    for i in range(ci_log.KEEP + 5):
        (tmp_path / f"web-start-2026010{i:02d}.log").write_text("x")
    ci_log.keep("web-start", "y")
    assert len(list(tmp_path.glob("web-start-*.log"))) == ci_log.KEEP
