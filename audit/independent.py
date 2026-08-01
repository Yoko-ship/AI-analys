"""The auditor's OWN arithmetic (ТЗ v1.3 §12.1).

This module deliberately duplicates work that ``formulas.py`` and
``fundamentals.py`` already do. That duplication is the entire mechanism: two
implementations, written from the definitions rather than from each other,
reading the raw tables rather than the materialised metrics, and compared. When
they disagree one of them is wrong, and that is a finding. Calling the
production function instead would make every check pass by construction.

So: **nothing in this package may import the production calculation layer.**
Not for a helper, not for a constant, not for number parsing. A test enforces
it. The only shared artefact is ``config/thresholds.json`` — configuration is
data, and both sides are supposed to read the same thresholds.

Where an approach was available in more than one form, this file takes the one
production does NOT: sums are accumulated over comprehensions rather than in a
running loop, windows are selected by explicit date arithmetic rather than by a
sliding pointer, and dates are parsed by a separate routine. Identical results
from different routes are worth something; identical results from the same code
are worth nothing.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "thresholds.json"

# The auditor's own defaults. They exist so a missing or broken config cannot
# silently disable a check — a rule with no threshold would otherwise pass.
_AUDIT_DEFAULTS: dict[str, Any] = {
    "audit": {
        "balance_tolerance_pct": 1.0,
        "recompute_tolerance_pct": 0.5,
        "market_cap_tolerance_pct": 0.1,
        "change_tolerance_pp": 0.01,
        "turnover_tolerance_pct": 0.5,
        "pb_identity_tolerance_pct": 5.0,
        "net_vs_gross_tolerance_pct": 5.0,
        "unit_scale_max_ratio": 1000.0,
        "stale_report_months": 18,
        "required_field_coverage_min": 1.0,
        "suppressed_share_max": 0.35,
        "median_gap_warn_days": 5,
        "median_gap_block_days": 15,
        "ma20_max_calendar_days": 45,
        "ma_mode_tolerance_days": 7,
        "spike_change_pct": 15.0,
        "spike_max_trades": 3,
        "max_runtime_seconds": 300,
        "ytm_tolerance": 0.05,
    },
}


def thresholds() -> dict[str, Any]:
    """Configuration, read here directly — not through the production loader."""
    merged = json.loads(json.dumps(_AUDIT_DEFAULTS))
    try:
        raw = json.loads(_CONFIG.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — defaults must survive a broken file
        return merged
    for section, values in raw.items():
        if not isinstance(values, dict):
            continue
        merged.setdefault(section, {})
        merged[section].update(values)
    return merged


def threshold(path: str, default: Any = None) -> Any:
    """`"multiples.pe_range"` -> the configured value."""
    node: Any = thresholds()
    for part in str(path or "").split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


# ---------------------------------------------------------------------------
# Parsing — the auditor's own, on purpose
# ---------------------------------------------------------------------------

def num(value: Any) -> float | None:
    """A number, or None. Tolerates the spellings the sources actually emit."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if not text or text in {"-", "—", "n/a", "null"}:
        return None
    text = text.replace(",", ".") if text.count(",") == 1 and "." not in text else text.replace(",", "")
    try:
        out = float(text)
    except ValueError:
        return None
    return out if math.isfinite(out) else None


_DATE_PATTERNS = (
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})"), (1, 2, 3)),
    (re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$"), (3, 2, 1)),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})$"), (1, 2, 3)),
)


def day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for pattern, (y, m, d) in _DATE_PATTERNS:
        hit = pattern.match(text)
        if hit:
            try:
                return date(int(hit.group(y)), int(hit.group(m)), int(hit.group(d)))
            except ValueError:
                return None
    return None


def relative_gap(a: float | None, b: float | None) -> float | None:
    """Difference between two figures as a percentage of the larger magnitude.

    Symmetric on purpose: "which one is the reference" is exactly what a
    disagreement leaves undecided.
    """
    if a is None or b is None:
        return None
    scale = max(abs(a), abs(b))
    if scale == 0:
        return 0.0
    return abs(a - b) / scale * 100.0


