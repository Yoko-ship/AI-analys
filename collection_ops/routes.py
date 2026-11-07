"""Human reads/retries and separate machine-only observation/dispatch endpoints."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from collection_ops import store
from server.auth.access import _require_admin, _require_admin_user

router = APIRouter(prefix="/api/admin/collections", tags=["collection operations"])

class Receipt(BaseModel):
    stage: str = Field(max_length=160)
    ok: bool
    event_id: str = Field(default="", max_length=64)
    phase: Literal["collection", "publication"] = "publication"
    counts: dict[str, int] = Field(default_factory=dict, max_length=20)
    reason: str = Field(default="", max_length=2000)
    unchanged: bool = False

class Observation(BaseModel):
    job: str = Field(max_length=64)
    invocation: str = Field(default="", max_length=64)
    started_at: str | None = Field(default=None, max_length=64)
    finished_at: str | None = Field(default=None, max_length=64)
    active: bool = False
    load_state: str = Field(default="not-found", max_length=32)
    result: str = Field(default="", max_length=64)
    exit_code: int | None = None
    timer_enabled: bool = False
    timer_active: bool = False
    next_run: str | None = Field(default=None, max_length=64)
    evidence: str = Field(default="", max_length=12000)
    evidence_truncated: bool = False
    receipts: list[Receipt] = Field(default_factory=list, max_length=100)

class Report(BaseModel):
    items: list[Observation] = Field(max_length=20)

class Ack(BaseModel):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    status: Literal["dispatched", "failed", "uncertain"]
    invocation: str = Field(default="", max_length=64)
    detail: str = Field(default="", max_length=2000)

def perform(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except store.OperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

@router.get("")
def read_collections(_=Depends(_require_admin_user)):
    return store.overview()

@router.post("/report")
def report_collections(body: Report, _=Depends(_require_admin)):
    return perform(store.report, [item.model_dump() for item in body.items])

@router.post("/claim")
def claim_request(_=Depends(_require_admin)):
    return {"request": store.claim()}

@router.post("/ack")
def acknowledge_request(body: Ack, _=Depends(_require_admin)):
    return perform(store.ack, body.id, body.status, body.invocation, body.detail)

@router.post("/{job}/run")
def run_collection(job: str, user=Depends(_require_admin_user)):
    return perform(store.enqueue, job, actor_id=user.id)

@router.get("/{job}/runs/{invocation}")
def read_run(job: str, invocation: str, _=Depends(_require_admin_user)):
    return perform(store.read_run, job, invocation)

@router.post("/requests/{request_id}/release")
def release_request(request_id: str, user=Depends(_require_admin_user)):
    return perform(store.release, request_id, actor_id=user.id)
