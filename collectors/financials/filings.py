"""Financials filings operations with explicit dependencies."""
from __future__ import annotations
import reports_catalog as rc

import collectors.financials.delivery as collectors_financials_delivery
import collectors.financials.settings as collectors_financials_settings
import os

import catalogue.facts as catalogue_facts
import catalogue.snapshots as catalogue_snapshots
import requests


def register_catalog() -> int:
    """Link the figures just pushed to the filings they came from (§Б.2/§Б.3).

    The parse that produces a figure runs HERE and moves the report through its
    states in the collector's own registry; the push carries values only. So
    prod's registry never advanced past `discovered` — 1703 reports, 0 published,
    every published number without a source link. This asks prod to re-derive the
    links from what it now holds, which is deterministic per (ticker, form,
    period) and needs no download. Idempotent: a report keeps the state it
    reached.
    """
    collectors_financials_settings.log.info("registering pushed figures against their filings ...")
    return collectors_financials_delivery._post("/api/admin/catalog/register", {})


def refresh_dividends() -> int:
    """Ask prod to re-read openinfo's dividend calendar into its snapshot.

    The read path refreshes itself once the snapshot goes stale, but only when
    somebody opens a Дивиденды tab. Doing it from the daily run means the first
    visitor of the day reads a table that is already current, and a payout
    announced overnight is on the page before anyone asks for it. The work runs
    on prod, where the snapshot lives — the collector has no volume to write to.
    """
    collectors_financials_settings.log.info("refreshing the dividend calendar snapshot ...")
    return collectors_financials_delivery._post("/api/admin/dividends/refresh?force=1", {})


def refresh_meetings() -> int:
    """Ask prod to re-read openinfo's meeting-announcement calendar.

    Same reasoning as refresh_dividends: the news «Календарь» warms itself on
    read, but the daily run means the first visitor already sees a meeting
    announced overnight."""
    collectors_financials_settings.log.info("refreshing the meetings calendar snapshot ...")
    return collectors_financials_delivery._post("/api/admin/meetings/refresh?force=1", {})


def push_financials_aliases() -> int:
    """Copy each issuer's financials onto its sibling tickers, then push to prod.

    A company's financials are issuer-level, but the board keys them by ticker —
    so preferred lines, issuer bonds, and ordinary/preferred variants (AGMK vs
    AGMKP, KSCMP vs KSCM) showed blank. This fills them from the sibling that has
    them.
    """
    import listings_collector as lc

    collectors_financials_settings.log.info("collecting issuer financials aliases (openinfo info_rfb) ...")
    rows = lc.collect_financials_aliases()
    collectors_financials_settings.log.info("financials aliases: %d sibling tickers", len(rows))
    if not rows:
        return 0
    return collectors_financials_delivery._post("/api/admin/financials", {"form": "NSBU", "rows": rows})


def collect_and_push_facts() -> int:
    """Run every registered source adapter locally, then push the fact store to prod.

    This is the extensible half of the pipeline: any adapter registered in
    data_sources (financial_indicators today, shareholder structure / news /
    ratings tomorrow) is picked up automatically and its facts propagate.
    """
    import data_sources as ds
    import listings_collector as lc

    collectors_financials_settings.log.info("running source adapters (fact store) ...")
    res = ds.run_all()
    collectors_financials_settings.log.info("adapters: %s", res.get("collectors"))
    # Land the ticker→org map next to the facts: prod joins the fact store by
    # org id, and only this map (not prod's own drifting catalog) is guaranteed
    # to use the same IDs the facts were collected under — siblings included.
    try:
        org_map = lc.collect_org_map_rows()
        catalogue_facts.upsert_facts(org_map)
        collectors_financials_settings.log.info("org map: %d ticker rows", len(org_map))
    except Exception:
        collectors_financials_settings.log.exception("org-map step failed (facts push continues without it)")
    facts = catalogue_facts.get_facts()
    rows = [{
        "entity_id": f["entity_id"], "dataset": f["dataset"], "field": f["field"],
        "period": f["period"],
        "value": f["value_num"] if f["value_num"] is not None else f["value_text"],
        "unit": f["unit"], "source": f["source"], "source_url": f["source_url"],
    } for f in facts]
    if not rows:
        collectors_financials_settings.log.warning("no facts collected")
        return 1
    collectors_financials_settings.log.info("pushing %d facts", len(rows))
    return collectors_financials_delivery._post("/api/admin/facts", {"rows": rows})


