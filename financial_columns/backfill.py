"""Populate recent detailed source tables for already-catalogued NSBU issuers.

This migration only writes immutable financial_form versions. Existing summary
history, ratios and approved IFRS publication are not rewritten. The ordinary
nightly NSBU collector continues filling the longer history through the same
source_store writer.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json

import catalogue.sources as catalogue_sources
from catalogue.organization import organization_kind
from catalogue.periods import _is_future_period
from catalogue.storage import get_catalog_conn
from . import nsbu, source_store


def pending(annual_periods=2):
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
        quarterly = sorted((p for p in reports if p[1] != 0), reverse=True)[:1]
        covered = {d['period_end'] for d in source_store.read(issuer, standard='NSBU', scope='separate')
                   if d['rows'] and d['quality'] != 'blocked' and d['source_coverage']['complete']}
        for year, quarter in annual + quarterly:
            month = quarter * 3 if quarter else 12
            # Compare year/month, since the source store uses the actual month end.
            if any(end.startswith(f'{year}-{month:02d}-') for end in covered):
                continue
            report = reports[(year, quarter)]
            jobs.append({'ticker': report['ticker'], 'issuer_id': issuer, 'year': year, 'quarter': quarter,
                         'template': organization_kind(report['ticker'], name=report['company_name']),
                         'urls': {k: report.get(k) for k in ('excel_url','excel_url_form1','published_at')}})
    # Cover issuers' latest annual first, then current quarters and prior years.
    return sorted(jobs, key=lambda j: (-(j['year'] if not j['quarter'] else j['year'] - 1), bool(j['quarter']), j['ticker']))


def _import(job):
    data = catalogue_sources.fetch_report_excel_data(job['ticker'], 'NSBU', job['year'], job['quarter'], use_snapshot_cache=False)
    if not data.get('ok'):
        raise ValueError(data.get('error') or 'Source download failed')
    if not any(nsbu.rows(data.get(name) or {}, template=job['template'], default_form=form)
               for name, form in [('income','F2'),('balance','F1')]):
        raise ValueError('No original source rows in workbook')
    version = source_store.record_nsbu(**job, data=data)
    document = source_store.version(version)
    if document['quality'] == 'blocked':
        raise ValueError('Source units require review')
    return {'ticker':job['ticker'], 'year':job['year'], 'quarter':job['quarter'], 'rows':len(document['rows'])}


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
    parser.add_argument('--annual-periods',type=int,default=2)
    parser.add_argument('--max-periods',type=int,default=1000)
    args=parser.parse_args()
    if args.inspect:
        jobs=pending(args.annual_periods)
        print(json.dumps({'date':date.today().isoformat(),'pending':len(jobs),'issuers':len({j['issuer_id'] for j in jobs}),
                          'tickers':sorted({j['ticker'] for j in jobs})}))
        return
    result=run(args.annual_periods,args.max_periods,progress=lambda item:print(json.dumps(item),flush=True))
    print('SOURCE_BACKFILL_RESULT='+json.dumps(result),flush=True)


if __name__ == '__main__':
    main()
