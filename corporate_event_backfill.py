"""Paced, resumable disclosure enrichment. No model or generated financial data."""
from datetime import datetime, timezone, timedelta
import argparse
import json
import dbx
import corporate_events as ce
import corporate_event_fields as fields
from catalogue.storage import get_catalog_conn
from collection_ops.model import receipt, scrub


def run(*, limit=40, days=120, now=None):
    now = now or datetime.now(timezone.utc)
    conn = get_catalog_conn()
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS corporate_event_checks (source_url TEXT PRIMARY KEY, checked_at TEXT NOT NULL, ok INTEGER NOT NULL)')
        columns=dbx.columns(conn,'corporate_event_checks')
        if 'extraction_version' not in columns:
            conn.execute('ALTER TABLE corporate_event_checks ADD COLUMN extraction_version INTEGER NOT NULL DEFAULT 0')
        if 'last_error' not in columns:
            conn.execute("ALTER TABLE corporate_event_checks ADD COLUMN last_error TEXT NOT NULL DEFAULT ''")
        conn.commit()
        checks={r['source_url']:dict(r) for r in conn.execute('SELECT * FROM corporate_event_checks')}
        versions={source:r['extraction_version'] for source,r in checks.items()}
        checked={source:r['checked_at'] for source,r in checks.items()}
        cutoff = (now-timedelta(days=7)).isoformat()
        retry_cutoff = (now-timedelta(days=1)).isoformat()
        docs = {d['source_url']:d for story in ce.feed((now-timedelta(days=min(days,399))).date().isoformat(),now.date().isoformat())['items'] for d in story['documents']}
        pending = [source for source in docs if versions.get(source,0)<fields.VERSION
                   or checked.get(source,'') < (retry_cutoff if checks.get(source,{}).get('ok')==0 else cutoff)]
        # Unseen and oldest-checked documents go first, so a busy recent feed
        # cannot starve older evidence when the daily budget is smaller.
        pending.sort(key=lambda source:checked.get(source,''))
        result = {'attempted':0,'enriched':0,'failed':0,'remaining':max(0,len(pending)-limit),'errors':[]}
        for source in pending[:max(0,min(limit,2000))]:
            ok = 0
            error = ''
            try:
                ce.refresh_document(source)
                result['enriched'] += 1
                ok = 1
            except Exception as exc:
                error = scrub(str(exc))[:1000]
                result['failed'] += 1
                result['errors'].append({'source_url':source,'reason':error})
            result['attempted'] += 1
            conn.execute('INSERT INTO corporate_event_checks (source_url,checked_at,ok,extraction_version,last_error) VALUES (?,?,?,?,?) ON CONFLICT(source_url) DO UPDATE SET checked_at=excluded.checked_at,ok=excluded.ok,extraction_version=excluded.extraction_version,last_error=excluded.last_error',(source,now.isoformat(),ok,fields.VERSION,error))
            conn.commit()
            receipt('disclosure/'+source,ok=bool(ok),phase='publication' if ok else 'collection',
                    counts={'written':1} if ok else None,reason=error)
        return result
    finally:
        conn.close()


def main(argv=None):
    import governance_collection
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=40)
    parser.add_argument('--days',type=int,default=120)
    parser.add_argument('--governance-limit', type=int, default=100)
    args=parser.parse_args(argv)
    evidence = run(limit=args.limit,days=args.days)
    governance = governance_collection.run(limit=args.governance_limit,
        progress=governance_collection.report_receipt)
    print(json.dumps({'evidence': evidence, 'governance': governance}, ensure_ascii=False), flush=True)
    return 1 if evidence['failed'] or governance['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
