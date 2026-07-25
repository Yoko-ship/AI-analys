"""Deleted securities stay deleted.

Removal here is a purge, not a display filter, and it has to survive three things
that would otherwise undo it: the collector re-emitting the row from openinfo, the
upsert-only listings ingest resurrecting it, and a catalog rebuild adding the
issuer back because openinfo still answers for it. Each path is pinned below.

The set itself is guarded too: the source list it was drawn from — the Справочник's
"Неактивны / возможный делистинг" tab — is computed from ``last_trade_date`` alone
and also caught securities that were trading normally, so a ticker landing in
DELISTED_TICKERS by mistake is the failure mode worth a test.
"""
from __future__ import annotations

import sqlite3

import pytest

import reports_catalog as rc
from delisted import DELISTED_TICKERS, is_delisted

# Lines that are demonstrably alive: they printed a trade the same week the
# reference tab listed them as delisting candidates. See module docstring.
STILL_TRADING = {
    "ALKB",                                             # Aloqabank, ordinary
    "ACMT1B3", "ACMT2B4", "ACMT2B5",                    # AGAT CREDIT bonds
    "BFMT2B5", "BFMT3B4", "BFMT3V2", "BFMT3V3",         # Biznes Finans bonds
    "CTFB3B2",                                          # CONTACT FINANCE bond
}

# Issuers large enough that deleting them would gut the board, all of which the
# same tab flagged. They are kept deliberately.
MAJOR_ISSUERS = {"UZNG", "AGMK", "TGBK", "KPBA", "UZGF", "UZIN", "FRAZ"}


class TestSetContents:
    @pytest.mark.parametrize("ticker", sorted(STILL_TRADING))
    def test_actively_traded_lines_are_not_deleted(self, ticker: str) -> None:
        assert ticker not in DELISTED_TICKERS

    @pytest.mark.parametrize("ticker", sorted(MAJOR_ISSUERS))
    def test_major_issuers_are_not_deleted(self, ticker: str) -> None:
        assert ticker not in DELISTED_TICKERS

    def test_issuer_ordinary_lines_survive_their_dead_paper(self) -> None:
        """Deleting a bond series must not take the issuer's own ticker with it."""
        for ordinary in ("SQBN", "KPBA", "IPKY", "IPTB", "TRSB", "HMKB", "MCBA", "UZMK"):
            assert ordinary not in DELISTED_TICKERS

    def test_is_delisted_normalises(self) -> None:
        assert is_delisted("sqb2") and is_delisted("  SQB2 ")
        assert not is_delisted(None) and not is_delisted("")


class TestCatalogRemoval:
    def test_dropped_from_company_catalog(self) -> None:
        from company_catalog import COMPANY_CATALOG, COMPANY_SECTORS

        assert not (set(COMPANY_CATALOG.values()) & DELISTED_TICKERS)
        assert not (set(COMPANY_SECTORS) & DELISTED_TICKERS)

    def test_hidden_from_the_market_board(self) -> None:
        import api

        assert DELISTED_TICKERS <= api.BOARD_DENYLIST


@pytest.fixture()
def catalog_db(tmp_path, monkeypatch):
    """A catalog DB seeded with one delisted and one live ticker per table."""
    path = tmp_path / "catalog.db"
    monkeypatch.setattr(rc, "_catalog_db_path", lambda: str(path))
    conn = rc.get_catalog_conn()
    rc._init_schema(conn)
    with conn:
        for ticker in ("SQB2", "SQBN"):
            conn.execute(
                "INSERT INTO catalog_listings (ticker, isin, name, last_trade_date) VALUES (?,?,?,?)",
                (ticker, f"UZ7{ticker}", ticker, None))
            conn.execute(
                "INSERT INTO catalog_companies (ticker, company_name, org_id) VALUES (?,?,?)",
                (ticker, ticker, "1"))
            conn.execute(
                "INSERT INTO catalog_financials (ticker, form, year, revenue) VALUES (?,?,?,?)",
                (ticker, "NSBU", 2025, 1.0))
            conn.execute(
                "INSERT INTO facts (entity_id, dataset, field, period, value_text, source) "
                "VALUES (?,?,?,?,?,?)", (ticker, "org_map", "org_id", "", "1", "collector"))
        conn.execute("INSERT INTO catalog_trade_stats (isin, trade_date) VALUES (?,?)",
                     ("UZ7SQB2", "2026-07-24"))
    conn.close()
    return path


class TestPurge:
    def test_removes_every_trace_but_spares_the_live_ticker(self, catalog_db) -> None:
        removed = rc.purge_delisted()
        assert removed["catalog_listings"] == 1
        assert removed["catalog_companies"] == 1
        assert removed["catalog_financials"] == 1
        assert removed["facts"] == 1
        # Trade stats key on ISIN, so they must be resolved through the registry
        # row before it is deleted.
        assert removed["catalog_trade_stats"] == 1

        conn = sqlite3.connect(catalog_db)
        for table, column in (("catalog_listings", "ticker"), ("catalog_companies", "ticker"),
                              ("catalog_financials", "ticker"), ("facts", "entity_id")):
            rows = [r[0] for r in conn.execute(f"SELECT {column} FROM {table}")]
            assert rows == ["SQBN"], f"{table} still holds {rows}"
        conn.close()

    def test_is_idempotent(self, catalog_db) -> None:
        assert rc.purge_delisted()
        assert rc.purge_delisted() == {}

    def test_ingest_cannot_resurrect_a_deleted_row(self, catalog_db) -> None:
        """An older collector build still pushes these; the upsert must refuse."""
        rc.purge_delisted()
        written = rc.bulk_upsert_listings([
            {"ticker": "SQB2", "isin": "UZ7SQB2", "name": "resurrected"},
            {"ticker": "SQBN", "isin": "UZ7SQBN", "name": "live"},
        ])
        assert written == 1
        assert set(rc.get_all_listings()) == {"SQBN"}

    def test_read_path_filters_a_row_that_predates_the_deletion(self, catalog_db) -> None:
        """A ticker delisted after its row was written must not leak on read."""
        assert "SQB2" not in rc.get_all_listings()


class TestCollector:
    def test_registry_walk_skips_deleted_securities(self, monkeypatch) -> None:
        import listings_collector as lc

        detail = {
            "full_name_text": "O'zsanoatqurilishbank",
            "info_rfb": {"isin_codes": [
                {"ticker": "SQB2", "isu_cd": "UZ6001", "stock_type": "01"},
                {"ticker": "SQBN", "isu_cd": "UZ7001", "stock_type": "01"},
            ]},
        }

        class _Resp:
            def raise_for_status(self): pass
            def json(self): return detail

        class _Session:
            def get(self, *a, **k): return _Resp()

        monkeypatch.setattr(lc, "_make_session", lambda: _Session())
        monkeypatch.setattr(lc, "_org_ids", lambda: {"SQBN": "1"})
        monkeypatch.setattr(lc, "_uzse_equity", lambda *a, **k: None)
        monkeypatch.setattr(lc, "_uzse_bond_nominal", lambda *a, **k: None)
        monkeypatch.setattr(lc, "_last_conclusion", lambda *a, **k: None)

        tickers = {r["ticker"] for r in lc.collect_listing_rows()}
        assert tickers == {"SQBN"}
