"""A red cron card must mean the data is wrong.

Two of the five services went red on 2026-08-04 and neither had anything to do
with the data. The 08:00 collector reads every security's page before the day's
first execution, so all seventy-five answered 0/0/0 and an empty quote list was
returned as exit 1 — after the run had collected and pushed financials, facts,
listings and the whole openinfo reconciliation correctly. A Monday morning does
the same thing one step earlier: the trade feed is a two-day window, so it holds
Saturday and Sunday and the exchange truthfully answers "nothing traded".

Neither is a failure, and a card that cries wolf every morning is a card nobody
reads on the morning it matters. These tests pin which empties are silence and
which are faults — including the one that used to pass silently: a feed that
stops paginating halfway returns real ISINs with turnover short by however many
pages it missed, and the board cannot tell that from a quiet day.
"""
from __future__ import annotations
import collectors.financials.delivery as collectors_financials_delivery
import collectors.financials.backfill as collectors_financials_backfill
import collectors.financials.market as collectors_financials_market
import collectors.financials.trading as collectors_financials_trading
import collectors.financials.retry as collectors_financials_retry

import pytest

import collector_financials as cf
import reports_catalog as rc
import catalogue.history as catalogue_history
import catalogue.market_store as catalogue_market_store
import catalogue.storage as catalogue_storage
import trade_stats as ts
import uzse_quotes as uq


@pytest.fixture(autouse=True)
def instant_retries(monkeypatch) -> None:
    """Retry the same number of times, without the five-minute wait."""
    monkeypatch.setattr(collectors_financials_retry, "RETRY_WAIT_SECONDS", 0)
    monkeypatch.setattr(collectors_financials_trading.archive_market, "fetch_latest_trade_stats",
                        lambda **kw: _feed(reachable=False, complete=False, stats={}))


@pytest.fixture()
def pushed(monkeypatch) -> list[tuple[str, dict]]:
    """Capture every admin push instead of making one."""
    calls: list[tuple[str, dict]] = []

    def _post(path, body):
        calls.append((path, body))
        return 0

    monkeypatch.setattr(collectors_financials_delivery, "_post", _post)
    monkeypatch.setattr(collectors_financials_market, "audit_board", lambda: 0)
    monkeypatch.setattr(collectors_financials_market, "board_securities", list)
    return calls


def _feed(**over) -> dict:
    data = {"trade_date": "20260804", "count": 1, "reachable": True, "complete": True,
            "stats": {"UZ7003040001": {"isin": "UZ7003040001", "trade_date": "20260804",
                                       "market": "STK", "total_value": 4_096_850.0,
                                       "total_qty": 79.0, "trade_count": 8}}}
    data.update(over)
    return data


def test_company_quarter_history_backfill_pushes_only_recovered_periods(monkeypatch, pushed) -> None:
    """A visible old quarter is repaired on demand, not by a market-wide sweep."""
    called: dict[str, object] = {}

    def harvest(ticker, *, limit):
        called.update({"ticker": ticker, "limit": limit})
        return {
            "rows": [
                {"ticker": "YGSY", "year": 2016, "quarter": 1, "revenue": 12.0},
                {"ticker": "YGSY", "year": 2016, "quarter": 2, "revenue": 24.0},
            ],
            "errors": [],
        }

    monkeypatch.setattr(catalogue_history, "harvest_historical_quarters", harvest)

    assert collectors_financials_backfill.backfill_company_quarter_history("ygsy") == 0
    assert called == {"ticker": "YGSY", "limit": 40}
    assert pushed == [("/api/admin/financials", {
        "form": "NSBU", "mode": "upsert", "rows": [
            {"ticker": "YGSY", "year": 2016, "quarter": 1, "revenue": 12.0},
            {"ticker": "YGSY", "year": 2016, "quarter": 2, "revenue": 24.0},
        ],
    })]


