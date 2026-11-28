"""Prepare public reports from saved sources; workers own source downloads."""
import json
from datetime import date

import catalogue.sources as sources
import sector_report_service as service
from . import read_cache, store


def read_report(issuer, standard, period, scope, lang):
    return read_cache.get_or_build(issuer, standard, period, scope, lang,
        lambda: _prepare(issuer, standard, period, scope, lang))


def _prepare(issuer, standard, period, scope, lang):
    missing = False

    def read_source(*args):
        nonlocal missing
        workbook = sources.cached_report_excel_data(*args)
        missing = missing or not workbook.get('ok')
        return workbook

    report = service.sector_report(issuer, standard, period, scope, lang, source_reader=read_source)
    incomplete = report.get('content_status') == 'shortened' or any(
        item.get('code') == 'KEY_LINE_MISSING' for item in report.get('data_quality', []))
    if standard == 'nsbu' and (missing or incomplete or report.get('source_refresh_failed')):
        context = dict(standard=standard, period=period, scope=scope, lang=lang,
                       date=date.today().isoformat(), source=report.get('source_snapshot_hash'))
        store.enqueue(issuer['ticker'], 'report-read:' + json.dumps(context, sort_keys=True),
                      reason='report_source_detail_missing')
    complete = report.get('status') == 'available' and not report.get('source_refresh_failed')
    return service.public_report(report), complete
