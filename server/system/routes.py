from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from functools import partial
from typing import Any
import asyncio
import cache_layer
import formulas
import logo_store
import migrations
import server.auth.access as auth_access
import server.http as http
import server.settings as settings


router = APIRouter()


@router.get("/ready")
async def api_ready() -> Response:
    """Readiness, not liveness (ТЗ §10.4.1/§10.4.6).

    503 while the database is behind the code: serving from a shape the code
    does not expect is not an honest 200. /health stays a liveness probe.
    """
    from reports_catalog import get_catalog_conn

    conn = get_catalog_conn()
    try:
        schema = migrations.status(conn)
    finally:
        conn.close()
    payload = {"ok": schema["ready"], "schema": schema, "cache": cache_layer.backend()}
    return JSONResponse(payload, status_code=200 if schema["ready"] else 503)


@router.post("/api/admin/migrate")
async def api_admin_migrate(_: None = Depends(auth_access._require_admin)) -> dict[str, Any]:
    """Apply pending migrations. Additive only, ordered, recorded, idempotent."""
    from reports_catalog import get_catalog_conn

    loop = asyncio.get_running_loop()

    def _run() -> dict[str, Any]:
        conn = get_catalog_conn()
        try:
            return migrations.upgrade(conn)
        finally:
            conn.close()

    return http._json_safe(await loop.run_in_executor(None, _run))


@router.get("/api/config")
async def api_config(request: Request) -> Response:
    """Thresholds and feature flags the interface is allowed to know about.

    ТЗ §10.10: thresholds are configuration in the repository, not constants in
    code — and the screen reads the same ones the calc layer applied, so a label
    can never claim a window the server did not use.
    """
    return http._etag_json(request, {
        "ok": True,
        "thresholds": formulas.thresholds(),
        "flags": settings.FEATURE_FLAGS,
    }, max_age=300)


@router.post("/api/admin/pg/copy")
async def api_admin_pg_copy(payload: dict[str, Any] | None = None,
                            _: None = Depends(auth_access._require_admin)) -> dict[str, Any]:
    """Copy the SQLite databases into PostgreSQL (ТЗ §10.1, phase one).

    It runs HERE, on the service, because this is where the volume is mounted —
    a developer's machine holds a partial copy with test rows in it, and seeding
    production from that would be worse than not migrating at all.

    Additive and reversible: the copied tables sit beside the web-auth ones, the
    SQLite files are untouched, and nothing that serves a request changes until
    DATABASE_BACKEND is flipped. Pass `{"schema": "..."}` to rehearse into a
    throwaway schema first.
    """
    import pg_migrate

    payload = payload or {}
    loop = asyncio.get_running_loop()
    report = await loop.run_in_executor(None, partial(
        pg_migrate.migrate,
        schema=str(payload.get("schema") or "public"),
        dry_run=bool(payload.get("dry_run")),
        only=payload.get("only")))
    if not report.get("ok"):
        # A partial copy that reports success is how a bad cutover happens.
        return JSONResponse(http._json_safe(report), status_code=500)
    return http._json_safe(report)


@router.post("/api/admin/logos/materialise")
async def api_admin_materialise_logos(_: None = Depends(auth_access._require_admin)) -> dict[str, Any]:
    """Pull externally hosted logos into our own storage (Дополнение 1 §Б.7).

    Idempotent — a logo already stored is left alone. Run it after adding a new
    company, or the interface starts depending on somebody else's service again.
    """
    loop = asyncio.get_running_loop()
    return http._json_safe(await loop.run_in_executor(None, logo_store.materialise_all))


@router.get("/api/admin/logos/audit")
async def api_admin_logo_audit(_: None = Depends(auth_access._require_admin)) -> dict[str, Any]:
    """How much of the interface still depends on a third party."""
    return http._json_safe({"ok": True, **logo_store.audit()})
