"""One price history and one period rule, for every surface (audit register К1/К2).

The register of 12–13.10.2026 traced its price findings to two roots:

* К1 — a period's base was found differently per window and per surface: day
  counts on the board (3М = 91 days), 360 days on the card, 90 for QoQ, an
  inclusive window on the card against an exclusive one on the board. Whenever
  the anchor fell on a weekend or a holiday the surfaces came out a session apart.
* К2 — the board read ``catalog_quote_history`` while the card read openinfo's
  archive, and the store let a session rebuilt from executions overwrite the
  exchange's own close and turnover (541 sessions of 60 securities).

These tests pin the rules that close both, on real-data-shaped series, with the
cases each rule must catch and the ones it must leave alone.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

import catalogue.market_store as catalogue_market_store
import catalogue.storage as catalogue_storage
import formulas
import reports_catalog as rc
import server.market.history as market_history
import trade_stats


# --------------------------------------------------------------------------- helpers

def _sessions(start: date, end: date, *, skip: set[date] = frozenset()) -> list[dict]:
    """A weekday series with a distinct close per session, the board's point shape."""
    out, day, price = [], start, 100.0
    while day <= end:
        if day.weekday() < 5 and day not in skip:
            price += 1.0
            out.append({"d": day, "date": day.strftime("%Y%m%d"), "close": price,
                        "turnover": price * 10, "quantity": 10.0})
        day += timedelta(days=1)
    return out


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A scratch catalog DB, so the suite never writes the real one."""
    import db

    monkeypatch.setattr(db, "APP_DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(catalogue_storage, "APP_DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(rc, "CATALOG_DB", str(tmp_path / "catalog.db"), raising=False)
    catalogue_storage.get_catalog_conn().close()
    return tmp_path


def _stored(isin: str, day: str) -> dict:
    return catalogue_market_store.get_quote_history([isin], 3650)[isin][
        [r["trade_date"] for r in catalogue_market_store.get_quote_history([isin], 3650)[isin]].index(day)]


# --------------------------------------------------------------------------- К1

# Anchors that put a period's cutoff on a Saturday, a Sunday, a holiday-shaped
# gap, a month end the earlier month lacks, and an ordinary weekday.
ANCHORS = [date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 9), date(2026, 5, 31),
           date(2026, 3, 31), date(2026, 1, 5), date(2026, 8, 17), date(2026, 7, 1)]
# Two exchange holidays inside the series, so a cutoff can land on a weekday
# with no session as well as on a weekend.
HOLIDAYS = {date(2026, 3, 20), date(2026, 3, 23), date(2026, 9, 1)}


class TestOneBaseRuleForEveryWindow:
    """The board, the card's window and the absolute returns read one rule."""

    SERIES = _sessions(date(2024, 12, 2), date(2026, 10, 13), skip=HOLIDAYS)

    @pytest.mark.parametrize("as_of", ANCHORS)
    @pytest.mark.parametrize("code", ["1w", "1m", "3m", "6m", "1y", "ytd"])
    def test_the_board_and_the_card_describe_one_period(self, code, as_of) -> None:
        points = [p for p in self.SERIES if p["d"] <= as_of]
        span = formulas.PERIOD_SPANS[code]
        cutoff = formulas.period_cutoff(span, as_of)

        change = market_history._window_change(points, market_history.MARKET_CHANGE_WINDOWS[code], as_of)
        stats = market_history._window_stats(points, market_history.MARKET_CHANGE_WINDOWS[code], as_of)
        card = formulas.window_slice(points, 1, today=as_of, code=code)

        base = [p for p in points if p["d"] <= cutoff][-1]  # last session at/before the cutoff
        assert change["from"] == base["date"], "the base is the last close at or before the cutoff"
        assert card[0]["d"] > cutoff and card[0]["d"] > base["d"], "the window starts after the base"
        assert [p["date"] for p in card] == [p["date"] for p in points if p["d"] > cutoff]
        assert stats["sessions"] == len(card), "the board's sessions are the card's sessions"
        assert stats["from"] == card[0]["date"]

    @pytest.mark.parametrize("as_of", ANCHORS)
    @pytest.mark.parametrize(("code", "horizon"), [("1m", "m1"), ("3m", "qoq"), ("1y", "yoy"),
                                                   ("ytd", "ytd")])
    def test_the_absolute_returns_use_the_boards_base(self, code, horizon, as_of) -> None:
        points = [{**p, "date": p["d"].isoformat()} for p in self.SERIES if p["d"] <= as_of]
        got = formulas.returns(points, as_of)[horizon]
        board = market_history._window_change(
            [{**p, "date": p["d"].strftime("%Y%m%d")} for p in points],
            market_history.MARKET_CHANGE_WINDOWS[code], as_of)

        assert got["base_date"].replace("-", "") == board["from"]

    def test_qoq_on_13_october_is_measured_from_13_july_not_15_july(self) -> None:
        """Written as 90 days, QoQ on 13.10.2026 was based on 15.07 — the board's 3М on 13.07."""
        points = [{**p, "date": p["d"].isoformat()} for p in self.SERIES if p["d"] <= date(2026, 10, 13)]

        assert formulas.returns(points)["qoq"]["base_date"] == "2026-07-13"

    @pytest.mark.parametrize(("as_of", "code", "cutoff"), [
        # 12.10.2026 is a Monday; 12.07 and 12.04 were Sundays.
        (date(2026, 10, 12), "3m", date(2026, 7, 12)),
        (date(2026, 10, 12), "6m", date(2026, 4, 12)),
        (date(2026, 10, 12), "1m", date(2026, 9, 12)),
        (date(2026, 10, 12), "1w", date(2026, 10, 5)),
        (date(2026, 10, 12), "1y", date(2025, 10, 12)),
        (date(2026, 10, 12), "ytd", date(2025, 12, 31)),
        (date(2026, 5, 31), "3m", date(2026, 2, 28)),
        (date(2028, 3, 31), "1m", date(2028, 2, 29)),
    ])
    def test_every_period_starts_on_the_date_its_label_names(self, as_of, code, cutoff) -> None:
        assert formulas.period_cutoff(formulas.PERIOD_SPANS[code], as_of) == cutoff

    def test_the_session_on_the_cutoff_is_the_base_not_the_first_day(self) -> None:
        """13.10.2026: the card's year began ON 13.10.2025, the board's after it."""
        points = _sessions(date(2025, 10, 1), date(2026, 10, 13))
        card = formulas.window_slice(points, 12, today=date(2026, 10, 13))

        assert card[0]["d"] == date(2025, 10, 14)

    def test_the_card_window_ends_on_the_market_anchor_not_the_calendar(self) -> None:
        """On a Sunday the board's year ends on Friday; so does the card's."""
        points = _sessions(date(2025, 10, 1), date(2026, 10, 9))
        friday = formulas.window_slice(points, 12, today=date(2026, 10, 9))
        sunday = formulas.window_slice(points, 12, today=date(2026, 10, 11))

        assert friday[0]["d"] == date(2025, 10, 10)
        assert sunday[0]["d"] == date(2025, 10, 13), "the calendar anchor moves the window"


