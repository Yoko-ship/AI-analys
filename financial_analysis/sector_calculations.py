"""Sector calculations. Pure deterministic rules."""
from __future__ import annotations

from decimal import Decimal
import financial_analysis.sector_numbers as financial_analysis_sector_numbers


METHODS = {
    "P1": (["form2:c270"], ["form1:c400"], True),
    "P2": (["form2:c240"], ["form1:c390"], True),
    "P3": (["form2:c240"], ["form1:c480", "form1:c570", "form1:c580"], True),
    "P4": (["form2:c240"], ["form1:c480"], True),
    "P5": (["form2:c030"], ["form2:c010"], True),
    "P6": (["form2:c030"], ["form2:c020"], True),
    "P7": (["form2:c240"], ["form2:c010"], True),
    "P8": (["form2:c240"], ["form1:c130"], True),
    "current_ratio": (["form1:c320", "form1:c370", "form1:c210", "form1:c140"], ["form1:c600"], False),
    "quick_ratio": (["form1:c320", "form1:c370", "form1:c210"], ["form1:c600"], False),
    "absolute_liquidity": (["form1:c320", "form1:c370"], ["form1:c600"], False),
}


def enterprise_ratios(lines, organization_type, standard, period, methods=None):
    if organization_type != "non_financial" or standard.lower() != "nsbu":
        return []
    results = []
    for code, (numerators, denominators, percent) in (METHODS if methods is None else methods).items():
        components = numerators + denominators
        values = {key: (lines.get(key) or {}).get("raw_current", (lines.get(key) or {}).get("current")) for key in components}
        numerator, denominator = financial_analysis_sector_numbers.total(*(values[k] for k in numerators)), financial_analysis_sector_numbers.total(*(values[k] for k in denominators))
        value = financial_analysis_sector_numbers.ratio(numerator, denominator, percent)
        # Balance opening values are comparable for liquidity, not for a
        # prior-year flow divided by this year's opening balance.
        opening = None
        if not percent:
            opening = financial_analysis_sector_numbers.ratio(financial_analysis_sector_numbers.total(*((lines.get(k) or {}).get("raw_previous", (lines.get(k) or {}).get("previous")) for k in numerators)),
                            financial_analysis_sector_numbers.total(*((lines.get(k) or {}).get("raw_previous", (lines.get(k) or {}).get("previous")) for k in denominators)))
        results.append({"metric": code, "metric_code": code,
                        "method_id": f"nsbu-enterprise-{'profitability' if percent else 'liquidity'}-1.0:{code}",
                        "accounting_standard": "NSBU", "period": period,
                        "numerator_value": financial_analysis_sector_numbers.number(numerator), "denominator_value": financial_analysis_sector_numbers.number(denominator),
                        "component_facts": components, "formula": f"({' + '.join(numerators)}) / ({' + '.join(denominators)})" + (" * 100" if percent else ""),
                        "raw_result": str(value) if value is not None else None,
                        "value": financial_analysis_sector_numbers.number(value), "display_result": str(value.quantize(Decimal("0.01"))) if value is not None else None,
                        "opening_value": financial_analysis_sector_numbers.number(opening), "change_value": financial_analysis_sector_numbers.number(financial_analysis_sector_numbers.difference(value, opening)),
                        "unit": "percent" if percent else "ratio", "benchmark_type": None if percent else "methodological_reference",
                        "benchmark_min": {"current_ratio": 1.5, "quick_ratio": 1, "absolute_liquidity": .2}.get(code),
                        "benchmark_max": {"current_ratio": 2, "absolute_liquidity": .5}.get(code),
                        "calculation_status": "verified" if value is not None else "missing_or_invalid_components",
                        "verification_status": "verified" if value is not None else "unavailable"})
    return results


# A financial organization's form carries no enterprise line codes, so its
# indicators are read from the named lines its own mapping produces.  Each
# method: numerators, denominators, unit, and which base its prior value has
# — "opening" for a balance-to-balance share, "previous" for flow-to-flow,
# None where a flow is divided by a balance and no comparable prior exists.
# None of these is a central-bank prudential ratio and none carries a
# benchmark: the filing does not disclose the regulatory components.
FINANCIAL_METHODS = {
    "roa": (["net_income"], ["total_assets"], "percent", None),
    "roe": (["net_income"], ["total_equity"], "percent", None),
    "equity_to_assets": (["total_equity"], ["total_assets"], "percent", "opening"),
    "loans_to_deposits": (["loan_portfolio"], ["customer_funds"], "ratio", "opening"),
    "liquid_to_deposits": (["cash", "central_bank_balances", "due_from_banks"], ["customer_funds"], "percent", "opening"),
    "loan_reserve_coverage": (["loan_reserves"], ["loan_portfolio"], "percent", "opening"),
    "cost_to_income": (["operating_expenses"], ["net_revenue_before_operating_expenses"], "percent", "previous"),
    "provisions_to_net_interest_income": (["credit_loss_provisions"], ["net_interest_income_before_provisions"], "percent", "previous"),
    "reinsurer_share_of_reserves": (["reinsurer_share_in_reserves"], ["gross_insurance_reserves"], "percent", "opening"),
    "insurance_reserves_to_liabilities": (["net_insurance_reserves"], ["total_liabilities"], "percent", "opening"),
}