class TestAnEmptySessionIsNotAFailure:
    def test_a_feed_window_with_no_trading_days_in_it(self, monkeypatch, pushed) -> None:
        """Monday 08:00 reads Saturday + Sunday."""
        monkeypatch.setattr(ts, "fetch_trade_stats",
                            lambda *a, **k: _feed(trade_date=None, count=0, stats={}))

        assert collectors_financials_trading.push_trade_stats() == 0
        assert pushed == []  # nothing to publish, and nothing overwritten

    def test_pages_that_have_not_opened_yet(self, monkeypatch, pushed) -> None:
        """08:00: every page reads 0/0/0 because the session has not started."""
        def _quotes(targets, **kw):
            outcome = kw.get("outcome")
            if outcome is not None:
                outcome.update({"targets": 2, "unreadable": 0, "idle": 2,
                                "settled": 0, "quoted": 0, "unread": []})
            return []

        monkeypatch.setattr(uq, "fetch_session_quotes", _quotes)

        assert collectors_financials_market.push_quotes(_feed()["stats"]) == 0
        assert [p for p, _ in pushed] == []


class TestWhatIsStillAFailure:
    def test_a_feed_that_never_answered(self, monkeypatch, pushed) -> None:
        attempts = []
        monkeypatch.setattr(ts, "fetch_trade_stats",
                            lambda *a, **k: attempts.append(1) or _feed(
                                trade_date=None, count=0, stats={},
                                reachable=False, complete=False))

        assert collectors_financials_trading.push_trade_stats() == 1
        assert len(attempts) == collectors_financials_retry.RETRY_ATTEMPTS  # waited and asked again first

    def test_a_feed_that_stopped_halfway(self, monkeypatch, pushed) -> None:
        """Real ISINs, understated turnover, and no way for the board to know."""
        monkeypatch.setattr(ts, "fetch_trade_stats", lambda *a, **k: _feed(complete=False))

        assert collectors_financials_trading.push_trade_stats() == 1
        assert pushed == []

    def test_not_one_page_could_be_read(self, monkeypatch, pushed) -> None:
        def _quotes(targets, **kw):
            outcome = kw.get("outcome")
            if outcome is not None:
                outcome.update({"targets": 1, "unreadable": 1, "idle": 0,
                                "settled": 0, "quoted": 0, "unread": list(targets)})
            return []

        monkeypatch.setattr(uq, "fetch_session_quotes", _quotes)

        assert collectors_financials_market.push_quotes(_feed()["stats"]) == 1


class TestWaitingForTheExchangeToComeBack:
    """uzse.uz was unreachable for over an hour on the evening of 2026-08-04 —
    from Railway as well as from a home connection — and then answered normally.
    Giving up on the first miss costs a whole scheduled slot: the next quotes run
    is hours away and the next collector a day.
    """

    def test_the_feed_is_asked_again_and_the_run_continues(self, monkeypatch, pushed) -> None:
        answers = [_feed(trade_date=None, count=0, stats={}, reachable=False, complete=False),
                   _feed()]
        monkeypatch.setattr(ts, "fetch_trade_stats", lambda *a, **k: answers.pop(0))
        monkeypatch.setattr(collectors_financials_market, "push_quotes", lambda stats: 0)

        assert collectors_financials_trading.push_trade_stats() == 0
        assert answers == []
        assert "/api/admin/trade-stats" in [path for path, _ in pushed]

    def test_only_the_unread_pages_are_asked_again(self, monkeypatch, pushed) -> None:
        monkeypatch.setattr(collectors_financials_market, "board_securities", lambda: [
            {"isin": "UZ7003040001", "_market": "STK"},
            {"isin": "UZ7043380003", "_market": "STK"},
        ])
        asked: list[list] = []

        def _quotes(targets, **kw):
            targets = list(targets)
            asked.append(targets)
            # `or {}` would swallow the update — an empty dict is falsy.
            outcome = kw["outcome"]
            if len(asked) == 1:
                # One page answered, the other could not be read at all.
                outcome.update({"targets": 2, "unreadable": 1, "idle": 0, "settled": 0,
                                "quoted": 1, "unread": [("UZ7043380003", "STK")]})
                return [{"isin": "UZ7003040001", "trade_date": "20260804", "close_price": 1.0}]
            outcome.update({"targets": 1, "unreadable": 0, "idle": 0, "settled": 1,
                            "quoted": 1, "unread": []})
            return [{"isin": "UZ7043380003", "trade_date": "20260729", "close_price": 2.0}]

        monkeypatch.setattr(uq, "fetch_session_quotes", _quotes)
        monkeypatch.setattr(collectors_financials_market, "quotes_from_archive", lambda targets: [])

        assert collectors_financials_market.push_quotes(_feed()["stats"]) == 0
        # The second pass asks about the unreadable one only — a page that
        # answered "no session" answered.
        assert asked[1] == [("UZ7043380003", "STK")]
        rows = next(body["rows"] for path, body in pushed if path == "/api/admin/quotes")
        assert {r["isin"] for r in rows} == {"UZ7003040001", "UZ7043380003"}


