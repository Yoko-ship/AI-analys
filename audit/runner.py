"""Running the audit (ТЗ v1.3 §12.7).

One pass over the catalog: every enabled rule against the current data, findings
folded into their existing rows, the report compared with the previous run so a
regression is visible as a regression rather than as one more line.

A rule that throws is a failed rule, not a failed run — the report is what tells
you the pipeline broke, and it cannot be the thing that breaks. §12.9 requires a
full pass inside five minutes; the timing is measured and returned so that
requirement is checkable rather than assumed.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Sequence

from audit import store
from audit.checks import AuditContext, Finding, registry
from audit.independent import threshold
from audit.rules import ALL_RULES, BLOCKING, INFO, RULES_BY_CODE, WARNING

logger = logging.getLogger(__name__)


def _select(codes: Sequence[str] | None, group: str | None) -> dict[str, Any]:
    checks = registry()
    if codes:
        wanted = {c.upper() for c in codes}
        return {k: v for k, v in checks.items() if k in wanted}
    if group:
        prefix = group.upper()
        return {k: v for k, v in checks.items() if k.startswith(f"{prefix}-")}
    return checks


def run_audit(ctx: AuditContext, *, trigger: str = "manual",
              codes: Sequence[str] | None = None, group: str | None = None,
              ticker: str | None = None, trace_id: str | None = None,
              persist: bool = True) -> dict[str, Any]:
    """Execute the selected rules and return the report."""
    started = time.time()
    checks = _select(codes, group)
    run_id = store.start_run(trigger, trace_id) if persist else "dry-run"

    findings: list[Finding] = []
    failed: list[dict[str, str]] = []
    for code, fn in sorted(checks.items()):
        rule = RULES_BY_CODE.get(code)
        if rule is None:
            continue
        try:
            produced = list(fn(ctx) or [])
        except Exception as exc:  # noqa: BLE001 — one broken rule must not hide the rest
            logger.exception("audit rule %s failed", code)
            failed.append({"rule": code, "error": str(exc)})
            continue
        if ticker:
            wanted = ticker.upper()
            produced = [f for f in produced if (f.ticker or "").upper().find(wanted) >= 0]
        findings.extend(produced)

    duration_ms = int((time.time() - started) * 1000)
    counts = {BLOCKING: 0, WARNING: 0, INFO: 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1

    previous = store.latest_run() if persist else None
    if persist:
        counts = store.record(run_id, findings)
        # A full pass owns the whole picture, so anything it did not see again
        # is fixed. A partial pass may not draw that conclusion.
        if not codes and not group and not ticker:
            store.resolve_missing(run_id, {
                store.fingerprint(f.rule_code, f.ticker, f.metric) for f in findings})
        status = "failed" if counts.get(BLOCKING) else ("warning" if counts.get(WARNING) else "ok")
        store.finish_run(run_id, status=status, instruments=len(ctx.board),
                         rules_run=len(checks), counts=counts, duration_ms=duration_ms)
    else:
        status = "failed" if counts.get(BLOCKING) else ("warning" if counts.get(WARNING) else "ok")

    by_group: dict[str, int] = {}
    for finding in findings:
        by_group[finding.rule_code.split("-")[0]] = \
            by_group.get(finding.rule_code.split("-")[0], 0) + 1

    budget = threshold("audit.max_runtime_seconds", 300)
    report = {
        "run_id": run_id,
        "status": status,
        "trigger": trigger,
        "instruments": len(ctx.board),
        "rules_run": len(checks),
        "rules_total": len(ALL_RULES),
        "rules_failed": failed,
        "duration_ms": duration_ms,
        "within_budget": duration_ms <= budget * 1000,
        "summary": {"blocking": counts.get(BLOCKING, 0), "warnings": counts.get(WARNING, 0),
                    "infos": counts.get(INFO, 0)},
        "by_group": by_group,
        "findings": [
            {"rule_code": f.rule_code, "severity": f.severity, "ticker": f.ticker,
             "metric": f.metric, "expected": f.expected, "actual": f.actual,
             "deviation": f.deviation, "message": f.message, "input": f.input}
            for f in findings
        ],
    }

    # §12.9: the report must say what changed against the previous run, or a
    # regression reads as one more line in a list nobody finishes.
    if previous:
        report["previous_run"] = {
            "run_id": previous.get("id"),
            "blocking": previous.get("blocking"),
            "warnings": previous.get("warnings"),
        }
        report["regressions"] = max(0, counts.get(BLOCKING, 0) - (previous.get("blocking") or 0))
        report["fixed_since_previous"] = max(
            0, (previous.get("blocking") or 0) - counts.get(BLOCKING, 0))
    return report
