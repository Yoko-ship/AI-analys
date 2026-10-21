"""Adapters for the verified sector contract, shared by both public entrypoints."""
from __future__ import annotations

import logging
import re
import json
from pathlib import Path
from copy import deepcopy
from decimal import Decimal
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


def sector_report(issuer, standard, period, scope, lang, *, persist=True, rule_override=None,
                  _workbook=None, _refresh_checked=False):
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
            workbook = _workbook if _workbook is not None else financials.fetch_report_excel_data(issuer["ticker"], "NSBU", year, quarter)
            if not workbook.get("ok"):
                raise ValueError("source workbook unavailable")
            workbook = deepcopy(workbook)
            hashes = {form: part['content_sha256'] for form in ('income', 'balance')
                      if (part := workbook.get(form) or {}).get('content_sha256')}
            if hashes:
                source['content_hashes'] = hashes
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
            earlier = {}
            if org in {"bank", "microfinance_bank", "microfinance", "insurance"}:
                catalog_opening = deepcopy(snapshot.get("opening_values") or {})
                map_special_lines(snapshot, workbook, org)
                if org in BANK_FORMS:
                    date_balance_comparison(issuer, snapshot, reports, org, catalog_opening, earlier)
                    _record_missing_key_lines(snapshot, lang, org)
            fill_from_earlier_filings(issuer, snapshot, reports, org, earlier)
            if org in BANK_FORMS:
                _drop_unbalanced_opening(snapshot)
        except Exception as exc:
            snapshot['source_refresh_failed'] = True
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
    cached_source = any((workbook or {}).get(form, {}).get('from_cache')
                        for form in ('income', 'balance') if (workbook or {}).get(form))
    incomplete = report.get('content_status') == 'shortened' or any(
        q.get('code') == 'KEY_LINE_MISSING' for q in report.get('data_quality', []))
    if standard == 'nsbu' and selected and cached_source and incomplete and not _refresh_checked:
        year, quarter = financials.period_key(selected)
        try:
            refreshed = financials.fetch_report_excel_data(
                issuer['ticker'], 'NSBU', year, quarter if 'Q' in selected else 0, revalidate_cached=True)
            if refreshed.get('ok'):
                return sector_report(issuer, standard, period, scope, lang, persist=persist,
                                     rule_override=rule_override, _workbook=refreshed, _refresh_checked=True)
        except Exception:
            logger.warning('Incomplete report source refresh failed for %s', issuer['ticker'], exc_info=True)
        report['source_refresh_failed'] = True
    if snapshot.get('source_refresh_failed') or any(
            ((workbook or {}).get(form) or {}).get('refresh_failed') for form in ('income', 'balance')):
        report['source_refresh_failed'] = True
    if report.get('source_refresh_failed'):
        report['data_quality'] = [*report.get('data_quality', []), {
            'code': 'SOURCE_REFRESH_FAILED', 'severity': 'warning',
            'message': financial_analysis_sector_language.tr(lang,
                'Обновление источника не удалось; показаны последние сохранённые данные.',
                'Manbani yangilab bo‘lmadi; oxirgi saqlangan ma’lumotlar ko‘rsatilgan.',
                'Source refresh failed; showing the last saved data.'),
        }]
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


def _earlier_workbook(issuer, reports, period, cache=None):
    """The source workbook of another filing of the same issuer, or None."""
    if cache is not None and period in cache:
        return cache[period]
    doc = next((r for r in reports if r.get("period") == period), None)
    if not doc or not (doc.get("excel_url") or doc.get("excel_url_form1")):
        return None
    year, quarter = financials.period_key(period)
    try:
        workbook = financials.fetch_report_excel_data(issuer["ticker"], "NSBU", year, quarter if "Q" in period else 0)
    except Exception:
        logger.warning("Comparison workbook unavailable for %s %s", issuer.get("ticker"), period, exc_info=True)
        return None
    workbook = deepcopy(workbook) if workbook and workbook.get("ok") else None
    if cache is not None:
        cache[period] = workbook
    return workbook


