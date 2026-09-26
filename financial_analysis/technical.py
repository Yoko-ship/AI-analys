"""Calculate technical indicators from supplied price history."""
from __future__ import annotations

import math


def compute_technical_indicators(price_history: list) -> dict:
    """
    Вычисляет технические индикаторы из истории цен.
    Использует реальные рыночные данные из OpenInfo.

    Args:
        price_history: список dict с ключами date, open, high, low, close, trading_volume

    Returns:
        dict с RSI, MACD, уровнями Фибоначчи, объёмным анализом
    """
    if not price_history or len(price_history) < 5:
        return {"status": "insufficient_data", "message": "Нужно минимум 5 точек данных"}

    def safe_float(v):
        if v is None:
            return None
        try:
            val = float(v)
            return val if not math.isnan(val) else None
        except (TypeError, ValueError):
            return None

    # Очищаем данные
    points = []
    for p in price_history:
        close = safe_float(p.get("close"))
        if close is not None and close > 0:
            points.append({
                "date": p.get("date"),
                "open": safe_float(p.get("open")),
                "high": safe_float(p.get("high")),
                "low": safe_float(p.get("low")),
                "close": close,
                "volume": safe_float(p.get("trading_volume")) or 0,
            })

    if len(points) < 5:
        return {"status": "insufficient_data", "message": "Недостаточно валидных данных"}

    # Сортируем по дате
    points = sorted(points, key=lambda x: str(x.get("date") or ""))
    closes = [p["close"] for p in points]
    volumes = [p["volume"] for p in points]

    indicators = {"status": "ok", "data_points": len(points)}

    # ── RSI (Relative Strength Index) ────────────────────
    # RSI = 100 - (100 / (1 + RS))
    # RS = Average Gain / Average Loss за период (обычно 14 дней)
    period = min(14, len(closes) - 1)
    if period >= 5:
        gains = []
        losses = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        # Используем последние N периодов
        recent_gains = gains[-period:]
        recent_losses = losses[-period:]

        avg_gain = sum(recent_gains) / len(recent_gains) if recent_gains else 0
        avg_loss = sum(recent_losses) / len(recent_losses) if recent_losses else 0

        if avg_loss == 0:
            rsi = 100 if avg_gain > 0 else 50
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        if rsi >= 70:
            rsi_signal = "ПЕРЕКУПЛЕННОСТЬ — возможна коррекция вниз"
            rsi_css = "bearish"
        elif rsi <= 30:
            rsi_signal = "ПЕРЕПРОДАННОСТЬ — возможен отскок вверх"
            rsi_css = "bullish"
        elif rsi >= 60:
            rsi_signal = "Бычий тренд, но приближается к перекупленности"
            rsi_css = "neutral"
        elif rsi <= 40:
            rsi_signal = "Медвежий тренд, но приближается к перепроданности"
            rsi_css = "neutral"
        else:
            rsi_signal = "Нейтральная зона"
            rsi_css = "neutral"

        indicators["rsi"] = {
            "value": round(rsi, 1),
            "period": period,
            "signal": rsi_signal,
            "css": rsi_css,
        }

    # ── PRICE FIBONACCI LEVELS (на основе реальных цен) ──
    highs = [p["high"] for p in points if p["high"]]
    lows = [p["low"] for p in points if p["low"]]

    if highs and lows:
        swing_high = max(highs)
        swing_low = min(lows)
        price_range = swing_high - swing_low

        if price_range > 0:
            current_price = closes[-1]

            fib_levels = {
                "0.0": round(swing_high, 2),
                "23.6": round(swing_high - price_range * 0.236, 2),
                "38.2": round(swing_high - price_range * 0.382, 2),
                "50.0": round(swing_high - price_range * 0.5, 2),
                "61.8": round(swing_high - price_range * 0.618, 2),
                "78.6": round(swing_high - price_range * 0.786, 2),
                "100.0": round(swing_low, 2),
            }

            # Определяем текущую зону
            if current_price >= fib_levels["23.6"]:
                zone = "выше 23.6% — сильный бычий тренд"
                zone_css = "bullish"
            elif current_price >= fib_levels["38.2"]:
                zone = "23.6–38.2% — здоровая коррекция"
                zone_css = "neutral"
            elif current_price >= fib_levels["50.0"]:
                zone = "38.2–50% — умеренная коррекция"
                zone_css = "neutral"
            elif current_price >= fib_levels["61.8"]:
                zone = "50–61.8% — глубокая коррекция (золотое сечение)"
                zone_css = "bearish"
            else:
                zone = "ниже 61.8% — сильный медвежий тренд"
                zone_css = "bearish"

            # Ближайшие уровни
            support_levels = [
                (level, price) for level, price in fib_levels.items()
                if price < current_price
            ]
            resistance_levels = [
                (level, price) for level, price in fib_levels.items()
                if price > current_price
            ]

            nearest_support = max(support_levels, key=lambda x: x[1]) if support_levels else None
            nearest_resistance = min(resistance_levels, key=lambda x: x[1]) if resistance_levels else None

            indicators["fibonacci_price"] = {
                "swing_high": round(swing_high, 2),
                "swing_low": round(swing_low, 2),
                "current_price": round(current_price, 2),
                "levels": fib_levels,
                "current_zone": zone,
                "css": zone_css,
                "nearest_support": {
                    "level": nearest_support[0],
                    "price": nearest_support[1],
                } if nearest_support else None,
                "nearest_resistance": {
                    "level": nearest_resistance[0],
                    "price": nearest_resistance[1],
                } if nearest_resistance else None,
            }

    # ── PRICE MOMENTUM ───────────────────────────────────
    # Изменение цены за разные периоды
    if len(closes) >= 2:
        price_changes = {}

        # 1 день
        price_changes["1d"] = round((closes[-1] / closes[-2] - 1) * 100, 2)

        # 1 неделя (5 торговых дней)
        if len(closes) >= 6:
            price_changes["1w"] = round((closes[-1] / closes[-6] - 1) * 100, 2)

        # 1 месяц (20 торговых дней)
        if len(closes) >= 21:
            price_changes["1m"] = round((closes[-1] / closes[-21] - 1) * 100, 2)

        # За весь период
        price_changes["total"] = round((closes[-1] / closes[0] - 1) * 100, 2)

        # Определяем тренд
        total_change = price_changes["total"]
        if total_change > 15:
            trend = "Сильный рост"
            trend_css = "bullish"
        elif total_change > 5:
            trend = "Умеренный рост"
            trend_css = "bullish"
        elif total_change > -5:
            trend = "Боковик"
            trend_css = "neutral"
        elif total_change > -15:
            trend = "Умеренное падение"
            trend_css = "bearish"
        else:
            trend = "Сильное падение"
            trend_css = "bearish"

        indicators["price_momentum"] = {
            "changes": price_changes,
            "trend": trend,
            "css": trend_css,
            "start_price": round(closes[0], 2),
            "end_price": round(closes[-1], 2),
        }

    # ── VOLUME ANALYSIS ──────────────────────────────────
    valid_volumes = [v for v in volumes if v and v > 0]
    if len(valid_volumes) >= 5:
        avg_volume = sum(valid_volumes) / len(valid_volumes)
        recent_avg = sum(valid_volumes[-5:]) / min(5, len(valid_volumes))
        latest_volume = valid_volumes[-1] if valid_volumes else 0

        # Volume trend
        if recent_avg > avg_volume * 1.5:
            vol_signal = "Объёмы растут — повышенный интерес"
            vol_css = "bullish"
        elif recent_avg < avg_volume * 0.5:
            vol_signal = "Объёмы падают — снижение интереса"
            vol_css = "bearish"
        else:
            vol_signal = "Объёмы стабильны"
            vol_css = "neutral"

        # Volume-price divergence
        price_up = closes[-1] > closes[0] if len(closes) >= 2 else False
        vol_up = recent_avg > avg_volume

        if price_up and not vol_up:
            divergence = "Цена растёт на низких объёмах — слабый рост"
        elif not price_up and vol_up:
            divergence = "Цена падает на высоких объёмах — сильное давление продавцов"
        elif price_up and vol_up:
            divergence = "Цена и объёмы растут — здоровый бычий тренд"
        else:
            divergence = "Цена и объёмы падают — истощение продавцов"

        indicators["volume_analysis"] = {
            "avg_volume": round(avg_volume, 0),
            "recent_avg": round(recent_avg, 0),
            "latest": round(latest_volume, 0),
            "signal": vol_signal,
            "css": vol_css,
            "divergence": divergence,
        }

    # ── VOLATILITY ───────────────────────────────────────
    if len(closes) >= 10:
        # Standard deviation of daily returns
        returns = [(closes[i] / closes[i-1] - 1) for i in range(1, len(closes))]
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        daily_volatility = variance ** 0.5
        annual_volatility = daily_volatility * (252 ** 0.5)  # annualized

        if annual_volatility > 0.5:
            vol_level = "Очень высокая волатильность"
            vol_css = "bearish"
        elif annual_volatility > 0.3:
            vol_level = "Высокая волатильность"
            vol_css = "neutral"
        elif annual_volatility > 0.15:
            vol_level = "Умеренная волатильность"
            vol_css = "neutral"
        else:
            vol_level = "Низкая волатильность"
            vol_css = "bullish"

        indicators["volatility"] = {
            "daily_pct": round(daily_volatility * 100, 2),
            "annual_pct": round(annual_volatility * 100, 1),
            "level": vol_level,
            "css": vol_css,
        }

    # ── SUMMARY SIGNAL ───────────────────────────────────
    bullish_signals = 0
    bearish_signals = 0
    neutral_signals = 0

    for key in ["rsi", "fibonacci_price", "price_momentum", "volume_analysis", "volatility"]:
        if key in indicators:
            css = indicators[key].get("css", "neutral")
            if css == "bullish":
                bullish_signals += 1
            elif css == "bearish":
                bearish_signals += 1
            else:
                neutral_signals += 1

    if bullish_signals >= 3:
        overall = "БЫЧИЙ — большинство индикаторов указывают на рост"
        overall_css = "bullish"
    elif bearish_signals >= 3:
        overall = "МЕДВЕЖИЙ — большинство индикаторов указывают на падение"
        overall_css = "bearish"
    else:
        overall = "НЕЙТРАЛЬНЫЙ — смешанные сигналы"
        overall_css = "neutral"

    indicators["summary"] = {
        "bullish_count": bullish_signals,
        "bearish_count": bearish_signals,
        "neutral_count": neutral_signals,
        "overall": overall,
        "css": overall_css,
    }

    return indicators
