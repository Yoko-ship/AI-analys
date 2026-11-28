"""Dated competitor comparisons, separate from unsupported business estimates."""
from typing import Literal

from pydantic import Field, model_validator

from . import store as s
from .models import Input
from .research_evidence import bind_source

FIELDS = {'purpose', 'audience', 'features', 'pricing', 'communication', 'revenue', 'conversion', 'audience_size'}


class CompetitorFact(Input):
    field: Literal['purpose', 'audience', 'features', 'pricing', 'communication', 'revenue', 'conversion', 'audience_size']
    evidence_id: str = Field(default='', max_length=200)
    observed_excerpt: str = Field(default='', max_length=2000)


class CompetitorCard(Input):
    product: str = Field(min_length=1, max_length=200)
    relationship: Literal['direct', 'inspiration', 'adjacent']
    relationship_reason: str = Field(min_length=1, max_length=2000)
    difference_hypothesis: str = Field(min_length=1, max_length=3000)
    facts: list[CompetitorFact] = Field(min_length=8, max_length=8)

    @model_validator(mode='after')
    def complete_dimensions(self):
        if {fact.field for fact in self.facts} != FIELDS:
            raise ValueError('Each comparison dimension must occur once, including undisclosed fields')
        return self


def bind(task, role, result, now):
    cards = result['competitor_cards']
    if cards and role != 'market':
        raise ValueError('Only the market analyst supplies competitor comparisons')
    if task['kind'] == 'competitors' and role == 'market' and result['verdict'] == 'accept' and not cards:
        raise ValueError('An accepted comparison needs a structured competitor card')
    if not cards:
        return
    originals = {row['id']: row for row in task['evidence']}
    with s.connection() as c:
        for card in cards:
            for fact in card['facts']:
                if fact['observed_excerpt'] and fact['evidence_id'] in originals:
                    if originals[fact['evidence_id']]['entity'].strip().casefold() != card['product'].strip().casefold():
                        raise ValueError('The observed fact belongs to another or unspecified product')
                fact['source'] = bind_source(c, originals, fact['evidence_id'], fact['observed_excerpt'], now)
