from __future__ import annotations

from dotenv import load_dotenv

# Configuration must be loaded before project modules bind adapters.
load_dotenv()

from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from issuer_analysis_api import router as issuer_analysis_v1_router
from server.settings import PROJECT_ROOT
import admin_control.api as control_api
import admin_railway
import analytics_api
import os
import sector_admin_api
import v3_api
import server.data_quality.routes as data_quality_routes
import server.accounts.notifications as accounts_notifications
import server.accounts.routes as accounts_routes
import server.audit.routes as audit_routes
import server.auth.access as auth_access
import server.auth.routes as auth_routes
import server.bonds.routes as bonds_routes
import server.catalog.routes as catalog_routes
import server.company.financial_routes as company_financial_routes
import server.company.history_routes as company_history_routes
import server.company.routes as company_routes
import server.currency.routes as currency_routes
import server.http as http
import server.ingestion.routes as ingestion_routes
import server.lifecycle as lifecycle
import server.market.routes as market_routes
import server.news.routes as news_routes
import server.research.routes as research_routes
import server.system.routes as system_routes


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "*").strip()
    if not raw or raw == "*":
        return ["*"]
    return [item.strip() for item in raw.split(",") if item.strip()]


# ТЗ §10.10: /docs and /openapi.json describe every route including the ones
# authorisation protects, together with their request shapes. That is a fine
# thing to hand a developer on staging and a poor thing to publish.
_EXPOSE_SCHEMA = os.getenv("APP_ENV", "production").strip().lower() in {"local", "dev", "staging"}


app = FastAPI(
    title="UZ Stock Analyzer API", version="1.2.0",
    docs_url="/docs" if _EXPOSE_SCHEMA else None,
    redoc_url="/redoc" if _EXPOSE_SCHEMA else None,
    openapi_url="/openapi.json" if _EXPOSE_SCHEMA else None,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(issuer_analysis_v1_router)


WEB_SOURCE_DIR = (PROJECT_ROOT / "web")


WEB_DIST_DIR = WEB_SOURCE_DIR / "dist"


WEB_DIR = WEB_DIST_DIR if (WEB_DIST_DIR / "index.html").exists() else WEB_SOURCE_DIR


ASSET_DIR = WEB_DIR / "assets" if WEB_DIR == WEB_DIST_DIR else WEB_DIR


class _ImmutableAssets(StaticFiles):
    """Content-hashed bundles, cached for a year (ТЗ §10.9).

    Vite writes the content hash into every asset filename, so `index-a1b2c3.js`
    can never change meaning — a new build is a new name. Serving it with no
    cache header at all, which is what happened before, made the browser
    revalidate a file that is immutable by construction on every single load.
    """

    def file_response(self, *args, **kwargs):  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


if ASSET_DIR.exists():
    app.mount("/assets", _ImmutableAssets(directory=ASSET_DIR), name="assets")


LOGO_DIR = (PROJECT_ROOT / "logos")


if LOGO_DIR.exists():
    app.mount("/logos", StaticFiles(directory=LOGO_DIR), name="logos")


app.include_router(analytics_api.public_router)


app.include_router(analytics_api.admin_router, dependencies=[Depends(auth_access._admin_panel_gate)])


app.include_router(admin_railway.router, dependencies=[Depends(auth_access._admin_panel_gate)])


app.include_router(control_api.router, dependencies=[Depends(auth_access._control_gate)])
app.include_router(v3_api.router, dependencies=[Depends(auth_access._control_gate)])


app.include_router(sector_admin_api.router, dependencies=[Depends(auth_access._sector_analysis_gate)])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def index() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend is not built yet")
    return FileResponse(
        index_path,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# ТЗ §10.11 — v2 lives BESIDE v1, and v1 is switched off only after the
# acceptance set passes. Every /api route is therefore also reachable under
# /api/v2 with the same handler: no fork, no second implementation, nothing to
# drift. Clients migrate at their own pace and a rollback is a URL, not a
# release.
#
# Registered here, before the SPA catch-all: FastAPI matches in registration
# order, and a catch-all added first would swallow every v2 path.
# ---------------------------------------------------------------------------

def _mount_v2_alias() -> int:
    from fastapi.routing import APIRoute

    aliased = 0
    for route in list(app.router.routes):
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if not path.startswith("/api/") or path.startswith("/api/v2/"):
            continue
        app.router.add_api_route(
            f"/api/v2{path[len('/api'):]}",
            route.endpoint,
            methods=list(route.methods or []),
            response_model=route.response_model,
            status_code=route.status_code,
            dependencies=list(route.dependencies or []),
            summary=route.summary,
            description=route.description,
            # Out of the schema: one route documented twice reads as two
            # different endpoints, which is the confusion this alias avoids.
            include_in_schema=False,
            name=f"{route.name}__v2" if route.name else None,
            route_class_override=type(route),
        )
        aliased += 1
    return aliased


app.include_router(research_routes.router)
app.include_router(auth_routes.router)
app.include_router(accounts_routes.router)
app.include_router(catalog_routes.router)
app.include_router(ingestion_routes.router)
app.include_router(news_routes.router)
app.include_router(market_routes.router)
app.include_router(currency_routes.router)
app.include_router(bonds_routes.router)
app.include_router(system_routes.router)
app.include_router(audit_routes.router)
app.include_router(company_routes.router)
app.include_router(company_financial_routes.router)
app.include_router(company_history_routes.router)
app.include_router(accounts_notifications.router)
app.include_router(data_quality_routes.router)

@app.on_event("startup")
async def _on_startup():
    await lifecycle._on_startup(app)


@app.on_event("shutdown")
async def _on_shutdown():
    await lifecycle._stop_sector_analysis_worker(app)


API_V2_ROUTES = _mount_v2_alias()


http.logger.info("api: %d routes also served under /api/v2", API_V2_ROUTES)


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str) -> FileResponse:
    """Serve the SPA shell for client-side routes (/market, /heatmap, /catalog…).

    Registered last so real API and static routes match first; unknown /api
    paths still resolve to a JSON 404 instead of the HTML shell.
    """
    if full_path == "api" or full_path.startswith(("api/", "assets/", "logos/")) or full_path == "health":
        raise HTTPException(status_code=404, detail="Not found")
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend is not built yet")
    return FileResponse(
        index_path,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )
