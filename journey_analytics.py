"""Anonymous visit journeys. Numeric event references never expose browser tokens."""
from datetime import datetime, timezone

from analytics_controls import public_path
import web_analytics as wa

_VISIBLE = "(event IN ('pageview','ui_click') OR (event LIKE 'feature_%%' AND tracking_version<2))"


def _snapshot(conn, through):
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    wa._scope(conn)
    maximum = conn.execute('SELECT coalesce(max(id),0) n FROM ev').fetchone()['n']
    return min(int(through), maximum) if through is not None else maximum


def _sessions(conn, through, since=None, anchor=None):
    condition, args = ('ts >= %s', [since]) if anchor is None else ('id = %s', [anchor])
    conn.execute(f"""
        CREATE TEMP TABLE journey_events ON COMMIT DROP AS
        WITH candidates AS (SELECT DISTINCT visitor_id,session_id FROM ev WHERE id<=%s AND {condition})
        SELECT e.* FROM ev e JOIN candidates c USING(visitor_id,session_id) WHERE e.id<=%s
    """, [through, *args, through])
    conn.execute(f"""
        CREATE TEMP TABLE journey_sessions ON COMMIT DROP AS
        SELECT visitor_id,session_id,min(id) id,max(id) cursor,min(ts) started,max(ts) last_seen,
            count(*) FILTER(WHERE event='pageview') pageviews,
            count(*) FILTER(WHERE event='ui_click') clicks,
            bool_or(tracking_version>=2 AND event IN ('pageview','ui_click')) measured,
            (array_agg(path ORDER BY id DESC) FILTER(WHERE {_VISIBLE}))[1] last_path,
            (array_agg(referrer ORDER BY id) FILTER(WHERE event='pageview'))[1] referrer,
            (array_agg(utm_source ORDER BY id) FILTER(WHERE event='pageview'))[1] utm_source
        FROM journey_events GROUP BY visitor_id,session_id
        HAVING count(*) FILTER(WHERE {_VISIBLE})>0
    """)


def _session(row):
    host = wa.referrer_host(row['referrer'] or '')
    return {key: row[key] for key in ('id','started','last_seen','pageviews','clicks','measured')} | {
        'last_path': public_path(row['last_path']),
        'source': row['utm_source'] or (host if wa.classify_referrer(row['referrer'] or '') != 'direct' else None) or 'direct',
    }


def _event(row):
    return {'id': row['id'], 'at': row['ts'],
            'kind': 'click' if row['event']=='ui_click' else 'pageview' if row['event']=='pageview' else 'feature',
            'path': public_path(row['path']), 'ticker': row['ticker'],
            'control_id': row['control_id'], 'control_value': row['control_value'],
            'target_path': public_path(row['target_path']),
            'feature': row['event'][8:] if row['event'].startswith('feature_') else None}


def journeys_report(days=7, *, limit=50, before=None, through=None):
    if not wa._available():
        return {'ok': False, 'reason': 'no database'}
    days, limit = max(1,min(int(days),90)), max(1,min(int(limit),100))
    with wa._conn() as conn:
        through = _snapshot(conn, through)
        _sessions(conn, through, wa._day_start(datetime.now(timezone.utc),days-1))
        totals = conn.execute("SELECT count(*) sessions, coalesce(sum(clicks),0) clicks, coalesce(sum(pageviews),0) pageviews, count(*) FILTER(WHERE measured) click_sessions FROM journey_sessions").fetchone()
        controls = conn.execute("""
            WITH per_visit AS (
                SELECT control_id,control_value,visitor_id,session_id,count(*) clicks FROM journey_events
                WHERE event='ui_click' GROUP BY control_id,control_value,visitor_id,session_id
            ) SELECT control_id,control_value,sum(clicks) clicks,count(*) sessions,
                count(DISTINCT visitor_id) visitors,count(*) FILTER(WHERE clicks>1) repeated_sessions
              FROM per_visit GROUP BY control_id,control_value ORDER BY clicks DESC,control_id,control_value LIMIT 50
        """).fetchall()
        last = conn.execute(f"""
            WITH last_events AS (SELECT DISTINCT ON(visitor_id,session_id) * FROM journey_events
                WHERE {_VISIBLE} ORDER BY visitor_id,session_id,id DESC)
            SELECT event,control_id,control_value,path,count(*) sessions FROM last_events
            GROUP BY event,control_id,control_value,path ORDER BY sessions DESC,path LIMIT 20
        """).fetchall()
        rows = conn.execute('SELECT * FROM journey_sessions WHERE (%s::bigint IS NULL OR cursor<%s) ORDER BY cursor DESC LIMIT %s', (before,before,limit+1)).fetchall()
    return {'ok': True,'days':days,'through':through,
            'totals': {k:totals[k] for k in ('sessions','clicks','pageviews')},
            'coverage': {'click_sessions':totals['click_sessions']}, 'controls':controls,
            'last_actions': [{'kind':'click' if r['event']=='ui_click' else 'pageview' if r['event']=='pageview' else 'feature',
                              'control_id':r['control_id'],'control_value':r['control_value'],
                              'path':public_path(r['path']),'sessions':r['sessions']} for r in last],
            'sessions': [_session(r) for r in rows[:limit]],
            'next_before': rows[limit-1]['cursor'] if len(rows)>limit else None}


def session_journey(anchor, *, through=None, after=0, limit=100):
    if not wa._available():
        return None
    limit=max(1,min(int(limit),200))
    with wa._conn() as conn:
        through=_snapshot(conn,through)
        _sessions(conn,through,anchor=anchor)
        session=conn.execute('SELECT * FROM journey_sessions').fetchone()
        if not session:
            return None
        rows=conn.execute(f'SELECT * FROM journey_events WHERE id>%s AND {_VISIBLE} ORDER BY id LIMIT %s',(after,limit+1)).fetchall()
    return {'ok':True,'through':through,'session':_session(session),
            'events':[_event(r) for r in rows[:limit]],
            'next_after':rows[limit-1]['id'] if len(rows)>limit else None}
