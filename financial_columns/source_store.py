"""Immutable full NSBU form versions in the existing catalogue database.

Readers never download or parse a filing. The collector records the actual
workbook it parsed, with an atomic pointer to its current source version.
"""
from datetime import date, datetime, timezone
from calendar import monthrange
import json
import re

import dbx
from catalogue.storage import get_catalog_conn
from financial_ingestion.store import digest, encoded
from financial_ingestion.statements import units, currency
from . import nsbu


def _schema(c):
    c.executescript('''
        CREATE TABLE IF NOT EXISTS financial_form_versions (
            id TEXT PRIMARY KEY, issuer_id TEXT NOT NULL, standard TEXT NOT NULL,
            scope TEXT NOT NULL, period_end TEXT NOT NULL, payload_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS financial_form_heads (
            issuer_id TEXT NOT NULL, standard TEXT NOT NULL, scope TEXT NOT NULL,
            period_end TEXT NOT NULL, version_id TEXT NOT NULL,
            PRIMARY KEY (issuer_id, standard, scope, period_end));
    ''')


def record_nsbu(*, ticker, issuer_id, year, quarter, template, data, urls):
    if not data.get('ok') or not issuer_id:
        raise ValueError('A verified issuer and parsed source are required')
    month = 3 * quarter if quarter else 12
    end = date(year, month, monthrange(year, month)[1]).isoformat()
    documents, rows, issues, seen, denominations = [], [], [], set(), set()
    for name, default_form in [('balance', 'F1'), ('income', 'F2')]:
        workbook = data.get(name)
        if not workbook:
            continue
        source = {'sheets': workbook.get('sheets') or [],
                  'source_url': workbook.get('source_url') or urls.get('excel_url_form1' if name == 'balance' else 'excel_url'),
                  'source_coverage': workbook.get('source_coverage') or {'complete': False, 'issues': ['LEGACY_PARTIAL_IMPORT']}}
        identity = digest(source)
        if identity in seen:
            continue
        seen.add(identity)
        documents.append(source)
        issues += source['source_coverage'].get('issues', [])
        if not source['source_coverage'].get('complete'):
            issues.append('PARTIAL_SOURCE_IMPORT')
        for sheet in source['sheets']:
            for row in sheet.get('source_rows') or []:
                for value in row['cells']:
                    if isinstance(value, str) and len(value) < 100 and units(value):
                        denominations.add((currency(value), units(value)))
        rows += nsbu.rows(source, template=template, default_form=default_form)
    denomination, scale = next(iter(denominations)) if len(denominations) == 1 else (None, None)
    if denomination != 'UZS' or not scale:
        issues.append('UNIT_UNRESOLVED')
    if not rows:
        issues.append('NO_SOURCE_ROWS')
    titles = [urls.get('title') or '', *(sheet.get('sheet', '') for doc in documents for sheet in doc['sheets'])]
    explicit_group = any(re.search(r'консолидированн|consolidated|konsolidatsiyalashgan', str(title), re.I) for title in titles)
    scope = urls.get('scope') or ('consolidated' if explicit_group else 'separate')
    if scope not in {'separate', 'consolidated'} or (explicit_group and scope == 'separate'):
        raise ValueError('Conflicting or unknown filing scope')
    payload = {'issuer_id': str(issuer_id), 'ticker': ticker, 'standard': 'NSBU', 'scope': scope,
               'period_start': f'{year}-01-01', 'period_end': end,
               'template': template, 'currency': denomination, 'unit_scale': scale,
               'published_at': urls.get('published_at'), 'source_forms': documents, 'rows': rows,
               'source_coverage': {'complete': not issues, 'issues': sorted(set(issues))},
               'quality': 'blocked' if 'UNIT_UNRESOLVED' in issues else 'warn' if issues else 'valid'}
    version_id = digest(payload)
    c = get_catalog_conn()
    try:
        _schema(c)
        context = (str(issuer_id), 'NSBU', scope, end)
        with c:
            old = c.execute('SELECT version_id FROM financial_form_heads WHERE issuer_id=? AND standard=? AND scope=? AND period_end=?', context).fetchone()
            payload['source_version'] = version_id
            payload['previous_version'] = old['version_id'] if old and old['version_id'] != version_id else None
            c.execute('INSERT INTO financial_form_versions VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                      (version_id, *context, encoded(payload), datetime.now(timezone.utc).isoformat()))
            c.execute('INSERT INTO financial_form_heads VALUES (?,?,?,?,?) ON CONFLICT(issuer_id,standard,scope,period_end) DO UPDATE SET version_id=excluded.version_id',
                      (*context, version_id))
        return version_id
    finally:
        c.close()


def read(issuer_id, *, standard, scope, period_end=None, latest=False):
    c = get_catalog_conn()
    try:
        if 'financial_form_heads' not in dbx.tables(c):
            return []
        params = [str(issuer_id), standard, scope]
        restriction = ''
        order = ' ORDER BY h.period_end'
        if period_end:
            restriction = ' AND h.period_end=?'
            params.append(period_end)
        elif latest:
            restriction = ' AND h.period_end<?'
            params.append(date.today().isoformat())
            order = ' ORDER BY h.period_end DESC LIMIT 1'
        return [json.loads(row['payload_json']) for row in c.execute(
            'SELECT v.payload_json FROM financial_form_heads h JOIN financial_form_versions v ON v.id=h.version_id '
            'WHERE h.issuer_id=? AND h.standard=? AND h.scope=?' + restriction + order, params)]
    finally:
        c.close()


def version(version_id):
    c = get_catalog_conn()
    try:
        if 'financial_form_versions' not in dbx.tables(c):
            return None
        row = c.execute('SELECT payload_json FROM financial_form_versions WHERE id=?', (version_id,)).fetchone()
        return json.loads(row['payload_json']) if row else None
    finally:
        c.close()

def consolidated_series(issuer_id):
    """Only dated, validated cells from an explicitly consolidated NSBU workbook."""
    from . import observations
    series, sources = {}, []
    for doc in read(issuer_id, standard='NSBU', scope='consolidated'):
        if doc.get('scope') != 'consolidated' or str(doc.get('issuer_id')) != str(issuer_id):
            continue
        rows = observations.nsbu([doc])
        observations.check(rows)
        end = date.fromisoformat(doc['period_end'])
        period = str(end.year) if end.month == 12 else f'{end.year}Q{end.month // 3}'
        values = {}
        for row in rows:
            if row['role'] == 'PRIMARY' and row.get('metric_id'):
                value = row['value'] if row['quality'] in {'valid','warn'} else None
                values.setdefault(row['metric_id'], set()).add(value)
        series[period] = {k:float(next(iter(v))) for k,v in values.items() if len(v) == 1 and None not in v}
        sources.append({'period':period, 'scope':'consolidated', 'published_at':doc.get('published_at'),
                        'report_id':doc['source_version'], 'excel_url':next((r['source_url'] for r in rows if r.get('source_url')),None)})
    return series, sources
