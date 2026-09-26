"""Financials refresh operations with explicit dependencies."""
from __future__ import annotations
import reports_catalog as rc

import collectors.financials.delivery as collectors_financials_delivery
import collectors.financials.settings as collectors_financials_settings

import catalogue.refresh as catalogue_refresh
import catalogue.snapshots as catalogue_snapshots
import catalogue.sync as catalogue_sync


def refresh_local() -> None:
    """Sync the catalog (catch new filings) then recompute all latest annuals."""
    collectors_financials_settings.log.info("sync_all: refreshing report catalog ...")
    try:
        res = catalogue_sync.sync_all()
        collectors_financials_settings.log.info("sync_all done: %s", {k: res.get(k) for k in ("synced", "skipped") if k in res} or "ok")
    except Exception:
        collectors_financials_settings.log.exception("sync_all failed (continuing with cached catalog)")
    collectors_financials_settings.log.info("recomputing financials for all annual reports ...")
    res = catalogue_refresh.refresh_financials_cache(ttl_days=0, sync_missing=False, limit=1000)
    collectors_financials_settings.log.info("financials refresh: %s", res)
    collectors_financials_settings.log.info("filling remaining gaps from report PDFs (broken-Excel issuers) ...")
    try:
        pdf = catalogue_refresh.refresh_financials_from_pdf()
        collectors_financials_settings.log.info("pdf fallback: %s", {k: pdf.get(k) for k in ("candidates", "updated")})
    except Exception:
        collectors_financials_settings.log.exception("pdf fallback failed")


def collect_rows() -> list[dict]:
    fin = catalogue_snapshots.get_all_financials()
    rows = []
    for ticker, r in fin.items():
        # The latest period AND the last complete fiscal year beside it. Prod
        # serves what it is given; pushing only the newest cumulative quarter
        # leaves every 12-month denominator on the deployment out of date.
        for period in (r, r.get("annual")):
            if not period:
                continue
            rows.append({
                "ticker": ticker,
                "year": period.get("year"),
                "quarter": period.get("quarter"),
                # Which period each field actually describes, when it is not the row's
                # own — prod serves what we push verbatim, so the provenance has to
                # travel with the figures or the row lies about its own period.
                "field_periods": period.get("field_periods") or {},
                # The comparative the filing prints for the year before, so a
                # ticker the structured reconciliation cannot resolve does not
                # lose the one it already had.
                "prior": period.get("prior"),
                **{k: period.get(k) for k in collectors_financials_settings.KEYS},
            })
    return rows


def push(rows: list[dict]) -> int:
    collectors_financials_settings.log.info("pushing %d financials rows", len(rows))
    return collectors_financials_delivery._post("/api/admin/financials", {"form": "NSBU", "rows": rows})
