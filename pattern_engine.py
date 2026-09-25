"""Chart-pattern and candlestick detection on confirmed daily sessions.

Everything here is causal: a pattern is reported on the session whose CLOSE
completed it, from data up to and including that close, and never moves or
disappears afterwards. That is what "no repainting" means for a daily series:

* A ZigZag turning point exists only from the session that confirmed it — the
  one on which price had moved ``k × ATR`` away from the extreme. Until then the
  extreme is a candidate, and no pattern may use it.
* A chart pattern (double top, head and shoulders, triangle, flag) is a
  formation built from confirmed turning points; its signal is the first later
  close beyond its neckline or boundary. A formation that never breaks out is
  never a signal.

The evaluation is the other half of the module, and the reason the first half
is allowed on a page at all. Each signal is executed at the NEXT session's close
(the fill a reader could actually have had), with fee and slippage, and scored
target-before-stop within a fixed horizon. Beside it stands the rate at which
the same target and stop would have been hit from an ordinary session of the
same stock — the chance level. A pattern is worth showing only where it beats
that line; on most of this market it will not, and the numbers say so.

Bearish signals are scored as "the price fell as the pattern said". UZSE has no
short selling, so they are never counted as short trades.
"""
from __future__ import annotations

from math import atan, degrees, sqrt
from statistics import mean, median, pstdev
from typing import Any, Iterable

MODEL_VERSION = "patterns-v1"

DEFAULTS: dict[str, float] = {
    "atr_days": 14,          # Wilder ATR
    "zigzag_atr": 2.0,       # a swing is k × ATR
    "zigzag_min_pct": 3.0,   # …and never less than this share of price
    "breakout_wait": 15,     # sessions a formation waits for its breakout
    "horizon": 20,           # sessions a signal has to reach its target
    "fee_bps": 15,
    "slippage_bps": 20,
}

# How large a swing has to be before the ZigZag calls it one. «Высокая»
# finds more, smaller figures; «низкая» fewer, larger ones. Each level has its
# own outcome table in config/pattern_stats.json — a pattern's record depends
# on the sensitivity it was found at.
SENSITIVITY = {"low": 3.0, "medium": 2.0, "high": 1.5}

CANDLE_TYPES = ("bullish_engulfing", "bearish_engulfing", "hammer", "shooting_star",
                "morning_star", "evening_star")
CHART_TYPES = ("double_top", "double_bottom", "triple_top", "triple_bottom",
               "head_shoulders", "inverse_head_shoulders",
               "ascending_triangle", "descending_triangle", "symmetrical_triangle",
               "rising_wedge", "falling_wedge",
               "ascending_channel", "descending_channel", "horizontal_channel",
               "bull_flag", "bear_flag", "bull_pennant", "bear_pennant")


# ── Input ────────────────────────────────────────────────────────────────────

