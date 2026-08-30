"""Cash-flow verification and market freshness are independent dimensions."""
from __future__ import annotations

import math
from datetime import date


def day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def freshness(quote_date, as_of):
    quote = day(quote_date)
    if quote is None:
        return {"status": "never_traded", "days_since_trade": None, "quote_as_of": None}
    age = (as_of - quote).days
    status = "invalid_future_quote" if age < 0 else "fresh" if age <= 7 else "aging" if age <= 30 else "stale" if age <= 90 else "very_stale"
    return {"status": status, "days_since_trade": age, "quote_as_of": quote.isoformat()}


def apply_quality(result, reference, coupons, as_of, curve):
    import bonds
    market = freshness(result.get("last_trade_date"), as_of)
    result["freshness"] = market
    result["quote_as_of"] = market["quote_as_of"]
    result["days_since_trade"] = market["days_since_trade"]
    result["settlement_date"] = as_of.isoformat()
    result["calculation_version"] = "bond-cashflow-1.0"
    result["instrument_verdict"] = "insufficient_data"
    schedule = result.get("schedule") or {}
    future = [c for c in coupons if day(c.get("pay_date")) and day(c["pay_date"]) > as_of]
    confirmed = [c for c in future if c.get("source_url") and c.get("amount") is not None and not c.get("inferred")]
    schedule_source = reference.get("schedule_source")
    basis = reference.get("day_count") or reference.get("day_count_basis")
    result["day_count_basis"] = basis
    maturity = day(reference.get("maturity_date"))
    exact_schedule = (
        reference.get("cashflows_verified") in (True, 1)
        and schedule_source in {"issuer", "prospectus"}
        and len(confirmed) == len(future)
        and bool(future)
        and reference.get("options_verified") in (True, 1)
        and reference.get("isin") and reference.get("currency")
        and reference.get("status") in {"active", "live"}
        and (reference.get("coupon_type") != "floating" or reference.get("future_rates_verified") in (True, 1))
        and basis in {"ACT/365", "ACT/365F"}
        and maturity is not None and max(day(c["pay_date"]) for c in future) == maturity
    )
    schedule.update(source=schedule_source if exact_schedule else "inferred" if schedule.get("source") else None,
                    confidence="high" if exact_schedule else "low",
                    confirmed_payments=len(confirmed),
                    calculation_status="exact" if exact_schedule else "indicative")
    result["schedule"] = schedule
    result["cashflow_schedule"] = {"source": schedule["source"], "confidence": schedule["confidence"],
                                  "confirmed_payments": len(confirmed)}
    blocked = []
    def withhold(key, code):
        metric = result.get(key) or {}
        result[key] = ({**metric, "blocked_reason": code} if metric.get("value") is None
                       else {"value": None, "status": "unavailable", "blocked_reason": code})
    if market["status"] in {"never_traded", "invalid_future_quote"} or not result.get("price") or result["price"] <= 0:
        blocked.append("NO_VERIFIED_TRADE")
    if reference.get("coupon_type") == "floating" and not reference.get("future_rates_verified"):
        blocked.append("UNKNOWN_FUTURE_COUPONS")
        result["effective_at_par"] = {"value": None, "status": "scenario_required"}
    if any(reference.get(k) for k in ("amortization", "has_put", "has_call")) and not exact_schedule:
        blocked.append("AMORTIZATION_OR_OPTIONS_NOT_VERIFIED")
    if reference.get("payment_overdue") or reference.get("status") in {"defaulted", "suspended"}:
        blocked.append("PAYMENT_OR_ISSUE_STATUS_BLOCKED")
    if not basis:
        blocked.append("DAY_COUNT_NOT_DISCLOSED")
        withhold("accrued", "DAY_COUNT_NOT_DISCLOSED")
        withhold("dirty", "DAY_COUNT_NOT_DISCLOSED")
    elif basis not in {"ACT/365", "ACT/365F"}:
        blocked.append("DAY_COUNT_NOT_SUPPORTED")
        result["accrued"] = {"value": None, "status": "unavailable", "blocked_reason": blocked[-1]}
        result["dirty"] = {"value": None, "status": "unavailable", "blocked_reason": blocked[-1]}
    elif (result.get("accrued") or {}).get("value") is not None:
        result["accrued"].update(status="exact" if exact_schedule else "indicative", calculation_status="exact" if exact_schedule else "indicative")
    if exact_schedule and result.get("state") != "matured":
        next_payment = min(confirmed, key=lambda c: day(c["pay_date"]))
        period_from, period_to = day(next_payment.get("period_from")), day(next_payment.get("period_to"))
        if period_from and period_to and period_from <= as_of < period_to:
            accrued = float(next_payment["amount"]) * (as_of - period_from).days / (period_to - period_from).days
            result["accrued"] = {"value": accrued, "status": "exact", "calculation_status": "exact"}
            result["dirty"] = ({"value": result["price"] + accrued, "status": "exact"}
                               if "NO_VERIFIED_TRADE" not in blocked else
                               {"value": None, "status": "unavailable", "blocked_reason": "NO_VERIFIED_TRADE"})
        else:
            blocked.append("ACCRUAL_PERIOD_NOT_VERIFIED")
            result["accrued"] = {"value": None, "status": "unavailable", "blocked_reason": blocked[-1]}
            result["dirty"] = {"value": None, "status": "unavailable", "blocked_reason": blocked[-1]}
        # All dated principal movements are part of the supplied cash flows.
        # Never add the face value again to an amortizing principal schedule.
        flows = []
        for payment in confirmed:
            amount = float(payment["amount"]) + float(payment.get("principal") or 0)
            flows.append(((day(payment["pay_date"]) - as_of).days / 365, amount))
        principal = sum(float(c.get("principal") or 0) for c in confirmed)
        if abs(principal - float(reference.get("outstanding_principal_per_bond") or reference.get("nominal") or 0)) > .01:
            blocked.append("PRINCIPAL_SCHEDULE_NOT_RECONCILED")
        elif not blocked:
            dirty = (result.get("dirty") or {}).get("value")
            result["ytm"] = bonds.yield_to_maturity(flows, dirty) if dirty else {"value": None, "status": "unavailable"}
            result["duration"] = bonds.macaulay_duration(flows, dirty, result["ytm"].get("value")) if dirty else {"value": None, "status": "unavailable"}
            # The solver yields an effective annual XIRR, so its derivative
            # uses 1+y, not 1+y/frequency.
            result["modified_duration"] = bonds.modified_duration(result["duration"].get("value"), result["ytm"].get("value"), 1)
            result["convexity"] = bonds.convexity(flows, dirty, result["ytm"].get("value")) if dirty else {"value": None, "status": "unavailable"}
            result["bpv"] = bonds.bpv(result["modified_duration"].get("value"), dirty)
            result["spread"] = {"value": None, "status": "unavailable", "blocked_reason": "BASIS_NOT_VERIFIED"}
            annual = sum(float(c["amount"]) for c in confirmed if (day(c["pay_date"]) - as_of).days <= 365)
            result["simple_yield"] = bonds.simple_yield(annual, result.get("price"))
    calculation = "stale_indicative" if market["status"] in {"stale", "very_stale"} else "exact" if exact_schedule and market["days_since_trade"] == 0 else "indicative"
    for key in ("ytm", "duration", "modified_duration", "convexity", "bpv", "spread"):
        metric = result.get(key) or {"value": None, "status": "unavailable"}
        if blocked and metric.get("value") is not None:
            metric = {"value": None, "status": "unavailable", "blocked_reason": blocked[0]}
        elif metric.get("value") is not None:
            metric.update(status=calculation, calculation_status=calculation, confidence=schedule["confidence"])
        result[key] = metric
    withhold("g_spread", "COMPOUNDING_BASIS_OR_SCHEDULE_NOT_VERIFIED")
    # CBU rates are continuously compounded. Dates, currency and convention
    # must be explicit on every curve point; an auction yield is not this curve.
    if calculation == "exact" and not blocked and curve and all(
        p.get("as_of") == as_of.isoformat() and p.get("currency") == reference.get("currency")
        and p.get("compounding") == "continuous" for p in curve
    ):
        maturity = day(reference.get("maturity_date"))
        years = (maturity - as_of).days / 365 if maturity else None
        base = bonds.gov_curve_yield(years, curve)
        ytm = result["ytm"].get("value")
        if base is not None and ytm is not None and ytm > -100:
            continuous = math.log1p(ytm / 100)
            spread = continuous * 100 - base
            result["g_spread"] = {"value": spread, "bps": spread * 100, "status": "exact", "compounding": "continuous", "as_of": as_of.isoformat()}
    result["yield"] = {
        "current": (result.get("simple_yield") or {}).get("value"),
        "ytm_effective": result["ytm"].get("value") if calculation == "exact" and not blocked else None,
        "ytm_indicative": result["ytm"].get("value") if calculation != "exact" and not blocked else None,
        "unit": "percent", "g_spread_bps": result["g_spread"].get("bps"),
        "blocked_reason": blocked[0] if blocked else None,
    }
    if market["status"] in {"never_traded", "invalid_future_quote"}:
        withhold("simple_yield", "NO_VERIFIED_TRADE")
        result["yield"]["current"] = None
    result["data_quality"] = [{"code": code, "severity": "blocking"} for code in blocked]
    if calculation == "exact" and not blocked and result["ytm"].get("value") is not None:
        result["instrument_verdict"] = "calculation_verified"
    return result