class TestTheMetricsEndpointUsesTheSharedPeriods:
    @pytest.fixture()
    def client(self, monkeypatch):
        from fastapi.testclient import TestClient

        import api

        points = [{"date": p["d"].isoformat(), "close": p["close"], "trading_volume": 10.0,
                   "trading_value": p["close"] * 10}
                  for p in _sessions(date(2025, 6, 2), date(2026, 10, 9))]

        async def fake_resolve(ticker):
            return "UZ0000000001"

        async def fake_history(isin, months=60):
            return {"points": points, "adjustments": []}

        async def friday():
            return date(2026, 10, 9)

        monkeypatch.setattr(market_history, "_resolve_isin", fake_resolve)
        monkeypatch.setattr(market_history, "_full_history", fake_history)
        monkeypatch.setattr(market_history, "_market_as_of", friday)
        return TestClient(api.app)

    def test_a_named_period_is_measured_by_its_own_span(self, client) -> None:
        body = client.get("/api/company/UZTL/metrics", params={"window": "6m"}).json()

        assert body["window"]["code"] == "6m"
        assert body["window"]["label"] == "за 6 месяцев"
        # 6М before Friday 09.10.2026 is Thursday 09.04 — the base; the window starts after it.
        assert body["window"]["first_date"] == "2026-04-10"
        assert body["market_as_of"] == "2026-10-09"

    def test_ytd_needs_no_day_count_from_the_browser(self, client) -> None:
        body = client.get("/api/company/UZTL/metrics", params={"window": "ytd"}).json()

        assert body["window"]["first_date"] == "2026-01-01"


