"""Rubric prerequisites, evaluated again immediately before dispatch."""
import math
import re

from .permissions import timestamp


def check(item, evidence, now, assets=None):
    rows = list(evidence.values())
    fields = {claim["field"] for claim in item["claims"]}
    rubric = item["rubric"]
    if rubric == "quarterly":
        return quarterly(item, rows, fields)
    if rubric == "market":
        complete = [row for row in rows if row["data"].get("session_complete") is True
                    and row["data"].get("trade_date") == item["period"]]
        if not complete or not {"turnover", "trades"} <= fields:
            return ["Final market results require a complete closed session, its date, turnover and trade count"]
        values = complete[0]["data"]
        if any(isinstance(values.get(key), bool) or not isinstance(values.get(key), (int, float))
               or not math.isfinite(values[key]) or values[key] < 0 for key in ("turnover", "trades")):
            return ["Market totals are missing or invalid"]
    elif rubric == "digest":
        from .trends import event_groups
        events = event_groups([row for row in rows if row.get("canonical_event_id")])
        if len(events) < 2:
            return ["A digest needs at least two distinct confirmed events; reprints count once"]
        from . import digest_material
        return digest_material.check(item, evidence, now)
    elif rubric == "dividend":
        if not {"dividend", "dividend_state", "share_class"} <= fields:
            return ["Dividend material requires explicit state, security class and amount bound to the original"]
    elif rubric == "calendar":
        if item.get('digest_items'):
            from . import calendar_events, digest_material
            return calendar_events.check(item, evidence, now) or digest_material.check(item, evidence, now)
        if not rows or any(not row.get("event_at") or timestamp(row["event_at"]) <= now
                           or row["data"].get("event_type") not in {"meeting", "report", "placement", "payment"} for row in rows):
            return ["A calendar needs an announced future date and a defined event type for each original"]
    elif rubric == "chart":
        from . import chart_series
        return chart_series.check(item, evidence, assets or {}, now)
    return []


def original_scope_matches(fact, row):
    pairs = (("period_end", "period"), ("accounting_standard", "standard"),
             ("consolidation_scope", "scope"), ("currency", "currency"))
    return (all(fact.get(left) and str(fact[left]).strip().casefold() == str(row.get(right, "")).strip().casefold()
                for left, right in pairs)
            and all(str(fact.get(key) or "").strip().casefold() == str(row.get(key) or "").strip().casefold()
                    for key in ("period_start", "period_kind")))


def quarterly(item, rows, fields):
    from . import quarter_text
    versions = {row.get("analysis_version") for row in rows} - {None, ""}
    if not versions:
        return ["A published UZStock analysis is required; a browser flag or filing alone is not proof"]
    if not re.fullmatch(r"\d{4}Q[1-4]", item["period"]):
        return ["A defined quarter is required"]
    metrics = set(fields)
    if item.get("calculation") and item["calculation"].get("field"):
        metrics.add(item["calculation"]["field"])
    if not 2 <= len(metrics) <= 3:
        return ["Quarterly material requires two or three checked metrics"]
    try:
        from reporting import store
        for version in versions:
            report = store.get_run(version)
            if not report or report["status"] != "available" or (report.get("text_checks") or {}).get("status") != "passed":
                return ["The referenced UZStock analysis is unavailable"]
            current = store.latest_publication(report["issuer"]["id"], report["language"], report["standard"])
            if not current or current["version"] != version:
                return ["The published UZStock analysis changed; the queued version needs a new check"]
            if report["issuer"]["ticker"] != item["entity"] or report["period"] != item["period"]:
                return ["The UZStock analysis refers to a different issuer or period"]
            from reporting.links import matches
            if not matches(item["destination_url"], report):
                return ["Link directly to the exact published analysis version, period, standard, scope and language"]
            facts = report.get("verified_facts") or []
            for row in (row for row in rows if row.get("analysis_version") == version):
                used = {claim["field"] for claim in item["claims"] if claim["evidence_id"] == row["id"]}
                calculation = item.get("calculation") or {}
                if row["id"] in {calculation.get("left"), calculation.get("right")} and calculation.get("field"):
                    used.add(calculation["field"])
                for field in used:
                    matching = [fact for fact in facts if fact.get("verification_status") == "verified" and fact.get("source_url") == row["url"]
                                and fact["metric_code"] == field and fact.get("raw", fact.get("value")) == row["data"].get(field)
                                and fact.get("unit_raw", fact.get("unit", "")) == row["units"].get(field, "")]
                    if not matching:
                        return ["A quarterly claim disagrees with the published analysis and its original"]
                    if not any(original_scope_matches(fact, row) for fact in matching):
                        return ["A quarterly original's financial scope differs from the published analysis"]
    except Exception:
        return ["The internal UZStock analysis store is unavailable; publication is blocked"]
    return quarter_text.check(item, rows)
