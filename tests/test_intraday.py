"""The hourly series: the trade feed's roll-up, its store, and the 1Д/1Н endpoint.

The bars come from uzse.uz/trade_results — the exchange's own execution feed.
Each record's ``header`` (a fixed-width protocol line) embeds the trade's
moment as {YYYYMMDD}{HHMMSS}; there is no trade_datetime field, and the quote
page's executions log was rejected as a source because it cannot say which
trades were negotiated (T1) deals.

Pinned here:

  * the moment is read from the header and VALIDATED against the record's own
    trade_date — a member number that happens to read like a date must not
    stamp a trade;
  * a negotiated deal never prints an hour's OHLC (the HMKB 14.08 lesson);
  * open/close follow the stamp, never input order — the feed lists newest
    first and pages interleave;
  * the store is deduplicated, idempotent and pruned — same PG constraints as
    catalog_quote_history;
  * the endpoint serves ISO-with-hour dates, which is what lets a series mixed
    with daily closes still sort as strings.
"""
from __future__ import annotations

import reports_catalog as subject_reports_catalog
import catalogue.market_store as catalogue_market_store
import catalogue.storage as catalogue_storage
import server.market.history as subject_server_market_history

import datetime as dt
import importlib

import pytest
from fastapi.testclient import TestClient

import reports_catalog as rc
import catalogue.market_store as catalogue_market_store
import catalogue.storage as catalogue_storage
import trade_stats as ts

api = importlib.import_module("api")

ISIN = "UZ7011340005"


def _trade(hhmmss: str, price, qty, value, *, day="20260817", board="G1",
           isin=ISIN, tid=None):
    return {
        "id": tid, "issue_code": isin, "trade_date": day, "board_id": board,
        "header": f"0910DATS00000057485009010090101{day}{hhmmss}039G 0000",
        "trade_price": str(price), "trade_quantity": qty, "trading_value": str(value),
    }


