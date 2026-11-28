"""Media recommendations bound to the excerpts actually available to the role."""
from typing import Literal

from pydantic import Field

from . import store as s
from .models import Input
from .research_evidence import bind_source


class ReferenceCard(Input):
    evidence_id: str = Field(default='', max_length=200)
    recommendation: Literal['adapt', 'original', 'reject']
    observed_excerpt: str = Field(default='', max_length=2000)
    technique: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=2000)
    test_plan: str = Field(min_length=1, max_length=2000)


def bind(task, role, result, now):
    cards = result['reference_cards']
    if cards and role != 'media':
        raise ValueError('Only the media analyst supplies reference cards')
    if task['kind'] == 'research' and role == 'media' and result['verdict'] == 'accept' and not cards:
        raise ValueError('Research needs reference cards or an explicit original-format proposal')
    if not cards:
        return
    originals = {row['id']: row for row in task['evidence']}
    with s.connection() as c:
        for card in cards:
            if card['recommendation'] == 'original':
                if card['evidence_id'] or card['observed_excerpt']:
                    raise ValueError('An original-format proposal cannot claim an observed reference')
                card['source'] = None
                continue
            if not card['evidence_id']:
                raise ValueError('A reference needs the selected original')
            card['source'] = bind_source(c, originals, card['evidence_id'], card['observed_excerpt'], now,
                                         required=card['recommendation'] == 'adapt')
