"""The board must be able to notice its own disagreement with the exchange.

Every mismatch so far shared a shape: it produced a plausible number instead of an
error, so the only detector was a person comparing our board to the exchange's
bulletin. A registry price from last week divides as happily as a previous close;
a feed carrying 78 of 122 securities answers 200; a page whose markup moved parses
to None and is skipped in silence.

Each test here is one of those historical failures, replayed as data, asserting
that the audit now names it.
"""
from __future__ import annotations

import pytest

from market_audit import audit_session

DAY = "20260731"


def _stat(value: float = 30720.0, qty: float = 1.0, day: str = DAY) -> dict:
    return {"trade_date": day, "total_value": value, "total_qty": qty, "trade_count": 1}


def _quote(value: float = 30720.0, qty: float = 1.0, day: str = DAY) -> dict:
    return {"trade_date": day, "turnover": value, "quantity": qty, "ticker": "UQEQ",
            "close_price": 30720.0, "prev_close": 25600.0}


def _row(**over) -> dict:
    row = {"isin": "UZ7042540003", "ticker": "UQEQ", "last_price": 30720.0,
           "close_price": 25600.0, "last_trade_date": "2026-07-31"}
    row.update(over)
    return row


def _failed(verdict) -> list[str]:
    return [c["name"] for c in verdict["checks"] if not c["ok"]]


class TestASessionThatAgrees:
    def test_a_clean_session_passes(self) -> None:
        verdict = audit_session({"UZ7042540003": _stat()}, {"UZ7042540003": _quote()}, [_row()])

        assert verdict["ok"] is True
        assert verdict["trade_date"] == DAY
        assert (verdict["audited"], verdict["quoted"], verdict["on_board"]) == (1, 1, 1)

    def test_a_security_that_did_not_trade_is_not_audited(self) -> None:
        """Only securities with executions have a session to agree about."""
        verdict = audit_session(
            {"UZ7042540003": _stat(), "UZ7012480008": _stat(0.0, 0.0)},
            {"UZ7042540003": _quote()}, [_row()])

        assert verdict["ok"] is True
        assert verdict["audited"] == 1

    def test_rounding_between_the_two_paths_is_not_a_disagreement(self) -> None:
        """The page prints a rounded total; the feed sums exact executions."""
        verdict = audit_session({"UZ7042540003": _stat(4_954_916.68)},
                                {"UZ7042540003": _quote(4_954_917.0)}, [_row()])

        assert verdict["ok"] is True


class TestTheFailuresItWouldHaveCaught:
    def test_a_security_the_mirror_never_carried(self) -> None:
        """KFSKP, EQQU: they traded, and the board had no row for them."""
        verdict = audit_session({"UZ7042540003": _stat()}, {"UZ7042540003": _quote()}, [])

        assert verdict["ok"] is False
        assert "board_carries_the_session" in _failed(verdict)
        assert verdict["checks"][1]["offenders"] == ["UQEQ"]

    def test_a_row_still_showing_last_weeks_session(self) -> None:
        """UQEQ priced from the registry's 24.07 trade while 31.07 had closed."""
        verdict = audit_session({"UZ7042540003": _stat()}, {"UZ7042540003": _quote()},
                                [_row(last_trade_date="2026-07-24", last_price=32000.0)])

        assert "board_carries_the_session" in _failed(verdict)

    def test_a_page_that_stopped_parsing(self) -> None:
        """Markup drift makes the quote pass skip a security in silence."""
        verdict = audit_session({"UZ7042540003": _stat()}, {}, [_row()])

        assert "quotes_cover_the_session" in _failed(verdict)

    def test_a_quote_left_behind_on_an_older_session(self) -> None:
        verdict = audit_session({"UZ7042540003": _stat()},
                                {"UZ7042540003": _quote(day="20260730")}, [_row()])

        assert "quotes_cover_the_session" in _failed(verdict)

    def test_turnover_from_another_session(self) -> None:
        """NGQS once showed 16.07's turnover beside its 24.07 price."""
        verdict = audit_session({"UZ7042650000": _stat(251_245.59, 6)},
                                {"UZ7042650000": _quote(287_900.0, 4)},
                                [_row(isin="UZ7042650000", ticker="NGQS")])

        assert _failed(verdict) == ["turnover_agrees_with_the_executions",
                                    "quantity_agrees_with_the_executions"]

    def test_a_row_that_cannot_state_a_change(self) -> None:
        """A traded security with no previous close renders an em-dash where the
        exchange published a percentage."""
        verdict = audit_session({"UZ7042540003": _stat()}, {"UZ7042540003": _quote()},
                                [_row(close_price=None)])

        assert "every_traded_row_states_a_change" in _failed(verdict)

    def test_a_zero_previous_close_is_not_a_denominator(self) -> None:
        verdict = audit_session({"UZ7042540003": _stat()}, {"UZ7042540003": _quote()},
                                [_row(close_price=0)])

        assert "every_traded_row_states_a_change" in _failed(verdict)


