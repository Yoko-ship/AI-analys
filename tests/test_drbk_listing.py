"""Davr Bank's newly relisted DRBK line stays correctly wired."""
from __future__ import annotations

import reports_catalog as subject_reports_catalog
import requests as subject_requests
import securities_catalog as subject_securities_catalog
import server.market.board as subject_server_market_board
import server.settings as subject_server_settings

from pathlib import Path

from fastapi.testclient import TestClient

import api
import entity_resolver
import listings_collector as lc
import securities_catalog
from company_catalog import COMPANY_CATALOG, COMPANY_SECTORS
from manual_company_info import MANUAL_INFO


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _Session:
    def get(self, *_args, **_kwargs):
        # This reproduces the current upstream defect: Davr Bank's OpenInfo org
        # carries Asia Insurance's security instead of its own newly relisted line.
        return _Response({
            "full_name_text": '"Davr-bank" Xususiy aksiyadorlik tijorat banki',
            "info_rfb": {
                "isin_codes": [{
                    "ticker": "AISK",
                    "isu_cd": "UZ7057300012",
                    "stock_type": "01",
                }],
            },
        })


def test_drbk_identity_and_company_metadata_are_complete() -> None:
    assert COMPANY_CATALOG['"Davr-bank" Xususiy aksiyadorlik tijorat banki'] == "DRBK"
    assert COMPANY_SECTORS["DRBK"] == securities_catalog._TICKER_SECTORS["DRBK"] == "finance"
    assert entity_resolver.ORG_OVERRIDES["DRBK"] == "26"
    assert entity_resolver.ISIN_OVERRIDES["DRBK"] == "UZ7050240009"
    assert MANUAL_INFO["DRBK"]["title"] == "Davr Bank"
    assert (Path(__file__).parents[1] / "logos" / "DRBK.png").is_file()


def test_pinned_drbk_listing_replaces_openinfo_foreign_security(monkeypatch) -> None:
    monkeypatch.setattr(lc, "_make_session", _Session)
    monkeypatch.setattr(lc, "_org_ids", lambda: {"DRBK": "26"})
    monkeypatch.setattr(lc, "_known_equities", lambda: {
        "DRBK": {"ticker": "DRBK", "isin": "UZ7050240009", "type": "stock"},
    })
    monkeypatch.setattr(lc, "_last_conclusion", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(lc, "_uzse_equity", lambda _session, isin: {
        "shares": 100_000_000,
        "price": 5_000,
        "date": "31.10.2019",
        "nominal": 5_000,
    } if isin == "UZ7050240009" else None)

    rows = lc.collect_listing_rows()

    assert [row["ticker"] for row in rows] == ["DRBK"]
    assert rows[0] == {
        "ticker": "DRBK",
        "isin": "UZ7050240009",
        "name": '"Davr-bank" Xususiy aksiyadorlik tijorat banki',
        "share_type": "ordinary",
        "listing_date": "2026-08-28",
        "shares_outstanding": 100_000_000,
        "nominal": 5_000,
        "reference_price": None,
        "last_price": 5_000,
        "last_trade_date": "2019-10-31",
        "open_price": None,
        "high_price": None,
        "low_price": None,
        "volume": None,
        "market_cap": 500_000_000_000,
    }


def test_pinned_drbk_org_map_does_not_absorb_aisk(monkeypatch) -> None:
    monkeypatch.setattr(lc, "_ORG_TICKERS_MEMO", None)
    monkeypatch.setattr(lc, "_org_ids", lambda: {"DRBK": "26"})

    assert lc._org_to_tickers(_Session()) == {"26": {"DRBK"}}


def test_drbk_registry_row_reaches_stock_board_before_mirror_updates(monkeypatch) -> None:
    class _MirrorResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"stocks": [], "updated_at": "2026-08-28T06:00:00"}

    listing = {
        "ticker": "DRBK",
        "isin": "UZ7050240009",
        "name": '"Davr-bank" Xususiy aksiyadorlik tijorat banki',
        "share_type": "ordinary",
        "listing_date": "2026-08-28",
        "shares_outstanding": 100_000_000,
        "nominal": 5_000,
        "last_price": 5_000,
        "last_trade_date": "2019-10-31",
        "market_cap": 500_000_000_000,
    }
    monkeypatch.setattr(subject_requests, "get", lambda *_args, **_kwargs: _MirrorResponse())
    monkeypatch.setattr(subject_server_market_board, '_issuer_names', lambda: {"DRBK": listing["name"]})
    monkeypatch.setattr(subject_server_market_board, '_registered_bond_isins', lambda: frozenset())
    monkeypatch.setattr(subject_reports_catalog, 'get_all_listings', lambda: {"DRBK": listing})
    monkeypatch.setattr(subject_reports_catalog, 'get_all_quotes', dict)
    monkeypatch.setattr(subject_securities_catalog, 'get_securities_map', dict)
    synced = []

    def _sync(rows, _logos):
        synced.extend(rows)
        return len(rows)

    monkeypatch.setattr(subject_securities_catalog, 'sync_securities', _sync)
    monkeypatch.setattr(subject_securities_catalog, 'record_volume', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(subject_server_settings, '_load_logos', dict)

    with TestClient(api.app) as client:
        body = client.get("/api/market/stocks?type=stock").json()

    assert body["count"] == 1
    assert body["inactive_listings"] == 1
    assert body["stocks"][0]["ticker"] == "DRBK"
    assert body["stocks"][0]["url"] == (
        "https://uzse.uz/isu_infos/STK?isu_cd=UZ7050240009"
    )
    # Registry-only rows are served without writing synthetic trades into the
    # live securities cache; the company endpoint joins registry metadata.
    assert [row["ticker"] for row in synced] == ["DRBK"]


def test_drbk_info_combines_catalog_and_listing_metadata(monkeypatch) -> None:
    name = '"Davr-bank" Xususiy aksiyadorlik tijorat banki'
    monkeypatch.setattr(subject_securities_catalog, 'get_securities_map', lambda: {
        "DRBK": {
            "ticker": "DRBK",
            "isin": "UZ7050240009",
            "name": name,
            "sector": "finance",
            "logo_url": "/logos/DRBK.png",
        },
    })
    monkeypatch.setattr(subject_reports_catalog, 'get_all_listings', lambda: {
        "DRBK": {
            "ticker": "DRBK",
            "name": name,
            "listing_date": "2026-08-28",
            "shares_outstanding": 100_000_000,
            "nominal": 5_000,
            "market_cap": 500_000_000_000,
        },
    })
    monkeypatch.setattr(subject_securities_catalog, 'get_wiki_info', lambda *_args, **_kwargs: {
        "ticker": "DRBK",
        "title": "Davr Bank",
        "extract": "Davr Bank profile",
        "page_url": "https://davrbank.uz",
        "source": "official",
    })

    with TestClient(api.app) as client:
        body = client.get("/api/securities/DRBK/info?language=en").json()

    assert body["ok"] is True
    assert body["security"] == {
        "ticker": "DRBK",
        "isin": "UZ7050240009",
        "name": name,
        "sector": "finance",
        "logo_url": "/logos/DRBK.png",
        "company_name": name,
        "security_name": name,
        "listing_date": "2026-08-28",
        "shares_outstanding": 100_000_000,
        "nominal": 5_000,
        "market_cap": 500_000_000_000,
    }
