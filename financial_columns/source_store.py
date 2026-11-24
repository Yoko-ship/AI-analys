"""Immutable full NSBU form versions in the existing catalogue database.

Readers never download or parse a filing. The collector records the actual
workbook it parsed, with an atomic pointer to its current source version.
"""
from datetime import date, datetime, timezone
from calendar import monthrange
from decimal import Decimal
import json
import re

import dbx
from catalogue.storage import get_catalog_conn
from financial_ingestion.store import digest, encoded
from financial_ingestion.statements import units, currency
from . import nsbu
from .share_disclosures import filing_key

CONSOLIDATED_TITLE = re.compile(r'консолидированн|consolidated|konsolidatsiyalashgan', re.I)


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


def _bank_filing_type(doc):
    keys = [filing_key(form.get('source_url')) for form in doc['source_forms']]
    if keys and all(key and key[0] == 'bank' and key[1] == keys[0][1] for key in keys):
        return keys[0][1]
    return None


def _prefer_annual(annual, quarterly):
    if annual['quality'] != 'valid' or _bank_filing_type(annual) != 'annual':
        return False
    try:
        annual_date = date.fromisoformat((annual.get('published_at') or '')[:10])
        quarter_date = date.fromisoformat((quarterly.get('published_at') or '')[:10])
    except ValueError:
        return False
    if annual_date <= quarter_date:
        return False
    stated_dates = {str(cells[1])[:10] for form in annual['source_forms'] for sheet in form['sheets']
                    for row in sheet['source_rows'] if len(cells := row['cells']) >= 2
                    and str(cells[0]).casefold().replace('ё', 'е').startswith('дата отчетности')}
    if stated_dates != {annual['period_end']}:
        return False
    totals = {r['metric_id']: Decimal(r['current']['value']) for r in annual['rows']
              if r['source_form'] == 'BANK_BS' and r['current']['quality'] == 'valid'
              and r['metric_id'] in ('total_assets', 'total_equity', 'total_liabilities')}
    return (len(totals) == 3 and totals['total_assets'] > 0
            and abs(totals['total_assets'] - totals['total_equity'] - totals['total_liabilities']) <= 1)


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
    explicit_group = any(CONSOLIDATED_TITLE.search(str(title)) for title in titles)
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
            # Claim the period in one write so concurrent imports see the committed predecessor.
            old_id = c.execute(
                'INSERT INTO financial_form_heads VALUES (?,?,?,?,?) '
                'ON CONFLICT(issuer_id,standard,scope,period_end) DO UPDATE SET version_id=financial_form_heads.version_id '
                'RETURNING version_id', (*context, version_id)).fetchone()['version_id']
            payload['source_version'] = version_id
            payload['previous_version'] = old_id if old_id != version_id else None
            c.execute('INSERT INTO financial_form_versions VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                      (version_id, *context, encoded(payload), datetime.now(timezone.utc).isoformat()))
            if old_id != version_id:
                if template == 'bank' and quarter == 4 and _bank_filing_type(payload) == 'quarter':
                    prior = c.execute('SELECT payload_json FROM financial_form_versions WHERE id=?', (old_id,)).fetchone()
                    if prior and _prefer_annual(json.loads(prior['payload_json']), payload):
                        return version_id
                c.execute('UPDATE financial_form_heads SET version_id=? WHERE issuer_id=? AND standard=? '
                          'AND scope=? AND period_end=?', (version_id, *context))
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


def read_filing_version(issuer_id, scope, end, urls):
    """Annual and fourth-quarter forms can share a closing date and have different figures."""
    required = {urls.get('excel_url'), urls.get('excel_url_form1')} - {None, ''}
    if not required:
        return []
    c = get_catalog_conn()
    try:
        if 'financial_form_versions' not in dbx.tables(c):
            return []
        versions = c.execute('SELECT payload_json FROM financial_form_versions WHERE issuer_id=? '
                             'AND standard=? AND scope=? AND period_end=? ORDER BY recorded_at DESC',
                             (str(issuer_id), 'NSBU', scope, end))
        for row in versions:
            doc = json.loads(row['payload_json'])
            sources = {form.get('source_url') for form in doc.get('source_forms', [])}
            if sources == required and (not urls.get('published_at') or urls['published_at'] == doc.get('published_at')):
                return [doc]
        return []
    finally:
        c.close()


def prior_dates(issuer_id, *, standard, scope, end):
    c = get_catalog_conn()
    try:
        if 'financial_form_heads' not in dbx.tables(c):
            return []
        return [r['period_end'] for r in c.execute(
            'SELECT period_end FROM financial_form_heads WHERE issuer_id=? AND standard=? AND scope=? AND period_end<?',
            (str(issuer_id), standard, scope, end))]
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
