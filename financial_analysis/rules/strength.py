"""Financial strength and total scoring rules."""
import math
from financial_analysis.history import value as get


def strength(history):
    metrics = {}
    annual_data = history.annual
    latest = history.latest
    prev = history.previous
    revenue = get(latest, "revenue", 0)
    net_income = get(latest, "net_income", 0)
    equity = get(latest, "equity", 0)
    total_assets = get(latest, "total_assets", 0)
    current_assets = get(latest, "current_assets", 0)
    current_liab = get(latest, "current_liabilities", 0)
    long_term_debt = get(latest, "long_term_debt", 0)
    ebit = get(latest, "ebit", 0)
    interest_exp = get(latest, "interest_expense", 0)
    gross_profit = get(latest, "gross_profit", 0)
    ret_earnings = get(latest, "retained_earnings", 0)
    prev_revenue = get(prev, "revenue", 0)
    prev_net_income = get(prev, "net_income", 0)
    prev_assets = get(prev, "total_assets", 0)
    prev_equity = get(prev, "equity", 0)
    prev_curr_liab = get(prev, "current_liabilities", 0)
    prev_long_debt = get(prev, "long_term_debt", 0)
    # ── PIOTROSKI F-SCORE (0–9) ──────────────────────────
    # Метод Джозефа Пиотроски для оценки финансовой силы
    f_score = 0
    f_details = {}

    # Прибыльность (0–4 балла)
    f1 = 1 if net_income > 0 else 0
    f_details["ROA > 0 (прибыльность)"] = f1
    f_score += f1

    roa = net_income / total_assets if total_assets else 0
    prev_roa = prev_net_income / prev_assets if prev_assets else 0
    f2 = 1 if roa > prev_roa else 0
    f_details["ROA растёт (улучшение)"] = f2
    f_score += f2

    op_cf = ebit  # упрощение: используем EBIT как прокси операционного CF
    f3 = 1 if op_cf > 0 else 0
    f_details["Операционный поток > 0"] = f3
    f_score += f3

    f4 = 1 if (op_cf > net_income) else 0
    f_details["CF > чистой прибыли (качество прибыли)"] = f4
    f_score += f4

    # Leverage/Liquidity (0–3 балла)
    curr_ratio = current_assets / current_liab if current_liab else 0
    prev_curr_ratio = (get(prev, "current_assets", 0) / prev_curr_liab) if prev_curr_liab else 0
    f5 = 1 if curr_ratio > prev_curr_ratio else 0
    f_details["Ликвидность улучшилась"] = f5
    f_score += f5

    leverage = long_term_debt / total_assets if total_assets else 0
    prev_leverage = prev_long_debt / prev_assets if prev_assets else 0
    f6 = 1 if leverage < prev_leverage else 0
    f_details["Долговая нагрузка снизилась"] = f6
    f_score += f6

    # Упрощение: нет доп. эмиссии акций (считаем как рост equity без долгов)
    f7 = 1 if equity > prev_equity else 0
    f_details["Капитал не размывался"] = f7
    f_score += f7

    # Эффективность (0–2 балла)
    gp_margin = gross_profit / revenue if revenue else 0
    prev_gp   = get(prev, "gross_profit", 0)
    prev_rev  = get(prev, "revenue", 0)
    prev_gp_margin = prev_gp / prev_rev if prev_rev else 0
    f8 = 1 if gp_margin > prev_gp_margin else 0
    f_details["Валовая маржа растёт"] = f8
    f_score += f8

    asset_turn = revenue / total_assets if total_assets else 0
    prev_asset_turn = prev_revenue / prev_assets if prev_assets else 0
    f9 = 1 if asset_turn > prev_asset_turn else 0
    f_details["Оборачиваемость активов растёт"] = f9
    f_score += f9

    if f_score >= 7:
        f_verdict = "Сильная компания — высокая вероятность роста"
    elif f_score >= 4:
        f_verdict = "Средняя компания — нейтральные перспективы"
    else:
        f_verdict = "Слабая компания — высокий риск"

    metrics["piotroski_f_score"] = {
        "score": f_score,
        "max": 9,
        "verdict": f_verdict,
        "details": f_details,
    }

    # ── GRAHAM NUMBER ────────────────────────────────────
    # Бен Грэм: справедливая цена = √(22.5 × EPS × BVPS)
    # Используем прокси: EPS ~ net_income/equity, BVPS ~ equity
    # (без данных о кол-ве акций используем относительный показатель)
    if net_income > 0 and equity > 0:
        # Упрощённый Graham: справедливая стоимость компании
        # GV = √(22.5 × NI × BV) — масштаб компании, не цена акции
        graham_value = math.sqrt(22.5 * abs(net_income) * abs(equity))
        graham_ratio = graham_value / total_assets if total_assets else 0
        metrics["graham_number"] = {
            "estimated_fair_value_proxy": round(graham_value, 0),
            "vs_total_assets": round(graham_ratio, 2),
            "interpretation": (
                "Число Грэма — оценка справедливой стоимости бизнеса. "
                f"Если рыночная капитализация ниже {round(graham_value/1e9, 1)} млрд UZS — "
                "акция потенциально недооценена."
            ),
        }

    # ── ALTMAN Z-SCORE ───────────────────────────────────
    # Предсказывает вероятность банкротства
    # Z = 1.2×X1 + 1.4×X2 + 3.3×X3 + 0.6×X4 + 1.0×X5
    if total_assets > 0:
        x1 = (current_assets - current_liab) / total_assets
        x2 = ret_earnings / total_assets if ret_earnings else 0
        x3 = ebit / total_assets
        total_liab = total_assets - equity
        x4 = equity / total_liab if total_liab > 0 else 0
        x5 = revenue / total_assets

        z = 1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + 1.0*x5

        if z > 2.99:
            z_zone = "Безопасная зона — банкротство маловероятно"
        elif z > 1.81:
            z_zone = "Серая зона — есть риски, нужен мониторинг"
        else:
            z_zone = "Опасная зона — высокий риск финансовых проблем"

        metrics["altman_z_score"] = {
            "score": round(z, 2),
            "zone": z_zone,
            "components": {
                "X1_ликвидность": round(x1, 3),
                "X2_накопленная_прибыль": round(x2, 3),
                "X3_прибыльность_активов": round(x3, 3),
                "X4_капитал_vs_долг": round(x4, 3),
                "X5_эффективность": round(x5, 3),
            },
        }

    # ── BUFFETT-КРИТЕРИИ ─────────────────────────────────
    roe = net_income / equity if equity else 0
    debt_to_equity = (long_term_debt) / equity if equity else 0
    net_margin = net_income / revenue if revenue else 0

    # Стабильность прибыли — кол-во лет с положительной прибылью
    profitable_years = sum(
        1 for y in annual_data if (get(y, "net_income") or 0) > 0
    )

    # Рост выручки за 5 лет
    rev_first = get(annual_data[0], "revenue", 0) if annual_data else 0
    rev_last  = get(annual_data[-1], "revenue", 0) if annual_data else 0
    rev_growth_5y = ((rev_last / rev_first) - 1) * 100 if rev_first and rev_first > 0 else 0

    buffett_checks = {
        "ROE > 15%": {"pass": roe > 0.15, "value": f"{roe*100:.1f}%"},
        "Долг/капитал < 0.5": {"pass": debt_to_equity < 0.5, "value": f"{debt_to_equity:.2f}"},
        "Чистая маржа > 10%": {"pass": net_margin > 0.10, "value": f"{net_margin*100:.1f}%"},
        f"Прибыльность {profitable_years}/{len(annual_data)} лет": {
            "pass": profitable_years >= len(annual_data) * 0.8,
            "value": f"{profitable_years} из {len(annual_data)}"
        },
        "Рост выручки 5 лет > 30%": {"pass": rev_growth_5y > 30, "value": f"{rev_growth_5y:.1f}%"},
    }
    buffett_passed = sum(1 for v in buffett_checks.values() if v["pass"])
    metrics["buffett_criteria"] = {
        "passed": buffett_passed,
        "total": len(buffett_checks),
        "checks": buffett_checks,
        "verdict": (
            "Компания соответствует критериям Баффетта" if buffett_passed >= 4
            else "Компания частично соответствует" if buffett_passed >= 2
            else "Компания не соответствует критериям Баффетта"
        ),
    }

    # ── INTEREST COVERAGE RATIO ──────────────────────────
    if interest_exp and interest_exp > 0:
        icr = ebit / interest_exp
        metrics["interest_coverage"] = {
            "ratio": round(icr, 2),
            "verdict": (
                "Отлично — легко платит по долгам" if icr > 5
                else "Нормально — платит по долгам" if icr > 2
                else "Риск — могут быть проблемы с долгами"
            ),
        }
    return metrics


def score(history, computed):
    metrics = dict(computed)
    net_margin = history.net_margin
    rev_growth_5y = history.revenue_growth
    buffett_passed = metrics["buffett_criteria"]["passed"]
    f_score = metrics["piotroski_f_score"]["score"]
    trend_score = metrics["trends"]["overall_score"]
    # ── СВОДНЫЙ СКОРИНГ 0–100 ────────────────────────────
    score = 0

    # Piotroski (0–27 баллов)
    score += f_score * 3

    # Altman Z (0–20 баллов)
    if "altman_z_score" in metrics:
        z = metrics["altman_z_score"]["score"]
        if z > 2.99:   score += 20
        elif z > 1.81: score += 10

    # Buffett (0–20 баллов)
    score += buffett_passed * 4

    # Тренды (0–12 баллов) ← новый блок
    score += trend_score

    # Рост выручки за 5 лет (0–12 баллов)
    if rev_growth_5y > 100: score += 12
    elif rev_growth_5y > 50: score += 8
    elif rev_growth_5y > 20: score += 4

    # Momentum (0–8 баллов)
    if "momentum" in metrics:
        mom_css = metrics["momentum"].get("css", "neutral")
        streak  = metrics["momentum"].get("growth_streak", 0)
        if mom_css == "bullish":   score += 5
        elif mom_css == "neutral": score += 2
        if streak >= 3:  score += 3
        elif streak >= 2: score += 1

    # DCF сигнал (0–9 баллов)
    if "dcf" in metrics:
        dcf_sig = metrics["dcf"].get("signal", "neutral")
        if dcf_sig == "bullish":   score += 9
        elif dcf_sig == "neutral": score += 4

    # Маржа (0–9 баллов)
    if net_margin > 0.20: score += 9
    elif net_margin > 0.10: score += 6
    elif net_margin > 0.05: score += 3

    # Отраслевое сравнение (0–6 баллов)
    # добавляется после detect_industry, пока пропускаем (нет industry в scope)
    # industry_grade добавляется в run_analysis после вызова compute_metrics

    score = min(100, score)

    metrics["total_score"] = {
        "score": score,
        "grade": (
            "A — Отличная компания" if score >= 80
            else "B — Хорошая компания" if score >= 60
            else "C — Средняя компания" if score >= 40
            else "D — Слабая компания"
        ),
    }
    return metrics["total_score"]
