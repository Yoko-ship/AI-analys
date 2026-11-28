"""Validated input contracts; model output has no authority to alter permissions."""
from datetime import date, datetime, time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class ChartRef(Input):
    evidence_id: str = Field(min_length=1, max_length=200)
    field: str = Field(min_length=1, max_length=200)


class Goal(Input):
    title: str = Field(min_length=3, max_length=200)
    metric: str = Field(min_length=1, max_length=100)
    formula: str = Field(min_length=1, max_length=500)
    unit: str = Field(min_length=1, max_length=60)
    source: str = Field(min_length=1, max_length=200)
    baseline: float | None = Field(default=None, ge=0)
    target: float = Field(gt=0)
    starts_on: date
    deadline: date
    budget: float = Field(ge=0)
    currency: Literal["UZS", "USD"] = "UZS"
    audiences: list[str] = Field(default_factory=list, max_length=30)
    checkpoints: list[date] = Field(default_factory=list, max_length=30)
    product_context: str = Field(default="", max_length=12000)
    limitations: str = Field(default="", max_length=6000)

    @model_validator(mode="after")
    def dates_in_order(self):
        if self.deadline <= self.starts_on:
            raise ValueError("Deadline must follow the start date")
        if any(not self.starts_on <= d <= self.deadline for d in self.checkpoints):
            raise ValueError("Checkpoints must be inside the goal period")
        return self


PlanText = Annotated[str, Field(min_length=1, max_length=2000)]
PlanRole = Literal["owner", "cmo", "coordinator", "market", "pr", "news", "copywriter", "targeting", "analytics", "creative", "media", "quality"]


class StrategyStep(Input):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    owner: PlanRole
    action: PlanText
    deliverable: PlanText
    starts_on: date
    due: date
    budget: float = Field(ge=0, strict=True)
    dependencies: list[str] = Field(default_factory=list, max_length=100)
    channel: Literal["internal", "telegram", "instagram", "facebook", "linkedin"]
    rubric: str = Field(default="", max_length=100)
    mode: Literal["organic", "research", "measurement", "paid_proposal", "operations"]


class ScenarioProjection(Input):
    snapshot_id: str = Field(min_length=1, max_length=100)
    factor: float = Field(ge=0, strict=True)
    assumption: PlanText


class Scenario(Input):
    kind: Literal["conservative", "base", "target"]
    assumptions: list[PlanText] = Field(min_length=1, max_length=20)
    actions: list[PlanText] = Field(min_length=1, max_length=30)
    resources: PlanText
    budget: float = Field(ge=0, strict=True)
    constraints: list[PlanText] = Field(min_length=1, max_length=20)
    risks: list[PlanText] = Field(min_length=1, max_length=20)
    checkpoint: date
    formula: PlanText
    measurement_plan: PlanText
    projection: ScenarioProjection | None = None


class PlanKPI(Input):
    metric: str = Field(min_length=1, max_length=100)
    formula: PlanText
    unit: str = Field(min_length=1, max_length=60)
    source: PlanText
    target: float | None = Field(default=None, ge=0)
    owner: PlanRole
    checkpoint: date


class Strategy(Input):
    title: str = Field(min_length=3, max_length=200)
    goal_version: int = Field(ge=1)
    segments: list[PlanText] = Field(min_length=1, max_length=30)
    positioning: str = Field(min_length=1, max_length=5000)
    channels: list[Literal["telegram", "instagram", "facebook", "linkedin"]] = Field(min_length=1, max_length=4)
    rubrics: list[PlanText] = Field(min_length=1, max_length=30)
    steps: list[StrategyStep] = Field(min_length=1, max_length=100)
    kpis: list[PlanKPI] = Field(min_length=1, max_length=30)
    measurement: str = Field(min_length=1, max_length=5000)
    risks: list[str] = Field(default_factory=list, max_length=50)
    allowed_changes: list[str] = Field(default_factory=list, max_length=30)
    assumptions: list[str] = Field(default_factory=list, max_length=50)
    scenarios: list[Scenario] = Field(min_length=3, max_length=3)


class PublicationSchedule(Input):
    window_start: time = time(9)
    window_end: time = time(21)
    min_interval_minutes: int = Field(default=60, ge=1, le=10080)
    news_daily_limit: int = Field(default=2, ge=1, le=24)
    news_publish_times: list[time] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def valid_schedule(self):
        values = [self.window_start, self.window_end, *self.news_publish_times]
        if any(t.tzinfo is not None or t.second or t.microsecond for t in values):
            raise ValueError("Укажите время в часах и минутах по Ташкенту, без часового пояса")
        if self.window_start >= self.window_end:
            raise ValueError("Choose a nonempty same-day release window in Asia/Tashkent")
        times = sorted(self.news_publish_times)
        if times:
            if len(times) != self.news_daily_limit or len(set(times)) != len(times):
                raise ValueError("Для каждого поста нужно отдельное время: число времён должно совпадать с лимитом")
            if any(not self.window_start <= t < self.window_end for t in times):
                raise ValueError("Все времена должны быть внутри окна публикаций; конец окна не включён")
            minutes = [t.hour * 60 + t.minute for t in times]
            gaps = [b - a for a, b in zip(minutes, [*minutes[1:], minutes[0] + 1440])]
            if min(gaps) < self.min_interval_minutes:
                raise ValueError("Времена слишком близко: учитывайте минимальный интервал между публикациями")
        self.news_publish_times = times
        return self


