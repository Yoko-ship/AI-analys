"""Explain recorded failures without guessing from a process exit code.

Legacy adapters read the collectors' exact result formats. Ordinary log prose
and previous recoverable warnings never count as proof of a successful write.
"""
import ast
import json
import re

CBU_DATASETS = {"npl", "main", "structure", "capital", "liquidity", "profitability", "industry",
                "rates", "fsi", "inflation", "SDMX catalogue", "fx"}


def cbu_events(result):
    period = result.get("month", "")
    if not re.fullmatch(r"\d{4}-\d{2}", str(period)):
        return []
    events = []
    for kind in result.get("loaded", []):
        if isinstance(kind, str):
            events.append({"stage": f"cbu/{kind}/{period}", "ok": True,
                           "phase": "publication", "counts": {"datasets": 1}})
    for error in result.get("errors", []):
        if isinstance(error, str):
            kind, sep, reason = error.partition(": ")
            scoped = sep and kind in CBU_DATASETS
            events.append({"stage": f"cbu/{kind if scoped else 'source'}/{period}",
                           "ok": False, "phase": "collection", "reason": reason if scoped else error})
    return events


def recorded_events(value):
    if value.get("receipts"):
        return value["receipts"]
    events = []
    for line in str(value.get("evidence") or "").splitlines():
        if value.get("job") == "terminal-cbu" and line.startswith('{"month":'):
            try:
                result = json.loads(line)
                if isinstance(result.get("loaded"), list) and isinstance(result.get("errors"), list):
                    events.extend(cbu_events(result))
            except (ValueError, TypeError):
                pass
        # Historical delivery logs predate structured receipts. Ignore facts:
        # they may only record heartbeat/rotation metadata, not collected data.
        match = re.search(r"\bINFO push (/api/admin/[\w-]+) ok: (\{.*\})$", line)
        if match and match[1] != "/api/admin/facts":
            try:
                result = ast.literal_eval(match[2])
                if isinstance(result, dict) and result.get("ok") is True:
                    counts = {k: v for k, v in result.items() if type(v) is int and v >= 0}
                    events.append({"stage": match[1], "ok": True, "phase": "publication", "counts": counts})
            except (ValueError, SyntaxError):
                pass
    return events


def _cause(reason, phase):
    if "no published table" in reason:
        return "table_missing"
    if "workbook header states" in reason and "catalogued as" in reason:
        return "period_mismatch"
    if "Incomplete parse would erase existing fields" in reason:
        return "incomplete_values"
    if "No Excel document is linked" in reason:
        return "document_missing"
    if "Empty source filing" in reason:
        return "empty_filing"
    if re.search(r"FormatChanged|Invalid (?:SDMX|table|financial)|source_problem", reason):
        return "format_changed"
    if re.search(r"ModuleNotFoundError|ImportError|missing required packages", reason, re.I):
        return "missing_dependency"
    if re.search(r"No space left on device|database is locked|disk is full", reason, re.I):
        return "storage_error"
    if re.search(r"(?:SECRET|TOKEN|credential).*(?:not configured|not set|missing)", reason, re.I):
        return "credentials_missing"
    if phase == "publication":
        return "publication_unavailable"
    if re.search(r"\b429\b|TooManyRequests|rate limit", reason, re.I):
        return "rate_limited"
    if re.search(r"\b(?:401|403)\b|Forbidden|Unauthorized", reason):
        return "access_denied"
    if re.search(r"Timeout|timed out", reason, re.I):
        return "source_timeout"
    if re.search(r"ConnectionError|connection refused|NameResolutionError|HTTP 5\d\d|5\d\d Server Error", reason, re.I):
        return "source_unavailable"
    return "unknown"


def _issue(reason, phase="collection", **context):
    issue = {"code": _cause(reason, phase), **context}
    if issue["code"] == "period_mismatch":
        match = re.search(r"workbook header states (\d{4}-\d{2}-\d{2})", reason)
        if match:
            issue["actual_date"] = match[1]
    if issue["code"] == "incomplete_values":
        match = re.search(r"erase existing fields: ([a-z_, ]+)", reason)
        if match:
            issue["fields"] = [v.strip() for v in match[1].split(",")]
    return issue


def explain(value, events, status):
    issues = []
    for event in events:
        if event.get("ok") is not False:
            continue
        context = {}
        stage = event.get("stage", "")
        if stage.startswith("cbu/"):
            _, kind, period = stage.split("/", 2)
            context = {"period": period, "datasets": [kind]}
        issues.append(_issue(event.get("reason", ""), event.get("phase", "publication"), **context))
    if status in ("failed", "partial"):
        for line in str(value.get("evidence") or "").splitlines():
            match = re.search(r"\bWARNING (?:NSBU (\w+) (\d{4}) Q([0-4])|(?:quarterly |financials )?backfill: (\w+) (\d{4}(?:Q[1-4])?)): (.*)", line)
            if match:
                ticker = match[1] or match[4]
                period = (match[2] + ("Q" + match[3] if match[3] != "0" else "")) if match[1] else match[5]
                issues.append(_issue(match[6], ticker=ticker, period=period))
            elif re.match(r"^(?:\w+\.)*(?:\w*Error|\w*Timeout|FormatChanged): ", line):
                issues.append(_issue(line))
        system_code = {"timeout": "time_limit", "oom-kill": "memory_limit", "signal": "interrupted"}.get(value.get("result"))
        if system_code:
            issues.insert(0, {"code": system_code})
        if not issues:
            issues.append({"code": "unknown"})
    grouped = {}
    for issue in issues:
        datasets = issue.pop("datasets", None)
        key = json.dumps(issue, sort_keys=True)
        if key not in grouped:
            grouped[key] = {**issue, **({"datasets": []} if datasets else {})}
        if datasets:
            grouped[key]["datasets"] = list(dict.fromkeys(grouped[key]["datasets"] + datasets))
    return {"issues": list(grouped.values()), "evidence_limited": bool(value.get("evidence_truncated")),
            "saved_datasets": sum(e.get("counts", {}).get("datasets", 0) for e in events if e.get("ok"))}