# Forms that print no date over their comparison column (the bank family's
# quarterly form).  The enterprise and insurance Form №1 heads the column
# «на начало отчётного периода», which is 1 January by the form itself.
BANK_FORMS = frozenset({"bank", "microfinance_bank", "microfinance"})


def _same_amount(left, right):
    left, right = financial_analysis_sector_numbers.decimal(left), financial_analysis_sector_numbers.decimal(right)
    return left is not None and right is not None and abs(left - right) <= max(Decimal(1), abs(right) * Decimal("0.000001"))


def year_start_date(period):
    """The balance date «1 January» stands for: the previous year's end."""
    year = financials.period_key(period)[0]
    return f"{year - 1}-12-31" if year else None


def date_balance_comparison(issuer, snapshot, reports, org, catalog_opening, cache=None):
    """Date the comparison column of a bank's balance sheet, or replace it.

    The bank form gives no date for its comparison column and banks fill it
    differently: AGBA and HMKB with the end of the previous quarter, OCBK with
    1 January, ORFI with the same quarter a year earlier.  The column is
    matched against the totals the issuer's own filings state at their period
    ends; a match dates it.  A column that does not balance (MCBA 2026Q2:
    assets of one date, liabilities of another) or that no filing dates is
    not a comparison: the start of the year from the previous annual filing
    takes its place, as the specification prescribes for a column that does
    not reconcile.
    """
    sources = snapshot.setdefault("comparison_sources", {})
    period = snapshot.get("period")
    start = year_start_date(period)
    opening = snapshot.get("opening_values") or {}
    if not start:
        return
    if not sources.get("opening_from_filing"):
        sources["opening_date"] = start
        return
    filed_assets = opening.get("total_assets")
    balanced = financial_analysis_sector_calculations.balance_gate(opening).get("status") == "passed"
    dated = None
    if balanced:
        end = financials.period_end(period)
        known = sorted(((entry.get("date"), entry.get("total_assets")) for entry in (snapshot.get("balance_history") or {}).values()
                        if entry.get("date") and entry["date"] < end), key=lambda item: item[0] != start)
        dated = next((date for date, assets in known if _same_amount(filed_assets, assets)), None)
        if dated is None:
            annual = _earlier_workbook(issuer, reports, str(financials.period_key(period)[0] - 1), cache)
            if annual and _same_amount(filed_assets, _filed_lines(annual, org).get("total_assets")):
                dated = start
    if dated:
        sources["opening_date"] = dated
        return
    snapshot["opening_values"] = dict(catalog_opening)
    sources["opening_from_filing"] = False
    sources["opening_rejected"] = "unbalanced" if not balanced else "undated"
    sources["opening_date"] = start


def _drop_unbalanced_opening(snapshot):
    """A start-of-year balance that does not balance is no comparison either."""
    opening = snapshot.get("opening_values") or {}
    if not opening or any(financial_analysis_sector_numbers.decimal(opening.get(key)) is None
                          for key in ("total_assets", "total_equity", "total_liabilities")):
        return
    if financial_analysis_sector_calculations.balance_gate(opening).get("status") != "passed":
        sources = snapshot.setdefault("comparison_sources", {})
        snapshot["opening_values"] = {}
        sources.update(opening_available=False, opening_rejected="unbalanced", opening_date=None)
        sources.pop("opening_fallback", None)


def _filed_lines(workbook, org):
    """Current-column amounts of a workbook, mapped as the report maps them."""
    if org in {"bank", "microfinance_bank", "microfinance", "insurance"}:
        mapped = {"current_values": {}, "previous_values": {}, "opening_values": {}, "quality": {"data_quality": []}}
        map_special_lines(mapped, workbook, org)
        return mapped["current_values"]
    values = {}
    for form, table, mapping in (("form1", workbook.get("balance"), financial_analysis_sector_inputs.FORM1),
                                 ("form2", workbook.get("income"), financial_analysis_sector_inputs.FORM2)):
        for code, row in financial_analysis_sector_inputs.source_line_pairs(table, form).items():
            if code in mapping:
                values[mapping[code]] = row.get("raw_current")
    return values


