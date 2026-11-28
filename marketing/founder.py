"""Owner-confirmed biography/product wording for personal-profile content."""
from datetime import datetime, timezone
import re
from typing import Literal
import unicodedata

from pydantic import Field, model_validator

from . import checks, store as s
from .errors import MarketingError, require_owner
from .models import Input
from .permissions import timestamp


class FounderFact(Input):
    title: str = Field(min_length=1, max_length=200)
    category: Literal["role", "experience", "achievement", "product"] = "role"
    proof_url: str = Field(min_length=1, max_length=2000)
    verification_note: str = Field(min_length=1, max_length=2000)
    wordings: dict[Literal["ru", "uz", "en"], list[str]]
    status: Literal["draft", "verified", "disabled"] = "draft"
    valid_until: datetime

    @model_validator(mode="after")
    def reviewable(self):
        if self.valid_until.tzinfo is None:
            raise ValueError("Fact validity requires a time zone")
        if not self.wordings or any(not values or len(values) > 20 or any(not value.strip() or len(value) > 1000 for value in values) for values in self.wordings.values()):
            raise ValueError("Provide one to twenty explicit permitted sentences per language")
        if not self.verification_note.strip():
            raise ValueError("Describe how the owner confirmed this fact")
        return self


def save(actor, fact_id, data, expected_version):
    require_owner(actor)
    value = FounderFact.model_validate(data).model_dump(mode="json")
    if not checks.public_url(value["proof_url"]):
        raise MarketingError("INVALID_PROOF", "Use an HTTPS proof URL without credentials.", 422)
    with s.connection(write=True) as c:
        return s.put(c, "founder_fact", {**value, "id": fact_id, "verified_by": actor["id"] if value["status"] == "verified" else None},
                     actor=actor, action="founder_fact_recorded", expected_version=expected_version)


def revoke(actor, fact_id, expected_version):
    require_owner(actor)
    with s.connection(write=True) as c:
        item = s.get(c, "founder_fact", fact_id)
        return s.put(c, "founder_fact", {**item, "status": "disabled"}, actor=actor,
                     action="founder_fact_revoked", expected_version=expected_version)


def usable(fact, now):
    return bool(fact and fact["status"] == "verified" and fact.get("verified_by") is not None and timestamp(fact["valid_until"]) > now)


def context(c, ids):
    facts = [s.get(c, "founder_fact", key) for key in dict.fromkeys(ids)]
    if not all(usable(fact, datetime.now(timezone.utc)) for fact in facts):
        raise MarketingError("FOUNDER_MAP_REQUIRED", "Choose current owner-confirmed founder facts.")
    return facts


def _normalize(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().strip(' .!?«»“”\"').split())


def check(c, item, account, now):
    personal = account and account["platform"] == "linkedin"
    if not personal and not item["founder_fact_ids"]:
        return [], {}
    if not item["founder_fact_ids"]:
        return ["A personal LinkedIn version requires the confirmed founder fact map"], {}
    failures, versions, allowed = [], {}, set()
    for key in dict.fromkeys(item["founder_fact_ids"]):
        fact = s.get(c, "founder_fact", key, required=False)
        if not usable(fact, now):
            failures.append("Founder fact unavailable, expired or unverified: " + key)
            continue
        wordings = fact["wordings"].get(item["language"], [])
        if not wordings:
            failures.append("Founder fact has no approved wording for this language: " + key)
        allowed.update(_normalize(wording) for wording in wordings)
        versions[key] = fact["version"]
    # Exact approved sentences bound personal experience; the quality role also
    # reviews implications, third-person claims and facts not caught by syntax.
    sentences = re.split(r"(?<=[.!?])\s+|\n+", item["title"] + "\n" + item["body"])
    for sentence in sentences:
        if re.search(r"\b(?:я|мы|мой|моя|мои|наш|наша|наши|мен|биз|men|biz|mening|bizning|i|we|my|our)\b", sentence, re.I) and _normalize(sentence) not in allowed:
            failures.append("Personal statement is outside approved founder wording: " + sentence[:300])
    return failures, versions
