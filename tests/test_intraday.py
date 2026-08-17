"""The hourly series: the executions log, its store, and the 1Д/1Н endpoint.

uzse.uz stamps every execution with its time on the security's own quote page —
"17 авг., 16:02" — and keeps that log only while the page still shows the
session. There is no archive of it anywhere on the exchange, so the hourly
chart exists exactly as far back as the collector has banked these bars.

Pinned here:

  * the log parses into hourly OHLC bars in page order reversed (the page is
    newest-first, an hour's open is its EARLIEST trade);
  * the yearless timestamp is dated correctly, including a December row read in
    January;
  * the store is deduplicated, idempotent and pruned — same PG constraints as
    catalog_quote_history;
  * the endpoint serves ISO-with-hour dates, which is what lets a series mixed
    with daily closes still sort as strings.
"""
from __future__ import annotations

import datetime as dt
import importlib

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

import reports_catalog as rc
import uzse_quotes as uq

api = importlib.import_module("api")

ISIN = "UZ7011340005"


def _table(rows: list[tuple[str, str, str, str, str]]):
    body = "".join(
        f"<tr><td>{a}</td><td>{b}</td><td>{c}</td><td>{d}</td><td>{e}</td></tr>"
        for a, b, c, d, e in rows)
    html = ("<table><tr><th>Время</th><th>Цена</th><th>Изменение</th>"
            f"<th>Кол-во ЦБ</th><th>Объём торгов (UZS)</th></tr>{body}</table>")
    return BeautifulSoup(html, "html.parser").find("table")


class TestTheLogParse:
    def test_rolls_the_log_up_into_hourly_bars(self):
        # Newest first, as the page prints it. 10:xx traded 100→104→101.
        bars = uq._hourly_bars(_table([
            ("17 авг., 11:05", "102", "▲ 2", "5", "510"),
            ("17 авг., 10:59", "101", "▲ 1", "10", "1,010"),
            ("17 авг., 10:30", "104", "▲ 4", "2", "208"),
            ("17 авг., 10:00", "100", "—", "3", "300"),
        ]))
        year = dt.date.today().year
        assert [b["hour"] for b in bars] == [10, 11]
        ten = bars[0]
        assert ten["date"] == f"{year}0817"
        # Open is the EARLIEST trade of the hour — page order reversed.
        assert (ten["open"], ten["high"], ten["low"], ten["close"]) == (100, 104, 100, 101)
        assert ten["quantity"] == pytest.approx(15)
        assert ten["turnover"] == pytest.approx(1518)

    def test_two_sessions_in_one_log_stay_two_dates(self):
        bars = uq._hourly_bars(_table([
            ("15 мая, 10:10", "50", "—", "1", "50"),
            ("14 мая, 15:40", "49", "—", "1", "49"),
        ]))
        assert [b["date"][4:] for b in bars] == ["0514", "0515"]

    def test_a_december_row_read_in_january_is_last_years(self):
        # A date the log cannot mean (well ahead of today) must be read as the
        # previous year's — that is exactly what 31 December looks like on
        # 2 January.
        ahead = dt.date.today() + dt.timedelta(days=30)
        months = {1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "мая", 6: "июн",
                  7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек"}
        moment = uq._exec_moment(f"{ahead.day} {months[ahead.month]}., 12:30")
        assert moment is not None
        assert moment[0] == dt.date(ahead.year - 1, ahead.month, ahead.day).strftime("%Y%m%d")

    def test_garbage_rows_do_not_invent_a_bar(self):
        bars = uq._hourly_bars(_table([
            ("не время", "100", "—", "1", "100"),
            ("17 авг., 10:00", "", "—", "1", "100"),
            ("17 авг., 10:00", "0", "—", "1", "100"),
        ]))
        assert bars == []

    def test_no_table_is_no_bars(self):
        assert uq._hourly_bars(None) == []


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A scratch catalog DB, so the suite never writes the real one."""
    import db

    monkeypatch.setattr(db, "APP_DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(rc, "APP_DATA_DIR", tmp_path, raising=False)
    rc.get_catalog_conn().close()
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
        assert rc.bulk_upsert_intraday_history(rows) == 3
        series = rc.get_intraday_history(ISIN, days=7)
        assert len(series) == 3
        # Last write wins: the log only grows through the day.
        assert series[-2]["close_price"] == pytest.approx(101.5)

    def test_rerunning_the_collector_does_not_duplicate_a_bar(self, store):
        rc.bulk_upsert_intraday_history(_bars())
        rc.bulk_upsert_intraday_history(_bars())
        assert len(rc.get_intraday_history(ISIN, days=7)) == 3

    def test_bars_older_than_the_keep_window_are_pruned(self, store):
        old = (dt.date.today() - dt.timedelta(days=rc.INTRADAY_KEEP_DAYS + 5)).strftime("%Y%m%d")
        rc.bulk_upsert_intraday_history(
            [{"isin": ISIN, "trade_date": old, "hour": 12, "close": 1}])
        rc.bulk_upsert_intraday_history(_bars())
        days = {r["trade_date"] for r in rc.get_intraday_history(ISIN, days=rc.INTRADAY_KEEP_DAYS)}
        assert old not in days

    def test_a_row_with_no_key_is_dropped_not_stored(self, store):
        assert rc.bulk_upsert_intraday_history([
            {"isin": "", "trade_date": _day(), "hour": 10, "close": 1},
            {"isin": ISIN, "trade_date": "not a date", "hour": 10, "close": 1},
            {"isin": ISIN, "trade_date": _day(), "hour": 99, "close": 1},
            {"isin": ISIN, "trade_date": _day(), "hour": "x", "close": 1},
        ]) == 0
        assert rc.get_intraday_history(ISIN) == []

    def test_the_window_is_calendar_days(self, store):
        """1Н means THIS week — stretching a quiet security's old bars under
        that label would date the chart wrong; the chart falls back to closes."""
        rc.bulk_upsert_intraday_history(_bars())
        assert len(rc.get_intraday_history(ISIN, days=1)) == 2


class TestTheEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch):
        async def _isin(_ticker):
            return ISIN

        monkeypatch.setattr(api, "_resolve_isin", _isin)
        monkeypatch.setattr(api, "get_intraday_history", lambda isin, days: [
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

        monkeypatch.setattr(api, "_resolve_isin", _no_isin)
        assert TestClient(api.app).get("/api/intraday/NOPE").status_code == 404
