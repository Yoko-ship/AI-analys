"""The report catalog lists companies, and openinfo files by ORGANISATION.

The catalog is keyed by ticker, and one issuer can hold several: a common and a
preferred share, or one ticker per bond series. That put «AGAT CREDIT» on the
/catalog page four times — once per bond series, each showing a different slice
of the same filings (3 reports, 0, 0, 1) — and it left Hamkorbank's audit
opinions unreachable, because they had been synced under HMKBP while the page
only ever offered HMKB.

The fixture is a catalog holding exactly that shape: one bond issuer under four
series tickers, one bank under a common and a preferred, and one ordinary
single-ticker company as the control.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reports_catalog as rc  # noqa: E402


COMPANIES = [
    # ticker, name, org
    ("ACMT1B2", '"AGAT CREDIT" AJ MMT', "1058"),
    ("ACMT1B3", '"AGAT CREDIT" AJ MMT', "1058"),
    ("ACMT2B4", '"AGAT CREDIT" AJ MMT', "1058"),
    ("ACMT2B5", '"AGAT CREDIT" AJ MMT', "1058"),
    ("HMKB", '"Hamkorbank" ATB', "8"),
    ("HMKBP", '"Hamkorbank" ATB (привилегированные)', "8"),
    ("KVTS", "Акционерное общество «Кварц»", "412"),
]

# ticker, form, period_type, year, quarter — the same filing under two of an
# issuer's tickers is one filing (HMKB/HMKBP 2024 NSBU).
REPORTS = [
    ("ACMT1B2", "NSBU", "quarter", 2026, 1),
    ("ACMT1B2", "MSFO", "annual", 2025, 0),
    ("ACMT2B5", "Audition", "annual", 2025, 0),
    ("HMKB", "NSBU", "annual", 2024, 0),
    ("HMKBP", "NSBU", "annual", 2024, 0),
    ("HMKBP", "Audition", "annual", 2015, 0),
    ("KVTS", "NSBU", "annual", 2024, 0),
]


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    db = tmp_path / "catalog.db"
    monkeypatch.setattr(rc, "_catalog_db_path", lambda: str(db))
    conn = rc.get_catalog_conn()  # creates the schema
    with conn:
        for ticker, name, org in COMPANIES:
            conn.execute(
                "INSERT INTO catalog_companies (ticker, company_name, org_id, last_synced_at) "
                "VALUES (?,?,?,?)", (ticker, name, org, f"2026-08-0{len(ticker) % 9 + 1}"))
        for ticker, form, period, year, quarter in REPORTS:
            conn.execute(
                "INSERT INTO catalog_reports (ticker, report_form, period_type, year, quarter, "
                "pdf_url, excel_url) VALUES (?,?,?,?,?,?,?)",
                (ticker, form, period, year, quarter,
                 f"https://openinfo.uz/{ticker}-{form}-{year}-{quarter}.pdf", None))
    conn.close()
    return db


class TestOneEntryPerIssuer:
    def test_a_bond_issuer_is_listed_once_not_once_per_series(self, catalog) -> None:
        rows = rc.list_companies_with_stats()

        tickers = [r["ticker"] for r in rows]
        assert tickers == ["ACMT1B2", "HMKB", "KVTS"]

    def test_the_entry_names_the_tickers_it_stands_for(self, catalog) -> None:
        rows = {r["ticker"]: r for r in rc.list_companies_with_stats()}

        assert rows["ACMT1B2"]["tickers"] == ["ACMT1B2", "ACMT1B3", "ACMT2B4", "ACMT2B5"]
        assert rows["HMKB"]["tickers"] == ["HMKB", "HMKBP"]
        assert rows["KVTS"]["tickers"] == ["KVTS"]

    def test_a_common_share_outranks_its_own_preferred(self, catalog) -> None:
        """HMKB, not HMKBP — the P is the same company's second class."""
        assert rc._canonical_ticker(["HMKBP", "HMKB"]) == "HMKB"
        # No common share to defer to: the first alphabetically, and stable.
        assert rc._canonical_ticker(["ACMT2B5", "ACMT1B2", "ACMT1B3"]) == "ACMT1B2"
        assert rc._canonical_ticker(["AGMKP"]) == "AGMKP"

    def test_the_counts_are_the_issuers_whole_record(self, catalog) -> None:
        """Each series held a slice: 2 reports, 0, 0, 1. The company has 3."""
        rows = {r["ticker"]: r for r in rc.list_companies_with_stats()}

        assert rows["ACMT1B2"]["total_count"] == 3
        assert (rows["ACMT1B2"]["nsbu_count"], rows["ACMT1B2"]["msfo_count"],
                rows["ACMT1B2"]["audit_count"]) == (1, 1, 1)

    def test_one_filing_under_two_tickers_is_counted_once(self, catalog) -> None:
        """Both HMKB and HMKBP carry the 2024 annual NSBU. It is one filing."""
        rows = {r["ticker"]: r for r in rc.list_companies_with_stats()}

        assert rows["HMKB"]["total_count"] == 2
        assert rows["HMKB"]["nsbu_count"] == 1

    def test_the_header_counts_what_the_list_shows(self, catalog) -> None:
        """"85 companies" over a list of 73 is a page contradicting itself."""
        rows = rc.list_companies_with_stats()
        stats = rc.get_catalog_stats()

        assert stats["companies_synced"] == len(rows)
        assert stats["total_reports"] == sum(r["total_count"] for r in rows)


