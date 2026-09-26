"""Typed declarative rules; no eval, executable uploads or arbitrary expressions."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import re

from . import store as s


def validate(category, config):
    import sector_analysis as engine
    import financial_analysis.sector_calculations as financial_analysis_sector_calculations
    import financial_analysis.sector_inputs as financial_analysis_sector_inputs
    import financial_analysis.sector_templates as financial_analysis_sector_templates
    if not isinstance(config, dict) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{1,99}", str(config.get("code", ""))):
        raise s.ControlError("INVALID_RULE", "A rule needs a stable code of 2–100 characters.", 422)
    fields = {
        "formula": {"code", "numerators", "denominators", "percent", "test_cases"},
        "mapping": {"code", "source_line", "target_line", "test_cases"},
        "template": {"code", "oked_prefix", "template", "test_cases"},
        "signal": {"code", "max_age_days", "test_cases"},
        "parser": {"code", "header_phrase", "duration_months", "test_cases"},
    }
    if category not in fields or set(config) - fields[category]:
        raise s.ControlError("INVALID_RULE_SCHEMA", "Unsupported category or configuration fields.", 422)
    valid = True
    if category == "formula":
        valid = config["code"] in financial_analysis_sector_calculations.METHODS and isinstance(config.get("percent"), bool)
        for field in ("numerators", "denominators"):
            values = config.get(field)
            valid = valid and isinstance(values, list) and 1 <= len(values) <= 20 and all(re.fullmatch(r"form[12]:c\d{3}", str(v)) for v in values)
    elif category == "mapping":
        valid = all(re.fullmatch(r"form[12]:c\d{3}", str(config.get(f, ""))) for f in ("source_line", "target_line")) and config.get("source_line") != config.get("target_line")
    elif category == "template":
        valid = bool(re.fullmatch(r"\d{2,5}", str(config.get("oked_prefix", "")))) and config.get("template") in set(financial_analysis_sector_templates.OKED_MAP.values()) | {"generic_nsbu"}
    elif category == "signal":
        valid = config["code"] == "freshness" and isinstance(config.get("max_age_days"), int) and 1 <= config["max_age_days"] <= 550
    elif category == "parser":
        valid = isinstance(config.get("header_phrase"), str) and 8 <= len(config["header_phrase"]) <= 150 and config.get("duration_months") in {3, 6, 9, 12}
    cases = config.get("test_cases")
    if not valid or not isinstance(cases, list) or not 1 <= len(cases) <= 100 or any(not isinstance(case, dict) for case in cases):
        raise s.ControlError("INVALID_RULE_SCHEMA", "Use valid typed fields and 1–100 regression cases.", 422)


def active(c=None):
    if c is not None:
        return list(s.all_items(c, "rules", {"status": "ACTIVE"}))
    with s.connection() as c:
        return active(c)


def runtime_rules(override=None):
    rules = active()
    if override:
        rules = [r for r in rules if (r["category"], r["config"]["code"]) != (override["category"], override["config"]["code"])] + [override]
    return rules


def apply_snapshot(snapshot, issuer, workbook=None, rules=None):
    import sector_analysis as e
    import financial_analysis.sector_calculations as financial_analysis_sector_calculations
    import financial_analysis.sector_inputs as financial_analysis_sector_inputs
    import financial_analysis.sector_templates as financial_analysis_sector_templates
    snapshot = deepcopy(snapshot)
    rules = runtime_rules() if rules is None else rules
    if not rules:
        return snapshot
    values, previous, opening, lines = financial_analysis_sector_inputs.prepare_inputs(snapshot, workbook)
    methods = deepcopy(financial_analysis_sector_calculations.METHODS)
    formula_versions = {}
    for rule in rules:
        config = rule["config"]
        category = rule["category"]
        if category == "formula":
            methods[config["code"]] = (config["numerators"], config["denominators"], config["percent"])
            formula_versions[config["code"]] = rule["id"]
        elif category == "mapping" and snapshot.get("organization_type") == "non_financial":
            source = lines.get(config["source_line"])
            if source is not None:
                # A conflicting populated target requires investigation, never overwrite.
                target = lines.get(config["target_line"])
                if target and target.get("raw_current") != source.get("raw_current"):
                    snapshot.setdefault("quality", {}).setdefault("data_quality", []).append({"code": "MAPPING_TARGET_CONFLICT", "severity": "blocking"})
                else:
                    lines[config["target_line"]] = {**source, "original_line": config["source_line"], "mapping_rule": rule["id"]}
        elif category == "template" and snapshot.get("organization_type") == "non_financial":
            if str(issuer.get("oked_code") or "").startswith(config["oked_prefix"]):
                snapshot["template_resolution"] = {**snapshot.get("template_resolution", {}), "selected_template": config["template"],
                      "resolution_status": "versioned_oked_rule", "rule_version": rule["id"]}
        elif category == "signal":
            snapshot["max_age_days"] = config["max_age_days"]
    snapshot.update(source_lines=lines, formula_methods=methods, formula_rule_versions=formula_versions, control_rule_versions=[r["id"] for r in rules])
    # The already extracted workbook rows must not overwrite the mapped rows.
    snapshot["control_lines_prepared"] = True
    return snapshot


def apply_parser(document, header, rules=None):
    from .documents import classify
    item = dict(document)
    for rule in runtime_rules() if rules is None else rules:
        if rule["category"] != "parser":
            continue
        config = rule["config"]
        match = re.search(r"\b(20\d{2})\b", header)
        if config["header_phrase"].lower() in header.lower() and match:
            import calendar
            year, months = int(match.group(1)), config["duration_months"]
            item.update(period_start=f"{year}-01-01", period_end=f"{year}-{months:02d}-{calendar.monthrange(year, months)[1]}",
                        duration_months=months, period=f"{year}" + ("H1" if months == 6 else f"Q{months // 3}" if months < 12 else ""),
                        statement_type="annual" if months == 12 else "interim", parser_rule_version=rule["id"])
    return classify(item, header=header, detected=item.get("detected_format"))


def impact_fingerprint(c, rule):
    # Full downstream snapshots are included, not a guessed list from the UI.
    state = [(r["id"], r["version"]) for kind in ("issuers", "documents", "calculations", "analyses") for r in s.all_items(c, kind, {"sort": "id", "direction": "asc"})]
    return s.digest([state, sorted((r["id"], r["version"]) for r in active(c))])


def index_baseline(c):
    """Expose the actual engine method catalog; these records do not override it."""
    import sector_analysis as engine
    import financial_analysis.sector_calculations as financial_analysis_sector_calculations
    import financial_analysis.sector_inputs as financial_analysis_sector_inputs
    import financial_analysis.sector_templates as financial_analysis_sector_templates
    for code, (numerators, denominators, percent) in financial_analysis_sector_calculations.METHODS.items():
        inputs = {key: "100" for key in set(numerators + denominators)}
        expected = str(Decimal(len(numerators)) / Decimal(len(denominators)) * (100 if percent else 1))
        config = {"code": code, "numerators": numerators, "denominators": denominators, "percent": percent,
                  "test_cases": [{"inputs": inputs, "expected": expected}, {"inputs": {}, "expected": None}]}
        s.put(c, "rules", {"id": "baseline_formula_" + code, "title": code, "category": "formula", "status": "BASELINE",
                          "created_by": "domain-engine", "config": config, "engine_version": financial_analysis_sector_templates.CALCULATION_VERSION})


def parser_shadow(rule, ticker):
    """Compare classifications from identical stored bytes, with no source writes."""
    from . import documents
    with s.connection() as c:
        docs = [d for d in s.all_items(c, "documents", {"ticker": ticker}) if d.get("status") != "DUPLICATE"]
    if not docs:
        raise s.ControlError("SOURCE_NOT_AVAILABLE", "No original documents exist for this parser impact target.")
    changes = []
    fields = ("period", "period_end", "duration_months", "statement_type", "detected_format", "blockers")
    current_rules, draft_rules = runtime_rules(), runtime_rules(rule)
    for document in docs:
        first = documents.preview(document)
        header = first.get("text") or "\n".join(" ".join(str(cell["value"] or "") for cell in row) for row in first.get("rows", []))
        current = apply_parser(document, header[:20000], current_rules)
        draft = apply_parser(document, header[:20000], draft_rules)
        if set(draft["blockers"]) - set(current["blockers"]):
            raise s.ControlError("SHADOW_REGRESSION", "The parser draft introduces new classification blockers.")
        changes.append({"document_id": document["id"], "checksum": document["checksum"],
                        "current": {k: current.get(k) for k in fields}, "draft": {k: draft.get(k) for k in fields}})
    return {"verified": True, "verification_scope": "parser_shadow", "ticker": ticker, "documents": changes}


def impact(c, rule):
    rows = {kind: list(s.all_items(c, kind)) for kind in ("issuers", "documents", "facts", "calculations", "analyses", "publications")}
    return {"counts": {k: len(v) for k, v in rows.items()}, "tickers": sorted({r["ticker"] for r in rows["issuers"]}),
            "fingerprint": impact_fingerprint(c, rule), "scope": "conservative_full_catalog", "created_at": s.now()}


def test_rule(rule):
    import sector_analysis as e
    import financial_analysis.sector_calculations as financial_analysis_sector_calculations
    import financial_analysis.sector_inputs as financial_analysis_sector_inputs
    import financial_analysis.sector_templates as financial_analysis_sector_templates
    from sector_regressions import run
    config, category = rule["config"], rule["category"]
    validate(category, config)
    checks = []
    for index, case in enumerate(config["test_cases"]):
        try:
            if category == "formula":
                lines = {k: {"raw_current": v} for k, v in case["inputs"].items()}
                method = {config["code"]: (config["numerators"], config["denominators"], config["percent"])}
                actual = financial_analysis_sector_calculations.enterprise_ratios(lines, "non_financial", "nsbu", "2026Q1", methods=method)[0]["raw_result"]
                expected = case.get("expected")
                passed = actual is None if expected is None else actual is not None and Decimal(str(actual)) == Decimal(str(expected))
            elif category == "parser":
                result = apply_parser(case["document"], case["header"], [rule])
                actual = {k: result.get(k) for k in case["expected"]}
                passed = matches(actual, case["expected"])
            else:
                result = apply_snapshot(case["snapshot"], case.get("issuer", {}), rules=[rule])
                actual = {k: result.get(k) for k in case["expected"]}
                passed = matches(actual, case["expected"])
            checks.append({"case": index + 1, "passed": passed, "actual": actual, "expected": case.get("expected")})
        except (KeyError, ValueError, TypeError, ArithmeticError):
            checks.append({"case": index + 1, "passed": False, "code": "INVALID_TEST_CASE"})
    baseline = run()
    return {"passed": all(c["passed"] for c in checks) and baseline["status"] == "passed", "cases": checks,
            "baseline": baseline, "tested_config_hash": s.digest(config), "created_at": s.now()}


def matches(actual, expected):
    """Allow assertions on meaningful nested fields without dynamic run IDs."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and bool(expected) and all(k in actual and matches(actual[k], value) for k, value in expected.items())
    return actual == expected
