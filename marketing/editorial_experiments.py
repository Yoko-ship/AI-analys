"""Immutable organic test designs and owner decisions, without release authority."""
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from . import content, experiment_results, goals, reports, store as s
from .errors import MarketingError, require_owner
from .models import Input
from .permissions import TASHKENT

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]
KPI = Literal['news_open', 'report_open', 'chart_open', 'issuer_open', 'favorite', 'registration']


class Design(Input):
    title: Text
    goal_version: int = Field(ge=1)
    hypothesis: Text
    segment: Text
    reader_question: Text
    tested_variable: Text
    comparison: Text
    control_ids: list[str] = Field(min_length=1, max_length=12)
    variant_ids: list[str] = Field(min_length=1, max_length=12)
    kpi: KPI
    outcome_object_id: str = Field(default='', max_length=200)
    minimum_observations: int = Field(ge=1, le=1_000_000)
    starts_on: date
    ends_on: date
    followup_days: int = Field(ge=1, le=30)
    stop_condition: Text

    @model_validator(mode='after')
    def valid(self):
        ids = self.control_ids + self.variant_ids
        if len(set(ids)) != len(ids) or any(not key.strip() for key in ids):
            raise ValueError('Choose distinct publications for the two arms')
        if not timedelta(0) < self.ends_on-self.starts_on <= timedelta(days=90):
            raise ValueError('Choose an ordered enrollment period of at most 90 days')
        self.outcome_object_id = self.outcome_object_id.strip()
        if (self.kpi == 'registration') != (not self.outcome_object_id):
            raise ValueError('Specify an exact product object except for registration')
        return self


def _current(c, key, version):
    item = s.get(c, 'editorial_experiment', key)
    if item['version'] != version:
        raise MarketingError('EXPERIMENT_CHANGED', 'Эксперимент изменился. Обновите текущую версию.')
    return item


def register(actor, data, *, now):
    require_owner(actor)
    value = Design.model_validate(data).model_dump(mode='json')
    with s.connection(write=True) as c:
        goal = goals.active_goal(c)
        if not goal or goal['version'] != value['goal_version']:
            raise MarketingError('STALE_GOAL', 'Сначала выберите действующую утверждённую цель.')
        if not goal['starts_on'] <= value['starts_on'] < value['ends_on'] <= goal['deadline']:
            raise MarketingError('EXPERIMENT_PERIOD', 'Набор читателей должен укладываться в период цели.', 422)
        candidates = [s.get(c, 'candidate', key) for key in value['control_ids']+value['variant_ids']]
        if (len({(row['account_id'], row['language']) for row in candidates}) != 1
                or any(row['publication_type'] != 'organic' or not row.get('track_visits') for row in candidates)):
            raise MarketingError('EXPERIMENT_PUBLICATIONS', 'Выберите органические публикации одного аккаунта и языка с учётом переходов.', 422)
        account = s.get(c, 'account', candidates[0]['account_id'])
        start = datetime.combine(date.fromisoformat(value['starts_on']), datetime.min.time(), TASHKENT)
        design = {**value, 'dataset': reports.settings(c)['data']['dataset'], 'registered_at': now.isoformat(),
                  'timing': 'prospective' if now <= start else 'retrospective',
                  'account_id': account['id'], 'channel': account['platform'], 'recipient': account['external_id'],
                  'goal': goal, 'creatives': {row['id']: {'title': row['title'], 'version': row['version'],
                      'content_digest': content.content_digest(row)} for row in candidates}}
        return s.put(c, 'editorial_experiment', {'id': s.uid('format_test'), 'title': value['title'],
                     'status': 'registered', 'design': design, 'decision': None}, actor=actor,
                     action='editorial_experiment_registered', expected_version=0)


def evaluate(actor, key, expected_version, *, now):
    require_owner(actor)
    with s.connection(write=True) as c:
        item = _current(c, key, expected_version)
        result = experiment_results.calculate(c, item['design'], now)
        return s.put(c, 'experiment_evaluation', {'id': s.uid('evaluation'), 'experiment_id': key,
                     'design': item['design'], 'result': result, 'status': 'frozen'}, actor=actor,
                     action='experiment_evaluated', expected_version=0)


def decide(actor, key, expected_version, evaluation_id, action, reason):
    require_owner(actor)
    if action not in {'repeat', 'change', 'stop'} or not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 2000:
        raise MarketingError('EXPERIMENT_DECISION', 'Выберите повтор, изменение или остановку и укажите основание.', 422)
    with s.connection(write=True) as c:
        item = _current(c, key, expected_version)
        evaluation = s.get(c, 'experiment_evaluation', evaluation_id)
        if evaluation['experiment_id'] != key or evaluation['design'] != item['design']:
            raise MarketingError('EXPERIMENT_BASIS', 'Решение должно ссылаться на оценку этого дизайна.', 422)
        return s.put(c, 'editorial_experiment', {**item, 'status': 'stopped' if action == 'stop' else 'registered',
                     'decision': {'evaluation_id': evaluation_id, 'action': action, 'reason': reason.strip(),
                                  'at': s.now(), 'actor': actor['id']}}, actor=actor,
                     action='editorial_experiment_decided', expected_version=expected_version)
