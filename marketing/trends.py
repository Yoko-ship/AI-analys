"""Reviewed, immutable comparisons of observed mentions in a fixed source population.

Collection success is not proof of a complete feed. Only an owner's explicit
inventory/deduplication review enables a change calculation. Expiry for publishing
today does not erase a historical observation; changed originals or permissions do
invalidate its current use. No model-estimated interest or market-wide inference.
"""
from datetime import date, datetime, time, timedelta
from urllib.parse import urldefrag

from pydantic import Field, field_validator, model_validator

from . import store as s
from .errors import MarketingError, require_owner
from .models import Input
from .permissions import TASHKENT, timestamp
from .sources import theme_key

METHOD = "distinct-canonical-mentions-v1"


class Review(Input):
    theme: str = Field(min_length=1, max_length=100)
    source_ids: list[str] = Field(min_length=1, max_length=30)
    starts_on: date
    ends_on: date
    complete: bool = False
    review_reason: str = Field(default="", max_length=2000)
    audience_relevance: str = Field(min_length=1, max_length=2000)
    risk: str = Field(min_length=1, max_length=2000)
    proposed_format: str = Field(min_length=1, max_length=500)

    @field_validator("theme")
    @classmethod
    def normalized_theme(cls, value):
        value = theme_key(value)
        if not value:
            raise ValueError("A theme is required")
        return value

    @model_validator(mode="after")
    def comparable_windows(self):
        if not 1 <= (self.ends_on - self.starts_on).days <= 90:
            raise ValueError("Choose a window of 1 to 90 complete days")
        if self.complete and not self.review_reason.strip():
            raise ValueError("Explain how both complete inventories and reprints were reviewed")
        self.source_ids = sorted(set(self.source_ids))
        return self


def _bounds(value):
    start = datetime.combine(date.fromisoformat(value["starts_on"]), time(), TASHKENT)
    end = datetime.combine(date.fromisoformat(value["ends_on"]), time(), TASHKENT)
    return start - (end - start), start, end


def _inventory(c, value, now):
    """Include earlier originals so a later reprint cannot become a new mention."""
    _, _, end = _bounds(value)
    sources, blocked = [], False
    for key in value["source_ids"]:
        source = s.get(c, "source", key, required=False)
        allowed = bool(source and source["status"] == "connected" and source["may_store"]
                       and source["may_display"] and source["commercial_use"] and source["rights"] != "unknown")
        sources.append({"id": key, "name": source["name"] if source else key,
                        "configuration": source.get("configuration_digest") if source else None, "available": allowed})
        blocked |= not allowed
    configurations = {source["id"]: source["configuration"] for source in sources}
    evidence = []
    for item in s.list_items(c, "evidence"):
        if item["source_id"] not in configurations:
            continue
        if timestamp(item["published_at"]) >= end or timestamp(item["retrieved_at"]) > now:
            continue
        allowed = (item.get("source_configuration") == configurations[item["source_id"]]
                   and item["rights"] != "unknown" and item["status"] not in {"disabled", "unavailable"})
        evidence.append({**{key: item[key] for key in ("id", "version", "source_id", "published_at", "url", "title")},
                         "canonical_event_id": item.get("canonical_event_id"),
                         "themes": item.get("themes", []), "available": allowed})
    selected = [item for group in event_groups(evidence) if any(value["theme"] in item["themes"] for item in group) for item in group]
    blocked |= any(not item["available"] for item in selected)
    return {"method": METHOD, "sources": sources, "evidence": sorted(selected, key=lambda item: item["id"])}, blocked


def event_groups(items):
    # Transitive union: either the same canonical event or the same original URL
    # identifies a reprint/update. Different URLs require a reviewed event key;
    # no fuzzy headline matching invents independent confirmations.
    parents = {}

    def event_key(item):
        return "event:" + item["canonical_event_id"] if item["canonical_event_id"] else "evidence:" + item["id"]

    def root(key):
        parents.setdefault(key, key)
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    for item in items:
        event, url = event_key(item), "url:" + urldefrag(item["url"])[0]
        parents[root(url)] = root(event)
    groups = {}
    for item in items:
        groups.setdefault(root(event_key(item)), []).append(item)
    return list(groups.values())


def _window(groups, start, end):
    selected = [group for group in groups if start <= min(timestamp(item["published_at"]) for item in group) < end]
    originals = [item for group in selected for item in group if start <= timestamp(item["published_at"]) < end]
    latest = max((min(timestamp(item["published_at"]) for item in group) for group in selected), default=None)
    return {"starts_on": start.date().isoformat(), "ends_on": end.date().isoformat(),
            "mentions": len(selected), "source_ids": sorted({item["source_id"] for item in originals}),
            "evidence_ids": sorted({item["id"] for item in originals}),
            "latest_published_at": latest.isoformat() if latest else None}


def _classification(window):
    if window["mentions"] >= 2:
        return "recurring_theme"
    end = datetime.combine(date.fromisoformat(window["ends_on"]), time(), TASHKENT)
    if window["mentions"] == 1 and end - timestamp(window["latest_published_at"]) <= timedelta(days=7):
        return "new_event"
    return "editorial_hypothesis"


def save(actor, record_id, data, expected_version, now):
    require_owner(actor)
    value = Review.model_validate(data).model_dump(mode="json")
    baseline_start, start, end = _bounds(value)
    if end > now:
        raise MarketingError("OPEN_WINDOW", "Only complete past days can be compared.", 422)
    with s.connection(write=True) as c:
        basis, blocked = _inventory(c, value, now)
        if blocked:
            raise MarketingError("TREND_SOURCE_UNAVAILABLE", "A selected source or original is unavailable; review its permissions and configuration.")
        groups = event_groups(basis["evidence"])
        baseline, current = _window(groups, baseline_start, start), _window(groups, start, end)
        growth = None
        classification = _classification(current)
        if value["complete"]:
            delta = current["mentions"] - baseline["mentions"]
            growth = {"absolute": delta, "percent": round(delta / baseline["mentions"] * 100, 2) if baseline["mentions"] else None}
            if delta > 0:
                classification = "measured_growth"
        return s.put(c, "trend", {**value, "id": record_id, "baseline": baseline, "current": current,
                     "growth": growth, "classification": classification, "basis": basis, "basis_digest": s.digest(basis),
                     "review_status": "current", "reviewed_at": now.isoformat()},
                     actor=actor, action="theme_observation_reviewed", expected_version=expected_version)


def current(c, record, now):
    basis, blocked = _inventory(c, record, now)
    if blocked or s.digest(basis) != record["basis_digest"]:
        return {**record, "review_status": "stale", "growth": None, "classification": _classification(record["current"])}
    return record


def task_context(c, versions, now):
    observations = []
    for key, version in versions.items():
        record = s.get(c, "trend", key)
        if record["version"] != version or current(c, record, now)["review_status"] != "current":
            raise MarketingError("TREND_REVIEW_CHANGED", "Selected theme observations changed. Review them and start a new task.")
        observation = {key: record[key] for key in (
            "id", "version", "theme", "source_ids", "starts_on", "ends_on", "baseline", "current", "growth",
            "classification", "complete", "review_reason", "reviewed_at", "audience_relevance", "risk", "proposed_format")}
        for window in ("baseline", "current"):
            observation[window] = {key: value for key, value in record[window].items() if key != "evidence_ids"}
        observation["sources"] = record["basis"]["sources"]
        observation["method"] = METHOD
        observations.append(observation)
    return observations
