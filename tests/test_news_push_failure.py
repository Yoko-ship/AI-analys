"""A collection that never reaches prod is a failed run, and must look like one.

On 2026-08-01 the PostgreSQL cutover left the news table's identity sequence at 1
while its ids ran to 630, so every push was rejected with a duplicate key. The
collector kept classifying (and paying for) items, printed a summary with
``"pushed": 0``, and exited 0 — six green cron cards over a feed that had not moved
in five days. The push is the point of the run; if it fails, the run failed.
"""
from __future__ import annotations

import pytest

import news_collector as nc


@pytest.fixture()
def cron_run(monkeypatch):
    """main() as the scheduler calls it, with the collection itself stubbed out."""
    import codex_usage

    monkeypatch.setattr(nc.sys, "argv", ["news_collector.py"])
    monkeypatch.setattr(nc, "preflight", lambda *a, **k: None)
    monkeypatch.setattr(codex_usage, "read_codex_rate_limit", lambda: None)
    monkeypatch.setattr(nc.news_store, "record_news_usage", lambda record: 1)
    monkeypatch.setattr(nc, "push_news_usage", lambda record: True)
    return monkeypatch


class TestTheExitCode:
    def test_a_rejected_push_fails_the_run(self, cron_run):
        cron_run.setattr(nc, "run", lambda **k: {"fetched": 10, "pushed": 0,
                                                 "push_failed": True})
        with pytest.raises(SystemExit) as exc:
            nc.main()
        assert exc.value.code == 1

    def test_a_successful_push_exits_zero(self, cron_run):
        cron_run.setattr(nc, "run", lambda **k: {"fetched": 10, "pushed": 10,
                                                 "push_failed": False})
        nc.main()  # no SystemExit

    def test_an_empty_but_healthy_run_is_not_a_failure(self, cron_run):
        """A quiet day has nothing to push. Silence is not the same as rejection."""
        cron_run.setattr(nc, "run", lambda **k: {"fetched": 0, "pushed": 0,
                                                 "push_failed": False})
        nc.main()


class TestTheReportedFlag:
    def test_run_reports_the_push_verdict(self, monkeypatch):
        """The flag main() acts on has to come from the push, not from the count:
        a run with nothing to send also pushes 0."""
        import inspect
        source = inspect.getsource(nc.run)
        assert "push_failed = code != 0" in source
