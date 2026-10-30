"""Internal Codex gateway: the one place on the server that holds the Codex login.

A long-running container (``uzstock-codex-gateway``) keeps the subscription login in
its own volume (``CODEX_HOME``) and serves model-only JSON calls to the news
collector over the private Docker network. Collectors never see the credentials;
they send a shared secret and get back the parsed object plus token usage.

    POST /v1/json   {system, user, response_schema?, model?, fallback_model?, effort?, timeout?}
    GET  /health    login state, last success/error, call counters

Log in once on the server (the login then persists across deploys and refreshes itself):

    docker exec -it -u appuser uzstock-codex-gateway codex login --device-auth
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from codex_client import CodexClient, safe_codex_environment
from llm_client import LLMError, Usage

logger = logging.getLogger("codex_gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_SECRET = os.getenv("CODEX_GATEWAY_SECRET", "").strip()
_CONCURRENCY = max(1, int(os.getenv("CODEX_GATEWAY_CONCURRENCY", "1")))
_QUEUE_WAIT = float(os.getenv("CODEX_GATEWAY_QUEUE_WAIT", "300"))
_slots = threading.BoundedSemaphore(_CONCURRENCY)
_auth_cache: dict[str, Any] = {"checked": 0.0, "status": None}
_auth_lock = threading.Lock()
_state: dict[str, Any] = {"last_success_at": None, "last_error_at": None, "last_error": None,
                          "calls": 0, "failures": 0}

app = FastAPI(title="UZStock Codex gateway", docs_url=None, redoc_url=None, openapi_url=None)


class JsonRequest(BaseModel):
    system: str = Field(min_length=1)
    user: str = Field(min_length=1)
    response_schema: dict[str, Any] | None = None
    model: str = "gpt-6-luna"
    fallback_model: str | None = "gpt-6.1-terra"
    effort: str = "low"
    timeout: float = Field(default=180.0, gt=0, le=600)


def _authorize(authorization: str = Header(default="")) -> None:
    if not _SECRET:
        raise HTTPException(503, "CODEX_GATEWAY_SECRET is not configured on the gateway")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), _SECRET.encode()):
        raise HTTPException(401, "invalid gateway secret")


def auth_status(*, max_age: float = 60.0) -> dict[str, Any]:
    """``codex login status`` (no model call), cached briefly."""
    with _auth_lock:
        if _auth_cache["status"] is not None and time.monotonic() - _auth_cache["checked"] < max_age:
            return _auth_cache["status"]
        try:
            completed = subprocess.run(
                [os.getenv("CODEX_EXECUTABLE", "codex"), "login", "status"],
                capture_output=True, text=True, timeout=30, env=safe_codex_environment(),
                check=False,
            )
            logged_in = completed.returncode == 0 and "using ChatGPT" in (completed.stdout + completed.stderr)
            status = {"logged_in": logged_in, "auth_method": "chatgpt" if logged_in else None}
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            status = {"logged_in": False, "auth_method": None, "error": exc.__class__.__name__}
        _auth_cache.update(checked=time.monotonic(), status=status)
        return status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        **auth_status(),
        **_state,
        "rate_limit": None,
        "concurrency": _CONCURRENCY,
    }


@app.post("/v1/json", dependencies=[Depends(_authorize)])
def complete_json(request: JsonRequest) -> dict[str, Any]:
    if not auth_status()["logged_in"]:
        raise HTTPException(502, "Codex gateway is not logged in: run "
                                 "`docker exec -it -u appuser uzstock-codex-gateway codex login --device-auth`")
    if not _slots.acquire(timeout=_QUEUE_WAIT):
        raise HTTPException(503, "Codex gateway is busy")
    try:
        try:
            client = CodexClient(model=request.model, reasoning_effort=request.effort,
                                      fallback_model=request.fallback_model,
                                      timeout=request.timeout)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        usage = Usage()
        try:
            data = client.complete_json(request.system, request.user, usage=usage,
                                        response_schema=request.response_schema)
        except LLMError as exc:
            _state.update(last_error_at=_now(), last_error=str(exc)[:500],
                          failures=_state["failures"] + 1)
            # A failed call may mean the login expired; re-check on the next request.
            _auth_cache["checked"] = 0.0
            raise HTTPException(502, str(exc)[:500]) from exc
        _state.update(last_success_at=_now(), calls=_state["calls"] + 1)
        return {
            "data": data,
            "usage": {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "cached_prompt_tokens": usage.cached_prompt_tokens,
                "calls": usage.calls,
                "model": usage.model,
            },
            "rate_limit": None,
        }
    finally:
        _slots.release()
