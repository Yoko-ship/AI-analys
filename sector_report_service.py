"""Adapters for the verified sector contract, shared by both public entrypoints."""
from __future__ import annotations

import logging
import re
import json
from pathlib import Path
from copy import deepcopy
from threading import RLock

import sector_analysis as engine
import financial_analysis.sector_calculations as financial_analysis_sector_calculations
import financial_analysis.sector_inputs as financial_analysis_sector_inputs
import financial_analysis.sector_language as financial_analysis_sector_language
import financial_analysis.sector_numbers as financial_analysis_sector_numbers
import financial_analysis.sector_templates as financial_analysis_sector_templates
import financial_analysis.sector_inputs as financial_analysis_sector_inputs
import financial_analysis.sector_language as financial_analysis_sector_language
import financial_analysis.sector_numbers as financial_analysis_sector_numbers
import financial_analysis.sector_report as financial_analysis_sector_report
import financial_analysis.sector_templates as financial_analysis_sector_templates
import issuer_financials as financials

logger = logging.getLogger(__name__)
_REPORT_CACHE = {}
_CACHE_LOCK = RLock()

_FLOW_FIELDS = frozenset(financial_analysis_sector_inputs.FORM2.values())


def _scale_gap(left, right):
    """Return the absolute multiplicative gap, ignoring unusable values."""
    left, right = financial_analysis_sector_numbers.decimal(left), financial_analysis_sector_numbers.decimal(right)
    if left is None or right is None or left == 0 or right == 0:
        return None
    ratio = abs(left / right)
    return max(ratio, 1 / ratio)


def _has_comparative_unit_conflict(snapshot, workbook):
    """Detect a corrected current form that conflicts with its PDF comparison.

    A reviewed correction can normalize a Form №2 value, but it must not make
    the comparative column in the original filing look trustworthy. Flag the
    case only when both conditions are present: the corrected current value
    differs from the source by a clear unit scale, and the source comparative
    value disagrees materially with the verified comparable filing. This is
    deliberately data-driven; it is not tied to any issuer or ticker.
    """
    reviewed = set(snapshot.get("reviewed_correction_fields") or ()) & _FLOW_FIELDS
    if not reviewed or not isinstance(workbook, dict):
        return False
    source_lines = financial_analysis_sector_inputs.source_line_pairs(workbook.get("income") or {}, "form2")
    values = snapshot.get("current_values") or {}
    previous = snapshot.get("previous_values") or {}
    has_unit_scale = False
    has_comparative_conflict = False
    for code, field in financial_analysis_sector_inputs.FORM2.items():
        if field not in reviewed:
            continue
        line = source_lines.get(code) or {}
        current_gap = _scale_gap(line.get("raw_current"), values.get(field))
        if current_gap is not None and current_gap >= 100:
            has_unit_scale = True
        previous_gap = _scale_gap(line.get("raw_previous"), previous.get(field))
        raw_previous = financial_analysis_sector_numbers.decimal(line.get("raw_previous"))
        verified_previous = financial_analysis_sector_numbers.decimal(previous.get(field))
        if (previous_gap is not None and previous_gap >= 10) or (
            raw_previous is not None and verified_previous is not None
            and raw_previous * verified_previous < 0
        ):
            has_comparative_conflict = True
    return has_unit_scale and has_comparative_conflict


def _verified_catalog_fallback(snapshot):
    """Whether normalized catalog facts can safely outlive workbook enrichment.

    Workbook rows add line-level detail, but the public catalog snapshot is an
    independent verified source. A transient workbook failure must not erase a
    report when all core facts are traceable and its balance still reconciles.
    """
    quality = snapshot.get("quality") or {}
    values = snapshot.get("current_values") or {}
    core = ("revenue", "net_income", "total_assets", "total_equity", "total_liabilities")
    source = snapshot.get("source") or {}
    return (
        quality.get("traceable") is True
        and quality.get("verification_status") == "verified"
        and bool(source.get("url"))
        and all(financial_analysis_sector_numbers.decimal(values.get(key)) is not None for key in core)
        and financial_analysis_sector_calculations.balance_gate(values, snapshot.get("rounding_unit", 1)).get("status") == "passed"
    )


