"""Annual trends and quarterly momentum rules."""
import math
from financial_analysis.history import value as get


def trends(history):
    metrics = {}
    annual_data = history.annual
    # ── TREND ANALYSIS: SLOPE / ACCELERATION / CONSISTENCY ─
    # Все три метода считаются из временного ряда без внешних библиотек.

    def linear_slope(values: list) -> float:
        """
        Наклон линии тренда методом наименьших квадратов (OLS).
        Нормализован: slope / mean → относительный прирост за период.
        Положительный = рост, отрицательный = падение.
        """
        n = len(values)
        if n < 2:
            return 0.0
        xs = list(range(n))
        mx = sum(xs) / n
        my = sum(values) / n
        num   = sum((x - mx) * (y - my) for x, y in zip(xs, values))
        denom = sum((x - mx) ** 2 for x in xs)
        if denom == 0 or my == 0:
            return 0.0
        return round(num / denom / abs(my) * 100, 2)  # % за период

    def acceleration(values: list) -> float:
        """
        Ускорение роста: сравниваем среднегодовой рост первой
        и второй половины периода.
        > 0 — рост ускоряется, < 0 — замедляется.
        """
        n = len(values)
        if n < 4:
            return 0.0
        mid = n // 2
        first_half  = values[:mid]
        second_half = values[mid:]

        def avg_growth(seq):
            rates = []
            for i in range(1, len(seq)):
                if seq[i-1] and seq[i-1] != 0:
                    rates.append((seq[i] - seq[i-1]) / abs(seq[i-1]) * 100)
            return sum(rates) / len(rates) if rates else 0

        return round(avg_growth(second_half) - avg_growth(first_half), 2)

    def consistency(values: list) -> float:
        """
        Стабильность роста: 100 - коэффициент вариации темпов роста.
        100 = идеально стабильный рост, 0 = хаотичный.
        """
        n = len(values)
        if n < 3:
            return 50.0
        rates = []
        for i in range(1, n):
            if values[i-1] and values[i-1] != 0:
                rates.append((values[i] - values[i-1]) / abs(values[i-1]) * 100)
        if not rates:
            return 50.0
        mean = sum(rates) / len(rates)
        if mean == 0:
            return 50.0
        std  = (sum((r - mean) ** 2 for r in rates) / len(rates)) ** 0.5
        cv   = std / abs(mean) * 100  # коэффициент вариации
        return round(max(0, min(100, 100 - cv)), 1)

    def trend_label(slope: float, accel: float, consist: float) -> str:
        """Человекочитаемое описание тренда."""
        if slope > 10:
            direction = "Сильный рост"
        elif slope > 3:
            direction = "Умеренный рост"
        elif slope > -3:
            direction = "Стагнация"
        elif slope > -10:
            direction = "Умеренное падение"
        else:
            direction = "Сильное падение"

        if accel > 5:
            momentum = "ускоряется"
        elif accel > -5:
            momentum = "стабильный темп"
        else:
            momentum = "замедляется"

        if consist >= 70:
            stability = "стабильно"
        elif consist >= 40:
            stability = "умеренно предсказуемо"
        else:
            stability = "нестабильно/скачки"

        return f"{direction} ({momentum}, {stability})"

    # Временные ряды для анализа
    rev_series    = [get(y, "revenue", 0) or 0 for y in annual_data]
    ni_series     = [get(y, "net_income", 0) or 0 for y in annual_data]
    margin_series = [
        round((get(y, "net_income", 0) or 0) / (get(y, "revenue", 1) or 1) * 100, 2)
        for y in annual_data
    ]
    equity_series = [get(y, "equity", 0) or 0 for y in annual_data]
    debt_series   = [get(y, "long_term_debt", 0) or 0 for y in annual_data]

    trend_revenue = {
        "slope":       linear_slope(rev_series),
        "acceleration": acceleration(rev_series),
        "consistency":  consistency(rev_series),
        "label":        trend_label(
                            linear_slope(rev_series),
                            acceleration(rev_series),
                            consistency(rev_series)
                        ),
        "values_by_year": {
            str(annual_data[i].get("year", i)): round(rev_series[i] / 1e6, 1)
            for i in range(len(annual_data)) if rev_series[i]
        },
    }
    trend_profit = {
        "slope":        linear_slope(ni_series),
        "acceleration": acceleration(ni_series),
        "consistency":  consistency(ni_series),
        "label":        trend_label(
                            linear_slope(ni_series),
                            acceleration(ni_series),
                            consistency(ni_series)
                        ),
        "profitable_years": sum(1 for v in ni_series if v > 0),
        "total_years":      len(ni_series),
    }
    trend_margin = {
        "slope":        linear_slope(margin_series),
        "acceleration": acceleration(margin_series),
        "consistency":  consistency(margin_series),
        "label":        trend_label(
                            linear_slope(margin_series),
                            acceleration(margin_series),
                            consistency(margin_series)
                        ),
        "current_pct":  round(margin_series[-1], 2) if margin_series else 0,
    }
    trend_debt = {
        "slope":        linear_slope(debt_series),
        "direction":    "снижается" if linear_slope(debt_series) < -2 else
                        "растёт"    if linear_slope(debt_series) > 2  else "стабильно",
        "acceleration": acceleration(debt_series),
    }

    # Сводный тренд-скоринг (влияет на итоговый скоринг)
    trend_score = 0
    if trend_revenue["slope"] > 10:  trend_score += 3
    elif trend_revenue["slope"] > 3: trend_score += 1
    if trend_revenue["acceleration"] > 3: trend_score += 2
    if trend_revenue["consistency"] > 70: trend_score += 2
    if trend_profit["slope"] > 5:    trend_score += 2
    if trend_margin["slope"] > 0:    trend_score += 1
    if trend_debt["slope"] < -2:     trend_score += 2  # долг снижается — хорошо
    trend_score = min(12, trend_score)

    metrics["trends"] = {
        "revenue":  trend_revenue,
        "profit":   trend_profit,
        "margin":   trend_margin,
        "debt":     trend_debt,
        "overall_score": trend_score,
        "overall_label": (
            "Позитивный" if trend_score >= 8
            else "Нейтральный" if trend_score >= 4
            else "Негативный"
        ),
    }
    return metrics


