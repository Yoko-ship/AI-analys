"""Bounded, read-only PostgreSQL observations without personal data in the ledger."""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from urllib.parse import urlparse

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from . import store as s
from .errors import MarketingError
from .permissions import TASHKENT, timestamp

BATCH = 500


def _team_emails():
    from identity.users import _admin_emails
    from admin_control import store as control_store
    from admin_control.service import CAPABILITIES
    configured = json.loads(os.getenv('ADMIN_ROLES', '{}'))
    if not isinstance(configured, dict):
        raise ValueError('Invalid administrative role configuration')
    emails = _admin_emails() | {email.strip().lower() for email, role in configured.items()
                               if isinstance(role, str) and role in {*CAPABILITIES, 'disabled'}}
    # Keep known team members internal after access revocation. Losing access
    # must not retrospectively turn their own tests into customer acquisition.
    with control_store.connection() as c:
        rows = c.execute("SELECT id FROM control_resources WHERE environment=? AND collection='access' LIMIT 10001",
                         (control_store.environment(),)).fetchall()
    if len(rows) > 10000:
        raise ValueError('Administrative roster exceeds the read limit')
    return sorted(emails | {row['id'].strip().lower() for row in rows})


def _identity():
    try:
        raw = os.environ['MARKETING_ANALYTICS_ID_KEY'].strip()
        key = base64.b64decode(raw, altchars=b'-_', validate=True)
        if len(key) != 32:
            raise ValueError()
        dsn = os.environ['DATABASE_URL'].strip()
        if not dsn:
            raise ValueError()
        info = conninfo_to_dict(dsn)
        source = [info.get('host', ''), info.get('port', '5432'), info.get('dbname', ''), os.getenv('DATABASE_SCHEMA', 'public')]
        return key, source
    except (KeyError, ValueError, psycopg.Error):
        raise MarketingError('WEBSITE_SETUP_REQUIRED', 'Настройте базу сайта и приватный ключ идентификаторов аналитики на сервере.') from None


def binding():
    key, source = _identity()
    return hmac.new(key, s.encode(['website-v1', source]).encode(), hashlib.sha256).hexdigest()


def ready():
    try:
        binding()
        return True
    except MarketingError:
        return False


def _subject(kind, *parts):
    key, source = _identity()
    digest = hmac.new(key, s.encode([source, kind, parts]).encode(), hashlib.sha256).hexdigest()
    return f'ws_{kind}_{digest}'


def _channel(source, medium, referrer):
    names = {'telegram': 'telegram', 'tg': 'telegram', 't.me': 'telegram', 'facebook': 'facebook', 'fb': 'facebook',
             'instagram': 'instagram', 'ig': 'instagram', 'linkedin': 'linkedin', 'google': 'google', 'yandex': 'yandex'}
    source = (source or '').strip().lower()
    if source:
        channel = names.get(source, 'other_campaign')
    else:
        try:
            host = (urlparse(referrer or '').hostname or '').lower().removeprefix('www.')
        except ValueError:
            host = ''
        channel = next((name for domain, name in [('t.me', 'telegram'), ('telegram.org', 'telegram'), ('facebook.com', 'facebook'),
                       ('instagram.com', 'instagram'), ('linkedin.com', 'linkedin'), ('google.com', 'google'), ('yandex.ru', 'yandex')]
                        if host == domain or host.endswith('.' + domain)), None)
        channel = channel or ('direct' if not host or host in {'uzstock.uz', 'www.uzstock.uz'} else 'referral')
    promotion = 'paid' if (medium or '').strip().lower() in {'paid', 'cpc', 'ppc', 'paid_social', 'display'} else 'organic'
    return channel, promotion


def _event(cfg, kind, subject, at, internal=False, **extra):
    return {'id': f'website:{kind}:{subject}', 'kind': kind, 'subject_id': subject, 'at': at.astimezone(timezone.utc).isoformat(),
            'source': 'uzstock_website', 'dataset': cfg['data']['dataset'], 'confirmed': True,
            'traffic': 'internal' if internal else 'external', **extra}