def fill_from_earlier_filings(issuer, snapshot, reports, org, cache=None):
    """Take a missing comparison from the issuer's other filings.

    Results are compared with the same period a year earlier and the balance
    with the start of the year.  When the filing itself has no usable
    comparison column (a bank's one-column income form, a blank or zeroed
    column), the same-period filing of the previous year and the previous
    annual filing supply it.  This applies to every sector; nothing is filled
    where the filing already states a comparison, and a balance compared with
    another date (the end of the previous quarter) is not completed with
    start-of-year lines: one balance comparison has one date.
    """
    period = snapshot.get("period")
    if not period or snapshot.get("standard", "nsbu") != "nsbu":
        return
    template = (snapshot.get("template_resolution") or {}).get("selected_template") or "generic_nsbu"
    current = snapshot.get("current_values") or {}
    sources = snapshot.setdefault("comparison_sources", {})
    year = financials.period_key(period)[0]
    for target, earlier in (("previous_values", snapshot.get("previous_comparable_period")),
                            ("opening_values", str(year - 1) if year else None)):
        balance = target == "opening_values"
        if balance and sources.get("opening_date") not in (None, year_start_date(period)):
            continue
        missing = [key for key, value in current.items() if value is not None
                   and financial_analysis_sector_templates.balance_line(key, template) == balance
                   and financial_analysis_sector_numbers.decimal((snapshot.get(target) or {}).get(key)) is None]
        if not missing or not earlier:
            continue
        workbook = _earlier_workbook(issuer, reports, earlier, cache)
        if not workbook:
            continue
        filed = _filed_lines(workbook, org)
        if financial_analysis_sector_inputs.blank_column(filed.get(key) for key in missing):
            continue
        filled = [key for key in missing if financial_analysis_sector_numbers.decimal(filed.get(key)) is not None]
        for key in filled:
            snapshot.setdefault(target, {})[key] = financial_analysis_sector_numbers.number(filed[key])
        if filled:
            sources["opening_fallback" if balance else "previous_fallback"] = earlier


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
    # the loan book by more than half for HMKB.  The form carries the loan
    # book twice (line 7 and its «г. …, чистые» subtotal) and banks leave
    # either one blank or fill it with the gross amount; ``_net_loans`` picks
    # the one that agrees with gross loans and leasing less the reserve.
    "loan_portfolio": (r"^(?:кредиты и лизинговые операции(?:,\s*чистые)?|кредиты клиентам|займы клиентам)$",),
    "gross_loans": (r"^брутто кредиты$",),
    "gross_leasing": (r"^лизинговые операции,\s*брутто$",),
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
    # The non-interest income outside fees, FX and trading: the line against
    # which a credit-loss charge of the same size reads as a gross-up.
    "other_noninterest_income": (r"^другие беспроцентные доходы$",),
    "total_assets": (r"^итого активов$",),
    "total_liabilities": (r"^итого обязательств$",),
    "total_equity": (r"^итого собственного капитала$",),
    "share_capital": (r"^уставный капитал$",),
    "additional_capital": (r"^добавленный капитал$",),
    "retained_earnings": (r"^нераспределенная прибыль",),
    "net_income": (r"^чистая прибыль \(убытки\)$",),
    "profit_before_tax": (r"^чистая прибыль до уплаты налогов",),
}


# Lines without which a bank's balance sheet is not a bank's: a zero here,
# beside positive assets, is a missed line, never a real amount.
BANK_CORE_LINES = ("loan_portfolio", "customer_funds", "cash", "central_bank_balances", "total_equity")


# Lines without which the bank analysis loses a section; a filing that does
# not yield one is recorded in data_quality instead of passing in silence.
BANK_KEY_LINES = ("total_assets", "total_liabilities", "total_equity", "loan_portfolio", "customer_funds",
                  "interest_income", "net_income")

