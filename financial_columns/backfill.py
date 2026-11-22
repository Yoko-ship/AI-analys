"""Populate recent detailed source tables for already-catalogued NSBU issuers.

The default operation writes immutable financial form versions. The ordinary
nightly NSBU collector continues filling the longer history through the same
source_store writer.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from calendar import monthrange
from datetime import date, timedelta
import json

import catalogue.sources as catalogue_sources
from catalogue.organization import organization_kind
from catalogue.periods import _is_future_period
from catalogue.storage import get_catalog_conn
from . import nsbu, source_store


def _recent_jobs(annual_periods):
    c = get_catalog_conn()
    try:
        reports = [dict(r) for r in c.execute(
            "SELECT r.*,c.org_id,c.company_name FROM catalog_reports r JOIN catalog_companies c "
            "ON c.ticker=r.ticker WHERE r.report_form='NSBU' AND "
            "r.period_type IN ('annual','quarter') AND (r.excel_url IS NOT NULL OR r.excel_url_form1 IS NOT NULL)")]
    finally:
        c.close()
    issuers = {}
    for report in reports:
        if not report['year'] or _is_future_period(report['year'], report['quarter']):
            continue
        issuer = str(report['org_id'] or 'ticker:' + report['ticker'])
        period = (report['year'], report['quarter'] or 0)
        candidates = issuers.setdefault(issuer, {})
        previous = candidates.get(period)
        if previous is None or (str(report.get('published_at') or ''), report['id']) > (str(previous.get('published_at') or ''), previous['id']):
            candidates[period] = report
    jobs = []
    for issuer, reports in issuers.items():
        annual = sorted((p for p in reports if p[1] == 0), reverse=True)[:annual_periods]
        quarterly = sorted((p for p in reports if p[1] != 0), reverse=True)
        if annual_periods is not None:
            quarterly = quarterly[:1]
        for year, quarter in annual + quarterly:
            report = reports[(year, quarter)]
            jobs.append({'ticker': report['ticker'], 'issuer_id': issuer, 'year': year, 'quarter': quarter,
                         'template': organization_kind(report['ticker'], name=report['company_name']),
                         'urls': {k: report.get(k) for k in ('excel_url','excel_url_form1','published_at')}})
    # Cover issuers' latest annual first, then current quarters and prior years.
    return sorted(jobs, key=lambda j: (-(j['year'] if not j['quarter'] else j['year'] - 1), bool(j['quarter']), j['ticker']))


def _end(job):
    month = job['quarter'] * 3 if job['quarter'] else 12
    return date(job['year'], month, monthrange(job['year'], month)[1]).isoformat()


def pending(annual_periods=2):
    covered = {}
    result = []
    for job in _recent_jobs(annual_periods):
        issuer = job['issuer_id']
        if issuer not in covered:
            covered[issuer] = {d['period_end'] for d in source_store.read(issuer, standard='NSBU', scope='separate')
                               if d['rows'] and d['quality'] != 'blocked' and d['source_coverage']['complete']}
        if _end(job) not in covered[issuer]:
            result.append(job)
    return result


def collect_share_bases():
    from collectors.openinfo.transport import _json_get
    from .share_disclosures import collect_form5, filing_key

    # The archive listing identifies the few filings with an Excel supplement.
    # Walking its pages covers older quarters without fetching every filing detail.
    groups = defaultdict(dict)
    for job in _recent_jobs(None):
        url = job['urls']['excel_url'] or job['urls']['excel_url_form1']
        key = filing_key(url)
        if key and job['issuer_id'].isdigit() and job['template'] not in {'bank','insurance','microfinance'}:
            org_type, report_type, report_id = key
            groups[(org_type, report_type)][(job['issuer_id'], report_id)] = (job, url)
    result = {'checked': 0, 'imported': 0, 'errors': []}
    with catalogue_sources._make_session() as session:
        for (org_type, report_type), jobs in groups.items():
            path = f'/reports/{org_type}/{report_type}/'
            page = 1
            while jobs:
                try:
                    listing = _json_get(session, path, {'page': page, 'page_size': 500})
                    pages = int(listing['total_pages'])
                    records = listing['results']
                except Exception as exc:
                    result['errors'].append({'listing':path, 'page':page, 'error':str(exc)})
                    break
                for entry in records:
                    found = jobs.pop((str(entry.get('organization')), str(entry.get('id'))), None)
                    if not found or not str(entry.get('int_report') or '').lower().endswith('.xlsx'):
                        continue
                    job, url = found
                    ticker, end = job['ticker'], _end(job)
                    result['checked'] += 1
                    try:
                        result['imported'] += collect_form5(session, ticker=ticker, issuer_id=job['issuer_id'],
                                                            period_end=end, excel_url=url)
                    except Exception as exc:
                        result['errors'].append({'ticker':ticker, 'period_end':end, 'error':str(exc)})
                if page >= pages:
                    break
                page += 1
    return result


def repair_issuer_links():
    from entity_resolver import ORG_OVERRIDES
    from collectors.financials.backfill import backfill_financials, backfill_quarterly_financials
    from catalogue.filings import get_company_index

    c = get_catalog_conn()
    try:
        tickers = {r['ticker'] for r in c.execute('SELECT ticker,org_id FROM catalog_companies')
                   if r['ticker'] in ORG_OVERRIDES and r['org_id'] and ORG_OVERRIDES[r['ticker']] != str(r['org_id'])}
    finally:
        c.close()
    if tickers:
        backfill_financials(tickers=tickers)
        backfill_quarterly_financials(tickers=tickers)
    return {ticker: {'issuer_id': get_company_index(ticker).get('org_id'),
                     'expected_issuer_id': ORG_OVERRIDES[ticker]} for ticker in sorted(tickers)}


def _import(job, *, cache_for_reports=False):
    data = catalogue_sources.fetch_report_excel_data(job['ticker'], 'NSBU', job['year'], job['quarter'], use_snapshot_cache=cache_for_reports)
    if not data.get('ok'):
        raise ValueError(data.get('error') or 'Source download failed')
    if cache_for_reports:
        expected = {job['urls'].get(key) for key in ('excel_url','excel_url_form1')} - {None, ''}
        complete = {part.get('source_url') for form in ('income','balance') if (part := data.get(form))
                    and (part.get('source_coverage') or {}).get('complete')}
        if expected - complete:
            prior = source_store.read(job['issuer_id'],standard='NSBU',scope='separate',period_end=_end(job))
            if any(d['source_coverage']['complete'] for d in prior):
                return {'ticker':job['ticker'], 'year':job['year'], 'quarter':job['quarter'], 'rows':len(prior[0]['rows'])}
            return _import(job)
    if not any(nsbu.rows(data.get(name) or {}, template=job['template'], default_form=form)
               for name, form in [('income','F2'),('balance','F1')]):
        raise ValueError('No original source rows in workbook')
    version = source_store.record_nsbu(**job, data=data)
    document = source_store.version(version)
    if document['quality'] == 'blocked':
        raise ValueError('Source units require review')
    return {'ticker':job['ticker'], 'year':job['year'], 'quarter':job['quarter'], 'rows':len(document['rows'])}


def collect_valuation_quotes(session, ticker, isin, start):
    from catalogue import market_store
    from catalogue.technical_history import _fill_gaps
    from collectors.openinfo import transport

    end = date.today()
    archive = transport._json_get(session, '/iuzse/conclusions/', {
        'isu_cd': isin, 'start_date': start, 'end_date': (end + timedelta(days=1)).isoformat()})
    points = archive.get('results') or []
    if points and str(archive.get('ticker') or '').strip().upper() != ticker:
        raise ValueError('Archive ticker differs from the reviewed issue')
    points = [p for p in points if start <= str(p.get('date') or '') <= end.isoformat()]
    stored = market_store.get_quote_history([isin], 3650).get(isin, [])
    _, changes = _fill_gaps(stored, points, isin)
    return market_store.bulk_upsert_quote_history(changes)


def collect_valuation_history():
    from . import share_disclosures
    from issuer_financials import resolve_issuer

    keys = share_disclosures.filing_keys()
    issues = {}
    result = {'filings':0, 'quotes':0, 'errors':[]}
    for job in _recent_jobs(None):
        org, ticker, end = job['issuer_id'], job['ticker'], _end(job)
        if (org, ticker, end, 'separate') not in keys:
            continue
        try:
            basis = share_disclosures.read(org, ticker, end, 'separate')
            if not basis:
                continue
            _import(job, cache_for_reports=True)
            result['filings'] += 1
            issuer = resolve_issuer(ticker)
            isin = issuer.get('isin') or basis.get('isin')
            if (str(issuer['id']) == org and issuer['ticker'] == ticker and isin and basis.get('ordinary_shares')
                    and basis.get('isin', isin) == isin):
                key = (ticker, isin)
                issues[key] = min(end, issues.get(key, end))
        except Exception as exc:
            result['errors'].append({'ticker':ticker, 'period_end':end, 'error':str(exc)})
    with catalogue_sources._make_session() as session:
        for (ticker, isin), start in issues.items():
            try:
                result['quotes'] += collect_valuation_quotes(session, ticker, isin, start)
            except Exception as exc:
                result['errors'].append({'ticker':ticker, 'error':str(exc)})
    return result


def run(annual_periods=2, max_periods=1000, workers=2, progress=None):
    if not 1 <= annual_periods <= 20 or not 1 <= workers <= 4 or not 1 <= max_periods <= 5000:
        raise ValueError('Invalid backfill bounds')
    jobs = pending(annual_periods)
    result = {'pending':len(jobs), 'imported':0, 'errors':[], 'deferred':max(0,len(jobs)-max_periods)}
    def attempt(job):
        try:
            return _import(job)
        except Exception as exc:
            return {'ticker':job['ticker'],'year':job['year'],'quarter':job['quarter'],'error':str(exc)}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for item in pool.map(attempt,jobs[:max_periods]):
            if item.get('error'):
                result['errors'].append(item)
            else:
                result['imported'] += 1
            if progress:
                progress(item)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspect',action='store_true')
    parser.add_argument('--repair-issuer-links',action='store_true')
    parser.add_argument('--share-bases',action='store_true')
    parser.add_argument('--annual-periods',type=int,default=2)
    parser.add_argument('--max-periods',type=int,default=1000)
    args=parser.parse_args()
    if args.inspect:
        jobs=pending(args.annual_periods)
        print(json.dumps({'date':date.today().isoformat(),'pending':len(jobs),'issuers':len({j['issuer_id'] for j in jobs}),
                          'tickers':sorted({j['ticker'] for j in jobs})}))
        return
    if args.repair_issuer_links:
        repaired = repair_issuer_links()
        print('ISSUER_LINK_REPAIR=' + json.dumps(repaired), flush=True)
        if any(item['issuer_id'] != item['expected_issuer_id'] for item in repaired.values()):
            raise SystemExit('Issuer mapping refresh did not complete')
    if args.share_bases:
        print('SHARE_DISCLOSURE_BACKFILL=' + json.dumps(collect_share_bases()), flush=True)
        print('VALUATION_HISTORY=' + json.dumps(collect_valuation_history()), flush=True)
    result=run(args.annual_periods,args.max_periods,progress=lambda item:print(json.dumps(item),flush=True))
    print('SOURCE_BACKFILL_RESULT='+json.dumps(result),flush=True)


if __name__ == '__main__':
    main()
