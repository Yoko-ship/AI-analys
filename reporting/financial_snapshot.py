"""Prepare normalized financial statements and bank metrics for reports."""

from __future__ import annotations
from reporting.localization import LANGUAGE_HINTS, _normalize_language
from reporting.numbers import (
    _growth_pct,
    _latest_item,
    _pct_from_fraction,
    _pct_from_percent,
    _safe_float,
)


def _compute_bank_profile(latest: dict, prev: dict | None) -> dict | None:
    """Compute bank-specific ratios (CAR, NIM, LDR, CIR) when the company has
    bank-shaped balance sheet (customer_deposits / loans_to_customers).

    Returns None for non-banks so the front-end can skip the bank panel."""
    customer_deposits = _safe_float(latest.get("customer_deposits"))
    loans = _safe_float(latest.get("loans_to_customers"))
    interbank = _safe_float(latest.get("interbank_deposits"))
    if customer_deposits is None and loans is None and interbank is None:
        return None

    total_assets = _safe_float(latest.get("total_assets"))
    equity = _safe_float(latest.get("equity"))
    revenue = _safe_float(latest.get("revenue"))           # interest income for banks
    gross_profit = _safe_float(latest.get("gross_profit"))  # net interest income
    operating_expenses = _safe_float(latest.get("operating_expenses"))
    net_income = _safe_float(latest.get("net_income"))
    interest_expense = _safe_float(latest.get("interest_expense"))

    def pct(num, den):
        if num is None or den in (None, 0):
            return None
        return round(num / den * 100, 2)

    # CAR (simplified: equity / total assets — true CAR needs risk-weighted assets)
    car_simple = pct(equity, total_assets)
    # NIM: net interest income / total assets
    nim = pct(gross_profit, total_assets)
    # LDR: loans / customer deposits
    ldr = pct(loans, customer_deposits)
    # CIR: operating expenses / (net interest income + ... ) ≈ opex / revenue (interest income)
    # Use gross_profit (NII) as denominator when revenue is sketchy
    cir_denom = gross_profit if gross_profit and gross_profit > 0 else revenue
    cir = pct(operating_expenses, cir_denom) if operating_expenses is not None else None
    # Cost of funds (rough): interest_expense / customer_deposits
    cost_of_funds = pct(interest_expense, customer_deposits)
    # Loan-to-asset
    loan_to_assets = pct(loans, total_assets)
    # ROA / ROE — банк-aware (используем то же net_income / equity / assets)
    bank_roa = pct(net_income, total_assets)
    bank_roe = pct(net_income, equity)
    # Interest income coverage (banking): interest income / interest expense
    int_income_cov = None
    if revenue is not None and interest_expense not in (None, 0):
        int_income_cov = round(revenue / abs(interest_expense), 3)

    def tone(value, good, bad, reverse=False):
        if value is None:
            return "neutral"
        if reverse:  # lower is better (CIR, cost of funds)
            return "good" if value <= good else "warning" if value <= bad else "danger"
        return "good" if value >= good else "warning" if value >= bad else "danger"

    return {
        "is_bank": True,
        "car_simple_pct": car_simple,           # capital adequacy (equity/assets)
        "nim_pct": nim,                          # net interest margin
        "ldr_pct": ldr,                          # loan-to-deposit
        "cir_pct": cir,                          # cost-to-income
        "loan_to_assets_pct": loan_to_assets,
        "roa_pct": bank_roa,
        "roe_pct": bank_roe,
        "interest_income_coverage": int_income_cov,  # interest income / interest expense
        "tones": {
            "car_simple_pct": tone(car_simple, 10, 6),
            "nim_pct": tone(nim, 4, 2),
            "ldr_pct": tone(ldr, 70, 95, reverse=True) if ldr is not None and ldr > 100
                       else tone(ldr, 90, 70),
            "cir_pct": tone(cir, 50, 65, reverse=True),
            "interest_income_coverage": tone(int_income_cov, 1.5, 1.2),
        },
        "notes": {
            "car_simple_pct": "Достаточность капитала (equity / активы) — рисково-взвешенный CAR требует RWA, которого нет в публичной отчётности.",
            "nim_pct": "Чистый процентный доход / активы — сколько банк зарабатывает на каждом сум активов.",
            "ldr_pct": "Кредиты / депозиты — насколько активно банк раздаёт собранные деньги.",
            "cir_pct": "Операционные расходы / чистый процентный доход — сколько съедает обслуживание.",
            "interest_income_coverage": "Процентные доходы / процентные расходы — сколько раз доходы покрывают стоимость фондирования.",
        },
    }


