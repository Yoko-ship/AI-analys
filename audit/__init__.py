"""audit — the data and calculation auditor (ТЗ v1.3 §12).

Everything the ТЗ found was found by hand: the frontend's formulas were
rewritten, recomputed against the live API and compared with what the screen
drew, across all 85 securities. That work cannot be done once. Data arrives
every day, statements appear with new periods and the source changes format
without warning, so the check becomes part of the system: a module that repeats
the same work automatically after every load and reports what disagreed.

The auditor's job is NOT to repair data. It is to notice, and to stop a wrong
number reaching the screen. It answers one question — can what is in the
database right now, and what the market screen is showing right now, be trusted.

**The one rule that makes it worth anything: this package may not import the
production calculation layer.** The moment it calls the same function, the check
is meaningless — both sides would be wrong in the same way. ``independent.py``
holds the auditor's own arithmetic, written from the definitions rather than
copied, and ``tests/test_audit.py`` fails the build if any module here imports
``formulas``, ``fundamentals``, ``heatmap`` or ``instruments``.
"""
from audit.rules import ALL_RULES, GROUPS, RULES_BY_CODE, Rule  # noqa: F401
from audit.runner import run_audit  # noqa: F401
from audit.store import (  # noqa: F401
    blocking_index,
    find_findings,
    get_run,
    latest_run,
    list_runs,
    ticker_badge,
    update_finding,
)

__all__ = [
    "ALL_RULES", "GROUPS", "RULES_BY_CODE", "Rule", "run_audit",
    "blocking_index", "find_findings", "get_run", "latest_run", "list_runs",
    "ticker_badge", "update_finding",
]
