"""The report catalog keeps itself current, instead of waiting for a button.

`sync_all` has always existed, and the daily collector calls it — but the
collectors have no database of their own: they POST results to the API over
HTTP, and the report catalog is not among what they post. So `catalog_reports`
only moved when an admin pressed «Синхронизировать всё». It was last pressed on
2026-07-21, and between 13 July and 5 August fifty issuers filed their half-year
report. The site did not have a single one of them.

The fix reads openinfo's filing feed — one request that answers "who filed" —
and re-syncs only those issuers, with the full sweep as a daily backstop for
what a feed cannot show: an issuer we have never catalogued, and the audit
opinions, whose endpoint has no per-issuer filter.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import reports_catalog as rc  # noqa: E402


COMPANIES = [
    # ticker, name, org — HMKB/HMKBP are one issuer, ACMT* are one issuer
    ("HMKB", '"Hamkorbank" ATB', "8"),
    ("HMKBP", '"Hamkorbank" ATB (привилегированные)', "8"),
    ("ACMT1B2", '"AGAT CREDIT" AJ MMT', "1058"),
    ("ACMT2B5", '"AGAT CREDIT" AJ MMT', "1058"),
    ("KVTS", "Акционерное общество «Кварц»", "412"),
]


def filing(org, pub="2026-08-05T15:59:00", form="NSBU", period="quarter"):
    return {"organization": org, "pub_date": pub, "report_form": form,
            "period_type": period, "id": 1, "object_id": 2}


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    """A catalog whose entries were all synced a week ago."""
    stale = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    db = tmp_path / "catalog.db"
    monkeypatch.setattr(rc, "_catalog_db_path", lambda: str(db))
    conn = rc.get_catalog_conn()
    with conn:
        for ticker, name, org in COMPANIES:
            conn.execute(
                "INSERT INTO catalog_companies (ticker, company_name, org_id, last_synced_at) "
                "VALUES (?,?,?,?)", (ticker, name, org, stale))
    conn.close()
    return db


@pytest.fixture
def synced(monkeypatch):
    """Record every sync_company call instead of touching openinfo."""
    calls: list[dict] = []

    def _sync(ticker, company_name, *, force=False, org_id=None):
        calls.append({"ticker": ticker, "name": company_name, "force": force, "org_id": org_id})
        return {"ticker": ticker, "added": 1}

    monkeypatch.setattr(rc, "sync_company", _sync)
    return calls


def feed(monkeypatch, items):
    import reports_watch as rw
    monkeypatch.setattr(rw, "recent_filings", lambda hours=12, **kw: list(items))


class TestOnlyWhoFiled:
    def test_an_issuer_that_filed_is_re_synced(self, catalog, synced, monkeypatch) -> None:
        feed(monkeypatch, [filing(8)])

        result = rc.sync_recent_filings(hours=12)

        assert [c["ticker"] for c in synced] == ["HMKB"]
        assert synced[0]["org_id"] == "8"
        assert (result["synced"], result["errors"]) == (1, [])

    def test_an_issuer_that_did_not_file_is_left_alone(self, catalog, synced, monkeypatch) -> None:
        """A quiet hour costs one request and syncs nothing — which is what
        makes running this every hour affordable at all."""
        feed(monkeypatch, [])

        result = rc.sync_recent_filings(hours=12)

        assert synced == []
        assert result["synced"] == 0

    def test_an_issuer_is_synced_once_not_once_per_ticker(self, catalog, synced, monkeypatch) -> None:
        """AGAT CREDIT holds four bond tickers and files once."""
        feed(monkeypatch, [filing(1058), filing(1058, form="MSFO")])

        rc.sync_recent_filings(hours=12)

        assert [c["ticker"] for c in synced] == ["ACMT1B2"]

    def test_the_common_share_carries_its_issuers_filings(self, catalog, synced, monkeypatch) -> None:
        """HMKB, not HMKBP: the same ticker the catalog entry is listed under,
        so the filing lands where the page reads it."""
        feed(monkeypatch, [filing(8)])

        rc.sync_recent_filings(hours=12)

        assert synced[0]["ticker"] == "HMKB"

    def test_an_issuer_we_have_never_catalogued_is_left_to_the_sweep(self, catalog, synced, monkeypatch) -> None:
        """openinfo's feed is the whole market — 438 organisations in 30 days,
        of which we track 50. An org with no catalog row has no ticker to sync."""
        feed(monkeypatch, [filing(99999), filing(8)])

        result = rc.sync_recent_filings(hours=12)

        assert [c["ticker"] for c in synced] == ["HMKB"]
        assert result["orgs"] == 2

    def test_one_failing_issuer_does_not_stop_the_others(self, catalog, monkeypatch) -> None:
        def _sync(ticker, name, *, force=False, org_id=None):
            if ticker == "HMKB":
                raise RuntimeError("openinfo timed out")
            return {"ticker": ticker, "added": 1}

        monkeypatch.setattr(rc, "sync_company", _sync)
        feed(monkeypatch, [filing(8), filing(1058)])

        result = rc.sync_recent_filings(hours=12)

        assert result["synced"] == 1
        assert result["errors"][0]["ticker"] == "HMKB"


class TestWhoeverHasWaitedLongest:
    """The feed only knows who FILED. An issuer that fell behind for any other
    reason — a failed request, a sweep a redeploy cut in half — needs a second
    way back, or it waits for the next full sweep and possibly past it."""

    def test_the_stalest_issuers_are_refreshed(self, catalog, synced) -> None:
        result = rc.sync_stale_companies(limit=2, older_than_hours=24)

        assert len(synced) == 2
        assert result["synced"] == 2

    def test_one_issuer_not_one_ticker(self, catalog, synced) -> None:
        """Three issuers behind five tickers — HMKB/HMKBP and ACMT1B2/ACMT2B5
        are one company each, and syncing both halves would be the same fetch."""
        rc.sync_stale_companies(limit=10, older_than_hours=24)

        assert sorted(c["ticker"] for c in synced) == ["ACMT1B2", "HMKB", "KVTS"]

    def test_the_batch_is_bounded(self, catalog, synced) -> None:
        """A pass that runs for minutes is a pass a deploy can interrupt."""
        result = rc.sync_stale_companies(limit=1, older_than_hours=24)

        assert len(synced) == 1
        assert result["remaining"] == 2

    def test_an_issuer_synced_recently_is_left_alone(self, catalog, synced) -> None:
        rc.sync_stale_companies(limit=10, older_than_hours=24 * 30)

        assert synced == []


class TestTheSweepClockIsRecorded:
    def test_a_catalog_that_has_never_swept_sweeps(self, catalog, monkeypatch) -> None:
        calls = []
        monkeypatch.setattr(api, "catalog_sync_all", lambda **kw: calls.append("full") or {"total": 1})

        assert api._catalog_watch_once()["mode"] == "full"
        assert calls == ["full"]

    def test_a_completed_sweep_is_written_down(self, catalog, monkeypatch) -> None:
        monkeypatch.setattr(api, "catalog_sync_all", lambda **kw: {"total": 1})

        api._catalog_watch_once()

        assert rc.full_sweep_age_hours() < 0.1

    def test_a_sweep_that_finished_is_not_repeated(self, catalog, monkeypatch) -> None:
        monkeypatch.setattr(api, "catalog_sync_all", lambda **kw: {"total": 1})
        monkeypatch.setattr(rc, "sync_recent_filings", lambda **kw: {"synced": 0})
        monkeypatch.setattr(rc, "sync_stale_companies", lambda **kw: {"synced": 0})
        api._catalog_watch_once()

        assert api._catalog_watch_once()["mode"] == "filings"

    def test_an_interrupted_sweep_does_not_count_as_done(self, catalog, monkeypatch) -> None:
        """The company timestamps say a sweep happened — some of them were just
        stamped. Only reaching the end records it, so the issuers a redeploy cut
        the sweep short of are picked up again rather than waiting another day."""
        def _die(**kw):
            raise RuntimeError("container went away")

        monkeypatch.setattr(api, "catalog_sync_all", _die)
        with pytest.raises(RuntimeError):
            api._catalog_watch_once()

        assert rc.full_sweep_age_hours() is None

    def test_the_window_is_wider_than_the_interval(self) -> None:
        """A missed tick — a deploy, a restart, one failed request — has to heal
        on the next pass rather than leave a hole nothing ever fills."""
        assert api.CATALOG_WATCH_WINDOW_HOURS * 60 > api.CATALOG_WATCH_INTERVAL_MIN
