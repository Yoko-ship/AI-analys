"""The connected Telegram channel supplies the scope for routine news work."""
from datetime import timedelta

from . import channels, permissions, sources, telegram_schedule, store as s
from .errors import MarketingError, require_owner
from .models import Account
from .permissions import TASHKENT, timestamp

ACTOR = {'id': 'coordinator', 'role': 'coordinator'}
SOURCE_ID = 'telegram-uzstock-news'


def connect(actor, channel, expected_version, now, account_id=None):
    require_owner(actor)
    with s.connection() as c:
        accounts = [a for a in s.list_items(c, 'account') if a['platform'] == 'telegram']
        previous = s.get(c, 'account', account_id, required=False) if account_id else next(
            (a for a in accounts if a['external_id'] == channel), accounts[0] if len(accounts) == 1 else None)
    if previous and previous['platform'] != 'telegram':
        raise MarketingError('ACCOUNT_PLATFORM', 'Choose a Telegram channel.', 422)
    value = {key: previous[key] for key in Account.model_fields if key in previous} if previous else {
        'platform': 'telegram', 'label': 'Telegram', 'mode': 'automatic',
        'rubrics': ['news'], 'formats': ['post'], 'languages': ['ru']}
    value.update(external_id=channel, automatic_news=True, valid_until=None)
    saved = permissions.save_account(actor, previous['id'] if previous else account_id or 'telegram', value, expected_version)
    return channels.probe(actor, saved['id'], saved['version'], now)


def _connected(c, now):
    if (s.get(c, 'settings', 'pause', required=False) or {}).get('processing'):
        return []
    return [a for a in s.list_items(c, 'account') if a['platform'] == 'telegram'
            and not a['paused'] and 'news' in a['rubrics'] and 'post' in a['formats'] and a['languages']
            and (not a.get('valid_until') or timestamp(a['valid_until']) > now)
            and channels.setup(a, now, c)['ready']]


def upgrade(now):
    changed = False
    with s.connection(write=True) as c:
        for account in _connected(c, now):
            if 'automatic_news' not in account:
                s.put(c, 'account', {**account, 'automatic_news': True, 'valid_until': None},
                      actor=ACTOR, action='telegram_defaults_adopted', expected_version=account['version'])
                changed = True
    return changed


def accounts(c, now):
    return [a for a in _connected(c, now) if a.get('automatic_news')]


def ensure_source(now):
    with s.connection(write=True) as c:
        if not accounts(c, now) or s.get(c, 'source', SOURCE_ID, required=False):
            return False
        value = sources.Source(name='Новости UZStock · Telegram', url='https://uzstock.uz/news', category='uzstock',
            method='internal_news', owner='UZStock', rights='link_and_excerpt', terms_checked_on=now.date(),
            may_store=True, may_display=True, commercial_use=True, frequency_minutes=15,
            restrictions='Собственный краткий пересказ и ссылки. Не копировать полные статьи и фотографии издателей.').model_dump(mode='json')
        s.put(c, 'source', {**value, 'id': SOURCE_ID, 'configuration_digest': s.digest(value), 'enabled': True,
              'status': 'reviewing', 'last_success_at': None, 'last_attempt_at': None,
              'reason': 'Awaiting first collection'}, actor=ACTOR, action='telegram_source_started', expected_version=0)
        return True


def available(c, now):
    source = s.get(c, 'source', SOURCE_ID, required=False)
    if not source or not source['enabled'] or source['status'] != 'connected':
        return []
    return sorted([item for saved in s.list_items(c, 'evidence') if saved['source_id'] == SOURCE_ID
                   and (item := sources.current_evidence(c, saved['id']))
                   and item['status'] in {'candidate', 'verified'}
                   and timedelta(0) <= now - timestamp(item['published_at']) < timedelta(hours=24)
                   and timestamp(item['expires_at']) > now], key=lambda item: item['published_at'], reverse=True)


def assigned(c, account_id, item):
    from . import automation
    event = {'aliases': automation._aliases([item])}
    if automation._assigned(c, event, account_id):
        return True
    return any(task.get('production') and any(t['account_id'] == account_id for t in task['production']['targets'])
               and set(event['aliases']).intersection(automation._aliases(task['evidence']))
               for task in s.list_items(c, 'task'))


def pending(c, account, now):
    return telegram_schedule.plan(c, account, now) is not None


