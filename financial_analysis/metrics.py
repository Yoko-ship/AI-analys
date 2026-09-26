"""Compose financial rule results without data collection or provider calls."""
from financial_analysis.history import FinancialHistory
from financial_analysis.rules import efficiency, profitability, statements, strength, trends, valuation


def compute_metrics(annual_data: list, quarterly_data: list = None) -> dict:
    if not annual_data:
        return {}
    history = FinancialHistory(annual_data, quarterly_data or [])
    metrics = {}
    for calculate in (valuation.fibonacci, strength.strength, efficiency.efficiency,
                      statements.statements, profitability.profitability,
                      trends.trends, trends.momentum, valuation.valuation):
        metrics.update(calculate(history))
    metrics["total_score"] = strength.score(history, metrics)
    return metrics
