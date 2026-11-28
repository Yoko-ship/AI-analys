"""Permissioned source registry, observable collection and canonical event groups."""
from datetime import date, datetime, timedelta
from typing import Literal
from typing import Annotated
import unicodedata

from pydantic import Field, field_validator

from . import store as s
from .url_policy import public_url
from .errors import MarketingError, require_owner
from .models import Evidence, Input
from .permissions import timestamp

COLLECTOR = {"id": "source_collector", "role": "research"}


def theme_key(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class Source(Input):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2000)
    category: Literal["uzstock", "exchange", "regulator", "issuer", "macro", "media", "social", "manual"]
    method: Literal["manual", "internal_news", "internal_market", "internal_analysis", "rss"]
    language: str = Field(default="ru", max_length=10)
    owner: str = Field(min_length=1, max_length=100)
    geography: str = Field(default="UZ", max_length=100)
    topics: list[str] = Field(default_factory=list, max_length=30)
    frequency_minutes: int = Field(default=60, ge=5, le=10080)
    stale_after_hours: int = Field(default=24, ge=1, le=8760)
    rights: Literal["link_and_excerpt", "owned", "licensed", "unknown"] = "unknown"
    terms_checked_on: date | None = None
    authorization_required: bool = False
    access_owner: str = Field(default="", max_length=100)
    data_type: Literal["extract", "headline", "numeric", "document", "full"] = "extract"
    may_store: bool = False
    may_display: bool = False
    commercial_use: bool = False
    restrictions: str = Field(default="", max_length=3000)
    fallback: str = Field(default="Stop and report unavailable", max_length=1000)


class Material(Input):
    source_item_id: str = Field(min_length=1, max_length=200)
    canonical_event_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2000)
    publisher: str = Field(min_length=1, max_length=200)
    entity: str = Field(default="", max_length=100)
    published_at: datetime
    event_at: datetime | None = None
    excerpt: str = Field(min_length=1, max_length=20000)
    data: dict = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    rights: Literal["link_and_excerpt", "owned", "licensed", "unknown"] = "unknown"
    period: str = ""
    standard: str = ""
    period_start: str = Field(default="", max_length=40)
    period_kind: str = Field(default="", max_length=40)
    scope: str = ""
    currency: str = "UZS"
    destination_url: str = Field(default="", max_length=2000)
    suggested_rubric: str = Field(default="news", max_length=40)
    analysis_version: str = Field(default="", max_length=200)
    themes: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=10)

    @field_validator("themes")
    @classmethod
    def normalized_themes(cls, values):
        keys = list(dict.fromkeys(theme_key(value) for value in values))
        if any(not value for value in keys):
            raise ValueError("Theme labels cannot be blank")
        return keys


def save_source(actor, source_id, data, expected_version):
    require_owner(actor)
    value = Source.model_validate(data).model_dump(mode="json")
    if not public_url(value["url"]):
        raise MarketingError("INVALID_URL", "Use an HTTPS source address without credentials.", 422)
    with s.connection(write=True) as c:
        previous = s.get(c, "source", source_id, required=False) or {}
        return s.put(c, "source", {**previous, **value, "id": source_id, "configuration_digest": s.digest(value), "enabled": False,
                     "status": "candidate", "last_success_at": None, "last_attempt_at": None, "reason": "Awaiting owner monitoring authorization"},
                     actor=actor, action="source_configured", expected_version=expected_version)


def enable_source(actor, source_id, expected_version, enabled=True):
    require_owner(actor)
    with s.connection(write=True) as c:
        source = s.get(c, "source", source_id)
        if enabled and (source["rights"] == "unknown" or not source["terms_checked_on"]):
            raise MarketingError("RIGHTS_REQUIRED", "Review the source's access and usage terms before monitoring.")
        if enabled and not source["may_store"]:
            raise MarketingError("STORAGE_REQUIRED", "Explicit storage permission is required before collecting source material.")
        if enabled:
            _validate_storage(source)
        return s.put(c, "source", {**source, "enabled": enabled, "status": "reviewing" if enabled else "disabled",
                     "next_attempt_at": None, "reason": "Awaiting first collection" if enabled else "Disabled by owner"},
                     actor=actor, action="source_permission_changed", expected_version=expected_version)


