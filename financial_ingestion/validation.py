"""Pure validation: no storage, fetching, inferred years or public writes."""
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import re

FIELDS = {"cash", "total_assets", "total_liabilities", "total_equity",
          "interest_income", "interest_expense", "operating_income",
          "operating_expenses", "net_income", "revenue", "gross_profit"}


def amount(value):
    if not isinstance(value, str) or not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        raise ValueError("Amounts must be unambiguous decimal strings")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not result.is_finite() or abs(result) > Decimal("1e24"):
        raise ValueError("Invalid amount range")
    return result


def validate(payload, *, page_count):
    errors, warnings = [], []
    if type(page_count) is not int or not 1 <= page_count <= 500:
        return {"valid": False, "errors": ["PAGE_COUNT_INVALID"], "warnings": [], "normalized_uzs": {}}
    meta = payload.get("classification") or {}
    if meta.get("standard") not in {"NSBU", "MSFO"}:
        errors.append("STANDARD_UNRESOLVED")
    if meta.get("scope") not in {"separate", "consolidated"}:
        errors.append("SCOPE_UNRESOLVED")
    if meta.get("currency") != "UZS" or str(meta.get("unit_scale")) not in {"1", "1000", "1000000"}:
        errors.append("UNIT_UNRESOLVED")
    if meta.get("role") not in {"PRIMARY", "COMPARATIVE", "RESTATEMENT"}:
        errors.append("ROLE_UNRESOLVED")
    try:
        start, end = date.fromisoformat(meta["period_start"]), date.fromisoformat(meta["period_end"])
        if start > end or end >= date.today() or (end - start).days > 365:
            errors.append("INVALID_PERIOD")
        if meta.get("role") == "PRIMARY" and end.year != meta.get("document_year"):
            errors.append("DOCUMENT_PERIOD_MISMATCH")
        if meta.get("role") == "COMPARATIVE" and end.year >= meta.get("document_year", 0):
            errors.append("COMPARATIVE_PERIOD_MISMATCH")
        if meta.get("role") == "RESTATEMENT" and end.year > meta.get("document_year", 0):
            errors.append("RESTATEMENT_PERIOD_MISMATCH")
    except (ValueError, TypeError, KeyError):
        errors.append("PERIOD_UNRESOLVED")
        end = None
    for key in ("period_evidence", "unit_evidence", "issuer_evidence"):
        if not meta.get(key):
            errors.append(key.upper() + "_MISSING")
    figures = payload.get("figures") or {}
    normalized = {}
    if not figures:
        errors.append("NO_FIGURES")
    for field, figure in figures.items():
        if field not in FIELDS:
            errors.append("UNKNOWN_FIELD:" + field)
            continue
        if (not figure.get("raw_label") or type(figure.get("page")) is not int
                or not 1 <= figure["page"] <= page_count or not end
                or figure.get("column_year") != end.year):
            errors.append("FIELD_EVIDENCE_INVALID:" + field)
        try:
            raw = amount(figure.get("raw_value"))
            scale = amount(str(meta.get("unit_scale")))
            with localcontext() as ctx:
                ctx.prec = 50
                normalized[field] = format(raw * scale, "f")
            if field in {"cash", "total_assets", "total_liabilities", "interest_income"} and raw < 0:
                errors.append("SIGN_INVALID:" + field)
            if field in {"interest_expense", "operating_expenses"} and raw > 0:
                errors.append("EXPENSE_SIGN_INVALID:" + field)
        except ValueError:
            errors.append("AMOUNT_INVALID:" + field)
    balance = {"total_assets", "total_liabilities", "total_equity"}
    if balance <= normalized.keys():
        gap = Decimal(normalized["total_assets"]) - Decimal(normalized["total_liabilities"]) - Decimal(normalized["total_equity"])
        if abs(gap) > Decimal(str(meta["unit_scale"])):
            errors.append("BALANCE_MISMATCH")
        if Decimal(normalized["total_assets"]) <= 0:
            errors.append("EMPTY_BALANCE")
    else:
        warnings.append("PARTIAL_BALANCE")
    if not {"net_income", "interest_income"} <= normalized.keys():
        warnings.append("PARTIAL_INCOME")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "normalized_uzs": normalized}


def from_review(entry):
    year = entry["year"]
    return {"classification": {
        "standard": entry.get("standard", "MSFO"), "scope": entry["scope"],
        "currency": entry["currency"], "unit_scale": str(entry["unit_scale"]),
        "period_start": entry.get("period_start", f"{year}-01-01"),
        "period_end": entry.get("period_end", f"{year}-12-31"),
        "document_year": entry.get("document_year", year), "role": entry.get("role", "PRIMARY"),
        "period_evidence": entry["period_evidence"], "unit_evidence": entry["unit_evidence"],
        "issuer_evidence": entry.get("issuer_evidence") or entry["issuer_name"],
        "issuer_name": entry["issuer_name"],
    }, "figures": entry["figures"], "review_method": entry["review_method"]}
