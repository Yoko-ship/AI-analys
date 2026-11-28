"""Owner opt-in and fenced, resumable website observation sweeps."""
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import Field

from . import store as s, website_ledger, website_source
from .errors import MarketingError, require_owner
from .models import Input
from .permissions import TASHKENT, timestamp

ACTOR = website_ledger.ACTOR


class Settings(Input):
    enabled: bool = False
    dataset: Literal['production', 'test'] = 'production'
    starts_on: date
    interval_minutes: int = Field(default=15, ge=5, le=1440)


def settings(c):
    return s.get(c, 'settings', 'website', required=False) or {'id': 'website', 'version': 0,
        'data': {'enabled': False, 'dataset': 'production', 'starts_on': None, 'interval_minutes': 15}}


def status(c):
    saved = settings(c)
    runtime = s.get(c, 'runtime', 'website', required=False)
    public_runtime = {key: value for key, value in (runtime or {}).items()
                      if key not in {'claim', 'claim_until', 'config_version', 'cursor'}}
    return {'settings': {key: value for key, value in saved.items() if key != 'binding'},
            'setup_ready': website_source.ready(), 'dataset_locked': bool(saved.get('binding')), 'runtime': public_runtime or None}


def configure(actor, data, expected_version, *, now=None):
    require_owner(actor)
    now = now or datetime.now(timezone.utc)
    value = Settings.model_validate(data).model_dump(mode='json')
    if date.fromisoformat(value['starts_on']) > now.astimezone(TASHKENT).date():
        raise MarketingError('INVALID_PERIOD', 'Дата начала не может быть в будущем.', 422)
    with s.connection(write=True) as c:
        old = settings(c)
        binding = old.get('binding')
        if binding and old['data']['dataset'] != value['dataset']:
            raise MarketingError('WEBSITE_DATASET_FIXED', 'Среда источника закреплена. Нельзя переносить его события между тестовой и рабочей базой.')
        if value['enabled']:
            current = website_source.binding()
            if binding and binding != current:
                raise MarketingError('WEBSITE_SOURCE_CHANGED', 'Восстановите прежнюю базу сайта и ключ идентификаторов.')
            binding = current
        saved = s.put(c, 'settings', {'id': 'website', 'data': value, 'binding': binding}, actor=actor,
                      action='website_configured', expected_version=expected_version)
        previous = s.get(c, 'runtime', 'website', required=False)
        s.put(c, 'runtime', {'id': 'website', 'status': 'queued' if value['enabled'] else 'disabled', 'next_at': now.isoformat()},
              actor=actor, action='website_configuration_changed', expected_version=previous['version'] if previous else 0)
        return saved


def _claim(now, force, expected_version=None):
    with s.connection(write=True) as c:
        cfg = settings(c)
        if expected_version is not None and cfg['version'] != expected_version:
            raise MarketingError('VERSION_CONFLICT', 'Настройка источника изменилась. Обновите страницу.')
        pause = s.get(c, 'settings', 'pause', required=False) or {}
        if not cfg['data']['enabled'] or pause.get('processing'):
            return None
        old = s.get(c, 'runtime', 'website', required=False)
        if old and old.get('claim_until') and timestamp(old['claim_until']) > now:
            return None
        if not force and old and timestamp(old['next_at']) > now:
            return None
        continuing = old and old.get('stage') and old.get('status') != 'waiting'
        value = {**(old or {}), 'id': 'website', 'status': 'running', 'reason': '', 'next_at': now.isoformat(),
                 'claim': s.uid('website'), 'claim_until': (now + timedelta(seconds=90)).isoformat(), 'config_version': cfg['version']}
        if not continuing:
            value.update(stage='accounts', cursor=0, cutoff=now.isoformat(), stats={}, imported=0, revised=0, identity_updates=0)
        job = s.put(c, 'runtime', value, actor=ACTOR, action='website_read_claimed', expected_version=old['version'] if old else 0)
        return cfg, job


