"""Read retained collector failures that may no longer fit in the journal tail."""
import json
from pathlib import Path


def snapshot(conn, report_path, operations=None):
    report = json.loads(Path(report_path).read_text()) if Path(report_path).is_file() else {}
    run = report.get('run', {})
    operations = operations or {}
    return {
        'observer': operations.get('observer', {}),
        'collectors': [{'id': item['id'], 'latest': {
            key: value for key, value in item['latest'].items()
            if key in {'status', 'publication', 'started_at', 'finished_at', 'reason', 'receipts', 'exit_code'}
        }} for item in operations.get('items', [])],
        'bulk_summary': report.get('summary', {}),
        'bulk_run': {key: run[key] for key in ('started_at', 'finished_at', 'errors', 'processing',
                                             'catalog_sync', 'unresolved_tickers') if key in run},
        'failed_jobs': [dict(row) for row in conn.execute(
            "SELECT j.id,s.ticker,s.url,j.stage,j.state,j.attempts,j.error,j.updated_at "
            "FROM ingest_jobs j JOIN ingest_sources s ON s.id=j.source_id "
            "WHERE j.state='FAILED' ORDER BY j.updated_at DESC LIMIT 100").fetchall()],
        'failed_disclosures': [dict(row) for row in conn.execute(
            'SELECT source_url,checked_at FROM corporate_event_checks WHERE ok=0 '
            'ORDER BY checked_at DESC LIMIT 30').fetchall()],
    }


if __name__ == '__main__':
    from catalogue.storage import get_catalog_conn
    from db import APP_DATA_DIR
    from collection_ops.model import scrub
    from collection_ops.store import overview

    conn = get_catalog_conn()
    try:
        print(scrub(json.dumps(snapshot(conn, APP_DATA_DIR / 'bulk-financial-report.json', overview()), ensure_ascii=True)))
    finally:
        conn.close()