def _num(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value == value and value > 0 else None


def normalize(points: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Ascending sessions with a close; OHLC kept only where it is consistent."""
    by_date: dict[str, dict[str, Any]] = {}
    for p in points or []:
        stamp = str(p.get("date") or p.get("trade_date") or "")[:10]
        close = _num(p.get("close", p.get("close_price")))
        if not stamp or close is None:
            continue
        o = _num(p.get("open", p.get("open_price")))
        h = _num(p.get("high", p.get("high_price")))
        lo = _num(p.get("low", p.get("low_price")))
        ok = (o is not None and h is not None and lo is not None
              and lo <= min(o, close) and max(o, close) <= h)
        by_date[stamp] = {
            "date": stamp, "close": close,
            "open": o if ok else close, "high": h if ok else close, "low": lo if ok else close,
            "ohlc": ok, "flat": (not ok) or h == lo,
            "value": _num(p.get("value", p.get("trading_value", p.get("turnover")))) or 0.0,
        }
    return [by_date[d] for d in sorted(by_date)]


def atr(rows: list[dict[str, Any]], days: int = 14) -> list[float | None]:
    """Wilder's average true range; the close-to-close move where a day has no range."""
    out: list[float | None] = [None] * len(rows)
    running = None
    trs: list[float] = []
    for i, r in enumerate(rows):
        prev = rows[i - 1]["close"] if i else r["close"]
        tr = max(r["high"] - r["low"], abs(r["high"] - prev), abs(r["low"] - prev))
        if running is None:
            trs.append(tr)
            if len(trs) == days:
                running = sum(trs) / days
        else:
            running = (running * (days - 1) + tr) / days
        out[i] = running
    return out


# ── ZigZag ───────────────────────────────────────────────────────────────────

def zigzag(rows: list[dict[str, Any]], atrs: list[float | None], k: float = 2.0,
           min_pct: float = 3.0) -> list[dict[str, Any]]:
    """Confirmed turning points: ``{i, price, kind: "H"|"L", confirmed}``.

    The threshold on session ``i`` uses ATR as known on ``i``. A pivot's
    ``confirmed`` index is the session on which the reversal reached the
    threshold — the first session that may use it.
    """
    pivots: list[dict[str, Any]] = []
    if len(rows) < 2:
        return pivots

    def threshold(i: int) -> float:
        base = rows[i]["close"] * min_pct / 100
        return max(base, k * atrs[i]) if atrs[i] else base

    hi_i = lo_i = 0
    hi, lo = rows[0]["high"], rows[0]["low"]
    trend = 0
    for i in range(1, len(rows)):
        h, low, th = rows[i]["high"], rows[i]["low"], threshold(i)
        if trend == 0:
            if h > hi:
                hi, hi_i = h, i
            if low < lo:
                lo, lo_i = low, i
            if hi_i < i and hi - low >= th:
                pivots.append({"i": hi_i, "price": hi, "kind": "H", "confirmed": i})
                trend, lo, lo_i = -1, low, i
            elif lo_i < i and h - lo >= th:
                pivots.append({"i": lo_i, "price": lo, "kind": "L", "confirmed": i})
                trend, hi, hi_i = 1, h, i
        elif trend == 1:
            if h >= hi:
                hi, hi_i = h, i
            elif hi - low >= th:
                pivots.append({"i": hi_i, "price": hi, "kind": "H", "confirmed": i})
                trend, lo, lo_i = -1, low, i
        else:
            if low <= lo:
                lo, lo_i = low, i
            elif h - lo >= th:
                pivots.append({"i": lo_i, "price": lo, "kind": "L", "confirmed": i})
                trend, hi, hi_i = 1, h, i
    return pivots


# ── Geometry ─────────────────────────────────────────────────────────────────

def _line(points: list[tuple[int, float]]) -> tuple[float, float]:
    """Least-squares ``price = a + b·i`` (exact through two points)."""
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points)
    b = sum((p[0] - mx) * (p[1] - my) for p in points) / sxx if sxx else 0.0
    return my - b * mx, b


def _at(line: tuple[float, float], i: float) -> float:
    return line[0] + line[1] * i


def _angle(slope: float, atr_value: float) -> float:
    """A boundary's tilt in degrees, one ATR per session being 45°.

    Price and time have no common unit, so a raw angle means nothing; scaled by
    ATR it compares a 2-сум share with a 20 000-сум one.
    """
    return degrees(atan(slope / atr_value)) if atr_value else 0.0


# ── Candlesticks ─────────────────────────────────────────────────────────────

def _trend(rows: list[dict[str, Any]], i: int, bars: int = 8) -> float:
    """Slope of the closes BEFORE session ``i``, in ATR-free relative terms."""
    start = max(0, i - bars)
    pts = [(j, rows[j]["close"]) for j in range(start, i)]
    if len(pts) < 4:
        return 0.0
    _, b = _line(pts)
    return b * bars / rows[i - 1]["close"]


def candle_patterns(rows: list[dict[str, Any]], atrs: list[float | None]) -> list[dict[str, Any]]:
    """Reversal candles, each confirmed at its own session's close.

    A candle needs a body and a context: a flat day (no trades beyond one
    price) has no shape, and a hammer means nothing outside a decline — so both
    are required, and the body must be a fair share of the ATR.
    """
    out: list[dict[str, Any]] = []
    for i in range(10, len(rows)):
        a = atrs[i]
        if not a:
            continue
        c, p = rows[i], rows[i - 1]
        if c["flat"] or p["flat"]:
            continue
        body = abs(c["close"] - c["open"])
        pbody = abs(p["close"] - p["open"])
        rng = c["high"] - c["low"]
        upper = c["high"] - max(c["open"], c["close"])
        lower = min(c["open"], c["close"]) - c["low"]
        tr = _trend(rows, i)
        down, up = tr < -0.02, tr > 0.02
        found: list[tuple[str, str, int]] = []
        if (down and p["close"] < p["open"] and c["close"] > c["open"] and body >= 0.3 * a
                and c["close"] >= p["open"] and c["open"] <= p["close"] and body > pbody):
            found.append(("bullish_engulfing", "bullish", i - 1))
        if (up and p["close"] > p["open"] and c["close"] < c["open"] and body >= 0.3 * a
                and c["open"] >= p["close"] and c["close"] <= p["open"] and body > pbody):
            found.append(("bearish_engulfing", "bearish", i - 1))
        if down and rng >= 0.6 * a and body > 0 and lower >= 2 * body and upper <= 0.3 * max(body, 1e-12) + 0.1 * rng:
            found.append(("hammer", "bullish", i))
        if up and rng >= 0.6 * a and body > 0 and upper >= 2 * body and lower <= 0.3 * max(body, 1e-12) + 0.1 * rng:
            found.append(("shooting_star", "bearish", i))
        if i >= 2 and not rows[i - 2]["flat"]:
            f = rows[i - 2]
            fbody = abs(f["close"] - f["open"])
            mid = (f["open"] + f["close"]) / 2
            if (_trend(rows, i - 2) < -0.02 and f["close"] < f["open"] and fbody >= 0.6 * a
                    and pbody <= 0.3 * fbody and c["close"] > c["open"] and c["close"] > mid):
                found.append(("morning_star", "bullish", i - 2))
            if (_trend(rows, i - 2) > 0.02 and f["close"] > f["open"] and fbody >= 0.6 * a
                    and pbody <= 0.3 * fbody and c["close"] < c["open"] and c["close"] < mid):
                found.append(("evening_star", "bearish", i - 2))
        for kind, direction, first in found:
            span = rows[first:i + 1]
            if direction == "bullish":
                stop = min(r["low"] for r in span)
                target = c["close"] + 2 * a
            else:
                stop = max(r["high"] for r in span)
                target = c["close"] - 2 * a
            out.append(_signal(rows, kind, "candle", direction, first, i, target, stop,
                               points=[(j, rows[j]["close"]) for j in range(first, i + 1)]))
    return out


# ── Chart patterns ───────────────────────────────────────────────────────────

def _signal(rows, kind, family, direction, start, i, target, stop, *, points=(), lines=(), angles=None):
    span = rows[start:i + 1]
    return {
        "type": kind, "family": family, "direction": direction,
        "start_index": start, "signal_index": i,
        "start_date": rows[start]["date"], "signal_date": rows[i]["date"],
        "price": rows[i]["close"], "target": target, "stop": stop,
        "points": [{"date": rows[j]["date"], "price": v} for j, v in points],
        "lines": [{"role": role, "from": {"date": rows[a]["date"], "price": pa},
                   "to": {"date": rows[b]["date"], "price": pb}} for role, a, pa, b, pb in lines],
        "angles": angles or {},
        # The formation's extent, for shading: its first session to the one
        # that completed it, between its lowest low and highest high.
        "box": {"from": rows[start]["date"], "to": rows[i]["date"],
                "high": max(r["high"] for r in span), "low": min(r["low"] for r in span)},
    }


def _boundary_kind(du: float, dl: float, w0: float, w1: float, a: float) -> str | None:
    """Name the figure two fitted edges make.

    ``du``/``dl`` are how far the upper and lower edge move across the
    formation, ``w0``/``w1`` its height at the start and the end. Converging
    edges are a triangle (one edge flat or the two meeting) or a wedge (both
    leaning the same way); parallel edges are a channel. A move under 0.6 ATR
    across the whole figure counts as flat.
    """
    if w0 < 2 * a or w1 <= 0:
        return None
    flat_u, flat_l = abs(du) <= 0.6 * a, abs(dl) <= 0.6 * a
    rise_u, rise_l, fall_u, fall_l = du >= 0.6 * a, dl >= 0.6 * a, du <= -0.6 * a, dl <= -0.6 * a
    if w1 <= 0.75 * w0:
        if flat_u and rise_l:
            return "ascending_triangle"
        if flat_l and fall_u:
            return "descending_triangle"
        if fall_u and rise_l:
            return "symmetrical_triangle"
        if rise_u and rise_l:
            return "rising_wedge"
        if fall_u and fall_l:
            return "falling_wedge"
        return None
    if 0.8 * w0 <= w1 <= 1.25 * w0:
        if rise_u and rise_l:
            return "ascending_channel"
        if fall_u and fall_l:
            return "descending_channel"
        if flat_u and flat_l:
            return "horizontal_channel"
    return None


def _breakout(rows, start, wait, level_at, direction, invalid_at=None):
    """First close beyond ``level_at(i)`` in ``[start, start+wait]``; None if the
    formation was invalidated or simply never broke out."""
    for b in range(start, min(len(rows), start + wait + 1)):
        if invalid_at is not None and invalid_at(b):
            return None
        level = level_at(b)
        if level is None:
            return None
        if (direction > 0 and rows[b]["close"] > level) or (direction < 0 and rows[b]["close"] < level):
            return b
    return None


def chart_patterns(rows: list[dict[str, Any]], atrs: list[float | None],
                   pivots: list[dict[str, Any]], wait: int = 15) -> list[dict[str, Any]]:
    """Formations from confirmed turning points, signalled on their breakout."""
    out: list[dict[str, Any]] = []
    for n in range(2, len(pivots)):
        c = pivots[n]["confirmed"]          # the first session that knows pivots[0..n]
        a = atrs[c]
        if not a:
            continue

        # Double top / bottom: H L H (or L H L), equal extremes, a real trough.
        p1, m, p2 = pivots[n - 2], pivots[n - 1], pivots[n]
        if p1["kind"] == p2["kind"] and 8 <= p2["i"] - p1["i"] <= 120:
            tol = max(a, 0.02 * p2["price"])
            if p2["kind"] == "H":
                top = max(p1["price"], p2["price"])
                if abs(p1["price"] - p2["price"]) <= tol and min(p1["price"], p2["price"]) - m["price"] >= 2 * a:
                    neck = m["price"]
                    b = _breakout(rows, c, wait, lambda _i, neck=neck: neck, -1,
                                  lambda i, top=top, a=a: rows[i]["high"] > top + 0.5 * a)
                    if b is not None:
                        out.append(_signal(rows, "double_top", "chart", "bearish", p1["i"], b,
                                           neck - (top - neck), top,
                                           points=[(p1["i"], p1["price"]), (m["i"], m["price"]), (p2["i"], p2["price"])],
                                           lines=[("neckline", m["i"], neck, b, neck)]))
            else:
                bottom = min(p1["price"], p2["price"])
                if abs(p1["price"] - p2["price"]) <= tol and m["price"] - max(p1["price"], p2["price"]) >= 2 * a:
                    neck = m["price"]
                    b = _breakout(rows, c, wait, lambda _i, neck=neck: neck, 1,
                                  lambda i, bottom=bottom, a=a: rows[i]["low"] < bottom - 0.5 * a)
                    if b is not None:
                        out.append(_signal(rows, "double_bottom", "chart", "bullish", p1["i"], b,
                                           neck + (neck - bottom), bottom,
                                           points=[(p1["i"], p1["price"]), (m["i"], m["price"]), (p2["i"], p2["price"])],
                                           lines=[("neckline", m["i"], neck, b, neck)]))

        if n < 4:
            continue
        ls, n1, head, n2, rs = pivots[n - 4:n + 1]

        # Triple top / bottom: three equal extremes, the neckline through the
        # shallower of the two troughs between them.
        if ls["kind"] == head["kind"] == rs["kind"] and 15 <= rs["i"] - ls["i"] <= 200:
            sign = 1 if head["kind"] == "H" else -1
            tops = [ls["price"], head["price"], rs["price"]]
            if max(tops) - min(tops) <= max(a, 0.02 * head["price"]):
                neck = min(n1["price"], n2["price"]) if sign > 0 else max(n1["price"], n2["price"])
                edge = max(tops) if sign > 0 else min(tops)
                if sign * ((min(tops) if sign > 0 else max(tops)) - neck) >= 2 * a:
                    b = _breakout(rows, c, wait, lambda _i, neck=neck: neck, -sign,
                                  lambda i, edge=edge, sign=sign, a=a: (rows[i]["high"] > edge + 0.5 * a) if sign > 0
                                  else (rows[i]["low"] < edge - 0.5 * a))
                    if b is not None:
                        avg = sum(tops) / 3
                        out.append(_signal(rows, "triple_top" if sign > 0 else "triple_bottom", "chart",
                                           "bearish" if sign > 0 else "bullish", ls["i"], b,
                                           neck - (avg - neck), edge,
                                           points=[(p["i"], p["price"]) for p in (ls, n1, head, n2, rs)],
                                           lines=[("neckline", n1["i"], neck, b, neck)]))

        # Head and shoulders (and inverse): the middle extreme beyond both
        # shoulders, shoulders level with each other, a neckline through the troughs.
        if 15 <= rs["i"] - ls["i"] <= 200:
            sign = 1 if head["kind"] == "H" else -1
            shoulders_level = abs(ls["price"] - rs["price"]) <= max(1.5 * a, 0.06 * head["price"])
            beyond = (head["price"] - max(ls["price"], rs["price"]) if sign > 0
                      else min(ls["price"], rs["price"]) - head["price"]) >= 0.5 * a
            if ls["kind"] == head["kind"] == rs["kind"] and shoulders_level and beyond:
                neck = _line([(n1["i"], n1["price"]), (n2["i"], n2["price"])])
                clear = min(sign * (ls["price"] - _at(neck, ls["i"])), sign * (rs["price"] - _at(neck, rs["i"])))
                if clear >= a and abs(neck[1]) * (n2["i"] - n1["i"]) <= 3 * a:
                    height = sign * (head["price"] - _at(neck, head["i"]))
                    b = _breakout(rows, c, wait, lambda i, neck=neck: _at(neck, i), -sign,
                                  lambda i, head=head, sign=sign: (rows[i]["high"] > head["price"]) if sign > 0
                                  else (rows[i]["low"] < head["price"]))
                    if b is not None:
                        kind = "head_shoulders" if sign > 0 else "inverse_head_shoulders"
                        level = _at(neck, b)
                        out.append(_signal(rows, kind, "chart", "bearish" if sign > 0 else "bullish", ls["i"], b,
                                           level - sign * height, rs["price"],
                                           points=[(p["i"], p["price"]) for p in (ls, n1, head, n2, rs)],
                                           lines=[("neckline", n1["i"], _at(neck, n1["i"]), b, level)],
                                           angles={"neckline": _angle(neck[1], a)}))

        # Triangles, wedges and channels: two edges fitted through the last
        # five turning points, named by how they lean and whether they meet.
        last = pivots[n - 4:n + 1]
        highs = [(p["i"], p["price"]) for p in last if p["kind"] == "H"]
        lows = [(p["i"], p["price"]) for p in last if p["kind"] == "L"]
        first_i, last_i = last[0]["i"], last[-1]["i"]
        span = last_i - first_i
        if len(highs) >= 2 and len(lows) >= 2 and 10 <= span <= 150:
            up, lo_line = _line(highs), _line(lows)
            du, dl = up[1] * span, lo_line[1] * span          # change across the formation
            w0 = _at(up, first_i) - _at(lo_line, first_i)
            w1 = _at(up, last_i) - _at(lo_line, last_i)
            kind = _boundary_kind(du, dl, w0, w1, a)
            if kind:
                def upper_at(i, up=up, lo_line=lo_line):
                    return _at(up, i) if _at(up, i) > _at(lo_line, i) else None

                def lower_at(i, up=up, lo_line=lo_line):
                    return _at(lo_line, i) if _at(up, i) > _at(lo_line, i) else None
                bu = _breakout(rows, c, wait, upper_at, 1)
                bd = _breakout(rows, c, wait, lower_at, -1)
                picks = [x for x in ((bu, 1), (bd, -1)) if x[0] is not None]
                if picks:
                    b, direction = min(picks)
                    # A converging figure projects its opening height; a channel
                    # projects its own width.
                    target = rows[b]["close"] + direction * (w1 if kind.endswith("_channel") else w0)
                    stop = _at(lo_line, b) if direction > 0 else _at(up, b)
                    out.append(_signal(rows, kind, "chart", "bullish" if direction > 0 else "bearish", first_i, b,
                                       target, stop,
                                       points=[(p["i"], p["price"]) for p in last],
                                       lines=[("upper", first_i, _at(up, first_i), b, _at(up, b)),
                                              ("lower", first_i, _at(lo_line, first_i), b, _at(lo_line, b))],
                                       angles={"upper": _angle(up[1], a), "lower": _angle(lo_line[1], a)}))
    out.extend(_flags(rows, atrs))
    return _dedupe(out)


def _flags(rows: list[dict[str, Any]], atrs: list[float | None]) -> list[dict[str, Any]]:
    """A strong pole, then a short channel sloping against it, then a breakout.

    Flags are too small for the ZigZag's swings, so they are read off the bars:
    the pole is ≥ 4 ATR within ten sessions; the channel is the least-squares
    line through the closes after it, with its upper and lower edges parallel by
    construction (the "parallel boundaries" condition) and fitted only on
    sessions before the one tested for the breakout.
    """
    out: list[dict[str, Any]] = []
    n = len(rows)
    last_used = -1
    for p in range(10, n - 5):
        a = atrs[p]
        if not a or p <= last_used:
            continue
        for sign in (1, -1):
            base = min(range(p - 10, p), key=lambda j: sign * rows[j]["close"])
            pole = sign * (rows[p]["close"] - rows[base]["close"])
            extreme = rows[p]["high"] if sign > 0 else rows[p]["low"]
            if pole < 4 * a or any(sign * ((r["high"] if sign > 0 else r["low"]) - extreme) > 0
                                   for r in rows[p - 5:p]):
                continue
            for b in range(p + 5, min(n, p + 21)):
                window = rows[p:b]
                if any(sign * ((r["high"] if sign > 0 else r["low"]) - extreme) > 0 for r in window[1:]):
                    break                                   # a new extreme: no flag, the pole goes on
                deepest = min(sign * (r["low"] if sign > 0 else r["high"]) for r in window)
                if sign * extreme - deepest > 0.5 * pole:
                    break                                   # retraced too far to be a pause
                # A pennant: the highs falling and the lows rising, meeting —
                # a small symmetrical triangle hung on the pole.
                hl = _line([(p + j, r["high"]) for j, r in enumerate(window)])
                ll = _line([(p + j, r["low"]) for j, r in enumerate(window)])
                w_start, w_end = _at(hl, p) - _at(ll, p), _at(hl, b - 1) - _at(ll, b - 1)
                if hl[1] < 0 < ll[1] and 0 < w_end <= 0.6 * w_start and w_start <= 0.5 * pole:
                    level = _at(hl, b) if sign > 0 else _at(ll, b)
                    if sign * (rows[b]["close"] - level) > 0:
                        other = _at(ll, b) if sign > 0 else _at(hl, b)
                        out.append(_signal(rows, "bull_pennant" if sign > 0 else "bear_pennant", "chart",
                                           "bullish" if sign > 0 else "bearish", base, b,
                                           rows[b]["close"] + sign * pole, other,
                                           points=[(base, rows[base]["close"]), (p, rows[p]["close"])],
                                           lines=[("upper", p, _at(hl, p), b, _at(hl, b)),
                                                  ("lower", p, _at(ll, p), b, _at(ll, b))],
                                           angles={"upper": _angle(hl[1], a), "lower": _angle(ll[1], a),
                                                   "pole": _angle(pole / max(1, p - base), a)}))
                        last_used = b
                        break
                line = _line([(p + j, r["close"]) for j, r in enumerate(window)])
                if sign * line[1] > 0.1 * a:
                    continue                                # a flag leans against its pole
                if sign > 0:
                    edge = max(r["high"] - _at(line, p + j) for j, r in enumerate(window))
                    width = edge - min(r["low"] - _at(line, p + j) for j, r in enumerate(window))
                else:
                    edge = min(r["low"] - _at(line, p + j) for j, r in enumerate(window))
                    width = max(r["high"] - _at(line, p + j) for j, r in enumerate(window)) - edge
                if width > 0.5 * pole:
                    continue
                level = _at(line, b) + edge
                if sign * (rows[b]["close"] - level) > 0:
                    kind = "bull_flag" if sign > 0 else "bear_flag"
                    other = _at(line, b) + (edge - sign * width)
                    out.append(_signal(rows, kind, "chart", "bullish" if sign > 0 else "bearish", base, b,
                                       rows[b]["close"] + sign * pole, other,
                                       points=[(base, rows[base]["close"]), (p, rows[p]["close"])],
                                       lines=[("upper" if sign > 0 else "lower", p, _at(line, p) + edge, b, level),
                                              ("lower" if sign > 0 else "upper", p, _at(line, p) + edge - sign * width,
                                               b, other)],
                                       angles={"channel": _angle(line[1], a), "pole": _angle(pole / max(1, p - base), a)}))
                    last_used = b
                    break
    return out


def _dedupe(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One signal per (type, session) — overlapping pivot windows find the same breakout."""
    seen: set[tuple[str, int]] = set()
    out = []
    for s in sorted(signals, key=lambda s: (s["signal_index"], s["type"])):
        key = (s["type"], s["signal_index"])
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


# ── Evaluation ───────────────────────────────────────────────────────────────

def _forward(rows, entry_i, direction, target, stop, horizon):
    """Target-before-stop from the session after ``entry_i``; the stop wins a tie."""
    for j in range(entry_i + 1, min(len(rows), entry_i + horizon + 1)):
        hi, lo = rows[j]["high"], rows[j]["low"]
        if direction > 0:
            if lo <= stop:
                return "stop", j
            if hi >= target:
                return "target", j
        else:
            if hi >= stop:
                return "stop", j
            if lo <= target:
                return "target", j
    end = min(len(rows) - 1, entry_i + horizon)
    return ("open" if end < entry_i + horizon else "horizon"), end


def evaluate(rows: list[dict[str, Any]], signals: list[dict[str, Any]], *, horizon: int = 20,
             fee_bps: float = 15, slippage_bps: float = 20) -> list[dict[str, Any]]:
    """Each signal as it could have been acted on, with its chance level beside it."""
    cost = 2 * (fee_bps + slippage_bps) / 10_000
    memo: dict[tuple[int, int, int], float | None] = {}
    out = []
    for s in signals:
        entry_i = s["signal_index"] + 1
        if entry_i >= len(rows):
            out.append({**s, "outcome": "pending"})
            continue
        direction = 1 if s["direction"] == "bullish" else -1
        entry = rows[entry_i]["close"]
        # Target and stop are distances from the signal close; carried to the fill.
        up_d = abs(s["target"] - s["price"])
        dn_d = abs(s["price"] - s["stop"])
        target, stop = entry + direction * up_d, entry - direction * dn_d
        if dn_d <= 0 or up_d <= 0 or (direction > 0 and stop >= entry) or (direction < 0 and stop <= entry):
            out.append({**s, "outcome": "invalid"})
            continue
        outcome, exit_i = _forward(rows, entry_i, direction, target, stop, horizon)
        exit_price = target if outcome == "target" else stop if outcome == "stop" else rows[exit_i]["close"]
        move = direction * (exit_price / entry - 1) - cost
        out.append({**s, "entry_date": rows[entry_i]["date"], "entry": entry, "exit_date": rows[exit_i]["date"],
                    "exit_price": exit_price, "outcome": outcome, "directional_return_pct": move * 100,
                    "chance_pct": _chance(rows, direction, up_d / entry, dn_d / entry, horizon, memo)})
    return out


def _chance(rows, direction, up_frac, dn_frac, horizon, memo=None, stride=2):
    """How often the same target/stop distances are hit from an ordinary session.

    Distances are bucketed to a quarter of a percent: two signals asking about
    a 6.1 % and a 6.2 % target are asking the same question of the history, and
    re-walking ten years for each made a long series take seconds.
    """
    key = (direction, round(up_frac * 400), round(dn_frac * 400))
    if memo is not None and key in memo:
        return memo[key]
    up_frac, dn_frac = key[1] / 400, key[2] / 400
    if up_frac <= 0 or dn_frac <= 0:
        return None
    hits = total = 0
    for i in range(0, len(rows) - horizon - 1, stride):
        entry = rows[i]["close"]
        outcome, _ = _forward(rows, i, direction, entry * (1 + direction * up_frac),
                              entry * (1 - direction * dn_frac), horizon)
        if outcome in ("target", "stop"):
            total += 1
            hits += outcome == "target"
    result = hits / total * 100 if total else None
    if memo is not None:
        memo[key] = result
    return result


def summarize(evaluated: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per pattern type: how often the target came first, against chance."""
    by: dict[str, list[dict[str, Any]]] = {}
    for e in evaluated:
        if e.get("outcome") in ("target", "stop", "horizon"):
            by.setdefault(e["type"], []).append(e)
    out = {}
    for kind, items in sorted(by.items()):
        decided = [e for e in items if e["outcome"] in ("target", "stop")]
        rets = [e["directional_return_pct"] for e in items]
        # Chance is read over the same trades as the hit rate: those that reached
        # their target or their stop. Averaging it over every trade compared two
        # different populations and flattered the pattern.
        chances = [e["chance_pct"] for e in decided if e.get("chance_pct") is not None]
        out[kind] = {
            "signals": len(items),
            "decided": len(decided),
            "hit_rate_pct": (sum(e["outcome"] == "target" for e in decided) / len(decided) * 100) if decided else None,
            "chance_pct": mean(chances) if chances else None,
            "avg_return_pct": mean(rets) if rets else None,
            "median_return_pct": median(rets) if rets else None,
            "positive_pct": sum(r > 0 for r in rets) / len(rets) * 100 if rets else None,
        }
    return out


def long_only_backtest(rows: list[dict[str, Any]], evaluated: list[dict[str, Any]], *,
                       fee_bps: float = 15, slippage_bps: float = 20) -> dict[str, Any]:
    """Bullish signals traded one at a time, marked to market every session.

    The ТЗ's strategy block: share of winning trades, Sharpe and maximum
    drawdown, fees and slippage included. Long only — the exchange has no short.
    """
    fee, slip = fee_bps / 10_000, slippage_bps / 10_000
    trades = sorted((e for e in evaluated if e["direction"] == "bullish" and e.get("entry_date")
                     and e["outcome"] in ("target", "stop", "horizon")), key=lambda e: e["entry_date"])
    index = {r["date"]: i for i, r in enumerate(rows)}
    equity = [1.0] * len(rows)
    cash, busy_until, results = 1.0, -1, []
    held: tuple[int, float, float] | None = None       # (exit index, shares, exit price)
    starts = {}
    for t in trades:
        starts.setdefault(index[t["entry_date"]], t)
    for i, r in enumerate(rows):
        if held and i == held[0]:
            cash = held[1] * held[2] * (1 - slip) * (1 - fee)
            held = None
        if held is None and i > busy_until and i in starts:
            t = starts[i]
            exit_i, exit_price = index[t["exit_date"]], t["exit_price"]
            buy = r["close"] * (1 + slip)
            shares = cash * (1 - fee) / buy
            results.append((exit_price * (1 - slip) * (1 - fee)) / (buy / (1 - fee)) - 1)
            held, busy_until, cash = (exit_i, shares, exit_price), exit_i, 0.0
        equity[i] = cash + (held[1] * r["close"] if held else 0.0)
    peak, max_dd = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = min(max_dd, (v / peak - 1) * 100 if peak else 0.0)
    daily = [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity)) if equity[i - 1] > 0]
    vol = pstdev(daily) if len(daily) >= 2 else None
    return {
        "trades": len(results),
        "win_rate_pct": sum(x > 0 for x in results) / len(results) * 100 if results else None,
        "total_return_pct": (equity[-1] - 1) * 100 if rows else None,
        "max_drawdown_pct": max_dd,
        "sharpe": mean(daily) / vol * sqrt(250) if vol else None,
    }


