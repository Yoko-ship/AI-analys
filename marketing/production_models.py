"""Owner production scope and untrusted structured role deliverables."""
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .models import ChartRef, Claim, DigestItem, Input, Occasion


class Target(Input):
    account_id: str = Field(min_length=1, max_length=200)
    languages: list[Literal["ru", "uz", "en"]] = Field(min_length=1, max_length=3)
    primary_language: Literal["ru", "uz", "en"]
    format: Literal["post", "image", "carousel", "video", "story"] = "post"
    instagram_link: Literal["none", "profile"] = "none"

    @model_validator(mode="after")
    def selected_language(self):
        if self.primary_language not in self.languages or len(set(self.languages)) != len(self.languages):
            raise ValueError("Choose one primary language from the distinct requested languages")
        return self


class ProductionBrief(Input):
    event_id: str = Field(min_length=1, max_length=200)
    rubric: Literal["market", "news", "digest", "quarterly", "dividend", "calendar", "chart", "education", "holiday", "product"]
    entity: str = Field(default="", max_length=100)
    period: str = Field(default="", max_length=40)
    destination_url: str = Field(default="", max_length=2000)
    expires_at: datetime
    not_before: datetime | None = None
    mode: Literal["draft", "account"] = "draft"
    targets: list[Target] = Field(min_length=1, max_length=8)
    founder_fact_ids: list[str] = Field(default_factory=list, max_length=30)
    chart: ChartRef | None = None
    occasion: Occasion | None = None

    @model_validator(mode="after")
    def distinct_targets(self):
        from .publication_links import valid_destination
        if self.rubric == 'chart' and (not self.chart or any(target.format == 'post' for target in self.targets)):
            raise ValueError('A chart production needs a selected source series and media formats')
        if self.chart and self.rubric != 'chart':
            raise ValueError('A fixed chart series belongs to chart production')
        if self.destination_url and not valid_destination(self.destination_url):
            raise ValueError("Use a direct HTTPS UZStock destination without credentials or a publication tracking token")
        if len({target.account_id for target in self.targets}) != len(self.targets):
            raise ValueError("Choose each account once")
        if self.expires_at.tzinfo is None:
            raise ValueError("Production expiry requires a time zone")
        if self.not_before is not None and (self.not_before.tzinfo is None or self.not_before >= self.expires_at):
            raise ValueError("Publication time requires a time zone and must precede production expiry")
        return self


class PlatformDraft(Input):
    account_id: str = Field(min_length=1, max_length=200)
    language: Literal["ru", "uz", "en"]
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    evidence_ids: list[str] = Field(min_length=1, max_length=30)
    claims: list[Claim] = Field(default_factory=list, max_length=100)
    digest_items: list[DigestItem] = Field(default_factory=list, max_length=8)
    destination_url: str = Field(max_length=2000)
    founder_fact_ids: list[str] = Field(default_factory=list, max_length=30)
    calculation: dict | None = None


class DraftReview(Input):
    draft_id: str = Field(min_length=1, max_length=200)
    draft_digest: str = Field(min_length=1, max_length=100)
    verdict: Literal["accept", "reject"]
    reason: str = Field(min_length=1, max_length=3000)
    fragments: list[str] = Field(default_factory=list, max_length=30)
