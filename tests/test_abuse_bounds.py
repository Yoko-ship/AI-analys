"""What one request, or one account, can make the server do.

Each bound is held to the heaviest request the site's own pages send (the case
it must let through) and to the abusive one it exists for.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
import catalogue.filings as catalogue_filings
import catalogue.market_store as market_store
import catalogue.sync as catalogue_sync
import securities_catalog
import server.auth.limits as auth_limits
import server.catalog.routes as catalog_routes
import server.company.routes as company_routes
import server.news.routes as news_routes
import web_auth


class TestNewsFeed:
    @pytest.fixture
    def asked(self, monkeypatch):
        seen = []
        monkeypatch.setattr(catalogue_filings, "get_recent_filings", lambda days, limit: seen.append((days, limit)) or [])
        monkeypatch.setattr(market_store, "get_all_listings", lambda: [])
        return seen

    def test_the_events_page_gets_what_it_asks_for(self, asked) -> None:
        TestClient(api.app).get("/api/news?limit=120&days=365")  # MarketEvents.jsx
        assert asked == [(365, 120)]

    def test_a_whole_table_request_is_bounded(self, asked) -> None:
        TestClient(api.app).get("/api/news?limit=100000000&days=100000")
        assert asked == [(news_routes.NEWS_MAX_DAYS, news_routes.NEWS_MAX_LIMIT)]


class TestQuoteSeries:
    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.setattr(securities_catalog, "get_securities_map", lambda: {})
        monkeypatch.setattr(market_store, "get_quote_history", lambda codes, days: {})
        return TestClient(api.app)

    @staticmethod
    def _tickers(n: int) -> str:
        return ",".join(f"T{i:03d}" for i in range(n))

    def test_a_compare_chart_and_a_list_of_sparklines_pass(self, client) -> None:
        # The compare chart: its ticker and up to five more, ten years each.
        assert client.get(f"/api/quotes/series?tickers={self._tickers(6)}&days=3650").status_code == 200
        # The watch rail / landing board: every listed company, 30 days.
        assert client.get(f"/api/quotes/series?tickers={self._tickers(90)}&days=30").status_code == 200

    def test_two_hundred_tickers_of_ten_years_is_refused(self, client) -> None:
        response = client.get(f"/api/quotes/series?tickers={self._tickers(200)}&days=3650")
        assert response.status_code == 400

    def test_days_beyond_the_store_are_capped_not_multiplied(self, client) -> None:
        response = client.get(f"/api/quotes/series?tickers={self._tickers(1)}&days=100000000")
        assert response.status_code == 200 and response.json()["days"] == company_routes.SERIES_MAX_DAYS

    def test_repeating_a_ticker_does_not_spend_the_budget(self, client) -> None:
        tickers = ",".join(["AAAA"] * 200)
        assert client.get(f"/api/quotes/series?tickers={tickers}&days=3650").status_code == 200


class TestReaderCatalogSync:
    @pytest.fixture
    def sync(self, monkeypatch):
        calls = []
        user = type("User", (), {"id": 501, "email": "reader@example.test", "email_verified": True})()
        monkeypatch.setattr(web_auth.web_auth_store.sessions, "get_user_by_token", lambda token: user)
        monkeypatch.setattr(catalog_routes.catalogue_settings, "_TICKER_TO_NAME", {"AAAA": "Alpha"})
        monkeypatch.setattr(catalogue_sync, "sync_company",
                            lambda ticker, name, force=False, org_id=None: calls.append(force) or {"ticker": ticker})
        for key in [k for k in auth_limits._rate_limiter._events if k.startswith("catalog-sync:")]:
            auth_limits._rate_limiter._events.pop(key, None)
        client = TestClient(api.app)
        post = lambda: client.post("/api/catalog/sync", json={"ticker": "AAAA", "force": True},
                                   headers={"Authorization": "Bearer t"})
        return post, calls, user, monkeypatch

    def test_a_reader_cannot_force_past_freshness(self, sync) -> None:
        post, calls, _, _ = sync
        assert post().status_code == 200
        assert calls == [False]

    def test_a_reader_is_paced(self, sync) -> None:
        post, calls, _, _ = sync
        statuses = [post().status_code for _ in range(catalog_routes.CATALOG_SYNC_PER_USER_PER_HOUR + 1)]
        assert statuses == [200] * catalog_routes.CATALOG_SYNC_PER_USER_PER_HOUR + [429]
        assert len(calls) == catalog_routes.CATALOG_SYNC_PER_USER_PER_HOUR

    def test_an_administrator_still_forces_and_is_not_paced(self, sync) -> None:
        post, calls, user, monkeypatch = sync
        monkeypatch.setenv("ADMIN_EMAILS", user.email)
        for _ in range(catalog_routes.CATALOG_SYNC_PER_USER_PER_HOUR + 1):
            assert post().status_code == 200
        assert set(calls) == {True}