class TestTheQuotePassCoversTheWholeBoard:
    @pytest.mark.parametrize("quote_day,expected", [
        ("20260804", (51950.0, 52000.0, 50900.0)),
        ("20260803", (None, None, None)),
    ])
    def test_settled_quotes_take_the_range_only_from_the_same_execution_session(
            self, monkeypatch, pushed, quote_day, expected):
        stats = _feed()["stats"]
        stats["UZ7003040001"].update(open_price=51950.0, high_price=52000.0, low_price=50900.0)
        monkeypatch.setattr(uq, "fetch_session_quotes", lambda targets, **kw: [
            {"isin": "UZ7003040001", "trade_date": quote_day, "close_price": 51850.0,
             "open_price": None, "high_price": None, "low_price": None}])
        assert collectors_financials_market.push_quotes(stats) == 0
        row = next(body["rows"][0] for path, body in pushed if path == "/api/admin/quotes")
        assert tuple(row[key] for key in ("open_price", "high_price", "low_price")) == expected

    def test_the_execution_fallback_preserves_the_quote_pages_own_range(self, monkeypatch, pushed):
        stats = _feed()["stats"]
        stats["UZ7003040001"].update(open_price=10.0, high_price=12.0, low_price=8.0)
        monkeypatch.setattr(uq, "fetch_session_quotes", lambda targets, **kw: [
            {"isin": "UZ7003040001", "trade_date": "20260804", "close_price": 11.0,
             "open_price": 9.0, "high_price": 13.0, "low_price": 7.0}])
        assert collectors_financials_market.push_quotes(stats) == 0
        row = next(body["rows"][0] for path, body in pushed if path == "/api/admin/quotes")
        assert (row["open_price"], row["high_price"], row["low_price"]) == (9.0, 13.0, 7.0)

    def test_every_listed_security_is_read_not_only_what_traded(
            self, monkeypatch, pushed) -> None:
        """The backfill list used to be read from the collector's own scratch
        database, which knows no securities at all — so on Railway it was always
        empty and a quiet security was never re-read."""
        monkeypatch.setattr(collectors_financials_market, "board_securities", lambda: [
            {"isin": "UZ7003040001", "_market": "STK"},   # traded today
            {"isin": "UZ7043380003", "_market": "STK"},   # quiet since 29.07
            {"isin": "UZ6011507AA9", "_market": "BND"},
        ])
        seen: dict = {}

        def _quotes(targets, **kw):
            seen["targets"] = list(targets)
            seen["settle"] = kw.get("settle")
            return [{"isin": "UZ7003040001", "trade_date": "20260804", "close_price": 1.0}]

        monkeypatch.setattr(uq, "fetch_session_quotes", _quotes)
        monkeypatch.setattr(collectors_financials_market, "quotes_from_archive", lambda targets: [])

        assert collectors_financials_market.push_quotes(_feed()["stats"]) == 0
        assert seen["targets"] == [("UZ6011507AA9", "BND"), ("UZ7003040001", "STK"),
                                   ("UZ7043380003", "STK")]
        assert seen["settle"] is True

    def test_what_the_page_cannot_date_goes_to_the_execution_archive(
            self, monkeypatch, pushed) -> None:
        """KPBA last traded in February 2024, outside the page's ~21 sessions."""
        monkeypatch.setattr(collectors_financials_market, "board_securities", lambda: [
            {"isin": "UZ7047440001", "_market": "STK"}])
        monkeypatch.setattr(uq, "fetch_session_quotes",
                            lambda targets, **kw: [{"isin": "UZ7003040001",
                                                    "trade_date": "20260804",
                                                    "close_price": 1.0}])
        asked: list = []

        def _archive(targets):
            asked.extend(targets)
            return [{"isin": "UZ7047440001", "trade_date": "20240223", "close_price": 5284.8}]

        monkeypatch.setattr(collectors_financials_market, "quotes_from_archive", _archive)

        assert collectors_financials_market.push_quotes(_feed()["stats"]) == 0
        assert asked == [("UZ7047440001", "STK")]
        rows = next(body["rows"] for path, body in pushed if path == "/api/admin/quotes")
        assert {r["isin"] for r in rows} == {"UZ7003040001", "UZ7047440001"}