def reconcile_and_push() -> int:
    """Reconcile every tracked ticker against openinfo's structured report JSON
    and push the corrected headline figures as the authoritative latest period.

    This runs LAST and uses the ``replace`` mode so it supersedes whatever the
    legacy Excel/PDF parse and the sibling-alias step wrote: the structured path
    (openinfo_reconcile) reads P&L, balance, period and issuer correctly, so its
    figures are the ones the site should serve. Tickers openinfo cannot source
    (bonds with no issuer, IFRS-only holdings) are left to the legacy rows.
    """
    import openinfo_reconcile as orc

    # Cover the full board registry. Source from /api/market/stocks (the stable
    # list of every listed security, stock + bond) so a ticker can't drop out just
    # because its served financials row is currently filtered; union with the
    # served financials keys and the local store as belt-and-braces.
    base = os.getenv("FINANCIALS_PUSH_URL", collectors_financials_settings.DEFAULT_URL).rstrip("/")
    tickers = set(catalogue_snapshots.get_all_financials().keys())
    try:
        data = requests.get(f"{base}/api/market/financials", timeout=60).json()
        tickers |= set((data.get("financials") or {}).keys())
    except Exception:
        collectors_financials_settings.log.exception("could not fetch served financials ticker list")
    try:
        for kind in ("stock", "bond"):
            board = requests.get(f"{base}/api/market/stocks?type={kind}", timeout=60).json()
            rows = board if isinstance(board, list) else (board.get("stocks") or [])
            tickers |= {str(r.get("ticker")).strip().upper() for r in rows if r.get("ticker")}
    except Exception:
        collectors_financials_settings.log.exception("could not fetch market board ticker list")
    tickers = sorted(t for t in tickers if t)
    collectors_financials_settings.log.info("reconcile: %d tickers via structured openinfo JSON ...", len(tickers))
    rows, errors = orc.reconcile_all(
        tickers, progress=lambda i, n, t: collectors_financials_settings.log.info("reconcile %d/%d %s", i + 1, n, t) if (i % 25 == 0) else None)
    # Two rows per ticker where the latest period is a cumulative quarter: the
    # quarter itself, and the last complete fiscal year beside it. Replace mode
    # clears the ticker before inserting, so the companion has to travel in the
    # same push or the 12-month figure every ratio needs is simply gone.
    push_rows = [r for row in rows for r in orc.admin_push_rows(row)]
    collectors_financials_settings.log.info("reconcile: resolved %d tickers (%d period rows), unresolved %d (%s)",
             len(rows), len(push_rows), len(errors), ", ".join(sorted(errors)[:8]))
    if not push_rows:
        collectors_financials_settings.log.warning("reconcile produced no rows — skipping push")
        return 1
    return collectors_financials_delivery._post("/api/admin/financials", {"form": "NSBU", "rows": push_rows, "mode": "replace"})


def watch_filings_and_push(hours: int | None = None) -> int:
    """Refresh only the issuers that filed since the last sweep.

    The daily run re-derives all ~100 tickers whether anything was filed or not,
    which is why it runs once: it is minutes of openinfo traffic. This is the same
    reconciliation restricted to the issuers openinfo's filing feed says have
    published something — usually none, a dozen on a deadline day — so it is cheap
    enough to run hourly and the board stops waiting a day for a report that is
    already public. Pushes with ``mode=replace``, which clears only the tickers in
    the payload, so an interleaved run cannot disturb anything it did not touch.
    """
    import reports_watch as rw

    base = os.getenv("FINANCIALS_PUSH_URL", collectors_financials_settings.DEFAULT_URL).rstrip("/")
    served = requests.get(f"{base}/api/market/financials", timeout=60).json()
    served = served.get("financials") or served
    universe = rw.board_tickers(base) | set(served)
    result = rw.scan(
        served=served, known_tickers=universe,
        hours=hours if hours is not None else int(os.getenv("REPORTS_WATCH_HOURS", "48")),
    )
    collectors_financials_settings.log.info("watch: %d filings, %d candidate(s), %d to refresh, %d unchanged, %d error(s)",
             result["filings"], len(result["candidates"]), len(result["refreshed"]),
             len(result["unchanged"]), len(result["errors"]))
    for ticker, reason in sorted(result["refreshed"].items()):
        collectors_financials_settings.log.info("watch: %s %s", ticker, reason)
    if result["errors"]:
        collectors_financials_settings.log.warning("watch: unresolved %s", result["errors"])
    if not result["rows"]:
        # Nothing filed, or nothing that changes a figure — a normal quiet run. The
        # heartbeat below still stamps it, so "no new reports" and "watcher dead"
        # stay distinguishable.
        collectors_financials_delivery._stamp_step("watch_filings", "no change")
        return 0
    status = collectors_financials_delivery._post("/api/admin/financials",
                   {"form": "NSBU", "rows": result["rows"], "mode": "replace"})
    if status == 0:
        collectors_financials_delivery._stamp_step("watch_filings", ", ".join(sorted(result["refreshed"])[:12]))
    return status
