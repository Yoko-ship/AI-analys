"""Browser-source fixtures; optional real, strictly local PostgreSQL integration."""
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import uuid


def prepare(request, database):
    path = Path(database).with_suffix('.website-fixture.json')
    method = request['method']
    if method in {'WEBSITE_CONFIGURE', 'WEBSITE_ERROR', 'WEBSITE_RECOVER'}:
        data = json.loads(path.read_text()) if path.exists() else {'at': datetime.now(timezone.utc).isoformat()}
        if 'reader' not in data:
            data['reader'] = 'postgres' if os.getenv('MARKETING_BROWSER_POSTGRES_URL') else 'fixture'
            if data['reader'] == 'postgres':
                data['schema'] = 'qa_mkt_browser_' + uuid.uuid4().hex
                _seed(data)
        data['error'] = method == 'WEBSITE_ERROR'
        path.write_text(json.dumps(data), encoding='utf-8')
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    from marketing import website_source
    os.environ['MARKETING_ANALYTICS_ID_KEY'] = base64.urlsafe_b64encode(b'w' * 32).decode()
    os.environ['DATABASE_URL'] = _dsn(data) if data['reader'] == 'postgres' else 'postgresql://synthetic:browser-private-password@127.0.0.1:1/browser_fixture'
    os.environ['DATABASE_SCHEMA'] = data.get('schema', 'public')
    os.environ['ADMIN_EMAILS'] = ''
    os.environ['ADMIN_ROLES'] = '{}'
    real_read = website_source.read_page
    def read(cfg, job):
        if data['error']:
            raise RuntimeError('browser-private-password must stay private')
        if data['reader'] == 'postgres':
            return real_read(cfg, job)
        at = datetime.fromisoformat(data['at'])
        common = {'source': 'uzstock_website', 'dataset': cfg['data']['dataset'], 'confirmed': True}
        events = [{**common, 'id': 'website:visit:browser', 'kind': 'visit', 'subject_id': 'ws_s_browser',
                   'at': (at - timedelta(minutes=20)).isoformat(), 'channel': 'telegram'}] if job['stage'] == 'web' else [
            {**common, 'id': 'website:' + kind + ':browser', 'kind': kind, 'subject_id': 'ws_u_browser',
             'at': (at - timedelta(minutes=minute)).isoformat()} for kind, minute in [('registration_started', 15), ('registration', 10)]]
        if job['stage'] == 'actions':
            events = []
        links = [{'dataset': cfg['data']['dataset'], 'subject_id': 'ws_s_browser', 'user_id': 'ws_u_browser',
                  'observed_at': (at - timedelta(minutes=5)).isoformat()}] if job['stage'] == 'web' else []
        return {'events': events, 'links': links, 'cursor': 3, 'done': True, 'stats': {'observed_rows': 3, 'legacy_undated': 2}}
    website_source.read_page = read
    if method == 'WEBSITE_CLEANUP' and data['reader'] == 'postgres':
        import psycopg
        from psycopg import sql
        with psycopg.connect(_dsn(data), autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(data['schema'])))
    return data['reader']


def _dsn(data):
    import re
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    dsn = os.environ['MARKETING_BROWSER_POSTGRES_URL']
    assert conninfo_to_dict(dsn).get('host') in {'localhost', '127.0.0.1', '::1'}
    assert re.fullmatch(r'qa_mkt_browser_[0-9a-f]{32}', data['schema'])
    return make_conninfo(dsn, options='-c search_path=' + data['schema'])


def _seed(data):
    import psycopg
    from psycopg import sql
    dsn = _dsn(data)
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(data['schema'])))
    from web_auth import WebAuthStore
    import web_analytics
    WebAuthStore(dsn)
    web_analytics.DATABASE_URL = dsn
    web_analytics.init_db()
    at = datetime.fromisoformat(data['at'])
    with psycopg.connect(dsn) as c:
        uid = c.execute('''INSERT INTO web_users(email,password_hash,created_at,registration_started_at,registration_completed_at)
            VALUES (%s,%s,%s,%s,%s) RETURNING id''', ('reader@example.test', 'synthetic-test-only', at - timedelta(minutes=15),
                                                   at - timedelta(minutes=15), at - timedelta(minutes=10))).fetchone()[0]
        for i in range(2):
            c.execute('INSERT INTO web_users(email,password_hash) VALUES (%s,%s)', (f'undated-{i}@example.test', 'synthetic-test-only'))
        for minutes, kind, user in [(20, 'pageview', None), (15, 'feature_reports', None), (5, 'pageview', uid)]:
            c.execute('''INSERT INTO web_events(ts,visitor_id,session_id,user_id,event,path,utm_source)
                         VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                      (at - timedelta(minutes=minutes), 'browser-visitor', 'browser-session', user, kind, '/company/HMKB', 'telegram'))