def _build_ifrs_snapshot(
    company_name: str,
    annual_data: list,
    quarterly_data: list,
    metrics: dict,
    industry: dict | None,
    liquidity_data: dict | None,
    language: str,
) -> dict:
    latest = _latest_item(annual_data)
    prev = annual_data[-2] if len(annual_data) >= 2 else {}
    latest_q = _latest_item(quarterly_data)

    revenue = _safe_float(latest.get("revenue"))
    gross_profit = _safe_float(latest.get("gross_profit"))
    ebit = _safe_float(latest.get("ebit"))
    net_income = _safe_float(latest.get("net_income"))
    total_assets = _safe_float(latest.get("total_assets"))
    equity = _safe_float(latest.get("equity"))
    current_assets = _safe_float(latest.get("current_assets"))
    current_liabilities = _safe_float(latest.get("current_liabilities"))
    cash = _safe_float(latest.get("cash"))
    long_term_debt = _safe_float(latest.get("long_term_debt"))
    inventory = _safe_float(latest.get("inventory"))
    receivables = _safe_float(latest.get("accounts_receivable"))
    payables = _safe_float(latest.get("accounts_payable"))
    retained_earnings = _safe_float(latest.get("retained_earnings"))
    interest_expense = _safe_float(latest.get("interest_expense"))

    working_capital = None
    if current_assets is not None and current_liabilities is not None:
        working_capital = round(current_assets - current_liabilities, 2)

    debt_to_equity = None
    if long_term_debt is not None and equity not in (None, 0):
        debt_to_equity = round(long_term_debt / equity, 3)

    debt_to_assets = None
    if long_term_debt is not None and total_assets not in (None, 0):
        debt_to_assets = round(long_term_debt / total_assets, 3)

    cash_to_debt = None
    if cash is not None and long_term_debt not in (None, 0):
        cash_to_debt = round(cash / long_term_debt, 3)

    current_ratio = None
    if current_assets is not None and current_liabilities not in (None, 0):
        current_ratio = round(current_assets / current_liabilities, 3)

    latest_revenue = revenue
    prev_revenue = _safe_float(prev.get("revenue")) if prev else None
    latest_gross_margin = _pct_from_fraction(latest.get("gross_profit_margin"))
    latest_ebit_margin = _pct_from_fraction(latest.get("ebit_margin"))
    latest_net_margin = _pct_from_fraction(latest.get("net_profit_margin"))
    latest_roe = _pct_from_percent(latest.get("return_on_equity"))
    latest_roa = _pct_from_percent(latest.get("return_on_assets"))

    trend_block = metrics.get("trends", {}) if isinstance(metrics, dict) else {}
    momentum_block = metrics.get("momentum", {}) if isinstance(metrics, dict) else {}
    piotroski = metrics.get("piotroski_f_score", {}) if isinstance(metrics, dict) else {}
    altman = metrics.get("altman_z_score", {}) if isinstance(metrics, dict) else {}
    buffett = metrics.get("buffett_criteria", {}) if isinstance(metrics, dict) else {}
    dcf = metrics.get("dcf", {}) if isinstance(metrics, dict) else {}
    graham = metrics.get("graham_number", {}) if isinstance(metrics, dict) else {}
    icr = metrics.get("interest_coverage", {}) if isinstance(metrics, dict) else {}

    green_flags: list[str] = []
    red_flags: list[str] = []

    def add_flag(bucket: list[str], text: str):
        if text not in bucket:
            bucket.append(text)

    revenue_yoy = _growth_pct(revenue, prev_revenue)
    if revenue_yoy is not None:
        if revenue_yoy >= 10:
            add_flag(green_flags, f"Выручка выросла на {revenue_yoy}% г/г")
        elif revenue_yoy <= 0:
            add_flag(red_flags, f"Выручка снизилась на {abs(revenue_yoy)}% г/г")

    if latest_net_margin is not None:
        if latest_net_margin >= 10:
            add_flag(green_flags, f"Чистая маржа {latest_net_margin}%")
        elif latest_net_margin < 0:
            add_flag(red_flags, f"Чистая маржа {latest_net_margin}%")

    if current_ratio is not None:
        if current_ratio >= 1.5:
            add_flag(green_flags, f"Текущая ликвидность {current_ratio}")
        elif current_ratio < 1:
            add_flag(red_flags, f"Текущая ликвидность {current_ratio}")

    if debt_to_equity is not None:
        if debt_to_equity <= 0.8:
            add_flag(green_flags, f"Долг/капитал {debt_to_equity}")
        elif debt_to_equity >= 2:
            add_flag(red_flags, f"Долг/капитал {debt_to_equity}")

    piotroski_score = piotroski.get("score")
    if isinstance(piotroski_score, (int, float)):
        if piotroski_score >= 7:
            add_flag(green_flags, f"Piotroski {piotroski_score}/9")
        elif piotroski_score <= 3:
            add_flag(red_flags, f"Piotroski {piotroski_score}/9")

    altman_score = altman.get("score")
    if isinstance(altman_score, (int, float)):
        if altman_score > 2.5:
            add_flag(green_flags, f"Altman Z {altman_score}")
        elif altman_score < 1.8:
            add_flag(red_flags, f"Altman Z {altman_score}")

    if icr.get("ratio") is not None:
        if icr["ratio"] > 5:
            add_flag(green_flags, f"Покрытие процентов {icr['ratio']}")
        elif icr["ratio"] < 2:
            add_flag(red_flags, f"Покрытие процентов {icr['ratio']}")

    if momentum_block.get("css") == "bullish":
        add_flag(green_flags, "Краткосрочный импульс положительный")
    elif momentum_block.get("css") == "bearish":
        add_flag(red_flags, "Краткосрочный импульс отрицательный")

    # EBITDA family (ТЗ §3.3). Only when the filing discloses D&A (many NSBU
    # commercial forms bury it in cost-of-sales); otherwise these stay None and
    # the UI shows "н/д" rather than a fabricated figure.
    depreciation = _safe_float(latest.get("depreciation")) if isinstance(latest, dict) else None
    ebitda = (ebit + depreciation) if (isinstance(ebit, (int, float)) and isinstance(depreciation, (int, float))) else None
    ebitda_margin = round(ebitda / revenue * 100, 1) if (ebitda is not None and isinstance(revenue, (int, float)) and revenue) else None
    debt_to_ebitda = round(long_term_debt / ebitda, 2) if (ebitda and ebitda > 0 and isinstance(long_term_debt, (int, float)) and long_term_debt) else None

    return {
        "company": company_name.strip() if company_name else "",
        "language": _normalize_language(language),
        "language_label": LANGUAGE_HINTS[_normalize_language(language)]["label"],
        "currency": "UZS (млн)",
        "periods": {
            "annual": (
                f"{annual_data[0].get('year')}–{annual_data[-1].get('year')}"
                if annual_data else None
            ),
            "quarterly": (
                f"{quarterly_data[0].get('period')}–{quarterly_data[-1].get('period')}"
                if quarterly_data else None
            ),
        },
        "income_statement": {
            "revenue": revenue,
            "revenue_yoy_pct": revenue_yoy,
            "gross_profit": gross_profit,
            "gross_margin_pct": latest_gross_margin,
            "ebit": ebit,
            "ebit_margin_pct": latest_ebit_margin,
            "ebitda": ebitda,
            "ebitda_margin_pct": ebitda_margin,
            "depreciation": depreciation,
            "debt_to_ebitda": debt_to_ebitda,
            "net_income": net_income,
            "net_margin_pct": latest_net_margin,
            "quarterly_revenue": _safe_float(latest_q.get("revenue")),
            "quarterly_net_income": _safe_float(latest_q.get("net_income")),
            "quarterly_growth": latest_q.get("qoq_growth") if isinstance(latest_q, dict) else None,
        },
        "balance_sheet": {
            "total_assets": total_assets,
            "equity": equity,
            "cash": cash,
            "working_capital": working_capital,
            "current_assets": current_assets,
            "current_liabilities": current_liabilities,
            "current_ratio": current_ratio,
            "long_term_debt": long_term_debt,
            "debt_to_equity": debt_to_equity,
            "debt_to_assets": debt_to_assets,
            "cash_to_debt": cash_to_debt,
            "inventory": inventory,
            "receivables": receivables,
            "payables": payables,
            "retained_earnings": retained_earnings,
            "interest_expense": interest_expense,
        },
        "quality": {
            "roe_pct": latest_roe,
            "roa_pct": latest_roa,
            "interest_coverage": icr.get("ratio"),
            "piotroski": {
                "score": piotroski.get("score"),
                "max": piotroski.get("max"),
                "verdict": piotroski.get("verdict"),
            },
            "altman": {
                "score": altman.get("score"),
                "zone": altman.get("zone") or altman.get("verdict"),
            },
            "buffett": {
                "passed": buffett.get("passed"),
                "total": buffett.get("total"),
                "verdict": buffett.get("verdict"),
            },
            "dcf": {
                "intrinsic_value_bn": dcf.get("intrinsic_value_bn"),
                "signal": dcf.get("signal"),
                "verdict": dcf.get("verdict"),
            },
            "graham": {
                "fair_value_proxy": graham.get("estimated_fair_value_proxy") or graham.get("graham_number"),
                "upside_pct": graham.get("upside_pct"),
                "verdict": graham.get("verdict"),
            },
        },
        "trends": {
            "revenue": trend_block.get("revenue"),
            "profit": trend_block.get("profit"),
            "margin": trend_block.get("margin"),
            "debt": trend_block.get("debt"),
            "overall_score": trend_block.get("overall_score"),
            "overall_label": trend_block.get("overall_label"),
            "momentum": momentum_block,
        },
        "industry": industry or {},
        "liquidity": liquidity_data or {},
        "bank": _compute_bank_profile(latest, prev),
        "valuation_summary": {
            "score": metrics.get("total_score", {}).get("score") if isinstance(metrics, dict) else None,
            "grade": metrics.get("total_score", {}).get("grade") if isinstance(metrics, dict) else None,
            "summary": metrics.get("total_score", {}).get("summary") if isinstance(metrics, dict) else None,
        },
        "series": {
            "annual": [
                {
                    "year": row.get("year"),
                    "revenue": _safe_float(row.get("revenue")),
                    "gross_profit": _safe_float(row.get("gross_profit")),
                    "ebit": _safe_float(row.get("ebit")),
                    "net_income": _safe_float(row.get("net_income")),
                    "equity": _safe_float(row.get("equity")),
                    "total_assets": _safe_float(row.get("total_assets")),
                    "current_ratio": _safe_float(row.get("current_ratio")),
                    "debt_to_equity_ratio": _safe_float(row.get("debt_to_equity_ratio")),
                    "net_profit_margin": _safe_float(row.get("net_profit_margin")),
                    "total_liabilities": _safe_float(
                        row.get("total_liabilities")
                        if row.get("total_liabilities") is not None
                        else (
                            (row.get("total_assets") - row.get("equity"))
                            if row.get("total_assets") is not None and row.get("equity") is not None
                            else row.get("long_term_debt")
                        )
                    ),
                }
                for row in annual_data
                if isinstance(row, dict)
            ],
            "quarterly": [
                {
                    "period": row.get("period"),
                    "revenue": _safe_float(row.get("revenue")),
                    "gross_profit": _safe_float(row.get("gross_profit")),
                    "ebit": _safe_float(row.get("ebit")),
                    "net_income": _safe_float(row.get("net_income")),
                }
                for row in quarterly_data
                if isinstance(row, dict)
            ],
        },
        "flags": {
            "green": green_flags,
            "red": red_flags,
        },
        "decision_inputs": [
            "Прибыльность и маржи",
            "Ликвидность и рабочий капитал",
            "Долговая нагрузка и покрытие процентов",
            "Качество прибыли (Piotroski / Altman / Buffett)",
            "Тренд выручки и квартальный импульс",
        ],
    }
