"""Reviewed, dated share disclosures, independent of accounting-standard money.

Only share counts and equal ordinary-share rights belong here. A closing count
does not establish a weighted average. ``ordinary_only`` certifies that all
participating equity was ordinary throughout the stated period, not merely that
one ordinary instrument was found on today's exchange board.
"""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

import dbx
from catalogue.storage import get_catalog_conn


FIELDS = {'issuer_id', 'ticker', 'period_start', 'period_end', 'scope', 'source_url',
          'source_standard', 'ordinary_shares', 'weighted_average_shares',
          'ordinary_only', 'ordinary_only_at_end', 'source_lines', 'unit'}
REVIEWED = Path(__file__).resolve().parents[1] / 'config' / 'reviewed_share_disclosures.json'


def _validate(value):
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise ValueError('Share disclosure contains unsupported fields')
    data = dict(value)
    if not str(data.get('issuer_id') or '').strip() or not str(data.get('ticker') or '').strip():
        raise ValueError('Issuer identity is required')
    data['issuer_id'], data['ticker'] = str(data['issuer_id']), data['ticker'].strip().upper()
    start, end = date.fromisoformat(data['period_start']), date.fromisoformat(data['period_end'])
    if start > end or data.get('scope') not in {'separate', 'consolidated'}:
        raise ValueError('Invalid disclosure period or scope')
    source = urlparse(data.get('source_url') or '')
    if source.scheme != 'https' or not source.hostname or source.username or source.password:
        raise ValueError('A public source URL is required')
    if data.get('unit') != 'shares' or data.get('source_standard') not in {'NSBU', 'MSFO'}:
        raise ValueError('Share counts must use shares, with their source standard identified')
    lines = data.get('source_lines')
    if not isinstance(lines, dict):
        raise ValueError('Source lines are required')
    for key in ('ordinary_shares', 'weighted_average_shares'):
        if key not in data:
            continue
        try:
            number = Decimal(str(data[key]))
        except (ValueError, InvalidOperation):
            raise ValueError('Invalid share count') from None
        if not number.is_finite() or number <= 0 or (key == 'ordinary_shares' and number != number.to_integral_value()):
            raise ValueError('Invalid share count')
        if not isinstance(lines.get(key), str) or not lines[key].strip():
            raise ValueError('Each count needs a source line')
        data[key] = str(number)
    if not any(k in data for k in ('ordinary_shares', 'weighted_average_shares')):
        raise ValueError('At least one disclosed share count is required')
    for field in ('ordinary_only', 'ordinary_only_at_end'):
        if type(data.get(field, False)) is not bool:
            raise ValueError('Ordinary-share rights must be explicit')
        if data.get(field) and not (isinstance(lines.get(field), str) and lines[field].strip()):
            raise ValueError('Ordinary-only equity requires source evidence')
    return data


