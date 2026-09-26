"""Profitability, solvency, and cash-flow proxy rules."""
import math
from financial_analysis.history import value as get


def profitability(history):
    metrics = {}
    latest = history.latest
    revenue = get(latest, "revenue", 0)
    net_income = get(latest, "net_income", 0)
    equity = get(latest, "equity", 0)
    total_assets = get(latest, "total_assets", 0)
    current_liab = get(latest, "current_liabilities", 0)
    ebit = get(latest, "ebit", 0)
    gross_profit = get(latest, "gross_profit", 0)
    # ── PROFITABILITY RATIOS (Коэффициенты рентабельности) ─
    profitability = {}

    if revenue > 0:
        profitability["gross_margin"] = {
            "value": round((gross_profit / revenue) * 100, 2) if gross_profit else 0,
            "benchmark": "15-40%",
            "verdict": (
                "Отлично" if gross_profit and (gross_profit / revenue) > 0.35
                else "Хорошо" if gross_profit and (gross_profit / revenue) > 0.20
                else "Низкая маржа"
            ),
        }
        profitability["operating_margin"] = {
            "value": round((ebit / revenue) * 100, 2) if ebit else 0,
            "benchmark": "10-25%",
            "verdict": (
                "Отлично" if ebit and (ebit / revenue) > 0.20
                else "Хорошо" if ebit and (ebit / revenue) > 0.10
                else "Низкая операционная маржа"
            ),
        }
        profitability["net_margin"] = {
            "value": round((net_income / revenue) * 100, 2),
            "benchmark": "5-15%",
            "verdict": (
                "Отлично" if (net_income / revenue) > 0.15
                else "Хорошо" if (net_income / revenue) > 0.08
                else "Нормально" if (net_income / revenue) > 0.03
                else "Низкая чистая маржа"
            ),
        }

    if total_assets > 0:
        profitability["roa"] = {
            "value": round((net_income / total_assets) * 100, 2),
            "benchmark": "5-10%",
            "verdict": (
                "Отлично" if (net_income / total_assets) > 0.10
                else "Хорошо" if (net_income / total_assets) > 0.05
                else "Низкая доходность активов"
            ),
        }

    if equity > 0:
        profitability["roe"] = {
            "value": round((net_income / equity) * 100, 2),
            "benchmark": "15-25%",
            "verdict": (
                "Отлично" if (net_income / equity) > 0.20
                else "Хорошо" if (net_income / equity) > 0.12
                else "Низкая доходность капитала"
            ),
        }

    if profitability:
        metrics["profitability_ratios"] = profitability

    # ── SOLVENCY RATIOS (Коэффициенты платежеспособности) ─
    solvency = {}
    total_liab = total_assets - equity if total_assets and equity else 0

    if total_assets > 0:
        solvency["debt_ratio"] = {
            "value": round((total_liab / total_assets) * 100, 1),
            "benchmark": "<50%",
            "verdict": (
                "Отлично — низкий долг" if (total_liab / total_assets) < 0.40
                else "Нормально" if (total_liab / total_assets) < 0.60
                else "Высокий долг — риск"
            ),
        }

    if equity > 0 and total_liab > 0:
        dte = total_liab / equity
        solvency["debt_to_equity"] = {
            "value": round(dte, 2),
            "benchmark": "<1.0",
            "verdict": (
                "Отлично — капитал превышает долг" if dte < 0.5
                else "Нормально" if dte < 1.5
                else "Высокий финансовый рычаг"
            ),
        }

    if equity > 0:
        solvency["equity_ratio"] = {
            "value": round((equity / total_assets) * 100, 1) if total_assets else 0,
            "benchmark": ">40%",
            "verdict": (
                "Отлично — сильный капитал" if total_assets and (equity / total_assets) > 0.50
                else "Нормально" if total_assets and (equity / total_assets) > 0.30
                else "Слабая капитализация"
            ),
        }

    if solvency:
        metrics["solvency_ratios"] = solvency

    # ── CASH FLOW ANALYSIS (Анализ денежных потоков) ──────
    # Используем доступные данные для оценки денежных потоков
    cash_flow = {}

    # Операционный денежный поток (прокси через EBIT + амортизация)
    # Упрощение: OCF ≈ EBIT × (1 - tax) + depreciation (если нет прямых данных)
    op_cash_flow = get(latest, "operating_cash_flow", 0)
    if not op_cash_flow and ebit > 0:
        # Грубая оценка: EBIT после налога как прокси OCF
        op_cash_flow = ebit * 0.85  # ~15% налог

    if op_cash_flow and revenue > 0:
        ocf_to_sales = (op_cash_flow / revenue) * 100
        cash_flow["ocf_to_sales"] = {
            "value": round(ocf_to_sales, 1),
            "interpretation": (
                "Отлично — сильная генерация кеша" if ocf_to_sales > 15
                else "Хорошо — здоровый денежный поток" if ocf_to_sales > 8
                else "Нормально" if ocf_to_sales > 3
                else "Слабый денежный поток"
            ),
        }

    # Коэффициент денежного покрытия
    if op_cash_flow and current_liab > 0:
        cash_coverage = op_cash_flow / current_liab
        cash_flow["cash_coverage_ratio"] = {
            "value": round(cash_coverage, 2),
            "interpretation": (
                "Отлично — OCF покрывает обязательства" if cash_coverage > 1.5
                else "Нормально" if cash_coverage > 0.8
                else "Риск — недостаточный денежный поток"
            ),
        }

    # Free Cash Flow (если есть CAPEX или оцениваем)
    capex = get(latest, "capital_expenditures", 0) or get(latest, "capex", 0)
    if op_cash_flow:
        # Если нет CAPEX, оцениваем как % от выручки (средне 5-10%)
        if not capex and revenue > 0:
            capex = revenue * 0.06  # консервативная оценка

        fcf = op_cash_flow - capex if capex else op_cash_flow
        cash_flow["free_cash_flow"] = {
            "value": round(fcf, 0),
            "as_pct_of_revenue": round((fcf / revenue) * 100, 1) if revenue else 0,
            "verdict": (
                "Позитивный FCF — компания генерирует свободный кеш" if fcf > 0
                else "Отрицательный FCF — компания потребляет кеш"
            ),
        }

        if op_cash_flow > 0:
            fcf_ratio = fcf / op_cash_flow
            cash_flow["fcf_to_ocf_ratio"] = {
                "value": round(fcf_ratio * 100, 1),
                "interpretation": (
                    f"{round(fcf_ratio * 100, 0)}% OCF остается после капзатрат"
                ),
            }

    if cash_flow:
        metrics["cash_flow_analysis"] = cash_flow
    return metrics
