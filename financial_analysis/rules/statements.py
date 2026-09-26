"""Horizontal and vertical statement comparisons."""
import math
from financial_analysis.history import value as get


def statements(history):
    metrics = {}
    latest = history.latest
    prev = history.previous
    revenue = get(latest, "revenue", 0)
    net_income = get(latest, "net_income", 0)
    equity = get(latest, "equity", 0)
    total_assets = get(latest, "total_assets", 0)
    ebit = get(latest, "ebit", 0)
    gross_profit = get(latest, "gross_profit", 0)
    # ── HORIZONTAL ANALYSIS (Горизонтальный анализ) ──────
    # Сравнение показателей текущего года с предыдущим (YoY изменения)
    horizontal = {}

    def yoy_change(current, previous):
        if current and previous and previous != 0:
            change = current - previous
            pct = (change / abs(previous)) * 100
            return {"current": round(current, 0), "previous": round(previous, 0),
                    "change": round(change, 0), "pct": round(pct, 1)}
        return None

    # Ключевые статьи для горизонтального анализа
    h_items = [
        ("revenue", "Выручка"),
        ("gross_profit", "Валовая прибыль"),
        ("net_income", "Чистая прибыль"),
        ("total_assets", "Всего активов"),
        ("equity", "Собственный капитал"),
        ("current_assets", "Оборотные активы"),
        ("current_liabilities", "Краткосрочные обязательства"),
        ("long_term_debt", "Долгосрочный долг"),
        ("cash", "Денежные средства"),
        ("inventory", "Запасы"),
    ]

    for key, label in h_items:
        curr_val = get(latest, key, 0)
        prev_val = get(prev, key, 0)
        change = yoy_change(curr_val, prev_val)
        if change:
            horizontal[key] = {"label": label, **change}

    if horizontal:
        # Определяем общий тренд горизонтального анализа
        growing = sum(1 for v in horizontal.values() if v.get("pct", 0) > 5)
        declining = sum(1 for v in horizontal.values() if v.get("pct", 0) < -5)

        metrics["horizontal_analysis"] = {
            "items": horizontal,
            "summary": {
                "growing_count": growing,
                "declining_count": declining,
                "stable_count": len(horizontal) - growing - declining,
            },
            "verdict": (
                "Позитивная динамика — большинство показателей растут" if growing > declining + 2
                else "Негативная динамика — большинство показателей падают" if declining > growing + 2
                else "Смешанная динамика — нет явного тренда"
            ),
        }

    # ── VERTICAL ANALYSIS (Вертикальный анализ) ───────────
    # Структура баланса: каждая статья как % от общих активов
    # Структура доходов: каждая статья как % от выручки
    vertical = {}

    # Баланс: % от total_assets
    if total_assets > 0:
        balance_structure = {}
        balance_items = [
            ("cash", "Денежные средства"),
            ("accounts_receivable", "Дебиторская задолженность"),
            ("inventory", "Запасы"),
            ("current_assets", "Оборотные активы"),
            ("long_term_debt", "Долгосрочный долг"),
            ("equity", "Собственный капитал"),
        ]
        for key, label in balance_items:
            val = get(latest, key, 0) or 0
            if val:
                balance_structure[key] = {
                    "label": label,
                    "value": round(val, 0),
                    "pct_of_assets": round((val / total_assets) * 100, 1),
                }

        # Добавляем обязательства (total_assets - equity)
        total_liab = total_assets - equity
        if total_liab > 0:
            balance_structure["total_liabilities"] = {
                "label": "Всего обязательств",
                "value": round(total_liab, 0),
                "pct_of_assets": round((total_liab / total_assets) * 100, 1),
            }

        vertical["balance_sheet"] = {
            "base": "total_assets",
            "base_value": round(total_assets, 0),
            "items": balance_structure,
            "equity_ratio": round((equity / total_assets) * 100, 1) if equity else 0,
            "debt_ratio": round((total_liab / total_assets) * 100, 1) if total_liab else 0,
        }

    # Отчет о прибылях: % от выручки
    if revenue > 0:
        income_structure = {}
        income_items = [
            ("gross_profit", "Валовая прибыль"),
            ("ebit", "Операционная прибыль (EBIT)"),
            ("net_income", "Чистая прибыль"),
            ("interest_expense", "Процентные расходы"),
        ]
        for key, label in income_items:
            val = get(latest, key, 0) or 0
            if val:
                income_structure[key] = {
                    "label": label,
                    "value": round(val, 0),
                    "pct_of_revenue": round((val / revenue) * 100, 1),
                }

        # Расчет COGS если есть валовая прибыль
        if gross_profit:
            cogs_calc = revenue - gross_profit
            income_structure["cogs"] = {
                "label": "Себестоимость",
                "value": round(cogs_calc, 0),
                "pct_of_revenue": round((cogs_calc / revenue) * 100, 1),
            }

        vertical["income_statement"] = {
            "base": "revenue",
            "base_value": round(revenue, 0),
            "items": income_structure,
            "gross_margin_pct": round((gross_profit / revenue) * 100, 1) if gross_profit else 0,
            "operating_margin_pct": round((ebit / revenue) * 100, 1) if ebit else 0,
            "net_margin_pct": round((net_income / revenue) * 100, 1),
        }

    if vertical:
        metrics["vertical_analysis"] = vertical
    return metrics
