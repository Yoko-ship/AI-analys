"""Publish a report, then refresh the recoverable administrative projection."""
import logging

from admin_control.adapters import record_analysis
from . import store


def publish_report(report):
    published = store.record_report(report)
    # A rollback hold returns its saved publication. Preserve that exact result;
    # the administrative refresh can replay the persisted history separately.
    if published.get("publication_restored"):
        return published
    from server.terminal.quality import report_events
    report_events(published, published=published.get("status") == "available" and store.publication_version(published) == published.get("version"))
    try:
        record_analysis(published, current_version=store.publication_version(published))
    except Exception:
        logging.getLogger(__name__).exception("Administrative analysis projection failed")
    return published
