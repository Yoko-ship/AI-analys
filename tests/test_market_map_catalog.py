"""Market map and instrument catalog (ТЗ v1.2 §9 and §4).

Pinned against what the live board actually contains: of 81 tiles, 4 have trades
but no last price, 10 never traded, 2 are dormant listings and 18 rest on fewer
than five trades. Every one of those used to be a coloured tile that voted in its
sector's average.

The catalog is assembled from five references holding 78 / 3 / 81 / 68 / 107
tickers. They are merged into one universe of 110 without dropping anything, and
every disagreement is recorded rather than resolved by read order.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import heatmap
import instruments
import invariants


def row(ticker, last=None, close=None, trades=None, turnover=None, qty=None, **kw):
    return {"ticker": ticker, "last_price": last, "close_price": close,
            "trade_count": trades, "volume": turnover, "quantity": qty,
            "sector": kw.pop("sector", "finance"), "type": kw.pop("type", "stock"), **kw}


# ---------------------------------------------------------------------------
# Tiles
# ---------------------------------------------------------------------------

class TestTiles:
    def test_change_is_computed_on_unrounded_prices(self):
        """KASU trades at 0.01 sum on 232 trades; rounding erases every move."""
        assert heatmap.day_change(0.0125, 0.01) == pytest.approx(25.0)
        assert heatmap.day_change(round(0.0125, 2), round(0.01, 2)) == pytest.approx(0.0)

    def test_trades_without_a_price_are_not_a_hundred_percent_fall(self):
        """UTYK: 8 trades on 34 050 000 sums and no last price."""
        tile = heatmap.classify_tile(row("UTYK", last=None, close=5000.0,
                                         trades=8, turnover=34_050_000.0))
        assert tile["status"] == heatmap.TILE_NO_PRICE
        assert tile["change_pct"] is None
        assert tile["reason"]

    def test_no_session_is_distinct_from_an_unchanged_price(self):
        quiet = heatmap.classify_tile(row("SANE", last=None, close=None))
        flat = heatmap.classify_tile(row("X", last=100.0, close=100.0, trades=9, qty=50))
        assert quiet["status"] == heatmap.TILE_NOT_TRADED and quiet["change_pct"] is None
        assert flat["status"] == heatmap.TILE_OK and flat["change_pct"] == 0.0

    def test_a_dormant_listing_says_so(self):
        tile = heatmap.classify_tile(row("OLD", last=None, close=None, inactive=True))
        assert tile["status"] == heatmap.TILE_INACTIVE

    def test_a_single_trade_is_marked_low_confidence(self):
        """UQEQ led the whole screen's "top gainers" on one trade of one share."""
        tile = heatmap.classify_tile(row("UQEQ", last=30_720.0, close=25_600.0,
                                         trades=1, qty=1, turnover=30_720.0))
        assert tile["change_pct"] == pytest.approx(20.0)
        assert tile["confidence"] == "low"

    def test_a_liquid_tile_is_not_marked(self):
        tile = heatmap.classify_tile(row("NMKB", last=101.0, close=100.0,
                                         trades=860, qty=5000, turnover=98_400_000.0))
        assert tile["confidence"] == "normal"

    def test_day_statistics_fill_in_what_the_board_row_lacks(self):
        tile = heatmap.classify_tile(row("A", last=110.0, close=100.0),
                                     {"trade_count": 40, "total_qty": 900,
                                      "total_value": 5_000_000.0})
        assert tile["trades"] == 40 and tile["turnover"] == pytest.approx(5_000_000.0)
        assert tile["confidence"] == "normal"


# ---------------------------------------------------------------------------
# Sector aggregation
# ---------------------------------------------------------------------------

class TestSectors:
    def test_sector_move_is_weighted_by_turnover(self):
        tiles = [
            heatmap.classify_tile(row("BIG", last=101.0, close=100.0, trades=800,
                                      qty=9000, turnover=99_000_000.0)),   # +1 %
            heatmap.classify_tile(row("TINY", last=120.0, close=100.0, trades=1,
                                      qty=1, turnover=100.0)),             # +20 %
        ]
        got = heatmap.aggregate_sector(tiles)
        assert got["weighting"] == "turnover"
        # A simple mean would say +10.5 %; almost all the money moved 1 %.
        assert got["change_pct"] == pytest.approx(1.0, abs=0.01)

    def test_priceless_tiles_do_not_vote(self):
        tiles = [
            heatmap.classify_tile(row("A", last=110.0, close=100.0, trades=50,
                                      qty=100, turnover=1000.0)),
            heatmap.classify_tile(row("B", last=None, close=None)),
            heatmap.classify_tile(row("C", last=None, close=100.0, trades=8, turnover=500.0)),
        ]
        got = heatmap.aggregate_sector(tiles)
        assert got["change_pct"] == pytest.approx(10.0)
        assert got["tiles_total"] == 3 and got["tiles_counted"] == 1
        assert got["tiles_no_price"] == 1 and got["tiles_not_traded"] == 1

    def test_a_sector_with_no_priced_tile_has_no_number(self):
        got = heatmap.aggregate_sector([heatmap.classify_tile(row("A", last=None, close=None))])
        assert got["change_pct"] is None and got["tiles_counted"] == 0

    def test_zero_turnover_falls_back_to_a_mean_and_admits_it(self):
        tiles = [heatmap.classify_tile(row("A", last=110.0, close=100.0)),
                 heatmap.classify_tile(row("B", last=90.0, close=100.0))]
        got = heatmap.aggregate_sector(tiles)
        assert got["weighting"] == "equal_no_turnover"
        assert got["change_pct"] == pytest.approx(0.0)

    def test_build_reports_how_many_tiles_entered_each_number(self):
        board = [row("A", last=110.0, close=100.0, trades=9, qty=90, turnover=1000.0),
                 row("B", last=None, close=None, sector="energy")]
        got = heatmap.build_heatmap(board, trade_date="2026-07-31")
        assert got["counts"]["tiles"] == 2 and got["counts"]["ok"] == 1
        assert {s["name"] for s in got["sectors"]} == {"finance", "energy"}
        assert got["total"]["tiles_counted"] == 1


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

