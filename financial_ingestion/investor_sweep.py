"""Nightly collection and coverage for published per-share metrics and EBIT."""
from collections import Counter
from contextlib import closing
import time

from catalogue.sources import cached_report_excel_data
from catalogue.storage import get_catalog_conn
from financial_analysis.report_investor_metrics import HISTORICAL_METRICS
from financial_columns import backfill, source_store
from issuer_financials import IssuerNotFoundError, resolve_issuer, report_rows
from sector_report_service import public_report, sector_report
from securities_catalog import get_securities_map
from . import investor_eps, publication, store


def unlinked_equities():
    with closing(get_catalog_conn()) as conn:
        catalog = {r['ticker'] for r in conn.execute('SELECT ticker FROM catalog_companies')}
    return [{'ticker':ticker, 'org_id':None} for ticker, security in get_securities_map().items()
            if security.get('share_type') == 'ordinary' and ticker not in catalog]


def latest_reports(ticker, org):
    try:
        issuer = resolve_issuer(ticker)
    except IssuerNotFoundError:
        return []
    if str(issuer['id']) != str(org) or issuer['ticker'] != ticker:
        raise ValueError('Catalog issuer and security do not match')
    bases = [('nsbu', 'separate')]
    if source_store.prior_dates(org, standard='NSBU', scope='consolidated', end='9999-12-31'):
        bases.append(('nsbu','consolidated'))
    scopes = publication.scopes(ticker)
    if not scopes and report_rows(issuer, 'ifrs'):
        scopes = ['separate']
    bases.extend(('ifrs', scope) for scope in scopes)
    reports = []
    for standard, scope in bases:
        report = public_report(sector_report(issuer, standard, None, scope, 'en', persist=False,
                                             source_reader=cached_report_excel_data))
        if (report['standard'], report['scope']) not in {(r['standard'], r['scope']) for r in reports}:
            reports.append(report)
    return reports


def _metric(code, report):
    row = next((r for r in report.get('ratios', []) if r['metric_code']==code), {})
    verified = row if row.get('verification_status')=='verified' and row.get('value') is not None else None
    previous = row.get('last_verified') or {}
    if verified or (previous.get('verification_status')=='verified' and previous.get('value') is not None):
        value = verified or previous
        return {'state':'verified' if verified else 'historical', 'value':value['value'], 'unit':value.get('unit'),
                'period_end':value.get('period_end'), 'market_as_of':value.get('market_as_of'),
                'source_url':value.get('share_disclosure_url') or next(
                    (c['source_url'] for c in value.get('components', []) if c.get('source_url')), None)}
    state = 'missing'
    if row.get('calculation_status') == 'not_applicable' or (not row and report['status'] in {'available','stale'}):
        state = 'not_applicable'
    result = {'state':state, 'reason':row.get('reason_code') or report['status'],
              'missing_inputs':row.get('missing_inputs') or []}
    if row.get('other_filing'):
        result['other_filing'] = row['other_filing']
    return result


def coverage(companies):
    totals = {key:Counter() for key in sorted(HISTORICAL_METRICS)}
    issuers = []
    for company in companies:
        ticker, org = company['ticker'], company['org_id']
        item = {'ticker':ticker, 'org_id':org, 'reports':[]}
        issuers.append(item)
        if not org:
            item['status'] = 'unresolved_issuer'
            continue
        try:
            for report in latest_reports(ticker, org):
                metrics = {code:_metric(code, report) for code in totals}
                item['reports'].append({k:report.get(k) for k in ('standard','scope','period','status','financial_as_of')}
                                       | {'metrics':metrics})
                for code, result in metrics.items():
                    totals[code][result['state']] += 1
            item['status'] = 'checked' if item['reports'] else 'no_security'
        except Exception as exc:
            item.update(status='error', error=str(exc))
    return {'generated_at':store.now(), 'issuer_count':len(issuers), 'by_metric_and_reporting_basis':totals, 'issuers':issuers}


def collect(companies, *, ocr, deadline=None):
    ids = {str(c['org_id']) for c in companies if c['org_id']}
    result = {'errors':[], 'pdfs_checked':0, 'pdfs_with_eps':0}
    for name, operation in [('share_supplements',backfill.collect_share_bases), ('valuation_history',backfill.collect_valuation_history)]:
        if deadline is not None and time.monotonic() >= deadline:
            return {**result, 'deferred':True}
        try:
            result[name] = operation(issuer_ids=ids)
            result['errors'].extend(result[name]['errors'])
        except Exception as exc:
            result['errors'].append({'stage':name,'error':str(exc)})
    # Include new official annuals as soon as the document worker archives them.
    with closing(store.connect()) as conn:
        heads = conn.execute('SELECT DISTINCT h.org_id,v.sha FROM ingest_heads h '
            'JOIN ingest_snapshots s ON s.id=h.snapshot_id JOIN ingest_candidates c ON c.id=s.candidate_id '
            'JOIN ingest_versions v ON v.id=c.version_id WHERE h.standard=\'MSFO\'').fetchall()
        annuals = conn.execute('SELECT s.org_id,v.sha FROM ingest_sources s JOIN ingest_versions v ON v.id=s.latest_version '
                               'WHERE s.category=? ORDER BY s.last_seen DESC,s.id', ('MSFO',)).fetchall()
    hashes = dict.fromkeys(h['sha'] for h in [*heads,*annuals] if h['org_id'] in ids)
    # Leave the shared nightly worker time for statutory history and document discovery.
    # Completed originals are checkpointed, so subsequent nights advance through the backlog.
    scan_until = time.monotonic() + 1800
    for index, sha in enumerate(hashes):
        if deadline is not None and time.monotonic() >= deadline:
            return {**result, 'deferred':True}
        if time.monotonic() >= scan_until:
            result['pdfs_pending'] = len(hashes) - index
            break
        try:
            rows = investor_eps.archived_rows(sha, ocr=ocr)
            result['pdfs_checked'] += 1
            result['pdfs_with_eps'] += bool(rows)
        except Exception as exc:
            result['errors'].append({'file_hash':sha, 'error':str(exc)})
    return result