def public_report(report):
    """Return the public contract without internal-only liquidity ratios.

    Current and quick liquidity remain available to the calculation trace and
    administrator controls, but the v1.3 public set deliberately excludes
    them.  Copying here keeps monitoring and rollback records complete while
    preventing the website and public APIs from leaking the internal fields.
    """
    result = deepcopy(report)
    result["ratios"] = deepcopy(result.get("public_ratios") or [])
    result.pop("public_ratios", None)
    credit = result.get("credit_profile")
    if isinstance(credit, dict):
        credit["public_ratio_policy"] = "current_and_quick_liquidity_excluded"
    return result


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
        if kind in financial_analysis_sector_templates.SPECIAL_TYPES:
            return financial_analysis_sector_templates.SPECIAL_TYPES[kind]
    return None


def sector_report(issuer, standard, period, scope, lang, *, persist=True, rule_override=None):
    if persist:
        from reporting import store as report_store
        override = report_store.active_override(issuer["id"], financials.now().date().isoformat())
        if override:
            issuer = {**issuer, "template_override": override}
    org = financials.classify_organization(issuer, standard)
    resolution = financial_analysis_sector_templates.resolve_template(issuer, org, financials.now().date())
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
    snapshot = snapshot or financials.financial_snapshot(issuer, standard, period, scope)
    if snapshot.get("fund_record") and scope != snapshot.get("scope"):
        snapshot["quality"]["data_quality"].append({
            "code": "SCOPE_NOT_VERIFIED", "severity": "blocking",
            "message": financial_analysis_sector_language.tr(lang, "Аудированный источник не подтверждает запрошенный периметр.",
                                 "Audit manbasi so‘ralgan hisobot doirasini tasdiqlamaydi.",
                                 "The audited source does not verify the requested reporting scope."),
        })
    snapshot["template_resolution"] = resolution
    source = snapshot.get("source") or {}
    if source.get("url"):
        source["document_id"] = "filing:" + financial_analysis_sector_numbers.digest([issuer["id"], standard, snapshot.get("period"), source["url"]])[:24]
    if org == "commodity_exchange":
        snapshot["organization_type"] = "non_financial"
    workbook = None
    selected = snapshot.get("period")
    reports = financials.report_rows(issuer, standard)
    doc = next((r for r in reports if r.get("period") == selected), {})
    if selected and standard == "nsbu" and (doc.get("excel_url") or doc.get("excel_url_form1")):
        year, quarter = financials.period_key(selected)
        if "Q" not in selected:
            quarter = 0
        try:
            workbook = financials.fetch_report_excel_data(issuer["ticker"], "NSBU", year, quarter)
            if not workbook.get("ok"):
                raise ValueError("source workbook unavailable")
            workbook = deepcopy(workbook)
            for form, url in (("income", doc.get("excel_url")), ("balance", doc.get("excel_url_form1") or doc.get("excel_url"))):
                if isinstance(workbook.get(form), dict) and url:
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
                source_resolution = financial_analysis_sector_templates.resolve_template(source_issuer, org, financials.now().date())
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
        except Exception as exc:
            logger.warning("Workbook enrichment failed for %s %s", issuer.get("ticker"), selected,
                           exc_info=True)
            # Internal exceptions never become public prose. Keep a verified,
            # reconciled catalog snapshot publishable and disclose only that
            # its optional line-level enrichment is unavailable. If those
            # independent facts are not sufficient, retain the hard gate.
            if _verified_catalog_fallback(snapshot):
                snapshot["quality"]["data_quality"].append({
                    "code": "SOURCE_ENRICHMENT_UNAVAILABLE", "severity": "warning",
                    "message": financial_analysis_sector_language.tr(
                        lang,
                        "Детализация строк источника временно недоступна; анализ построен по проверенным показателям каталога.",
                        "Manba satrlari tafsiloti vaqtincha mavjud emas; tahlil katalogdagi tekshirilgan ko‘rsatkichlarga asoslangan.",
                        "Source-line detail is temporarily unavailable; the analysis uses verified catalog metrics.",
                    ),
                })
            else:
                snapshot["quality"]["data_quality"].append({
                    "code": "SOURCE_MAPPING_FAILED", "severity": "blocking",
                    "message": financial_analysis_sector_language.tr(lang, "Данные найдены, но их пока не удалось подготовить для анализа.", "Ma’lumotlar topildi, ammo hozircha tahlil uchun tayyorlanmadi.", "The data was found but is not ready for analysis yet."),
                })
    if _has_comparative_unit_conflict(snapshot, workbook):
        snapshot["quality"]["data_quality"].append({
            "code": "COMPARATIVE_VALUES_UNIT_MISMATCH",
            "severity": "blocking",
            "message": financial_analysis_sector_language.tr(
                lang,
                "Данные требуют подтверждения: расхождение сравнительных значений и единиц измерения",
                "Ma’lumotlar tasdiqlanishi kerak: taqqoslama qiymatlar va o‘lchov birliklari mos emas",
                "Data requires confirmation: comparative values and units of measure conflict",
            ),
        })
    from admin_control.rules import apply_snapshot, runtime_rules
    snapshot = apply_snapshot(snapshot, issuer, workbook, runtime_rules(rule_override))
    snapshot["generated_at"] = financials.now().isoformat()
    from sector_regressions import run
    regression = run()
    if regression["status"] != "passed":
        snapshot["quality"]["data_quality"].append({"code": "REGRESSION_GATE_FAILED", "severity": "blocking",
                                                   "message": "Calculation release did not pass its regression gate."})
    # Same issuer, filing and rules share the fundamentals across share classes.
    cache_key = financial_analysis_sector_numbers.digest([issuer["id"], {k: v for k, v in snapshot.items() if k not in {"generated_at", "observations", "source_snapshot_hash", "ticker", "issuer"}}, workbook, lang, financials.now().date(), financial_analysis_sector_templates.VERSION])
    with _CACHE_LOCK:
        report = deepcopy(_REPORT_CACHE.get(cache_key))
    if report is None:
        report = financial_analysis_sector_report.make_report(snapshot, issuer, lang, financials.now().date(), workbook,
                                    financials.period_label(selected, lang))
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
    quote, _ = financials.quote_and_trade(issuer)
    from bond_quality import freshness
    market = freshness(quote.get("trade_date"), financials.now().date())
    report["market_as_of"] = market["quote_as_of"]
    report["instrument"] = {
        "issuer_id": issuer["id"], "issuer_analysis_id": report["financial_snapshot_id"],
        "security_id": security.get("isin") or issuer.get("isin") or issuer["ticker"],
        "ticker": issuer["ticker"], "isin": issuer.get("isin"),
        "instrument_type": "bond" if security.get("type") == "bond" else "preferred_share" if security.get("is_preferred") or security.get("share_type") == "preferred" else "ordinary_share",
        "verdict": "insufficient_data", "market_as_of": report["market_as_of"],
        "last_price": financial_analysis_sector_numbers.number(quote.get("close_price")), "freshness": market,
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
        reconcile_share_basis(report, security.get("share_reconciliation"), report["instrument"]["last_price"], financials.now().date())
    # Financial version is independent of a quote or share-class event.
    report["instrument_version"] = financial_analysis_sector_numbers.digest([report["instrument"], report["version"]])
    if persist:
        from reporting import publication
        report = publication.publish_report(report)
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
                    value = financial_analysis_sector_numbers.decimal(cell)
                    if value is not None and value == int(value) and 1000 <= value <= 99999:
                        codes.add(f"{int(value):05d}")
    return codes


def bond_issuer_context(reference, lang="ru"):
    """Resolve an exact issuer identity; never infer credit quality from a name fragment."""
    identifier = reference.get("issuer_id") or reference.get("issuer")
    if not identifier:
        return {"issuer_id": None, "issuer_analysis_id": None, "issuer_report": None,
                "issuer_link_status": "not_verified"}
    try:
        issuer = financials.resolve_issuer(str(identifier))
    except financials.IssuerNotFoundError:
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
    report = public_report(report)
    return {"issuer_id": issuer["id"], "issuer_analysis_id": report["financial_snapshot_id"],
            "financial_as_of": report["financial_as_of"], "issuer_link_status": "verified",
            "issuer_report": report}


SPECIAL_LABELS = {
    "interest_income": (r"^итого процентных доходов$",),
    "interest_expenses": (r"^итого процентных расходов$",),
    "noninterest_income": (r"^итого (?:непроцентных|беспроцентных) доходов$",),
    "noninterest_expenses": (r"^итого (?:непроцентных|беспроцентных) расходов$",),
    "operating_expenses": (r"итого операционных расходов",),
    "net_revenue_before_operating_expenses": (r"^чистый доход до операционных расходов$",),
    # Match the asset line exactly.  A prefix match also captured the bank's
    # liability line "Кредиты и лизинговые операции к оплате" and understated
    # the loan book by more than half for HMKB.
    "loan_portfolio": (r"^(?:кредиты и лизинговые операции(?:,\s*чистые)?|кредиты клиентам|займы клиентам)$",),
    "customer_funds": (r"^(?:средства клиентов|депозиты клиентов)",),
    "demand_deposits": (r"^депозиты до востребования$",),
    "savings_deposits": (r"^сберегательные депозиты$",),
    "term_deposits": (r"^срочные депозиты$",),
    "loan_reserves": (r"^(?:минус:\s*)?резерв(?:ы)? (?:возможных убытков по кредитам и лизингу|на покрытие|по кредитам|по займам)",),
    "insurance_premiums": (r"^начисленные страховые премии",),
    "insurance_claims": (r"^страховые выплаты",),
    "cash": (r"^кассовая наличность",),
    "central_bank_balances": (r"^к получению из цбру$",),
    "due_from_banks": (r"^к получению из других банков$",),
    # Bank Form 2 lines the sector formulation library relies on: interest
    # income before and after the credit-loss estimate, the estimate itself,
    # and the fee and FX pairs that make up non-interest income.
    "net_interest_income_before_provisions": (r"^чистые процентные доходы до оценки возможных убытков",),
    "credit_loss_provisions": (r"^(?:минус:\s*)?оценка возможных убытков по кредитам и лизингу$",),
    "net_interest_income_after_provisions": (r"^чистые процентные доходы после оценки возможных убытков",),
    "fee_income": (r"^доходы от комиссий и платы за услуги$",),
    "fee_expenses": (r"^комиссионные расходы и расходы за услуги$",),
    "fx_income": (r"^прибыль в иностранной валюте$",),
    "fx_expenses": (r"^убытки в иностранной валюте$",),
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
            for row in financial_analysis_sector_inputs.statement_rows(sheet, "form1" if form == "balance" else "form2"):
                label = str(row.get("label") or "").lower().replace("ё", "е").replace("| nan", "").strip()
                label = re.sub(r"^(?:\d+|[а-яa-z])\.\s*", "", label).rstrip(".")
                matched = next((key for key, patterns in SPECIAL_LABELS.items() if any(re.search(p, label) for p in patterns)), None)
                if not matched:
                    continue
                nums = row.get("numeric_values") or []
                original = row.get("source_cells")
                if original:
                    code_index = next((i for i, v in enumerate(original) if financial_analysis_sector_numbers.decimal(v) is not None), None)
                    if code_index is not None:
                        nums = original[code_index:]
                # The bank income form discloses one current cumulative column.
                if form == "income" and original and nums:
                    current, prior = nums[0], None
                elif len(nums) in (2, 3):
                    prior, current = nums[-2:]
                else:
                    continue
                # The catalog snapshot has already reconciled these three
                # bank balance totals.  Some bank workbooks append percentage
                # columns or export blank totals as zero; treating one of
                # those cells as the amount used to replace valid catalog
                # totals and incorrectly block an otherwise complete report.
                # Keep the reconciled values and use the workbook mapper for
                # the bank-specific detail lines around them.
                preserve_current = False
                if matched in {"total_assets", "total_equity", "total_liabilities"}:
                    existing = financial_analysis_sector_numbers.decimal(snapshot["current_values"].get(matched))
                    if existing is not None and existing > 0:
                        preserve_current = True
                if not preserve_current:
                    snapshot["current_values"][matched] = financial_analysis_sector_numbers.number(current)
                target = "opening_values" if form == "balance" else "previous_values"
                if prior is not None:
                    snapshot[target][matched] = financial_analysis_sector_numbers.number(prior)
                snapshot.setdefault("field_sources", {})[matched] = {
                    "source_line_id": f"{form}:{sheet.get('sheet', sheet.get('name', ''))}:row{row.get('row', '')}",
                    "raw_current": str(current) if financial_analysis_sector_numbers.decimal(current) is not None else None,
                }

    # The statutory bank form exposes customer deposits as three adjacent
    # verified lines rather than one total.  Aggregate only when every
    # component is present; a missing line must never be treated as zero.
    deposit_keys = ("demand_deposits", "savings_deposits", "term_deposits")
    for target in ("current_values", "opening_values"):
        deposit_total = financial_analysis_sector_numbers.total(*(snapshot[target].get(key) for key in deposit_keys))
        if deposit_total is not None:
            snapshot[target]["customer_funds"] = financial_analysis_sector_numbers.number(deposit_total)
    if snapshot["current_values"].get("customer_funds") is not None:
        snapshot.setdefault("field_sources", {})["customer_funds"] = {
            "source_line_id": "balance:demand_deposits+savings_deposits+term_deposits",
            "raw_current": str(snapshot["current_values"]["customer_funds"]),
        }


def map_insurance_lines(snapshot, workbook):
    # c012 (premiums ceded to reinsurers) and c080 (the insurance-service
    # result, c060 − c070) are what premium retention and «результат от
    # страховых услуг» are calculated from.
    income_map = {"c060": "revenue", "c070": "insurance_service_cost", "c080": "insurance_service_result",
                  "c012": "ceded_premiums", "c090": "expenses",
                  "c150": "operating_income", "c160": "financial_income", "c200": "fx_income",
                  "c220": "financial_expenses", "c250": "fx_expenses", "c290": "profit_before_tax",
                  "c320": "net_income", "c011": "direct_insurance_premiums",
                  "c013": "accepted_reinsurance_premiums"}
    balance_map = {"c012": "fixed_assets", "c030": "long_term_investments", "c100": "construction_in_progress",
                   "c190": "receivables", "c410": "cash", "c490": "total_assets", "c570": "total_equity",
                   "c580": "gross_insurance_reserves", "c670": "reinsurer_share_in_reserves",
                   "c720": "net_insurance_reserves", "c1190": "other_liabilities"}
    for form, mapping, target in (("income", income_map, "previous_values"), ("balance", balance_map, "opening_values")):
        lines = financial_analysis_sector_inputs.source_line_pairs(workbook.get(form), "form2" if form == "income" else "form1", set(mapping))
        for code, field in mapping.items():
            if code not in lines:
                continue
            row = lines[code]
            for key, source_key in (("current_values", "raw_current"), (target, "raw_previous")):
                value = financial_analysis_sector_numbers.decimal(row[source_key])
                if field in {"insurance_service_cost", "ceded_premiums", "expenses", "financial_expenses", "fx_expenses"} and value is not None:
                    value = abs(value)
                snapshot[key][field] = str(value) if value is not None else None
            snapshot.setdefault("field_sources", {})[field] = {"source_line_id": f"insurance:{form}:{code}"}
    for target in ("current_values", "previous_values", "opening_values"):
        values = snapshot[target]
        if target != "previous_values":
            net = financial_analysis_sector_numbers.difference(values.get("gross_insurance_reserves"), values.get("reinsurer_share_in_reserves"))
            values["net_insurance_reserves"] = financial_analysis_sector_numbers.number(net)
            values["total_liabilities"] = financial_analysis_sector_numbers.number(financial_analysis_sector_numbers.total(net, values.get("other_liabilities")))
        else:
            continue
    for target in ("current_values", "previous_values"):
        values = snapshot[target]
        values["insurance_premiums"] = financial_analysis_sector_numbers.number(financial_analysis_sector_numbers.total(values.get("direct_insurance_premiums"), values.get("accepted_reinsurance_premiums")))
    snapshot.setdefault("field_sources", {})["insurance_premiums"] = {"source_line_id": "insurance:income:c011+c013"}
