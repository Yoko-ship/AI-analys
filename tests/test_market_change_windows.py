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


def _turnover_points(*triples: tuple[str, float, float | None]) -> list[dict]:
    return [{"d": date(int(s[:4]), int(s[4:6]), int(s[6:8])), "date": s,
             "close": c, "turnover": t}
            for s, c, t in triples]


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


class TestWindowTurnover:
    """«Топ ликвидности за месяц» is the month's sessions added up — not the
    session's figure reprinted under a heading that says a month."""

    def test_the_window_sums_every_session_inside_it(self) -> None:
        # A week back from the 17th is the 10th. The 8th is outside it: its
        # turnover belongs to the week before and must not be counted here.
        points = _turnover_points(("20260808", 100.0, 500.0), ("20260812", 110.0, 300.0),
                                  ("20260817", 120.0, 200.0))

        got = api._window_turnover(points, 7, date(2026, 8, 17))

        assert got == {"value": 500, "sessions": 2, "from": "20260812"}

    def test_a_session_on_the_cutoff_is_outside_the_window(self) -> None:
        """The same half-open span the change over it uses, so a sum and the
        percent beside it describe one stretch of calendar."""
        points = _turnover_points(("20260810", 100.0, 900.0), ("20260817", 120.0, 100.0))

        assert api._window_turnover(points, 7, date(2026, 8, 17)) == {
            "value": 100, "sessions": 1, "from": "20260817"}

    def test_carried_forward_sessions_are_not_counted(self) -> None:
        """The exchange repeats a close at zero quantity when nothing traded and
        the store writes turnover 0. Counting it would make `sessions` claim
        activity that did not happen — and `sessions` is what tells a reader
        whether the sum is a month of trading or one busy Tuesday inside it."""
        points = _turnover_points(("20260812", 100.0, 0.0), ("20260814", 100.0, None),
                                  ("20260817", 120.0, 250.0))

        got = api._window_turnover(points, 30, date(2026, 8, 17))

        assert got == {"value": 250, "sessions": 1, "from": "20260817"}

    def test_a_line_with_no_base_close_still_reports_its_turnover(self) -> None:
        """A history that starts inside the window yields no CHANGE (see above),
        but it did trade, and the liquidity panel must be able to rank it."""
        points = _turnover_points(("20260814", 100.0, 700.0), ("20260817", 130.0, 300.0))

        assert api._window_change(points, 7, date(2026, 8, 17)) is None
        assert api._window_turnover(points, 7, date(2026, 8, 17))["value"] == 1000

    def test_a_window_with_no_trading_yields_nothing(self) -> None:
        points = _turnover_points(("20260710", 100.0, 400.0), ("20260817", 100.0, 0.0))

        assert api._window_turnover(points, 7, date(2026, 8, 17)) is None

    def test_ytd_sums_from_the_first_of_january(self) -> None:
        points = _turnover_points(("20251230", 90.0, 900.0), ("20260105", 100.0, 40.0),
                                  ("20260817", 180.0, 60.0))

        got = api._window_turnover(points, None, date(2026, 8, 17))

        assert got == {"value": 100, "sessions": 2, "from": "20260105"}

    def test_no_history_yields_nothing(self) -> None:
        assert api._window_turnover([], 7, date(2026, 8, 17)) is None