def _coverage(c, cfg, job, now, status):
    cut = timestamp(job['cutoff'])
    row = {'dataset': cfg['data']['dataset'], 'categories': ['visits', 'registrations', 'activity'],
           'starts_on': cfg['data']['starts_on'], 'ends_on': (cut.astimezone(TASHKENT).date() + timedelta(days=1)).isoformat(),
           'through': cut.isoformat(), 'history_complete': False, 'status': status,
           'reference': ('Наблюдения базы UZStock. Буфер посещений может терять события; старые регистрации без дат не восстановлены. '
                         'Успешные действия — наблюдения интерфейса, которые браузер может не доставить. Поиск ограничен загруженными новостями; оплаты не подключены.' if status == 'incomplete' else
                         'База сайта временно недоступна; предыдущие наблюдения сохранены.')}
    key = s.digest([row, now.isoformat()])
    if not s.get(c, 'coverage', key, required=False):
        s.put(c, 'coverage', {'id': key, 'coverage': row, 'received_at': now.isoformat()},
              actor=ACTOR, action='website_coverage_observed', expected_version=0)


def _finish(cfg, job, page, reason, now):
    with s.connection(write=True) as c:
        current = s.get(c, 'runtime', 'website', required=False)
        latest = settings(c)
        if not current or current.get('claim') != job['claim'] or latest['version'] != cfg['version']:
            return False
        value = {**current, 'claim': None, 'claim_until': None}
        if (s.get(c, 'settings', 'pause', required=False) or {}).get('processing'):
            value.update(status='queued', next_at=now.isoformat())
        else:
            try:
                if website_source.binding() != cfg['binding']:
                    raise MarketingError('WEBSITE_SOURCE_CHANGED', 'База сайта или ключ изменились. Восстановите прежнюю настройку.')
            except MarketingError as exc:
                page, reason = None, str(exc)
            if page is None:
                value.update(status='error', reason=reason, next_at=(now + timedelta(minutes=cfg['data']['interval_minutes'])).isoformat())
                _coverage(c, cfg, job, now, 'unavailable')
            else:
                counts = website_ledger.ingest(c, page['events'], page['links'], now)
                for key, count in counts.items():
                    value[key] = value.get(key, 0) + count
                value.update(cursor=page['cursor'], status='queued', next_at=now.isoformat(), last_success_at=now.isoformat())
                stats = value.get('stats', {})
                value['stats'] = {**stats, 'observed_rows': stats.get('observed_rows', 0) + page['stats']['observed_rows']}
                if 'legacy_undated' in page['stats']:
                    value['stats']['legacy_undated'] = page['stats']['legacy_undated']
                if page['done']:
                    if job['stage'] == 'accounts':
                        value.update(stage='web', cursor=0)
                    elif job['stage'] == 'web':
                        value.update(stage='actions', cursor=0)
                    else:
                        value.update(status='waiting', cycle_completed_at=now.isoformat(),
                                     next_at=(now + timedelta(minutes=cfg['data']['interval_minutes'])).isoformat())
                _coverage(c, cfg, job, now, 'incomplete')
        s.put(c, 'runtime', value, actor=ACTOR, action='website_read_finished', expected_version=current['version'])
        return True


def run_one(now=None, *, force=False, expected_version=None):
    supplied_now = now
    now = now or datetime.now(timezone.utc)
    claimed = _claim(now, force, expected_version)
    if not claimed:
        return False
    cfg, job = claimed
    try:
        page = website_source.read_page(cfg, job)
        if (not isinstance(page['done'], bool) or not isinstance(page['cursor'], int) or page['cursor'] < job['cursor']
                or len(page['events']) > 2 * website_source.BATCH or len(page['links']) > website_source.BATCH
                or any(row['dataset'] != cfg['data']['dataset'] for row in [*page['events'], *page['links']])
                or not isinstance(page['stats']['observed_rows'], int) or page['stats']['observed_rows'] < 0):
            raise ValueError('Invalid website batch')
        reason = ''
    except Exception:
        page, reason = None, 'База сайта недоступна или её схема не готова. Проверьте подключение; личные данные и адрес базы в журнал не записаны.'
    received_at = supplied_now or datetime.now(timezone.utc)
    try:
        return _finish(cfg, job, page, reason, received_at)
    except Exception:
        # A rejected batch rolls back atomically, including all source revisions.
        # Record a safe failure separately without advancing its cursor.
        return _finish(cfg, job, None, 'Пакет сайта не прошёл проверку. События не добавлены; предыдущие данные сохранены.', received_at)
