"""Period discipline in the financials read path.

The regression this pins: ``_enrich_financials_from_facts`` wrote a fact from one
reporting period into a row labelled with another and left the label alone, so
UZMK served FY2024 revenue under "Q1 2026 (3 months)" — a ~5.5x overstatement
that also destroyed the fresher quarterly figure underneath it.
"""
from __future__ import annotations

import sqlite3

import pytest

import reports_catalog as rc
import catalogue.snapshots as catalogue_snapshots
import catalogue.codecs as catalogue_codecs
import catalogue.ratios as catalogue_ratios
import catalogue.snapshots as catalogue_snapshots


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE catalog_companies (ticker TEXT PRIMARY KEY, org_id TEXT);
        CREATE TABLE facts (
            entity_id TEXT, dataset TEXT, field TEXT, period TEXT,
            value_num REAL, value_text TEXT, unit TEXT, source TEXT, source_url TEXT,
            fetched_at TEXT
        );
        """
    )
    yield c
    c.close()


def _company(conn: sqlite3.Connection, ticker: str, org: str) -> None:
    conn.execute("INSERT INTO catalog_companies (ticker, org_id) VALUES (?, ?)", (ticker, org))


def _fact(conn: sqlite3.Connection, org: str, field: str, period: str, value: float) -> None:
    conn.execute(
        "INSERT INTO facts (entity_id, dataset, field, period, value_num, source) "
        "VALUES (?, 'financial_indicators', ?, ?, ?, 'test')",
        (org, field, period, value),
    )


def _row(year: int, quarter: int, **values: float | None) -> dict:
    row = {
        "year": year, "quarter": quarter, "is_ytd": bool(quarter),
        "revenue": None, "gross_profit": None, "cash": None,
        "total_liabilities": None, "net_income": None, "operating_income": None,
    }
    row.update(values)
    return row


class TestRowPeriod:
    @pytest.mark.parametrize(("year", "quarter", "expected"), [
        (2024, 0, "2024"),
        (2025, 1, "2025Q1"),
        (2026, 4, "2026Q4"),
        (2024, 5, "2024"),      # out-of-range quarter is not a quarter
        (None, 0, None),
    ])
    def test_labels(self, year, quarter, expected) -> None:
        assert catalogue_ratios._row_period({"year": year, "quarter": quarter}) == expected


class TestCrossPeriodOverwrite:
    """The reported UZMK regression, on the branch it actually came from.

    UZMK is an ORG_OVERRIDES ticker, so it took the "org is human-verified, the
    indicators are authoritative" path — which overwrote revenue and net income
    unconditionally, from whichever period happened to be newest on file.
    """

    UZMK_ORG = rc.ORG_OVERRIDES["UZMK"]

    def test_insurer_revenue_uses_openinfo_net_revenue(self, conn, monkeypatch) -> None:
        """Insurance P/S must receive line 060, not gross written premiums."""
        ticker, org = "INSURE", "insurance-org"
        monkeypatch.setitem(rc.COMPANY_SECTORS, ticker, "finance")
        _company(conn, ticker, org)
        _fact(conn, org, "net_revenue", "2026Q1", 400_000.0)
        out = {ticker: _row(2026, 1, revenue=900_000.0, org_type="insurance")}

        catalogue_snapshots._enrich_financials_from_facts(conn, out)

        assert out[ticker]["revenue"] == 400_000.0

    def test_the_uzmk_regression(self, conn) -> None:
        _company(conn, "UZMK", self.UZMK_ORG)
        _fact(conn, self.UZMK_ORG, "net_revenue", "2024", 5_500_000.0)
        _fact(conn, self.UZMK_ORG, "net_profit", "2024", 900_000.0)
        out = {"UZMK": _row(2026, 1, revenue=1_000_000.0, net_income=150_000.0)}

        catalogue_snapshots._enrich_financials_from_facts(conn, out)

        assert out["UZMK"]["revenue"] == 1_000_000.0, "FY2024 revenue clobbered a Q1 2026 figure"
        assert out["UZMK"]["net_income"] == 150_000.0
        assert out["UZMK"]["year"] == 2026 and out["UZMK"]["quarter"] == 1
        assert not out["UZMK"].get("field_periods")

    def test_the_rows_own_period_is_authoritative_and_overwrites(self, conn) -> None:
        _company(conn, "UZMK", self.UZMK_ORG)
        _fact(conn, self.UZMK_ORG, "net_revenue", "2026Q1", 1_200_000.0)
        _fact(conn, self.UZMK_ORG, "net_revenue", "2024", 5_500_000.0)
        out = {"UZMK": _row(2026, 1, revenue=1_000_000.0)}

        catalogue_snapshots._enrich_financials_from_facts(conn, out)

        # Same period, cleaner source — this is the correction the pass exists for,
        # and it must still prefer the row's period over the newest on file.
        assert out["UZMK"]["revenue"] == 1_200_000.0
        assert not out["UZMK"].get("field_periods")

    def test_a_null_is_filled_and_its_real_period_recorded(self, conn) -> None:
        _company(conn, "UZMK", self.UZMK_ORG)
        _fact(conn, self.UZMK_ORG, "total_liabilities", "2024", 3_000_000.0)
        out = {"UZMK": _row(2026, 1, revenue=1_000_000.0)}

        catalogue_snapshots._enrich_financials_from_facts(conn, out)

        assert out["UZMK"]["total_liabilities"] == 3_000_000.0
        assert out["UZMK"]["field_periods"] == {"total_liabilities": "2024"}

    def test_non_override_issuers_keep_their_parsed_figure(self, conn) -> None:
        # Unchanged policy for plain issuers: the NSBU parse is the source and the
        # indicator only fills blanks. What is new is that the fill is labelled.
        _company(conn, "PLAIN", "900")
        _fact(conn, "900", "net_revenue", "2023", 9_000_000.0)
        out = {"PLAIN": _row(2025, 2, revenue=2_000_000.0)}

        catalogue_snapshots._enrich_financials_from_facts(conn, out)

        assert out["PLAIN"]["revenue"] == 2_000_000.0
        assert not out["PLAIN"].get("field_periods")


class TestBankCoverageIsPreserved:
    """Filling genuinely-absent figures must keep working — banks file no NSBU
    revenue line at all, and blanking them would undo real coverage."""

    def test_bank_revenue_is_still_filled(self, conn, monkeypatch) -> None:
        monkeypatch.setitem(rc.COMPANY_SECTORS, "BANK", "finance")
        _company(conn, "BANK", "300")
        _fact(conn, "300", "net_revenue", "2024", 4_000_000.0)
        _fact(conn, "300", "net_profit", "2024", 800_000.0)
        out = {"BANK": _row(2024, 0)}

        catalogue_snapshots._enrich_financials_from_facts(conn, out)

        assert out["BANK"]["revenue"] == 4_000_000.0
        assert out["BANK"]["net_income"] == 800_000.0
        # Same period as the row — nothing to footnote.
        assert not out["BANK"].get("field_periods")

    def test_bank_revenue_from_another_period_is_labelled(self, conn, monkeypatch) -> None:
        monkeypatch.setitem(rc.COMPANY_SECTORS, "BANK", "finance")
        _company(conn, "BANK", "300")
        _fact(conn, "300", "net_revenue", "2024", 4_000_000.0)
        out = {"BANK": _row(2026, 1, net_income=90_000.0)}

        catalogue_snapshots._enrich_financials_from_facts(conn, out)

        assert out["BANK"]["revenue"] == 4_000_000.0
        assert out["BANK"]["field_periods"] == {"revenue": "2024"}


class TestSignFlip:
    """A sign flip corrects THIS row's own number, so it stays unlabelled."""

    def test_same_magnitude_opposite_sign_is_corrected(self, conn) -> None:
        _company(conn, "SIGN", "400")
        _fact(conn, "400", "net_profit", "2024", -500_000.0)
        out = {"SIGN": _row(2024, 0, net_income=500_000.0)}

        catalogue_snapshots._enrich_financials_from_facts(conn, out)

        assert out["SIGN"]["net_income"] == -500_000.0
        assert not out["SIGN"].get("field_periods")

    def test_a_genuine_magnitude_disagreement_is_left_alone(self, conn) -> None:
        _company(conn, "SIGN", "400")
        _fact(conn, "400", "net_profit", "2024", -900_000.0)
        out = {"SIGN": _row(2024, 0, net_income=500_000.0)}

        catalogue_snapshots._enrich_financials_from_facts(conn, out)

        # Not the same number — flagged by the audit, never silently "corrected".
        assert out["SIGN"]["net_income"] == 500_000.0


class TestFieldPeriodsRoundTrip:
    @pytest.mark.parametrize(("raw", "expected"), [
        (None, {}),
        ("", {}),
        ("{}", {}),
        ('{"revenue": "2024"}', {"revenue": "2024"}),
        ("not json", {}),
        ("[1,2]", {}),
        ({"revenue": "2024"}, {"revenue": "2024"}),
        ({"revenue": None}, {}),
    ])
    def test_decode(self, raw, expected) -> None:
        assert catalogue_codecs._decode_field_periods(raw) == expected

    def test_encode_is_none_when_empty(self) -> None:
        assert catalogue_codecs._encode_field_periods({}) is None
        assert catalogue_codecs._encode_field_periods(None) is None

    def test_encode_round_trips(self) -> None:
        encoded = catalogue_codecs._encode_field_periods({"revenue": "2024", "cash": "2023Q2"})
        assert catalogue_codecs._decode_field_periods(encoded) == {"revenue": "2024", "cash": "2023Q2"}
