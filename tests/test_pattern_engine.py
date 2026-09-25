"""Pattern detection on hand-built price paths, where the right answer is known.

ТЗ §5.1: every detector is checked on a synthetic chart drawn to contain
exactly one instance of its figure. The causality test is the one that matters
most: a pattern that appears only once later sessions are known is a
repainting pattern, and no chart built on it can be trusted.
"""
from datetime import date, timedelta

import pattern_engine as pe


def _path(waypoints, step=1.0, spread=0.2):
    """Daily bars walking linearly through ``waypoints`` about ``step`` per session."""
    closes = [float(waypoints[0])]
    for a, b in zip(waypoints, waypoints[1:]):
        n = max(1, round(abs(b - a) / step))
        closes.extend(a + (b - a) * k / n for k in range(1, n + 1))
    start = date(2024, 1, 1)
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        bars.append({"date": (start + timedelta(days=i)).isoformat(), "open": o,
                     "high": max(o, c) + spread, "low": min(o, c) - spread, "close": c,
                     "value": 1_000_000})
    return bars


def _redate(bars):
    start = date(2024, 1, 1)
    return [{**b, "date": (start + timedelta(days=i)).isoformat()} for i, b in enumerate(bars)]


def _calm(level, sessions=60):
    """A quiet stretch before the figure, so the history is long enough to read."""
    return _path([level] + [level + (0.8 if k % 2 else 0) for k in range(sessions // 2)] + [level], step=0.4)


def _types(result, family=None):
    return [s["type"] for s in result["signals"] if family is None or s["family"] == family]


def test_short_histories_are_refused():
    assert pe.analyse(_path([100, 110], step=1))["status"] == "NO_DATA"


def test_zigzag_pivots_are_confirmed_after_their_extreme_and_alternate():
    rows = pe.normalize(_path([100, 130, 105, 135, 100, 125]))
    pivots = pe.zigzag(rows, pe.atr(rows), 2.0, 3.0)
    kinds = [p["kind"] for p in pivots]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))
    assert all(p["confirmed"] > p["i"] for p in pivots)
    assert [round(p["price"], 1) for p in pivots if p["kind"] == "H"][:2] == [130.2, 135.2]


def test_nothing_repaints_when_history_is_cut():
    """Signals found on a prefix are exactly the full run's signals up to that date."""
    bars = _path([100, 118, 104, 118, 96, 110, 98, 124, 108, 124, 100, 130, 105, 131, 90])
    full = pe.analyse(bars)["signals"]
    assert full, "the path must produce signals for this test to mean anything"
    for cut in range(80, len(bars), 7):
        part = pe.analyse(bars[:cut])
        if part["status"] != "AVAILABLE":
            continue
        last = bars[cut - 1]["date"]
        want = {(s["type"], s["signal_date"]) for s in full if s["signal_date"] <= last}
        got = {(s["type"], s["signal_date"]) for s in part["signals"]}
        assert got == want, f"cut at {last}"


def test_double_top_signals_on_the_break_of_the_trough():
    bars = _path([100] * 2 + [100, 120, 104, 120, 95])
    result = pe.analyse(_redate(_path([90, 100]) + bars[1:]))
    tops = [s for s in result["signals"] if s["type"] == "double_top"]
    assert len(tops) == 1
    top = tops[0]
    assert top["direction"] == "bearish"
    assert top["price"] < 104.2                       # the close that broke the neckline
    assert abs(top["lines"][0]["from"]["price"] - top["lines"][0]["to"]["price"]) < 1e-9


def test_double_bottom_is_the_mirror():
    result = pe.analyse(_path([130, 120, 100, 116, 100, 125]))
    assert "double_bottom" in _types(result)
    assert all(s["direction"] == "bullish" for s in result["signals"] if s["type"] == "double_bottom")


def test_head_and_shoulders_needs_the_neckline_to_break():
    formed = _path([95, 100, 115, 105, 126, 105, 115, 106])
    assert "head_shoulders" not in _types(pe.analyse(_redate(formed + _path([106, 108])[1:])))
    broken = pe.analyse(_path([95, 100, 115, 105, 126, 105, 115, 92]))
    hs = [s for s in broken["signals"] if s["type"] == "head_shoulders"]
    assert len(hs) == 1 and hs[0]["direction"] == "bearish"
    assert hs[0]["target"] < hs[0]["price"] < hs[0]["stop"]
    assert len(hs[0]["points"]) == 5


def test_inverse_head_and_shoulders():
    result = pe.analyse(_path([130, 125, 110, 120, 99, 120, 110, 133]))
    assert "inverse_head_shoulders" in _types(result)


def test_ascending_triangle_breaks_out_upward_with_measured_angles():
    result = pe.analyse(_path([95, 100, 120, 104, 120, 109, 120, 113, 130]))
    tri = [s for s in result["signals"] if s["type"] == "ascending_triangle"]
    assert tri and tri[0]["direction"] == "bullish"
    angles = tri[0]["angles"]
    assert abs(angles["upper"]) < 5 < angles["lower"]   # a flat roof over a rising floor


def test_bull_flag_after_a_pole():
    bars = _calm(100) + _path([100, 130], step=5)[1:] + _path([130, 126], step=0.5)[1:] + _path([126, 136], step=2.5)[1:]
    flags = [s for s in pe.analyse(_redate(bars))["signals"] if s["type"] == "bull_flag"]
    assert flags and flags[0]["direction"] == "bullish"
    assert flags[0]["angles"]["channel"] <= 0          # the channel leans against the pole


def _bars(spec):
    start = date(2024, 1, 1)
    return [{"date": (start + timedelta(days=i)).isoformat(), "open": o, "high": h, "low": lo, "close": c}
            for i, (o, h, lo, c) in enumerate(spec)]


def test_bullish_engulfing_only_after_a_decline():
    decline = [(120 - 2 * i, 120.5 - 2 * i, 117.5 - 2 * i, 118 - 2 * i) for i in range(12)]
    engulf = [(96.5, 97, 95.5, 96), (95.5, 99, 95.2, 98.5)]
    lead = _calm(120)
    bars = _redate(lead + _bars(decline + engulf) + _path([98.5, 110], step=0.5)[1:])
    result = pe.analyse(bars)
    kinds = {s["type"]: s for s in result["signals"]}
    assert "bullish_engulfing" in kinds
    assert kinds["bullish_engulfing"]["signal_date"] == bars[len(lead) + len(decline) + 1]["date"]


def test_flat_sessions_never_form_candles():
    """A day that printed one price has no body or shadow to read."""
    flat = [{"date": b["date"], "open": b["close"], "high": b["close"], "low": b["close"], "close": b["close"]}
            for b in _path([100, 80, 100, 80, 100, 80], step=1)]
    assert _types(pe.analyse(flat), "candle") == []


def test_signals_are_executed_on_the_next_session_with_costs():
    result = pe.analyse(_redate(_path([95, 100, 115, 105, 126, 105, 115, 104]) + _path([104, 70], step=3)[1:]))
    hs = next(s for s in result["signals"] if s["type"] == "head_shoulders")
    assert hs["entry_date"] > hs["signal_date"]
    assert hs["outcome"] == "target"                   # the path fell through the target
    # A bearish pattern that was right earns a positive DIRECTIONAL return,
    # less two sides of fee and slippage.
    gross = (1 - hs["exit_price"] / hs["entry"]) * 100
    assert abs(hs["directional_return_pct"] - (gross - 0.7)) < 1e-9
    assert hs["chance_pct"] is not None


def test_summary_and_backtest_shapes():
    result = pe.analyse(_path([100, 120, 104, 120, 95, 120, 100, 118, 96, 130, 110, 130, 100, 140]))
    for stats in result["summary"].values():
        assert stats["signals"] >= stats["decided"]
    bt = result["backtest"]
    assert set(bt) == {"trades", "win_rate_pct", "total_return_pct", "max_drawdown_pct", "sharpe"}
    assert bt["max_drawdown_pct"] <= 0


def test_triple_top_needs_three_equal_highs_and_the_break():
    result = pe.analyse(_path([95, 100, 120, 104, 120, 105, 120, 92]))
    triples = [s for s in result["signals"] if s["type"] == "triple_top"]
    assert len(triples) == 1 and triples[0]["direction"] == "bearish"
    assert len(triples[0]["points"]) == 5
    assert "head_shoulders" not in _types(result)        # no head: three equal tops


def test_rising_wedge_is_two_rising_edges_meeting():
    result = pe.analyse(_path([90, 95, 110, 100, 116, 108, 119, 113, 121, 105]))
    wedge = [s for s in result["signals"] if s["type"] == "rising_wedge"]
    assert wedge, _types(result)
    assert wedge[0]["angles"]["lower"] > wedge[0]["angles"]["upper"] > 0


def test_ascending_channel_has_parallel_rising_edges():
    result = pe.analyse(_path([90, 95, 110, 100, 115, 105, 120, 110, 125, 100]))
    chan = [s for s in result["signals"] if s["type"] == "ascending_channel"]
    assert chan, _types(result)
    up, lo = chan[0]["angles"]["upper"], chan[0]["angles"]["lower"]
    assert up > 0 and lo > 0 and abs(up - lo) < 15


def test_bull_pennant_converges_after_a_pole():
    body = _path([100, 130], step=5)[1:]
    # Highs falling and lows rising: a small triangle on top of the pole.
    tri = _bars([(128, 130, 126, 127), (127, 129.5, 126.3, 128.5), (128.5, 129, 126.6, 127.2),
                 (127.2, 128.6, 126.9, 128.2), (128.2, 128.3, 127.2, 127.6), (127.6, 128.1, 127.4, 127.9)])
    breakout = _path([127.9, 137], step=3)[1:]
    bars = _redate(_calm(100) + body + tri + breakout)
    kinds = _types(pe.analyse(bars))
    assert "bull_pennant" in kinds, kinds


def test_every_signal_carries_a_box_around_its_formation():
    result = pe.analyse(_path([95, 100, 115, 105, 126, 105, 115, 92]))
    for s in result["signals"]:
        box = s["box"]
        assert box["from"] == s["start_date"] and box["to"] == s["signal_date"]
        assert box["low"] <= s["price"] <= box["high"] or s["family"] == "chart"


def test_sensitivity_presets_change_how_much_is_found():
    bars = _path([100, 118, 104, 118, 96, 110, 98, 124, 108, 124, 100, 130, 105, 131, 90, 112, 99, 121])
    high = len(pe.analyse(bars, sensitivity="high")["signals"])
    low = len(pe.analyse(bars, sensitivity="low")["signals"])
    assert high >= low
    assert pe.analyse(bars, sensitivity="low")["parameters"]["zigzag_atr"] == pe.SENSITIVITY["low"]


def test_cycle_is_found_only_where_there_is_one():
    import numpy as np
    rng = np.random.default_rng(1)
    walk = np.cumsum(rng.normal(0, 0.01, 800))
    start = date(2020, 1, 1)

    def bars(logp):
        return [{"date": (start + timedelta(days=i)).isoformat(), "close": float(np.exp(v))}
                for i, v in enumerate(logp)]

    noise = pe.dominant_cycle(pe.normalize(bars(walk)))
    assert noise["status"] == "AVAILABLE" and not noise["significant"]
    cycled = pe.dominant_cycle(pe.normalize(bars(walk * 0.3 + 0.06 * np.sin(2 * np.pi * np.arange(800) / 40))))
    assert cycled["significant"] and abs(cycled["period_sessions"] - 40) < 2
    assert 0 <= cycled["next_peak_in"] < 40