class TestCatalog:
    def test_every_source_contributes_and_nothing_is_dropped(self):
        got = instruments.build_catalog(
            securities={"A": {"isin": "UZ1", "name": "A", "sector": "finance"}},
            board=[{"ticker": "B", "last_trade_date": "2026-07-31"}],
            financials={"C": {}}, ratios={"D": {}})
        assert {i["ticker"] for i in got["items"]} == {"A", "B", "C", "D"}
        assert got["source_counts"] == {"securities": 1, "listings": 0, "board": 1,
                                        "financials": 1, "ratios": 1}

    def test_a_sector_disagreement_is_recorded_not_silently_resolved(self):
        got = instruments.build_catalog(
            securities={"UTGAP": {"sector": "transport"}},
            sectors={"UTGAP": "logistics"})
        sector_issues = [d for d in got["discrepancies"] if d["field"] == "sector"]
        assert len(sector_issues) == 1
        assert got["items"][0]["sector"] == "transport"        # documented precedence

    def test_activity_follows_trading_not_the_registry_flag(self):
        today = date(2026, 8, 1)
        old = (today - timedelta(days=200)).isoformat()
        recent = (today - timedelta(days=3)).isoformat()
        got = instruments.build_catalog(
            securities={"OLD": {"last_trade_date": old}, "NEW": {"last_trade_date": recent}},
            today=today)
        by = {i["ticker"]: i for i in got["items"]}
        assert by["OLD"]["is_active"] is False and by["OLD"]["days_since_trade"] == 200
        assert by["NEW"]["is_active"] is True

    def test_the_three_date_spellings_all_parse(self):
        today = date(2026, 8, 1)
        got = instruments.build_catalog(
            securities={"A": {"last_trade_date": "31.07.2026"},
                        "B": {"last_trade_date": "2026-07-31"},
                        "C": {"last_trade_date": "20260731"}},
            today=today)
        assert {i["last_trade_date"] for i in got["items"]} == {"2026-07-31"}

    def test_trading_today_beats_a_stale_stored_date(self):
        today = date(2026, 8, 1)
        got = instruments.build_catalog(
            securities={"A": {"last_trade_date": "2020-01-01"}},
            board=[{"ticker": "A", "trade_count": 12}], today=today)
        assert got["items"][0]["is_active"] is True

    def test_bonds_keep_their_class(self):
        got = instruments.build_catalog(securities={"XB": {"type": "bond"}})
        assert got["items"][0]["share_class"] == "bond"


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

class TestInvariants:
    def test_classes_disagreeing_on_a_multiple_is_blocking(self):
        found = invariants.check_multiples_agree_across_classes({
            "acme": {"tickers": ["A", "AP"],
                     "multiples": {"pe": {"value": 5.0}, "pb": {"value": 1.0}}},
        })
        assert found == []

    def test_a_published_out_of_range_multiple_is_caught(self):
        found = invariants.check_multiples_in_range([
            {"ticker": "X", "pe": {"value": 1000.0}, "pb": {"value": 1.0},
             "roe": {"value": 10715.0}},
        ])
        codes = {f["code"] for f in found}
        assert "MUL-02" in codes and "MUL-03" in codes
        assert all(f["severity"] == invariants.SEVERITY_BLOCKING for f in found)

    def test_a_multiple_from_an_unverified_statement_is_caught(self):
        found = invariants.check_invalid_statements_are_suppressed([
            {"ticker": "TGPG", "validation": {"valid": False, "reasons": ["..."]},
             "pe": {"value": 8.0}, "pb": {"value": 1.0}},
        ])
        assert [f["code"] for f in found] == ["FIN-01", "FIN-01"]

    def test_map_findings(self):
        payload = heatmap.build_heatmap([
            row("UTYK", last=None, close=5000.0, trades=8, turnover=34_050_000.0),
        ])
        found = invariants.check_map(payload)
        assert "MKT-03" in {f["code"] for f in found}

    def test_a_broken_check_does_not_take_the_report_down(self):
        def boom():
            raise RuntimeError("source unavailable")

        report = invariants.run([("ok", lambda: []), ("boom", boom)])
        assert report["checks_run"] == 2
        assert report["checks_failed"][0]["check"] == "boom"
        assert report["ok"] is False

    def test_an_empty_report_is_the_good_outcome(self):
        report = invariants.run([("ok", lambda: [])])
        assert report["ok"] is True and report["findings"] == []
