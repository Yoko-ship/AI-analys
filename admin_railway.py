"""Human-admin Railway monitoring. Credentials and resource scope stay server-side."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
import re
import threading
import time
from typing import Literal
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, StrictBool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/railway")
API_URL = "https://backboard.railway.com/graphql/v2"
DEPLOYMENT_FIELDS = "id status createdAt statusUpdatedAt deploymentStopped canRedeploy"
SNAPSHOT_QUERY = """query AdminRailway($id: String!) {
  environment(id: $id) { id name projectId serviceInstances { edges { node {
    serviceId serviceName cronSchedule nextCronRunAt
    latestDeployment { %s }
  } } } }
}""" % DEPLOYMENT_FIELDS
HISTORY_QUERY = """query AdminRailwayHistory($input: DeploymentListInput!) {
  deployments(input: $input, first: 10) { edges { node { %s } } }
}""" % DEPLOYMENT_FIELDS
DETAIL_QUERY = """query AdminRailwayDeployment($id: String!) {
  deployment(id: $id) { %s projectId environmentId serviceId }
}""" % DEPLOYMENT_FIELDS
_lock = threading.Lock()
_snapshot_cache: dict = {}
_recovery_times: dict = {}


@dataclass(frozen=True)
class Config:
    project_id: str
    environment_id: str
    token: str
    account_token: bool
    recovery_services: frozenset[str]

    @property
    def headers(self):
        return ({"Authorization": f"Bearer {self.token}"} if self.account_token
                else {"Project-Access-Token": self.token})


def config() -> Config | None:
    token = os.getenv("ADMIN_RAILWAY_TOKEN", "").strip()
    account_token = not bool(token)
    token = token or os.getenv("ADMIN_RAILWAY_API_TOKEN", "").strip()
    project = os.getenv("ADMIN_RAILWAY_PROJECT_ID") or os.getenv("RAILWAY_PROJECT_ID", "")
    environment = os.getenv("ADMIN_RAILWAY_ENVIRONMENT_ID") or os.getenv("RAILWAY_ENVIRONMENT_ID", "")
    if not (token and project and environment):
        return None
    return Config(project.strip(), environment.strip(), token, account_token, frozenset(
        value.strip() for value in os.getenv("ADMIN_RAILWAY_RECOVERY_SERVICES", "").split(",")
        if value.strip()))


def require_config() -> Config:
    result = config()
    if result is None:
        raise HTTPException(503, "Railway monitoring is not configured on the server.")
    return result


async def query(cfg: Config, document: str, variables: dict) -> dict:
    # No automatic retries: a lost mutation response may still have taken effect.
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            result = await client.post(API_URL, headers=cfg.headers,
                                       json={"query": document, "variables": variables})
        if result.status_code == 429:
            raise HTTPException(503, "Railway rate limit reached. Wait before refreshing.")
        result.raise_for_status()
        body = result.json()
        if not isinstance(body, dict) or body.get("errors") or not isinstance(body.get("data"), dict):
            raise HTTPException(502, "Railway could not complete the request. Check the server token and its project/environment access.")
        return body["data"]
    except (httpx.HTTPError, ValueError) as exc:
        # Never forward a response body, request headers, or credential-bearing URL.
        raise HTTPException(502, "Railway is unavailable. Refresh to check its current state before retrying any action.") from exc


def redact(value) -> str:
    text = str(value or "")
    # Redact known local secrets as well as common secret formats from other services.
    for key, secret in os.environ.items():
        if len(secret) >= 8 and re.search(r"TOKEN|SECRET|PASSWORD|API_KEY|DATABASE_URL", key, re.I):
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[^\s,;\"']+", r"\1 [REDACTED]", text)
    text = re.sub(r"(?i)([\w-]*(?:token|secret|password|api[_-]?key|authorization|cookie)[\w-]*[\"']?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&]+)", r"\1[REDACTED]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", text)
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    return text[:2000]


def deployment_view(dep: dict | None) -> dict | None:
    if not dep:
        return None
    return {"id": dep["id"], "status": dep.get("status", "UNKNOWN"),
            "created_at": dep.get("createdAt"), "changed_at": dep.get("statusUpdatedAt"),
            "stopped": bool(dep.get("deploymentStopped")),
            "can_redeploy": bool(dep.get("canRedeploy"))}


def recovery_action(service: dict, cfg: Config) -> str | None:
    if service["id"] not in cfg.recovery_services:
        return None
    dep = service.get("deployment") or {}
    if dep.get("status") == "CRASHED":
        return "restart"
    if dep.get("status") == "FAILED" and dep.get("can_redeploy"):
        return "redeploy"
    return None


async def snapshot(cfg: Config, *, fresh: bool = False) -> dict:
    with _lock:
        cached = _snapshot_cache.get(cfg)
        if not fresh and cached and time.monotonic() - cached[0] < 30:
            return cached[1]
    data = await query(cfg, SNAPSHOT_QUERY, {"id": cfg.environment_id})
    env = data.get("environment")
    if not env or env.get("projectId") != cfg.project_id or env.get("id") != cfg.environment_id:
        raise HTTPException(502, "Railway returned a different project or environment. Check the server configuration.")
    services = []
    for edge in env["serviceInstances"]["edges"]:
        node = edge["node"]
        service = {"id": node["serviceId"], "name": node["serviceName"],
                   "cron_schedule": node.get("cronSchedule"), "next_run_at": node.get("nextCronRunAt"),
                   "deployment": deployment_view(node.get("latestDeployment")),
                   "railway_url": f"https://railway.com/project/{cfg.project_id}/service/{node['serviceId']}?environmentId={cfg.environment_id}"}
        service["recovery_action"] = recovery_action(service, cfg)
        services.append(service)
    services.sort(key=lambda s: ((s.get("deployment") or {}).get("status") not in {"CRASHED", "FAILED"}, s["name"].lower()))
    result = {"configured": True, "environment": env["name"], "project_id": cfg.project_id,
              "checked_at": datetime.now(timezone.utc).isoformat(), "services": services}
    with _lock:
        _snapshot_cache.clear()
        _snapshot_cache[cfg] = (time.monotonic(), result)
    return result


async def scoped_service(cfg: Config, service_id: str) -> dict:
    data = await snapshot(cfg, fresh=True)
    service = next((s for s in data["services"] if s["id"] == service_id), None)
    if not service:
        raise HTTPException(404, "Service not found in the configured Railway environment.")
    return service


async def scoped_deployment(cfg: Config, service_id: str, deployment_id: str) -> dict:
    data = await query(cfg, DETAIL_QUERY, {"id": deployment_id})
    dep = data.get("deployment")
    if not dep or (dep.get("projectId"), dep.get("environmentId"), dep.get("serviceId")) != (
            cfg.project_id, cfg.environment_id, service_id):
        raise HTTPException(404, "Deployment not found in this service and environment.")
    return dep


@router.get("")
async def status(response: Response):
    response.headers["Cache-Control"] = "no-store"
    cfg = config()
    return await snapshot(cfg) if cfg else {"configured": False, "services": []}


@router.get("/services/{service_id}/deployments")
async def history(service_id: UUID, response: Response):
    response.headers["Cache-Control"] = "no-store"
    cfg = require_config()
    await scoped_service(cfg, str(service_id))
    data = await query(cfg, HISTORY_QUERY, {"input": {
        "projectId": cfg.project_id, "environmentId": cfg.environment_id, "serviceId": str(service_id)}})
    return {"deployments": [deployment_view(edge["node"]) for edge in data["deployments"]["edges"]]}


@router.get("/services/{service_id}/deployments/{deployment_id}/logs")
async def logs(service_id: UUID, deployment_id: UUID, response: Response,
               kind: Literal["runtime", "build"] = "runtime"):
    response.headers["Cache-Control"] = "no-store"
    cfg = require_config()
    await scoped_deployment(cfg, str(service_id), str(deployment_id))
    field = "buildLogs" if kind == "build" else "deploymentLogs"
    document = f"query AdminRailwayLogs($id: String!) {{ {field}(deploymentId: $id, limit: 80) {{ timestamp message severity }} }}"
    data = await query(cfg, document, {"id": str(deployment_id)})
    rows = [{"timestamp": r.get("timestamp"), "severity": r.get("severity"),
             "message": redact(r.get("message"))} for r in (data.get(field) or [])[-80:]]
    # Evidence only: an error line is not a proven root cause.
    errors = [r["message"] for r in rows if re.search(
        r"error|exception|fatal|out of memory|oom|\[fail\]", r["message"], re.I)]
    return {"kind": kind, "lines": rows, "error_excerpt": errors[-1] if errors else None}


class RecoveryRequest(BaseModel):
    deployment_id: UUID
    action: Literal["restart", "redeploy"]
    confirm: StrictBool


def audit_action(actor, service: dict, payload: RecoveryRequest, request_id: str, outcome: str):
    import web_analytics
    if not web_analytics._available():
        raise RuntimeError("Admin audit database unavailable")
    with web_analytics._conn() as conn:
        web_analytics._write_admin_audit(
            conn, actor_user_id=actor.id, actor_email=actor.email,
            action=f"railway_{payload.action}", target_type="railway_service", target_id=service["id"],
            target_label=service["name"], outcome=outcome, request_id=request_id,
            details={"deployment_id": str(payload.deployment_id)})


@router.post("/services/{service_id}/recover", status_code=202)
async def recover(service_id: UUID, payload: RecoveryRequest, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not payload.confirm:
        raise HTTPException(400, "Confirm the recovery action first.")
    cfg = require_config()
    service_id = str(service_id)
    if service_id not in cfg.recovery_services:
        raise HTTPException(403, "Recovery is not enabled for this service on the server.")
    # Reserve before any await. Concurrent clicks cannot launch duplicate recoveries.
    key = (cfg.project_id, cfg.environment_id, service_id)
    with _lock:
        now = time.monotonic()
        if now - _recovery_times.get(key, -1000) < 60:
            raise HTTPException(429, "Recovery was requested recently. Wait 60 seconds and refresh.")
        _recovery_times[key] = now
    service = await scoped_service(cfg, service_id)
    dep = service.get("deployment") or {}
    if dep.get("id") != str(payload.deployment_id) or recovery_action(service, cfg) != payload.action:
        raise HTTPException(409, "The deployment changed or no longer needs recovery. Refresh first.")
    request_id = uuid4().hex
    actor = request.state.admin_user
    try:
        await asyncio.to_thread(audit_action, actor, service, payload, request_id, "requested")
    except Exception as exc:
        raise HTTPException(503, "Recovery was not sent because the admin audit log is unavailable.") from exc
    field = "deploymentRestart" if payload.action == "restart" else "deploymentRedeploy"
    selection = " { id status }" if payload.action == "redeploy" else ""
    outcome = "unconfirmed"
    try:
        result = await query(cfg, f"mutation AdminRailwayRecovery($id: String!) {{ {field}(id: $id){selection} }}",
                             {"id": str(payload.deployment_id)})
        if not result.get(field):
            raise HTTPException(502, "Railway did not accept the recovery request.")
    except HTTPException:
        outcome = "unconfirmed"
        raise
    else:
        outcome = "accepted"
    finally:
        with _lock:
            _snapshot_cache.clear()
        try:
            await asyncio.to_thread(audit_action, actor, service, payload, request_id, outcome)
        except Exception:
            logger.error("Railway recovery outcome audit unavailable request_id=%s outcome=%s", request_id, outcome)
    return {"accepted": True, "action": payload.action, "request_id": request_id}