@pytest.fixture()
def catalog_db(tmp_path, monkeypatch):
    path = tmp_path / "catalog.db"
    monkeypatch.setattr(catalogue_storage, "_catalog_db_path", lambda: str(path))
    catalogue_storage.get_catalog_conn().close()
    return str(path)


class TestASecondReadOfTheSameSessionOnlyAdds:
    """The 16:10 run watches the session live and records its open, high and low.
    The morning run settles the same session from the exchange's daily history,
    which publishes the close and not the OHLC — writing those NULLs over the
    columns the live run captured would lose them to a read that knew less.
    """

    def _quote(self, **over) -> dict:
        row = {"isin": "UZ7003040001", "ticker": "UZMT", "trade_date": "20260804",
               "close_price": 51850.0, "prev_close": 51700.0, "quantity": 79.0,
               "turnover": 4_096_850.0, "open_price": 51950.0, "high_price": 52000.0,
               "low_price": 50900.0}
        row.update(over)
        return row

    def test_the_settled_row_keeps_the_ohlc_the_live_run_saw(self, catalog_db) -> None:
        catalogue_market_store.bulk_upsert_quotes([self._quote()])
        catalogue_market_store.bulk_upsert_quotes([self._quote(open_price=None, high_price=None, low_price=None,
                                           quantity=86.0, turnover=4_403_867.95)])

        stored = catalogue_market_store.get_all_quotes()["UZ7003040001"]
        assert (stored["open_price"], stored["high_price"], stored["low_price"]) == (
            51950.0, 52000.0, 50900.0)
        # ...and takes the settled numbers where the exchange did state them.
        assert stored["quantity"] == 86.0
        assert stored["turnover"] == pytest.approx(4_403_867.95)

    def test_a_later_session_replaces_the_row_outright(self, catalog_db) -> None:
        catalogue_market_store.bulk_upsert_quotes([self._quote()])
        catalogue_market_store.bulk_upsert_quotes([self._quote(trade_date="20260805", close_price=52000.0,
                                           open_price=None, high_price=None, low_price=None)])

        stored = catalogue_market_store.get_all_quotes()["UZ7003040001"]
        assert stored["trade_date"] == "20260805"
        assert (stored["open_price"], stored["high_price"], stored["low_price"]) == (
            None, None, None)

    def test_an_older_session_is_still_refused(self, catalog_db) -> None:
        catalogue_market_store.bulk_upsert_quotes([self._quote()])
        catalogue_market_store.bulk_upsert_quotes([self._quote(trade_date="20260731", close_price=1.0)])

        assert catalogue_market_store.get_all_quotes()["UZ7003040001"]["close_price"] == 51850.0
