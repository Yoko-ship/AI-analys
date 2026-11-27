import json
import sqlite3


def test_diagnostics_preserve_errors_hidden_by_the_journal_tail(tmp_path):
    from scripts.diagnose_collectors import snapshot

    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE ingest_sources(id TEXT, ticker TEXT, url TEXT);
        CREATE TABLE ingest_jobs(id TEXT, source_id TEXT, stage TEXT, state TEXT,
                                 attempts INTEGER, error TEXT, updated_at TEXT);
        CREATE TABLE corporate_event_checks(source_url TEXT, checked_at TEXT, ok INTEGER);
        INSERT INTO ingest_sources VALUES('s1','INFB','https://openinfo.uz/report.pdf');
        INSERT INTO ingest_jobs VALUES('j1','s1','FETCH','FAILED',5,'HTTP 404','2026-11-27');
        INSERT INTO corporate_event_checks VALUES('https://openinfo.uz/facts/1','2026-11-26',0);
    ''')
    report = tmp_path / 'bulk-financial-report.json'
    report.write_text(json.dumps({'summary': {'failed_jobs': 20}, 'run': {
        'started_at': '2026-11-26', 'errors': [{'ticker': 'INFB', 'reason': 'Annual statement mismatch'}]}}))
    conn.set_authorizer(lambda action, *_: sqlite3.SQLITE_DENY if action in {
        sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE} else sqlite3.SQLITE_OK)
    operations = {'observer': {'online': True}, 'items': [
        {'id': 'terminal-cbu', 'latest': {'status': 'completed', 'publication': 'acknowledged',
                                        'receipts': [{'stage': 'inflation', 'ok': True}]}},
        {'id': 'financial-ingestion', 'latest': {'status': 'running'}},
    ]}
    result = snapshot(conn, report, operations)
    assert result['bulk_run']['errors'] == [{'ticker': 'INFB', 'reason': 'Annual statement mismatch'}]
    assert result['failed_jobs'][0]['error'] == 'HTTP 404'
    assert result['failed_jobs'][0]['ticker'] == 'INFB'
    assert result['failed_disclosures'][0]['source_url'] == 'https://openinfo.uz/facts/1'
    assert result['bulk_summary']['failed_jobs'] == 20
    assert result['observer'] == {'online': True}
    assert result['collectors'][0]['latest']['publication'] == 'acknowledged'
    assert result['collectors'][0]['latest']['receipts'][0]['stage'] == 'inflation'
    assert result['collectors'][1]['latest']['status'] == 'running'
