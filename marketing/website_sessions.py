"""Session context shared by visit and successful-action observations."""
from datetime import timezone


def context(c, pairs, cut, admins):
    if not pairs:
        return {}
    visitors, sessions = map(list, zip(*sorted(pairs)))
    rows = c.execute('''WITH selected AS (SELECT * FROM unnest(%s::text[],%s::text[]) AS t(visitor_id,session_id)),
        observations AS (
            SELECT e.visitor_id,e.session_id,e.user_id,e.ts,e.internal FROM web_events e
            WHERE e.visitor_id=ANY(%s) AND e.ts<=%s
            UNION ALL
            SELECT visitor_id,session_id,user_id,received_at,traffic='internal' FROM web_product_events
            WHERE visitor_id=ANY(%s) AND observed_at<=%s AND received_at<=%s),
        team AS (SELECT DISTINCT o.visitor_id FROM observations o LEFT JOIN web_users u ON u.id=o.user_id
                 WHERE o.internal OR lower(u.email)=ANY(%s)),
        identities AS (
            SELECT o.visitor_id,o.session_id,min(o.user_id) AS min_user,max(o.user_id) AS max_user,max(o.ts) AS observed_at
            FROM observations o JOIN selected k USING(visitor_id,session_id) GROUP BY o.visitor_id,o.session_id)
        SELECT i.*,t.visitor_id IS NOT NULL AS internal FROM identities i LEFT JOIN team t USING(visitor_id)''',
        (visitors, sessions, visitors, cut, visitors, cut, cut, admins)).fetchall()
    return {(row['visitor_id'], row['session_id']): row for row in rows}


def links(cfg, contexts, subject):
    return [{'dataset': cfg['data']['dataset'], 'subject_id': subject('s', visitor, session),
             'user_id': subject('u', row['min_user']) if row['min_user'] is not None and row['min_user'] == row['max_user'] else None,
             'observed_at': row['observed_at'].astimezone(timezone.utc).isoformat()}
            for (visitor, session), row in sorted(contexts.items())]


def actions(c, cfg, job, start, cut, admins):
    from product_events import Action
    from . import publication_links, store as s
    from .website_source import BATCH, _event, _subject
    rows = c.execute('''SELECT id,event_id,observed_at,visitor_id,session_id,user_id,traffic,payload,object_id
        FROM web_product_events WHERE id>%s AND observed_at>=%s AND observed_at<=%s AND received_at<=%s
        ORDER BY id LIMIT %s''', (job['cursor'], start, cut, cut, BATCH+1)).fetchall()
    selected = rows[:BATCH]
    # One bounded workspace read for the batch. A receipt can wait for later
    # provider visibility; the next full sweep reconsiders it with the same ID.
    publications = {}
    if any(row['payload']['kind'] == 'publication_visit' for row in selected):
        with s.connection() as workspace:
            for row in selected:
                if row['payload']['kind'] == 'publication_visit':
                    action = Action.model_validate(row['payload'])
                    publications[row['id']] = publication_links.resolve(workspace, action.publication_token,
                        action.route_fingerprint, row['observed_at'], cut, cfg['data']['dataset'])
    contexts = context(c, {(row['visitor_id'], row['session_id']) for row in selected}, cut, admins)
    events = []
    for row in selected:
        action = Action.model_validate(row['payload'])
        if action.object_id() != row['object_id']:
            raise ValueError('Receipt object differs from its typed observation')
        if action.kind == 'publication_visit' and not publications.get(row['id']):
            continue
        identity = _subject('u', row['user_id']) if row['user_id'] is not None else _subject('s', row['visitor_id'], row['session_id'])
        internal = contexts[(row['visitor_id'], row['session_id'])]['internal']
        event = _event(cfg, action.kind, identity, row['observed_at'], internal, object_id=row['object_id'])
        event['id'] = 'website:action:' + str(row['event_id'])
        if action.kind == 'publication_visit':
            event.update(publications[row['id']])
            event['object_id'] = event['publication_id']
        if row['traffic'] == 'automated':
            event['traffic'] = 'automated'
        events.append(event)
    return {'events': events, 'links': links(cfg, contexts, _subject), 'cursor': selected[-1]['id'] if selected else job['cursor'],
            'done': len(rows)<=BATCH, 'stats': {'observed_rows': len(selected)}}