def collect_one(fetch, now):
    with s.connection(write=True) as c:
        if (s.get(c, "settings", "pause", required=False) or {}).get("processing"):
            return False
        source = next((src for src in reversed(s.list_items(c, "source")) if src["enabled"] and src["may_store"] and src["method"] != "manual"
                       and (not src.get("next_attempt_at") or timestamp(src["next_attempt_at"]) <= now)), None)
        if not source:
            return False
        claimed = s.put(c, "source", {**source, "last_attempt_at": now.isoformat(),
                        "next_attempt_at": (now + timedelta(minutes=source["frequency_minutes"])).isoformat(),
                        "reason": "Collection in progress"}, actor=COLLECTOR, action="collection_started", expected_version=source["version"])
    try:
        from .source_adapters import CollectionBatch
        batch = fetch(source)
        materials = batch.materials if isinstance(batch, CollectionBatch) else batch
        verified_ids = batch.verified_ids if isinstance(batch, CollectionBatch) else set()
        if not isinstance(materials, list) or len(materials) > 1000:
            raise ValueError("Collector result is not a bounded material list")
        values = [Material.model_validate(value).model_dump(mode="json") for value in materials]
        with s.connection(write=True) as c:
            current = s.get(c, "source", source["id"])
            if not current["enabled"] or current["version"] != claimed["version"]:
                return True
            for material in values:
                _record_material(c, current, material, now, verified=material["source_item_id"] in verified_ids)
            s.put(c, "source", {**current, "status": "connected", "last_success_at": now.isoformat(),
                  "last_count": len(values), "reason": "Collection completed" if values else "Collection succeeded; no materials in the selected window"},
                  actor=COLLECTOR, action="collection_completed", expected_version=current["version"])
    except Exception:
        with s.connection(write=True) as c:
            current = s.get(c, "source", source["id"])
            if current["version"] == claimed["version"]:
                s.put(c, "source", {**current, "status": "unavailable", "reason": "Source collection failed; previous evidence is preserved"},
                      actor=COLLECTOR, action="collection_failed", expected_version=current["version"])
    return True


def _record_material(c, source, material, now, *, verified=False):
    if material["rights"] not in {source["rights"], "link_and_excerpt", "unknown"}:
        raise MarketingError("RIGHTS_EXCEEDED", "Material rights cannot exceed the source's approved rights.", 422)
    if source["data_type"] == "headline":
        material = {**material, "excerpt": material["title"], "data": {}, "units": {}}
        verified = False
    elif source["data_type"] == "numeric":
        data = {key: value for key, value in material["data"].items() if isinstance(value, (int, float, bool))}
        units = {key: unit for key, unit in material["units"].items() if key in data}
        material = {**material, "data": data, "units": units, "excerpt": s.encode({"data": data, "units": units})}
    key = s.digest([source["id"], material["source_item_id"]])
    previous = s.get(c, "evidence", key, required=False)
    fingerprint = s.digest([material, source.get("configuration_digest")])
    expires = (now + timedelta(hours=source["stale_after_hours"])).isoformat()
    if not previous or previous.get("material_digest") != fingerprint:
        data = {k: material[k] for k in Evidence.model_fields if k in material}
        value = Evidence.model_validate({**data, "retrieved_at": now.isoformat(), "expires_at": expires,
                                        "source_id": source["id"], "status": "verified" if verified else "candidate"}).model_dump(mode="json")
        if not public_url(value["url"]):
            raise ValueError("Original source URL is invalid")
        previous = s.put(c, "evidence", {**value, "id": key, "material_digest": fingerprint,
                         "canonical_event_id": material["canonical_event_id"], "destination_url": material["destination_url"],
                         "suggested_rubric": material["suggested_rubric"], "analysis_version": material["analysis_version"],
                         "themes": material["themes"],
                         "source_configuration": source.get("configuration_digest")}, actor=COLLECTOR,
                         action="material_updated" if previous else "material_received", expected_version=previous["version"] if previous else 0)
    observation = s.get(c, "observation", key, required=False)
    s.put(c, "observation", {"id": key, "source_id": source["id"], "evidence_version": previous["version"],
          "received_at": now.isoformat(), "expires_at": expires}, actor=COLLECTOR,
          action="source_observed", expected_version=observation["version"] if observation else 0)
    topic_id = s.digest(material["canonical_event_id"])
    topic = s.get(c, "topic", topic_id, required=False) or {"id": topic_id, "version": 0, "evidence_ids": []}
    evidence_ids = list(dict.fromkeys([*topic["evidence_ids"], key]))
    event_at = material.get("event_at") or material["published_at"]
    fresh = timedelta(0) <= now - timestamp(event_at) <= timedelta(days=7)
    s.put(c, "topic", {**topic, "canonical_event_id": material["canonical_event_id"], "title": material["title"],
          "entity": material["entity"], "event_at": event_at, "evidence_ids": evidence_ids, "independent_events": 1,
          "classification": "new_event" if fresh else "editorial_hypothesis", "interest_growth": None,
          "reason": "A dated event from monitored sources; reprints are not independent confirmations"},
          actor=COLLECTOR, action="topic_updated", expected_version=topic["version"])