_BANK_RATIOS = ("roa", "roe", "equity_to_assets", "loans_to_deposits", "liquid_to_deposits",
                "loan_reserve_coverage", "cost_to_income", "provisions_to_net_interest_income")

# Which indicators each organization type publishes.  Every type the report
# can publish figures for is either here, enterprise (form line codes), or in
# RATIOS_NOT_APPLICABLE with the reason — a type missing from all three is
# how banks went without indicators.
FINANCIAL_RATIOS = {
    "bank": _BANK_RATIOS,
    "microfinance_bank": _BANK_RATIOS,
    # A microfinance organization takes no deposits.
    "microfinance": ("roa", "roe", "equity_to_assets", "loan_reserve_coverage", "cost_to_income",
                     "provisions_to_net_interest_income"),
    # No loss ratio: the form does not separate claims from premiums earned.
    "insurance": ("roa", "roe", "equity_to_assets", "reinsurer_share_of_reserves", "insurance_reserves_to_liabilities"),
}

# Only a result may be negative (a loss).  A negative reserve, cost or balance
# line is a sign convention the mapping has not resolved — AGBA files its
# credit-loss estimate negative where every other bank files it positive — so
# a share built on it is withheld rather than printed as «−539%».
SIGNED_RATIOS = frozenset({"roa", "roe"})

RATIOS_NOT_APPLICABLE = {
    "investment_fund_ifrs_annual": "the fund is described by its NAV block",
    "spv": "an SPV report is blocked until its backing assets are verified",
}


def financial_ratios(values, previous, opening, organization_type, standard, period):
    results = []
    for code in FINANCIAL_RATIOS.get(organization_type, ()):
        numerators, denominators, unit, basis = FINANCIAL_METHODS[code]
        percent = unit == "percent"

        def measure(data):
            parts = [financial_analysis_sector_numbers.decimal(data.get(k)) for k in numerators]
            if code not in SIGNED_RATIOS and any(part is not None and part < 0 for part in parts):
                return None
            return financial_analysis_sector_numbers.ratio(
                financial_analysis_sector_numbers.total(*parts),
                financial_analysis_sector_numbers.total(*(data.get(k) for k in denominators)), percent)

        value = measure(values)
        prior = measure({"opening": opening, "previous": previous}[basis]) if basis else None
        numerator = financial_analysis_sector_numbers.total(*(values.get(k) for k in numerators))
        denominator = financial_analysis_sector_numbers.total(*(values.get(k) for k in denominators))
        results.append({"metric": code, "metric_code": code,
                        "method_id": f"{standard.lower()}-{organization_type}-indicators-1.0:{code}",
                        "accounting_standard": standard.upper(), "period": period,
                        "numerator_value": financial_analysis_sector_numbers.number(numerator),
                        "denominator_value": financial_analysis_sector_numbers.number(denominator),
                        "component_facts": numerators + denominators,
                        "formula": f"({' + '.join(numerators)}) / ({' + '.join(denominators)})" + (" * 100" if percent else ""),
                        "raw_result": str(value) if value is not None else None,
                        "value": financial_analysis_sector_numbers.number(value),
                        "display_result": str(value.quantize(Decimal("0.01"))) if value is not None else None,
                        "opening_value": financial_analysis_sector_numbers.number(prior),
                        "change_value": financial_analysis_sector_numbers.number(financial_analysis_sector_numbers.difference(value, prior)),
                        "unit": unit, "benchmark_type": None, "benchmark_min": None, "benchmark_max": None,
                        "calculation_status": "verified" if value is not None else "missing_or_invalid_components",
                        "verification_status": "verified" if value is not None else "unavailable"})
    return results


def balance_gate(values, rounding_unit=1):
    assets, equity, liabilities = (financial_analysis_sector_numbers.decimal(values.get(k)) for k in ("total_assets", "total_equity", "total_liabilities"))
    if any(v is None for v in (assets, equity, liabilities)):
        return {"status": "not_checked", "code": "BALANCE_COMPONENTS_MISSING", "severity": "blocking"}
    difference_value = assets - equity - liabilities
    tolerance = min(financial_analysis_sector_numbers.decimal(rounding_unit) or Decimal(1), abs(assets) * Decimal("0.0005"))
    passed = abs(difference_value) <= tolerance and assets > 0
    return {"status": "passed" if passed else "failed", "code": "BALANCE_IDENTITY_FAILED",
            "severity": None if passed else "blocking", "difference": financial_analysis_sector_numbers.number(difference_value),
            "tolerance": financial_analysis_sector_numbers.number(tolerance), "formula": "assets = equity + liabilities"}


