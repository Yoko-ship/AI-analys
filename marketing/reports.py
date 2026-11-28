"""Owner reports computed from the durable ledger and frozen without replacement."""
from datetime import date, datetime, timedelta, timezone

from pydantic import Field, ValidationError, model_validator

from . import analytics, event_ledger, report_activity, snapshots, store as s
from .analytics_config import AnalyticsSettings
from .errors import MarketingError, require_owner
from .models import Input
from .permissions import TASHKENT, timestamp
from .report_coverage import Coverage


class Period(Input):
    starts_on: date
    ends_on: date
    cutoff: datetime | None = None

    @model_validator(mode="after")
    def valid(self):
        if not timedelta(0) < self.ends_on - self.starts_on <= timedelta(days=366):
            raise ValueError("Choose an ordered period of at most one year")
        if self.cutoff and self.cutoff.tzinfo is None:
            raise ValueError("The cutoff needs a timezone")
        return self


def settings(c):
    return s.get(c, "settings", "analytics", required=False) or {
        "id": "analytics", "version": 0, "data": AnalyticsSettings().model_dump(mode="json")}


def save_settings(actor, data, expected_version):
    require_owner(actor)
    value = AnalyticsSettings.model_validate(data).model_dump(mode="json")
    review = value['ltv_stability']
    if review['confirmed'] and review['reviewed_at'] and timestamp(review['reviewed_at']) > datetime.now(timezone.utc):
        raise MarketingError('FUTURE_CONFIRMATION', 'Решение о стабильности не может быть подтверждено будущей датой.', 422)
    # Completeness is dated evidence, never a permanent settings toggle.
    value["source_status"] = {}
    with s.connection(write=True) as c:
        return s.put(c, "settings", {"id": "analytics", "data": value}, actor=actor,
                     action="analytics_configured", expected_version=expected_version)


def import_events(actor, events, coverage, *, corrections=None, now=None):
    require_owner(actor)
    now = now or datetime.now(timezone.utc)
    if len(events) > 10000 or len(coverage) > 100 or len(corrections or []) > 1000:
        raise MarketingError("IMPORT_TOO_LARGE", "Import at most 10,000 events and 100 coverage records.", 422)
    try:
        values = [analytics.Event.model_validate(e).model_dump(mode="json") for e in events]
        confirmations = [Coverage.model_validate(row).model_dump(mode="json") for row in coverage]
        amendments = [event_ledger.Correction.model_validate(row).model_dump(mode="json") for row in corrections or []]
    except ValidationError as exc:
        raise MarketingError("INVALID_IMPORT", str(exc), 422) from None
    if any(timestamp(row["through"]) > now for row in confirmations) or any(timestamp(e["at"]) > now for e in values):
        raise MarketingError("FUTURE_CONFIRMATION", "Future observations cannot be confirmed.", 422)
    with s.connection(write=True) as c:
        count = analytics.ingest(c, actor, values, now.isoformat(), validate=False)
        event_ledger.amend(c, actor, amendments, now)
        effective, _ = event_ledger.read(c, now)
        analytics._deduplicate([row["event"] for row in effective])
        for row in confirmations:
            key = s.digest(row)
            if not s.get(c, "coverage", key, required=False):
                s.put(c, "coverage", {"id": key, "coverage": row, "received_at": now.isoformat()},
                      actor=actor, action="coverage_confirmed", expected_version=0)
    return {"imported": count, "coverage_confirmations": len(confirmations), "corrections": len(amendments)}


def current_week(now):
    today = now.astimezone(TASHKENT).date()
    monday = today - timedelta(days=today.weekday())
    return {"starts_on": monday.isoformat(), "ends_on": (monday + timedelta(days=7)).isoformat()}


