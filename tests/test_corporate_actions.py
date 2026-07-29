"""Price back-adjustment across splits and bonus issues (corporate_actions.py).

The numbers below are the real filings. Each ratio was confirmed against the share count
uzse.uz reports today, which equals the registered emissions summed exactly — so a change
to the table that breaks these totals is a change that would put the chart back into two
different units.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corporate_actions import CORPORATE_ACTIONS, actions_for, adjust_history, resolve_ticker  # noqa: E402


def point(date: str, close: float, **extra):
    return {"date": date, "open": close, "high": close, "low": close, "close": close,
            "trading_volume": 100.0, "trading_value": close * 100.0, **extra}


def test_alskom_three_fold_cliff_closes():
    """ALSM's April 1 495 and October 897 are the same stock; only the unit differed."""
    points, applied = adjust_history(
        [point("2025-04-03", 1495.0), point("2025-10-07", 897.0)], "ALSM")
    assert points[0]["close"] == pytest.approx(1495.0 / 3, rel=1e-6)
    assert points[1]["close"] == 897.0  # after both events — untouched
    assert [a["kind"] for a in applied] == ["split", "bonus"]
    assert all(a["points"] == 1 for a in applied)


def test_every_quoted_field_moves_together():
    raw = {"date": "2024-01-10", "open": 90.0, "high": 100.0, "low": 80.0,
           "close": 95.0, "change": -5.0, "trading_volume": 1000.0, "trading_value": 95000.0}
    (adjusted,), _ = adjust_history([raw], "ALKB")
    for field in ("open", "high", "low", "close", "change"):
        assert adjusted[field] == pytest.approx(raw[field] / 205, rel=1e-6)
    # Volume and turnover are quoted in shares and sums, not per share: left as printed.
    assert adjusted["trading_volume"] == 1000.0
    assert adjusted["trading_value"] == 95000.0
    assert raw["close"] == 95.0  # the caller's list is never mutated


def test_series_that_starts_after_the_event_is_untouched():
    """KASUP only resumed trading in 2025 — nothing to restate, and nothing to explain."""
    points, applied = adjust_history(
        [point("2025-11-03", 0.03), point("2026-02-02", 0.25)], "KASUP")
    assert [p["close"] for p in points] == [0.03, 0.25]
    assert applied == []


def test_ticker_without_actions_passes_through():
    points, applied = adjust_history([point("2020-01-02", 12.5)], "UZMK")
    assert points[0]["close"] == 12.5
    assert applied == []
    assert actions_for("UZMK") == ()


def test_dateless_point_is_left_raw():
    """A point that cannot be placed either side of the event stays as the feed sent it."""
    points, applied = adjust_history(
        [{"date": None, "close": 1495.0}, point("2025-04-03", 1495.0)], "ALSM")
    assert points[0]["close"] == 1495.0
    assert points[1]["close"] == pytest.approx(1495.0 / 3, rel=1e-6)
    assert all(a["points"] == 1 for a in applied)


def test_isin_resolves_when_the_feed_omits_the_ticker():
    assert resolve_ticker(None, "uz7045320007") == "ALSM"
    assert resolve_ticker("", "UZ7044760005") == "ALKB"
    assert resolve_ticker(None, "UZ7000000000") is None
    points, applied = adjust_history([point("2021-01-05", 10.0)], None, "UZ7038380000")
    assert points[0]["close"] == pytest.approx(1.0)
    assert applied[0]["kind"] == "split"


@pytest.mark.parametrize("ticker,expected", [
    ("ALSM", 3.0), ("ALSMP", 3.0),      # 2× redenomination then 1.5× out of own funds
    ("ALKB", 205.0), ("ALKBP", 205.0),  # 121× then 84 free shares per 121 held
    ("CBSK", 10.0), ("KASU", 100.0), ("KASUP", 100.0),
])
def test_cumulative_ratio_matches_the_registered_share_counts(ticker, expected):
    cumulative = 1.0
    for action in CORPORATE_ACTIONS[ticker]:
        cumulative *= action.ratio
    assert cumulative == pytest.approx(expected, rel=1e-9)


def test_actions_are_ordered_and_well_formed():
    for ticker, actions in CORPORATE_ACTIONS.items():
        dates = [a.ex_date for a in actions]
        assert dates == sorted(dates), ticker
        for action in actions:
            assert action.ratio > 1, ticker          # every event adds shares
            assert action.kind in {"split", "bonus"}, ticker
            assert action.source.startswith("https://"), ticker
