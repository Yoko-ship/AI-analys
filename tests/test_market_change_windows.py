"""The board's change columns: a change is a statement about two dates.

`/api/market/changes` measures every period the board offers from the stored
settled closes. The base is the last close AT OR BEFORE the cutoff — the price
the security was worth then — and each figure names the session it came from,
because on this market the earlier date is rarely the one the label implies.
"""
from __future__ import annotations

from datetime import date

import pytest

import api


def _points(*pairs: tuple[str, float]) -> list[dict]:
    return [{"d": date(int(s[:4]), int(s[4:6]), int(s[6:8])), "date": s, "close": c}
            for s, c in pairs]


class TestWindowChange:
    def test_the_base_is_the_last_close_before_the_cutoff(self) -> None:
        # A week back from the 17th is the 10th. The 8th is the last close at or
        # before it; the 15th is the first one after — taking that would print
        # two sessions' move under a label that says a week.
        points = _points(("20260801", 100.0), ("20260808", 110.0),
                         ("20260815", 120.0), ("20260817", 121.0))

        got = api._window_change(points, 7, date(2026, 8, 17))

        assert got == {"pct": 10.0, "from": "20260808", "base": 110.0}

    def test_a_close_exactly_on_the_cutoff_is_the_base(self) -> None:
        points = _points(("20260810", 100.0), ("20260817", 150.0))

        assert api._window_change(points, 7, date(2026, 8, 17))["from"] == "20260810"

    def test_a_history_that_starts_inside_the_window_yields_nothing(self) -> None:
        """An issuer whose first stored session is inside the window has not
        moved over it — it was not there. A figure off the earliest close would
        be a change over an unknown, shorter span."""
        points = _points(("20260814", 100.0), ("20260817", 130.0))

        assert api._window_change(points, 7, date(2026, 8, 17)) is None

    def test_ytd_measures_from_the_first_of_january(self) -> None:
        points = _points(("20251230", 90.0), ("20260105", 100.0), ("20260817", 180.0))

        got = api._window_change(points, None, date(2026, 8, 17))

        assert got["from"] == "20251230", "the last close of the old year IS the base"
        assert got["pct"] == 100.0

    def test_a_fall_keeps_its_sign(self) -> None:
        points = _points(("20260710", 200.0), ("20260817", 150.0))

        assert api._window_change(points, 30, date(2026, 8, 17))["pct"] == -25.0

    def test_a_zero_base_yields_nothing(self) -> None:
        # A zero close is the mirror's filler, not a price; dividing by it would
        # print an infinite move.
        points = _points(("20260710", 0.0), ("20260817", 150.0))

        assert api._window_change(points, 30, date(2026, 8, 17)) is None

    def test_no_history_yields_nothing(self) -> None:
        assert api._window_change([], 7, date(2026, 8, 17)) is None

    @pytest.mark.parametrize(("code", "span"), [("1w", 7), ("1m", 30), ("3m", 91),
                                               ("6m", 182), ("1y", 365), ("ytd", None)])
    def test_every_offered_window_has_a_span(self, code, span) -> None:
        assert api.MARKET_CHANGE_WINDOWS[code] == span
