"""Walk-forward validation for the deterministic business forecast."""
from __future__ import annotations

from statistics import median
from typing import Any


def walk_forward_annual(annual: dict[str, dict[str, Any]], *,
                        publication_dates: dict[str, str] | None = None) -> dict[str, Any]:
    """Run a deterministic annual walk-forward experiment.

    The numerical diagnostic is useful even when an old filing has no known
    publication timestamp.  It must not, however, become a publishable
    backtest in that case: without that timeline the system cannot prove that a
    corrected filing was not available to the historical model.
    """
    rows = []
    for year, values in (annual or {}).items():
        try:
            revenue, profit = float(values["revenue"]), float(values["net_income"])
            if revenue > 0 and str(year).isdigit(): rows.append((int(year), revenue, profit))
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort()
    trials = []
    for index in range(3, len(rows)):
        history, actual = rows[:index], rows[index]
        growth = [b[1] / a[1] - 1 for a, b in zip(history, history[1:]) if a[1] > 0]
        margins = [p / r for _, r, p in history[-3:] if r > 0]
        if len(growth) < 2 or not margins: continue
        predicted = history[-1][1] * (1 + median(growth[-3:]))
        error = abs(predicted - actual[1]) / actual[1] * 100 if actual[1] else None
        trials.append({"year": actual[0], "predicted_revenue": predicted, "actual_revenue": actual[1], "absolute_error_pct": error})
    if len(trials) < 2:
        return {"status": "NO_DATA", "model_version": "forecast-historical-v1",
                "reason": "At least five comparable annual periods are required for walk-forward backtesting.", "trials": trials}
    mae = sum(t["absolute_error_pct"] for t in trials if t["absolute_error_pct"] is not None) / len(trials)
    needed_years = {str(year) for year, _, _ in rows}
    dated_years = {str(year) for year, stamp in (publication_dates or {}).items() if stamp}
    chronology_verified = needed_years.issubset(dated_years)
    return {"status": "AVAILABLE", "method": "walk-forward annual revenue forecast",
            "model_version": "forecast-historical-v1", "trials": trials,
            "mae_pct": mae, "calibrated": False,
            "publication": "BLOCKED",
            "chronology_verified": chronology_verified,
            "reason": ("Backtest is reported, but probability calibration is not implemented."
                       if chronology_verified else
                       "Backtest diagnostic is not publishable: publication dates are missing for one or more filing years.")}
