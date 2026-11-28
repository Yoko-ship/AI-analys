"""Versioned owner choices for definitions, attribution and monetization."""
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .models import Input

FORMULA_VERSION = "7"
ACTIVITY = Literal["visit", "report_open", "chart_open", "issuer_open", "news_open", "search_open", "favorite"]


class ChurnMonth(Input):
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    rate: float = Field(gt=0, le=1)
    source: str = Field(min_length=1, max_length=500)


class StabilityReview(Input):
    confirmed: bool = False
    note: str = Field(default="", max_length=2000)
    monthly_rates: list[ChurnMonth] = Field(default_factory=list, max_length=36)
    period: str | None = Field(default=None, pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    reviewed_at: datetime | None = None
    dataset: Literal['production', 'test'] | None = None
    currency: Literal['UZS', 'USD'] | None = None
    legal_entities: list[Literal['ip', 'llc']] = Field(default_factory=list)
    opening_customers: int | None = Field(default=None, strict=True, ge=1)
    lost_customers: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode="after")
    def supported(self):
        if self.confirmed and (not self.note.strip() or len({row.period for row in self.monthly_rates}) < 3):
            raise ValueError("A stability decision needs a reason and three measured months")
        if len({row.period for row in self.monthly_rates}) != len(self.monthly_rates) or any(not row.source.strip() for row in self.monthly_rates):
            raise ValueError('Each measured month needs one value and a source')
        if self.reviewed_at and self.reviewed_at.tzinfo is None:
            raise ValueError('The stability review needs a timezone')
        if self.opening_customers and self.lost_customers and self.lost_customers > self.opening_customers:
            raise ValueError('Lost customers cannot exceed the opening base')
        return self


class AnalyticsSettings(Input):
    dataset: Literal["production", "test"] = "production"
    currency: Literal["UZS", "USD"] = "UZS"
    attribution_model: Literal["last_non_direct"] = "last_non_direct"
    attribution_days: int = Field(default=7, ge=1, le=90)
    conversion_days: int = Field(default=7, ge=1, le=365)
    activation_event: ACTIVITY = "report_open"
    activation_days: int = Field(default=7, ge=1, le=365)
    retention_days: int = Field(default=7, ge=1, le=365)
    activity_events: list[ACTIVITY] = Field(default_factory=lambda: ["report_open"])
    cost_categories: list[Literal["advertising", "marketing", "sales"]] = Field(default_factory=list)
    cost_allocation: Literal["event_channel"] = "event_channel"
    acquisition_channels: list[str] = Field(default_factory=list, max_length=30)
    monetization_live: bool = False
    legal_entities: list[Literal["ip", "llc"]] = Field(default_factory=list)
    entity_launches: dict[Literal["ip", "llc"], datetime] = Field(default_factory=dict)
    shared_customer_ids: bool = False
    ltv_stability: StabilityReview = Field(default_factory=StabilityReview)
    automatic_weekly: bool = False
    formula_version: str = FORMULA_VERSION
    source_status: dict[str, Literal["complete", "incomplete", "unavailable", "not_connected"]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_definitions(self):
        if not self.activity_events:
            raise ValueError("Choose at least one measured activity event")
        if any(value.tzinfo is None for value in self.entity_launches.values()):
            raise ValueError("Launch timestamps require time zones")
        self.formula_version = FORMULA_VERSION
        return self
