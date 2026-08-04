"""The board must carry every security the exchange trades, at the exchange's price.

The market board is assembled from a third-party ``/stocks`` mirror whose universe
is a fixed 78 securities. The exchange lists 122 shares and 40 bonds. On 31.07.2026
seven securities traded outside that universe, and five of them were on the
exchange's own top-ten boards: UQEQ +20.00%, METQ +19.74%, KFSKP +17.27%,
PLST +11.37% and KFSK -6.82%. Two (KFSKP, EQQU) were absent from our board
outright; the rest were priced from the openinfo registry's last-known trade —
a week-old number, with the day's percentage struck against it.

These tests pin the repair: the exchange's own quote decides a row's close and the
previous close it is measured against, and a security no feed carries still gets a
row.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api


def _quote(**over) -> dict:
    """UQEQ as the exchange published it on 31.07.2026."""
    base = {
        "isin": "UZ7042540003", "ticker": "UQEQ", "name": "<O'zqishloqelektrqurilish> AJ",
        "market": "STK", "share_type": "ordinary", "trade_date": "20260731",
        "close_price": 30720.0, "prev_close": 25600.0, "prev_close_date": "20260730",
        "change_value": 5120.0, "change_percent": 20.0,
        "open_price": 30720.0, "high_price": 30720.0, "low_price": 30720.0,
        "quantity": 1.0, "turnover": 30720.0, "shares_outstanding": 2404129.0,
    }
    base.update(over)
    return base


class TestAQuoteOverlaysABoardRow:
    def test_the_change_becomes_the_exchanges_change(self) -> None:
        """The registry priced UQEQ at 32 000 (24.07): -4.00%. The exchange says +20%."""
        row = {"ticker": "UQEQ", "isin": "UZ7042540003", "last_price": 32000.0,
               "close_price": 32000.0, "last_trade_date": "2026-07-24",
               "close_date": "2026-07-24", "inactive": True}

        api._apply_quote(row, _quote())

        assert row["last_price"] == pytest.approx(30720.0)
        assert row["close_price"] == pytest.approx(25600.0)
        assert row["last_trade_date"] == "2026-07-31"
        # What the page then computes: (30720 - 25600) / 25600.
        assert (row["last_price"] - row["close_price"]) / row["close_price"] * 100 == pytest.approx(20.0)

    def test_a_security_that_traded_is_no_longer_tagged_dormant(self) -> None:
        row = {"ticker": "UQEQ", "isin": "UZ7042540003", "last_price": 32000.0,
               "close_price": 32000.0, "last_trade_date": "2026-07-24", "inactive": True}

        api._apply_quote(row, _quote())

        assert not row["inactive"]

    def test_session_totals_and_cap_come_with_it(self) -> None:
        row = {"ticker": "UQEQ", "isin": "UZ7042540003", "volume": 4283999.17,
               "last_trade_date": "2026-07-31"}

        api._apply_quote(row, _quote())

        assert row["volume"] == pytest.approx(30720.0)
        assert row["quantity"] == pytest.approx(1.0)
        assert row["market_cap"] == pytest.approx(2404129.0 * 30720.0)

    def test_a_row_from_a_later_session_is_left_alone(self) -> None:
        """A stored quote for a security that has since gone quiet must not
        pull a live row backwards."""
        row = {"ticker": "UQEQ", "isin": "UZ7042540003", "last_price": 31000.0,
               "close_price": 30720.0, "last_trade_date": "2026-08-03"}

        api._apply_quote(row, _quote())

        assert row["last_price"] == pytest.approx(31000.0)
        assert row["last_trade_date"] == "2026-08-03"

    def test_a_carried_forward_close_outranks_an_older_trade(self) -> None:
        """No trade today, and the exchange is carrying a close our quote does not
        know: that is a session newer than ours, so the quote waits."""
        row = {"ticker": "UQEQ", "isin": "UZ7042540003", "last_price": None,
               "close_price": 26000.0, "last_trade_date": None, "close_date": "30.07.2026"}

        api._apply_quote(row, _quote(trade_date="20260724", close_price=32000.0,
                                     prev_close=33000.0, prev_close_date="20260723"))

        assert row["close_price"] == pytest.approx(26000.0)
        assert row["last_price"] is None

    def test_the_carried_close_is_the_quoted_session_when_they_agree(self) -> None:
        """UTGA last traded on 29.07 at 116 000 and the exchange has repeated that
        close every session since — so the mirror's 03.08 "close date" is that
        same trade, not a later one. The row was showing the date and no price.
        """
        row = {"ticker": "UTGA", "isin": "UZ7043380003", "last_price": None,
               "close_price": 116000.0, "last_trade_date": None,
               "close_date": "03.08.2026", "quantity": None, "volume": None}

        api._apply_quote(row, _quote(
            ticker="UTGA", isin="UZ7043380003", trade_date="20260729",
            close_price=116000.0, prev_close=116000.0, prev_close_date="20260728",
            change_value=0.0, change_percent=0.0, quantity=3.0, turnover=348000.0,
            open_price=None, high_price=None, low_price=None, shares_outstanding=None))

        assert row["last_price"] == pytest.approx(116000.0)
        assert row["last_trade_date"] == "2026-07-29"
        assert row["quantity"] == pytest.approx(3.0)
        assert row["volume"] == pytest.approx(348000.0)


class TestTheDaysTurnover:
    """The session's totals come from the executions we hold, not the mirror's.

    The ``/trades`` mirror is a 44-row snapshot of the same fixed universe: it
    called 31.07 "120,7 млн over ~900 trades" while the session the exchange
    published — and the board itself listed — was 1,56 млрд over 6 507.
    """

    def _totals(self, monkeypatch, stats, mirror_calls=None):
        def _mirror(*a, **kw):
            if mirror_calls is not None:
                mirror_calls.append(a)
            raise AssertionError("the mirror must not be consulted when we hold statistics")

        monkeypatch.setattr(api, "get_all_trade_stats", lambda: stats)
        monkeypatch.setattr(api.requests, "get", _mirror)
        with TestClient(api.app) as client:
            return client.get("/api/market/trades").json()

    def test_only_the_latest_session_counts(self, monkeypatch) -> None:
        body = self._totals(monkeypatch, {
            "UZ7047110000": {"trade_date": "20260731", "total_value": 190_783_267.47,
                             "total_qty": 27342, "trade_count": 838},
            "UZ7001100005": {"trade_date": "20260731", "total_value": 4_954_916.68,
                             "total_qty": 60572, "trade_count": 91},
            # A backfilled row for a security whose last trade was another week.
            "UZ7012480008": {"trade_date": "20260716", "total_value": 9_999_999.0,
                             "total_qty": 1, "trade_count": 1},
        })

        assert body["trade_date"] == "20260731"
        assert body["securities"] == 2
        assert body["total_volume"] == pytest.approx(195_738_184.15)
        assert body["total_trade_count"] == 929

    def test_an_empty_cache_falls_back_to_the_mirror(self, monkeypatch) -> None:
        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"trades": [{"volume": 7.8e6, "quantity": 10, "trade_count": 73}]}

        monkeypatch.setattr(api, "get_all_trade_stats", dict)
        monkeypatch.setattr(api.requests, "get", lambda *a, **kw: _Resp())
        with TestClient(api.app) as client:
            body = client.get("/api/market/trades").json()

        assert body["total_volume"] == pytest.approx(7.8e6)
        assert body["total_trade_count"] == 73


class TestTheBoardIsCompleted:
    """A security no feed carries still trades, and still belongs on the board."""

    def _board(self, monkeypatch, quotes, mirror=(), listings=None, kind=None, synced=None):
        class _Resp:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        monkeypatch.setattr(api.requests, "get",
                            lambda *a, **kw: _Resp({"stocks": list(mirror),
                                                    "updated_at": "2026-07-31T14:00:00"}))
        monkeypatch.setattr(api, "get_all_quotes", lambda: quotes)
        monkeypatch.setattr(api, "get_all_listings", lambda: listings or {})
        monkeypatch.setattr(api, "get_securities_map", lambda: {})
        def _sync(rows, logos):
            if synced is not None:
                synced.extend(str(r.get("ticker") or "") for r in rows)
            return len(rows)

        monkeypatch.setattr(api, "sync_securities", _sync)
        monkeypatch.setattr(api, "record_volume", lambda *a, **kw: 0)
        monkeypatch.setattr(api, "_load_logos", lambda: {})
        with TestClient(api.app) as client:
            url = "/api/market/stocks" + (f"?type={kind}" if kind else "")
            return client.get(url).json()

    def test_a_security_absent_from_the_mirror_gets_a_row(self, monkeypatch) -> None:
        body = self._board(monkeypatch, {"UZ7042540003": _quote()})

        rows = {r["ticker"]: r for r in body["stocks"]}
        assert "UQEQ" in rows
        assert rows["UQEQ"]["last_price"] == pytest.approx(30720.0)
        assert rows["UQEQ"]["close_price"] == pytest.approx(25600.0)
        assert rows["UQEQ"]["url"].endswith("STK?isu_cd=UZ7042540003")

    def test_kafolats_preferred_share_is_not_dormant(self, monkeypatch) -> None:
        """KFSKP was suppressed as a dormant registry line; it traded 39 times
        on 31.07 and closed +17.27%, third on the exchange's gainers board."""
        assert "KFSKP" not in api.BOARD_DENYLIST

        body = self._board(monkeypatch, {"UZ700110K018": _quote(
            isin="UZ700110K018", ticker="KFSKP", share_type="preferred",
            close_price=936.99, prev_close=799.0, change_value=137.99,
            change_percent=17.2703, quantity=801.0, turnover=641586.99)})

        row = next(r for r in body["stocks"] if r["ticker"] == "KFSKP")
        assert (row["last_price"] - row["close_price"]) / row["close_price"] * 100 == pytest.approx(17.27, abs=0.005)

    def test_a_bond_quote_stays_out_of_the_share_view(self, monkeypatch) -> None:
        bond = _quote(isin="UZ6058967AB7", ticker="UZUMN2B2", market="BND")

        shares = self._board(monkeypatch, {"UZ6058967AB7": bond}, kind="stock")
        bonds = self._board(monkeypatch, {"UZ6058967AB7": bond}, kind="bond")

        assert [r["ticker"] for r in shares["stocks"]] == []
        assert [r["ticker"] for r in bonds["stocks"]] == ["UZUMN2B2"]
        assert bonds["stocks"][0]["type"] == "bond"

    def test_a_mirror_row_is_updated_not_duplicated(self, monkeypatch) -> None:
        body = self._board(monkeypatch, {"UZ7042540003": _quote()}, mirror=[
            {"ticker": "UQEQ", "isin": "UZ7042540003", "last_price": 32000.0,
             "close_price": 32000.0, "last_trade_date": "24.07.2026",
             "close_date": "24.07.2026"},
        ])

        rows = [r for r in body["stocks"] if r["ticker"] == "UQEQ"]
        assert len(rows) == 1
        assert rows[0]["close_price"] == pytest.approx(25600.0)

    def test_a_quoted_security_is_catalogued(self, monkeypatch) -> None:
        """Without a catalog row a board line has no name, logo, sector or company
        page — which is what a security outside the mirror's universe always had.
        Trading is the qualification, whichever source put the row on the board."""
        synced: list[str] = []
        self._board(monkeypatch, {"UZ7042540003": _quote()}, mirror=[
            {"ticker": "UQEQ", "isin": "UZ7042540003", "last_price": 32000.0,
             "close_price": 32000.0, "last_trade_date": "24.07.2026"},
        ], synced=synced)

        assert "UQEQ" in synced

    def test_the_audit_reads_the_board_the_site_serves(self, monkeypatch) -> None:
        """/api/market/audit must compare the exchange against the merged board,
        not the mirror — reading the mirror is what made the old coverage report
        blind to exactly the securities it was supposed to surface."""
        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"stocks": [], "updated_at": "2026-07-31T14:00:00"}

        monkeypatch.setattr(api.requests, "get", lambda *a, **kw: _Resp())
        monkeypatch.setattr(api, "get_all_quotes", lambda: {"UZ7042540003": _quote()})
        monkeypatch.setattr(api, "get_all_trade_stats", lambda: {
            "UZ7042540003": {"trade_date": "20260731", "total_value": 30720.0,
                             "total_qty": 1.0, "trade_count": 1}})
        monkeypatch.setattr(api, "get_all_listings", lambda: {})
        monkeypatch.setattr(api, "get_securities_map", lambda: {})
        monkeypatch.setattr(api, "sync_securities", lambda *a, **kw: 0)
        monkeypatch.setattr(api, "record_volume", lambda *a, **kw: 0)
        monkeypatch.setattr(api, "_load_logos", lambda: {})

        with TestClient(api.app) as client:
            body = client.get("/api/market/audit").json()

        assert body["ok"] is True
        assert body["trade_date"] == "20260731"
        # The row exists only because the quote put it there.
        assert (body["audited"], body["on_board"]) == (1, 1)

    def test_a_delisted_ticker_still_cannot_come_back_through_a_quote(self, monkeypatch) -> None:
        body = self._board(monkeypatch, {"UZ7000000001": _quote(
            isin="UZ7000000001", ticker=sorted(api.BOARD_DENYLIST)[0])})

        assert body["stocks"] == []