def current_evidence(c, evidence_id):
    evidence = s.get(c, "evidence", evidence_id, required=False)
    if not evidence:
        return None
    source = s.get(c, "source", evidence.get("source_id", "manual"), required=False)
    if source and (source["status"] != "connected" or not source["may_display"] or not source["commercial_use"]
                   or evidence.get("source_configuration") != source.get("configuration_digest")):
        return {**evidence, "status": "disabled" if source["status"] == "disabled" else "unavailable"}
    observation = s.get(c, "observation", evidence_id, required=False)
    if observation and observation["evidence_version"] == evidence["version"]:
        source = s.get(c, "source", observation["source_id"], required=False)
        if source and source["enabled"] and source["status"] == "connected":
            return {**evidence, "expires_at": observation["expires_at"]}
    return evidence


def import_materials(actor, source_id, materials, now):
    require_owner(actor)
    if not 1 <= len(materials) <= 100:
        raise MarketingError("IMPORT_SIZE", "Import between 1 and 100 materials.", 422)
    values = [Material.model_validate(value).model_dump(mode="json") for value in materials]
    with s.connection(write=True) as c:
        source = s.get(c, "source", source_id)
        if not source["may_store"] or source["rights"] == "unknown" or not source["terms_checked_on"]:
            raise MarketingError("RIGHTS_REQUIRED", "Confirm storage rights before importing source material.")
        _validate_storage(source)
        for value in values:
            _record_material(c, source, value, now)
        s.put(c, "source", {**source, "last_success_at": now.isoformat(), "status": "connected", "last_count": len(values),
              "reason": "Owner import completed"}, actor=actor, action="materials_imported", expected_version=source["version"])
    return {"count": len(values)}


def _validate_storage(source):
    if source["data_type"] in {"full", "document"} and source["rights"] == "link_and_excerpt":
        raise MarketingError("STORAGE_SCOPE", "Link-and-excerpt rights do not permit full document storage.")


def verify_evidence(actor, evidence_id, expected_version, reason):
    require_owner(actor)
    if not reason.strip():
        raise MarketingError("REASON_REQUIRED", "Record how you compared the extracted facts with the original.", 422)
    with s.connection(write=True) as c:
        value = s.get(c, "evidence", evidence_id)
        return s.put(c, "evidence", {**value, "status": "verified", "verification_reason": reason[:2000]},
                     actor=actor, action="evidence_verified_by_owner", expected_version=expected_version)
