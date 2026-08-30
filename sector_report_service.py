"""Adapters for the verified sector contract, shared by both public entrypoints."""
from __future__ import annotations

import logging
import re
import json
from pathlib import Path
from copy import deepcopy
from threading import RLock

import sector_analysis as engine

logger = logging.getLogger(__name__)
_REPORT_CACHE = {}
_CACHE_LOCK = RLock()


def special_type(issuer):
    # Versioned legal-type routing from the supplied v2.2 specification.
    # These rules contain no financial values.
    ticker = issuer.get("ticker", "").upper()
    if ticker == "UZNF":
        return "investment_fund_ifrs_annual"
    if ticker == "URTS":
        return "commodity_exchange"
    for obj in (issuer, issuer.get("index") or {}, issuer.get("security") or {}):
        kind = obj.get("special_legal_type") or obj.get("organization_type")
        if kind in engine.SPECIAL_TYPES:
            return engine.SPECIAL_TYPES[kind]
    return None


def sector_report(issuer, standard, period, scope, lang, *, persist=True, rule_override=None):
    import issuer_analysis_api as api
    if persist:
        import analysis_monitor
        override = analysis_monitor.active_override(issuer["id"], api._now().date().isoformat())
        if override:
            issuer = {**issuer, "template_override": override}
    org = api._organization_type(issuer, standard)
    resolution = engine.resolve_template(issuer, org, api._now().date())
    classifications = json.loads((Path(__file__).parent / "config" / "verified_sector_classifications.json").read_text(encoding="utf-8"))
    verified_activity = next((r for r in classifications["records"] if r["issuer_id"] == str(issuer["id"])), None)
    if verified_activity and resolution["resolution_status"] == "generic_fallback":
        resolution.update(selected_template=verified_activity["template"], resolution_status="verified_activity",
                          evidence_source=verified_activity["evidence_source"], reason_code=verified_activity["reason_code"],
                          rule_version=classifications["version"])
    if org == "commodity_exchange":
        resolution.update(selected_template="commodity_exchange", resolution_status="special_override",
                          evidence_source="https://uzse.uz/isu_infos?locale=ru", reason_code="exchange_legal_type")
    if org == "investment_fund_ifrs_annual":
        standard = "ifrs"
        resolution.update(selected_template=org, resolution_status="special_override",
                          evidence_source="https://openinfo.uz/ru/reports/to_pdf30194/", reason_code="investment_fund_legal_type")
    snapshot = None
    if org == "investment_fund_ifrs_annual":
        from fund_analysis import audited_snapshot
        snapshot = audited_snapshot(issuer, period)
    snapshot = snapshot or api._financial_snapshot(issuer, standard, period, scope)
    if snapshot.get("fund_record") and scope != snapshot.get("scope"):
        snapshot["quality"]["data_quality"].append({
            "code": "SCOPE_NOT_VERIFIED", "severity": "blocking",
            "message": engine.tr(lang, "Аудированный источник не подтверждает запрошенный периметр.",
                                 "Audit manbasi so‘ralgan hisobot doirasini tasdiqlamaydi.",
                                 "The audited source does not verify the requested reporting scope."),
        })
    snapshot["template_resolution"] = resolution
    source = snapshot.get("source") or {}
    if source.get("url"):
        source["document_id"] = "filing:" + engine.digest([issuer["id"], standard, snapshot.get("period"), source["url"]])[:24]
    if org == "commodity_exchange":
        snapshot["organization_type"] = "non_financial"
    workbook = None
    selected = snapshot.get("period")
    reports = api._report_rows(issuer, standard)
    doc = next((r for r in reports if r.get("period") == selected), {})
    if selected and standard == "nsbu" and (doc.get("excel_url") or doc.get("excel_url_form1")):
        year, quarter = api._period_key(selected)
        if "Q" not in selected:
            quarter = 0
        try:
            workbook = api.fetch_report_excel_data(issuer["ticker"], "NSBU", year, quarter)
            if not workbook.get("ok"):
                raise ValueError("source workbook unavailable")
            workbook = deepcopy(workbook)
            for form, url in (("income", doc.get("excel_url")), ("balance", doc.get("excel_url_form1") or doc.get("excel_url"))):
                if workbook.get(form) and url:
                    workbook[form]["source_url"] = url
            snapshot["parser_version"] = "+".join(sorted({
                str((workbook.get(form) or {}).get("parser_version")) for form in ("balance", "income")
                if (workbook.get(form) or {}).get("parser_version")
            })) or workbook.get("parser_version", "catalog")
            source_codes = source_oked_codes(workbook)
            if len(source_codes) == 1:
                source_issuer = {**issuer, "oked_code": next(iter(source_codes))}
                if verified_activity:
                    source_issuer["verified_activity_template"] = verified_activity["template"]
                source_resolution = engine.resolve_template(source_issuer, org, api._now().date())
                if source_resolution["resolution_status"] == "classification_conflict":
                    snapshot["quality"]["data_quality"].append({"code": "CLASSIFICATION_CONFLICT", "severity": "blocking",
                                                               "message": "Source OKED conflicts with the evidenced principal activity."})
                elif resolution["resolution_status"] == "generic_fallback":
                    resolution = source_resolution
                    resolution["evidence_source"] = doc.get("excel_url") or doc.get("excel_url_form1")
                    snapshot["template_resolution"] = resolution
            elif len(source_codes) > 1:
                snapshot["quality"]["data_quality"].append({"code": "CLASSIFICATION_CONFLICT", "severity": "blocking",
                                                           "message": "Source documents contain conflicting OKED codes."})
            if org in {"bank", "microfinance_bank", "microfinance", "insurance"}:
                map_special_lines(snapshot, workbook, org)
        except Exception:
            # Internal exceptions never become public prose.
            snapshot["quality"]["data_quality"].append({
                "code": "SOURCE_MAPPING_FAILED", "severity": "blocking",
                "message": engine.tr(lang, "Не удалось прочитать исходные строки отчёта.", "Hisobotning asl satrlari o‘qilmadi.", "The source statement rows could not be read."),
            })
    from admin_control.rules import apply_snapshot, runtime_rules
    snapshot = apply_snapshot(snapshot, issuer, workbook, runtime_rules(rule_override))
    snapshot["generated_at"] = api._now().isoformat()
    from sector_regressions import run
    regression = run()
    if regression["status"] != "passed":
        snapshot["quality"]["data_quality"].append({"code": "REGRESSION_GATE_FAILED", "severity": "blocking",
                                                   "message": "Calculation release did not pass its regression gate."})
    # Same issuer, filing and rules share the fundamentals across share classes.
    cache_key = engine.digest([issuer["id"], {k: v for k, v in snapshot.items() if k not in {"generated_at", "observations", "source_snapshot_hash", "ticker", "issuer"}}, workbook, lang, api._now().date(), engine.VERSION])
    with _CACHE_LOCK:
        report = deepcopy(_REPORT_CACHE.get(cache_key))
    if report is None:
        report = engine.make_report(snapshot, issuer, lang, api._now().date(), workbook,
                                    api._period_label(selected, lang))
        if snapshot.get("fund_record"):
            from fund_analysis import enrich
            report = enrich(report, snapshot)
        with _CACHE_LOCK:
            if len(_REPORT_CACHE) >= 300:
                _REPORT_CACHE.clear()
            _REPORT_CACHE[cache_key] = deepcopy(report)
    report["financial_snapshot_id"] = report["source_snapshot_hash"]
    report["regression"] = regression
    security = issuer.get("security") or {}
    quote, _ = api._quote_and_trade(issuer)
    from bond_quality import freshness
    market = freshness(quote.get("trade_date"), api._now().date())
    report["market_as_of"] = market["quote_as_of"]
    report["instrument"] = {
        "issuer_id": issuer["id"], "issuer_analysis_id": report["financial_snapshot_id"],
        "security_id": security.get("isin") or issuer.get("isin") or issuer["ticker"],
        "ticker": issuer["ticker"], "isin": issuer.get("isin"),
        "instrument_type": "bond" if security.get("type") == "bond" else "preferred_share" if security.get("is_preferred") or security.get("share_type") == "preferred" else "ordinary_share",
        "verdict": "insufficient_data", "market_as_of": report["market_as_of"],
        "last_price": engine.number(quote.get("close_price")), "freshness": market,
        "dividend_rights": security.get("dividend_rights"), "share_class": security.get("share_type"),
    }
    report["credit_profile"] = {
        "issuer_id": issuer["id"], "financial_snapshot_id": report["financial_snapshot_id"],
        "method": report["sector_template_code"], "financial_as_of": report["financial_as_of"],
        "facts": report["replacement_blocks"]["cash_and_working_capital"],
        "risks": report["risks"], "verdict": report["verdict"]["status"],
        "debt_policy": "Issued bond principal reconciles to, and is never added to, reported liabilities.",
    }
    if snapshot.get("fund_record"):
        from fund_analysis import reconcile_share_basis
        reconcile_share_basis(report, security.get("share_reconciliation"), report["instrument"]["last_price"], api._now().date())
    # Financial version is independent of a quote or share-class event.
    report["instrument_version"] = engine.digest([report["instrument"], report["version"]])
    if persist:
        try:
            import analysis_monitor
            report = analysis_monitor.record_report(report)
        except Exception:
            logger.exception("Could not record sector-analysis run")
    return report


