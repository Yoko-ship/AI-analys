"""Dividend calendar → ticker mapping (dividends.py).

openinfo publishes one calendar for the whole market, keyed by
``organization_id``. It carries our ticker on barely half its rows and it names
issuers in families that share a stem — «O'zbekinvest» / «O'zbekinvest Hayot»,
«Andijon biokimyo zavodi» / «QO'QON BIOKIMYO», «Universal bank» / «Namangan
chorsu dehqon universal bozori». Every test below pins a case that was observed
in the live 3 995-row calendar while this mapper was being built: the first
version of it, which matched on name containment, handed a bank a bazaar's
dividends and gave BIOK the payouts of two other chemical plants.
"""
from __future__ import annotations

import catalogue.storage as catalogue_storage

import re

import pytest

import dbx
import dividends

# Spellings PostgreSQL has no answer for, checked against the TRANSLATED
# statement — a hit means dbx's translation missed it.
SQLITE_ONLY = (
    (re.compile(r"\bdatetime\s*\(", re.I), "datetime() — PostgreSQL has no such function"),
    (re.compile(r"\bGROUP_CONCAT\s*\(", re.I), "GROUP_CONCAT — use string_agg"),
    (re.compile(r"\bINSERT\s+OR\s+(IGNORE|REPLACE)\b", re.I), "INSERT OR … — use ON CONFLICT"),
    (re.compile(r"\bIFNULL\s*\(", re.I), "IFNULL — use COALESCE"),
    (re.compile(r"\bAUTOINCREMENT\b", re.I), "AUTOINCREMENT"),
)


def _assert_translates_clean(statements: list[str]) -> None:
    assert statements, "nothing was captured — the fixture is not wired up"
    for sql in statements:
        translated = dbx.translate(sql, dbx.POSTGRES)
        for pattern, why in SQLITE_ONLY:
            assert not pattern.search(translated), (
                f"{why}\n  source:     {' '.join(sql.split())[:160]}\n"
                f"  translated: {' '.join(translated.split())[:160]}")
        assert "?" not in re.sub(r"'[^']*'", "", translated), (
            f"a placeholder survived translation: {' '.join(translated.split())[:160]}")


def entry(ticker, *, org=None, names=(), type_="stock", isin=None):
    return {"ticker": ticker, "org_id": org, "names": list(names),
            "type": type_, "isin": isin}


def filing(filing_id, org_id, organization, *, ticker=None, common=100.0,
           preferred=0.0, decision="2026-06-16"):
    return {
        "id": filing_id,
        "organization_id": org_id,
        "organization": organization,
        "ticker": ticker,
        "decision_date": decision,
        "pub_date": f"{decision}T10:00:00",
        "common_share_amount": common,
        "common_share_percent": "10.0000000000",
        "common_share_start_date": decision,
        "common_share_end_date": "2026-08-16",
        "priviliged_share_amount": preferred,
        "priviliged_share_percent": "0E-10",
        "priviliged_share_start_date": "2026-07-01" if preferred else None,
        "priviliged_share_end_date": "2026-09-01" if preferred else None,
        "link": f"https://openinfo.uz/facts/32/{filing_id}",
    }


class TestOrgMatching:
    def test_ticker_is_never_the_lookup_key(self):
        """The bug: the endpoint asked openinfo to resolve "UNVB" as a company
        name. It is not one, so nine payouts read as «Дивиденды не объявлялись».
        organization_id 9 is what ties the filing to the bank."""
        universe = [entry("UNVB", org="9", names=['Aksiyadorlik-tijorat banki "Universal bank"'])]
        rows = dividends.map_rows([filing(4011, "9", 'ATB "Universal bank"')], universe)
        assert [r["ticker"] for r in rows] == ["UNVB"]
        assert rows[0]["matched_by"] == "org_id"
        assert rows[0]["ordinary_amount"] == 100.0

    def test_one_filing_lands_on_both_lines_of_the_issuer(self):
        """A filing declares the ordinary AND the preferred amount, so both
        securities show it and each renders its own column."""
        universe = [entry("ALKB", org="7", names=['"Aloqabank" ATB']),
                    entry("ALKBP", org="7", names=['"Aloqabank" ATB'])]
        rows = dividends.map_rows([filing(1, "7", 'AT "Aloqabank"', preferred=250.0)], universe)
        assert sorted(r["ticker"] for r in rows) == ["ALKB", "ALKBP"]
        assert {r["preferred_amount"] for r in rows} == {250.0}

    def test_an_unlisted_issuers_filing_is_dropped(self):
        universe = [entry("UNVB", org="9", names=['ATB "Universal bank"'])]
        assert dividends.map_rows([filing(2, "940", '"NEO INSURANCE CORP" AJ')], universe) == []


