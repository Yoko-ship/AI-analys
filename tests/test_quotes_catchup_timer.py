"""One quotes timer preserves closing collections and recovery windows.

09.10.2026 both Friday runs (16:10 and 21:30) failed and the board kept
Thursday's session all weekend. The single idempotent --trades-only worker
keeps both closing runs, evening recovery and the daily morning check.
"""
import ast
import textwrap
from pathlib import Path


def _units():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    start = workflow.index("          def worker(")
    end = workflow.index("          for name, content in units.items():", start)
    source = textwrap.dedent(workflow[start:end])
    ast.parse(source)
    namespace = {}
    exec(compile(source, "VPS workers", "exec"), namespace)
    return workflow, namespace["units"]


def test_one_quotes_worker_keeps_close_final_and_recovery_schedules():
    workflow, units = _units()
    service = units["/etc/systemd/system/uzstock-quotes-catchup.service"]
    assert "python collector_financials.py --trades-only" in service
    # It shares the openinfo pause and request count with every other reader.
    assert "-v uzstock_data:/app/data" in service
    timer = units["/etc/systemd/system/uzstock-quotes-catchup.timer"]
    calendars = [line.split("=", 1)[1] for line in timer.splitlines() if line.startswith("OnCalendar=")]
    # 09:30 every day (Sunday too, so a lost Friday does not wait for Monday),
    # then 18:00 and 23:30 Tashkent — each past the 60-minute openinfo pause
    # after the 16:10 and 21:30 runs it backs up.
    assert calendars == ["*-*-* 04:30:00", "Mon..Sat *-*-* 11:10:00", "Mon..Sat *-*-* 13:00:00",
                         "Mon..Sat *-*-* 16:30:00", "Mon..Sat *-*-* 18:30:00"]
    # Stopped before the image is replaced, re-enabled after, and counted as a
    # running collector by the manual refresh.
    assert "systemctl start uzstock-quotes-catchup.service" in workflow
    for old in ("quotes-1610", "quotes-2130"):
        assert f"/etc/systemd/system/uzstock-{old}.service" not in units
        assert f"/etc/systemd/system/uzstock-{old}.timer" not in units
    assert "for retired in uzstock-intraday uzstock-quotes-1300 uzstock-quotes-1610 uzstock-quotes-2130; do" in workflow


def test_intraday_bars_remain_an_independent_small_collection():
    _, units = _units()
    timer = units["/etc/systemd/system/uzstock-hourly-bars.timer"]
    assert [line for line in timer.splitlines() if line.startswith("OnCalendar=")] == [
        "OnCalendar=Mon..Sat *-*-* 06..11:05:00"]
    assert "--intraday-only" in units["/etc/systemd/system/uzstock-hourly-bars.service"]


def test_every_server_worker_has_uzse_pinned_off():
    # uzse.uz blocked the host after ~30 crawls a day; a server .env must not
    # be able to switch a collector back onto it (docker's -e beats --env-file).
    _, units = _units()
    for name, unit in units.items():
        if "docker run" in unit and "--env-file /root/uzstock/app/.env" in unit:
            assert "--env-file /root/uzstock/app/.env -e UZSE_ENABLED=0" in unit, name