# «Минус: …» lines are deductions whatever sign the bank typed: ORFI files its
# loan-loss reserve as −90.6 bn and still nets it out of the loan book.
DEDUCTION_LINES = frozenset({"loan_reserves"})


def _first_filled(found):
    """The first non-zero amount a key matched, else the first amount.

    A subtotal the bank left at zero («г. Кредиты и лизинговые операции,
    чистые» at AGBA and INFB) must not hide the filled line above it.
    """
    for value, line in found:
        amount = financial_analysis_sector_numbers.decimal(value)
        if amount is not None and amount != 0:
            return value, line
    return next(((value, line) for value, line in found if value is not None), found[0] if found else (None, None))


def _net_loans(found, gross, leasing, reserve):
    """The net loan book of one column, checked against its components.

    The filed loan lines disagree with each other across banks (AGBA's line 7
    is net and its «чистые» line gross or zero, OCBK's line 7 is gross, GRBK
    files leasing only and leaves both totals at zero).  Gross loans plus
    gross leasing less the reserve is the net book; the filed line that
    equals it is taken, and without such a line the components themselves.
    """
    parts = [financial_analysis_sector_numbers.decimal(item) for item in (gross, leasing)]
    reserve = financial_analysis_sector_numbers.decimal(reserve)
    same = lambda a, b: abs(a - b) <= max(Decimal(1), abs(b) * Decimal("0.000001"))
    if reserve is not None and any(part is not None and part > 0 for part in parts):
        net = sum(part for part in parts if part is not None) - abs(reserve)
        if net > 0:
            for value, line in found:
                amount = financial_analysis_sector_numbers.decimal(value)
                if amount is not None and same(amount, net):
                    return value, line
            return financial_analysis_sector_numbers.number(net), "balance:gross_loans+gross_leasing-loan_reserves"
    if reserve:
        # No gross lines: of two filed totals one reserve apart, the smaller
        # is the net book (SQBN 2025Q2: line 7 gross, «чистые» net).
        amounts = [(financial_analysis_sector_numbers.decimal(value), value, line) for value, line in found]
        for amount, value, line in amounts:
            if amount and any(other and same(other - abs(reserve), amount) for other, _, _ in amounts):
                return value, line
    return _first_filled(found) if found else (None, None)


def _resolve_bank_column(found, snapshot=None):
    """One amount per key for one statement column."""
    column, lines = {}, {}
    for key, entries in found.items():
        if key == "loan_portfolio":
            continue
        value, line = _first_filled(entries)
        if key in DEDUCTION_LINES and financial_analysis_sector_numbers.decimal(value) is not None:
            value = financial_analysis_sector_numbers.number(abs(financial_analysis_sector_numbers.decimal(value)))
        column[key], lines[key] = value, line
    if "loan_portfolio" in found or "gross_loans" in found or "gross_leasing" in found:
        value, line = _net_loans(found.get("loan_portfolio") or [], column.get("gross_loans"), column.get("gross_leasing"),
                                 column.get("loan_reserves"))
        if value is not None or "loan_portfolio" in found:
            column["loan_portfolio"], lines["loan_portfolio"] = value, line
    if snapshot is not None:
        for key, value in column.items():
            snapshot.setdefault("field_sources", {})[key] = {
                "source_line_id": lines[key],
                "raw_current": str(value) if financial_analysis_sector_numbers.decimal(value) is not None else None,
            }
    return column