# ── Cycles (ТЗ §2, optional) ─────────────────────────────────────────────────

def _cycle_stat(logp, periods_mask, np):
    """Strongest share of spectral power in the band, and its frequency index."""
    n = len(logp)
    t = np.arange(n)
    b, a = np.polyfit(t, logp, 1)
    x = (logp - (a + b * t)) * np.hanning(n)
    power = np.abs(np.fft.rfft(x)) ** 2
    band = power[periods_mask]
    total = band.sum()
    if total <= 0:
        return 0.0, 0
    k = int(np.argmax(band))
    return float(band[k] / total), k


def dominant_cycle(rows: list[dict[str, Any]], *, min_period: int = 10, max_sessions: int = 1024,
                   surrogates: int = 199, seed: int = 7) -> dict[str, Any]:
    """The strongest periodicity in the price, and whether chance explains it.

    The periodogram of a detrended log price always has a highest peak — a
    random walk has one too, and it sits at the long periods. So the peak is
    tested against surrogates: the same stock's daily returns in shuffled
    order, summed back into a price. That keeps every return and destroys any
    rhythm. ``p_value`` is the share of surrogates whose own peak was at least
    as dominant; only below 0.05 is the cycle called real. Deterministic: the
    shuffle is seeded.
    """
    import numpy as np

    closes = [r["close"] for r in rows][-max_sessions:]
    n = len(closes)
    if n < 128:
        return {"status": "NO_DATA", "sessions": n, "reason": "At least 128 sessions are required."}
    logp = np.log(np.asarray(closes, dtype=float))
    freqs = np.fft.rfftfreq(n)
    with np.errstate(divide="ignore"):
        periods = np.where(freqs > 0, 1 / np.where(freqs > 0, freqs, 1), np.inf)
    # At least three full cycles inside the window, or it is a trend, not a rhythm.
    mask = (periods >= min_period) & (periods <= n / 3)
    if mask.sum() < 3:
        return {"status": "NO_DATA", "sessions": n, "reason": "Window too short for a cycle band."}
    stat, k = _cycle_stat(logp, mask, np)
    period = float(periods[mask][k])

    rets = np.diff(logp)
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(surrogates):
        path = np.concatenate([[logp[0]], logp[0] + np.cumsum(rng.permutation(rets))])
        if _cycle_stat(path, mask, np)[0] >= stat:
            exceed += 1
    p_value = (exceed + 1) / (surrogates + 1)

    # Where the fitted sine stands today: sessions to its next crest and trough.
    t = np.arange(n)
    b, a = np.polyfit(t, logp, 1)
    resid = logp - (a + b * t)
    w = 2 * np.pi / period
    design = np.column_stack([np.sin(w * t), np.cos(w * t)])
    (cs, cc), *_ = np.linalg.lstsq(design, resid, rcond=None)
    phase = float(np.arctan2(cc, cs))                 # resid ≈ R·sin(w·t + phase)
    now = (w * (n - 1) + phase) % (2 * np.pi)
    to_peak = ((np.pi / 2 - now) % (2 * np.pi)) / w
    to_trough = ((3 * np.pi / 2 - now) % (2 * np.pi)) / w
    return {
        "status": "AVAILABLE", "sessions": n, "from": rows[-n]["date"], "to": rows[-1]["date"],
        "period_sessions": round(period, 1), "power_share": round(stat, 3),
        "amplitude_pct": round(float(np.hypot(cs, cc)) * 100, 2),
        "p_value": round(p_value, 3), "significant": p_value < 0.05,
        "next_peak_in": round(float(to_peak), 1), "next_trough_in": round(float(to_trough), 1),
        "surrogates": surrogates,
    }


