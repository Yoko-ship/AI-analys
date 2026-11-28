"""Machine access only to leased video jobs; never an admin-session fallback."""
from datetime import datetime, timezone
import os
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from admin_control.api import ControlRoute
from . import store, video_files, video_studio as studio
from .models import Input
from .errors import MarketingError


def worker_gate(request: Request):
    expected = os.getenv("MARKETING_VIDEO_WORKER_TOKEN", "")
    authorization = request.headers.get("Authorization", "")
    if len(expected) < 32 or not secrets.compare_digest(authorization, "Bearer " + expected):
        raise MarketingError("WORKER_UNAUTHORIZED", "Video worker authentication required", 401)


router = APIRouter(prefix="/api/marketing-video-worker", tags=["video worker"], route_class=ControlRoute,
                   dependencies=[Depends(worker_gate)])


class Progress(Input):
    lease_token: str = Field(min_length=20, max_length=100)
    stage: Literal["narration", "capturing", "encoding", "uploading"]


@router.post("/claim")
def claim_video():
    return {"job": studio.claim(datetime.now(timezone.utc))}


@router.post("/{identifier}/progress")
def video_progress(identifier: str, body: Progress):
    studio.progress(identifier, body.lease_token, body.stage, datetime.now(timezone.utc))
    return {"ok": True}


@router.post("/{identifier}/fail")
def video_failed(identifier: str, body: Progress):
    studio.fail(identifier, body.lease_token, datetime.now(timezone.utc))
    return {"ok": True}


@router.post("/{identifier}/chunk")
async def upload_video_chunk(identifier: str, request: Request):
    token = request.headers.get("X-Video-Lease", "")
    try:
        offset = int(request.headers.get("X-Video-Offset", "-1"))
    except ValueError:
        raise MarketingError("VIDEO_UPLOAD_OFFSET", "Invalid upload offset", 422) from None
    with store.connection() as c:
        studio.leased(c, identifier, token, datetime.now(timezone.utc))
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 512000:
            raise MarketingError("VIDEO_TOO_LARGE", "Video chunk exceeds upload limit", 413)
    offset = await run_in_threadpool(video_files.append, identifier, token, offset, bytes(content), datetime.now(timezone.utc))
    return {"offset": offset}


@router.post("/{identifier}/complete")
async def complete_video(identifier: str, body: Progress):
    token = body.lease_token
    target = video_files.upload_path(identifier, token)
    try:
        await run_in_threadpool(video_files.finish, identifier, token, target, datetime.now(timezone.utc))
        return {"ok": True}
    finally:
        target.unlink(missing_ok=True)
