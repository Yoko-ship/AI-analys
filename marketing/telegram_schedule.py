"""Reserve daily news slots in Tashkent time; never catch up missed releases."""
from datetime import datetime, time, timedelta

from . import store as s
from .permissions import TASHKENT, timestamp

PREPARE_AHEAD = timedelta(hours=1)
LATE_ALLOWANCE = timedelta(minutes=15)


def plan(c, account, now):
    local = now.astimezone(TASHKENT)
    today = local.date()
    start, end = (datetime.combine(today, time.fromisoformat(account[key]), TASHKENT)
                  for key in ('window_start', 'window_end'))
    tasks = [t for t in s.list_items(c, 'task') if (t.get('editorial') or {}).get('kind') == 'telegram'
             and t['production']['targets'][0]['account_id'] == account['id']
             and timestamp(t['editorial']['assigned_at']).astimezone(TASHKENT).date() == today]
    # A settings edit cancels unsent work, but must not reset today's used quota.
    sent = {item.get('origin_task') for item in s.list_items(c, 'candidate')
            if item['status'] in {'published', 'sending', 'unknown'}}
    reserved = [t for t in tasks if t['editorial']['account_version'] == account['version'] or t['id'] in sent]
    if len(reserved) >= account.get('news_daily_limit', 2):
        return None
    if any(t['status'] in {'queued', 'running', 'waiting_assets'}
           and timestamp(t['production']['expires_at']) > now for t in reserved):
        return None
    times = account.get('news_publish_times', [])
    if not times:
        return {'not_before': None, 'expires_at': end} if start <= local < end else None
    used = {timestamp(t['production']['not_before']) for t in reserved if t['production'].get('not_before')}
    for value in times:
        at = datetime.combine(today, time.fromisoformat(value), TASHKENT)
        expires = min(at + LATE_ALLOWANCE, end)
        if at not in used and at - PREPARE_AHEAD <= now < expires:
            return {'not_before': at, 'expires_at': expires}
    return None
