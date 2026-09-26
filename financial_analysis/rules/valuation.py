"""Revenue retracement and legacy valuation estimates."""
import math
from financial_analysis.history import value as get


def fibonacci(history):
    metrics = {}
    annual_data = history.annual
    # ── FIBONACCI RETRACEMENT ────────────────────────────
    # Используем выручку как прокси для ценового движения
    revenues = [get(y, "revenue", 0) for y in annual_data if get(y, "revenue")]
    revenues = [r for r in revenues if r and r > 0]

    if len(revenues) >= 2:
        high = max(revenues)
        low  = min(revenues)
        diff = high - low
        fib_levels = {
            "high":   round(high, 0),
            "low":    round(low, 0),
            "0.236":  round(high - 0.236 * diff, 0),
            "0.382":  round(high - 0.382 * diff, 0),
            "0.500":  round(high - 0.500 * diff, 0),
            "0.618":  round(high - 0.618 * diff, 0),  # золотое сечение
            "0.786":  round(high - 0.786 * diff, 0),
        }
        current_rev = revenues[-1]
        # Определяем зону Фибоначчи для текущей выручки
        if current_rev >= fib_levels["0.236"]:
            fib_zone = "выше 23.6% — сильный восходящий тренд"
        elif current_rev >= fib_levels["0.382"]:
            fib_zone = "зона 23.6–38.2% — здоровая коррекция"
        elif current_rev >= fib_levels["0.500"]:
            fib_zone = "зона 38.2–50% — умеренная коррекция"
        elif current_rev >= fib_levels["0.618"]:
            fib_zone = "зона 50–61.8% — глубокая коррекция (золотое сечение)"
        else:
            fib_zone = "ниже 61.8% — сильный нисходящий тренд"

        metrics["fibonacci"] = {
            "levels_by_revenue": fib_levels,
            "current_revenue": round(current_rev, 0),
            "current_zone": fib_zone,
            "interpretation": (
                "Уровни Фибоначчи показывают ключевые зоны поддержки и сопротивления "
                "на основе исторических максимумов и минимумов выручки компании."
            ),
        }
    return metrics


def valuation(history):
    metrics = {}
    annual_data = history.annual
    latest = history.latest
    net_income = get(latest, "net_income", 0)
    total_assets = get(latest, "total_assets", 0)
    ebit = get(latest, "ebit", 0)
    rev_first = get(annual_data[0], "revenue", 0)
    rev_last = get(latest, "revenue", 0)
    # ── DCF — ОЦЕНКА СПРАВЕДЛИВОЙ СТОИМОСТИ ─────────────
    # Упрощённая двухэтапная модель DCF (без данных о кол-ве акций).
    # Считает справедливую стоимость всего бизнеса в UZS.
    #
    # Этап 1 (5 лет): FCF = EBIT × (1 - налог) — прокси свободного денежного потока.
    # Этап 2 (терминальная стоимость): TV = FCF₅ × (1 + g) / (WACC - g).
    # Discount rate откалиброван под UZ: WACC = 20% (инфляция ~13% + риск-премия).
    # Рост g выводится из исторического тренда выручки, но не более 8%.

    try:
        # Параметры (откалиброваны под frontier market Узбекистана)
        WACC      = 0.20   # ставка дисконтирования: инфляция UZS + премия за риск
        TAX_RATE  = 0.15   # ставка налога на прибыль в Узбекистане
        MAX_G     = 0.08   # максимальный вечный рост (conservative)
        MIN_G     = 0.02   # минимальный вечный рост
        N_YEARS   = 5      # горизонт прогноза

        # Базовый FCF = EBIT × (1 - tax)
        base_fcf = ebit * (1 - TAX_RATE) if ebit > 0 else net_income

        # Темп роста выручки — из тренда, ограничиваем
        # Переводим в годовой % (slope считался как % от среднего за весь период)
        n_years_data = len(annual_data)
        if n_years_data > 1 and rev_first and rev_first > 0:
            cagr = (rev_last / rev_first) ** (1 / (n_years_data - 1)) - 1
        else:
            cagr = 0.05  # дефолтный рост 5%

        # Консервативный прогноз: берём меньшее из CAGR и разумного максимума
        growth_rate = min(max(cagr * 0.7, MIN_G), 0.25)  # не более 25% в год
        terminal_g  = min(max(cagr * 0.3, MIN_G), MAX_G)  # вечный рост скромнее

        if base_fcf > 0:
            # Этап 1: дисконтируем FCF на 5 лет
            pv_fcf = 0.0
            fcf_t  = base_fcf
            fcf_by_year = {}
            for t_year in range(1, N_YEARS + 1):
                fcf_t *= (1 + growth_rate)
                pv_t   = fcf_t / (1 + WACC) ** t_year
                pv_fcf += pv_t
                fcf_by_year[f"год_{t_year}"] = round(fcf_t, 0)

            # Этап 2: терминальная стоимость
            fcf_terminal = fcf_t * (1 + terminal_g)
            tv = fcf_terminal / (WACC - terminal_g)
            pv_tv = tv / (1 + WACC) ** N_YEARS

            # Итоговая справедливая стоимость бизнеса
            intrinsic_value = pv_fcf + pv_tv

            # Сравниваем с балансовой стоимостью активов
            vs_assets = intrinsic_value / total_assets if total_assets else 0

            # Интерпретация
            if vs_assets > 1.5:
                dcf_verdict = "Потенциально сильно недооценён — DCF выше активов в 1.5x+"
                dcf_signal  = "bullish"
            elif vs_assets > 1.0:
                dcf_verdict = "Потенциально недооценён — DCF выше балансовой стоимости"
                dcf_signal  = "bullish"
            elif vs_assets > 0.7:
                dcf_verdict = "Оценён справедливо — DCF близок к балансовой стоимости"
                dcf_signal  = "neutral"
            else:
                dcf_verdict = "Потенциально переоценён или бизнес стагнирует"
                dcf_signal  = "bearish"

            metrics["dcf"] = {
                "intrinsic_value":   round(intrinsic_value, 0),
                "intrinsic_value_bn": round(intrinsic_value / 1e9, 2),
                "pv_fcf_5yr":        round(pv_fcf, 0),
                "terminal_value":    round(pv_tv, 0),
                "assumed_growth_pct": round(growth_rate * 100, 1),
                "terminal_growth_pct": round(terminal_g * 100, 1),
                "wacc_pct":          round(WACC * 100, 1),
                "vs_total_assets":   round(vs_assets, 2),
                "verdict":           dcf_verdict,
                "signal":            dcf_signal,
                "fcf_projection":    fcf_by_year,
                "note": (
                    f"Прогнозный рост {round(growth_rate*100,1)}%/год × 5 лет, "
                    f"затем вечный рост {round(terminal_g*100,1)}%/год. "
                    f"Ставка дисконтирования {round(WACC*100,0):.0f}% (UZ frontier market)."
                ),
            }
        else:
            metrics["dcf"] = {
                "intrinsic_value": 0,
                "verdict": "DCF не применим — компания убыточна (FCF отрицательный)",
                "signal": "bearish",
                "note": "DCF требует положительного операционного потока.",
            }
    except Exception as dcf_err:
        metrics["dcf"] = {
            "verdict": f"Ошибка расчёта DCF: {dcf_err}",
            "signal": "neutral",
        }
    return metrics
