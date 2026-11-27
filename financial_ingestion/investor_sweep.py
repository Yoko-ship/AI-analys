"""Nightly collection and coverage for published per-share metrics and EBIT."""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date
import json
import logging
import time
from urllib.parse import urlsplit

from catalogue import sources
from catalogue.sources import cached_report_excel_data
from catalogue.storage import get_catalog_conn
from financial_analysis.report_investor_metrics import HISTORICAL_METRICS
from financial_columns import backfill, source_store
from issuer_financials import IssuerNotFoundError, resolve_issuer, report_rows
from sector_report_service import public_report, sector_report
from securities_catalog import get_securities_map
from . import documents, extract, investor_eps, publication, source_policy, store

log = logging.getLogger(__name__)


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
        result['state'] = 'other_filing'
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


def _filing_rounds(ids):
    """Order by the filing's publication date, never by when the crawler last saw it."""
    with closing(store.connect()) as conn:
        rows = conn.execute("""
            SELECT s.org_id,s.id,s.url,s.metadata_json,v.sha,'' AS period_end,a.media_type
            FROM ingest_sources s LEFT JOIN ingest_versions v ON v.id=s.latest_version
            LEFT JOIN ingest_artifacts a ON a.sha=v.sha
            WHERE s.category='MSFO'
            UNION ALL
            SELECT h.org_id,s.id,s.url,v.metadata_json,v.sha,MAX(h.period_end),a.media_type
            FROM ingest_heads h JOIN ingest_snapshots p ON p.id=h.snapshot_id
            JOIN ingest_candidates c ON c.id=p.candidate_id JOIN ingest_versions v ON v.id=c.version_id
            JOIN ingest_sources s ON s.id=v.source_id
            JOIN ingest_artifacts a ON a.sha=v.sha WHERE h.standard='MSFO'
            GROUP BY h.org_id,s.id,s.url,v.metadata_json,v.sha,a.media_type
        """).fetchall()
    issuers = defaultdict(dict)
    for row in rows:
        # XLSX originals already have their own importer. Feeding their ZIP
        # bytes to PDFium is a format-routing error, not a damaged source PDF.
        if ((row['media_type'] and row['media_type'] != 'application/pdf')
                or urlsplit(row['url']).path.lower().endswith(('.xlsx','.doc','.docx','.jpg','.jpeg','.png'))):
            continue
        if row['org_id'] not in ids or (not row['sha'] and not source_policy.allows(row['url'])):
            continue
        meta = json.loads(row['metadata_json'])
        if not row['period_end'] and (meta.get('status') not in (None,'approved')
                                     or meta.get('period_type') not in (None,'annual')):
            continue
        filed = str(meta.get('published_at') or row['period_end'] or '')[:10]
        group = issuers[row['org_id']]
        key = row['sha'] or row['id']
        if key not in group or filed > group[key][0]:
            group[key] = (filed, row['org_id'], row['id'], row['sha'])
    latest, history = [], []
    for group in issuers.values():
        newest = max(doc[0] for doc in group.values())
        for doc in group.values():
            (latest if doc[0] == newest else history).append(doc)
    return sorted(latest, reverse=True), sorted(history, reverse=True)


def _fetch_filing(source):
    job = store.claim(stages=('FETCH',), source_id=source)
    if job:
        try:
            documents.fetch_job(job, extract.processor_version())
        except Exception as exc:
            store.fail(job, exc)
            raise
    with closing(store.connect()) as conn:
        row = conn.execute('SELECT v.sha FROM ingest_sources s JOIN ingest_versions v '
                           'ON v.id=s.latest_version WHERE s.id=?', (source,)).fetchone()
    if not row:
        raise ValueError('Latest original is awaiting download or retry')
    return row['sha']


def _check_filing_receipt(source, sha, rows):
    """Bind a legacy original to a fresh official listing and a matching download."""
    with closing(store.connect()) as conn:
        item = conn.execute(
            'SELECT s.org_id,s.ticker,s.url,s.metadata_json,COALESCE(f.metadata_json,v.metadata_json) AS receipt,'
            'c.company_name FROM ingest_sources s JOIN ingest_versions v ON v.id=s.latest_version '
            'LEFT JOIN ingest_version_filing_checks f ON f.version_id=v.id '
            'LEFT JOIN catalog_companies c ON c.ticker=s.ticker WHERE s.id=? AND v.sha=?',
            (source, sha)).fetchone()
    if not item:
        return sha
    org, url = item['org_id'], item['url']
    today = date.today().isoformat()
    def approved(meta):
        return any(investor_eps.official_filing(meta, url=url, org=org, row=row, end=today, cutoff=today) for row in rows)
    current, receipt = json.loads(item['metadata_json']), json.loads(item['receipt'])
    if approved(current) and approved(receipt):
        return sha
    if not item['company_name']:
        return sha
    with sources._make_session() as session:
        listings, _ = sources._fetch_main_results(session, item['company_name'], org)
    matching = [sources._build_report_document(record) for record in listings
                if record.get('pdf_url') == url and str(record.get('organization')) == org
                and record.get('report_type') == 'MSFO']
    if len(matching) != 1:
        return sha
    official = matching[0]
    processor = extract.processor_version()
    with store.transaction() as conn:
        documents.register(conn, org_id=org, ticker=item['ticker'], url=url, category='MSFO',
                           metadata=official, processor=processor, refresh_days=0)
    return _fetch_filing(source) if approved(official) else sha