class Account(PublicationSchedule):
    platform: Literal["telegram", "instagram", "facebook", "linkedin"]
    label: str = Field(min_length=1, max_length=120)
    external_id: str = Field(default="", max_length=200)
    mode: Literal["draft", "manual", "automatic"] = "draft"
    rubrics: list[str] = Field(default_factory=list, max_length=30)
    formats: list[Literal["post", "carousel", "image", "video", "story"]] = Field(default_factory=list)
    languages: list[Literal["ru", "uz", "en"]] = Field(default_factory=lambda: ["ru"])
    valid_until: datetime | None = None
    correction_policy: Literal["manual", "authorized_correction"] = "manual"
    paused: bool = False
    personal_profile: bool = False
    instagram_link_ready: bool = False
    automatic_news: bool = False

    @model_validator(mode="after")
    def permission_scope(self):
        if self.mode != "draft":
            ongoing_news = self.platform == 'telegram' and self.automatic_news
            if not self.external_id or (not self.valid_until and not ongoing_news) or not self.rubrics or not self.formats:
                raise ValueError("Release permission requires an account, expiry, rubrics and formats")
            if self.platform == "linkedin" and not self.personal_profile:
                raise ValueError("LinkedIn requires a separately authorized personal profile")
        if self.valid_until and self.valid_until.tzinfo is None:
            raise ValueError("Permission expiry requires a time zone")
        return self


class Evidence(Input):
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2000)
    publisher: str = Field(min_length=1, max_length=200)
    entity: str = Field(default="", max_length=100)
    published_at: datetime
    event_at: datetime | None = None
    retrieved_at: datetime
    expires_at: datetime
    excerpt: str = Field(min_length=1, max_length=20000)
    rights: Literal["link_and_excerpt", "owned", "licensed", "unknown"] = "unknown"
    data: dict[str, Any] = Field(default_factory=dict)
    status: Literal["candidate", "verified", "unavailable", "disabled"] = "candidate"
    period: str = Field(default="", max_length=40)
    standard: str = Field(default="", max_length=40)
    period_start: str = Field(default="", max_length=40)
    period_kind: str = Field(default="", max_length=40)
    scope: str = Field(default="", max_length=80)
    currency: str = Field(default="UZS", max_length=10)
    units: dict[str, str] = Field(default_factory=dict)
    source_id: str = Field(default="manual", max_length=100)

    @model_validator(mode="after")
    def timestamps(self):
        for value in (self.published_at, self.event_at, self.retrieved_at, self.expires_at):
            if value and value.tzinfo is None:
                raise ValueError("Evidence timestamps require a time zone")
        if self.expires_at <= self.retrieved_at:
            raise ValueError("Evidence expiry must follow retrieval")
        return self


class Claim(Input):
    evidence_id: str
    field: str
    value: str | float
    unit: str = ""


class DigestItem(Input):
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    text: str = Field(min_length=1, max_length=3000)


class Occasion(Input):
    kind: Literal['holiday', 'gaming']
    evidence_id: str = Field(min_length=1, max_length=200)
    evidence_version: int = Field(ge=1)


class Candidate(Input):
    event_id: str = Field(min_length=1, max_length=200)
    account_id: str = Field(min_length=1, max_length=200)
    publication_type: Literal["organic", "paid"] = "organic"
    rubric: Literal["market", "news", "digest", "quarterly", "dividend", "calendar", "chart", "education", "holiday", "product"]
    entity: str = Field(default="", max_length=100)
    language: Literal["ru", "uz", "en"] = "ru"
    format: Literal["post", "carousel", "image", "video", "story"] = "post"
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    claims: list[Claim] = Field(default_factory=list, max_length=100)
    digest_items: list[DigestItem] = Field(default_factory=list, max_length=8)
    occasion: Occasion | None = None
    destination_url: str = Field(default="", max_length=2000)
    instagram_link: Literal["none", "profile"] = "none"
    track_visits: bool = Field(default=False, strict=True)
    expires_at: datetime
    not_before: datetime | None = None
    mode: Literal["draft", "manual", "automatic"] = "draft"
    analysis_ready: bool = False
    period: str = Field(default="", max_length=40)
    calculation: dict[str, Any] | None = None
    assets: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    founder_fact_ids: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def expiry_zone(self):
        if self.digest_items and self.rubric not in {"digest", "calendar"}:
            raise ValueError("Source-bound items belong to the digest or calendar rubric")
        if self.expires_at.tzinfo is None:
            raise ValueError("Content expiry requires a time zone")
        if self.not_before is not None:
            if self.not_before.tzinfo is None:
                raise ValueError("Publication time requires a time zone")
            if self.not_before >= self.expires_at:
                raise ValueError("Publication time must precede content expiry")
        return self
