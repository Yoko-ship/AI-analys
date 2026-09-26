from __future__ import annotations

from typing import Any
import asyncio
import company_imports
import os
import reports_catalog as catalog_store
import server.http as http
import threading


# The report catalog keeps itself current. Nothing did before: `sync_all` runs in
# the daily collector, but the collectors have no database of their own — they
# POST results to this service over HTTP, and the catalog is not among what they
# post. So `catalog_reports` only ever moved when an admin pressed
# «Синхронизировать всё». It was last pressed on 2026-07-21, and fifty issuers
# filed their half-year report after that: the site simply did not have them.
# This runs where the database is, which is also the only place that redeploys on
# a push (the cron services have no deployment trigger).
CATALOG_WATCH = os.getenv("CATALOG_WATCH", "1").strip().lower() not in {"0", "false", "no"}


CATALOG_WATCH_INTERVAL_MIN = int(os.getenv("CATALOG_WATCH_INTERVAL_MIN", "60"))


# Wider than the interval on purpose: a missed tick (restart, deploy, a failed
# request) heals on the next one instead of leaving a hole in the record.
CATALOG_WATCH_WINDOW_HOURS = int(os.getenv("CATALOG_WATCH_WINDOW_HOURS", "12"))


# The feed-driven pass cannot see an issuer we have never catalogued, and the
# audit-opinion endpoint has no per-issuer filter. The full sweep covers both.
CATALOG_FULL_SYNC_HOURS = int(os.getenv("CATALOG_FULL_SYNC_HOURS", "24"))


# How many of the longest-unsynced issuers each hourly pass also refreshes. Sixty-six
# issuers at eight an hour is a working day, and a pass this size is short enough
# that a redeploy landing on it costs almost nothing.
CATALOG_WATCH_BATCH = int(os.getenv("CATALOG_WATCH_BATCH", "8"))


def _catalog_watch_once() -> dict[str, Any]:
    """One pass: whoever just filed, then whoever has waited longest.

    The full sweep runs when it is due, and its completion is RECORDED — a sweep
    a redeploy cut short does not count, or the issuers it never reached would
    wait another day. Everything here is bounded so that being cut short costs
    one pass, not a day.

    Blocking (openinfo HTTP + DB writes) — always called in an executor.
    """
    from datetime import datetime, timezone

    from reports_catalog import (FULL_SWEEP_KEY, full_sweep_age_hours, set_state,
                                 sync_recent_filings, sync_stale_companies)

    age = full_sweep_age_hours()
    if age is None or age >= CATALOG_FULL_SYNC_HOURS:
        result = catalog_store.sync_all()
        set_state(FULL_SWEEP_KEY, datetime.now(timezone.utc).isoformat())
        http.logger.info("catalog watch: full sweep (last %s h ago) %s",
                    None if age is None else round(age, 1),
                    {k: result.get(k) for k in ("total", "synced", "skipped")})
        return {"mode": "full", **result}

    filings = sync_recent_filings(hours=CATALOG_WATCH_WINDOW_HOURS)
    # The feed only knows who filed. An issuer that fell behind for any other
    # reason — a failed request, a pass a deploy interrupted — is caught by
    # taking the stalest few every hour, which converges without a cursor.
    stale = sync_stale_companies(limit=CATALOG_WATCH_BATCH,
                                 older_than_hours=CATALOG_FULL_SYNC_HOURS)
    if filings.get("synced") or filings.get("errors") or stale.get("synced"):
        http.logger.info("catalog watch: filed=%s stale=%s remaining=%s",
                    filings.get("targets"), stale.get("targets"), stale.get("remaining"))
    return {"mode": "filings", "filings": filings, "stale": stale}


async def _catalog_watch_loop() -> None:
    """Keep the report catalog level with openinfo, hourly, for as long as we run."""
    loop = asyncio.get_running_loop()
    # Let boot finish first: migrations, the delisted purge and the securities
    # seed are all in flight, and none of them should queue behind a sync.
    await asyncio.sleep(90)
    while True:
        if not _admin_catalog_sync_running.is_set():
            _admin_catalog_sync_running.set()
            try:
                await loop.run_in_executor(None, _catalog_watch_once)
            except Exception:
                http.logger.exception("catalog watch pass failed")
            finally:
                _admin_catalog_sync_running.clear()
        await asyncio.sleep(max(60, CATALOG_WATCH_INTERVAL_MIN * 60))


_admin_company_syncs: set[str] = set()


_admin_company_syncs_lock = threading.Lock()


def _sync_approved_company(ticker: str) -> None:
    """Run one approved import through the existing report collector."""
    ticker = ticker.upper()
    try:
        company_imports.set_sync_status(ticker, "running")
        metadata = company_imports.approved_metadata_map().get(ticker) or {}
        if not metadata:
            raise RuntimeError("company is not approved")
        result = catalog_store.sync_company(
            ticker,
            str(metadata.get("company_name") or ticker),
            force=True,
            org_id=str(metadata.get("org_id") or "") or None,
        )
        errors = result.get("errors") if isinstance(result, dict) else None
        if errors:
            company_imports.set_sync_status(ticker, "failed", "; ".join(map(str, errors)))
        else:
            company_imports.set_sync_status(ticker, "complete")
    except Exception as exc:  # noqa: BLE001 - status is the admin-facing result
        http.logger.exception("admin company sync failed for %s", ticker)
        company_imports.set_sync_status(ticker, "failed", str(exc))
    finally:
        with _admin_company_syncs_lock:
            _admin_company_syncs.discard(ticker)


def _schedule_company_sync(ticker: str) -> bool:
    ticker = ticker.upper()
    with _admin_company_syncs_lock:
        if ticker in _admin_company_syncs:
            return False
        _admin_company_syncs.add(ticker)
    company_imports.set_sync_status(ticker, "queued")
    asyncio.get_running_loop().run_in_executor(None, _sync_approved_company, ticker)
    return True


_admin_catalog_sync_running = threading.Event()