# --------------------------------------------------------------------------- К2: the store

AGMKP = "UZ700055K015"


class TestTheExchangesOwnFiguresOutrankRebuiltOnes:
    """AGMKP 13.10.2025: one order swept 8 701,01 → 8 800 in one millisecond. The
    exchange's close is 8 701,01; the executions, which carry no order, were
    rebuilt with 8 800 last — and, written last, the rebuilt close stood."""

    OFFICIAL = {"isin": AGMKP, "trade_date": "2025-10-13", "close_price": 8701.01,
                "quantity": 1669.0, "turnover": 14563355.45, "open_price": 8640.2,
                "high_price": 9248.99, "low_price": 8640.2001953125}
    REBUILT = {"isin": AGMKP, "trade_date": "20251013", "close_price": 8800.0,
               "total_qty": 1668.0, "total_value": 14554555.45, "open_price": 8640.2,
               "high_price": 9248.99, "low_price": 8640.2, "trade_count": 25,
               "largest_value": 261030.3, "source": "executions"}

    def test_a_rebuilt_session_cannot_overwrite_the_official_one(self, store) -> None:
        catalogue_market_store.bulk_upsert_quote_history([self.OFFICIAL])
        catalogue_market_store.bulk_upsert_quote_history([self.REBUILT])

        row = _stored(AGMKP, "20251013")
        assert (row["close_price"], row["turnover"], row["quantity"]) == (8701.01, 14563355.45, 1669.0)
        # What only the executions can see still lands.
        assert (row["trade_count"], row["largest_value"]) == (25, 261030.3)

    def test_the_official_session_replaces_a_rebuilt_one(self, store) -> None:
        catalogue_market_store.bulk_upsert_quote_history([self.REBUILT])
        catalogue_market_store.bulk_upsert_quote_history([self.OFFICIAL])

        row = _stored(AGMKP, "20251013")
        assert (row["close_price"], row["turnover"]) == (8701.01, 14563355.45)
        assert row["trade_count"] == 25

    def test_a_rebuilt_session_fills_a_day_the_exchange_has_not_published(self, store) -> None:
        catalogue_market_store.bulk_upsert_quote_history([self.REBUILT])

        assert _stored(AGMKP, "20251013")["close_price"] == 8800.0

    def test_the_aggregate_shape_is_rebuilt_even_without_its_tag(self, store) -> None:
        """A collector built before the tag still cannot pass executions off as official."""
        untagged = {k: v for k, v in self.REBUILT.items() if k != "source"}
        catalogue_market_store.bulk_upsert_quote_history([self.OFFICIAL])
        catalogue_market_store.bulk_upsert_quote_history([untagged])

        assert _stored(AGMKP, "20251013")["close_price"] == 8701.01

    def test_the_day_statistics_are_banked_as_rebuilt(self) -> None:
        rows = catalogue_market_store.trade_stats_as_history(
            [{"isin": AGMKP, "trade_date": "20261013", "close_price": 1.0, "total_qty": 1,
              "total_value": 1.0, "trade_count": 1}])
        assert catalogue_market_store.quote_history_source(rows[0]) == \
            catalogue_market_store.QUOTE_SOURCE_EXECUTIONS

    def test_a_later_read_of_the_same_rank_still_settles_a_session(self, store) -> None:
        """Mid-session reads are provisional; the later read of one source wins."""
        catalogue_market_store.bulk_upsert_quote_history(
            [{"isin": AGMKP, "trade_date": "20261013", "close_price": 31000.0, "turnover": 1.0e6}])
        catalogue_market_store.bulk_upsert_quote_history(
            [{"isin": AGMKP, "trade_date": "20261013", "close_price": 31750.0, "turnover": 1.5e7}])

        assert _stored(AGMKP, "20261013")["close_price"] == 31750.0

    def test_the_rebuilt_range_keeps_settling_under_an_official_close(self, store) -> None:
        """The quote page has a close and no range: its rank must not freeze the
        executions' mid-session high and low."""
        mid = {"isin": AGMKP, "trade_date": "20261013", "source": "executions", "close_price": 31000.0,
               "high_price": 31500.0, "low_price": 30000.0, "total_qty": 1, "total_value": 1.0}
        page = {"isin": AGMKP, "trade_date": "20261013", "close_price": 31750.0, "quantity": 488.0,
                "turnover": 15495659.0}
        final = {**mid, "high_price": 32000.0, "low_price": 29500.0, "close_price": 31750.0}
        for row in (mid, page, final):
            catalogue_market_store.bulk_upsert_quote_history([row])

        row = _stored(AGMKP, "20261013")
        assert (row["high_price"], row["low_price"]) == (32000.0, 29500.0)
        assert (row["close_price"], row["turnover"]) == (31750.0, 15495659.0)

    def test_the_market_anchor_is_the_newest_stored_session(self, store) -> None:
        assert catalogue_market_store.latest_session_date() is None
        catalogue_market_store.bulk_upsert_quote_history([self.OFFICIAL, {
            "isin": "UZ7000000009", "trade_date": "20261009", "close_price": 1.0, "quantity": 0}])

        assert catalogue_market_store.latest_session_date() == date(2026, 10, 9)

    def test_two_writers_in_one_batch_obey_the_same_rule(self, store) -> None:
        catalogue_market_store.bulk_upsert_quote_history([self.OFFICIAL, self.REBUILT])

        assert _stored(AGMKP, "20251013")["close_price"] == 8701.01

    def test_rows_stored_before_the_ranks_existed_are_still_replaceable(self, store) -> None:
        conn = catalogue_storage.get_catalog_conn()
        with conn:
            conn.execute("INSERT INTO catalog_quote_history (isin, trade_date, close_price, turnover) "
                         "VALUES (?, '20251013', 8800.0, 14554555.45)", (AGMKP,))
        conn.close()

        catalogue_market_store.bulk_upsert_quote_history([self.OFFICIAL])

        assert _stored(AGMKP, "20251013")["close_price"] == 8701.01


