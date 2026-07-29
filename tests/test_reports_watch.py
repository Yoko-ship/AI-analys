"""The filing watcher that keeps the board from waiting a day (reports_watch.py).

Fixtures are shaped like the real feed: openinfo's ``/reports/main/`` gives a naive
Tashkent ``pub_date``, an ``organization`` id and a form, and nothing else — no period,
no figures. Everything the watcher decides comes from that plus what prod already serves.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reports_watch as rw  # noqa: E402

UZTL_ORG = 666


def filing(org=UZTL_ORG, pub="2026-07-29T11:27:42", form="NSBU", period="quarter"):
    return {"organization": org, "pub_date": pub, "report_form": form,
            "period_type": period, "id": 31090, "object_id": 18692}


@pytest.fixture
def one_org(monkeypatch):
    """openinfo's registry lists an issuer's classes together: 'UZTL, UZTLP'."""
    monkeypatch.setattr(rw.orc, "ticker_org_map", lambda refresh=False: {"UZTL": UZTL_ORG, "UZTLP": UZTL_ORG})
    monkeypatch.setattr(rw.orc, "ORG_ID_OVERRIDE", {})


def test_pub_date_is_tashkent_wall_clock(monkeypatch):
    """Read as UTC, a filing from the last five hours falls outside every window."""
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((rw._now_local() - utc_now).total_seconds() - 5 * 3600) < 120


def test_both_share_classes_follow_their_issuer(one_org):
    found = rw.candidates([filing()], known_tickers={"UZTL", "UZTLP"})
    assert sorted(found) == ["UZTL", "UZTLP"]
    assert found["UZTL"]["object_id"] == 18692


def test_a_delisted_issuer_is_never_pushed_back_onto_the_board(monkeypatch):
    """openinfo keeps filing for issuers the exchange dropped (MNGM, OCBK)."""
    monkeypatch.setattr(rw.orc, "ticker_org_map", lambda refresh=False: {"MNGM": 999, "UZTL": UZTL_ORG})
    monkeypatch.setattr(rw.orc, "ORG_ID_OVERRIDE", {})
    found = rw.candidates([filing(org=999), filing()], known_tickers={"UZTL"})
    assert sorted(found) == ["UZTL"]


def test_an_ifrs_filing_changes_nothing_the_board_serves(one_org):
    """MSFO is a PDF the reconciler cannot read — it must not trigger a refresh."""
    assert rw.candidates([filing(form="MSFO")], known_tickers={"UZTL", "UZTLP"}) == {}


def test_the_newest_filing_wins_per_ticker(one_org):
    feed = [filing(pub="2026-07-29T11:27:42"), filing(pub="2026-04-28T17:28:07")]
    assert rw.candidates(feed, known_tickers={"UZTL"})["UZTL"]["pub_date"] == "2026-07-29T11:27:42"


# --- what counts as a change ------------------------------------------------

def served(year=2026, quarter=1, revenue=2_519_903_616_000.0):
    return {"year": year, "quarter": quarter, "revenue": revenue,
            "gross_profit": 852_643_177_000.0, "cash": None,
            "total_liabilities": None, "net_income": None, "operating_income": None}


def reconciled(year=2026, quarter=2, revenue=5_123_511_838_000.0):
    return {"ticker": "UZTL", "year": year, "quarter": quarter, "revenue_full": revenue,
            "gross_profit_full": 1_832_293_869_000.0, "cash_full": None,
            "total_liabilities_full": None, "net_income_full": None,
            "operating_income_full": None}


def test_a_newer_period_is_the_whole_point():
    assert rw._changed(reconciled(), served()) == "2026Q1 -> 2026Q2"


def test_the_same_period_with_the_same_figures_is_left_alone():
    row = reconciled(quarter=1, revenue=2_519_903_616_000.0)
    row["gross_profit_full"] = 852_643_177_000.0
    assert rw._changed(row, served()) is None


def test_a_restatement_of_the_same_period_is_republished():
    row = reconciled(quarter=1, revenue=2_600_000_000_000.0)
    row["gross_profit_full"] = 852_643_177_000.0
    assert rw._changed(row, served()) == "revenue restated"


def test_rounding_noise_is_not_a_restatement():
    row = reconciled(quarter=1, revenue=2_519_903_616_000.0 * 1.001)
    row["gross_profit_full"] = 852_643_177_000.0
    assert rw._changed(row, served()) is None


def test_an_older_period_never_pushes_backwards():
    """A partial read must not roll the board back to last quarter."""
    assert rw._changed(reconciled(quarter=1), served(quarter=2)) is None


def test_a_ticker_the_board_lists_but_has_no_figures_for_is_filled():
    assert rw._changed(reconciled(), None) == "not served yet"


def test_a_metric_appearing_for_the_first_time_counts():
    row = reconciled(quarter=1, revenue=2_519_903_616_000.0)
    row["gross_profit_full"] = 852_643_177_000.0
    row["net_income_full"] = 25_729_613_000.0
    assert rw._changed(row, served()) == "net_income appeared"


# --- feed paging ------------------------------------------------------------

def test_the_window_stops_paging_at_the_first_old_filing(monkeypatch):
    now = rw._now_local()
    pages = {
        1: {"results": [{"id": 1, "organization": UZTL_ORG, "report_type": "NSBU",
                         "pub_date": (now - timedelta(hours=2)).isoformat(),
                         "properties": {"report_type": "quarter"}},
                        {"id": 2, "organization": UZTL_ORG, "report_type": "NSBU",
                         "pub_date": (now - timedelta(days=9)).isoformat(),
                         "properties": {"report_type": "quarter"}}],
             "next": "page2"},
        2: {"results": [{"id": 3}], "next": None},
    }
    seen: list[int] = []

    def fake_get(url, params=None):
        seen.append(params["page"])
        return pages[params["page"]]

    monkeypatch.setattr(rw.orc, "_getj", fake_get)
    out = rw.recent_filings(hours=48)
    assert [f["id"] for f in out] == [1]
    assert seen == [1]  # the second page is never fetched


def test_an_unparseable_pub_date_ends_the_scan_rather_than_being_guessed(monkeypatch):
    now = rw._now_local()
    monkeypatch.setattr(rw.orc, "_getj", lambda url, params=None: {
        "results": [{"id": 1, "organization": UZTL_ORG, "report_type": "NSBU",
                     "pub_date": (now - timedelta(hours=1)).isoformat(),
                     "properties": {"report_type": "quarter"}},
                    {"id": 2, "organization": UZTL_ORG, "report_type": "NSBU",
                     "pub_date": "not a date", "properties": {}}],
        "next": None})
    assert [f["id"] for f in rw.recent_filings(hours=48)] == [1]
