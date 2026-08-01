"""rollout.py — running the new calculation beside the old one (ТЗ §11.6).

The rollout procedure the ТЗ prescribes is the same for every flag: the new
implementation runs in PARALLEL with the old and only writes a fingerprint of
its values to a log. Then the two are compared across every security on the
stand and each difference is explained line by line — "every change must have a
cause named in this task". Only then is the flag turned on for internal users;
only after two consecutive days of an empty invariant report is it opened to
everyone; and the rollback is switching the flag off, not reverting a release.

This module is the comparison half of that. It does not decide anything: it
records what both sides produced, groups the differences by cause, and answers
the one question a reviewer actually has — *is every difference here one we
intended?*
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Iterable, Sequence

logger = logging.getLogger(__name__)


def fingerprint(value: Any) -> str:
    """A stable digest of a metric value, insensitive to float noise.

    Values are rounded before hashing: a difference in the twelfth decimal is
    not a change anybody meant, and a comparison that reports it drowns the ones
    that matter.
    """
    def norm(v: Any) -> Any:
        if isinstance(v, float):
            return round(v, 6)
        if isinstance(v, dict):
            return {k: norm(v[k]) for k in sorted(v)}
        if isinstance(v, (list, tuple)):
            return [norm(x) for x in v]
        return v

    payload = json.dumps(norm(value), sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def compare(subjects: Iterable[str],
            old: Callable[[str], Any],
            new: Callable[[str], Any],
            *, explain: Callable[[str, Any, Any], str | None] | None = None
            ) -> dict[str, Any]:
    """Run both implementations over the same subjects and diff the results.

    ``explain`` maps a difference to the reason it was expected — the cause named
    in the specification. A difference with no explanation is the finding: it
    means the new code changed something nobody asked it to.
    """
    same: list[str] = []
    differences: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for subject in subjects:
        try:
            before, after = old(subject), new(subject)
        except Exception as exc:  # noqa: BLE001 — one bad subject is data, not a crash
            failures.append({"subject": subject, "error": str(exc)})
            continue
        if fingerprint(before) == fingerprint(after):
            same.append(subject)
            continue
        reason = explain(subject, before, after) if explain else None
        differences.append({
            "subject": subject, "before": before, "after": after,
            "reason": reason, "explained": bool(reason),
        })

    unexplained = [d for d in differences if not d["explained"]]
    return {
        "subjects": len(same) + len(differences) + len(failures),
        "identical": len(same),
        "differences": differences,
        "unexplained": unexplained,
        "failures": failures,
        # The gate. ТЗ §11.6: "каждое изменение должно иметь причину из этого
        # задания" — an unexplained difference blocks the flag.
        "ready_to_enable": not unexplained and not failures,
    }


def summarise(report: dict[str, Any]) -> str:
    """One line for the deployment log."""
    return (f"{report['identical']}/{report['subjects']} identical, "
            f"{len(report['differences'])} differ "
            f"({len(report['unexplained'])} unexplained), "
            f"{len(report['failures'])} failed — "
            f"{'READY' if report['ready_to_enable'] else 'BLOCKED'}")
