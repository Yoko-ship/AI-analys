"""Join verified bank ratios for the exact annual, without source downloads."""
from contextlib import closing
from functools import lru_cache
import json
import logging
from pathlib import Path
import math
from datetime import date

from .analytics import number

logger = logging.getLogger(__name__)
METRICS = ('nim', 'cost_of_risk')


def enrich_interim(company, row, published, held, end):
    """Use the same scoped, YTD source lines as the financial-columns screen."""
    from financial_columns import observations, ratios, source_store

    ticker = company['ticker']
    opening_year = str(int(end[:4]) - 1)
    if opening_year in held:
        return
    try:
        if row['standard'] == 'NSBU':
            issuer_id = company.get('org_id') or f'ticker:{ticker}'
            source = observations.nsbu(source_store.read(issuer_id, standard='NSBU', scope=row['scope']))
        else:
            source = observations.ifrs(published)
        dates = {end, f'{opening_year}-12-31'}
        source = [item for item in source if item['period_end'] in dates]
        if not source:
            return
        observations.check(source)
        for metric in ratios.calculate(source, ticker=ticker, template='bank', end=end, basis='ytd'):
            if metric['metric_id'] in METRICS and metric['quality'] in {'valid', 'warn'}:
                row[metric['metric_id']] = number(metric['value'])
    except Exception:
        logger.warning('Bank interim detail unavailable for %s %s', ticker, end, exc_info=True)


def _statutory(ticker, row, form, scope):
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


@lru_cache(maxsize=1)
def _reviewed_filings():
    path = Path(__file__).resolve().parents[2] / 'config' / 'reviewed_bank_ratio_filings.json'
    return {(r['ticker'], r['period']): r for r in json.loads(path.read_text(encoding='utf-8'))}


def enrich(ticker, row, form, scope):
    from catalogue.storage import get_catalog_conn
    from financial_analysis.profitability import return_on
    from financial_ingestion.disclosures import reviewed_attachment
    from issuer_financials import resolve_issuer

    row = _statutory(ticker, row, form, scope)
    if row.get('kind') != 'bank' or form != 'NSBU' or scope != 'separate':
        return row
    record = _reviewed_filings().get((ticker, row.get('period')))
    if not record or all(row.get(metric) is not None for metric in METRICS):
        return row
    try:
        issuer = resolve_issuer(ticker)
        if (str(issuer['id']) != record['org_id'] or issuer['ticker'] != ticker
                or record['publication_date'] > date.today().isoformat()):
            return row
        path = f"/reports/bank/annual/{record['parent']}/"
        with closing(get_catalog_conn()) as conn:
            if not reviewed_attachment(conn, org_id=record['org_id'], api_path=path, category=record['category'],
                                      url=record['pdf_url'], pdf_sha=record['pdf_sha256'], parent_sha=record['approved_parent_sha256']):
                return row
    except Exception:
        logger.warning('Audited bank attachment unavailable for %s %s', ticker, row['period'], exc_info=True)
        return row
    for metric, flow, base in [('nim', 'net_interest_income', 'assets'), ('cost_of_risk', 'loan_loss_charge', 'net_loans')]:
        if row.get(metric) is not None or flow not in record:
            continue
        opening, closing_balance = record['opening_' + base], record['closing_' + base]
        result = return_on(record[flow], closing_balance, opening)
        if result['value'] is not None and result['denominator_basis'] == 'average':
            row.setdefault('other_filing_metrics', {})[metric] = {
                'standard': 'ifrs', 'scope': record['scope'], 'period': record['period'], 'audited': True,
                'publication_date': record['publication_date'], 'value': result['value'], 'unit': 'percent',
                'source_url': record['pdf_url'], 'page': record['income_page'], 'balance_page': record['balance_page'],
                'components': {flow: record[flow], 'opening_' + base: opening, 'closing_' + base: closing_balance,
                               'unit': record['component_unit']},
            }
    return row
