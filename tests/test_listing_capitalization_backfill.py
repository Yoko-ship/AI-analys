"""OpenInfo/UZSE listing capitalisation reaches every known equity class."""
from __future__ import annotations

import pytest

import listings_collector as lc


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class _Session:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *_args, **_kwargs):
        return _Response(self.payload)


def _equity(ticker: str, isin: str, *, preferred: bool = False) -> dict:
    return {
        "ticker": ticker,
        "isin": isin,
        "name": ticker,
        "type": "stock",
        "share_type": "preferred" if preferred else "ordinary",
        "is_preferred": preferred,
    }


def _sources(monkeypatch, equities: dict[str, dict], values: dict[str, tuple[float, float]]):
    monkeypatch.setattr(lc, "_known_equities", lambda: equities)
    monkeypatch.setattr(lc, "_uzse_equity", lambda _session, isin: {
        "shares": values[isin][0], "price": values[isin][1],
        "date": "22.09.2026", "nominal": 1.0,
    })
    monkeypatch.setattr(lc, "_last_conclusion", lambda _session, isin: {
        "close": values[isin][1], "date": "2026-09-22",
        "open": values[isin][1], "high": values[isin][1],
        "low": values[isin][1], "trading_volume": 1,
    })


def test_share_wins_when_openinfo_reuses_its_ticker_for_a_bond(monkeypatch) -> None:
    share = _equity("ALKB", "UZ7044760005")
    payload = {
        "full_name_text": "Aloqabank",
        "info_rfb": {"isin_codes": [
            {"ticker": "ALKB", "isu_cd": "UZ60447611B9", "market": "BND"},
            {"ticker": "ALKB", "isu_cd": share["isin"], "market": "STK",
             "stock_type": "01"},
        ]},
    }
    monkeypatch.setattr(lc, "_make_session", lambda: _Session(payload))
    monkeypatch.setattr(lc, "_org_ids", lambda: {"ALKB": "10"})
    _sources(monkeypatch, {"ALKB": share}, {share["isin"]: (3_674_450_046_965, 0.89)})

    rows = lc.collect_listing_rows()

    assert [row["ticker"] for row in rows] == ["ALKB"]
    assert rows[0]["isin"] == "UZ7044760005"
    assert rows[0]["market_cap"] == pytest.approx(3_270_260_541_798.85)


def test_empty_issuer_security_list_uses_known_common_and_preferred_isins(monkeypatch) -> None:
    equities = {
        "UZAS": _equity("UZAS", "UZ7045570007"),
        "UZASP": _equity("UZASP", "UZ704557K016", preferred=True),
    }
    values = {
        "UZ7045570007": (33_198_274, 178_000),
        "UZ704557K016": (20_000, 13_000),
    }
    payload = {"full_name_text": "O'zagrosug'urta", "info_rfb": {"isin_codes": []}}
    monkeypatch.setattr(lc, "_make_session", lambda: _Session(payload))
    monkeypatch.setattr(lc, "_org_ids", lambda: {"UZAS": "669", "UZASP": "669"})
    _sources(monkeypatch, equities, values)

    rows = lc.collect_listing_rows()

    assert {row["ticker"] for row in rows} == {"UZAS", "UZASP"}
    assert sum(row["market_cap"] for row in rows) == pytest.approx(5_909_552_772_000)
    preferred = next(row for row in rows if row["ticker"] == "UZASP")
    assert preferred["share_type"] == "preferred"


def test_security_without_catalog_org_still_gets_source_capitalisation(monkeypatch) -> None:
    equities = {
        "ORFI": _equity("ORFI", "UZ7055870008"),
        "ORFIP": _equity("ORFIP", "UZ7055871006", preferred=True),
    }
    values = {
        "UZ7055870008": (2_867_124_015, 573.95),
        "UZ7055871006": (400_000, 1_800.01),
    }
    monkeypatch.setattr(lc, "_make_session", lambda: _Session({}))
    monkeypatch.setattr(lc, "_org_ids", dict)
    _sources(monkeypatch, equities, values)

    rows = lc.collect_listing_rows()

    assert {row["ticker"] for row in rows} == {"ORFI", "ORFIP"}
    assert sum(row["market_cap"] for row in rows) == pytest.approx(1_646_305_832_409.25)
