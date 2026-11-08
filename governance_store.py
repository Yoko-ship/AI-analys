"""Per-issuer collection receipts, separate from the public disclosure ledger."""
import json

import dbx
from catalogue.storage import get_catalog_conn


def receipts():
    conn = get_catalog_conn()
    try:
        if 'governance_collection' not in dbx.tables(conn):
            return {}
        return {row['issuer_id']: json.loads(row['payload_json'])
                for row in conn.execute('SELECT issuer_id,payload_json FROM governance_collection')}
    finally:
        conn.close()


def save(issuer_id, payload):
    conn = get_catalog_conn()
    try:
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS governance_collection (issuer_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)')
            conn.execute('INSERT INTO governance_collection VALUES (?,?) ON CONFLICT(issuer_id) DO UPDATE SET payload_json=excluded.payload_json',
                         (str(issuer_id), json.dumps(payload, ensure_ascii=False)))
    finally:
        conn.close()


def status(issuer_id):
    if not issuer_id:
        return {'state': 'unavailable', 'reason': 'MISSING_ISSUER_ID'}
    row = receipts().get(str(issuer_id))
    if not row:
        return {'state': 'pending', 'reason': 'NOT_COLLECTED'}
    return {k: v for k, v in row.items() if k != 'document_checks'}


def identity(ticker):
    """Local issuer mapping for market securities with no financial reports yet."""
    matches = [row for row in receipts().values() if ticker in row.get('tickers', [])]
    row = max(matches, key=lambda row: row['checked_at']) if matches else {}
    return row.get('issuer_id'), set(row.get('tickers') or [])


def documents():
    conn = get_catalog_conn()
    try:
        if 'corporate_event_documents' not in dbx.tables(conn):
            return {}
        rows = [json.loads(row['document_json']) for row in conn.execute(
            'SELECT document_json FROM corporate_event_documents WHERE document_json LIKE ?', ('%"governance"%',))]
        return {str(row['global_fact_id']): row for row in rows if row.get('global_fact_id')}
    finally:
        conn.close()