# ── Entry point ──────────────────────────────────────────────────────────────

def analyse(points: Iterable[dict[str, Any]] | None, sensitivity: str | None = None,
            **overrides: float) -> dict[str, Any]:
    """Detect, evaluate and summarise one security's daily history."""
    cfg = {**DEFAULTS, **overrides}
    if sensitivity in SENSITIVITY:
        cfg["zigzag_atr"] = SENSITIVITY[sensitivity]
    rows = normalize(points)
    if len(rows) < 60:
        return {"status": "NO_DATA", "model_version": MODEL_VERSION, "observations": len(rows),
                "reason": "At least 60 confirmed sessions are required."}
    atrs = atr(rows, int(cfg["atr_days"]))
    pivots = zigzag(rows, atrs, cfg["zigzag_atr"], cfg["zigzag_min_pct"])
    signals = sorted(candle_patterns(rows, atrs) + chart_patterns(rows, atrs, pivots, int(cfg["breakout_wait"])),
                     key=lambda s: (s["signal_index"], s["type"]))
    evaluated = evaluate(rows, signals, horizon=int(cfg["horizon"]),
                         fee_bps=cfg["fee_bps"], slippage_bps=cfg["slippage_bps"])
    return {
        "status": "AVAILABLE", "model_version": MODEL_VERSION, "parameters": cfg,
        "period": {"from": rows[0]["date"], "to": rows[-1]["date"], "observations": len(rows)},
        "pivots": [{"date": rows[p["i"]]["date"], "price": p["price"], "kind": p["kind"],
                    "confirmed_date": rows[p["confirmed"]]["date"]} for p in pivots],
        "signals": evaluated,
        "summary": summarize(evaluated),
        "backtest": long_only_backtest(rows, evaluated, fee_bps=cfg["fee_bps"], slippage_bps=cfg["slippage_bps"]),
        # The same strategy on each family alone, so the page can quote the
        # one the reader has switched on.
        "backtest_by_family": {
            fam: long_only_backtest(rows, [e for e in evaluated if e["family"] == fam],
                                    fee_bps=cfg["fee_bps"], slippage_bps=cfg["slippage_bps"])
            for fam in ("chart", "candle")},
        "cycle": dominant_cycle(rows),
        "disclaimer": "Historical pattern statistics only; not a trading recommendation.",
    }
