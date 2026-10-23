"""Account-owned comparison selections; financial figures are always read fresh."""
from __future__ import annotations

import hashlib
import json
import re

MAX_SAVED = 50


class ComparisonChanged(ValueError):
    pass


def snapshot_key(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest() if snapshot else 'none'


def clean(payload):
    name = str(payload.get('name') or '').strip()
    if not name or len(name) > 80:
        raise ValueError('Comparison name must contain 1–80 characters')
    tokens = payload.get('tickers')
    if not isinstance(tokens, list) or not 2 <= len(tokens) <= 4:
        raise ValueError('Choose two to four companies')
    if any(not isinstance(t, str) or not re.fullmatch(r'[A-Z0-9]{2,16}', t.strip().upper()) for t in tokens):
        raise ValueError('Invalid ticker')
    tickers = list(dict.fromkeys(t.strip().upper() for t in tokens))
    if len(tickers) < 2:
        raise ValueError('Choose two to four distinct companies')
    selection = {'tickers': tickers}
    for key, default, allowed in [('standard', 'NSBU', {'NSBU', 'IFRS'}),
                                  ('scope', 'separate', {'separate', 'consolidated'}),
                                  ('unit', 'billion', {'billion', 'million'})]:
        value = payload.get(key, default)
        if not isinstance(value, str) or value not in allowed:
            raise ValueError('Invalid ' + key)
        selection[key] = value
    period = payload.get('period', 'latest')
    if not isinstance(period, str) or (period != 'latest' and not re.fullmatch(r'20\d{2}(?:Q[1-4])?', period)):
        raise ValueError('Invalid reporting period')
    selection['period'] = period
    return name, selection


def public(row):
    return {'id': str(row['id']), 'name': row['name'], 'selection': dict(row['selection']),
            'created_at': row['created_at'].isoformat(), 'updated_at': row['updated_at'].isoformat(),
            'has_baseline': bool(row.get('has_baseline') or row.get('seen_snapshot')),
            'last_seen_at': row['seen_at'].isoformat() if row.get('seen_at') else None}


class Comparisons:
    def __init__(self, database):
        self.database = database

    def list(self, user_id):
        with self.database.connect() as conn:
            rows = conn.execute('''SELECT id, name, selection, created_at, updated_at, seen_at,
                seen_snapshot IS NOT NULL AS has_baseline
                FROM web_saved_comparisons WHERE user_id = %s
                ORDER BY updated_at DESC, id DESC LIMIT 50''', (user_id,)).fetchall()
        return [public(row) for row in rows]

    def save(self, user_id, payload, initial_snapshot=None):
        name, selection = clean(payload)
        encoded = json.dumps(selection, sort_keys=True, separators=(',', ':'))
        signature = hashlib.sha256(encoded.encode()).hexdigest()
        with self.database.connect() as conn:
            # Serialize one account's writes so concurrent devices cannot exceed
            # the limit. Same-selection saves rename/update, without duplication.
            owner = conn.execute('SELECT id FROM web_users WHERE id = %s FOR UPDATE', (user_id,)).fetchone()
            if not owner:
                raise ValueError('Account not found')
            existing = conn.execute('SELECT id FROM web_saved_comparisons WHERE user_id = %s AND signature = %s',
                                    (user_id, signature)).fetchone()
            count = conn.execute('SELECT COUNT(*) AS n FROM web_saved_comparisons WHERE user_id = %s', (user_id,)).fetchone()['n']
            if not existing and count >= MAX_SAVED:
                raise ValueError('You can save up to 50 comparisons; remove one before saving another')
            row = conn.execute('''INSERT INTO web_saved_comparisons (user_id, name, selection, signature, seen_snapshot, seen_at)
                VALUES (%s, %s, %s::jsonb, %s, %s::jsonb, CASE WHEN %s THEN NOW() ELSE NULL END)
                ON CONFLICT (user_id, signature) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()
                RETURNING id, name, selection, created_at, updated_at, seen_snapshot, seen_at''',
                (user_id, name, encoded, signature, json.dumps(initial_snapshot) if initial_snapshot else None, bool(initial_snapshot))).fetchone()
        return public(row)

    def get(self, user_id, comparison_id):
        with self.database.connect() as conn:
            return conn.execute('''SELECT id, name, selection, seen_snapshot, seen_at
                FROM web_saved_comparisons WHERE id = %s AND user_id = %s''', (comparison_id, user_id)).fetchone()

    def mark_seen(self, user_id, comparison_id, snapshot, expected_baseline):
        with self.database.connect() as conn:
            row = conn.execute('''SELECT seen_snapshot, seen_at FROM web_saved_comparisons
                WHERE id = %s AND user_id = %s FOR UPDATE''', (comparison_id, user_id)).fetchone()
            if not row: return None
            existing = snapshot_key(row['seen_snapshot'])
            if existing == snapshot_key(snapshot):
                viewed = conn.execute('''UPDATE web_saved_comparisons SET seen_at = NOW()
                    WHERE id = %s AND user_id = %s RETURNING seen_at''', (comparison_id, user_id)).fetchone()
                return {'last_seen_at': viewed['seen_at'].isoformat()}
            if existing != expected_baseline:
                raise ComparisonChanged('This comparison was viewed on another device; refresh the updates')
            row = conn.execute('''UPDATE web_saved_comparisons SET seen_snapshot = %s::jsonb, seen_at = NOW()
                WHERE id = %s AND user_id = %s RETURNING seen_at''',
                (json.dumps(snapshot), comparison_id, user_id)).fetchone()
        return {'last_seen_at': row['seen_at'].isoformat()}

    def delete(self, user_id, comparison_id):
        with self.database.connect() as conn:
            cursor = conn.execute('DELETE FROM web_saved_comparisons WHERE id = %s AND user_id = %s',
                                  (comparison_id, user_id))
        return cursor.rowcount > 0
