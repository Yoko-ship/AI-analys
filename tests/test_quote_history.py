"""The daily-close store, and the one request that draws a list of sparklines.

`catalog_quotes` keeps only the latest session, so a price SERIES existed
nowhere we could reach and every sparkline cost one live openinfo request per
ticker. `catalog_quote_history` is what the collector was already fetching and
throwing away — the exchange page's table of settled sessions.

Two properties matter more than the rest and are pinned here:

  * the batch is deduplicated and idempotent — PostgreSQL refuses an ON CONFLICT
    that touches one key twice in a statement, and the same session legitimately
    arrives twice in a run;
  * the two sources date differently (the exchange page YYYYMMDD, openinfo ISO)
    and a series half in each orders by its leading digits, which draws a
    scrambled line rather than failing.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import reports_catalog as rc

api = importlib.import_module("api")

ISIN_A = "UZ7047110000"
ISIN_B = "UZ7036730008"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A scratch catalog DB, so the suite never writes the real one."""
    import db

    monkeypatch.setattr(db, "APP_DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(rc, "APP_DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(rc, "CATALOG_DB", str(tmp_path / "catalog.db"), raising=False)
    rc.get_catalog_conn().close()
    return tmp_path


def _rows():
    return [
        {"isin": ISIN_A, "trade_date": "20260807", "close_price": 12000, "quantity": 79740},
        {"isin": ISIN_A, "trade_date": "2026-08-06", "close_price": 10000, "quantity": 0},
        {"isin": ISIN_A, "trade_date": "05.08.2026", "close_price": 9800, "quantity": 12},
        {"isin": ISIN_B, "trade_date": "20260807", "close_price": 88000},
    ]


class TestTheStore:
    def test_normalises_every_date_form_the_two_sources_use(self, store):
        rc.bulk_upsert_quote_history(_rows())
        days = [r["trade_date"] for r in rc.get_quote_history([ISIN_A])[ISIN_A]]
        # Chronological, which it can only be if all three parsed to one form.
        assert days == ["20260805", "20260806", "20260807"]

    def test_a_repeated_session_in_one_batch_is_written_once(self, store):
        rows = _rows() + [{"isin": ISIN_A, "trade_date": "20260807", "close_price": 12345}]
        n = rc.bulk_upsert_quote_history(rows)
        assert n == 4
        series = rc.get_quote_history([ISIN_A])[ISIN_A]
        assert len(series) == 3
        # Last write wins: a later read of the same day is more settled.
        assert series[-1]["close_price"] == 12345

    def test_rerunning_the_collector_does_not_duplicate_a_session(self, store):
        rc.bulk_upsert_quote_history(_rows())
        rc.bulk_upsert_quote_history(_rows())
        assert len(rc.get_quote_history([ISIN_A])[ISIN_A]) == 3

    def test_keeps_the_sessions_the_exchange_carried_forward(self, store):
        """A flat day IS what the security did; dropping it compresses time."""
        rc.bulk_upsert_quote_history(_rows())
        series = rc.get_quote_history([ISIN_A])[ISIN_A]
        assert [r["quantity"] for r in series] == [12, 0, 79740]

    def test_drops_a_row_with_no_isin_or_no_readable_day(self, store):
        n = rc.bulk_upsert_quote_history([
            {"isin": "", "trade_date": "20260807", "close_price": 1},
            {"isin": ISIN_A, "trade_date": "not a date", "close_price": 1},
            {"isin": ISIN_A, "close_price": 1},
        ])
        assert n == 0
        assert rc.get_quote_history([ISIN_A]) == {}

    def test_the_window_counts_sessions_not_calendar_days(self, store):
        """A quiet security must not come back empty and read as 'no data'."""
        rc.bulk_upsert_quote_history(_rows())
        assert len(rc.get_quote_history([ISIN_A], days=2)[ISIN_A]) == 2

    def test_asks_for_many_securities_at_once(self, store):
        rc.bulk_upsert_quote_history(_rows())
        got = rc.get_quote_history([ISIN_A, ISIN_B, "UZ0000000000"])
        assert set(got) == {ISIN_A, ISIN_B}

    def test_an_empty_request_touches_nothing(self, store):
        assert rc.bulk_upsert_quote_history([]) == 0
        assert rc.get_quote_history([]) == {}


class TestTheEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch):
        monkeypatch.setattr(api, "get_securities_map",
                            lambda: {"UZTL": {"isin": ISIN_A}, "TGPG": {"isin": ISIN_B}})
        monkeypatch.setattr(api, "get_quote_history", lambda isins, days: {
            ISIN_A: [{"trade_date": "20260806", "close_price": 10000},
                     {"trade_date": "20260807", "close_price": 12000}],
        })
        return TestClient(api.app)

    def test_serves_compact_pairs(self, client):
        body = client.get("/api/quotes/series?tickers=UZTL&days=30").json()
        assert body["ok"] is True
        assert body["series"]["UZTL"] == [["20260806", 10000], ["20260807", 12000]]

    def test_a_ticker_with_no_stored_session_is_absent_not_flat(self, client):
        """No line beats an invented one — TGPG resolves but has no history."""
        body = client.get("/api/quotes/series?tickers=UZTL,TGPG").json()
        assert "TGPG" not in body["series"]
        assert "UZTL" in body["series"]

    def test_an_unknown_ticker_does_not_fail_the_whole_list(self, client):
        body = client.get("/api/quotes/series?tickers=UZTL,NOPE").json()
        assert body["ok"] is True
        assert list(body["series"]) == ["UZTL"]

    def test_no_tickers_is_an_empty_answer_not_an_error(self, client):
        body = client.get("/api/quotes/series").json()
        assert body["ok"] is True and body["series"] == {}