def capital_analysis(values, opening):
    result = {"method_id": "nsbu-capital-structure-1.0",
              "equity_open": financial_analysis_sector_numbers.number(opening.get("total_equity")), "equity_end": financial_analysis_sector_numbers.number(values.get("total_equity")),
              "equity_change": financial_analysis_sector_numbers.number(financial_analysis_sector_numbers.difference(values.get("total_equity"), opening.get("total_equity"))),
              "change_sources": []}
    for suffix, data in (("open", opening), ("end", values)):
        result[f"equity_to_assets_{suffix}"] = financial_analysis_sector_numbers.number(financial_analysis_sector_numbers.ratio(data.get("total_equity"), data.get("total_assets"), True))
        result[f"liabilities_to_equity_{suffix}"] = financial_analysis_sector_numbers.number(financial_analysis_sector_numbers.ratio(data.get("total_liabilities"), data.get("total_equity")))
    for key in ("share_capital", "additional_capital", "reserve_capital", "treasury_shares", "retained_earnings", "target_receipts", "future_expense_reserves"):
        delta = financial_analysis_sector_numbers.difference(values.get(key), opening.get(key))
        result["change_sources"].append({"metric_code": key, "change_value": financial_analysis_sector_numbers.number(-delta if delta is not None and key == "treasury_shares" else delta)})
    sum_changes = financial_analysis_sector_numbers.total(*(item["change_value"] for item in result["change_sources"]))
    result["reconciliation_difference"] = financial_analysis_sector_numbers.number(financial_analysis_sector_numbers.difference(result["equity_change"], sum_changes))
    result["reconciliation_status"] = "not_available" if result["reconciliation_difference"] is None else "passed" if abs(financial_analysis_sector_numbers.decimal(result["reconciliation_difference"])) <= 1 else "failed"
    return result


def profit_quality(values, previous):
    op = financial_analysis_sector_numbers.change(values.get("operating_income"), previous.get("operating_income"))
    profit = financial_analysis_sector_numbers.change(values.get("net_income"), previous.get("net_income"))
    fx, fx_prev = financial_analysis_sector_numbers.difference(values.get("fx_income"), values.get("fx_expenses")), financial_analysis_sector_numbers.difference(previous.get("fx_income"), previous.get("fx_expenses"))
    fx_delta = financial_analysis_sector_numbers.difference(fx, fx_prev)
    driver = "unknown"
    unrealized = financial_analysis_sector_numbers.decimal(values.get("unrealized_fair_value_gain"))
    if unrealized is not None and (financial_analysis_sector_numbers.decimal(values.get("net_income")) or 0) > 0 and unrealized > 0 and unrealized >= financial_analysis_sector_numbers.decimal(values["net_income"]) * Decimal("0.5"):
        driver = "unrealized_revaluation"
    elif fx_delta is not None and profit["change_value"] is not None and fx_delta > 0 and profit["change_value"] > 0 and fx_delta >= financial_analysis_sector_numbers.decimal(profit["change_value"]) * Decimal("0.5"):
        driver = "FX-driven"
    return {"method_id": "nsbu-profit-quality-1.0", "operating_profit_change": op,
            "net_profit_change": profit, "net_fx_result_current": financial_analysis_sector_numbers.number(fx), "net_fx_result_previous": financial_analysis_sector_numbers.number(fx_prev),
            "net_fx_result_change": financial_analysis_sector_numbers.number(fx_delta), "driver": driver, "cash_confirmation": "not_available"}


def trend_state(points):
    """Describe only trends supported by comparable observations.

    Two observations are a comparison, not a trend.  Three comparable points
    can establish a direction; saying that a metric fell three times in a row
    requires four observations.  Context fields are part of comparability so a
    year, YTD and standalone quarter can never be joined into one sequence.
    """
    clean = []
    for point in points or []:
        value = financial_analysis_sector_numbers.decimal(point.get("value"))
        period = point.get("period")
        if value is None or not period:
            continue
        clean.append({**point, "value": financial_analysis_sector_numbers.number(value)})
    clean.sort(key=lambda item: str(item["period"]))
    if not clean:
        return {"status": "unavailable", "points": 0, "direction": None, "consecutive_moves": 0}
    contexts = {
        (item.get("period_basis"), item.get("accounting_standard"), item.get("consolidation_scope"))
        for item in clean
    }
    if len(contexts) > 1:
        return {"status": "not_comparable", "points": len(clean), "direction": None, "consecutive_moves": 0}
    if len(clean) == 1:
        return {"status": "single_point", "points": 1, "direction": None, "consecutive_moves": 0}
    moves = [clean[index]["value"] - clean[index - 1]["value"] for index in range(1, len(clean))]
    direction = "up" if all(move > 0 for move in moves) else "down" if all(move < 0 for move in moves) else "mixed"
    if len(clean) == 2:
        status = "comparison_only"
    elif direction == "down" and len(moves) >= 3:
        status = "three_consecutive_declines"
    elif direction in {"up", "down"}:
        status = "trend"
    else:
        status = "mixed"
    return {"status": status, "points": len(clean), "direction": direction,
            "consecutive_moves": len(moves) if direction in {"up", "down"} else 0,
            "periods": [item["period"] for item in clean]}