class TestAPriceThatCannotBeAPriceIsNotWritten:
    """openinfo's conclusions for 21.04.2026: a close of 0 for 25 securities and
    UZTL's previous close (2 400) beside a session that traded only at 2 880.
    Those are the only rows of 13 676 in a year of the archive that fail."""

    UZTL = "UZ7004510002"

    def test_a_zero_close_never_replaces_a_real_one(self, store) -> None:
        catalogue_market_store.bulk_upsert_quote_history(
            [{"isin": self.UZTL, "trade_date": "20260421", "close_price": 795.0, "turnover": 1.7e6,
              "source": "executions"}])
        catalogue_market_store.bulk_upsert_quote_history(
            [{"isin": self.UZTL, "trade_date": "2026-04-21", "close": 0.0, "open": 750.0,
              "high": 800.0, "low": 720.0, "trading_value": 1763873.0}])

        assert _stored(self.UZTL, "20260421")["close_price"] == 795.0

    def test_a_close_outside_its_own_session_is_unknown(self, store) -> None:
        catalogue_market_store.bulk_upsert_quote_history(
            [{"isin": self.UZTL, "trade_date": "20260421", "close_price": 2880.0, "turnover": 1549440.0,
              "source": "executions"}])
        catalogue_market_store.bulk_upsert_quote_history(
            [{"isin": self.UZTL, "trade_date": "20260421", "close_price": 2400.0, "change_value": 480.0,
              "open_price": 2880.0, "high_price": 2880.0, "low_price": 2880.0,
              "quantity": 538.0, "turnover": 1549440.0}])

        row = _stored(self.UZTL, "20260421")
        assert row["close_price"] == 2880.0
        assert row["low_price"] == 2880.0, "the rest of the row is still the exchange's"

    @pytest.mark.parametrize(("close", "low", "high", "outside"), [
        (2400.0, 2880.0, 2880.0, True),          # UZTL 21.04.2026
        (0.5, 1.0, 2.0, True),
        (2.5, 1.0, 2.0, True),
        (8640.2, 8640.2001953125, 9248.99, False),  # AGMKP: single-precision low
        (1.13, 0.8999999761581421, 1.13, False),    # ALKB: close on the high
        (0.9, 0.8999999761581421, 1.13, False),     # ...and on the low
        (100.0, None, 120.0, False),               # a page row carries no range
        (100.0, 120.0, 90.0, False),               # an inverted range proves nothing
    ])
    def test_the_range_check(self, close, low, high, outside) -> None:
        assert catalogue_market_store.close_outside_range(close, low, high) is outside


