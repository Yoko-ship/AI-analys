"""Deduplicated, pseudonymous events and reproducible Tashkent reporting cuts."""
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from . import store as s
from .errors import MarketingError, require_owner
from .models import Input
from .permissions import timestamp


class Event(Input):
    id: str = Field(min_length=1, max_length=200)
    kind: Literal["visit", "publication_visit", "registration_started", "registration", "report_open", "chart_open", "issuer_open", "news_open",
                  "search", "search_empty", "search_open", "favorite", "click", "impression", "view", "reach", "reaction", "save", "share",
                  "payment", "refund", "cancellation", "expense", "budget", "subscription"]
    subject_id: str = Field(default="", max_length=100, pattern=r"^[a-zA-Z0-9_:-]*$")
    at: datetime
    dataset: Literal["production", "test"] = "production"
    traffic: Literal["external", "internal", "automated"] = "external"
    source: str = Field(min_length=1, max_length=100)
    confirmed: bool = False
    channel: str = Field(default="unknown", max_length=100)
    publication_id: str = Field(default="", max_length=200)
    object_id: str = Field(default="", max_length=200)
    transaction_id: str = Field(default="", max_length=200)
    amount: float | None = Field(default=None, ge=0)
    currency: Literal["UZS", "USD"] = "UZS"
    category: Literal["advertising", "marketing", "sales", "other"] = "other"
    legal_entity: Literal["ip", "llc", "unknown"] = "unknown"
    payment_type: Literal["first", "renewal", "one_off"] | None = None
    count: int = Field(default=1, ge=0, le=1_000_000_000)
    promotion: Literal["organic", "paid"] = "organic"
    observation_mode: Literal["event", "snapshot"] = "event"
    observed_starts_at: datetime | None = None
    observed_ends_at: datetime | None = None
    revenue_kind: Literal["recurring", "one_off", "unknown"] = "unknown"
    gross_profit: float | None = None
    related_transaction_id: str = Field(default="", max_length=200)
    subscription_id: str = Field(default="", max_length=200)
    subscription_state: Literal["active", "cancelled"] = "active"
    billing_months: int | None = Field(default=None, ge=1, le=36)
    service_starts_at: datetime | None = None
    service_ends_at: datetime | None = None

    @model_validator(mode="after")
    def required_evidence(self):
        if self.at.tzinfo is None:
            raise ValueError("Event timestamp requires a time zone")
        if self.kind == 'publication_visit' and (not self.publication_id or not self.subject_id or self.channel in {'', 'unknown', 'direct'}):
            raise ValueError('A publication arrival needs its publication, pseudonymous reader and known channel')
        if self.kind in {"payment", "refund"} and (not self.transaction_id or self.amount is None):
            raise ValueError("A financial event requires a transaction ID and amount")
        if self.kind in {"registration", "payment", "cancellation"} and not self.subject_id:
            raise ValueError("A pseudonymous subject ID is required")
        if self.kind == "expense" and self.amount is None:
            raise ValueError("An expense requires a confirmed amount")
        if self.count != 1 and self.kind not in {"impression", "click", "view", "reach", "reaction", "save", "share"}:
            raise ValueError("Only platform observations can contain aggregate counts")
        if self.observation_mode == "snapshot":
            if self.kind not in {"impression", "click", "view", "reach", "reaction", "save", "share"} or not (self.publication_id or self.object_id):
                raise ValueError("A platform snapshot needs a measured object")
            if not self.observed_starts_at or not self.observed_ends_at or self.observed_starts_at.tzinfo is None or self.observed_ends_at.tzinfo is None or not self.observed_starts_at < self.observed_ends_at <= self.at:
                raise ValueError("A platform snapshot requires its measured interval before collection")
        if self.kind == "subscription" and (not self.subscription_id or not self.subject_id or self.amount is None or not self.billing_months):
            raise ValueError("A subscription snapshot needs customer, subscription, price and billing months")
        if self.kind == "subscription" or self.revenue_kind == "recurring":
            if not self.service_starts_at or not self.service_ends_at or self.service_starts_at.tzinfo is None or self.service_ends_at.tzinfo is None or self.service_ends_at <= self.service_starts_at:
                raise ValueError("Recurring service needs an ordered, timezone-aware coverage period")
        if self.gross_profit is not None and (self.kind != "payment" or self.amount is None or self.gross_profit > self.amount):
            raise ValueError("Confirmed contribution belongs to a payment and cannot exceed its revenue")
        return self


def ingest_events(actor, events, *, now=None):
    require_owner(actor)
    if len(events) > 10000:
        raise MarketingError("IMPORT_TOO_LARGE", "Import at most 10,000 events per batch.", 422)
    values = [Event.model_validate(event).model_dump(mode="json") for event in events]
    with s.connection(write=True) as c:
        return ingest(c, actor, values, now.isoformat() if now else s.now())


def ingest(c, actor, values, received_at, *, validate=True):
    """Join the caller's transaction so coverage cannot outlive a failed import."""
    count = 0
    for value in values:
        key = s.digest([value["dataset"], value["id"]])
        old = s.get(c, "event", key, required=False)
        if old:
            if old["event"] != value:
                raise MarketingError("EVENT_CONFLICT", "An event ID already contains different data.")
            continue
        s.put(c, "event", {"id": key, "event": value, "received_at": received_at},
              actor=actor, action="event_ingested", expected_version=0)
        count += 1
    if validate:
        from .event_ledger import read
        records, _ = read(c, timestamp(received_at))
        _deduplicate([row["event"] for row in records])
    return count


def _deduplicate(events):
    seen, transactions, result = {}, {}, []
    for raw in events:
        event = Event.model_validate(raw).model_dump(mode="json")
        key = (event["dataset"], event["id"])
        if key in seen:
            if seen[key] != event:
                raise MarketingError("EVENT_CONFLICT", "An event ID already contains different data.")
            continue
        seen[key] = event
        if event["kind"] in {"payment", "refund"}:
            txkey = (event["dataset"], event["kind"], event["transaction_id"])
            fingerprint = {key: value for key, value in event.items() if key not in {"id", "source"}}
            if txkey in transactions:
                if transactions[txkey] != fingerprint:
                    raise MarketingError("TRANSACTION_CONFLICT", "Conflicting copies of a financial transaction")
                continue
            transactions[txkey] = fingerprint
        result.append(event)
    return sorted(result, key=lambda event: (timestamp(event["at"]), event["id"]))


def calculate_report(events, *, starts_on, ends_on, cutoff, settings, coverage_records=None):
    from .report_calculation import calculate
    return calculate(_deduplicate(events), starts_on=starts_on, ends_on=ends_on, cutoff=cutoff, settings=settings, coverage_records=coverage_records)
