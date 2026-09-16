"""Transparent, deterministic business scenarios for the paid research view.

This is deliberately not a recommendation engine.  It extrapolates only the
issuer's filed annual revenue and net-margin history, labels every assumption,
and withholds probabilities until a walk-forward calibration exists.
"""
from __future__ import annotations

from statistics import median
from typing import Any


def _number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if value == value else None
    except (TypeError, ValueError):
        return None


def build_forecast(ticker: str, standard: str, annual: dict[str, dict[str, Any]], *,
                   shares_outstanding: float | None = None,
                   current_price: float | None = None,
                   peer_pe: list[float] | None = None) -> dict[str, Any]:
    rows = []
    for period, values in (annual or {}).items():
        if not str(period).isdigit():
            continue
        revenue, profit = _number(values.get("revenue")), _number(values.get("net_income"))
        if revenue is not None and profit is not None and revenue > 0:
            rows.append((int(period), revenue, profit))
    rows.sort()
    if len(rows) < 3:
        return {"status": "NO_DATA", "ticker": ticker, "standard": standard,
                "model_version": "forecast-historical-v1",
                "reason": "At least three comparable filed annual periods are required."}

    growth = [(cur[1] / prev[1]) - 1 for prev, cur in zip(rows, rows[1:]) if prev[1] > 0]
    margins = [profit / revenue for _, revenue, profit in rows[-3:]]
    if len(growth) < 2 or not margins:
        return {"status": "NO_DATA", "ticker": ticker, "standard": standard,
                "model_version": "forecast-historical-v1",
                "reason": "Comparable revenue growth and net-margin history is insufficient."}
    ordered_growth = sorted(growth[-3:])
    latest_year, latest_revenue, _latest_profit = rows[-1]
    base_margin = median(margins)
    scenarios = []
    for key, rate in (("downside", ordered_growth[0]), ("base", median(ordered_growth)), ("upside", ordered_growth[-1])):
        revenue = latest_revenue * (1 + rate)
        profit = revenue * base_margin
        eps = (profit * 1000 / shares_outstanding) if shares_outstanding and shares_outstanding > 0 else None
        scenarios.append({"scenario": key, "revenue": revenue, "net_profit": profit,
                          "eps": eps, "revenue_growth_pct": rate * 100,
                          "net_margin_pct": base_margin * 100, "probability": None,
                          "probability_status": "NOT_CALIBRATED"})
    valid_pe = sorted(p for p in (peer_pe or []) if p > 0 and p <= 80)
    fair_value = {"status": "NO_DATA", "reason": "At least two verified comparable sector peer P/E inputs are required."}
    if len(valid_pe) >= 2 and all(item["eps"] is not None for item in scenarios):
        multiples = [valid_pe[0], median(valid_pe), valid_pe[-1]]
        prices = [scenarios[i]["eps"] * multiples[i] for i in range(3)]
        fair_value = {"status": "AVAILABLE", "method": "peer P/E on next-year scenario EPS",
                      "lower": prices[0], "mid": prices[1], "upper": prices[2],
                      "peer_pe": {"lower": multiples[0], "mid": multiples[1], "upper": multiples[2]},
                      "facts_as_of_year": latest_year,
                      "current_price": current_price}
    return {"status": "AVAILABLE", "ticker": ticker, "standard": standard,
            "model_version": "forecast-historical-v1",
            "scenario_money_unit": "thousand UZS",
            "facts_as_of_year": latest_year, "historical_years": [r[0] for r in rows[-3:]],
            "assumptions": {"revenue_growth_history_pct": [v * 100 for v in growth[-3:]],
                            "net_margin_history_pct": [v * 100 for v in margins],
                            "method": "historical annual growth and median net margin"},
            "scenarios": scenarios, "fair_value": fair_value,
            "market_scenario": {"status": "NO_DATA", "reason": "A price scenario requires a confirmed technical condition."},
            "quality": {"publication": "BLOCKED", "reason": "Scenario probabilities require walk-forward calibration."}}
