"""formulas.py — the one place where price metrics are computed.

ТЗ v1.2 §3/§5. Metrics fall into two classes and keeping them apart is the
whole point of this module:

  window    depend on the selected period — min / max / mean close, VWAP,
            turnover, volume.
  absolute  do NOT depend on it — YTD, YOY, QOQ, volatility, day change,
            max daily range, data quality. They are computed once over the
            full history. **The period button must never move an absolute
            metric.** Before this module the card recomputed everything from
            whatever slice the chart happened to have loaded, so YTD changed
            on 76 of 77 securities when the period changed and flipped sign
            on 44 of them (BNGPP ranged from +9.52 % to +557.14 %).

Every metric comes back as ``{"value": ..., "status": ...}``, never a bare
number. A metric that cannot be computed honestly returns ``value=None`` and
a status naming the reason, so the interface can draw a dash that explains
itself instead of a plausible wrong number.

Nothing here reads the network or the database: points in, numbers out. That
is what makes it testable on synthetic series and reusable by the card, the
market screen and the export without a second implementation.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (ТЗ §11.4: not one of these numbers may appear as a literal in
# calculation code — changing a threshold must not require a release).
# ---------------------------------------------------------------------------

_DEFAULT_THRESHOLDS: dict[str, dict[str, Any]] = {
    "quality": {
        # ТЗ §5: liquid at flat share <= 0.5 AND calendar coverage >= 0.6;
        # sparse when either is violated; no_data below two points.
        "flat_share_max": 0.5,
        "coverage_min": 0.6,
        "min_points": 2,
        # ТЗ names the `illiquid` tier in the calc_quality schema (§10.3) and in
        # the /instruments contract (§10.4.1) but never states its thresholds.
        # These are ours: a series this degenerate is not a thinner `sparse`,
        # it is a series whose shape carries no information at all.
        "illiquid_flat_share": 0.8,
        "illiquid_coverage": 0.25,
        "window_days": 365,
    },
    "volatility": {
        "window_days": 30,
        "min_observations": 10,
        "trading_days_per_year": 252,
    },
    "returns": {
        # ТЗ §5: a comparison base older than this is not a base.
        "base_staleness_max_days": 30,
    },
    "moving_average": {
        # ТЗ §6 says "calendar window", ТЗ §11.5 pins the acceptance invariant
        # at "MA20 spans 28 calendar days ±20 %". 20 trading days ARE 28
        # calendar days; a literal 20-calendar-day window would fail the
        # invariant it is checked against, so the calendar lengths are 28/70.
        "ma20_calendar_days": 28,
        "ma50_calendar_days": 70,
        "min_observations": 3,
    },
    # ТЗ §7 — a statement that breaks one of these cannot be published as a
    # number. 7 of 89 cached rows do (TGPG, MXUS, UZML, KSCM, UZNGP, GRBK, BNGP).
    "financials": {
        "gross_profit_vs_revenue_max": 1.0,
        "net_income_vs_revenue_max": 1.5,
        "liabilities_vs_assets_max": 1.5,
        "half_year_vs_annual_max": 5,
        "roe_implied_vs_published_max": 8,
    },
    # ТЗ §8 — outside these a multiple is a data error, not a valuation.
    "multiples": {
        "pe_range": [0.5, 200],
        "pb_range": [0.05, 20],
        "roe_abs_max": 100,
        "cap_vs_price_shares_max": 1.5,
    },
    # ТЗ §9 — below either of these one trade is deciding a tile's colour.
    "market_map": {
        "min_trades_confident": 5,
        "min_quantity_confident": 10,
    },
    "catalog": {
        "inactive_after_days": 90,
    },
}

_THRESHOLDS_PATH = Path(__file__).resolve().parent / "config" / "thresholds.json"
_thresholds_cache: dict[str, dict[str, Any]] | None = None


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def thresholds(refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Configured thresholds, defaults deep-merged with config/thresholds.json."""
    global _thresholds_cache
    if _thresholds_cache is not None and not refresh:
        return _thresholds_cache
    merged = _DEFAULT_THRESHOLDS
    try:
        if _THRESHOLDS_PATH.exists():
            merged = _deep_merge(_DEFAULT_THRESHOLDS,
                                 json.loads(_THRESHOLDS_PATH.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 — a broken config must not take the API down
        logger.exception("thresholds config unreadable, using defaults")
        merged = _DEFAULT_THRESHOLDS
    _thresholds_cache = merged
    return merged


# Period buttons on the card. The month count is what /api/price-history takes,
# so the window sliced here is exactly the window the chart draws.
WINDOW_CODES: dict[int, str] = {1: "1m", 3: "3m", 6: "6m", 12: "1y", 36: "3y", 60: "5y"}
WINDOW_LABELS_RU: dict[int, str] = {
    1: "за месяц", 3: "за 3 месяца", 6: "за 6 месяцев",
    12: "за 12 месяцев", 36: "за 3 года", 60: "за 5 лет",
}


def _metric(value: Any, status: str, **extra: Any) -> dict[str, Any]:
    """Every number leaves this module with a status attached (ТЗ §10.4)."""
    out: dict[str, Any] = {"value": value, "status": status}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


# Public alias: the API layer and the other domain modules parse untrusted
# numbers through the same coercion the formulas use, so "1 234,56", None and
# NaN cannot mean one thing in a calculation and another in a response.
to_number = _num


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Points
# ---------------------------------------------------------------------------

def normalize_points(raw: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Clean ascending daily series from openinfo or /api/price-history rows.

    Accepts both spellings the codebase carries: openinfo's
    ``trading_volume`` / ``trading_value`` and the API's ``volume`` / ``value``.
    Turnover is kept because VWAP is turnover over volume and nothing else —
    dropping it is what forced the old sum(close*volume)/volume approximation.
    """
    seen: dict[date, dict[str, Any]] = {}
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        day = _as_date(row.get("date") or row.get("trade_date"))
        close = _num(row.get("close") if row.get("close") is not None else row.get("close_price"))
        if day is None or close is None or close <= 0:
            continue
        volume = _num(row.get("volume"))
        if volume is None:
            volume = _num(row.get("trading_volume"))
        turnover = _num(row.get("value"))
        if turnover is None:
            turnover = _num(row.get("trading_value"))
        # A later record for the same day supersedes an earlier one (revisions).
        seen[day] = {
            "d": day,
            "date": day.isoformat(),
            "open": _num(row.get("open") if row.get("open") is not None else row.get("open_price")),
            "high": _num(row.get("high") if row.get("high") is not None else row.get("high_price")),
            "low": _num(row.get("low") if row.get("low") is not None else row.get("low_price")),
            "close": close,
            "volume": volume if volume is not None else 0.0,
            "turnover": turnover,
            "trades": _num(row.get("trades") or row.get("trade_count")),
        }
    return [seen[k] for k in sorted(seen)]


def ohlc_valid(point: dict[str, Any]) -> bool:
    """ТЗ §6: the OHLC check applies to a POINT, not to the whole series.

    The old gate was ``daily.every(...)`` — a single malformed record from the
    source turned candles off for the entire instrument.
    """
    o, h, l, c = point.get("open"), point.get("high"), point.get("low"), point.get("close")
    if None in (o, h, l, c):
        return False
    if min(o, h, l, c) <= 0:
        return False
    return l <= min(o, c) and max(o, c) <= h


def is_flat(point: dict[str, Any]) -> bool:
    """Open = high = low = close — a day with no intraday range at all."""
    if not ohlc_valid(point):
        return False
    return point["open"] == point["high"] == point["low"] == point["close"]


def _trading_days(start: date, end: date) -> int:
    """Mon-Fri days in [start, end]. The exchange publishes no holiday calendar,
    so a five-day week is the honest approximation for coverage."""
    if end < start:
        return 0
    total = (end - start).days + 1
    full_weeks, rest = divmod(total, 7)
    days = full_weeks * 5
    weekday = start.weekday()
    for i in range(rest):
        if (weekday + i) % 7 < 5:
            days += 1
    return days


# ---------------------------------------------------------------------------
# Window metrics — these MAY depend on the selected period
# ---------------------------------------------------------------------------

def window_slice(points: Sequence[dict[str, Any]], months: int,
                 today: date | None = None) -> list[dict[str, Any]]:
    """The slice the period button selects.

    ``months * 30`` days back from today reproduces exactly what
    ``fetch_price_history`` asks openinfo for, so the window measured here and
    the series drawn on the chart cannot describe different spans.
    """
    start = (today or date.today()) - timedelta(days=max(1, int(months)) * 30)
    return [p for p in points if p["d"] >= start]


def vwap(points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """VWAP is turnover divided by volume and nothing else (ТЗ §5).

    Substituting the mean close is forbidden: over 77 securities the old
    sum(close*volume)/sum(volume) form was off by a median 0.69 %, above 1 % on
    34 of them, and by +33.0 % on UZHM and +32.4 % on UNVB.
    """
    volume = 0.0
    turnover = 0.0
    missing = 0
    for p in points:
        vol = p.get("volume") or 0.0
        if vol <= 0:
            continue
        volume += vol
        if p.get("turnover") is None:
            missing += 1
        else:
            turnover += p["turnover"]
    if volume <= 0:
        return _metric(None, "no_volume", note="за период не было сделок")
    if missing:
        return _metric(None, "turnover_missing", missing_points=missing,
                       note="оборот известен не по всем точкам окна")
    return _metric(turnover / volume, "ok", method="turnover/volume")


def window_stats(points: Sequence[dict[str, Any]], months: int,
                 today: date | None = None) -> dict[str, Any]:
    """Everything on the card that is allowed to change with the period."""
    window = window_slice(points, months, today)
    code = WINDOW_CODES.get(int(months), f"{int(months)}m")
    label = WINDOW_LABELS_RU.get(int(months), f"за {int(months)} мес.")
    if not window:
        return {
            "code": code, "label": label, "points": 0,
            "vwap": _metric(None, "no_data"),
            "min_close": _metric(None, "no_data"),
            "max_close": _metric(None, "no_data"),
            "mean_close": _metric(None, "no_data"),
            "turnover": _metric(None, "no_data"),
            "volume": _metric(None, "no_data"),
            "first_date": None, "last_date": None,
        }
    closes = [p["close"] for p in window]
    turnovers = [p["turnover"] for p in window if p.get("turnover") is not None]
    return {
        "code": code,
        "label": label,
        "points": len(window),
        "vwap": vwap(window),
        "min_close": _metric(min(closes), "ok"),
        "max_close": _metric(max(closes), "ok"),
        # ТЗ §6: labelled "среднее закрытий", never "средняя цена" — it is not
        # volume-weighted and must not be read as one.
        "mean_close": _metric(sum(closes) / len(closes), "ok"),
        "turnover": _metric(sum(turnovers), "ok") if len(turnovers) == len(window)
        else _metric(None, "turnover_missing", missing_points=len(window) - len(turnovers)),
        "volume": _metric(sum(p.get("volume") or 0.0 for p in window), "ok"),
        "first_date": window[0]["date"],
        "last_date": window[-1]["date"],
    }


# ---------------------------------------------------------------------------
# Absolute metrics — these may NOT depend on the selected period
# ---------------------------------------------------------------------------

def _base_point(points: Sequence[dict[str, Any]], target: date,
                max_stale_days: int) -> tuple[dict[str, Any] | None, str]:
    """Last point at or before ``target``, rejected when it is too far back.

    A base older than the staleness limit is not a comparison base: the number
    it produces measures a different span than its label claims.
    """
    base = None
    for p in points:
        if p["d"] <= target:
            base = p
        else:
            break
    if base is None:
        return None, "no_base"
    if (target - base["d"]).days > max_stale_days:
        return None, "base_too_stale"
    return base, "ok"


def _pct_change(last: float, base: float) -> float | None:
    if base <= 0:
        return None
    return (last - base) / base * 100.0


def returns(points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """YTD / YOY / QOQ over the FULL history (ТЗ §5).

    Computed from every point we hold, never from the loaded slice, so the
    period button cannot move them.
    """
    cfg = thresholds()["returns"]
    max_stale = int(cfg["base_staleness_max_days"])
    if len(points) < 2:
        empty = _metric(None, "no_data")
        return {"ytd": empty, "yoy": dict(empty), "qoq": dict(empty)}
    last = points[-1]

    # YTD — the previous year's closing price. ТЗ §5: when the instrument has
    # no prior-year close, fall back to the first trade of the current year and
    # say so, rather than showing nothing.
    year_end = date(last["d"].year - 1, 12, 31)
    base, status = _base_point(points, year_end, max_stale)
    fallback = False
    if base is None:
        this_year = [p for p in points if p["d"].year == last["d"].year]
        if len(this_year) >= 2:
            base, status, fallback = this_year[0], "ok", True
    if base is None or base is last:
        ytd = _metric(None, status if base is None else "no_base")
    else:
        ytd = _metric(_pct_change(last["close"], base["close"]), "ok",
                      base_date=base["date"], base_is_fallback=fallback or None)

    def horizon(days: int, name: str) -> dict[str, Any]:
        target = last["d"] - timedelta(days=days)
        b, st = _base_point(points, target, max_stale)
        if b is None or b is last:
            return _metric(None, st if b is None else "no_base",
                           note=f"нет сделок около {target.isoformat()}")
        return _metric(_pct_change(last["close"], b["close"]), "ok", base_date=b["date"])

    return {"ytd": ytd, "yoy": horizon(365, "yoy"), "qoq": horizon(90, "qoq")}


def volatility(points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Annualised volatility on a CALENDAR window (ТЗ §5).

    Log returns normalised by the gap between observations, sample standard
    deviation, annualised by sqrt(252), 30-calendar-day window, at least 10
    observations. The old form took the last 21 points whatever calendar they
    covered — 230 days for TRSBP (off 7 points), 214 for FRAZP, 185 for UZML —
    and never annualised, so the number was neither a 20-day nor a yearly one.
    """
    cfg = thresholds()["volatility"]
    window_days = int(cfg["window_days"])
    min_obs = int(cfg["min_observations"])
    if not points:
        return _metric(None, "no_data", window_days=window_days, observations=0)
    # Exactly `window_days` calendar days ending on the last point: a `>=`
    # bound here would span window_days + 1 days and quietly widen the window.
    cutoff = points[-1]["d"] - timedelta(days=window_days)
    obs = [p for p in points if p["d"] > cutoff]
    if len(obs) < min_obs:
        return _metric(None, "insufficient_data", window_days=window_days,
                       observations=len(obs),
                       note=f"нужно не менее {min_obs} наблюдений за {window_days} дней")
    rets: list[float] = []
    for prev, cur in zip(obs, obs[1:]):
        gap = (cur["d"] - prev["d"]).days
        if gap <= 0 or prev["close"] <= 0 or cur["close"] <= 0:
            continue
        rets.append(math.log(cur["close"] / prev["close"]) / math.sqrt(gap))
    if len(rets) < 2:
        return _metric(None, "insufficient_data", window_days=window_days,
                       observations=len(obs))
    mean = sum(rets) / len(rets)
    variance = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    annual = math.sqrt(variance) * math.sqrt(float(cfg["trading_days_per_year"])) * 100.0
    return _metric(annual, "ok", window_days=window_days, observations=len(obs),
                   annualized=True)


def max_day_range(points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Largest (high-low)/close over the full history, in percent."""
    min_obs = int(thresholds()["volatility"]["min_observations"])
    usable = [p for p in points if ohlc_valid(p)]
    if len(usable) < min_obs:
        return _metric(None, "insufficient_data", observations=len(usable))
    best = None
    best_day = None
    for p in usable:
        rng = (p["high"] - p["low"]) / p["close"] * 100.0
        if best is None or rng > best:
            best, best_day = rng, p["date"]
    return _metric(best, "ok", date=best_day, observations=len(usable))


def day_change(points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Last close against the previous trading day's close (ТЗ §5).

    Volume and turnover ride along so the interface can show how much trading
    the number rests on instead of presenting one lot as a market move.
    """
    if len(points) < 2:
        return _metric(None, "no_data")
    last, prev = points[-1], points[-2]
    return _metric(_pct_change(last["close"], prev["close"]), "ok",
                   date=last["date"], base_date=prev["date"],
                   last_price=last["close"], prev_close=prev["close"],
                   volume=last.get("volume"), turnover=last.get("turnover"),
                   trades=last.get("trades"))


def absolute_metrics(points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The block that must be identical under every period button."""
    return {
        **returns(points),
        "volatility": volatility(points),
        "max_day_range": max_day_range(points),
        "day": day_change(points),
    }


# ---------------------------------------------------------------------------
# Data quality (ТЗ §5 / §6)
# ---------------------------------------------------------------------------

def data_quality(points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Classify the series so the chart can stop drawing illiquidity as trading.

    On live data 15 of 77 securities break one of these thresholds — CTFB3 is
    87 % flat candles on 32 % calendar coverage — and every one of them is
    currently drawn with the same candles as a security that trades daily.
    """
    cfg = thresholds()["quality"]
    horizon = int(cfg["window_days"])
    if points:
        cutoff = points[-1]["d"] - timedelta(days=horizon)
        recent = [p for p in points if p["d"] > cutoff]
    else:
        recent = []

    if len(recent) < int(cfg["min_points"]):
        return {
            "data_tier": "no_data", "points": len(recent), "flat_share": None,
            "coverage": None, "max_gap_days": None, "median_gap_days": None,
            "candles_enabled": False, "ohlc_points": 0,
            "reason": "менее двух точек за период",
        }

    ohlc_pts = [p for p in recent if ohlc_valid(p)]
    flats = sum(1 for p in ohlc_pts if is_flat(p))
    flat_share = (flats / len(ohlc_pts)) if ohlc_pts else None
    span_days = _trading_days(recent[0]["d"], recent[-1]["d"])
    coverage = (len(recent) / span_days) if span_days else None
    gaps = [(b["d"] - a["d"]).days for a, b in zip(recent, recent[1:])]

    reasons: list[str] = []
    tier = "full"
    if flat_share is not None and flat_share > float(cfg["illiquid_flat_share"]):
        tier = "illiquid"
        reasons.append(f"{flat_share:.0%} свечей без внутридневного диапазона")
    elif coverage is not None and coverage < float(cfg["illiquid_coverage"]):
        tier = "illiquid"
        reasons.append(f"сделки лишь в {coverage:.0%} торговых дней")
    else:
        if flat_share is not None and flat_share > float(cfg["flat_share_max"]):
            tier = "sparse"
            reasons.append(f"{flat_share:.0%} свечей без внутридневного диапазона")
        if coverage is not None and coverage < float(cfg["coverage_min"]):
            tier = "sparse"
            reasons.append(f"сделки лишь в {coverage:.0%} торговых дней")
    if not ohlc_pts:
        tier = "sparse" if tier == "full" else tier
        reasons.append("нет корректных OHLC")

    return {
        "data_tier": tier,
        "points": len(recent),
        "ohlc_points": len(ohlc_pts),
        "flat_share": flat_share,
        "coverage": coverage,
        "max_gap_days": max(gaps) if gaps else 0,
        "median_gap_days": sorted(gaps)[len(gaps) // 2] if gaps else 0,
        # ТЗ §6: candles are switched off BY THE SYSTEM at sparse, not by hand.
        "candles_enabled": tier == "full" and bool(ohlc_pts),
        "reason": "; ".join(reasons) or None,
    }


# ---------------------------------------------------------------------------
# Moving averages (ТЗ §6)
# ---------------------------------------------------------------------------

MA_WINDOWS: dict[str, str] = {"ma20": "ma20_calendar_days", "ma50": "ma50_calendar_days"}


def moving_average(points: Sequence[dict[str, Any]], calendar_days: int,
                   min_observations: int | None = None) -> list[float | None]:
    """Mean close over a CALENDAR window, on the raw daily series (ТЗ §6).

    Always the daily series, never the display buckets: averaging 20 weekly
    candles spans 134 calendar days, not 28, and made "MA20" a different line
    in candle mode than in line mode on 72 of 72 securities.
    """
    cfg = thresholds()["moving_average"]
    min_obs = int(min_observations if min_observations is not None else cfg["min_observations"])
    out: list[float | None] = []
    start = 0
    total = 0.0
    for i, p in enumerate(points):
        total += p["close"]
        while points[start]["d"] < p["d"] - timedelta(days=calendar_days - 1):
            total -= points[start]["close"]
            start += 1
        count = i - start + 1
        out.append(total / count if count >= min_obs else None)
    return out


def moving_averages(points: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """MA20 / MA50 aligned to ``points``, each with its calendar window."""
    cfg = thresholds()["moving_average"]
    out: dict[str, dict[str, Any]] = {}
    for name, key in MA_WINDOWS.items():
        days = int(cfg[key])
        series = moving_average(points, days)
        available = sum(1 for v in series if v is not None)
        out[name] = {
            "window_days": days,
            "values": series,
            "enabled": available > 0,
            "reason": None if available else
            f"менее {int(cfg['min_observations'])} наблюдений в окне {days} дней",
        }
    return out


# ---------------------------------------------------------------------------
# The whole card in one call
# ---------------------------------------------------------------------------

def company_metrics(raw_points: Iterable[dict[str, Any]] | None, months: int = 12,
                    today: date | None = None) -> dict[str, Any]:
    """Window block, absolute block and quality for one instrument.

    ``raw_points`` is the FULL history. The window block is sliced from it; the
    absolute block never is.
    """
    points = normalize_points(raw_points)
    ma_cfg = thresholds()["moving_average"]
    return {
        "window": window_stats(points, months, today),
        "absolute": absolute_metrics(points),
        "quality": data_quality(points),
        # The chart draws the MA itself (it needs a value per plotted point),
        # so it is told the calendar lengths rather than left to guess them —
        # guessing is how "MA20" became 134 days in candle mode.
        "ma_windows": {
            "ma20": int(ma_cfg["ma20_calendar_days"]),
            "ma50": int(ma_cfg["ma50_calendar_days"]),
            "min_observations": int(ma_cfg["min_observations"]),
        },
        "history_points": len(points),
        "history_first": points[0]["date"] if points else None,
        "history_last": points[-1]["date"] if points else None,
    }
