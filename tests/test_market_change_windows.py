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

        got = api._window_stats(points, 7, date(2026, 8, 17))

        assert (got["value"], got["sessions"], got["from"]) == (500, 2, "20260812")

    def test_a_session_on_the_cutoff_is_outside_the_window(self) -> None:
        """The same half-open span the change over it uses, so a sum and the
        percent beside it describe one stretch of calendar."""
        points = _turnover_points(("20260810", 100.0, 900.0), ("20260817", 120.0, 100.0))

        got = api._window_stats(points, 7, date(2026, 8, 17))

        assert (got["value"], got["sessions"], got["from"]) == (100, 1, "20260817")

    def test_carried_forward_sessions_are_not_counted(self) -> None:
        """The exchange repeats a close at zero quantity when nothing traded and
        the store writes turnover 0. Counting it would make `sessions` claim
        activity that did not happen — and `sessions` is what tells a reader
        whether the sum is a month of trading or one busy Tuesday inside it."""
        points = _turnover_points(("20260812", 100.0, 0.0), ("20260814", 100.0, None),
                                  ("20260817", 120.0, 250.0))

        got = api._window_stats(points, 30, date(2026, 8, 17))

        assert (got["value"], got["sessions"], got["from"]) == (250, 1, "20260817")

    def test_a_line_with_no_base_close_still_reports_its_turnover(self) -> None:
        """A history that starts inside the window yields no CHANGE (see above),
        but it did trade, and the liquidity panel must be able to rank it."""
        points = _turnover_points(("20260814", 100.0, 700.0), ("20260817", 130.0, 300.0))

        assert api._window_change(points, 7, date(2026, 8, 17)) is None
        assert api._window_stats(points, 7, date(2026, 8, 17))["value"] == 1000

    def test_a_window_with_no_trading_yields_nothing(self) -> None:
        points = _turnover_points(("20260710", 100.0, 400.0), ("20260817", 100.0, 0.0))

        assert api._window_stats(points, 7, date(2026, 8, 17)) is None

    def test_ytd_sums_from_the_first_of_january(self) -> None:
        points = _turnover_points(("20251230", 90.0, 900.0), ("20260105", 100.0, 40.0),
                                  ("20260817", 180.0, 60.0))

        got = api._window_stats(points, None, date(2026, 8, 17))

        assert (got["value"], got["sessions"], got["from"]) == (100, 2, "20260105")

    def test_no_history_yields_nothing(self) -> None:
        assert api._window_stats([], 7, date(2026, 8, 17)) is None


def _session(day: str, *, close: float, turnover: float | None = None,
             quantity: float | None = None, open_: float | None = None,
             high: float | None = None, low: float | None = None,
             trades: float | None = None, largest: float | None = None,
             largest_qty: float | None = None) -> dict:
    return {"d": date(int(day[:4]), int(day[4:6]), int(day[6:8])), "date": day,
            "close": close, "turnover": turnover, "quantity": quantity,
            "open": open_, "high": high, "low": low, "trade_count": trades,
            "largest_value": largest, "largest_qty": largest_qty}


