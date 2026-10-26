"""Paced, resumable disclosure enrichment. No model or generated financial data."""
from datetime import datetime, timezone, timedelta
import argparse
import json
import dbx
import corporate_events as ce
import corporate_event_fields as fields
from catalogue.storage import get_catalog_conn


def run(*, limit=40, days=120, now=None):
    now = now or datetime.now(timezone.utc)
    conn = get_catalog_conn()
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS corporate_event_checks (source_url TEXT PRIMARY KEY, checked_at TEXT NOT NULL, ok INTEGER NOT NULL)')
        columns=dbx.columns(conn,'corporate_event_checks')
        if 'extraction_version' not in columns:
            conn.execute('ALTER TABLE corporate_event_checks ADD COLUMN extraction_version INTEGER NOT NULL DEFAULT 0')
        conn.commit()
        versions={r['source_url']:r['extraction_version'] for r in conn.execute('SELECT * FROM corporate_event_checks')}
        checked = {r['source_url']: r['checked_at'] for r in conn.execute('SELECT * FROM corporate_event_checks').fetchall()}
        cutoff = (now-timedelta(days=7)).isoformat()
        docs = {d['source_url']:d for story in ce.feed((now-timedelta(days=min(days,399))).date().isoformat(),now.date().isoformat())['items'] for d in story['documents']}
        pending = [source for source in docs if versions.get(source,0)<fields.VERSION or checked.get(source,'') < cutoff]
        # Unseen and oldest-checked documents go first, so a busy recent feed
        # cannot starve older evidence when the daily budget is smaller.
        pending.sort(key=lambda source:checked.get(source,''))
        result = {'attempted':0,'enriched':0,'failed':0,'remaining':max(0,len(pending)-limit)}
        for source in pending[:max(0,min(limit,2000))]:
            ok = 0
            try:
                ce.refresh_document(source)
                result['enriched'] += 1
                ok = 1
            except Exception:
                result['failed'] += 1
            result['attempted'] += 1
            conn.execute('INSERT INTO corporate_event_checks (source_url,checked_at,ok,extraction_version) VALUES (?,?,?,?) ON CONFLICT(source_url) DO UPDATE SET checked_at=excluded.checked_at,ok=excluded.ok,extraction_version=excluded.extraction_version',(source,now.isoformat(),ok,fields.VERSION))
            conn.commit()
        return result
    finally:
        conn.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=40)
    parser.add_argument('--days',type=int,default=120)
    args=parser.parse_args()
    print(json.dumps(run(limit=args.limit,days=args.days)))