def record(disclosure, *, actor, reason, replace=False):
    data = _validate(disclosure)
    if not actor.strip() or not reason.strip():
        raise ValueError('A reviewer and review reason are required')
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    version = hashlib.sha256(payload.encode()).hexdigest()
    key = (data['issuer_id'], data['ticker'], data['period_end'], data['scope'])
    c = get_catalog_conn()
    try:
        c.executescript('''
            CREATE TABLE IF NOT EXISTS share_disclosure_versions (
                id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, actor TEXT NOT NULL,
                reason TEXT NOT NULL, reviewed_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS share_disclosure_heads (
                issuer_id TEXT NOT NULL, ticker TEXT NOT NULL, period_end TEXT NOT NULL,
                scope TEXT NOT NULL, version_id TEXT NOT NULL,
                PRIMARY KEY (issuer_id,ticker,period_end,scope));
        ''')
        with c:
            old = c.execute('SELECT version_id FROM share_disclosure_heads WHERE issuer_id=? AND ticker=? AND period_end=? AND scope=?', key).fetchone()
            if old and old['version_id'] != version and not replace:
                raise ValueError('Conflicting share disclosure: explicit replace is required')
            c.execute('INSERT INTO share_disclosure_versions VALUES (?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                      (version, payload, actor, reason, datetime.now(timezone.utc).isoformat()))
            c.execute('INSERT INTO share_disclosure_heads VALUES (?,?,?,?,?) ON CONFLICT(issuer_id,ticker,period_end,scope) DO UPDATE SET version_id=excluded.version_id', (*key, version))
        return version
    finally:
        c.close()


@lru_cache(maxsize=1)
def _reviewed():
    records = {}
    for value in json.loads(REVIEWED.read_text(encoding='utf-8')):
        data = _validate(value)
        key = (data['issuer_id'], data['ticker'], data['period_end'], data['scope'])
        if key in records:
            raise ValueError('Duplicate reviewed share disclosure')
        digest = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        records[key] = (data, digest)
    return records


def read(issuer_id, ticker, end, scope):
    from copy import deepcopy

    key = (str(issuer_id), ticker.upper(), end, scope)
    c = get_catalog_conn()
    try:
        row = None
        if 'share_disclosure_heads' in dbx.tables(c):
            row = c.execute('SELECT v.* FROM share_disclosure_heads h JOIN share_disclosure_versions v ON v.id=h.version_id '
                            'WHERE h.issuer_id=? AND h.ticker=? AND h.period_end=? AND h.scope=?', key).fetchone()
    finally:
        c.close()
    if row:
        data, version = _validate(json.loads(row['payload_json'])), row['id']
        if (data['issuer_id'], data['ticker'], data['period_end'], data['scope']) != key:
            return None
    else:
        reviewed = _reviewed().get(key)
        if not reviewed:
            return None
        data, version = deepcopy(reviewed)
    return {**data, 'source_version': version, 'verification_status': 'verified'}

def form5_basis(workbook, *, ticker, issuer_id, tin, period_end):
    """Extract point-in-time share counts from a dated NSBU equity statement."""
    from datetime import timedelta
    from financial_ingestion.statements import START_MONTHS
    from .nsbu import cell

    if not re.fullmatch(r'\d{9}', str(tin)):
        return None
    end = date.fromisoformat(period_end)
    dates = {end, end + timedelta(days=1)}
    date_pattern = re.compile(r'^\s*на\s+(\d{1,2})\s+(' + '|'.join(START_MONTHS) + r')\s+(20\d{2})\b', re.I | re.M)
    codes = {'131', '150', '151', '152'}
    matches = []
    for sheet in workbook.get('sheets', []):
        rows = [entry['cells'] for entry in sheet.get('source_rows', [])]
        header = '\n'.join(str(cell or '') for row in rows[:16] for cell in row)
        if '0710005' not in header or not re.search(r'(?<!\d)' + str(tin) + r'(?!\d)', header):
            continue
        stamps = set()
        for day, month, year in date_pattern.findall(header):
            try:
                stamps.add(date(int(year), START_MONTHS[month.lower()], int(day)))
            except ValueError:
                continue
        if not stamps or not stamps <= dates:
            continue
        amounts = {}
        for row in rows:
            if len(row) < 9 or str(row[1]).strip() not in codes:
                continue
            code = str(row[1]).strip()
            # The reference rows put share counts in the total column.
            if code in amounts:
                amounts = {}
                break
            amount = cell(row[8])['value']
            number = Decimal(amount) if amount is not None else None
            amounts[code] = number if number is not None and number >= 0 and number == number.to_integral_value() else None
        ordinary, preferred, total = (amounts.get(code) for code in ('152', '151', '150'))
        if ordinary is None or ordinary <= 0 or preferred is None or total != ordinary + preferred:
            continue
        only = preferred == 0 and amounts.get('131') == 0
        lines = {'ordinary_shares': 'Form 5, lines 150–152: shares outstanding by class'}
        if only:
            lines['ordinary_only_at_end'] = 'Form 5, lines 131 and 150–152: no preferred shares issued or outstanding'
        matches.append({'issuer_id': str(issuer_id), 'ticker': ticker, 'scope': 'separate',
                        'period_start': f'{end.year}-01-01', 'period_end': period_end,
                        'unit': 'shares', 'source_url': workbook['source_url'], 'source_standard': 'NSBU',
                        'ordinary_shares': str(ordinary), 'ordinary_only_at_end': only, 'source_lines': lines})
    return matches[0] if matches and all(basis == matches[0] for basis in matches) else None

def collect_form5(session, *, ticker, issuer_id, period_end, excel_url):
    """Import a supplement attached to the same official OpenInfo filing."""
    from urllib.parse import parse_qs
    from collectors.openinfo.transport import _json_get
    from catalogue.history import _parse_workbook_uncached

    if not str(issuer_id or '').isdigit():
        return False
    source = urlparse(excel_url or '')
    if (source.scheme, source.netloc, source.path) != (
        'https', 'new-api.openinfo.uz', '/api/v2/reports/export-excel/',
    ):
        return False
    query = parse_qs(source.query)
    report_type = (query.get('report_type') or [''])[0]
    org_type = (query.get('org_type') or [''])[0]
    report_id = (query.get('report_id') or [''])[0]
    if report_type not in {'annual', 'quarter'} or not re.fullmatch(r'[a-z_]+', org_type) or not report_id.isdigit():
        return False
    if read(issuer_id, ticker, period_end, 'separate'):
        return False
    detail = _json_get(session, f'/reports/{org_type}/{report_type}/{report_id}/')
    if str((detail.get('organization') or {}).get('id')) != str(issuer_id) or str(detail.get('id')) != report_id:
        return False
    attachment = urlparse(detail.get('int_report') or '')
    if (attachment.scheme != 'https' or attachment.netloc != 'openinfo.uz' or attachment.query or attachment.fragment
            or not re.fullmatch(r'/media/int_report/[A-Za-z0-9_-]+\.xlsx', attachment.path)):
        return False
    url = attachment.geturl()
    workbook = _parse_workbook_uncached(session, url)
    basis = form5_basis({**workbook, 'source_url': url}, ticker=ticker, issuer_id=issuer_id,
                        tin=detail.get('organization_inn'), period_end=period_end)
    if not basis:
        return False
    try:
        record(basis, actor='openinfo-form5', reason='Matched issuer, reporting date and issued share classes')
    except ValueError:
        # A concurrently reviewed source keeps its precedence over this import.
        if not read(issuer_id, ticker, period_end, 'separate'):
            raise
        return False
    return True
