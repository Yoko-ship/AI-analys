"""The events timeline is dated by the ISSUER, and the «now» rows are refused.

`DEFAULT (datetime('now'))` reached PostgreSQL as `DEFAULT (TEXT('now'))` — the
type map rewrote DATETIME to TEXT before it looked for `datetime('now')` — so
every row that relied on that default was stamped with the literal string «now».
195 of the 199 rows in catalog_new_reports on prod carried it, and «now» sorts
above every real date AND satisfies every `>= datetime('now', ?)` window, so those
events pinned themselves to the head of the timeline where no cleanup could reach
them.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import pg_migrate
import reports_catalog as rc


@pytest.fixture()
def catalog(tmp_path, monkeypatch) -> sqlite3.Connection:
    db = tmp_path / "catalog.sqlite3"
    monkeypatch.setattr(rc, "_catalog_db_path", lambda: str(db))
    monkeypatch.setattr(rc, "_maybe_seed_financials", lambda *a, **k: None)
    conn = rc.get_catalog_conn()
    yield conn
    conn.close()


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


class TestTheTypeMapOrder:
    def test_the_clock_default_survives_the_datetime_to_text_rule(self) -> None:
        got = pg_migrate.translate_ddl("CREATE TABLE t (at DATETIME NOT NULL DEFAULT (datetime('now')))")

        assert "TEXT('now')" not in got, "the DATETIME rule ate the datetime() call"
        assert "to_char(now() AT TIME ZONE 'UTC'" in got
        assert "at TEXT NOT NULL" in got or "at  TEXT NOT NULL" in got or "TEXT" in got

    def test_a_bare_datetime_column_is_still_text(self) -> None:
        assert "TEXT" in pg_migrate.translate_ddl("CREATE TABLE t (at DATETIME)")


class TestTheEventsTimeline:
    def test_a_now_stamped_row_is_refused(self, catalog) -> None:
        with catalog:
            catalog.execute(
                "INSERT INTO catalog_new_reports (ticker, report_form, period_type, year, "
                "quarter, title, detected_at) VALUES ('AAA','NSBU','annual',2025,0,NULL,'now')")
            catalog.execute(
                "INSERT INTO catalog_new_reports (ticker, report_form, period_type, year, "
                "quarter, title, detected_at) VALUES ('BBB','NSBU','annual',2025,0,NULL,?)",
                (_iso(3),))

        got = rc.get_recent_new_reports(30, 50)

        assert [r["ticker"] for r in got] == ["BBB"]

    def test_a_new_row_stamps_its_own_clock(self, catalog) -> None:
        with catalog:
            rc._upsert_report(catalog, "AAA", report_form="NSBU", period_type="annual",
                              year=2025, quarter=0, title=None, published_at=None,
                              pdf_url=None, excel_url=None, excel_url_form1=None,
                              openinfo_report_id="1", object_id=None)

        row = catalog.execute("SELECT detected_at FROM catalog_new_reports").fetchone()

        assert row["detected_at"].startswith(datetime.now(timezone.utc).strftime("%Y-%m-%d")), \
            "the INSERT must state its own clock, not lean on the column default"

    def test_filings_are_ordered_by_the_issuers_publication_date(self, catalog) -> None:
        with catalog:
            for ticker, pub in (("AAA", _iso(2)), ("BBB", _iso(9)), ("CCC", _iso(1))):
                rc._upsert_report(catalog, ticker, report_form="NSBU", period_type="quarter",
                                  year=2026, quarter=2, title=None, published_at=pub,
                                  pdf_url="p", excel_url="x", excel_url_form1="x",
                                  openinfo_report_id=ticker, object_id=None)

        got = rc.get_recent_filings(30, 50)

        assert [r["ticker"] for r in got] == ["CCC", "AAA", "BBB"]
        assert got[0]["pdf_url"] == "p", "a row in the timeline links to the document"

    def test_a_filing_with_no_publication_date_stays_out(self, catalog) -> None:
        """A timeline is a claim about WHEN; «unknown» has no place in one."""
        with catalog:
            rc._upsert_report(catalog, "AAA", report_form="NSBU", period_type="annual",
                              year=2025, quarter=0, title=None, published_at=None,
                              pdf_url=None, excel_url=None, excel_url_form1=None,
                              openinfo_report_id="1", object_id=None)

        assert rc.get_recent_filings(30, 50) == []

    def test_the_window_is_honoured(self, catalog) -> None:
        with catalog:
            rc._upsert_report(catalog, "OLD", report_form="NSBU", period_type="annual",
                              year=2020, quarter=0, title=None, published_at=_iso(400),
                              pdf_url=None, excel_url=None, excel_url_form1=None,
                              openinfo_report_id="1", object_id=None)
            rc._upsert_report(catalog, "NEW", report_form="NSBU", period_type="annual",
                              year=2025, quarter=0, title=None, published_at=_iso(5),
                              pdf_url=None, excel_url=None, excel_url_form1=None,
                              openinfo_report_id="2", object_id=None)

        assert [r["ticker"] for r in rc.get_recent_filings(30, 50)] == ["NEW"]

    def test_a_sync_with_no_date_does_not_erase_the_one_on_file(self, catalog) -> None:
        """The structured accounting feed carries no publication date; an hourly
        re-sync must not blank the date the unified feed established."""
        with catalog:
            rc._upsert_report(catalog, "AAA", report_form="NSBU", period_type="quarter",
                              year=2026, quarter=2, title=None, published_at=_iso(4),
                              pdf_url=None, excel_url="x", excel_url_form1="x",
                              openinfo_report_id="1", object_id=None)
            rc._upsert_report(catalog, "AAA", report_form="NSBU", period_type="quarter",
                              year=2026, quarter=2, title=None, published_at=None,
                              pdf_url=None, excel_url="x", excel_url_form1="x",
                              openinfo_report_id="1", object_id=None)

        assert len(rc.get_recent_filings(30, 50)) == 1
