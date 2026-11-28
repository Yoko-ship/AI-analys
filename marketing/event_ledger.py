"""Original observations and dated owner amendments form one replayable input ledger."""
from typing import Literal

from pydantic import Field, model_validator

from . import analytics, store as s
from .errors import MarketingError
from .models import Input
from .permissions import timestamp


class Correction(Input):
    event_id: str = Field(min_length=1, max_length=200)
    dataset: Literal["production", "test"]
    replacement: analytics.Event | None
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=0)

    @model_validator(mode="after")
    def same_identity(self):
        if self.replacement and (self.replacement.id != self.event_id or self.replacement.dataset != self.dataset):
            raise ValueError("An amendment cannot change the event's identity or dataset")
        return self


def read(c, cut):
    records = {row["id"]: row for row in s.list_items(c, "event") if timestamp(row["received_at"]) <= cut}
    from . import website_ledger
    corrections, protected = [], set()
    for latest in s.list_items(c, "event_correction"):
        available = [row["record"] for row in s.history(c, "event_correction", latest["id"])
                     if timestamp(row["record"]["received_at"]) <= cut]
        if not available or latest["id"] not in records:
            continue
        amendment = available[-1]
        protected.add(amendment['id'])
        corrections.append({"id": amendment["id"], "dataset": amendment["dataset"], "version": amendment["version"], "reason": amendment["reason"], "received_at": amendment["received_at"]})
        if amendment["replacement"] is None:
            del records[amendment["id"]]
        else:
            records[amendment["id"]] = {**records[amendment["id"]], "event": amendment["replacement"]}
    corrections.extend(website_ledger.apply(c, records, cut, protected=protected))
    return list(records.values()), corrections


def amend(c, actor, amendments, now):
    for value in amendments:
        key = s.digest([value["dataset"], value["event_id"]])
        s.get(c, "event", key)
        if value["replacement"] and timestamp(value["replacement"]["at"]) > now:
            raise MarketingError("FUTURE_CONFIRMATION", "Future observations cannot be confirmed.", 422)
        s.put(c, "event_correction", {"id": key, **{name: content for name, content in value.items() if name != "expected_version"},
              "received_at": now.isoformat()}, actor=actor, action="event_corrected", expected_version=value["expected_version"])
