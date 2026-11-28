"""Select a published analysis, retaining its original filing dates separately."""
import json
import re
from datetime import timedelta

from . import sources
from .errors import MarketingError
from .permissions import timestamp


def published(version, now):
    try:
        return _published(version, now)
    except Exception as exc:
        raise MarketingError("EDITORIAL_ANALYSIS_UNAVAILABLE", "The published analysis store is unavailable; selection is blocked.") from exc


def _published(version, now):
    from reporting import store
    report = store.get_run(version)
    if (not report or report.get("status") != "available" or report.get("source_refresh_failed")
            or (report.get("text_checks") or {}).get("status") != "passed"
            or not re.fullmatch(r"\d{4}Q[1-4]", report.get("period", ""))
            or timestamp(report["generated_at"]) > now):
        return None
    current = store.latest_publication(report["issuer"]["id"], report["language"], report["standard"])
    return report if current and current["version"] == version else None


def first_available(report):
    try:
        return _first_available(report)
    except Exception as exc:
        raise MarketingError("EDITORIAL_ANALYSIS_UNAVAILABLE", "The published analysis store is unavailable; selection is blocked.") from exc


def _first_available(report):
    from reporting import store
    # Regenerating commentary on an old quarter must not create fresh news.
    with store.connect() as c:
        rows = c.execute("SELECT payload FROM sector_runs WHERE issuer_id=? AND language=? AND standard=? AND period=? AND status='available'",
                         (str(report["issuer"]["id"]), report["language"], report["standard"], report["period"])).fetchall()
    dates = [timestamp(report["generated_at"])]
    for row in rows:
        saved = json.loads(row["payload"])
        if not saved.get("source_refresh_failed") and (saved.get("text_checks") or {}).get("status") == "passed":
            dates.append(timestamp(saved["generated_at"]))
    return min(dates)


def original_matches(row, report):
    from .rubric_checks import original_scope_matches
    fields = set(row["data"]) - {"analysis_ready"}
    facts = report.get("verified_facts") or []
    return bool(fields) and all(any(fact.get("verification_status") == "verified" and fact.get("source_url") == row["url"]
        and fact.get("metric_code") == field and fact.get("raw", fact.get("value")) == row["data"][field]
        and fact.get("unit_raw", fact.get("unit", "")) == row["units"].get(field, "")
        and original_scope_matches(fact, row) for fact in facts) for field in fields)


def select(c, rule, now, groups):
    from reporting.links import url
    result = []
    for group in groups:
        selected = [sources.current_evidence(c, item["id"]) for item in group if item["source_id"] in rule["source_ids"]]
        selected = [row for row in selected if row and row["status"] == "verified" and timestamp(row["expires_at"]) > now]
        for version in sorted({row.get("analysis_version") for row in selected} - {None, ""}):
            report = published(version, now)
            if not report or report["language"] != rule["target"]["primary_language"]:
                continue
            at = first_available(report)
            if not timedelta(0) <= now - at < timedelta(hours=rule["max_age_hours"]):
                continue
            event_id = f"analysis:{report['issuer']['ticker']}:{report['standard']}:{report['period']}"
            originals = [row for row in selected if row.get("analysis_version") == version
                         and row["canonical_event_id"] == event_id and row["entity"] == report["issuer"]["ticker"]
                         and original_matches(row, report)]
            metrics = {field for row in originals for field in row["data"]} - {"analysis_ready"}
            if not originals or len(originals) > 30 or len(metrics) < 2:
                continue
            result.append({"id": event_id, "at": at, "aliases": ["event:" + event_id], "originals": originals,
                           "period": report["period"], "destination_url": url(report), "analysis_version": version,
                           "inventory_versions": {row["id"]: row["version"] for row in group}})
    return sorted(result, key=lambda event: (event["at"], event["id"]))


def guard(task, now):
    version = (task.get("editorial") or {}).get("analysis_version")
    if version and not published(version, now):
        raise MarketingError("EDITORIAL_ANALYSIS_CHANGED", "The selected published analysis changed or became unavailable; this assignment is stopped.")
