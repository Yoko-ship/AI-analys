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

    def test_bond_row_carries_the_block_through_to_the_response(self):
        """apply_day_stats attaches the fields; bond_row rebuilds its dict with
        fixed keys, so without an explicit passthrough the API drops them."""
        stats = {"trade_date": "20260813", "total_qty": 0, "trade_count": 0,
                 "close_price": None, "block_value": 128_327_214_000.0,
                 "block_qty": 120_000.0}
        row = bonds.bond_row({**self.ROW, "isin": "UZ6056887AH6"},
                             stats=stats, board_day=date(2026, 8, 14))
        assert row["block_value"] == pytest.approx(128_327_214_000.0)
        assert row["block_qty"] == pytest.approx(120_000.0)
        assert row["block_date"] == "2026-08-13"
        # and the session itself still belongs to the last real trading day
        assert row["last_trade_date"] == "2026-08-11"


class TestTheNcBoardIsOffSession:
    """ORFI 24.08.2026 / INFB 28.08.2026: four executions each on board NC, at
    the nominal, the same member on both sides — 883,8 and 146,1 млрд that the
    exchange's own daily history leaves at zero. Not a session."""

    ORFI_DAY = [
        {"board_id": "NC", "market_id": "STK", "trade_price": 1250.0,
         "trade_quantity": q, "trading_value": 1250.0 * q,
         "trade_datetime": f"2026-08-24T1{n}:00:00", "trade_number": n, "id": n}
        for n, q in enumerate((197_991_742, 404_127_226, 26_253_671, 78_704_046), 1)
    ]

    def test_an_nc_only_day_has_no_session_figures(self):
        st = _aggregate("UZ7055870008", self.ORFI_DAY, "20260824")
        assert st["trade_count"] == 0 and st["total_value"] == 0 and not st["total_qty"]
        assert st["close_price"] is None
        assert st["block_count"] == 4
        assert st["block_value"] == pytest.approx(883_845_856_250.0)

    def test_an_nc_only_day_is_never_banked_as_a_session(self):
        from catalogue.market_store import trade_stats_as_history
        st = _aggregate("UZ7055870008", self.ORFI_DAY, "20260824")
        live = _aggregate("UZ7011340005", HMKB_DAY, "20260814")
        banked = trade_stats_as_history([st, live])
        assert [r["isin"] for r in banked] == ["UZ7011340005"]


def test_the_banked_nc_days_are_purged_once_and_nothing_else(tmp_path, monkeypatch):
    """The rows banked before the fix: the COALESCE upsert cannot blank them."""
    import catalogue.market_store as store
    import catalogue.schema as schema
    import catalogue.storage as storage

    monkeypatch.setattr(storage, "_catalog_db_path", lambda: str(tmp_path / "catalog.db"))
    conn = storage.get_catalog_conn()
    schema._init_schema(conn)
    with conn:
        for isin, day in (("UZ7055870008", "20260824"), ("UZ7055870008", "20210727"),
                          ("UZ7055560005", "20260828")):
            conn.execute("INSERT INTO catalog_quote_history (isin, trade_date, close_price, turnover) "
                         "VALUES (?,?,?,?)", (isin, day, 1.0, 1.0))
        conn.execute("INSERT INTO catalog_trade_stats (isin, trade_date) VALUES (?,?)",
                     ("UZ7055560005", "20260828"))
    conn.close()

    assert store.purge_off_session_days() == {"catalog_quote_history": 2, "catalog_trade_stats": 1}
    assert store.purge_off_session_days() == {}
    conn = storage.get_catalog_conn()
    left = [(r["isin"], r["trade_date"]) for r in conn.execute("SELECT isin, trade_date FROM catalog_quote_history")]
    conn.close()
    assert left == [("UZ7055870008", "20210727")]