class TestWeakerEvidence:
    def test_the_ticker_column_is_used_when_the_org_is_unknown(self):
        """EQQU resolves to no org, and the calendar's own ticker column names it."""
        universe = [entry("EQQU", names=["<Elektrqishloqqurilish> aksiyadorlik jamiyati"])]
        rows = dividends.map_rows(
            [filing(3, "555", '"Elektrqishloqqurilish" AJ', ticker="EQQU")], universe)
        assert [r["ticker"] for r in rows] == ["EQQU"]
        assert rows[0]["matched_by"] == "ticker_field"

    def test_the_ticker_column_may_name_several_securities(self):
        universe = [entry("KASU", names=["Kapital sug'urta"]),
                    entry("KASUP", names=["Kapital sug'urta"])]
        rows = dividends.map_rows(
            [filing(4, "556", "Kapital sug'urta AJ", ticker="KASU, KASUP")], universe)
        assert sorted(r["ticker"] for r in rows) == ["KASU", "KASUP"]

    def test_a_resolved_ticker_ignores_evidence_from_another_org(self):
        """BIOK is pinned to org 78 (Andijon biokimyo) in ORG_OVERRIDES because
        two other plants match it by name. openinfo's own ticker column claims
        one of them. A ticker whose issuer is known takes that issuer's filings
        and nothing else."""
        universe = [entry("BIOK", org="78", names=['"Andijon biokimyo zavodi" AJ', "Biokimyo"])]
        rows = dividends.map_rows([
            filing(5, "78", '"Andijon biokimyo zavodi" AJ'),
            filing(6, "433", '"QO\'QON BIOKIMYO" AJ'),
            filing(7, "434", '"Biokimyo" AJ', ticker="BIOK"),
        ], universe)
        assert [r["org_id"] for r in rows] == ["78"]


class TestNameMatching:
    def test_legal_forms_reduce_away(self):
        assert dividends._core_key('ATB "Universal bank"') == "universalbank"
        assert dividends._core_key('Aksiyadorlik-tijorat banki "Universal bank"') == "universalbank"
        assert dividends._core_key('"93-maxsus trest" AJ') == dividends._core_key("93-MAXSUS TREST")

    def test_a_shared_stem_is_not_a_match(self):
        """«O'zbekinvest» and «O'zbekinvest Hayot» are different issuers, and the
        second one's payouts must not reach the first one's ticker."""
        universe = [entry("UZIN", names=["O'zbekinvest"]), entry("UZINP", names=["O'zbekinvest"])]
        rows = dividends.map_rows([
            filing(8, "835", '"O\'zbekinvest"'),
            filing(9, "898", "O'zbekinvest Hayot"),
        ], universe)
        assert {r["org_id"] for r in rows} == {"835"}
        assert sorted(r["ticker"] for r in rows) == ["UZIN", "UZINP"]

    def test_a_generic_word_inside_a_longer_name_is_not_a_match(self):
        """«Universal bank» once collected «Namangan chorsu dehqon universal
        bozori» — a market hall — because "universal" was a substring."""
        universe = [entry("UNVB", names=['ATB "Universal bank"'])]
        assert dividends.map_rows([filing(10, "763", '"Namangan chorsu dehqon universal bozori" AJ')],
                                  universe) == []

    def test_a_name_two_issuers_answer_to_matches_neither(self):
        universe = [entry("AAAA", names=["Sharq"]), entry("BBBB", names=["Sharq"])]
        assert dividends.map_rows([filing(11, "600", "Sharq")], universe) == []

    def test_an_exact_name_reaches_the_whole_issuer(self):
        universe = [entry("MXUS", names=["93-MAXSUS TREST"])]
        rows = dividends.map_rows([filing(12, "522", '"93-maxsus trest" AJ')], universe)
        assert [r["matched_by"] for r in rows] == ["name"]


class TestUniverse:
    def test_secondary_lines_belong_to_their_ordinary_line(self):
        listed = {"ALKB", "ALKBP", "UZAL", "UZAL2", "PLST"}
        assert dividends._base_ticker("ALKBP", listed) == "ALKB"
        assert dividends._base_ticker("UZAL2", listed) == "UZAL"
        assert dividends._base_ticker("ALKB", listed) is None
        # A ticker that merely ends in P or a digit is not a secondary line.
        assert dividends._base_ticker("PLST", listed) is None
        assert dividends._base_ticker("ACMT1B2", listed) is None

    def test_an_org_resolved_on_one_line_covers_the_issuer(self):
        """The catalog stores the org against whichever line it catalogued —
        UZINP has it and UZIN does not; the deterministic index sometimes has it
        the other way round."""
        universe = dividends.attach_org_ids(
            [entry("UZIN"), entry("UZINP", org="835")], use_index=False)
        assert {e["ticker"]: e["org_id"] for e in universe} == {"UZIN": "835", "UZINP": "835"}

    def test_bonds_are_left_out(self):
        """A bond pays a coupon, not a dividend, and its issuer's equity payouts
        are not its own — the company page does not offer the tab for one."""
        universe = [entry("ACMT1B2", org="1058", names=["AGAT CREDIT"], type_="bond")]
        assert dividends.map_rows([filing(13, "1058", '"AGAT CREDIT" AJ')], universe) == []
        assert dividends.map_rows([filing(13, "1058", '"AGAT CREDIT" AJ')],
                                  universe, include_bonds=True)