def source_oked_codes(workbook):
    codes = set()
    for form in ("balance", "income"):
        for sheet in (workbook.get(form) or {}).get("sheets") or []:
            for row in sheet.get("table_rows") or []:
                label = str(row.get("label") or "")
                if not re.search(r"ок[эе]д|oked|ifut", label, re.I):
                    continue
                for cell in row.get("source_cells") or row.get("values") or row.get("numeric_values") or []:
                    value = engine.decimal(cell)
                    if value is not None and value == int(value) and 1000 <= value <= 99999:
                        codes.add(f"{int(value):05d}")
    return codes


def bond_issuer_context(reference, lang="ru"):
    """Resolve an exact issuer identity; never infer credit quality from a name fragment."""
    from fastapi import HTTPException
    import issuer_analysis_api as api
    identifier = reference.get("issuer_id") or reference.get("issuer")
    if not identifier:
        return {"issuer_id": None, "issuer_analysis_id": None, "issuer_report": None,
                "issuer_link_status": "not_verified"}
    try:
        issuer = api._resolve_issuer(str(identifier))
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return {"issuer_id": None, "issuer_analysis_id": None, "issuer_report": None,
                "issuer_link_status": "not_verified"}
    try:
        report = sector_report(issuer, "nsbu", None, "separate", lang)
    except Exception:
        logger.exception("Issuer fundamentals are temporarily unavailable for a bond")
        return {"issuer_id": issuer["id"], "issuer_analysis_id": None, "issuer_report": None,
                "issuer_link_status": "source_unavailable"}
    # This embedded report describes the issuer, not its ordinary-share quote.
    report.pop("instrument", None)
    report["market_as_of"] = None
    if report.get("valuation"):
        report["valuation"] = {"price_to_nav": None, "premium_to_nav_pct": None,
                               "blocked_reason": "SHARE_VALUATION_NOT_APPLICABLE_TO_BOND"}
    return {"issuer_id": issuer["id"], "issuer_analysis_id": report["financial_snapshot_id"],
            "financial_as_of": report["financial_as_of"], "issuer_link_status": "verified",
            "issuer_report": report}