def _sign_credit_loss_provisions(income):
    """Read the credit-loss charge's sign from the form's own arithmetic.

    Line 3 less line 3а is line 3б: a charge when 3б is below 3, a release
    when above.  Banks type the charge with either sign (AGBA: −3.28 trn with
    3б = 3 − 3.28 trn), so the sign of the cell says nothing; the identity
    does.  Without it, or when neither reading reconciles, the filed amount
    stands.
    """
    before = financial_analysis_sector_numbers.decimal(income.get("net_interest_income_before_provisions"))
    after = financial_analysis_sector_numbers.decimal(income.get("net_interest_income_after_provisions"))
    charge = financial_analysis_sector_numbers.decimal(income.get("credit_loss_provisions"))
    if None in (before, after, charge) or charge == 0:
        return
    tolerance = max(Decimal(1), abs(charge) * Decimal("0.0001"))
    if abs(before - abs(charge) - after) <= tolerance:
        income["credit_loss_provisions"] = financial_analysis_sector_numbers.number(abs(charge))
    elif abs(before + abs(charge) - after) <= tolerance:
        income["credit_loss_provisions"] = financial_analysis_sector_numbers.number(-abs(charge))


def _record_missing_key_lines(snapshot, lang="ru", org="bank"):
    """A key bank line the filing did not yield is a data-quality finding."""
    values = snapshot.get("current_values") or {}
    # A microfinance organisation takes no deposits: no customer funds to miss.
    expected = [key for key in BANK_KEY_LINES if not (org == "microfinance" and key == "customer_funds")]
    missing = [key for key in expected if financial_analysis_sector_numbers.decimal(values.get(key)) is None]
    quality = snapshot.setdefault("quality", {}).setdefault("data_quality", [])
    quality[:] = [item for item in quality if item.get("code") != "KEY_LINE_MISSING"]
    if missing:
        names = ", ".join(financial_analysis_sector_language.label(key, lang) for key in missing)
        quality.append({"code": "KEY_LINE_MISSING", "severity": "warning", "lines": missing,
                        "message": financial_analysis_sector_language.tr(
                            lang, f"В отчёте не найдены строки: {names}; разделы с ними не пишутся.",
                            f"Hisobotda satrlar topilmadi: {names}; ular bilan bo‘limlar yozilmaydi.",
                            f"Lines not found in the filing: {names}; sections that need them are omitted.")})


def _apply_columns(snapshot, staged, protected=()):
    """Write staged statement columns, skipping a blank one.

    A column whose every amount is zero is an empty column in the filing (or
    a parser miss), so it is not written over the comparison the catalogue
    already holds.  Returns which targets were taken from the filing.
    """
    used = {}
    for target, rows in staged.items():
        amounts = [value for key, value in rows.items() if key not in protected]
        if not rows or financial_analysis_sector_inputs.blank_column(amounts):
            used[target] = False
            continue
        for key, value in rows.items():
            snapshot[target][key] = value
        used[target] = True
    return used


def _drop_missed_bank_lines(snapshot):
    """A bank never holds zero cash, central-bank balances, loans, deposits or equity.

    Beside positive assets such a zero is a line the parser missed, so it is
    removed rather than published as «снизился до нуля».
    """
    for target in ("current_values", "opening_values"):
        values = snapshot.get(target) or {}
        assets = financial_analysis_sector_numbers.decimal(values.get("total_assets"))
        if not assets or assets <= 0:
            continue
        for key in BANK_CORE_LINES:
            if financial_analysis_sector_numbers.decimal(values.get(key)) == 0:
                values.pop(key, None)


