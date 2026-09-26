"""Prepare computed metrics for a compact analysis prompt."""
from __future__ import annotations




def slim_metrics_for_prompt(metrics: dict) -> dict:
    if not metrics:
        return {}

    keep = {}

    score = metrics.get("total_score", {})
    if score:
        keep["total_score"] = {
            "score": score.get("score"),
            "grade": score.get("grade"),
            "summary": score.get("summary"),
        }

    # Piotroski / Altman / Buffett / Graham are NOT shown to the user any more
    # (industrial-only models, misleading for banks). Don't pass them to the LLM
    # either — otherwise it cites the numbers in the verdict text.

    dcf = metrics.get("dcf", {})
    if dcf:
        keep["dcf"] = {
            "intrinsic_value_bn": dcf.get("intrinsic_value_bn"),
            "signal": dcf.get("signal"),
            "verdict": dcf.get("verdict"),
        }

    trends = metrics.get("trends", {})
    if trends:
        keep["trends"] = {
            "overall_score": trends.get("overall_score"),
            "overall_label": trends.get("overall_label"),
            "revenue": trends.get("revenue"),
            "profit": trends.get("profit"),
            "margin": trends.get("margin"),
            "debt": trends.get("debt"),
        }

    industry = metrics.get("industry", {})
    if industry:
        keep["industry"] = {
            "sector_name": industry.get("sector_name"),
            "verdict": industry.get("verdict"),
            "good_count": industry.get("good_count"),
            "weak_count": industry.get("weak_count"),
            "capex_note": industry.get("capex_note"),
        }

    liquidity = metrics.get("market_liquidity", {})
    if liquidity:
        keep["market_liquidity"] = liquidity

    momentum = metrics.get("momentum", {})
    if momentum:
        keep["momentum"] = momentum

    # NEW: Efficiency metrics
    efficiency = metrics.get("efficiency", {})
    if efficiency:
        keep["efficiency"] = {
            "inventory_turnover": efficiency.get("inventory_turnover"),
            "receivable_days": efficiency.get("receivable_days"),
            "payable_days": efficiency.get("payable_days"),
            "cash_conversion_cycle": efficiency.get("cash_conversion_cycle"),
        }

    # NEW: DuPont Analysis
    dupont = metrics.get("dupont_analysis", {})
    if dupont:
        keep["dupont_analysis"] = {
            "roe_pct": dupont.get("roe_pct"),
            "components": dupont.get("components"),
            "drivers": dupont.get("drivers"),
            "interpretation": dupont.get("interpretation"),
        }

    # NEW: Working Capital
    working_cap = metrics.get("working_capital", {})
    if working_cap:
        keep["working_capital"] = {
            "amount": working_cap.get("amount"),
            "change_yoy": working_cap.get("change_yoy"),
            "current_ratio": working_cap.get("current_ratio"),
            "quick_ratio": working_cap.get("quick_ratio"),
            "cash_ratio": working_cap.get("cash_ratio"),
            "verdict": working_cap.get("verdict"),
        }

    # NEW: Technical Indicators
    technical = metrics.get("technical_indicators", {})
    if technical and technical.get("status") == "ok":
        keep["technical_indicators"] = {
            "rsi": technical.get("rsi"),
            "fibonacci_price": technical.get("fibonacci_price"),
            "price_momentum": technical.get("price_momentum"),
            "volume_analysis": technical.get("volume_analysis"),
            "volatility": technical.get("volatility"),
            "summary": technical.get("summary"),
        }

    # NEW: Horizontal Analysis (YoY changes)
    horizontal = metrics.get("horizontal_analysis", {})
    if horizontal:
        keep["horizontal_analysis"] = {
            "items": horizontal.get("items"),
            "summary": horizontal.get("summary"),
            "verdict": horizontal.get("verdict"),
        }

    # NEW: Vertical Analysis (structure %)
    vertical = metrics.get("vertical_analysis", {})
    if vertical:
        keep["vertical_analysis"] = {
            "balance_sheet": vertical.get("balance_sheet"),
            "income_statement": vertical.get("income_statement"),
        }

    # NEW: Profitability Ratios
    profitability = metrics.get("profitability_ratios", {})
    if profitability:
        keep["profitability_ratios"] = profitability

    # NEW: Solvency Ratios
    solvency = metrics.get("solvency_ratios", {})
    if solvency:
        keep["solvency_ratios"] = solvency

    # NEW: Cash Flow Analysis
    cash_flow = metrics.get("cash_flow_analysis", {})
    if cash_flow:
        keep["cash_flow_analysis"] = cash_flow

    return keep