class TestWindowSessionFigures:
    """A period is summarised the way a session is: it has an opening price, a
    high, a low, an average share price, an average deal and a biggest deal.

    Customer, 19.08.2026: choosing «за год» must CHANGE these figures, not merely
    show the change beside unchanged ones.
    """

    def test_the_period_is_the_sessions_inside_it_added_up(self) -> None:
        points = [
            _session("20260808", close=100.0, turnover=999.0, quantity=9.0),  # outside
            _session("20260812", close=110.0, turnover=300.0, quantity=3.0,
                     open_=105.0, high=112.0, low=104.0, trades=6, largest=200.0,
                     largest_qty=2.0),
            _session("20260817", close=120.0, turnover=200.0, quantity=2.0,
                     open_=118.0, high=125.0, low=100.0, trades=4, largest=150.0,
                     largest_qty=1.0),
        ]

        got = api._window_stats(points, 7, date(2026, 8, 17))

        assert got["value"] == 500, "turnover is the window's sessions summed"
        assert got["qty"] == 5
        assert got["trades"] == 10
        assert got["open"] == 105.0, "the FIRST traded session inside the window opens it"
        assert got["close"] == 120.0
        assert got["high"] == 125.0
        assert got["low"] == 100.0
        assert got["vwap"] == 100.0, "500 сумов bought 5 bumag"
        assert got["avg_trade"] == 50, "500 сумов across 10 deals"
        assert got["largest_value"] == 200
        assert got["largest_qty"] == 2
        assert got["largest_pct"] == 40.0
        assert got["largest_from"] == "20260812"
        assert "approx" not in got, "every session inside carried its own high and low"

    def test_a_session_that_carries_no_extremes_stands_in_with_its_close(self) -> None:
        """openinfo's archive reaches further back than the day statistics do, so
        old sessions are banked as closes alone. The close IS a traded price of
        that session, so it bounds the extreme — and the answer says it is a bound."""
        points = [
            _session("20260805", close=90.0, turnover=100.0, quantity=1.0),
            _session("20260817", close=120.0, turnover=200.0, quantity=2.0,
                     high=125.0, low=118.0),
        ]

        got = api._window_stats(points, 30, date(2026, 8, 17))

        assert got["high"] == 125.0
        assert got["low"] == 90.0, "the older session's close is the lowest price seen"
        assert got["approx"] is True

    def test_a_figure_no_session_answers_is_absent_not_zero(self) -> None:
        """Sessions banked before the day statistics existed carry no deal count
        and no largest deal. A column with nothing behind it prints a dash — it
        does not print a nought that claims the period had no deals."""
        points = [_session("20260817", close=120.0, turnover=200.0, quantity=2.0)]

        got = api._window_stats(points, 30, date(2026, 8, 17))

        assert "trades" not in got and "avg_trade" not in got
        assert "largest_value" not in got
        assert got["vwap"] == 100.0, "the average share price needs only сумы and bumagi"

    def test_the_average_deal_is_measured_inside_the_sessions_that_can_say(self) -> None:
        """Only the sessions banked with the day statistics beside them know how
        many deals they held. Dividing the WHOLE window's сумы by that partial
        count would overstate the average deal by exactly the sessions it could
        not see — over a year, most of them."""
        points = [
            # An old session: сумы and bumagi, no deal count (openinfo's archive).
            _session("20260210", close=90.0, turnover=9_000.0, quantity=100.0),
            _session("20260817", close=120.0, turnover=1_000.0, quantity=10.0,
                     trades=4, largest=700.0),
        ]

        got = api._window_stats(points, 365, date(2026, 8, 17))

        assert got["value"] == 10_000, "the turnover is still the whole window"
        assert got["trades"] == 4
        assert got["avg_trade"] == 250, "1 000 сумов across the 4 deals we can see"
        assert got["detail_sessions"] == 1, "one session of two could answer"

    def test_a_session_with_quantity_but_no_turnover_still_counts(self) -> None:
        points = [_session("20260817", close=120.0, quantity=2.0)]

        got = api._window_stats(points, 30, date(2026, 8, 17))

        assert got["sessions"] == 1 and got["qty"] == 2
        assert "vwap" not in got, "no сумы, no volume-weighted price"


class TestTheEndpointServesThePeriodsFigures:
    """The payload the board restates its rows from, end to end."""

    def test_every_window_carries_its_own_session_figures(self, monkeypatch) -> None:
        from fastapi.testclient import TestClient

        monkeypatch.setattr(api, "get_securities_map",
                            lambda: {"ZZZZ": {"isin": "UZ7000000001"}})
        monkeypatch.setattr(api, "get_quote_history", lambda codes, days: {
            "UZ7000000001": [
                {"trade_date": "20260601", "close_price": 100.0, "quantity": 10.0,
                 "turnover": 1000.0, "open_price": 98.0, "high_price": 101.0,
                 "low_price": 97.0, "trade_count": 5, "largest_value": 600.0,
                 "largest_qty": 6.0},
                {"trade_date": "20260817", "close_price": 120.0, "quantity": 5.0,
                 "turnover": 600.0, "open_price": 119.0, "high_price": 130.0,
                 "low_price": 118.0, "trade_count": 3, "largest_value": 400.0,
                 "largest_qty": 3.0},
            ]})

        with TestClient(api.app) as client:
            body = client.get("/api/market/changes").json()

        row = body["changes"]["ZZZZ"]
        month = row["stats"]["1m"]
        assert month["value"] == 600 and month["sessions"] == 1
        assert month["high"] == 130.0 and month["low"] == 118.0
        assert month["trades"] == 3 and month["avg_trade"] == 200
        half = row["stats"]["6m"]
        assert half["value"] == 1600, "both sessions are inside half a year"
        assert half["high"] == 130.0 and half["low"] == 97.0
        assert half["open"] == 98.0, "the older session opens the window"
        assert half["largest_value"] == 600 and half["largest_from"] == "20260601"
        # The key the liquidity panel has read since 2026-08-18 keeps answering.
        assert row["turnover"]["6m"] == {"value": 1600, "sessions": 2, "from": "20260601"}