class TestTheFeedRollUp:
    def test_rolls_executions_up_into_hourly_bars(self):
        # Newest first, as the feed pages them. 10:xx traded 100→104→101.
        bars = ts.hourly_bars([
            _trade("110500", 102, 5, 510),
            _trade("105900", 101, 10, 1010),
            _trade("103000", 104, 2, 208),
            _trade("100000", 100, 3, 300),
        ])
        assert [b["hour"] for b in bars] == [10, 11]
        ten = bars[0]
        assert (ten["isin"], ten["date"]) == (ISIN, "20260817")
        # Open is the hour's EARLIEST stamp, close its latest — never input order.
        assert (ten["open"], ten["high"], ten["low"], ten["close"]) == (100, 104, 100, 101)
        assert ten["quantity"] == pytest.approx(15)
        assert ten["turnover"] == pytest.approx(1518)

    def test_a_negotiated_deal_never_prints_a_bar(self):
        """HMKB 14.08: one T1 block at 55,00 under a 98-сум session — folding it
        in would hand the hour a low the order book never stood at."""
        bars = ts.hourly_bars([
            _trade("100100", 98, 10, 980),
            _trade("100200", 55, 2_200_000, 121_000_000, board="T1"),
        ])
        assert len(bars) == 1
        assert bars[0]["low"] == pytest.approx(98)
        assert bars[0]["quantity"] == pytest.approx(10)

    def test_the_header_moment_must_agree_with_the_trade_date(self):
        # A header whose only date-like digits belong to ANOTHER day (or to a
        # member/account number) stamps nothing — the trade is dropped, not
        # misfiled onto a neighbouring session.
        t = _trade("100000", 100, 1, 100)
        t["header"] = "0910DATS0000005748500901009010120260816100000039G 0000"
        assert ts.trade_moment(t) is None
        assert ts.hourly_bars([t]) == []

    def test_two_sessions_stay_two_dates(self):
        bars = ts.hourly_bars([
            _trade("101000", 50, 1, 50, day="20260515"),
            _trade("154000", 49, 1, 49, day="20260514"),
        ])
        assert [b["date"] for b in bars] == ["20260514", "20260515"]

    def test_garbage_prices_do_not_invent_a_bar(self):
        assert ts.hourly_bars([
            _trade("100000", 0, 1, 0),
            _trade("100000", "", 1, 100),
        ]) == []


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A scratch catalog DB, so the suite never writes the real one."""
    import db

    monkeypatch.setattr(db, "APP_DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(catalogue_storage, "APP_DATA_DIR", tmp_path, raising=False)
    catalogue_storage.get_catalog_conn().close()
    return tmp_path


def _day(offset: int = 0) -> str:
    return (dt.date.today() - dt.timedelta(days=offset)).strftime("%Y%m%d")


def _bars():
    return [
        {"isin": ISIN, "trade_date": _day(), "hour": 10, "open": 100, "high": 104,
         "low": 100, "close": 101, "quantity": 15, "turnover": 1518},
        {"isin": ISIN, "trade_date": _day(), "hour": 11, "open": 101, "high": 102,
         "low": 101, "close": 102, "quantity": 5, "turnover": 510},
        {"isin": ISIN, "trade_date": _day(1), "hour": 15, "close": 99},
    ]


class TestTheStore:
    def test_a_repeated_bar_in_one_batch_is_written_once(self, store):
        # The same hour arrives twice when a page is read twice in a run; PG
        # refuses one statement touching a key twice, so the batch dedupes.
        rows = _bars() + [{"isin": ISIN, "trade_date": _day(), "hour": 10, "close": 101.5}]
        assert catalogue_market_store.bulk_upsert_intraday_history(rows) == 3
        series = catalogue_market_store.get_intraday_history(ISIN, days=7)
        assert len(series) == 3
        # Last write wins: the log only grows through the day.
        assert series[-2]["close_price"] == pytest.approx(101.5)

    def test_rerunning_the_collector_does_not_duplicate_a_bar(self, store):
        catalogue_market_store.bulk_upsert_intraday_history(_bars())
        catalogue_market_store.bulk_upsert_intraday_history(_bars())
        assert len(catalogue_market_store.get_intraday_history(ISIN, days=7)) == 3

    def test_bars_older_than_the_keep_window_are_pruned(self, store):
        old = (dt.date.today() - dt.timedelta(days=catalogue_market_store.INTRADAY_KEEP_DAYS + 5)).strftime("%Y%m%d")
        catalogue_market_store.bulk_upsert_intraday_history(
            [{"isin": ISIN, "trade_date": old, "hour": 12, "close": 1}])
        catalogue_market_store.bulk_upsert_intraday_history(_bars())
        days = {r["trade_date"] for r in catalogue_market_store.get_intraday_history(ISIN, days=catalogue_market_store.INTRADAY_KEEP_DAYS)}
        assert old not in days

    def test_a_row_with_no_key_is_dropped_not_stored(self, store):
        assert catalogue_market_store.bulk_upsert_intraday_history([
            {"isin": "", "trade_date": _day(), "hour": 10, "close": 1},
            {"isin": ISIN, "trade_date": "not a date", "hour": 10, "close": 1},
            {"isin": ISIN, "trade_date": _day(), "hour": 99, "close": 1},
            {"isin": ISIN, "trade_date": _day(), "hour": "x", "close": 1},
        ]) == 0
        assert catalogue_market_store.get_intraday_history(ISIN) == []

    def test_the_window_is_calendar_days(self, store):
        """1Н means THIS week — stretching a quiet security's old bars under
        that label would date the chart wrong; the chart falls back to closes."""
        catalogue_market_store.bulk_upsert_intraday_history(_bars())
        assert len(catalogue_market_store.get_intraday_history(ISIN, days=1)) == 2


class TestTheEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch):
        async def _isin(_ticker):
            return ISIN

        monkeypatch.setattr(subject_server_market_history, '_resolve_isin', _isin)
        monkeypatch.setattr(catalogue_market_store, 'get_intraday_history', lambda isin, days: [
            {"trade_date": "20260817", "hour": 10, "open_price": 100.0, "high_price": 104.0,
             "low_price": 100.0, "close_price": 101.0, "quantity": 15.0, "turnover": 1518.0},
        ])
        return TestClient(api.app)

    def test_serves_iso_dates_with_the_hour(self, client):
        """"2026-08-17T10:00" — sorts as a string against a daily "2026-08-17"."""
        body = client.get("/api/intraday/HMKB").json()
        assert body["ok"] is True
        point = body["points"][0]
        assert point["date"] == "2026-08-17T10:00"
        assert point["close"] == pytest.approx(101.0)
        assert point["value"] == pytest.approx(1518.0)

    def test_an_unknown_ticker_is_a_404(self, monkeypatch):
        async def _no_isin(_ticker):
            return None

        monkeypatch.setattr(subject_server_market_history, '_resolve_isin', _no_isin)
        assert TestClient(api.app).get("/api/intraday/NOPE").status_code == 404
