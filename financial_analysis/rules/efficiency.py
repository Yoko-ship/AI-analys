"""Operating efficiency, DuPont, and working-capital rules."""
import math
from financial_analysis.history import value as get


def efficiency(history):
    metrics = {}
    latest = history.latest
    prev = history.previous
    revenue = get(latest, "revenue", 0)
    net_income = get(latest, "net_income", 0)
    equity = get(latest, "equity", 0)
    total_assets = get(latest, "total_assets", 0)
    current_assets = get(latest, "current_assets", 0)
    current_liab = get(latest, "current_liabilities", 0)
    cash = get(latest, "cash", 0)
    inventory = get(latest, "inventory", 0)
    accounts_rec = get(latest, "accounts_receivable", 0)
    curr_ratio = current_assets / current_liab if current_liab else 0
    # ── EFFICIENCY METRICS (NEW) ─────────────────────────
    # Оборачиваемость и эффективность использования активов
    cogs = get(latest, "cogs", 0) or 0
    accounts_pay = get(latest, "accounts_payable", 0) or 0
    prev_inventory = get(prev, "inventory", 0) or 0
    prev_accounts_rec = get(prev, "accounts_receivable", 0) or 0
    prev_accounts_pay = get(prev, "accounts_payable", 0) or 0

    efficiency = {}

    # Inventory Turnover (оборачиваемость запасов)
    avg_inventory = (inventory + prev_inventory) / 2 if prev_inventory else inventory
    if avg_inventory and cogs:
        inv_turnover = cogs / avg_inventory
        inv_days = 365 / inv_turnover if inv_turnover > 0 else 0
        efficiency["inventory_turnover"] = {
            "ratio": round(inv_turnover, 2),
            "days": round(inv_days, 0),
            "verdict": (
                "Отлично — быстрая оборачиваемость" if inv_days < 60
                else "Нормально" if inv_days < 120
                else "Медленно — деньги заморожены в запасах"
            ),
        }

    # Receivable Days (дни дебиторской задолженности)
    avg_receivables = (accounts_rec + prev_accounts_rec) / 2 if prev_accounts_rec else accounts_rec
    if avg_receivables and revenue:
        rec_turnover = revenue / avg_receivables
        rec_days = 365 / rec_turnover if rec_turnover > 0 else 0
        efficiency["receivable_days"] = {
            "ratio": round(rec_turnover, 2),
            "days": round(rec_days, 0),
            "verdict": (
                "Отлично — быстро собирают деньги" if rec_days < 30
                else "Нормально" if rec_days < 60
                else "Медленно — деньги застряли у клиентов"
            ),
        }

    # Payable Days (дни кредиторской задолженности)
    avg_payables = (accounts_pay + prev_accounts_pay) / 2 if prev_accounts_pay else accounts_pay
    if avg_payables and cogs:
        pay_turnover = cogs / avg_payables
        pay_days = 365 / pay_turnover if pay_turnover > 0 else 0
        efficiency["payable_days"] = {
            "ratio": round(pay_turnover, 2),
            "days": round(pay_days, 0),
            "verdict": (
                "Хорошо — используют деньги поставщиков" if pay_days > 45
                else "Нормально" if pay_days > 20
                else "Платят слишком быстро"
            ),
        }

    # Cash Conversion Cycle (цикл конвертации денег)
    inv_days_val = efficiency.get("inventory_turnover", {}).get("days", 0) or 0
    rec_days_val = efficiency.get("receivable_days", {}).get("days", 0) or 0
    pay_days_val = efficiency.get("payable_days", {}).get("days", 0) or 0
    if inv_days_val or rec_days_val:
        ccc = inv_days_val + rec_days_val - pay_days_val
        efficiency["cash_conversion_cycle"] = {
            "days": round(ccc, 0),
            "verdict": (
                "Отрицательный CCC — бизнес генерирует кеш" if ccc < 0
                else "Отлично" if ccc < 30
                else "Нормально" if ccc < 60
                else "Долгий цикл — много денег заморожено"
            ),
            "interpretation": (
                f"От покупки товара до получения денег: {round(ccc, 0)} дней"
            ),
        }

    if efficiency:
        metrics["efficiency"] = efficiency

    # ── DUPONT ANALYSIS (ROE Decomposition) ──────────────
    # ROE = Net Margin × Asset Turnover × Equity Multiplier
    if revenue and total_assets and equity and equity > 0:
        net_margin_pct = (net_income / revenue) * 100 if revenue else 0
        asset_turnover = revenue / total_assets
        equity_multiplier = total_assets / equity
        roe_dupont = (net_income / revenue) * (revenue / total_assets) * (total_assets / equity) * 100

        # Определяем драйверы ROE
        drivers = []
        if net_margin_pct > 10:
            drivers.append("высокая маржа")
        elif net_margin_pct < 3:
            drivers.append("низкая маржа тянет вниз")

        if asset_turnover > 1.5:
            drivers.append("эффективное использование активов")
        elif asset_turnover < 0.5:
            drivers.append("активы работают неэффективно")

        if equity_multiplier > 3:
            drivers.append("высокий leverage (риск)")
        elif equity_multiplier < 1.5:
            drivers.append("консервативная структура капитала")

        metrics["dupont_analysis"] = {
            "roe_pct": round(roe_dupont, 2),
            "components": {
                "net_margin_pct": round(net_margin_pct, 2),
                "asset_turnover": round(asset_turnover, 3),
                "equity_multiplier": round(equity_multiplier, 2),
            },
            "drivers": drivers if drivers else ["сбалансированный профиль"],
            "interpretation": (
                f"ROE {round(roe_dupont, 1)}% = "
                f"маржа {round(net_margin_pct, 1)}% × "
                f"оборачиваемость {round(asset_turnover, 2)}x × "
                f"leverage {round(equity_multiplier, 1)}x"
            ),
        }

    # ── WORKING CAPITAL ANALYSIS ─────────────────────────
    working_capital = current_assets - current_liab
    prev_working_cap = get(prev, "current_assets", 0) - get(prev, "current_liabilities", 0)

    wc_change = working_capital - prev_working_cap if prev_working_cap else 0
    wc_to_revenue = (working_capital / revenue * 100) if revenue else 0

    # Quick Ratio (без запасов)
    quick_assets = current_assets - inventory
    quick_ratio = quick_assets / current_liab if current_liab else 0

    # Cash Ratio (только деньги)
    cash_ratio = cash / current_liab if current_liab else 0

    metrics["working_capital"] = {
        "amount": round(working_capital, 0),
        "change_yoy": round(wc_change, 0),
        "pct_of_revenue": round(wc_to_revenue, 1),
        "current_ratio": round(curr_ratio, 2),
        "quick_ratio": round(quick_ratio, 2),
        "cash_ratio": round(cash_ratio, 2),
        "verdict": (
            "Отлично — избыток ликвидности" if curr_ratio > 2.5 and quick_ratio > 1.5
            else "Хорошо — здоровая ликвидность" if curr_ratio > 1.5 and quick_ratio > 1.0
            else "Нормально — достаточная ликвидность" if curr_ratio > 1.0
            else "Риск — может не хватить на текущие платежи"
        ),
        "change_verdict": (
            "Рабочий капитал растёт" if wc_change > 0
            else "Рабочий капитал снижается" if wc_change < 0
            else "Без изменений"
        ),
    }
    return metrics
