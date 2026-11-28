"""Explicit, dated completeness evidence; absent observations never imply zero."""
from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from .models import Input
from .permissions import TASHKENT, timestamp

CATEGORY_KINDS = {
    "visits": {"visit"}, "registrations": {"registration", "registration_started"},
    "payments": {"payment", "refund", "cancellation"}, "expenses": {"expense"},
    "activity": {"report_open", "chart_open", "issuer_open", "news_open", "search", "search_open", "search_empty", "favorite", "visit"},
    "subscriptions": {"subscription"}, "margin": {"payment", "refund"},
    **{kind + "s": {kind} for kind in ("click", "impression", "view", "reaction", "save", "share")},
    "reach": {"reach"},
}


class Coverage(Input):
    dataset: Literal["production", "test"]
    categories: list[str] = Field(min_length=1, max_length=20)
    starts_on: date
    ends_on: date
    through: datetime
    history_complete: bool = False
    status: Literal["complete", "incomplete", "unavailable"]
    reference: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def ordered(self):
        if self.ends_on <= self.starts_on or self.through.tzinfo is None:
            raise ValueError("Coverage requires an ordered period and timezone-aware cutoff")
        if not set(self.categories) <= CATEGORY_KINDS.keys() or not self.reference.strip():
            raise ValueError("Specify known event categories and evidence of completeness")
        return self


class CoverageLedger:
    """Resolve dated confirmations at one immutable cut; cache shared windows."""
    def __init__(self, records, dataset, cut):
        self.records = []
        self.cache = {}
        for record in records:
            row = record["coverage"]
            if row['dataset'] != dataset or timestamp(record['received_at']) > cut:
                continue
            self.records.append((record,
                datetime.combine(date.fromisoformat(row['starts_on']), datetime.min.time(), TASHKENT),
                datetime.combine(date.fromisoformat(row['ends_on']), datetime.min.time(), TASHKENT),
                timestamp(row['through']), (timestamp(record['received_at']), record['id'])))

    def assess(self, category, start, end, *, history_required=False, end_inclusive=False):
        key = category, start, end, history_required, end_inclusive
        if key in self.cache:
            return self.cache[key]
        applicable = []
        for record, begins, ends, through, order in self.records:
            row = record['coverage']
            if category not in row['categories']:
                continue
            overlaps_end = begins <= end if end_inclusive else begins < end
            if row['status'] != 'complete' and overlaps_end and (history_required or ends > start):
                applicable.append((order, record))
                continue
            if begins > start or ends < end or (end_inclusive and ends == end) or through < end:
                continue
            if history_required and not row['history_complete']:
                continue
            applicable.append((order, record))
        # Only a newer confirmation of the whole required basis can replace a gap notice.
        latest = max(applicable, key=lambda item: item[0])[1] if applicable else None
        result = {'starts_at': start.isoformat(), 'ends_at': end.isoformat(), 'end_inclusive': end_inclusive,
                  'history_required': history_required, 'status': latest['coverage']['status'] if latest else 'unavailable',
                  'confirmation': {'id': latest['id'], **latest['coverage']} if latest else None}
        self.cache[key] = result
        return result
