"""A security's day statistics only ever move forward in time.

The market board joins two feeds: the live uzse row (price, its own day) and the
per-trade statistics the nightly collector pushes (turnover, trade count, largest
trade). When the two describe different sessions the page shows a turnover that
belongs to no quote — NGQS rendered 16.07's 251 246 UZS over 6 trades beside its
24.07 price of 23 900, a session whose real figures were 287 900 over 4.

Half of that is a display rule (``tradeStatsApply``, pinned in
tests/valuation.test.js). The other half is this one: the ingest must not write a
security's statistics backwards. The backfill path derives an untraded security's
"last trading day" from the board and asks openinfo for it, so a lagging board row
— or an archive that answers for the wrong date — could otherwise overwrite a
fresh session with an older one and make the display rule discard live data.
"""
from __future__ import annotations

import pytest

import reports_catalog as rc
import catalogue.market_store as catalogue_market_store
import catalogue.storage as catalogue_storage


@pytest.fixture()
def catalog_db(tmp_path, monkeypatch):
    path = tmp_path / "catalog.db"
    monkeypatch.setattr(catalogue_storage, "_catalog_db_path", lambda: str(path))
    conn = catalogue_storage.get_catalog_conn()
    conn.close()
    return str(path)


def _row(day: str, value: float, trades: int) -> dict:
    return {"isin": "UZ7042650000", "trade_date": day, "total_value": value,
            "total_qty": 14, "trade_count": trades, "avg_price": value / max(trades, 1),
            "close_price": 23900, "open_price": 20000, "high_price": 24000,
            "low_price": 20000}


def _stored() -> dict:
    return catalogue_market_store.get_all_trade_stats()["UZ7042650000"]


class TestTradeStatsAreMonotonic:
    def test_a_newer_session_replaces_the_stored_one(self, catalog_db) -> None:
        catalogue_market_store.bulk_upsert_trade_stats([_row("20260716", 251245.59, 6)])
        assert catalogue_market_store.bulk_upsert_trade_stats([_row("20260724", 287900.0, 4)]) == 1

        stored = _stored()
        assert stored["trade_date"] == "20260724"
        assert stored["total_value"] == pytest.approx(287900.0)
        assert stored["trade_count"] == 4

    def test_an_older_session_is_refused(self, catalog_db) -> None:
        catalogue_market_store.bulk_upsert_trade_stats([_row("20260724", 287900.0, 4)])
        # A backfill for a stale board date must not undo the live session.
        assert catalogue_market_store.bulk_upsert_trade_stats([_row("20260716", 251245.59, 6)]) == 0

        stored = _stored()
        assert stored["trade_date"] == "20260724"
        assert stored["total_value"] == pytest.approx(287900.0)

    def test_the_same_session_still_corrects_itself(self, catalog_db) -> None:
        # A re-run later in the day sees more executions of the same session; that
        # correction has to land, so the guard is >=, not >.
        catalogue_market_store.bulk_upsert_trade_stats([_row("20260724", 54000.0, 1)])
        assert catalogue_market_store.bulk_upsert_trade_stats([_row("20260724", 287900.0, 4)]) == 1
        assert _stored()["total_value"] == pytest.approx(287900.0)

    def test_a_dateless_row_cannot_wipe_a_stored_session(self, catalog_db) -> None:
        catalogue_market_store.bulk_upsert_trade_stats([_row("20260724", 287900.0, 4)])
        assert catalogue_market_store.bulk_upsert_trade_stats([_row("", 0.0, 0)]) == 0
        assert _stored()["trade_date"] == "20260724"

    def test_a_first_sighting_is_always_written(self, catalog_db) -> None:
        assert catalogue_market_store.bulk_upsert_trade_stats([_row("20260716", 251245.59, 6)]) == 1
        assert _stored()["trade_date"] == "20260716"