def _accounts(c, cfg, job, start, cut, admins):
    rows = c.execute('''SELECT id, registration_started_at, registration_completed_at,
        lower(email) = ANY(%s) AS internal FROM web_users WHERE id > %s
        AND ((registration_started_at >= %s AND registration_started_at <= %s)
          OR (registration_completed_at >= %s AND registration_completed_at <= %s))
        ORDER BY id LIMIT %s''', (admins, job['cursor'], start, cut, start, cut, BATCH + 1)).fetchall()
    selected, events = rows[:BATCH], []
    for row in selected:
        subject = _subject('u', row['id'])
        for kind, column in [('registration_started', 'registration_started_at'), ('registration', 'registration_completed_at')]:
            at = row[column]
            if at and start <= at <= cut:
                events.append(_event(cfg, kind, subject, at, row['internal']))
    legacy = c.execute('SELECT count(*) AS n FROM web_users WHERE registration_started_at IS NULL AND registration_completed_at IS NULL').fetchone()['n']
    return {'events': events, 'links': [], 'cursor': selected[-1]['id'] if selected else job['cursor'],
            'done': len(rows) <= BATCH, 'stats': {'observed_rows': len(selected), 'legacy_undated': legacy}}


def _web(c, cfg, job, start, cut, admins):
    rows = c.execute('''SELECT id, visitor_id, session_id FROM web_events
        WHERE id > %s AND ts >= %s AND ts <= %s ORDER BY id LIMIT %s''',
        (job['cursor'], start, cut, BATCH + 1)).fetchall()
    from . import website_sessions
    selected = rows[:BATCH]
    pairs = {(row['visitor_id'], row['session_id']) for row in selected}
    contexts = website_sessions.context(c, pairs, cut, admins)
    events = []
    if pairs:
        visitors, sessions = map(list, zip(*sorted(pairs)))
        first_pages = c.execute("""WITH selected AS (SELECT * FROM unnest(%s::text[],%s::text[]) AS t(visitor_id,session_id))
            SELECT DISTINCT ON(e.visitor_id,e.session_id) e.visitor_id,e.session_id,e.ts,e.utm_source,e.utm_medium,e.referrer
            FROM web_events e JOIN selected k USING(visitor_id,session_id) WHERE e.ts<=%s AND e.event='pageview'
            ORDER BY e.visitor_id,e.session_id,e.ts,e.id""", (visitors, sessions, cut)).fetchall()
        for row in first_pages:
            subject = _subject('s', row['visitor_id'], row['session_id'])
            channel, promotion = _channel(row['utm_source'], row['utm_medium'], row['referrer'])
            if start <= row['ts'] <= cut:
                internal = contexts[(row['visitor_id'], row['session_id'])]['internal']
                events.append(_event(cfg, 'visit', subject, row['ts'], internal, channel=channel, promotion=promotion))
    return {'events': events, 'links': website_sessions.links(cfg, contexts, _subject),
            'cursor': selected[-1]['id'] if selected else job['cursor'], 'done': len(rows) <= BATCH,
            'stats': {'observed_rows': len(selected)}}


def read_page(cfg, job):
    if binding() != cfg['binding']:
        raise MarketingError('WEBSITE_SOURCE_CHANGED', 'База сайта или ключ идентификаторов изменились. Восстановите прежнюю настройку.')
    start = datetime.combine(datetime.fromisoformat(cfg['data']['starts_on']).date(), datetime.min.time(), TASHKENT)
    cut = timestamp(job['cutoff'])
    admins = _team_emails()
    with psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=5, row_factory=dict_row) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        c.execute("SET LOCAL statement_timeout = '10s'")
        c.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(os.getenv('DATABASE_SCHEMA', 'public'))))
        from .website_sessions import actions
        return {'accounts': _accounts, 'web': _web, 'actions': actions}[job['stage']](c, cfg, job, start, cut, admins)