def _scan_statements(filings, result, deadline=None):
    originals = []
    for filed, org, source, sha in filings:
        if deadline is not None and time.monotonic() >= deadline:
            result['deferred'] = True
            break
        try:
            sha = sha or _fetch_filing(source)
            found = investor_eps.archived_statements(sha)
            if found:
                latest = _check_filing_receipt(source, sha, found)
                if latest != sha:
                    sha, found = latest, investor_eps.archived_statements(latest)
                today = date.today().isoformat()
                published = investor_eps.official_eps(org, today, today, 'separate')
                log.info('Printed EPS: issuer %s filed %s, extracted %s, verified %s', org, filed,
                         [(r['period_end'], r['raw_value']) for r in found], published)
            result['statements_checked'] += 1
            result['statements_with_eps'] += bool(found)
        except Exception as exc:
            result['errors'].append({'issuer_id':org, 'source_id':source, 'file_hash':sha, 'error':str(exc)})
        if sha:
            originals.append((filed, org, source, sha))
    return originals


def backfill_statements():
    """Refresh the issuer listings and scan printed statements without waiting for image OCR."""
    from catalogue.snapshots import _remember_ifrs_sources
    from .bulk import issuers

    companies, _ = issuers()
    result = {'statements_checked':0, 'statements_with_eps':0, 'errors':[]}
    with sources._make_session() as session:
        for company in companies:
            org, ticker = str(company['org_id']), company['ticker']
            try:
                records, _ = sources._fetch_main_results(session, company['company_name'], org)
                count = _remember_ifrs_sources(ticker=ticker, org_id=org, records=records)
                log.info('Filing registry: %s, %s originals', ticker, count)
            except Exception as exc:
                result['errors'].append({'issuer_id':org, 'stage':'listing', 'error':str(exc)})
    rounds = _filing_rounds({str(c['org_id']) for c in companies})
    with store.transaction() as conn:
        for filings in rounds:
            for _, _, source, sha in filings:
                if not sha:
                    failed = conn.execute("SELECT id FROM ingest_jobs WHERE source_id=? AND stage='FETCH' AND state='FAILED'",
                                          (source,)).fetchall()
                    for job in failed:
                        store.retry_failed(conn, job['id'], actor='bulk-cli', reason='Explicit reported EPS backfill')
    for filings in rounds:
        _scan_statements(filings, result)
    return result


def collect(companies, *, ocr, deadline=None):
    ids = {str(c['org_id']) for c in companies if c['org_id']}
    result = {'errors':[], 'pdfs_checked':0, 'pdfs_with_eps':0, 'statements_checked':0, 'statements_with_eps':0,
              'share_supplements':{'checked':0,'imported':0,'errors':[]},
              'valuation_history':{'filings':0,'quotes':0,'errors':[]}}
    if deadline is not None and time.monotonic() >= deadline:
        return {**result, 'deferred':True}
    try:
        current_shares, past_shares, errors = backfill.share_supplement_rounds(ids)
    except Exception as exc:
        current_shares, past_shares, errors = [], [], [{'stage':'share_supplements','error':str(exc)}]
    result['share_supplements']['errors'].extend(errors)
    result['errors'].extend(errors)
    latest, history = _filing_rounds(ids)
    scanned = set()
    for phase, filings, supplements in [('latest', latest, current_shares), ('history', history, past_shares)]:
        if deadline is not None and time.monotonic() >= deadline:
            return {**result, 'deferred':True}
        log.info('Investor metrics: %s filings (%d originals)', phase, len(filings))
        for name, operation, kwargs in [
            ('share_supplements', backfill.import_share_supplements, {'jobs':supplements}),
            ('valuation_history', backfill.collect_valuation_history, {'issuer_ids':ids,'historical':phase == 'history'}),
        ]:
            try:
                outcome = operation(**kwargs)
            except Exception as exc:
                outcome = {'errors':[{'stage':name,'error':str(exc)}]}
            for key, value in outcome.items():
                result[name][key] += value
            result['errors'].extend(outcome['errors'])
        # A slow image-only PDF must not starve the searchable statements in
        # this round. Each native scan is checkpointed independently of OCR.
        originals = _scan_statements(filings, result, deadline)
        if result.get('deferred'):
            return result
        history_until = time.monotonic() + 1800 if phase == 'history' else None
        for index, (filed, org, source, sha) in enumerate(originals):
            if deadline is not None and time.monotonic() >= deadline:
                return {**result, 'deferred':True}
            if history_until is not None and time.monotonic() >= history_until:
                result['pdfs_pending'] = len(originals) - index
                break
            try:
                if sha in scanned:
                    continue
                log.info('Investor EPS: %s issuer %s, filed %s', phase, org, filed or 'undated')
                rows = investor_eps.archived_rows(sha, ocr=ocr)
                scanned.add(sha)
                result['pdfs_checked'] += 1
                result['pdfs_with_eps'] += bool(rows)
            except Exception as exc:
                result['errors'].append({'issuer_id':org, 'source_id':source, 'file_hash':sha, 'error':str(exc)})
    return result

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    print(json.dumps(backfill_statements(), ensure_ascii=False))
