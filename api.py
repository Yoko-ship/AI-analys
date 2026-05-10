from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from analysis_service import build_summary, run_company_analysis
from company_catalog import COMPANY_CATALOG


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "*").strip()
    if not raw or raw == "*":
        return ["*"]
    return [item.strip() for item in raw.split(",") if item.strip()]


app = FastAPI(title="UZ Stock Analyzer API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    company: str = Field(..., min_length=1, max_length=200)
    force_refresh: bool = False
    include_html: bool = False
    include_raw: bool = False


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/companies")
async def api_companies() -> dict[str, Any]:
    return {
        "ok": True,
        "count": len(COMPANY_CATALOG),
        "companies": [
            {"company_name": name, "ticker": ticker}
            for name, ticker in COMPANY_CATALOG.items()
        ],
    }


@app.post("/api/analyze")
async def api_analyze(payload: AnalyzeRequest) -> dict[str, Any]:
    try:
        result = await run_company_analysis(
            payload.company,
            force_refresh=payload.force_refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    response: dict[str, Any] = {
        "ok": True,
        "input": payload.company,
        "company_name": result.get("company_name"),
        "model": result.get("model"),
        "annual_period": result.get("annual_period"),
        "quarterly_period": result.get("quarterly_period"),
        "cost": result.get("cost"),
        "from_cache": result.get("from_cache", False),
        "source": result.get("source", "fresh"),
        "summary": build_summary(result),
        "sections": result.get("sections", {}),
        "metrics": result.get("metrics"),
        "liquidity": result.get("liquidity"),
    }

    if payload.include_raw:
        response["raw_analysis"] = result.get("raw_analysis")
    if payload.include_html:
        response["html_report"] = result.get("html_report")

    return _json_safe(response)
