"""Negotiated deals stay out of the session (HMKB 14.08.2026).

One T1 execution — 2,2 млрд бумаг по 55,00 — was summed into HMKB's day
statistics: turnover 121,5 млрд against the bulletin's 82,9 млн, a stored low
of 55 the exchange never printed, a VWAP of 55,02 outside the day's range.
The exchange's own bulletin aggregates the auction board (G1) only, and so
must we. The deal itself is real money and stays visible — in its own fields,
never inside a session number.
"""
from __future__ import annotations

from datetime import date

import pytest

import bonds
from trade_stats import _aggregate


def g1(price, qty, n, dt="2026-08-14T10:00:00"):
    return {"board_id": "G1", "market_id": "STK", "trade_price": price,
            "trade_quantity": qty, "trading_value": price * qty,
            "trade_datetime": dt, "trade_number": n, "id": n}


HMKB_DAY = [
    g1(99.99, 100_000, 1, "2026-08-14T09:30:00"),
    g1(95.5, 300_000, 2, "2026-08-14T11:00:00"),
    # the block: negotiated board, a price the order book never held
    {"board_id": "T1", "market_id": "STK", "trade_price": 55.0,
     "trade_quantity": 2_207_636_364, "trading_value": 121_420_000_020.0,
     "trade_datetime": "2026-08-14T11:05:46", "trade_number": 3, "id": 3},
    g1(99.0, 439_168, 4, "2026-08-14T13:00:00"),
]


class TestAggregatePartition:
    def test_session_numbers_come_from_the_auction_board_only(self):
        st = _aggregate("UZ7011340005", HMKB_DAY, "20260814")
        assert st["total_qty"] == pytest.approx(839_168)
        assert st["total_value"] == pytest.approx(
            99.99 * 100_000 + 95.5 * 300_000 + 99.0 * 439_168)
        assert st["trade_count"] == 3
        # The low the exchange actually printed — not the negotiated 55.
        assert st["low_price"] == pytest.approx(95.5)
        assert st["close_price"] == pytest.approx(99.0)
        assert st["vwap"] == pytest.approx(st["total_value"] / st["total_qty"], abs=0.005)

    def test_the_block_is_recorded_apart_not_erased(self):
        st = _aggregate("UZ7011340005", HMKB_DAY, "20260814")
        assert st["block_count"] == 1
        assert st["block_qty"] == pytest.approx(2_207_636_364)
        assert st["block_value"] == pytest.approx(121_420_000_020.0)

    def test_largest_trade_is_the_largest_eligible_one(self):
        """99,93% of the day's money was the block — a 'largest trade' share
        computed over it says nothing about the session."""
        st = _aggregate("UZ7011340005", HMKB_DAY, "20260814")
        assert st["largest_value"] == pytest.approx(99.0 * 439_168)
        assert st["largest_pct_value"] <= 100.0

    def test_a_block_only_day_is_not_a_session(self):
        """IQMK5B8 13.08: one T1 deal, nothing on the auction board."""
        st = _aggregate("UZ", [HMKB_DAY[2]], "20260813")
        assert st["trade_count"] == 0
        assert st["total_qty"] == 0
        assert st["close_price"] is None and st["low_price"] is None
        assert st["block_value"] == pytest.approx(121_420_000_020.0)

    def test_unmarked_executions_stay_in_the_session(self):
        """A feed without board_id cannot be split — counted in, loudly logged,
        never silently dropped."""
        bare = [{"trade_price": 100.0, "trade_quantity": 10, "trading_value": 1000.0,
                 "trade_number": 1, "id": 1}]
        st = _aggregate("UZ", bare, "20260814")
        assert st["trade_count"] == 1
        assert st["total_value"] == pytest.approx(1000.0)
        assert st["block_count"] == 0


class TestBondsApplyDayStats:
    ROW = {"ticker": "IQMK5B8", "type": "bond", "last_price": 1_037_753.42,
           "close_price": 1_030_000.0, "last_trade_date": "2026-08-11"}

    def test_a_block_only_day_does_not_advance_the_session(self):
        """The negotiated 1 069 393,45 must not become the row's market price."""
        stats = {"trade_date": "20260813", "total_qty": 0, "trade_count": 0,
                 "close_price": None, "block_value": 128_327_214_000.0,
                 "block_qty": 120_000.0}
        out = bonds.apply_day_stats(self.ROW, stats)
        assert out["last_price"] == pytest.approx(1_037_753.42)
        assert out["last_trade_date"] == "2026-08-11"
        assert out.get("volume") is None
        # but the deal itself is not hidden
        assert out["block_value"] == pytest.approx(128_327_214_000.0)
        assert out["block_date"] == "2026-08-13"

    def test_a_real_session_still_applies_and_carries_its_block(self):
        stats = {"trade_date": "20260814", "total_qty": 839_168.0,
                 "trade_count": 878, "total_value": 82_881_324.87,
                 "close_price": 99.0, "block_value": 121_420_000_020.0,
                 "block_qty": 2_207_636_364.0}
        out = bonds.apply_day_stats(self.ROW, stats)
        assert out["volume"] == pytest.approx(82_881_324.87)
        assert out["last_trade_date"] == "2026-08-14"
        assert out["block_value"] == pytest.approx(121_420_000_020.0)

    def test_no_stats_no_change(self):
        assert bonds.apply_day_stats(self.ROW, None) == self.ROW
