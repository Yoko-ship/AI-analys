"""Reviewed, dated share disclosures, independent of accounting-standard money.

Only share counts and equal ordinary-share rights belong here. A closing count
does not establish a weighted average. ``ordinary_only`` certifies that all
participating equity was ordinary throughout the stated period, not merely that
one ordinary instrument was found on today's exchange board.
"""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from urllib.parse import urlparse

import dbx
from catalogue.storage import get_catalog_conn


FIELDS = {'issuer_id', 'ticker', 'period_start', 'period_end', 'scope', 'source_url',
          'source_standard', 'ordinary_shares', 'weighted_average_shares',
          'ordinary_only', 'source_lines', 'unit'}


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
    if type(data.get('ordinary_only', False)) is not bool:
        raise ValueError('Ordinary-share rights must be explicit')
    if data.get('ordinary_only') and not (isinstance(lines.get('ordinary_only'), str) and lines['ordinary_only'].strip()):
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


def read(issuer_id, ticker, end, scope):
    c = get_catalog_conn()
    try:
        if 'share_disclosure_heads' not in dbx.tables(c):
            return None
        row = c.execute('SELECT v.* FROM share_disclosure_heads h JOIN share_disclosure_versions v ON v.id=h.version_id '
                        'WHERE h.issuer_id=? AND h.ticker=? AND h.period_end=? AND h.scope=?',
                        (str(issuer_id), ticker.upper(), end, scope)).fetchone()
        if not row:
            return None
        data = _validate(json.loads(row['payload_json']))
        if (data['issuer_id'], data['ticker'], data['period_end'], data['scope']) != (str(issuer_id), ticker.upper(), end, scope):
            return None
        return {**data, 'source_version': row['id'], 'verification_status': 'verified'}
    finally:
        c.close()
