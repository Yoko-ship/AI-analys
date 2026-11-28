"""Bounded recovery of the old PDF-only failures, without financial publication."""
import json

from . import documents, extract, maintenance, store, worker


def run(*, fetch=None, limit=50):
    if not 1 <= limit <= 50:
        raise ValueError('Recovery source limit must be between 1 and 50')
    c = store.connect()
    try:
        sources = [dict(row) for row in c.execute(
            "SELECT DISTINCT s.* FROM ingest_sources s JOIN ingest_jobs j ON j.source_id=s.id "
            "WHERE j.stage='FETCH' AND j.error='Source did not return a PDF' "
            "AND j.state IN ('FAILED','SUPERSEDED') ORDER BY s.id LIMIT ?", (limit,))]
    finally:
        c.close()
    result = {'selected': len(sources), 'backup': maintenance.backup(), 'sources': []}
    processor = extract.processor_version()
    for source in sources:
        with store.transaction() as c:
            documents.register(c, org_id=source['org_id'], ticker=source['ticker'], url=source['url'],
                               category=source['category'], metadata=json.loads(source['metadata_json']), processor=processor)
        run_result = worker.run(max_jobs=2, source_id=source['id'], ocr=True, fetch=fetch, include_coverage=False)
        c = store.connect()
        try:
            candidates = c.execute(
                'SELECT x.payload_json,x.checks_json FROM ingest_candidates x JOIN ingest_versions v ON v.id=x.version_id '
                'JOIN ingest_sources s ON s.latest_version=v.id WHERE s.id=?', (source['id'],)).fetchall()
            evidence = [{'figures': len(json.loads(row['payload_json']).get('figures', {})),
                         'validation_errors': json.loads(row['checks_json']).get('errors', [])} for row in candidates]
        finally:
            c.close()
        result['sources'].append({'source_id': source['id'], 'ticker': source['ticker'], 'url': source['url'],
                                  'outcomes': run_result['outcomes'], 'candidates': len(candidates), 'evidence': evidence})
    result['status'] = store.status()
    result['complete'] = all(source['candidates'] > 0 and all(job['ok'] for job in source['outcomes'])
                             for source in result['sources'])
    return result


if __name__ == '__main__':
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    raise SystemExit(0 if result['complete'] else 1)
