"""Join verified bank ratios for the exact annual, without source downloads."""
import logging
import math
from datetime import date

from .analytics import number

logger = logging.getLogger(__name__)
METRICS = ('nim', 'cost_of_risk')


def enrich(ticker, row, form, scope):
    if row.get('kind') != 'bank' or form != 'NSBU' or scope != 'separate' or not row.get('period'):
        return row
    # Empty or quarantined annuals must not be repopulated through another reader.
    if row.get('assets') is None or row.get('net_profit') is None:
        return row
    reasons = row.setdefault('metric_reasons', {})
    def unavailable(code):
        for metric in METRICS:
            row[metric] = None
            reasons[metric] = {'code': code}
        return row
    if any(issue.get('code') in {'VALUE_QUARANTINE', 'SOURCE_UNAVAILABLE', 'UNDER_REVIEW'} for issue in row.get('issues', [])):
        return unavailable('UNDER_REVIEW')
    try:
        from catalogue.sources import cached_report_excel_data
        from issuer_financials import resolve_issuer
        from sector_report_service import sector_report
        report = sector_report(resolve_issuer(ticker), 'nsbu', row['period'], scope, 'ru',
                               persist=False, source_reader=cached_report_excel_data)
    except Exception:
        logger.warning('Bank annual detail unavailable for %s %s', ticker, row['period'], exc_info=True)
        return unavailable('SOURCE_UNAVAILABLE')
    pending = bool(report.get('source_refresh_failed'))
    if pending:
        from reporting import store
        store.enqueue(ticker, f"terminal-bank-annual:{row['period']}:{date.today().isoformat()}",
                      reason='annual_bank_detail_missing')
    if (report.get('period') != row['period'] or report.get('standard', '').lower() != 'nsbu'
            or report.get('scope') != scope or report.get('status') not in {'available', 'stale'}):
        return unavailable('SOURCE_PENDING' if pending and report.get('status') == 'mapping_failed' else 'UNDER_REVIEW')
    # Both readers must be looking at the same accepted statement amounts.
    facts = {fact['metric_code']: fact for fact in report.get('verified_facts', [])}
    for field, key in (('net_income', 'net_profit'), ('total_assets', 'assets'), ('total_equity', 'equity')):
        fact = facts.get(field, {})
        value = number(fact.get('value'))
        if value is None or fact.get('verification_status') != 'verified' or fact.get('period') != row['period']:
            return unavailable('UNDER_REVIEW')
        if fact.get('unit') == 'thousand UZS':
            value *= 1000
        elif fact.get('unit') != 'UZS':
            return unavailable('UNDER_REVIEW')
        if row.get(key) is None or not math.isclose(value, row[key], rel_tol=1e-6, abs_tol=1000):
            return unavailable('UNDER_REVIEW')
    details = {item['metric_code']: item for item in report.get('ratios', [])}
    for metric in METRICS:
        item = details.get(metric, {})
        value = number(item.get('value'))
        if item.get('verification_status') == 'verified' and item.get('calculation_status') == 'verified' and value is not None:
            row[metric] = value
            reasons.pop(metric, None)
        else:
            row[metric] = None
            reasons[metric] = {'code': 'WITHHELD_GROSS_UP' if item.get('calculation_status') == 'withheld_gross_up' else
                               'SOURCE_PENDING' if pending else 'MISSING_BANK_FIELDS'}
    return row
