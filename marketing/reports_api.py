"""Authenticated report commands; metric values are never accepted from a browser."""
import csv
import io
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import Field

from admin_control.api import ControlRoute, reply
from . import report_activity, reports, store as s, website
from .analytics import Event
from .event_ledger import Correction
from .analytics_config import AnalyticsSettings
from .models import Input
from .report_coverage import Coverage

router = APIRouter(prefix="/reports", route_class=ControlRoute)


class SaveSettings(Input):
    data: AnalyticsSettings
    expected_version: int = Field(ge=0)


class WebsiteSettings(Input):
    data: website.Settings
    expected_version: int = Field(ge=0)


class WebsiteRead(Input):
    expected_version: int = Field(ge=0)


class Import(Input):
    events: list[Event] = Field(default_factory=list, max_length=10000)
    coverage: list[Coverage] = Field(default_factory=list, max_length=100)
    corrections: list[Correction] = Field(default_factory=list, max_length=1000)


class Freeze(Input):
    name: str = Field(min_length=1, max_length=150)
    period: reports.Period
    expected_settings_version: int = Field(ge=0)


class Recompute(Input):
    reason: str = Field(min_length=1, max_length=2000)


class Compare(Input):
    first_id: str
    second_id: str | None = None
    period: reports.Period | None = None


class SaveReview(Input):
    period: reports.Period
    data: reports.Review
    expected_version: int = Field(ge=0)


@router.put('/website')
def configure_website(request: Request, body: WebsiteSettings):
    website.configure(request.state.control_actor, body.data.model_dump(mode='json'), body.expected_version)
    with s.connection() as c:
        return reply(request, {'item': website.status(c)['settings']})


@router.post('/website/sync')
def sync_website(request: Request, body: WebsiteRead):
    from .errors import require_owner
    require_owner(request.state.control_actor)
    worked = website.run_one(force=True, expected_version=body.expected_version)
    with s.connection() as c:
        return reply(request, {'worked': worked, 'website': website.status(c)})


@router.put("/settings")
def save_report_settings(request: Request, body: SaveSettings):
    return reply(request, {"item": reports.save_settings(request.state.control_actor, body.data.model_dump(mode="json"), body.expected_version)})


@router.post("/import")
def import_report_events(request: Request, body: Import):
    return reply(request, reports.import_events(request.state.control_actor, [row.model_dump(mode="json") for row in body.events],
                                               [row.model_dump(mode="json") for row in body.coverage],
                                               corrections=[row.model_dump(mode="json") for row in body.corrections]))


@router.post("/calculate")
def calculate_report(request: Request, body: reports.Period):
    return reply(request, {"report": reports.calculate(body.model_dump(mode="json"))})


@router.post("/snapshots")
def freeze_report(request: Request, body: Freeze):
    return reply(request, {"item": reports.freeze(request.state.control_actor, body.name, body.period.model_dump(mode="json"), body.expected_settings_version)})


@router.post("/snapshots/{snapshot_id}/recompute")
def recompute_report(request: Request, snapshot_id: str, body: Recompute):
    return reply(request, {"item": reports.recompute(request.state.control_actor, snapshot_id, body.reason)})


@router.post("/compare")
def compare_reports(request: Request, body: Compare):
    return reply(request, reports.compare(body.first_id, body.second_id, period=body.period.model_dump(mode="json") if body.period else None))


@router.put("/review")
def save_report_review(request: Request, body: SaveReview):
    return reply(request, {"item": reports.save_review(request.state.control_actor, body.period.model_dump(mode="json"), body.data.model_dump(), body.expected_version)})


@router.post("/analysis")
def request_report_analysis(request: Request, body: reports.Period):
    return reply(request, {"item": reports.request_analysis(request.state.control_actor, body.model_dump(mode="json"))})


@router.get("/snapshots/{snapshot_id}/export")
def export_report(request: Request, snapshot_id: str, format: Literal["json", "csv"] = "json"):
    with s.connection() as c:
        snapshot = s.get(c, "snapshot", snapshot_id)
    report = report_activity.aggregate(snapshot['report'])
    if format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        keys = ("title", "value", "unit", "currency", "numerator", "denominator", "status", "formula", "definition_version", "reason")
        writer.writerow(["metric", *keys, "starts_on", "ends_on", "cutoff"])
        for key, metric in report["metrics"].items():
            cells = [key, *(metric.get(field) for field in keys), *(report["period"][field] for field in ("starts_on", "ends_on", "cutoff"))]
            writer.writerow(["'" + cell if isinstance(cell, str) and cell.startswith(("=", "+", "-", "@")) else cell for cell in cells])
        data, mime = stream.getvalue().encode("utf-8-sig"), "text/csv"
    else:
        data, mime = s.encode(report).encode("utf-8"), "application/json"
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="report-{s.digest(snapshot_id)[:16]}.{format}"',
                    "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