# --------------------------------------------------------------------------- К2: rebuilt sessions

ORFI = "UZ7055870008"


class TestIdenticalExecutionsAreSeparateFills:
    """ORFI 27.07.2021: the archive lists two identical records — 46 172 373 shares
    at 573,95 in the same millisecond — and the exchange's conclusion counts
    92 344 746. Folding them as duplicates halved the session."""

    FILL = {"trade_datetime": "2021-07-27T13:17:01.292000", "isin_code": ORFI, "market_id": "STK",
            "board_id": "G1", "trade_price": 573.95, "trade_quantity": 46172373.0,
            "trading_value": 26500633483.35}

    def test_identical_records_within_the_count_are_all_kept(self) -> None:
        kept = trade_stats.without_archive_surplus([self.FILL, dict(self.FILL)], 2)
        day = trade_stats.aggregate_by_day(ORFI, kept)[0]

        assert day["total_qty"] == 92344746.0
        assert day["trade_count"] == 2

    def test_only_the_surplus_over_the_count_is_removed(self) -> None:
        """09.10.2026: count 7 334, rows 7 335 — one execution listed twice."""
        other = {**self.FILL, "trade_price": 574.0}
        rows = [self.FILL, dict(self.FILL), other, dict(self.FILL)]

        kept = trade_stats.without_archive_surplus(rows, 3)

        assert len(kept) == 3
        assert kept.count(self.FILL) == 2, "a genuine identical fill survives the trim"

    def test_a_surplus_with_nothing_repeated_keeps_every_record(self) -> None:
        rows = [self.FILL, {**self.FILL, "trade_price": 574.0}]
        assert trade_stats.without_archive_surplus(rows, 1) == rows

    def test_the_archive_walk_reads_the_count(self, monkeypatch) -> None:
        import collectors.openinfo.transport as transport

        monkeypatch.setattr(transport, "_json_get", lambda client, path, params: {
            "count": 2, "has_next": False, "results": [self.FILL, dict(self.FILL)]})

        rows = trade_stats.archive_executions(ORFI, "2021-07-27", "2021-07-27", session=object())

        assert len(rows) == 2


# --------------------------------------------------------------------------- К2: the card reads the store

GRBK = "UZ7051860003"


class TestTheCardReadsTheBoardsHistory:
    """From the store's first session on, the card's history IS the store's."""

    ARCHIVE = {"ticker": "GRBK", "adjustments": [], "points": [
        {"date": "2026-04-16", "close": 700.0, "trading_volume": 1.0, "trading_value": 700.0},
        {"date": "2026-04-20", "close": 760.0, "trading_volume": 2.0, "trading_value": 1520.0},
        # openinfo's broken day: a close of 0 beside a real session.
        {"date": "2026-04-21", "close": 0.0, "open": 750.0, "high": 800.0, "low": 720.0,
         "trading_volume": 2316.0, "trading_value": 1763873.0},
        # A tie the archive resolved one way and the store another.
        {"date": "2026-04-22", "close": 463.03, "trading_volume": 5.0, "trading_value": 2400.0},
        # A session only the archive saw: a gap in the store, not a card-only session.
        {"date": "2026-04-23", "close": 470.0, "trading_volume": 1.0, "trading_value": 470.0},
    ]}
    STORED = [
        {"trade_date": "20260420", "close_price": 760.0, "quantity": 2.0, "turnover": 1520.0},
        {"trade_date": "20260421", "close_price": 795.0, "quantity": 2316.0, "turnover": 1763873.0},
        {"trade_date": "20260422", "close_price": 464.0, "quantity": 5.0, "turnover": 2400.0},
        # Carried forward at zero turnover: not a session.
        {"trade_date": "20260424", "close_price": 464.0, "quantity": 0.0, "turnover": 0.0},
    ]

    def _merge(self, monkeypatch, stored, archive=None, isin=GRBK):
        monkeypatch.setattr(catalogue_market_store, "get_quote_history",
                            lambda isins, days=30: {isin: stored})
        return market_history._with_stored_sessions(isin, archive or self.ARCHIVE)

    def test_every_session_from_the_stores_first_is_the_stores(self, monkeypatch) -> None:
        got = self._merge(monkeypatch, self.STORED)

        assert [(p["date"], p["close"]) for p in got["points"]] == [
            ("2026-04-16", 700.0),            # before the store: the archive's
            ("2026-04-20", 760.0),
            ("2026-04-21", 795.0),            # not the archive's 0
            ("2026-04-22", 464.0),            # the board's close, not the archive's
        ]
        assert got["store_from"] == "2026-04-20"

    def test_the_card_window_counts_the_boards_sessions(self, monkeypatch) -> None:
        got = self._merge(monkeypatch, self.STORED)
        card = formulas.window_stats(formulas.normalize_points(got["points"]), 1,
                                     today=date(2026, 4, 24), code="1w")

        assert card["points"] == 3, "20.04, 21.04 and 22.04 — the session the archive zeroed counts"

    def test_store_prices_are_restated_onto_todays_share(self, monkeypatch) -> None:
        """ALSM split 2:1 on 19.05.2025 and issued 1:2 bonus shares on 26.09.2025."""
        stored = [{"trade_date": "20250410", "close_price": 3000.0, "quantity": 1.0, "turnover": 3000.0},
                  {"trade_date": "20251010", "close_price": 1100.0, "quantity": 1.0, "turnover": 1100.0}]
        archive = {"ticker": "ALSM", "adjustments": [], "points": []}

        got = self._merge(monkeypatch, stored, archive, isin="UZ7045320007")

        assert [p["close"] for p in got["points"]] == [1000.0, 1100.0]
        assert {a["ex_date"] for a in got["adjustments"]} == {"2025-05-19", "2025-09-26"}

    def test_an_unreadable_archive_still_serves_the_store(self, monkeypatch) -> None:
        import collectors.openinfo.market as openinfo_market

        def broken(*args, **kwargs):
            raise RuntimeError("openinfo is down")

        monkeypatch.setattr(openinfo_market, "fetch_price_history", broken)
        monkeypatch.setattr(catalogue_market_store, "get_quote_history",
                            lambda isins, days=30: {GRBK: self.STORED})
        market_history._HISTORY_CACHE.clear()
        market_history._HISTORY_LOCKS.clear()

        got = asyncio.run(market_history._full_history(GRBK, months=240))

        assert [p["date"] for p in got["points"]] == ["2026-04-20", "2026-04-21", "2026-04-22"]
