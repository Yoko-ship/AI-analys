"""Pinned editorial context and conservative checks for unsupported occasion claims.

The vocabulary supplements the exact-version editorial review; it is not a
general proof of natural-language meaning or of a causal research claim.
"""
import re

from . import sources
from .errors import MarketingError
from .permissions import timestamp


def _text(value):
    value = re.sub(r'https?://\S+', '', value).casefold().replace('ё', 'е')
    return re.sub('[‘’ʼʻ`´]', "'", value)


RISKS = {
    'exchange_schedule': ('exchange schedule',
        r'\b(?:бирж\w*|торг\w*)\b[^.!?\n]{0,60}\b(?:закрыт\w*|открыт\w*|работ\w*|начнут\w*|начина\w*|заверш\w*)'
        r'|\b(?:exchange|trading)\b[^.!?\n]{0,50}\b(?:closed?|opens?|begins?|starts?|ends?)\b'
        r'|\b(?:birja|savdo)\b[^.!?\n]{0,50}\b(?:yopiq|ochiq|ishlaydi|ishlamaydi|boshlanadi|tugaydi)\b'),
    'popularity': ('popularity',
        r'\b(?:популяр\w*|все\s+(?:играют|обсуждают)|вирусн\w*|popular\w*|viral|everyone\s+(?:is\s+)?(?:playing|discussing)|mashhur|ommabop|hamma\s+muhokama)\b'),
    'market_effect': ('market effect',
        r'\b(?:вызва\w*|повлия\w*|влия\w*|влиян\w*)\b[^.!?\n]{0,60}\b(?:акци\w*|рын\w*|цен\w*)'
        r'|\b(?:акци\w*|рын\w*|цен\w*)\b[^.!?\n]{0,50}\b(?:из-за|благодаря)\b'
        r'|\b(?:caus\w*|drove|drives?|affect\w*|impact\w*)\b[^.!?\n]{0,60}\b(?:shares?|stocks?|prices?|market)\b'
        r'|\b(?:aksiya|bozor)\b[^.!?\n]{0,50}\b(?:ta\'sir|tufayli)\b'),
}
DISCLAIMERS = (
    r'не\s+(?:доказывает|подтверждает|означает)\s+(?:популярность|влияние\s+на\s+акции|закрытие\s+биржи)',
    r'(?:does\s+not|doesn\'t)\s+(?:prove|confirm|mean)\s+(?:popularity|market\s+impact|an?\s+exchange\s+closure)',
    r'(?:aksiya\s+narxiga\s+ta\'sirni|mashhurlikni|birja\s+yopiqligini)\s+(?:isbotlamaydi|tasdiqlamaydi)',
)


def _source_problem(ref, selected, originals, now):
    row = originals.get(ref['evidence_id'])
    if (ref['evidence_id'] not in selected or not row or row['version'] != ref['evidence_version']
            or row['status'] != 'verified' or row['rights'] == 'unknown' or not row.get('event_at')
            or not row.get('excerpt') or timestamp(row['expires_at']) <= now
            or timestamp(row['retrieved_at']) > now or timestamp(row['published_at']) > now):
        return 'The editorial occasion needs its selected, current verified original and announced date'
    return ''


def validate_scope(c, scope, originals, now):
    if not scope or not scope.get('occasion'):
        return
    ref = scope['occasion']
    current = sources.current_evidence(c, ref['evidence_id'])
    problem = _source_problem(ref, {row['id'] for row in originals}, {ref['evidence_id']: current}, now)
    if problem:
        raise MarketingError('OCCASION_SOURCE', problem, 422)


def guard(c, task, now):
    validate_scope(c, task.get('production'), task.get('evidence', []), now)


def check(item, evidence, now):
    ref = item.get('occasion')
    if not ref:
        return []
    if problem := _source_problem(ref, item['evidence_ids'], evidence, now):
        return [problem]
    visible = _text(item['title'] + '\n' + item['body'])
    failures = []
    for field, (label, pattern) in RISKS.items():
        unsupported = visible
        for claim in item['claims']:
            row = evidence.get(claim['evidence_id'])
            value = claim['value']
            if (claim['field'] == field and isinstance(value, str) and value.strip() and row
                    and claim['evidence_id'] in item['evidence_ids'] and row['status'] == 'verified'
                    and row['data'].get(field) == value and value in row['excerpt']):
                unsupported = unsupported.replace(_text(value), '')
        for disclaimer in DISCLAIMERS:
            unsupported = re.sub(disclaimer, '', unsupported)
        if re.search(pattern, unsupported):
            failures.append(f'An occasion does not confirm {label}; use an exact checked source statement or remove the claim')
    return failures