class TestTheIssuersWholeRecordIsReachable:
    def test_the_index_gathers_every_ticker_of_the_issuer(self, catalog) -> None:
        """HMKBP's 2015 audit opinion was invisible: the page only asked HMKB."""
        index = rc.get_company_index("HMKB")

        assert index["report_count"] == 2
        years = {e["year"] for e in index["availability"]["Audition"]["annual"]}
        assert years == {2015}

    def test_a_sibling_ticker_answers_with_the_same_record(self, catalog) -> None:
        """Whichever ticker is asked for, the answer is the company's."""
        assert (rc.get_company_index("ACMT2B5")["report_count"]
                == rc.get_company_index("ACMT1B2")["report_count"] == 3)

    def test_a_report_filed_under_a_sibling_still_downloads(self, catalog) -> None:
        """The entry offers ACMT2B5's audit opinion under ACMT1B2 — the link has
        to resolve, or every merged row 404s the moment it is clicked."""
        urls = rc.get_report_urls("ACMT1B2", "Audition", 2025, 0)

        assert urls and urls["pdf_url"].endswith("ACMT2B5-Audition-2025-0.pdf")

    def test_the_tickers_own_report_still_wins(self, catalog) -> None:
        """Siblings are a fallback, not a substitute: HMKB's own copy answers."""
        urls = rc.get_report_urls("HMKB", "NSBU", 2024, 0)

        assert urls["pdf_url"].endswith("HMKB-NSBU-2024-0.pdf")

    def test_a_report_no_ticker_of_the_issuer_has_is_still_missing(self, catalog) -> None:
        assert rc.get_report_urls("ACMT1B2", "NSBU", 1999, 0) is None
        assert rc.get_report_urls("ZZZZ", "NSBU", 2024, 0) is None

    def test_the_company_page_reads_the_same_record(self, catalog) -> None:
        """/catalog and the company page look at one thing; per-ticker reads made
        them disagree — 38 filings on one and 28 on the other for the same bank."""
        page = rc.get_company_reports("HMKB")

        assert len(page) == rc.get_company_index("HMKB")["report_count"] == 2
        assert {(r["report_form"], r["year"]) for r in page} == {("NSBU", 2024), ("Audition", 2015)}

    def test_a_single_ticker_company_is_untouched(self, catalog) -> None:
        assert rc._org_siblings(rc.get_catalog_conn(), "KVTS") == ["KVTS"]
        assert rc.get_company_index("KVTS")["report_count"] == 1
        assert rc.get_report_urls("KVTS", "NSBU", 2024, 0)["pdf_url"].endswith(
            "KVTS-NSBU-2024-0.pdf")