SPECIAL_LABELS = {
    "interest_income": (r"^итого процентных доходов$",),
    "interest_expenses": (r"^итого процентных расходов$",),
    "noninterest_income": (r"^итого (?:непроцентных|беспроцентных) доходов$",),
    "noninterest_expenses": (r"^итого (?:непроцентных|беспроцентных) расходов$",),
    "operating_expenses": (r"итого операционных расходов",),
    "loan_portfolio": (r"^(?:кредиты и лизинг|кредиты клиентам|займы клиентам)",),
    "customer_funds": (r"^(?:средства клиентов|депозиты клиентов)",),
    "loan_reserves": (r"^резервы (?:на покрытие|по кредитам|по займам)",),
    "insurance_premiums": (r"^начисленные страховые премии",),
    "insurance_claims": (r"^страховые выплаты",),
    "central_bank_balances": (r"^к получению из цбру$",),
    "total_assets": (r"^итого активов$",),
    "total_liabilities": (r"^итого обязательств$",),
    "total_equity": (r"^итого собственного капитала$",),
    "share_capital": (r"^уставный капитал$",),
    "additional_capital": (r"^добавленный капитал$",),
    "retained_earnings": (r"^нераспределенная прибыль",),
    "net_income": (r"^чистая прибыль \(убытки\)$",),
    "profit_before_tax": (r"^чистая прибыль до уплаты налогов",),
}


