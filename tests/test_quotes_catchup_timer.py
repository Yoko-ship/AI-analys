"""The quotes catch-up timer: the fallback for a failed scheduled market run.

09.10.2026 both Friday runs (16:10 and 21:30) failed and the board kept
Thursday's session all weekend. A third worker re-runs the same idempotent
--trades-only collector later the same evening and every morning.
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


def test_catchup_reruns_the_trades_collector_after_the_scheduled_runs():
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
    assert calendars == ["*-*-* 04:30:00", "Mon..Sat *-*-* 13:00:00", "Mon..Sat *-*-* 18:30:00"]
    # Stopped before the image is replaced, re-enabled after, and counted as a
    # running collector by the manual refresh.
    assert workflow.count("uzstock-quotes-2130.timer uzstock-quotes-catchup.timer") == 2
    assert workflow.count("uzstock-quotes-2130.service uzstock-quotes-catchup.service uzstock-reports-watch") == 1
    assert "uzstock-quotes-2130.service uzstock-quotes-catchup.service; do" in workflow


def test_single_calendar_timers_are_unchanged():
    _, units = _units()
    timer = units["/etc/systemd/system/uzstock-quotes-2130.timer"]
    assert [line for line in timer.splitlines() if line.startswith("OnCalendar=")] == [
        "OnCalendar=Mon..Sat *-*-* 16:30:00"]
