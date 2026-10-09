"""The unified news calendar (calendar_events.py).

Every event on it is a date a source states. These tests pin the cases where a
naive read of the sources would put a date on the calendar that nobody filed:
a share class with no payout, a typo'd decision year, a meeting hour copied
from a filing timestamp.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import calendar_events  # noqa: E402
import dbx  # noqa: E402


def filing(**over):
    row = {
        "filing_id": "4236", "organization": '"Buxoroneftgazparmalash" AJ', "ticker": "BNGP",
        "tickers": ["BNGP", "BNGPP"], "decision_date": "2026-09-25", "pub_date": "2026-10-05T15:17:42",
        "ordinary_amount": 242.47, "ordinary_percent": 4.85,
        "ordinary_start": "2026-10-01", "ordinary_end": "2026-11-24",
        "preferred_amount": 242.47, "preferred_percent": 4.85,
        "preferred_start": "2026-10-01", "preferred_end": "2026-11-24",
        # openinfo fills a start date for a class that declared nothing.
        "bond_amount": 0.0, "bond_percent": 0.0, "bond_start": "2026-10-05", "bond_end": None,
        "link": "https://openinfo.uz/facts/32/4236",
    }
    row.update(over)
    return row


class TestDividendSteps:
    def test_classes_sharing_a_date_make_one_event(self):
        events = calendar_events._dividend_events(filing(), "2026-01-01", "2027-01-01")
        by_kind = {e["kind"]: e for e in events}
        assert set(by_kind) == {"decision", "payment_start", "payment_end"}
        assert by_kind["payment_start"]["date"] == "2026-10-01"
        assert by_kind["payment_start"]["classes"] == ["ordinary", "preferred"]
        assert by_kind["payment_end"]["date"] == "2026-11-24"
        assert by_kind["decision"]["date"] == "2026-09-25"

    def test_a_class_without_an_amount_puts_nothing_on_the_calendar(self):
        events = calendar_events._dividend_events(filing(), "2026-10-05", "2026-10-06")
        assert events == []
        detail = calendar_events._dividend_events(filing(), "2026-01-01", "2027-01-01")[0]["details"]
        assert [c["class"] for c in detail["classes"]] == ["ordinary", "preferred"]

    def test_a_decision_dated_after_its_own_filing_is_dropped(self):
        events = calendar_events._dividend_events(
            filing(decision_date="2108-10-02"), "2000-01-01", "2200-01-01")
        assert "decision" not in {e["kind"] for e in events}
        assert all(e["details"]["decision_date"] is None for e in events)

    def test_only_steps_inside_the_window_are_returned(self):
        events = calendar_events._dividend_events(filing(), "2026-11-01", "2026-12-01")
        assert [(e["kind"], e["date"]) for e in events] == [("payment_end", "2026-11-24")]

    def test_ids_are_unique_per_step(self):
        events = calendar_events._dividend_events(filing(), "2026-01-01", "2027-01-01")
        assert len({e["id"] for e in events}) == len(events)


class TestMeetingTime:
    @pytest.mark.parametrize("value, expected", [
        ("2026-10-02T10:00:00", "10:00"),
        ("2026-10-01T16:19:12", None),   # the filing timestamp, not an agenda
        ("2026-10-02T00:00:00", None),   # a bare date
        ("2026-10-02", None),
    ])
    def test_only_a_filed_hour_is_shown(self, value, expected):
        assert calendar_events._meeting_time(value) == expected


class TestRange:
    def test_defaults_to_the_current_month(self, monkeypatch):
        from datetime import date
        monkeypatch.setattr(calendar_events, "_today", lambda: date(2026, 2, 11))
        first, last = calendar_events.parse_range(None, None)
        assert (first.isoformat(), last.isoformat()) == ("2026-02-01", "2026-02-28")

    @pytest.mark.parametrize("start, end", [
        ("2026-10-09", "2026-10-01"), ("2026-01-01", "2027-06-01"), ("09.10.2026", None)])
    def test_a_bad_range_is_refused(self, start, end):
        with pytest.raises(ValueError):
            calendar_events.parse_range(start, end)


class TestMerge:
    def test_one_failing_source_leaves_the_rest(self, monkeypatch):
        def broken(lo, hi):
            raise RuntimeError("openinfo is down")

        monkeypatch.setattr(calendar_events, "SOURCES", {
            "meeting": broken,
            "report": lambda lo, hi: [{"id": "r", "type": "report", "date": "2026-10-03",
                                       "organization": "B"}],
            "dividend": lambda lo, hi: [{"id": "d", "type": "dividend", "date": "2026-10-03",
                                         "organization": "A"},
                                        {"id": "e", "type": "dividend", "date": "2026-10-01",
                                         "organization": "Z"}],
        })
        out = calendar_events.events_between("2026-10-01", "2026-10-31")
        assert out["ok"] is True
        assert out["sources"]["meeting"]["ok"] is False
        # Date first, then the fixed type order (dividend before report).
        assert [e["id"] for e in out["items"]] == ["e", "d", "r"]

    def test_types_narrow_the_sources_read(self, monkeypatch):
        called = []
        monkeypatch.setattr(calendar_events, "SOURCES", {
            "meeting": lambda lo, hi: called.append("meeting") or [],
            "report": lambda lo, hi: called.append("report") or [],
        })
        calendar_events.events_between("2026-10-01", "2026-10-31", ["report", "nonsense"])
        assert called == ["report"]


class TestStore:
    """The SQL each source runs, against a scratch catalog and through dbx's
    PostgreSQL translation — production runs on PostgreSQL."""

    @pytest.fixture()
    def catalog(self, tmp_path, monkeypatch):
        import catalogue.storage as catalogue_storage

        monkeypatch.setattr(catalogue_storage, "_catalog_db_path", lambda: str(tmp_path / "catalog.db"))
        seen: list[str] = []
        original = dbx.Cursor.execute

        def recording(self, sql, params=None):
            seen.append(sql)
            return original(self, sql, params)

        monkeypatch.setattr(dbx.Cursor, "execute", recording)
        return seen

    def test_meetings_notices_and_reports_read_back(self, catalog, monkeypatch):
        import meetings
        from catalogue.storage import get_catalog_conn

        monkeypatch.setattr(meetings, "ensure_snapshot", lambda: {"announcements": 1})
        meetings.replace_snapshot([
            {"announcement_id": "21349", "org_id": "1", "organization": "АО Alpha", "ticker": "ALFA",
             "title": "Внеочередное общее собрание акционеров",
             "meeting_date": "2026-10-20T10:00:00", "pub_date": "2026-09-28T09:00:00"},
            {"announcement_id": "21350", "org_id": "2", "organization": "АО Beta", "ticker": None,
             "title": "Объявления", "meeting_date": "2026-11-05T11:00:00", "pub_date": "2026-10-02T12:00:00"},
        ])
        conn = get_catalog_conn()
        conn.execute(
            "INSERT INTO catalog_reports (ticker, report_form, period_type, year, quarter, title, published_at, pdf_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ALFA", "NAS", "quarterly", 2026, 2, "Q2", "2026-10-07 09:40:00", "https://x/r.pdf"))
        conn.commit()
        conn.close()

        lo, hi = "2026-10-01", "2026-11-01"
        meetings_in = calendar_events._meetings(lo, hi)
        assert [(e["id"], e["date"], e["time"]) for e in meetings_in] == [("meeting:21349", "2026-10-20", "10:00")]
        notices = calendar_events._notices(lo, hi)
        assert [(e["id"], e["date"], e["details"]["meeting_date"]) for e in notices] == [
            ("notice:21350", "2026-10-02", "2026-11-05")]
        reports = calendar_events._reports(lo, hi)
        assert [(e["ticker"], e["date"], e["details"]["quarter"]) for e in reports] == [("ALFA", "2026-10-07", 2)]

        for sql in catalog:
            translated = dbx.translate(sql, dbx.POSTGRES)
            assert not re.search(r"\b(datetime|GROUP_CONCAT|IFNULL)\s*\(", translated, re.I), translated

    def test_material_facts_split_the_issuer_from_the_fact(self, catalog, monkeypatch):
        import news_store
        from catalogue.storage import get_catalog_conn

        monkeypatch.setattr(news_store, "disclosure_source_ids", lambda: {"openinfo_facts"})
        conn = get_catalog_conn()
        conn.execute(
            "INSERT INTO news (url, source, source_id, title, published_at) VALUES (?, ?, ?, ?, ?)",
            ("https://openinfo.uz/ru/organizations/30?fact=99663", "openinfo.uz — material facts",
             "openinfo_facts", "\"O'zsanoatqurilishbank\" ATB: Решения высшего органа управления",
             "2026-10-08T16:09:27"))
        conn.execute(
            "INSERT INTO news (url, source, source_id, title, published_at) VALUES (?, ?, ?, ?, ?)",
            ("https://press.example/1", "press", "press", "A retelling: same fact", "2026-10-08T17:00:00"))
        news_id = conn.execute("SELECT id FROM news WHERE source_id = 'openinfo_facts'").fetchone()[0]
        conn.execute("INSERT INTO news_entities (news_id, ticker) VALUES (?, ?)", (news_id, "SQBNP"))
        conn.execute("INSERT INTO news_entities (news_id, ticker) VALUES (?, ?)", (news_id, "SQBN"))
        conn.commit()
        conn.close()

        facts = calendar_events._facts("2026-10-01", "2026-11-01")
        assert len(facts) == 1
        fact = facts[0]
        assert fact["organization"] == "\"O'zsanoatqurilishbank\" ATB"
        assert fact["title"] == "Решения высшего органа управления"
        assert fact["tickers"] == ["SQBN", "SQBNP"] and fact["ticker"] == "SQBN"
        # Not classified yet: no page of ours to open, the source link stands in.
        assert fact["news_id"] is None
        assert fact["details"]["link"].startswith("https://openinfo.uz/")
        for sql in catalog:
            translated = dbx.translate(sql, dbx.POSTGRES)
            assert not re.search(r"\b(datetime|GROUP_CONCAT|IFNULL)\s*\(", translated, re.I), translated
