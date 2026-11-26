"""Bounded report execution; persistence and leases belong to the store."""
from catalogue import filings, sources
import issuer_financials as financials
import sector_report_service
import re
from . import store


def _refresh_filing_workbook(ticker, event):
    _, form, year, quarter, _, _ = event.split(':')
    filing = (ticker, form, int(year), int(quarter))
    sources.fetch_report_excel_data(*filing, revalidate_cached=True)
    # On a network failure the downloader may return the old copy.
    checked = sources.cached_report_excel_data(*filing)
    urls = filings.get_report_urls(*filing) or {}
    expected = {urls.get('excel_url'), urls.get('excel_url_form1')} - {None, ''}
    verified = {part['source_url'] for part in (checked['income'], checked['balance']) if part}
    return bool(expected) and expected == verified


def run_pending(limit=10):
    rows = store.due_jobs(limit)
    for row in rows:
        if not store.claim_job(row["id"]):
            continue
        error = None
        attempts = row["attempts"] + 1
        try:
            event = row.get('source_event', '')
            if event.startswith('filing-workbook:'):
                if _refresh_filing_workbook(row['ticker'], event):
                    store.finish_job(row['id'], 'completed', attempts, None)
                else:
                    store.finish_job(row['id'], 'retry' if attempts < 4 else 'incident', attempts, 'SOURCE_REFRESH_FAILED')
                continue
            issuer = financials.resolve_issuer(row["ticker"])
            annual = re.fullmatch(r'terminal-bank-annual:(\d{4}):\d{4}-\d{2}-\d{2}', row.get('source_event', ''))
            # Populate annual source detail without replacing the latest public narrative.
            reports = ([sector_report_service.sector_report(issuer, 'nsbu', annual[1], 'separate', 'ru', persist=False)]
                       if annual else [sector_report_service.sector_report(issuer, "nsbu", None, "separate", lang) for lang in ("ru", "uz")])
            refresh_failed = any(r.get('source_refresh_failed') for r in reports)
            retryable = refresh_failed or any(r["status"] == "mapping_failed" for r in reports)
            state = ("retry" if retryable and attempts < 4 else "incident" if retryable
                     else "completed" if all(r["status"] in ({'available','stale'} if annual else {'available'}) for r in reports) else "blocked")
            if state != "completed":
                error = ('SOURCE_REFRESH_FAILED' if refresh_failed else
                         next((q["code"] for r in reports for q in r["data_quality"] if q.get("severity") == "blocking"), reports[0]["status"]))
        except Exception:
            state = "retry" if attempts < 4 else "incident"
            error = "SOURCE_TEMPORARILY_UNAVAILABLE"
        store.finish_job(row["id"], state, attempts, error)
    return len(rows)
