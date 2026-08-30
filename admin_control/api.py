"""Human-session API for the operational console. No machine-secret fallback."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import io
import json
import logging

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from . import store as s, service, documents

log = logging.getLogger(__name__)


class ControlRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            request.state.control_request_id = s.uid("req")
            try:
                response = await original(request)
            except (s.ControlError, RequestValidationError) as exc:
                is_validation = isinstance(exc, RequestValidationError)
                status = 422 if is_validation else exc.status
                response = JSONResponse(status_code=status, content={"ok": False, "error": {
                    "code": "VALIDATION_ERROR" if is_validation else exc.code,
                    "message": "Invalid request fields." if is_validation else exc.message,
                    "field_errors": [{"field": ".".join(str(x) for x in e["loc"]), "message": e["msg"]} for e in exc.errors()] if is_validation else [],
                    "request_id": request.state.control_request_id, "retryable": status >= 500}})
            except Exception:
                log.exception("Control request failed: %s", request.state.control_request_id)
                response = JSONResponse(status_code=500, content={"ok": False, "error": {
                    "code": "CONTROL_UNAVAILABLE", "message": "The operation could not be completed. Retry using the same request key.",
                    "field_errors": [], "request_id": request.state.control_request_id, "retryable": True}})
            response.headers["X-Request-ID"] = request.state.control_request_id
            response.headers["Cache-Control"] = "no-store"
            return response
        return handle


router = APIRouter(prefix="/api/admin/control", tags=["admin control"], route_class=ControlRoute)


def actor(request):
    return request.state.control_actor


def reply(request, data):
    return {"ok": True, **data, "request_id": request.state.control_request_id}


@router.get("/session")
def session(request: Request):
    person = actor(request)
    return reply(request, {"actor": person, "environment": s.environment(),
              "capabilities": sorted(service.CAPABILITIES[person["role"]]),
              "mfa_required_for_mutations": person["role"] in {"administrator", "rule_editor"}})


@router.get("/overview")
def overview(request: Request):
    with s.connection() as c:
        return reply(request, service.overview(c))


@router.get("/search")
def search(request: Request, q: str = ""):
    if len(q.strip()) < 2:
        return reply(request, {"items": []})
    with s.connection() as c:
        results = [{**r, "collection": kind} for kind in ("issuers", "documents", "calculations", "incidents", "jobs", "securities")
                   for r in s.query(c, kind, {"q": q[:200]}, limit=5)["items"]]
    return reply(request, {"items": results[:25]})


@router.get("/{collection}/export")
def export(request: Request, collection: str, format: str = "json"):
    service.require(actor(request), "access" if collection == "access" else "export")
    params = dict(request.query_params)
    params.pop("cursor", None)
    if format not in {"csv", "json"}:
        raise s.ControlError("INVALID_FORMAT", "Choose CSV or JSON.", 422)
    with s.connection(write=True) as c:
        items = list(s.all_items(c, collection, params))
        service.require(actor(request), "read")
        s.audit(c, actor(request), "export", collection, "Export filtered registry", request.state.control_request_id,
                new={"filters": params, "rows": len(items), "format": format})
    if format == "json":
        content, media = s.encode(items), "application/json"
    else:
        buffer = io.StringIO()
        fields = sorted(set().union(*(r.keys() for r in items))) if items else ["id"]
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        for item in items:
            safe = {}
            for key, value in item.items():
                value = s.encode(value) if isinstance(value, (list, dict)) else str(value if value is not None else "")
                # Opening the export in Excel must not execute a formula.
                safe[key] = "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value
            writer.writerow(safe)
        content, media = "\ufeff" + buffer.getvalue(), "text/csv"
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="admin-{collection}.{format}"'})


@router.get("/documents/{entity_id}/preview")
def preview(request: Request, entity_id: str, page: int = 1, sheet: str | None = None, start: int = 0, q: str = ""):
    if not 1 <= page <= 10000 or not 0 <= start < 2000:
        raise s.ControlError("INVALID_LOCATION", "Invalid page or row location.", 422)
    with s.connection() as c:
        document = s.get(c, "documents", entity_id)
    return reply(request, documents.preview(document, page=page, sheet=sheet, start=start, query=q[:200]))


@router.get("/documents/{entity_id}/page/{page}")
def page_image(entity_id: str, page: int):
    with s.connection() as c:
        document = s.get(c, "documents", entity_id)
    return Response(documents.pdf_page_image(document, page), media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})


@router.get("/documents/{entity_id}/original")
def original(entity_id: str):
    with s.connection() as c:
        document = s.get(c, "documents", entity_id)
    data = documents.read_original(document)
    kind = documents.detect_format(data)
    return Response(data, media_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{document["checksum"][:16]}.{kind.lower()}"', "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.get("/{collection}/{entity_id}/history")
def history(request: Request, collection: str, entity_id: str):
    if collection == "access":
        service.require(actor(request), "access")
    with s.connection() as c:
        s.get(c, collection, entity_id)
        rows = c.execute("SELECT payload FROM control_revisions WHERE environment=? AND collection=? AND id=? ORDER BY version DESC LIMIT 100",
                         (s.environment(), collection, entity_id)).fetchall()
    return reply(request, {"items": [json.loads(r["payload"]) for r in rows]})


@router.get("/{collection}/{entity_id}")
def detail(request: Request, collection: str, entity_id: str):
    if collection == "access":
        service.require(actor(request), "access")
    with s.connection() as c:
        item = s.get(c, collection, entity_id)
        related = {}
        if collection == "issuers":
            related = {kind: s.query(c, kind, {"ticker": item["ticker"]}, limit=20)["items"] for kind in
                       ("documents", "facts", "calculations", "incidents", "analyses", "securities", "jobs")}
    return JSONResponse(reply(request, {"item": item, "related": related}), headers={"ETag": '"' + str(item["version"]) + '"'})


@router.get("/{collection}")
def registry(request: Request, collection: str, limit: int = 50):
    if collection == "access":
        service.require(actor(request), "access")
    if collection == "audit":
        service.require(actor(request), "read")
    with s.connection() as c:
        return reply(request, s.query(c, collection, dict(request.query_params), limit=limit))


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=2000)
    version: int | None = Field(default=None, ge=1)
    category: str | None = None
    title: str | None = Field(default=None, max_length=200)
    config: dict | None = None
    filters: dict[str, str] | None = None
    incident_id: str | None = None
    role: str | None = None


def verify_mfa(request, person):
    if person["role"] not in {"administrator", "rule_editor"}:
        return
    from web_auth import web_auth_store
    since = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with s.connection() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM control_audit WHERE environment=? AND actor=? AND action='mfa.denied' AND created_at>?",
                      (s.environment(), person["email"], since)).fetchone()["n"]
    if n >= 5:
        raise s.ControlError("RATE_LIMITED", "Too many verification attempts. Try again in a minute.", 429)
    if not web_auth_store.verify_admin_two_factor(person["id"], request.headers.get("X-Admin-OTP", "")):
        raise s.ControlError("MFA_REQUIRED", "Enter a current authenticator code. Enable two-factor authentication in your account settings first.", 403)


@router.post("/{collection}/{entity_id}/{action}")
def mutate(request: Request, collection: str, entity_id: str, action: str, payload: Command):
    person = actor(request)
    data = payload.model_dump(exclude_none=True)
    try:
        verify_mfa(request, person)
        result = s.command(person, request.headers.get("Idempotency-Key"), [collection, entity_id, action, data],
                           request.state.control_request_id,
                           lambda c: service.execute(c, person, collection, entity_id, action, data, request.state.control_request_id))
    except s.ControlError as exc:
        with s.connection(write=True) as c:
            s.audit(c, person, "mfa.denied" if exc.code == "MFA_REQUIRED" else collection + "." + action,
                    entity_id, payload.reason, request.state.control_request_id, new={"error_code": exc.code}, result="denied")
        raise
    return JSONResponse(result, status_code=202 if result.get("job_id") else 200)