def momentum(history):
    metrics = {}
    quarterly_data = history.quarterly
    # ── MOMENTUM-АНАЛИЗ (квартальные данные) ────────────
    # Три горизонта: 3 мес (последний квартал), 6 мес (2 квартала), 12 мес (4 квартала).
    # Считаем изменение выручки, прибыли и тренд ускорения между горизонтами.
    # Сигналы: BULLISH / NEUTRAL / BEARISH для каждого горизонта.

    def safe_get_q(d, key):
        v = d.get(key)
        return float(v) if v and str(v) not in ("None", "nan", "0") else None

    def pct_change(new_val, old_val):
        if old_val and old_val != 0 and new_val is not None:
            return round((new_val - old_val) / abs(old_val) * 100, 2)
        return None

    def momentum_signal(pct):
        """Сигнал по одному показателю."""
        if pct is None:    return "нет данных"
        if pct > 15:       return "STRONG_UP"
        if pct > 5:        return "UP"
        if pct > -5:       return "FLAT"
        if pct > -15:      return "DOWN"
        return "STRONG_DOWN"

    mom = {}

    if len(quarterly_data) >= 2:
        # Берём последние 8 кварталов (2 года максимум)
        q = quarterly_data[-8:]
        n = len(q)

        # Текущий квартал и предыдущие
        q_now  = q[-1]    if n >= 1 else {}
        q_1ago = q[-2]    if n >= 2 else {}
        q_3ago = q[-4]    if n >= 4 else {}
        q_5ago = q[-5]    if n >= 5 else {}  # ~12 мес назад (5 кварталов = 15 мес ≈ год)

        # ── 3-месячный (последний квартал vs предыдущий) ──
        rev_3m  = pct_change(safe_get_q(q_now, "revenue"), safe_get_q(q_1ago, "revenue"))
        ni_3m   = pct_change(safe_get_q(q_now, "net_income"), safe_get_q(q_1ago, "net_income"))
        mom["3m"] = {
            "revenue_pct":    rev_3m,
            "net_income_pct": ni_3m,
            "signal":         momentum_signal(rev_3m),
            "period":         f"{q_1ago.get('period','?')} → {q_now.get('period','?')}",
        }

        # ── 6-месячный (2 квартала назад vs 2 квартала до) ──
        if n >= 4:
            q_2ago = q[-3] if n >= 3 else {}
            q_4ago = q[-5] if n >= 5 else {}
            rev_6m  = pct_change(
                safe_get_q(q_now, "revenue"),
                safe_get_q(q_3ago, "revenue")
            )
            ni_6m   = pct_change(
                safe_get_q(q_now, "net_income"),
                safe_get_q(q_3ago, "net_income")
            )
            mom["6m"] = {
                "revenue_pct":    rev_6m,
                "net_income_pct": ni_6m,
                "signal":         momentum_signal(rev_6m),
                "period":         f"{q_3ago.get('period','?')} → {q_now.get('period','?')}",
            }

        # ── 12-месячный (год назад vs сейчас) ──
        if n >= 5:
            rev_12m = pct_change(
                safe_get_q(q_now, "revenue"),
                safe_get_q(q_5ago, "revenue")
            )
            ni_12m  = pct_change(
                safe_get_q(q_now, "net_income"),
                safe_get_q(q_5ago, "net_income")
            )
            mom["12m"] = {
                "revenue_pct":    rev_12m,
                "net_income_pct": ni_12m,
                "signal":         momentum_signal(rev_12m),
                "period":         f"{q_5ago.get('period','?')} → {q_now.get('period','?')}",
            }

        # ── Acceleration: ускоряется ли рост? ──
        # Сравниваем 3m-рост с 6m-ростом
        accel_signal = "нет данных"
        accel_desc   = ""
        if rev_3m is not None and "6m" in mom and mom["6m"]["revenue_pct"] is not None:
            half_6m = mom["6m"]["revenue_pct"] / 2  # нормируем к одному кварталу
            if rev_3m > half_6m + 3:
                accel_signal = "УСКОРЕНИЕ"
                accel_desc   = f"Последний квартал (+{rev_3m:.1f}%) быстрее среднего за полгода (+{half_6m:.1f}%)"
            elif rev_3m < half_6m - 3:
                accel_signal = "ЗАМЕДЛЕНИЕ"
                accel_desc   = f"Последний квартал (+{rev_3m:.1f}%) медленнее среднего за полгода (+{half_6m:.1f}%)"
            else:
                accel_signal = "СТАБИЛЬНО"
                accel_desc   = f"Темп роста стабилен: {rev_3m:.1f}% (кв) vs {half_6m:.1f}% (норм. полгода)"

        # ── Consecutive growth streaks ──
        # Сколько кварталов подряд растёт выручка?
        growth_streak = 0
        decline_streak = 0
        for i in range(len(q)-1, 0, -1):
            curr_rev = safe_get_q(q[i],   "revenue")
            prev_rev = safe_get_q(q[i-1], "revenue")
            if curr_rev and prev_rev:
                if curr_rev > prev_rev:
                    if decline_streak == 0:
                        growth_streak += 1
                    else:
                        break
                else:
                    if growth_streak == 0:
                        decline_streak += 1
                    else:
                        break
            else:
                break

        # ── Общий momentum-сигнал ──
        signals = [v.get("signal","") for v in mom.values()]
        bullish  = sum(1 for s in signals if "UP" in s)
        bearish  = sum(1 for s in signals if "DOWN" in s)
        if bullish >= 2:
            overall_momentum = "БЫЧИЙ — рост на нескольких горизонтах"
            mom_css = "bullish"
        elif bearish >= 2:
            overall_momentum = "МЕДВЕЖИЙ — падение на нескольких горизонтах"
            mom_css = "bearish"
        else:
            overall_momentum = "НЕЙТРАЛЬНЫЙ — смешанные сигналы"
            mom_css = "neutral"

        metrics["momentum"] = {
            "horizons":        mom,
            "acceleration":    accel_signal,
            "accel_desc":      accel_desc,
            "growth_streak":   growth_streak,
            "decline_streak":  decline_streak,
            "overall":         overall_momentum,
            "css":             mom_css,
            "quarters_used":   n,
            "summary": (
                f"Рост выручки за последний квартал: "
                f"{rev_3m:+.1f}%" if rev_3m is not None else "нет данных"
            ),
        }
    else:
        metrics["momentum"] = {
            "overall": "НЕЙТРАЛЬНЫЙ — недостаточно квартальных данных",
            "css": "neutral",
            "horizons": {},
        }
    return metrics
