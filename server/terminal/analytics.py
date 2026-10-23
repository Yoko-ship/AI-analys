"""Terminal projections of published financials. Never fill missing figures.

All statement amounts at this boundary are UZS, as in financial_series.
No ingestion, network calls or model-generated figures belong here.
"""
from __future__ import annotations

import math
import re
from financial_analysis.profitability import return_on


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def ratio(numerator, denominator, scale=1):
    n, d = number(numerator), number(denominator)
    return n / d * scale if n is not None and d is not None and d > 0 else None


def growth(values, end, years, *, inflation=None, fx=None):
    start = str(int(end) - years)
    first, last = number(values.get(start)), number(values.get(str(end)))
    result = {"start": start, "end": str(end), "years": years, "nominal": None,
              "real": None, "usd": None, "reason": None}
    if first is None or last is None:
        return {**result, "reason": "MISSING_ENDPOINT"}
    if first <= 0 or last <= 0:
        return {**result, "reason": "NON_POSITIVE_ENDPOINT"}
    factor = last / first
    result["nominal"] = (factor ** (1 / years) - 1) * 100
    rates = [number((inflation or {}).get(str(y))) for y in range(int(start) + 1, int(end) + 1)]
    if all(r is not None and r > -100 for r in rates):
        result["real"] = ((factor / math.prod(1 + r / 100 for r in rates)) ** (1 / years) - 1) * 100
    first_fx, last_fx = number((fx or {}).get(start)), number((fx or {}).get(str(end)))
    if first_fx and last_fx and first_fx > 0 and last_fx > 0:
        result["usd"] = ((factor * first_fx / last_fx) ** (1 / years) - 1) * 100
    return result


def values(data, field):
    return (data.get("series", {}).get(field) or {}).get("values", {})


def snapshot(data, *, kind="industry", year=None, market_cap=None):
    periods = sorted(p for p in data.get("periods", []) if re.fullmatch(r"\d{4}", str(p)))
    period = str(year) if year is not None else (periods[-1] if periods else None)
    v = lambda field: number(values(data, field).get(period))
    profit, equity, assets = v("net_profit"), v("total_equity"), v("total_assets")
    prior = str(int(period) - 1) if period else None
    returns = {code: return_on(profit, v(field), values(data, field).get(prior))
               for code, field in (("roe", "total_equity"), ("roa", "total_assets"))}
    # Returns state their denominator explicitly. Market multiples use this
    # exact annual, not a TTM figure from another screen or another standard.
    result = {"period": period, "standard": data.get("standard", "NSBU"),
              "scope": data.get("scope") or "separate", "kind": kind,
              "net_profit": profit, "equity": equity, "assets": assets,
              "revenue": None if kind in {"bank", "fund"} else v("net_revenue"),
              "roe": returns["roe"]["value"], "roa": returns["roa"]["value"],
              "de": None if kind in {"bank", "fund", "insurance", "financial"} else ratio(v("total_liabilities"), equity),
              "pe": ratio(market_cap, profit), "pb": ratio(market_cap, equity),
              "ps": None if kind in {"bank", "fund"} else ratio(market_cap, v("net_revenue")),
              "ep": ratio(profit, market_cap, 100), "return_basis": returns,
              "cg3": None, "cg5": None, "dy": None, "npl": None, "nim": None, "cost_of_risk": None,
              "source": (data.get("period_sources") or {}).get(period),
              "issues": [g for g in data.get("data_gaps", []) if g.get("period") == period]}
    if period and kind == "bank":
        from financial_analysis.sector_calculations import financial_ratios
        current = {field:v(field) for field in data.get("series", {})}
        opening = {field:number(values(data, field).get(prior)) for field in data.get("series", {})}
        if current.get("net_interest_income_before_provisions") is None:
            income, expense = v("interest_income"), v("interest_expense")
            if income is not None and expense is not None:
                current["net_interest_income_before_provisions"] = income - expense
        for item in financial_ratios(current, {}, opening, "bank", "ifrs" if data.get("standard") == "MSFO" else "nsbu", period):
            if item["metric"] in {"nim", "cost_of_risk"}:result[item["metric"]] = item["value"]
    if period:
        for years in (3, 5):
            result[f"cg{years}"] = growth(values(data, "net_profit"), period, years)["nominal"]
    return result


def peers(base, candidates):
    return [r for r in candidates if r.get("ticker") != base.get("ticker")
            and all(r.get(k) == base.get(k) for k in ("kind", "standard", "scope", "period"))]


def reconcile(nsbu, ifrs):
    rows = []
    for field in ("net_revenue", "net_profit", "total_assets", "total_equity", "total_liabilities"):
        left, right = values(nsbu, field), values(ifrs, field)
        for period in sorted(set(left) | set(right), reverse=True):
            a, b = number(left.get(period)), number(right.get(period))
            rows.append({"field": field, "period": period, "nsbu": a, "ifrs": b,
                         "difference": b - a if a is not None and b is not None else None,
                         "nsbu_source": (nsbu.get("period_sources") or {}).get(period),
                         "ifrs_source": (ifrs.get("period_sources") or {}).get(period)})
    return {"rows": rows, "nsbu_scope": nsbu.get("scope") or "separate", "ifrs_scope": ifrs.get("scope"),
            "same_scope": (nsbu.get("scope") or "separate") == ifrs.get("scope")}


def quarters(data, field="net_profit"):
    if data.get("period_basis") == "cumulative_ytd":
        return {"rows": [], "reason": "CUMULATIVE_NOT_STANDALONE"}
    source, rows = values(data, field), []
    for p in sorted(source):
        if not re.fullmatch(r"\d{4}Q[1-4]", p) or int(p[:4]) < 2022:
            continue
        year, quarter = int(p[:4]), int(p[-1])
        current, prior = number(source[p]), number(source.get(f"{year-1}Q{quarter}"))
        index = year * 4 + quarter - 1
        trailing = [number(source.get(f"{i//4}Q{i%4+1}")) for i in range(index - 3, index + 1)]
        annual = [number(source.get(f"{year}Q{q}")) for q in range(1, 5)]
        total = sum(annual) if all(v is not None for v in annual) else None
        same_quarter = {k[:4]: v for k, v in source.items() if k.endswith(f"Q{quarter}")}
        rows.append({"period": p, "value": current,
                     "yoy": (current / prior - 1) * 100 if current is not None and prior is not None and prior > 0 else None,
                     "ltm": sum(trailing) if all(v is not None for v in trailing) else None,
                     "seasonality": ratio(current, total, 100),
                     "cg3": growth(same_quarter, str(year), 3)["nominal"]})
    return {"rows": rows, "reason": None}


def dividend(items, price, *, today=None):
    """Latest positive decision, not an invented sum of overlapping payouts."""
    from datetime import date
    today = today or date.today()
    eligible = []
    for item in items:
        try:
            day = date.fromisoformat(str(item.get('decision_date'))[:10])
        except ValueError:
            continue
        amount = number(item.get('ordinary_amount'))
        if amount is not None and amount > 0 and 0 <= (today-day).days <= 366:
            eligible.append((day, amount, item))
    latest = max(eligible, key=lambda r:r[0], default=None)
    return {'dy':ratio(latest[1], price, 100) if latest else None,
            'basis':'latest_decision', 'decision':latest[2] if latest else None}