def map_special_lines(snapshot, workbook, org):
    # Label-anchored direct lines only. Bank pre-tax profit is not operating profit.
    if org == "insurance":
        return map_insurance_lines(snapshot, workbook)
    snapshot["current_values"].pop("operating_income", None) if org != "insurance" else None
    for form in ("balance", "income"):
        for sheet in (workbook.get(form) or {}).get("sheets") or []:
            for row in engine.statement_rows(sheet, "form1" if form == "balance" else "form2"):
                label = str(row.get("label") or "").lower().replace("ё", "е").replace("| nan", "").strip()
                label = re.sub(r"^(?:\d+|[а-яa-z])\.\s*", "", label).rstrip(".")
                matched = next((key for key, patterns in SPECIAL_LABELS.items() if any(re.search(p, label) for p in patterns)), None)
                if not matched:
                    continue
                nums = row.get("numeric_values") or []
                original = row.get("source_cells")
                if original:
                    code_index = next((i for i, v in enumerate(original) if engine.decimal(v) is not None), None)
                    if code_index is not None:
                        nums = original[code_index:]
                # The bank income form discloses one current cumulative column.
                if form == "income" and original and nums:
                    current, prior = nums[0], None
                elif len(nums) in (2, 3):
                    prior, current = nums[-2:]
                else:
                    continue
                snapshot["current_values"][matched] = engine.number(current)
                target = "opening_values" if form == "balance" else "previous_values"
                if prior is not None:
                    snapshot[target][matched] = engine.number(prior)
                snapshot.setdefault("field_sources", {})[matched] = {
                    "source_line_id": f"{form}:{sheet.get('sheet', sheet.get('name', ''))}:row{row.get('row', '')}",
                    "raw_current": str(current) if engine.decimal(current) is not None else None,
                }


def map_insurance_lines(snapshot, workbook):
    income_map = {"c060": "revenue", "c070": "insurance_service_cost", "c090": "expenses",
                  "c150": "operating_income", "c160": "financial_income", "c200": "fx_income",
                  "c220": "financial_expenses", "c250": "fx_expenses", "c290": "profit_before_tax",
                  "c320": "net_income", "c011": "direct_insurance_premiums",
                  "c013": "accepted_reinsurance_premiums"}
    balance_map = {"c012": "fixed_assets", "c030": "long_term_investments", "c100": "construction_in_progress",
                   "c190": "receivables", "c410": "cash", "c490": "total_assets", "c570": "total_equity",
                   "c580": "gross_insurance_reserves", "c670": "reinsurer_share_in_reserves",
                   "c720": "net_insurance_reserves", "c1190": "other_liabilities"}
    for form, mapping, target in (("income", income_map, "previous_values"), ("balance", balance_map, "opening_values")):
        lines = engine.source_line_pairs(workbook.get(form), "form2" if form == "income" else "form1", set(mapping))
        for code, field in mapping.items():
            if code not in lines:
                continue
            row = lines[code]
            for key, source_key in (("current_values", "raw_current"), (target, "raw_previous")):
                value = engine.decimal(row[source_key])
                if field in {"insurance_service_cost", "expenses", "financial_expenses", "fx_expenses"} and value is not None:
                    value = abs(value)
                snapshot[key][field] = str(value) if value is not None else None
            snapshot.setdefault("field_sources", {})[field] = {"source_line_id": f"insurance:{form}:{code}"}
    for target in ("current_values", "previous_values", "opening_values"):
        values = snapshot[target]
        if target != "previous_values":
            net = engine.difference(values.get("gross_insurance_reserves"), values.get("reinsurer_share_in_reserves"))
            values["net_insurance_reserves"] = engine.number(net)
            values["total_liabilities"] = engine.number(engine.total(net, values.get("other_liabilities")))
        else:
            continue
    for target in ("current_values", "previous_values"):
        values = snapshot[target]
        values["insurance_premiums"] = engine.number(engine.total(values.get("direct_insurance_premiums"), values.get("accepted_reinsurance_premiums")))
    snapshot.setdefault("field_sources", {})["insurance_premiums"] = {"source_line_id": "insurance:income:c011+c013"}
