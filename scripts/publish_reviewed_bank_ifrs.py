"""Explicit release of checked-in bank reviews, preserving existing published values.

Run python -m scripts.publish_reviewed_bank_ifrs --apply after deployment.
Scheduled workers never invoke this command.
"""
import argparse
import hashlib
import json
import time
import tempfile
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from financial_ingestion import documents, extract, maintenance, publication, store, validation
from ifrs_financials import download_pdf
import reports_catalog as rc

def claim_selected(source_id, stage, processor_filter=None):
    with store.transaction() as c:
        row = c.execute("SELECT * FROM ingest_jobs WHERE source_id=? AND stage=? AND state IN ('QUEUED','RETRY') AND available_at<=? AND attempts<3 "
                        + ("AND processor=? " if processor_filter else "") + "ORDER BY available_at,id LIMIT 1",
                        (source_id, stage, time.time(), *((processor_filter,) if processor_filter else ()))).fetchone()
        if not row:
            raise RuntimeError('No eligible selected job: ' + source_id + ' ' + stage)
        job = dict(row)
        job.update(lease_token=uuid4().hex, attempts=job['attempts'] + 1)
        c.execute("UPDATE ingest_jobs SET state='RUNNING',attempts=?,lease_until=?,lease_token=?,updated_at=? WHERE id=?",
                  (job['attempts'], time.time() + 900, job['lease_token'], store.now(), job['id']))
        store.event(c, job['id'], 'job.claimed', actor='reviewed-gap-release', attempt=job['attempts'])
        return job

def release(*, fetch=None):
    with tempfile.TemporaryDirectory(prefix="reviewed-bank-release-") as scratch:
        return _release(fetch=fetch or download_pdf, scratch=Path(scratch))


def _release(*, fetch, scratch):
    entries = extract.review_entries()
    processor = extract.processor_version()
    tickers = sorted({e['ticker'] for e in entries})
    verified_sources = {}
    for entry in entries:
        url = entry['pdf_url']
        if url not in verified_sources:
            path = scratch / (str(len(verified_sources)) + '.pdf')
            path.write_bytes(fetch(url))
            verified_sources[url] = path
        if hashlib.sha256(verified_sources[url].read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Source changed since visual review: ' + entry['ticker'])
    backup = maintenance.backup()
    if not backup['verified']:
        raise ValueError('Verified backup required before release')
    print(json.dumps({'backup': backup}), flush=True)
    before = {t: {**(publication.series(t) or {}), **(publication.series(t, quarterly=True) or {})} for t in tickers}
    for ticker in tickers:
        expected_org = next(str(e['org_id']) for e in entries if e['ticker'] == ticker)
        if str((rc.get_company_index(ticker) or {}).get('org_id')) != expected_org:
            raise ValueError('Issuer identity mismatch: ' + ticker)
        documents.discover(ticker=ticker, processor=processor)

    for url in sorted({e['pdf_url'] for e in entries}):
        entry = next(e for e in entries if e['pdf_url'] == url)
        c = store.connect()
        source = c.execute('SELECT s.*,v.sha FROM ingest_sources s LEFT JOIN ingest_versions v ON v.id=s.latest_version WHERE s.org_id=? AND s.url=?', (str(entry['org_id']), url)).fetchone()
        c.close()
        if not source:
            raise ValueError('Reviewed source absent from issuer catalog: ' + entry['ticker'])
        source = dict(source)
        if source['sha'] != entry['sha256']:
            job = claim_selected(source['id'], 'FETCH')
            try:
                documents.fetch_job(job, processor, fetch=lambda url: verified_sources[url].read_bytes())
            except Exception as exc:
                store.fail(job, exc)
                raise
        c = store.connect()
        current = c.execute('SELECT v.* FROM ingest_sources s JOIN ingest_versions v ON v.id=s.latest_version WHERE s.id=?', (source['id'],)).fetchone()
        existing = c.execute('SELECT COUNT(*) FROM ingest_candidates WHERE version_id=? AND processor=?', (current['id'], processor)).fetchone()[0]
        c.close()
        if current['sha'] != entry['sha256']:
            raise ValueError('Source changed since visual review')
        documents.read_artifact(entry['sha256'])
        if not existing:
            job = claim_selected(source['id'], 'EXTRACT', processor)
            try:
                extract.extract_job(job)
            except Exception as exc:
                store.fail(job, exc)
                raise
        print(json.dumps({'staged': entry['ticker'], 'sha': entry['sha256']}), flush=True)

    selected = {}
    for ticker in tickers:
        c = store.connect()
        rows = c.execute("SELECT x.* FROM ingest_candidates x JOIN ingest_versions v ON v.id=x.version_id JOIN ingest_sources s ON s.latest_version=v.id "
                         "WHERE s.org_id=? AND x.processor=? AND EXISTS (SELECT 1 FROM ingest_reviews r WHERE r.candidate_id=x.id AND r.decision='APPROVED')",
                         (str(rc.get_company_index(ticker)['org_id']), processor)).fetchall()
        c.close()
        if len(rows) != sum(e['ticker'] == ticker for e in entries):
            raise ValueError('Approved candidate count mismatch: ' + ticker)
        normalized = {}
        for row in rows:
            payload = json.loads(row['payload_json'])
            check = validation.validate(payload, page_count=payload['page_count'])
            if not check['valid']:
                raise ValueError('Invalid candidate: ' + str(check['errors']))
            normalized[publication.period_key(payload['classification'])] = {k: float(Decimal(v) / 1000) for k, v in check['normalized_uzs'].items()}
        for period, fields in (before[ticker] or {}).items():
            for field, value in fields.items():
                if normalized.get(period, {}).get(field) != value:
                    raise ValueError(f'Existing published value changed: {ticker} {period} {field}')
        selected[ticker] = [r['id'] for r in rows]

    for ticker, ids in selected.items():
        result = publication.publish(ticker, actor='visual-source-reviewed-gap-release-2026-09-18', candidate_ids=ids, replace=True)
        print(json.dumps(result), flush=True)

    verified = 0
    for entry in entries:
        payload = validation.from_review(entry)
        period = publication.period_key(payload['classification'])
        check = validation.validate(payload, page_count=entry['page_count'])
        for field in entry['figures']:
            passport = publication.passport(entry['ticker'], period, field)
            if (passport.get('source', {}).get('file_hash') != entry['sha256']
                    or passport['source']['normalized_value'] != float(check['normalized_uzs'][field])):
                raise ValueError(f'Published passport mismatch: {entry["ticker"]} {period} {field}')
            verified += 1
    with store.transaction() as c:
        store.event(c, 'reviewed-gap-release', 'release.verified', actor='visual-source-reviewed-gap-release-2026-09-18', figures=verified, periods=len(entries))
    return {'verified_figures': verified, 'periods': len(entries), 'preserved_previous_values': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True,
                        help='Explicitly stage and publish the checked-in reviewed ledger')
    parser.parse_args()
    print(json.dumps(release()), flush=True)