def _calculate(c, period, now):
    selected = Period.model_validate(period or current_week(now))
    cut = selected.cutoff or now
    start = datetime.combine(selected.starts_on, datetime.min.time(), TASHKENT)
    end = datetime.combine(selected.ends_on, datetime.min.time(), TASHKENT)
    if cut > now or cut < start:
        raise MarketingError("INVALID_CUTOFF", "Use a cutoff between the period start and now.", 422)
    configured = settings(c)
    config = {**configured["data"]}
    effective, corrections = event_ledger.read(c, cut)
    records = [row for row in effective if row["event"]["dataset"] == config["dataset"] and timestamp(row["event"]["at"]) <= cut]
    report = analytics.calculate_report([row["event"] for row in records], starts_on=selected.starts_on.isoformat(),
                                       ends_on=selected.ends_on.isoformat(), cutoff=cut.isoformat(), settings=config, coverage_records=s.list_items(c, 'coverage'))
    report.update(settings_version=configured["version"], input_event_ids=sorted(row["id"] for row in records),
                  input_digest=s.digest(sorted((row["id"], s.digest(row["event"])) for row in records)),
                  source_basis=sorted({row["event"]["source"] for row in records}),
                  generated_at=now.isoformat(), corrections=[row for row in corrections if row["dataset"] == config["dataset"]])
    report_activity.enrich(c, report, start, end, cut)
    return report


def calculate(period=None, *, now=None):
    with s.connection() as c:
        return _calculate(c, period, now or datetime.now(timezone.utc))


def _freeze(c, actor, name, period, expected_settings_version, now, **metadata):
    if not name.strip() or len(name) > 150:
        raise MarketingError("INVALID_NAME", "Give the snapshot a name of at most 150 characters.", 422)
    if settings(c)["version"] != expected_settings_version:
        raise MarketingError("VERSION_CONFLICT", "Analytics definitions changed. Reload before saving.")
    report = _calculate(c, period, now)
    return s.put(c, "snapshot", {"id": s.uid("snapshot"), "name": name.strip(), "report": report,
                 "status": "frozen", **metadata}, actor=actor, action="snapshot_frozen", expected_version=0)


def freeze(actor, name, period, expected_settings_version, *, now=None):
    require_owner(actor)
    with s.connection(write=True) as c:
        return _freeze(c, actor, name, period, expected_settings_version, now or datetime.now(timezone.utc))


def recompute(actor, snapshot_id, reason, *, now=None):
    require_owner(actor)
    if not reason.strip() or len(reason) > 2000:
        raise MarketingError("REASON_REQUIRED", "Explain why a new calculation is needed.", 422)
    with s.connection(write=True) as c:
        original = s.get(c, "snapshot", snapshot_id)
        period = {key: original["report"]["period"][key] for key in ("starts_on", "ends_on")}
        return _freeze(c, actor, (original["name"][:120] + " · пересчёт"), period, settings(c)["version"],
                       now or datetime.now(timezone.utc), recomputed_from=snapshot_id, reason=reason)


def compare(first_id, second_id=None, *, period=None, now=None):
    with s.connection() as c:
        first = s.get(c, "snapshot", first_id)
        second = s.get(c, "snapshot", second_id) if second_id else {"report": _calculate(c, period, now or datetime.now(timezone.utc))}
    return snapshots.compare(first, second)


def freeze_closed_week(now):
    """The owner opts in once; a retry cannot rewrite this closed-week cut."""
    with s.connection(write=True) as c:
        configured = settings(c)
        if not configured["data"]["automatic_weekly"]:
            return False
        monday = date.fromisoformat(current_week(now)["starts_on"])
        previous = monday - timedelta(days=7)
        key = f"weekly:{configured['data']['dataset']}:{previous}"
        if s.get(c, "snapshot", key, required=False):
            return False
        _freeze(c, {"id": "worker", "role": "coordinator"}, f"Неделя {previous} — {monday}",
                {"starts_on": previous.isoformat(), "ends_on": monday.isoformat()}, configured["version"], now,
                id=key, automatic=True)
        return True


class Review(Input):
    decisions: str = Field(max_length=6000)
    next_actions: str = Field(max_length=6000)


def save_review(actor, period, data, expected_version):
    require_owner(actor)
    period = Period.model_validate(period).model_dump(mode="json")
    value = Review.model_validate(data).model_dump()
    with s.connection(write=True) as c:
        dataset = settings(c)["data"]["dataset"]
        return s.put(c, "report_review", {"id": report_activity.review_id(dataset, period), "dataset": dataset,
                     "period": period, **value}, actor=actor, action="report_reviewed", expected_version=expected_version)


def request_analysis(actor, period, *, now=None):
    from . import agents
    require_owner(actor)
    report = report_activity.aggregate(calculate(period, now=now))
    report.pop("analysis", None)
    return agents.start(actor, kind="report", message="Проанализируйте подтверждённый отчёт: план-факт, ограничения данных, следующий тест и предложения владельцу. Не меняйте цель или бюджет.", report_context=report)
