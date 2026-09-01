from __future__ import annotations

import admin_overview
import news_store


class _Cursor:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row=None):
        self.row = row
        self.calls = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return _Cursor(self.row)

    def close(self):
        self.closed = True


def test_usage_record_is_idempotent_and_keeps_exact_tokens(monkeypatch) -> None:
    conn = _Conn()
    monkeypatch.setattr(news_store.rc, "get_catalog_conn", lambda: conn)
    record = {
        "run_id": "run-1",
        "mode": "collect",
        "started_at": "2026-08-29T10:00:00+00:00",
        "finished_at": "2026-08-29T10:05:00+00:00",
        "model": "gpt-5.6-luna",
        "calls": 11,
        "prompt_tokens": 150000,
        "completion_tokens": 8607,
        "cached_input_tokens": 0,
        "total_tokens": 158607,
        "subscription_tokens": 158607,
        "codex_before_pct": 26,
        "codex_after_pct": 27,
        "codex_delta_pct": 1,
        "codex_resets_at": 1788455987,
        "status": "completed",
    }

    assert news_store.record_news_usage(record) == 1
    sql, params = conn.calls[0]
    assert "ON CONFLICT(run_id) DO UPDATE" in sql
    assert 158607 in params
    assert conn.closed is True


def test_admin_news_block_returns_latest_usage(monkeypatch) -> None:
    row = {
        "run_id": "run-1",
        "codex_after_pct": 27.0,
        "codex_delta_pct": 1.0,
        "total_tokens": 158607,
    }
    conn = _Conn(row)
    monkeypatch.setattr(admin_overview, "_scalar", lambda *args, **kwargs: 0)

    block = admin_overview._news_block(conn, admin_overview._utcnow())

    assert block["usage"] == row
    assert "ORDER BY finished_at DESC LIMIT 1" in conn.calls[-1][0]
