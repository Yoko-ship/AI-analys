"""Reproducible, no-look-ahead technical strategy diagnostics.

One disclosed SMA(20) crossover rule is tested instead of searching parameters
until an attractive historical result appears. A signal formed at a session
close trades only on the following available session, with fee and slippage.
"""
from __future__ import annotations

from math import sqrt
from statistics import mean, pstdev
from typing import Any


MODEL_VERSION = "sma20-crossover-v1"


def _num(value: Any) -> float | None:
    try:
        value = float(value)
        return value if value == value else None
    except (TypeError, ValueError):
        return None


def _sma(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        if index >= window - 1:
            out[index] = running / window
    return out


def run_sma20_backtest(points: list[dict[str, Any]], *, fee_bps: float = 15,
                       slippage_bps: float = 20) -> dict[str, Any]:
    """Test a long-only SMA(20) rule from confirmed daily sessions."""
    rows = []
    for point in points or []:
        close = _num(point.get("close_price", point.get("close")))
        stamp = str(point.get("trade_date", point.get("date")) or "")
        if close is not None and close > 0 and stamp:
            rows.append({"date": stamp[:10], "close": close,
                         "trade_count": _num(point.get("trade_count")) or 0})
    rows.sort(key=lambda row: row["date"])
    if len(rows) < 100:
        return {"status": "NO_DATA", "model_version": MODEL_VERSION,
                "reason": "At least 100 confirmed trading sessions are required.",
                "observations": len(rows)}
    if sum(row["trade_count"] for row in rows[-100:]) <= 0:
        return {"status": "NO_DATA", "model_version": MODEL_VERSION,
                "reason": "Trade-count evidence is insufficient for a tradable technical rule.",
                "observations": len(rows)}
    closes, sma20 = [row["close"] for row in rows], None
    sma20 = _sma(closes, 20)
    fee, slip = max(0.0, float(fee_bps)) / 10_000, max(0.0, float(slippage_bps)) / 10_000
    cash, shares, entry_cost, pending = 1.0, 0.0, None, None
    trades: list[dict[str, Any]] = []
    equity: list[float] = []
    for index, row in enumerate(rows):
        # An order queued by yesterday's completed close executes now.  It is
        # deliberately handled before today's value is recorded, so neither the
        # signal session nor its closing price can benefit from a future fill.
        if pending == "buy" and shares == 0:
            execution = row["close"] * (1 + slip)
            shares, cash, entry_cost = cash * (1 - fee) / execution, 0.0, execution
            trades.append({"side": "buy", "signal_date": rows[index - 1]["date"], "execution_date": row["date"], "price": execution})
        elif pending == "sell" and shares > 0:
            execution = row["close"] * (1 - slip)
            cash = shares * execution * (1 - fee)
            ret = (execution / entry_cost - 1) * 100 if entry_cost else None
            trades.append({"side": "sell", "signal_date": rows[index - 1]["date"], "execution_date": row["date"], "price": execution, "return_pct": ret})
            shares, entry_cost = 0.0, None
        pending = None
        if index >= 2 and index + 1 < len(rows) and sma20[index] is not None and sma20[index - 1] is not None:
            crossed_up = closes[index - 1] <= sma20[index - 1] and closes[index] > sma20[index]
            crossed_down = closes[index - 1] >= sma20[index - 1] and closes[index] < sma20[index]
            if crossed_up and shares == 0:
                pending = "buy"
            elif crossed_down and shares > 0:
                pending = "sell"
        equity.append(cash + shares * row["close"])
    total_return = (equity[-1] - 1) * 100
    peak, max_drawdown = equity[0], 0.0
    for value in equity:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, (value / peak - 1) * 100 if peak else 0.0)
    returns = [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity)) if equity[i - 1] > 0]
    volatility = pstdev(returns) if len(returns) >= 2 else None
    sharpe = mean(returns) / volatility * sqrt(250) if volatility and volatility > 0 else None
    downside = [min(0.0, value) for value in returns]
    downside_dev = sqrt(mean([value * value for value in downside])) if downside else None
    sortino = mean(returns) / downside_dev * sqrt(250) if downside_dev and downside_dev > 0 else None
    completed = [trade for trade in trades if trade["side"] == "sell" and trade.get("return_pct") is not None]
    winners = [trade for trade in completed if trade["return_pct"] > 0]
    gains = sum(trade["return_pct"] for trade in completed if trade["return_pct"] > 0)
    losses = abs(sum(trade["return_pct"] for trade in completed if trade["return_pct"] < 0))
    return {"status": "AVAILABLE", "model_version": MODEL_VERSION,
            "rule": "Long-only SMA(20) close crossover; execution next confirmed session",
            "parameters": {"sma_days": 20, "fee_bps_per_side": fee_bps,
                           "slippage_bps_per_side": slippage_bps, "max_position": "100%"},
            "period": {"from": rows[0]["date"], "to": rows[-1]["date"], "observations": len(rows)},
            "metrics": {"total_return_pct": total_return, "max_drawdown_pct": max_drawdown,
                        "sharpe": sharpe, "sortino": sortino,
                        "win_rate_pct": len(winners) / len(completed) * 100 if completed else None,
                        "profit_factor": gains / losses if losses else None,
                        "completed_trades": len(completed)},
            "trades": trades, "publication": "AVAILABLE",
            "disclaimer": "Historical diagnostic only; it is not a trading recommendation."}