class TestSource:
    def test_a_short_read_is_refused(self, monkeypatch):
        """The snapshot REPLACES the stored table. Publishing half a calendar
        would delete real payout history and report it as no dividends."""
        pages = [{"count": 900, "next": None, "results": [filing(1, "9", "x")]}]
        fake = _FakeCollector(pages)
        from collectors.openinfo import transport
        monkeypatch.setattr(transport, "_json_get", fake._json_get)
        monkeypatch.setattr(transport, "_make_session", fake._make_session)
        with pytest.raises(RuntimeError, match="read short"):
            dividends.fetch_calendar()

    def test_every_page_is_read(self, monkeypatch):
        pages = [
            {"count": 3, "next": "?page=2", "results": [filing(1, "9", "x"), filing(2, "9", "x")]},
            {"count": 3, "next": None, "results": [filing(3, "9", "x")]},
        ]
        fake = _FakeCollector(pages)
        from collectors.openinfo import transport
        monkeypatch.setattr(transport, "_json_get", fake._json_get)
        monkeypatch.setattr(transport, "_make_session", fake._make_session)
        assert len(dividends.fetch_calendar()) == 3


class _FakeCollector:
    """Stands in for openinfo_collector's HTTP helpers inside fetch_calendar."""

    def __init__(self, pages):
        self._pages = pages

    def _make_session(self):
        return object()

    def _json_get(self, _session, _path, params):
        index = int(params.get("page", 1)) - 1
        return self._pages[index] if index < len(self._pages) else {"count": 0, "results": []}


class TestStore:
    """The snapshot round-trip, and what PostgreSQL would actually receive.

    Every statement here runs against a scratch SQLite catalog and is then put
    through dbx's translation — the news module shipped four SQLite-only idioms
    to production this way, each invisible locally (see
    tests/test_news_postgres_dialect.py, which this mirrors).
    """

    @pytest.fixture()
    def catalog(self, tmp_path, monkeypatch):
        import reports_catalog as rc
        import catalogue.storage as catalogue_storage

        monkeypatch.setattr(catalogue_storage, "_catalog_db_path", lambda: str(tmp_path / "catalog.db"))
        seen: list[str] = []
        original = dbx.Cursor.execute

        def recording(self, sql, params=None):
            seen.append(sql)
            return original(self, sql, params)

        monkeypatch.setattr(dbx.Cursor, "execute", recording)
        return seen

    def test_a_snapshot_reads_back(self, catalog):
        records = dividends.map_rows(
            [filing(4011, "9", 'ATB "Universal bank"', decision="2026-06-16"),
             filing(3570, "9", 'ATB "Universal bank"', decision="2025-06-17")],
            [entry("UNVB", org="9", names=['ATB "Universal bank"'])],
        )
        assert dividends.replace_snapshot(records) == 2

        payload = dividends.dividends_for("UNVB")
        assert payload["count"] == 2
        assert payload["source"] == "snapshot"
        # Newest decision first — the page's "latest dividend" card reads item 0.
        assert [i["decision_date"] for i in payload["items"]] == ["2026-06-16", "2025-06-17"]
        assert dividends.snapshot_state()["tickers"] == 1

        _assert_translates_clean(catalog)

    def test_a_refresh_replaces_rather_than_accumulates(self, catalog):
        universe = [entry("UNVB", org="9", names=['ATB "Universal bank"'])]
        dividends.replace_snapshot(dividends.map_rows([filing(1, "9", "x"), filing(2, "9", "x")], universe))
        dividends.replace_snapshot(dividends.map_rows([filing(1, "9", "x")], universe))
        assert dividends.snapshot_state()["filings"] == 1

    def test_a_chunk_boundary_does_not_drop_rows(self, catalog, monkeypatch):
        """Rows are written in multi-row chunks to keep the PostgreSQL round
        trips down; the boundary must not swallow the remainder."""
        monkeypatch.setattr(dividends, "INSERT_CHUNK", 3)
        universe = [entry("UNVB", org="9", names=["x"])]
        records = dividends.map_rows([filing(i, "9", "x") for i in range(1, 9)], universe)
        assert dividends.replace_snapshot(records) == 8
        assert dividends.snapshot_state()["filings"] == 8


class TestAge:
    def test_the_stamp_is_read_as_utc(self, monkeypatch):
        """updated_at is UTC on both backends. Reading it as local time reported
        a snapshot written seconds ago as hours old on any non-UTC machine."""
        import calendar as _calendar
        import time as _time

        stamp = "2026-08-04 19:18:12"
        epoch = _calendar.timegm(_time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))
        monkeypatch.setattr(dividends.time, "time", lambda: epoch + 3600)
        assert dividends._age_hours(stamp) == pytest.approx(1.0)

    def test_an_unwritten_snapshot_has_no_age(self):
        assert dividends._age_hours(None) is None
