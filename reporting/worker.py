"""Bounded report execution; persistence and leases belong to the store."""
import issuer_financials as financials
import sector_report_service
from . import store


def run_pending(limit=10):
    rows = store.due_jobs(limit)
    for row in rows:
        if not store.claim_job(row["id"]):
            continue
        error = None
        attempts = row["attempts"] + 1
        try:
            issuer = financials.resolve_issuer(row["ticker"])
            reports = [sector_report_service.sector_report(issuer, "nsbu", None, "separate", lang) for lang in ("ru", "uz")]
            retryable = any(r["status"] == "mapping_failed" for r in reports)
            state = ("retry" if retryable and attempts < 4 else "incident" if retryable
                     else "completed" if all(r["status"] == "available" for r in reports) else "blocked")
            if state != "completed":
                error = next((q["code"] for r in reports for q in r["data_quality"] if q.get("severity") == "blocking"), reports[0]["status"])
        except Exception:
            state = "retry" if attempts < 4 else "incident"
            error = "SOURCE_TEMPORARILY_UNAVAILABLE"
        store.finish_job(row["id"], state, attempts, error)
    return len(rows)
