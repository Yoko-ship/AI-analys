"""One period-specific ROE/ROA rule for the screener and verified analysis.

Inputs must belong to one issuer, standard, scope and cumulative reporting
period, in the same currency/unit. Callers resolve that context; no I/O here.
"""
from decimal import Decimal

from financial_analysis.sector_numbers import decimal, number, ratio


VERSION = "period-returns-1.0"


def return_on(net_income, closing, opening=None, *, months=12):
    profit, end, start = map(decimal, (net_income, closing, opening))
    months = decimal(months)
    # An all-zero opening column is how these forms encode an unfilled
    # comparison. Negative opening equity remains a real filed deficit.
    if start == 0 and end not in (None, 0):
        start = None
    base = (start + end) / 2 if start is not None and end is not None else end
    annualised_profit = (profit * Decimal(12) / months
                         if profit is not None and months is not None and 0 < months <= 12 else None)
    status = ("missing_components" if annualised_profit is None or end is None
              else "invalid_denominator" if end <= 0 or base <= 0 else "verified")
    result = ratio(annualised_profit, base, True) if status == "verified" else None
    basis = "average" if start is not None else "closing"
    return {"value": number(result), "raw_result": str(result) if result is not None else None,
            "numerator_value": number(profit), "annualised_net_income": number(annualised_profit),
            "denominator_value": number(base), "denominator_basis": basis,
            "opening_balance": number(start), "closing_balance": number(end),
            "period_months": number(months), "annualised": months is not None and 0 < months < 12,
            "calculation_status": status, "method_id": VERSION,
            "formula": "net_income * 12 / period_months / "
                       + ("((opening_balance + closing_balance) / 2)" if basis == "average" else "closing_balance")
                       + " * 100"}


def returns(values, opening, *, months=12):
    return {code: {**return_on(values.get("net_income"), values.get(field), opening.get(field), months=months),
                   "method_id": f"{VERSION}:{code}"}
            for code, field in (("roe", "total_equity"), ("roa", "total_assets"))}