def map_special_lines(snapshot, workbook, org):
    # Label-anchored direct lines only. Bank pre-tax profit is not operating profit.
    if org == "insurance":
        return map_insurance_lines(snapshot, workbook)
    snapshot["current_values"].pop("operating_income", None) if org != "insurance" else None
    # Staged per statement: a blank balance column must not be hidden by the
    # amounts of the income statement read in the same pass.
    staged = {form: {"current_values": {}, "opening_values": {}, "previous_values": {}} for form in ("balance", "income")}
    # Every row a key matched, per column, in the filing's order: a line the
    # form carries twice must not be decided by whichever row came last.
    candidates = {form: {"current_values": {}, "opening_values": {}, "previous_values": {}} for form in ("balance", "income")}
    preserved = set()
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
                # The bank income form discloses one current cumulative
                # column, and so does the annual balance sheet: its single
                # amount is the year end, not a comparison.
                if form == "income" and original and nums:
                    current, prior = nums[0], None
                elif len(nums) in (2, 3):
                    prior, current = nums[-2:]
                elif form == "balance" and len(nums) == 1:
                    current, prior = nums[0], None
                else:
                    continue
                # The catalog snapshot has already reconciled these three
                # bank balance totals.  Some bank workbooks append percentage
                # columns or export blank totals as zero; treating one of
                # those cells as the amount used to replace valid catalog
                # totals and incorrectly block an otherwise complete report.
                # Keep the reconciled values and use the workbook mapper for
                # the bank-specific detail lines around them.
                if matched in {"total_assets", "total_equity", "total_liabilities"}:
                    existing = financial_analysis_sector_numbers.decimal(snapshot["current_values"].get(matched))
                    if existing is not None and existing > 0:
                        preserved.add(matched)
                line = f"{form}:{sheet.get('sheet', sheet.get('name', ''))}:row{row.get('row', '')}"
                if matched not in preserved:
                    candidates[form]["current_values"].setdefault(matched, []).append((financial_analysis_sector_numbers.number(current), line))
                target = "opening_values" if form == "balance" else "previous_values"
                if prior is not None:
                    candidates[form][target].setdefault(matched, []).append((financial_analysis_sector_numbers.number(prior), line))
    for form, columns in candidates.items():
        for target, found in columns.items():
            staged[form][target] = _resolve_bank_column(found, snapshot if target == "current_values" else None)
    _sign_credit_loss_provisions(staged["income"]["current_values"])
    balance = staged["balance"]
    reconciled = financial_analysis_sector_numbers.decimal(snapshot["current_values"].get("total_assets"))
    filed_opening = financial_analysis_sector_numbers.decimal(balance["opening_values"].get("total_assets"))
    if (financial_analysis_sector_inputs.blank_column(balance["current_values"].values()) and reconciled and filed_opening is not None
            and abs(filed_opening - reconciled) <= 1):
        # The amounts sit one column early: the only filled column carries
        # exactly the reconciled period-end totals, so it is the period end,
        # and the start of the year comes from the previous annual filing.
        balance["current_values"] = {key: value for key, value in balance["opening_values"].items() if key not in preserved}
        balance["opening_values"] = {}
    used = {**_apply_columns(snapshot, staged["income"]), **_apply_columns(snapshot, balance)}
    _drop_missed_bank_lines(snapshot)
    sources = snapshot.setdefault("comparison_sources", {})
    sources["opening_from_filing"] = used.get("opening_values", False)
    if any(staged["income"]["previous_values"].values()):
        sources["previous_from_filing"] = used.get("previous_values", False)

    # The statutory bank form exposes customer deposits as three adjacent
    # verified lines rather than one total.  Aggregate only when every
    # component is present; a missing line must never be treated as zero.
    deposit_keys = ("demand_deposits", "savings_deposits", "term_deposits")
    for target in ("current_values", "opening_values"):
        deposit_total = financial_analysis_sector_numbers.total(*(snapshot[target].get(key) for key in deposit_keys))
        assets = financial_analysis_sector_numbers.decimal(snapshot[target].get("total_assets"))
        if deposit_total is not None and not (deposit_total == 0 and assets and assets > 0):
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
    staged = {"current_values": {}, "previous_values": {}, "opening_values": {}}
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
                # A blank cell stays missing rather than erasing the comparison.
                if value is not None:
                    staged[key][field] = str(value)
            snapshot.setdefault("field_sources", {})[field] = {"source_line_id": f"insurance:{form}:{code}"}
    used = _apply_columns(snapshot, staged)
    sources = snapshot.setdefault("comparison_sources", {})
    sources["opening_from_filing"] = used.get("opening_values", False)
    sources["previous_from_filing"] = used.get("previous_values", False)
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