def run_one(now):
    from . import agents, automation
    with s.connection(write=True) as c:
        for account in accounts(c, now):
            if _retry(c, account, now):
                return True
            plan = telegram_schedule.plan(c, account, now)
            if plan is None:
                continue
            due = max(now, plan['not_before'] or now)
            item = next((row for row in available(c, now) if row['status'] == 'verified'
                         and min(timestamp(row['published_at']) + timedelta(hours=24), timestamp(row['expires_at'])) > due
                         and not assigned(c, account['id'], row)), None)
            if not item:
                continue
            language = account['languages'][0]
            scope = {'event_id': item['canonical_event_id'], 'rubric': 'news', 'entity': item['entity'],
                     'period': '', 'destination_url': item['destination_url'], 'mode': 'account',
                     'not_before': plan['not_before'].isoformat() if plan['not_before'] else None,
                     'expires_at': min(plan['expires_at'], timestamp(item['published_at']) + timedelta(hours=24), timestamp(item['expires_at'])).isoformat(),
                     'targets': [{'account_id': account['id'], 'languages': [language], 'primary_language': language, 'format': 'post'}]}
            binding = {'kind': 'telegram', 'account_version': account['version'], 'assigned_at': now.isoformat(),
                       'aliases': automation._aliases([item]), 'priority': 'normal'}
            agents._start_in(c, ACTOR, kind='content', message=(
                'Подготовь короткий Telegram-пост по новости: ' + item['title'] + '. '
                'Объясни значение новости начинающему читателю от редакции UZStock. '
                'В публичном тексте источник — UZStock, ссылка — только выбранная страница UZStock. '
                'Не добавляй название издателя, внешние ссылки, подпись источника или CTA: их оформляет сервер. '
                'Оригинал издателя остаётся внутренним основанием проверки. Не утверждай, что UZStock получил эксклюзив или провёл независимое расследование. '
                'Используй только выбранный пересказ и проверенный фрагмент оригинала. '
                'Не придумывай числа, дату события, прогноз доходности или призыв покупать. '
                'Не называй дату публикации датой события. 80–120 слов, без изображений. '
                'Цель кампании, стратегия и дополнительные настройки для этой обычной новости не нужны.'),
                evidence_ids=[item['id']], production=scope, editorial=binding, assigned_roles=['news', 'copywriter', 'quality'])
            return True
    return False


def _retry(c, account, now):
    from .agents import MAX_ATTEMPTS
    for task in s.list_items(c, 'task', status='error'):
        if ((task.get('editorial') or {}).get('kind') != 'telegram'
                or task['production']['targets'][0]['account_id'] != account['id']
                or task['attempts'] >= MAX_ATTEMPTS
                or timestamp(task['claimed_at']) + timedelta(minutes=2 ** task['attempts']) > now):
            continue
        try:
            guard(c, task, now)
        except MarketingError:
            continue
        s.put(c, 'task', {**task, 'status': 'queued', 'reason': 'Automatic retry from the saved news step'},
              actor=ACTOR, action='telegram_news_retry', expected_version=task['version'])
        return True
    return False


def guard(c, task, now):
    account_id = task['production']['targets'][0]['account_id']
    account = next((a for a in accounts(c, now) if a['id'] == account_id), None)
    if not account or account['version'] != task['editorial']['account_version']:
        raise MarketingError('TELEGRAM_NEWS_CHANGED', 'Telegram channel settings or connection changed; this task is stopped.')
    if (timestamp(task['production']['expires_at']) <= now
            or timestamp(task['editorial']['assigned_at']).astimezone(TASHKENT).date() != now.astimezone(TASHKENT).date()):
        raise MarketingError('TELEGRAM_NEWS_EXPIRED', 'This news item is no longer current.')
    for key, version in task['evidence_versions'].items():
        item = sources.current_evidence(c, key)
        if not item or item['version'] != version or item['status'] != 'verified' or timestamp(item['expires_at']) <= now:
            raise MarketingError('TELEGRAM_NEWS_SOURCE', 'The reviewed source changed or is unavailable.')


def status(c, now):
    enabled = [a for a in s.list_items(c, 'account') if a['platform'] == 'telegram' and a.get('automatic_news')]
    return {'enabled': bool(enabled), 'ready': bool(accounts(c, now)),
            'max_daily': enabled[0].get('news_daily_limit', 2) if enabled else 2}