# ---------------------------------------------------------------------------
# Price series
# ---------------------------------------------------------------------------

def series(points: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Raw feed rows -> a clean ascending series, keyed by date."""
    out: dict[date, dict[str, Any]] = {}
    for row in points or []:
        if not isinstance(row, dict):
            continue
        d = day(row.get("date") or row.get("trade_date"))
        close = num(row.get("close") if row.get("close") is not None else row.get("close_price"))
        if d is None or close is None or close <= 0:
            continue
        out[d] = {
            "d": d,
            "open": num(row.get("open") if row.get("open") is not None else row.get("open_price")),
            "high": num(row.get("high") if row.get("high") is not None else row.get("high_price")),
            "low": num(row.get("low") if row.get("low") is not None else row.get("low_price")),
            "close": close,
            "volume": num(row.get("volume")) if row.get("volume") is not None
            else num(row.get("trading_volume")),
            "turnover": num(row.get("value")) if row.get("value") is not None
            else num(row.get("trading_value")),
        }
    return [out[k] for k in sorted(out)]


def vwap(points: Sequence[dict[str, Any]]) -> float | None:
    """Turnover over volume. Accumulated by comprehension, not by loop."""
    traded = [p for p in points if (p.get("volume") or 0) > 0]
    if not traded or any(p.get("turnover") is None for p in traded):
        return None
    volume = sum(p["volume"] for p in traded)
    if volume <= 0:
        return None
    return sum(p["turnover"] for p in traded) / volume


def flat_share(points: Sequence[dict[str, Any]]) -> float | None:
    usable = [p for p in points if ohlc_ok(p)]
    if not usable:
        return None
    flat = [p for p in usable if p["open"] == p["high"] == p["low"] == p["close"]]
    return len(flat) / len(usable)


def ohlc_ok(p: dict[str, Any]) -> bool:
    o, h, l, c = p.get("open"), p.get("high"), p.get("low"), p.get("close")
    if any(v is None for v in (o, h, l, c)) or min(o, h, l, c) <= 0:
        return False
    return l <= min(o, c) and max(o, c) <= h


def coverage(points: Sequence[dict[str, Any]]) -> float | None:
    """Points as a share of the weekday sessions the span contains."""
    if len(points) < 2:
        return None
    first, last = points[0]["d"], points[-1]["d"]
    weekdays = sum(1 for i in range((last - first).days + 1)
                   if (first + timedelta(days=i)).weekday() < 5)
    return (len(points) / weekdays) if weekdays else None


def gaps(points: Sequence[dict[str, Any]]) -> list[int]:
    return [(b["d"] - a["d"]).days for a, b in zip(points, points[1:])]


def moving_average_span(points: Sequence[dict[str, Any]], window_days: int) -> int | None:
    """Calendar days the last MA value actually averages over.

    Selected by explicit date arithmetic rather than a sliding index, so an
    off-by-one in either implementation shows up as a disagreement.
    """
    if len(points) < 2:
        return None
    last = points[-1]["d"]
    cutoff = last - timedelta(days=window_days - 1)
    inside = [p for p in points if p["d"] >= cutoff]
    if len(inside) < 2:
        return None
    return (inside[-1]["d"] - inside[0]["d"]).days


def bucket_ma_span(points: Sequence[dict[str, Any]], buckets: int = 20,
                   kind: str = "week") -> int | None:
    """Calendar span of the last N DISPLAY buckets — what averaging candles gives.

    CND-07 compares this against the calendar window: they must describe the
    same number of days, or "MA20" means one thing on a candle chart and
    another on a line chart of the same security.
    """
    if not points:
        return None
    keyed: dict[Any, list[dict[str, Any]]] = {}
    for p in points:
        d = p["d"]
        key = (d.year, d.month) if kind == "month" else d.isocalendar()[:2]
        keyed.setdefault(key, []).append(p)
    ordered = [group[-1] for _, group in sorted(keyed.items())]
    if len(ordered) < buckets:
        return None
    return (ordered[-1]["d"] - ordered[-buckets]["d"]).days


def pct_change(last: float | None, base: float | None) -> float | None:
    if last is None or base is None or base <= 0:
        return None
    return (last - base) / base * 100.0


def ytd(points: Sequence[dict[str, Any]]) -> float | None:
    """Against the previous year's last close, over the FULL series."""
    if len(points) < 2:
        return None
    last = points[-1]
    prior = [p for p in points if p["d"].year < last["d"].year]
    if prior:
        return pct_change(last["close"], prior[-1]["close"])
    same_year = [p for p in points if p["d"].year == last["d"].year]
    if len(same_year) < 2:
        return None
    return pct_change(last["close"], same_year[0]["close"])


def horizon_change(points: Sequence[dict[str, Any]], days: int,
                   max_stale: int) -> float | None:
    if len(points) < 2:
        return None
    last = points[-1]
    target = last["d"] - timedelta(days=days)
    earlier = [p for p in points if p["d"] <= target]
    if not earlier:
        return None
    base = earlier[-1]
    if (target - base["d"]).days > max_stale or base is last:
        return None
    return pct_change(last["close"], base["close"])


# ---------------------------------------------------------------------------
# Market arithmetic
# ---------------------------------------------------------------------------

def day_change(last_price: Any, prev_close: Any) -> float | None:
    """On unrounded inputs — rounding first is what erases a 0.01-sum move."""
    return pct_change(num(last_price), num(prev_close))


def market_cap(price: Any, shares: Any) -> float | None:
    p, s = num(price), num(shares)
    if p is None or s is None or p <= 0 or s <= 0:
        return None
    return p * s


def price_earnings(cap: float | None, net_income: float | None) -> float | None:
    if cap is None or net_income is None or net_income <= 0 or cap <= 0:
        return None
    return cap / net_income


def price_book(cap: float | None, equity: float | None) -> float | None:
    if cap is None or equity is None or equity <= 0 or cap <= 0:
        return None
    return cap / equity


def weighted_change(rows: Sequence[dict[str, Any]]) -> float | None:
    """Turnover-weighted mean of the changes, over priced rows only."""
    priced = [r for r in rows if r.get("change_pct") is not None
              and r.get("status") in (None, "ok")]
    weight = sum((r.get("turnover") or 0.0) for r in priced)
    if not priced:
        return None
    if weight <= 0:
        return sum(r["change_pct"] for r in priced) / len(priced)
    return sum(r["change_pct"] * (r.get("turnover") or 0.0) for r in priced) / weight


def months_between(period: Any, today: date | None = None) -> int | None:
    """Age of a reporting period in months."""
    text = str(period or "").strip().upper()
    hit = re.match(r"^(\d{4})(?:[-\s]?Q([1-4]))?A?$", text)
    if not hit:
        return None
    year = int(hit.group(1))
    quarter = int(hit.group(2)) if hit.group(2) else 4
    end = date(year, min(12, quarter * 3), 28)
    now = today or date.today()
    return (now.year - end.year) * 12 + (now.month - end.month)


def ytm_bisection(cashflows: Sequence[tuple[float, float]], dirty: float,
                  low: float = -0.9, high: float = 10.0,
                  tolerance: float = 1e-10, max_iterations: int = 400) -> float | None:
    """Yield to maturity by BISECTION — production solves it with Newton.

    Two different root-finders on the same equation is the whole point: Newton
    can converge to a different root, or report convergence at a point bisection
    would reject. Returns a percentage, or None when the root is not bracketed.
    """
    if not cashflows or dirty is None or dirty <= 0:
        return None

    def pv(rate: float) -> float:
        try:
            return sum(cf / (1.0 + rate) ** t for t, cf in cashflows) - dirty
        except (OverflowError, ZeroDivisionError):
            return float("inf")

    lo, hi = pv(low), pv(high)
    if lo * hi > 0:
        return None
    for _ in range(max_iterations):
        mid = (low + high) / 2.0
        value = pv(mid)
        if abs(value) < tolerance or (high - low) < tolerance:
            return mid * 100.0
        if lo * value <= 0:
            high = mid
        else:
            low, lo = mid, value
    return ((low + high) / 2.0) * 100.0
