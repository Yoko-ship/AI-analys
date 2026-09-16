"""Administrative HTTP contract for the UZStock V3 financial pipeline."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

import v3_financial_pipeline as pipeline

router = APIRouter(prefix="/admin", tags=["UZStock V3"])


def _actor(request: Request) -> str:
    actor = getattr(request.state, "control_actor", None) or {}
    return str(actor.get("email") or "pipeline")


def _require(request: Request, capability: str) -> None:
    """Use the established admin-control role matrix for every V3 mutation."""
    from admin_control.service import require
    require(getattr(request.state, "control_actor", {}), capability)


def _error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": "V3_VALIDATION_ERROR", "message": str(exc)})


class FactsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facts: list[dict[str, Any]] = Field(default_factory=list)


class ResolvePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: dict[str, Any]


class FormulaPreviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer_id: str
    period_end: str


class CalculatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_end: str


class RollbackPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=2000)


@router.post("/openinfo/scan")
def openinfo_scan(request: Request):
    _require(request, "retry")
    return pipeline.scan_openinfo(actor=_actor(request))


@router.get("/issuers/{issuer_id}")
def issuer(issuer_id: str):
    data = pipeline.issuer_snapshot(issuer_id)
    if not data:
        raise HTTPException(status_code=404, detail="issuer not found")
    return data


@router.get("/documents/{document_id}")
def document(document_id: str):
    data = pipeline.document(document_id)
    if not data:
        raise HTTPException(status_code=404, detail="document not found")
    return data


@router.get("/documents/{document_id}/original")
def document_original(document_id: str):
    data = pipeline.original(document_id)
    if data is None:
        raise HTTPException(status_code=404, detail="original not retained locally")
    return Response(data, media_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{document_id}"', "X-Content-Type-Options": "nosniff"})


@router.post("/documents/{document_id}/parse")
def parse_document(document_id: str, payload: FactsPayload, request: Request):
    try:
        _require(request, "retry")
        if payload.facts:
            pipeline.record_facts(document_id, payload.facts, actor=_actor(request))
        return pipeline.reconcile_document(document_id, actor=_actor(request))
    except pipeline.V3Error as exc:
        raise _error(exc) from exc


@router.post("/documents/{document_id}/check")
def check_document(document_id: str, request: Request):
    try:
        _require(request, "retry")
        return pipeline.reconcile_document(document_id, actor=_actor(request))
    except pipeline.V3Error as exc:
        raise _error(exc) from exc


@router.get("/incidents/{incident_id}")
def incident(incident_id: str):
    data = pipeline.incident(incident_id)
    if not data:
        raise HTTPException(status_code=404, detail="incident not found")
    return data


@router.get("/incidents/{incident_id}/evidence")
def incident_evidence(incident_id: str):
    data = pipeline.incident(incident_id)
    if not data:
        raise HTTPException(status_code=404, detail="incident not found")
    return {"id": incident_id, "evidence": data["evidence"], "facts": data["facts"]}


@router.post("/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: str, payload: ResolvePayload, request: Request):
    try:
        _require(request, "comment")
        return pipeline.resolve_incident(incident_id, actor=_actor(request), resolution=payload.resolution)
    except pipeline.V3Error as exc:
        raise _error(exc) from exc


@router.post("/issuers/{issuer_id}/calculate")
def calculate(issuer_id: str, payload: CalculatePayload, request: Request):
    try:
        _require(request, "retry")
        return {"calculations": pipeline.calculate_issuer(issuer_id, payload.period_end, actor=_actor(request))}
    except pipeline.V3Error as exc:
        raise _error(exc) from exc


@router.post("/formula-versions/{formula_id}/preview")
def formula_preview(formula_id: str, payload: FormulaPreviewPayload, request: Request):
    try:
        _require(request, "test")
        return pipeline.preview_formula(formula_id, payload.issuer_id, payload.period_end)
    except pipeline.V3Error as exc:
        raise _error(exc) from exc


@router.post("/publications/{publication_id}/rollback")
def publication_rollback(publication_id: str, payload: RollbackPayload, request: Request):
    try:
        _require(request, "rollback")
        return pipeline.rollback_publication(publication_id, actor=_actor(request), reason=payload.reason)
    except pipeline.V3Error as exc:
        raise _error(exc) from exc


@router.get("/audit")
def audit(limit: int = 100):
    return {"items": pipeline.audit(limit=limit)}