class TestWhatItMustNotReport:
    def test_a_deliberately_suppressed_ticker_is_not_a_gap(self) -> None:
        """A denylisted line is absent from the board on purpose."""
        verdict = audit_session({"UZ7042540003": _stat()}, {"UZ7042540003": _quote()},
                                [_row(ticker="UQEQ")], denylist={"UQEQ"})

        assert verdict["ok"] is True
        assert verdict["audited"] == 0

    def test_no_session_at_all_is_not_a_failure(self) -> None:
        """Sunday: the two-day trade feed holds nothing to audit."""
        verdict = audit_session({}, {}, [])

        assert verdict["ok"] is True
        assert verdict["trade_date"] is None

    @pytest.mark.parametrize("stored", ["2026-07-31", "31.07.2026", "20260731"])
    def test_every_date_shape_in_the_pipeline_is_the_same_day(self, stored) -> None:
        """The registry writes ISO, the live feed DD.MM.YYYY, the cache YYYYMMDD."""
        verdict = audit_session({"UZ7042540003": _stat()}, {"UZ7042540003": _quote()},
                                [_row(last_trade_date=stored)])

        assert verdict["ok"] is True


class TestASessionStillBeingTraded:
    """The 13:00 run reads the feed, then the pages, while the day goes on.

    On 2026-08-04 it summed 68 securities' executions and then read pages that
    had kept trading — 16 "disagreements" that were all settled by 16:10 and
    reported nothing but the six minutes between the two reads. A page ahead of
    the feed is the session continuing; a page BEHIND it is still wrong.
    """

    def test_a_page_ahead_of_the_feed_is_the_session_continuing(self) -> None:
        verdict = audit_session({"UZ7042540003": _stat(4_096_850.0, 79)},
                                {"UZ7042540003": _quote(4_403_867.0, 86)},
                                [_row()], today=DAY)

        assert verdict["ok"] is True
        assert verdict["session_open"] is True
        assert verdict["still_trading"] == ["UQEQ"]

    def test_a_page_behind_the_feed_is_wrong_even_mid_session(self) -> None:
        """More executions than the exchange itself reports cannot be explained."""
        verdict = audit_session({"UZ7042540003": _stat(4_403_867.0, 86)},
                                {"UZ7042540003": _quote(4_096_850.0, 79)},
                                [_row()], today=DAY)

        assert _failed(verdict) == ["turnover_agrees_with_the_executions",
                                    "quantity_agrees_with_the_executions"]

    def test_a_closed_session_still_has_to_agree_exactly(self) -> None:
        """Once the day has turned both sides are final — the 08:00 run's check."""
        verdict = audit_session({"UZ7042540003": _stat(4_096_850.0, 79)},
                                {"UZ7042540003": _quote(4_403_867.0, 86)},
                                [_row()], today="20260801")

        assert verdict["session_open"] is False
        assert _failed(verdict) == ["turnover_agrees_with_the_executions",
                                    "quantity_agrees_with_the_executions"]
