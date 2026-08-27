"""Versioned issuer and comparative-analysis API.

This module is the Lite-first HTTP contract from the issuer/comparison
specification.  It deliberately builds on the project's existing catalog,
provenance, bond and news stores: values are never invented and every numeric
observation identifies the period, reporting standard, unit and source used.

The legacy ``/api/compare`` endpoint remains available for the interactive UI.
This router adds reproducible, snapshot-backed runs suitable for API clients.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import sqlite3
import statistics
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator

import bonds as bond_math
import corporate_actions
import dividends
import news_store
import provenance
from reports_catalog import (
    get_all_financials,
    get_all_quotes,
    get_all_ratios,
    get_all_trade_stats,
    get_company_index,
    get_company_reports,
    get_financials_series,
    get_financials_series_quarterly,
)
from securities_catalog import get_securities_map


router = APIRouter(prefix="/api/v1", tags=["issuer comparative analysis"])

API_VERSION = "issuer-comparison-v1.0"
DEFAULT_ISSUER_METRICS = (
    "revenue",
    "revenue_growth_pct",
    "net_income",
    "net_income_growth_pct",
    "net_margin_pct",
    "roe_pct",
    "debt_ratio_pct",
    "current_ratio",
)
DEFAULT_STOCK_METRICS = (
    "latest_price",
    "price_change_pct",
    "turnover",
    "trade_count",
    "revenue_growth_pct",
    "net_margin_pct",
    "roe_pct",
)
DEFAULT_BOND_METRICS = (
    "latest_price",
    "price_pct",
    "coupon_rate_pct",
    "ytm_pct",
    "duration_years",
    "years_to_maturity",
    "turnover",
)

METRIC_DEFINITIONS: dict[str, dict[str, Any]] = {
    "revenue": {"label": "Revenue", "unit": "thousand UZS", "direction": "higher", "level": "issuer"},
    "revenue_growth_pct": {"label": "Revenue growth", "unit": "%", "direction": "higher", "level": "issuer"},
    "net_income": {"label": "Net income", "unit": "thousand UZS", "direction": "higher", "level": "issuer"},
    "net_income_growth_pct": {"label": "Net income growth", "unit": "%", "direction": "higher", "level": "issuer"},
    "net_margin_pct": {"label": "Net margin", "unit": "%", "direction": "higher", "level": "issuer"},
    "roe_pct": {"label": "ROE", "unit": "%", "direction": "higher", "level": "issuer"},
    "roa_pct": {"label": "ROA", "unit": "%", "direction": "higher", "level": "issuer"},
    "debt_ratio_pct": {"label": "Liabilities / assets", "unit": "%", "direction": "lower", "level": "issuer"},
    "debt_to_equity": {"label": "Debt / equity", "unit": "x", "direction": "lower", "level": "issuer"},
    "current_ratio": {"label": "Current ratio", "unit": "x", "direction": "higher", "level": "issuer", "sectors": ["nonbank"]},
    "quick_ratio": {"label": "Quick ratio", "unit": "x", "direction": "higher", "level": "issuer", "sectors": ["nonbank"]},
    "nim_pct": {"label": "Net interest margin", "unit": "%", "direction": "higher", "level": "issuer", "sectors": ["bank"]},
    "pe": {"label": "P/E", "unit": "x", "direction": "lower", "level": "stock", "sectors": ["nonbank"]},
    "pb": {"label": "P/B", "unit": "x", "direction": "lower", "level": "stock"},
    "ev_ebitda": {"label": "EV/EBITDA", "unit": "x", "direction": "lower", "level": "stock", "sectors": ["nonbank"]},
    "latest_price": {"label": "Last price", "unit": "UZS", "direction": "neutral", "level": "instrument"},
    "price_change_pct": {"label": "Price change", "unit": "%", "direction": "neutral", "level": "instrument"},
    "turnover": {"label": "Turnover", "unit": "UZS", "direction": "higher", "level": "instrument"},
    "trade_count": {"label": "Trades", "unit": "count", "direction": "higher", "level": "instrument"},
    "coupon_rate_pct": {"label": "Coupon rate", "unit": "%", "direction": "neutral", "level": "bond"},
    "price_pct": {"label": "Price / par", "unit": "%", "direction": "neutral", "level": "bond"},
    "ytm_pct": {"label": "Yield to maturity", "unit": "%", "direction": "higher", "level": "bond"},
    "duration_years": {"label": "Modified duration", "unit": "years", "direction": "lower", "level": "bond"},
    "years_to_maturity": {"label": "Years to maturity", "unit": "years", "direction": "neutral", "level": "bond"},
}

SECTOR_TEMPLATES: dict[str, dict[str, Any]] = {
    "bank": {
        "required_metrics": ["revenue", "net_income", "roe_pct", "roa_pct", "nim_pct", "debt_ratio_pct"],
        "optional_metrics": ["pb"],
        "warning_rules": ["Do not apply EV/EBITDA or industrial liquidity ratios."],
        "paragraph_structure": ["period", "income", "bank_kpis", "funding", "profitability", "strengths", "risks", "conclusion"],
        "version": "1.0",
    },
    "nonbank": {
        "required_metrics": ["revenue", "net_income", "net_margin_pct", "roe_pct", "debt_ratio_pct", "current_ratio"],
        "optional_metrics": ["quick_ratio", "pe", "pb", "ev_ebitda"],
        "warning_rules": ["Do not rank unavailable ownership or cash-flow metrics."],
        "paragraph_structure": ["period", "income", "operations", "debt", "profitability", "strengths", "risks", "conclusion"],
        "version": "1.0",
    },
}


class ComparisonRequest(BaseModel):
    object_type: Literal["issuer", "stock", "bond", "sector"] = "issuer"
    ids: list[str] | None = Field(default=None, max_length=3)
    peer_rule: dict[str, Any] | None = None
    as_of_date: date | None = None
    standard: Literal["nsbu", "ifrs"] | None = "nsbu"
    scope: Literal["separate", "consolidated"] = "separate"
    currency: str = Field(default="UZS", min_length=3, max_length=3)
    period: str | None = Field(default=None, max_length=8)
    metrics: list[str] | None = Field(default=None, max_length=8)
    normalization_options: dict[str, Any] = Field(default_factory=dict)
    language: Literal["ru", "uz", "en"] = "ru"

    @model_validator(mode="after")
    def validate_selection(self) -> "ComparisonRequest":
        ids = [str(item or "").strip() for item in (self.ids or []) if str(item or "").strip()]
        if bool(ids) == bool(self.peer_rule):
            raise ValueError("provide either ids or peer_rule")
        if ids and not 2 <= len(dict.fromkeys(item.upper() for item in ids)) <= 3:
            raise ValueError("Lite comparison requires 2 to 3 unique objects")
        self.ids = ids or None
        self.currency = self.currency.upper()
        return self


_RUN_DB_PATH = Path(os.getenv("ISSUER_ANALYTICS_DB", Path(__file__).with_name("data") / "issuer_analytics_v1.sqlite3"))
_RUN_LOCK = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _snapshot_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _normal_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9а-яёўқғҳ]+", " ", str(value or "").lower()).strip()


def _run_connection() -> sqlite3.Connection:
    _RUN_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_RUN_DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS comparison_runs (
               run_id TEXT PRIMARY KEY,
               created_at TEXT NOT NULL,
               snapshot_hash TEXT NOT NULL,
               request_json TEXT NOT NULL,
               result_json TEXT NOT NULL
           )"""
    )
    return conn


def _save_run(run: dict[str, Any]) -> None:
    with _RUN_LOCK, _run_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO comparison_runs VALUES (?, ?, ?, ?, ?)",
            (
                run["run_id"],
                run["created_at"],
                run["snapshot_hash"],
                _canonical(run["request"]),
                _canonical(run),
            ),
        )


def _load_run(run_id: str) -> dict[str, Any]:
    with _RUN_LOCK, _run_connection() as conn:
        row = conn.execute(
            "SELECT result_json FROM comparison_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="comparison run not found")
    return json.loads(row["result_json"])


def _resolve_issuer(identifier: str) -> dict[str, Any]:
    wanted = str(identifier or "").strip()
    if not wanted:
        raise HTTPException(status_code=404, detail="issuer not found")
    upper = wanted.upper()
    securities = get_securities_map()
    ticker = upper if upper in securities else None
    if not ticker:
        ticker = next(
            (key for key, row in securities.items() if str(row.get("isin") or "").upper() == upper),
            None,
        )
    candidates = [ticker] if ticker else list(securities)
    if not ticker:
        for key in candidates:
            idx = get_company_index(key) or {}
            if str(idx.get("org_id") or "") == wanted or _normal_name(idx.get("company_name")) == _normal_name(wanted):
                ticker = key
                break
    if not ticker:
        raise HTTPException(status_code=404, detail="issuer not found")
    security = dict(securities.get(ticker) or {})
    index = dict(get_company_index(ticker) or {})
    return {
        "id": str(index.get("org_id") or ticker),
        "ticker": ticker,
        "tickers": index.get("tickers") or [ticker],
        "isin": security.get("isin"),
        "name": index.get("company_name") or security.get("name") or ticker,
        "sector": index.get("sector") or security.get("sector"),
        "security": security,
        "index": index,
    }


def _standard_form(standard: str) -> str:
    return "NSBU" if standard == "nsbu" else "MSFO"


def _period_key(period: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})(?:Q([1-4]))?", str(period or ""))
    if not match:
        return (0, 0)
    return int(match.group(1)), int(match.group(2) or 4)


def _period_before(period: str) -> str | None:
    year, quarter = _period_key(period)
    if not year:
        return None
    return f"{year - 1}Q{quarter}" if "Q" in period else str(year - 1)


def _report_rows(issuer: dict[str, Any], standard: str) -> list[dict[str, Any]]:
    form = _standard_form(standard)
    availability = ((issuer.get("index") or {}).get("availability") or {}).get(form) or {}
    rows: list[dict[str, Any]] = []
    for kind in ("annual", "quarter"):
        for row in availability.get(kind) or []:
            period = str(row.get("year") or "") + (f"Q{row.get('quarter')}" if row.get("quarter") else "")
            rows.append({**row, "period": period, "period_type": kind})
    if rows:
        return rows
    for row in get_company_reports(issuer["ticker"]):
        if row.get("report_form") != form:
            continue
        period = str(row.get("year") or "") + (f"Q{row.get('quarter')}" if row.get("quarter") else "")
        rows.append({**row, "period": period})
    return rows


def _expected_reporting_period(standard: str, today: date) -> tuple[str, date, bool]:
    if standard == "ifrs":
        period = str(today.year - 1)
        due = date(today.year, 6, 30)
        if today < due:
            period, due = str(today.year - 2), date(today.year - 1, 6, 30)
        return period, due, today < due

    candidates: list[tuple[str, date, date]] = []
    for year in range(today.year - 2, today.year + 1):
        candidates.extend(
            [
                (f"{year}Q1", date(year, 3, 31), date(year, 4, 30)),
                (f"{year}Q2", date(year, 6, 30), date(year, 7, 30)),
                (f"{year}Q3", date(year, 9, 30), date(year, 10, 30)),
                (str(year), date(year, 12, 31), date(year + 1, 3, 31)),
            ]
        )
    ended = [item for item in candidates if item[1] <= today]
    period, _end, due = max(ended, key=lambda item: item[1])
    return period, due, today < due


def _freshness_one(issuer: dict[str, Any], standard: str, today: date | None = None) -> dict[str, Any]:
    today = today or _now().date()
    rows = _report_rows(issuer, standard)
    expected, due, within_window = _expected_reporting_period(standard, today)
    latest = max(rows, key=lambda row: _period_key(row.get("period")), default=None)
    latest_period = latest.get("period") if latest else None
    published = (latest or {}).get("published_at") or (latest or {}).get("synced_at")
    published_day = None
    try:
        published_day = datetime.fromisoformat(str(published).replace("Z", "+00:00")).date() if published else None
    except ValueError:
        pass
    if not latest:
        status = "no_data"
    elif _period_key(latest_period) >= _period_key(expected):
        status = "updated" if published_day and (today - published_day).days <= 30 else "current"
    elif within_window:
        status = "awaiting"
    else:
        gap = (_period_key(expected)[0] * 4 + _period_key(expected)[1]) - (_period_key(latest_period)[0] * 4 + _period_key(latest_period)[1])
        status = "stale" if gap >= (8 if standard == "nsbu" else 2) else "overdue"
    return {
        "standard": standard,
        "expected_period": expected,
        "latest_period": latest_period,
        "expected_due_date": due.isoformat(),
        "status": status,
        "publication_date": published,
        "calculated_at": _now().isoformat(),
        "source": (latest or {}).get("pdf_url") or (latest or {}).get("excel_url"),
    }


def _financial_snapshot(
    issuer: dict[str, Any],
    standard: str,
    period: str | None,
    scope: str,
) -> dict[str, Any]:
    if standard == "ifrs" and period and "Q" in period:
        raise HTTPException(status_code=422, detail="IFRS quarterly data is not part of the market-wide comparable layer")
    ticker = issuer["ticker"]
    form = _standard_form(standard)
    is_quarterly = standard == "nsbu" and bool(period and "Q" in period)
    if standard == "nsbu" and period is None:
        annual_series = get_financials_series(ticker, form)
        quarterly_series = get_financials_series_quarterly(ticker, form)
        selected = max(
            [*(str(key) for key in (annual_series or {})), *(str(key) for key in (quarterly_series or {}))],
            key=_period_key,
            default=None,
        )
        is_quarterly = bool(selected and "Q" in selected)
        series = quarterly_series if is_quarterly else annual_series
    else:
        series = get_financials_series_quarterly(ticker, form) if is_quarterly else get_financials_series(ticker, form)
        selected = period
    available = sorted((str(key) for key in (series or {})), key=_period_key, reverse=True)
    selected = selected or (available[0] if available else None)
    reported_values = dict((series or {}).get(selected) or {}) if selected else {}
    values = dict(reported_values)
    previous_period = _period_before(selected) if selected else None
    previous_reported = dict((series or {}).get(previous_period) or {}) if previous_period else {}
    previous = dict(previous_reported)
    period_basis = "annual"
    if is_quarterly and selected:
        period_basis = "standalone_quarter"
        year, quarter = _period_key(selected)
        previous_year, previous_quarter = _period_key(previous_period or "")
        flow_fields = ("revenue", "net_income", "gross_profit", "operating_income")
        if quarter > 1:
            predecessor = dict((series or {}).get(f"{year}Q{quarter - 1}") or {})
            for field in flow_fields:
                current, prior = _safe_float(reported_values.get(field)), _safe_float(predecessor.get(field))
                values[field] = current - prior if current is not None and prior is not None else None
        if previous_quarter > 1:
            predecessor = dict((series or {}).get(f"{previous_year}Q{previous_quarter - 1}") or {})
            for field in flow_fields:
                current, prior = _safe_float(previous_reported.get(field)), _safe_float(predecessor.get(field))
                previous[field] = current - prior if current is not None and prior is not None else None
    reports = _report_rows(issuer, standard)
    source_doc = next((row for row in reports if row.get("period") == selected), None)
    source = {
        "document_id": (source_doc or {}).get("report_id") or f"catalog:{ticker}:{form}:{selected or 'none'}",
        "url": (source_doc or {}).get("pdf_url") or (source_doc or {}).get("excel_url"),
        "publication_date": (source_doc or {}).get("published_at") or (source_doc or {}).get("synced_at"),
        "provider": "openinfo/catalog",
    }
    observations: dict[str, dict[str, Any]] = {}

    missing = object()

    def add(code: str, value: Any, unit: str, raw_value: Any = missing) -> None:
        number = _safe_float(value)
        reported = number if raw_value is missing else _safe_float(raw_value)
        observations[code] = {
            "metric": code,
            "raw": reported,
            "normalized": number,
            "period": selected,
            "standard": standard,
            "scope": scope,
            "currency": "UZS" if "UZS" in unit else None,
            "unit": unit,
            "source": source,
            "quality": ("normalized" if reported is not None and number is not None and reported != number else "reported") if number is not None else "missing",
        }

    for code in ("revenue", "net_income", "gross_profit", "operating_income", "cash", "total_assets", "total_equity", "total_liabilities"):
        add(code, values.get(code), "thousand UZS", reported_values.get(code))
    ratios = get_all_ratios().get(ticker) or {}
    for source_code, code in (("roe", "roe_pct"), ("roa", "roa_pct"), ("debt_ratio", "debt_ratio_pct"), ("debt_to_equity", "debt_to_equity"), ("current_ratio", "current_ratio"), ("quick_ratio", "quick_ratio")):
        value = values.get(source_code)
        ratio_period = selected
        if value is None and ratios.get(source_code) is not None:
            value = ratios.get(source_code)
            ratio_period = (ratios.get("periods") or {}).get(source_code) or ratios.get("period")
        add(code, value, "%" if code.endswith("_pct") else "x")
        observations[code]["period"] = ratio_period
        if ratio_period and selected and ratio_period != selected:
            observations[code]["quality"] = "different_period"

    def derived(code: str, value: Any, formula: str, unit: str = "%") -> None:
        add(code, value, unit)
        observations[code]["quality"] = "derived" if value is not None else "missing"
        observations[code]["formula"] = formula

    revenue, net_income = _safe_float(values.get("revenue")), _safe_float(values.get("net_income"))
    prev_revenue, prev_income = _safe_float(previous.get("revenue")), _safe_float(previous.get("net_income"))
    derived("revenue_growth_pct", ((revenue - prev_revenue) / abs(prev_revenue) * 100) if revenue is not None and prev_revenue not in (None, 0) else None, "(current-prior)/abs(prior)*100")
    derived("net_income_growth_pct", ((net_income - prev_income) / abs(prev_income) * 100) if net_income is not None and prev_income not in (None, 0) else None, "(current-prior)/abs(prior)*100")
    derived("net_margin_pct", (net_income / revenue * 100) if net_income is not None and revenue not in (None, 0) else None, "net_income/revenue*100")

    payload = {
        "issuer": {key: issuer[key] for key in ("id", "ticker", "name", "sector", "isin")},
        "standard": standard,
        "scope": scope,
        "period": selected,
        "period_basis": period_basis,
        "available_periods": available,
        "previous_comparable_period": previous_period,
        "observations": list(observations.values()),
        "source": source,
    }
    payload["source_snapshot_hash"] = _snapshot_hash(payload)
    payload["quality"] = {
        "traceable": all(item["source"]["document_id"] for item in observations.values() if item["raw"] is not None),
        "missing_metrics": [code for code, item in observations.items() if item["normalized"] is None],
        "warnings": (["requested period is unavailable"] if selected and not values else [])
        + (["NSBU and IFRS are separate layers; this response contains only one standard"]),
    }
    return payload


def _quote_and_trade(issuer: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    isin = str(issuer.get("isin") or "").upper()
    quote = dict(get_all_quotes().get(isin) or {})
    trade = dict(get_all_trade_stats().get(isin) or {})
    security = issuer.get("security") or {}
    if not quote:
        quote = {
            "close_price": security.get("close_price") or security.get("last_price"),
            "trade_date": security.get("last_trade_date"),
        }
    return quote, trade


def _risk_flags(snapshot: dict[str, Any], quote: dict[str, Any]) -> list[dict[str, Any]]:
    obs = {item["metric"]: item.get("normalized") for item in snapshot.get("observations") or []}
    flags: list[dict[str, Any]] = []
    debt = _safe_float(obs.get("debt_ratio_pct"))
    current = _safe_float(obs.get("current_ratio"))
    if debt is not None and debt >= 70:
        flags.append({"code": "high_leverage", "level": "warning", "evidence": {"debt_ratio_pct": debt}})
    if current is not None and current < 1:
        flags.append({"code": "low_current_liquidity", "level": "warning", "evidence": {"current_ratio": current}})
    trade_date = quote.get("trade_date")
    try:
        stale_days = (_now().date() - date.fromisoformat(str(trade_date)[:10])).days if trade_date else None
    except ValueError:
        stale_days = None
    if stale_days is None or stale_days > 7:
        flags.append({"code": "stale_or_missing_price", "level": "information", "evidence": {"trade_date": trade_date}})
    if snapshot.get("quality", {}).get("missing_metrics"):
        flags.append({"code": "incomplete_financial_data", "level": "information", "evidence": {"missing_metrics": snapshot["quality"]["missing_metrics"]}})
    return flags


def _issuer_bonds(issuer: dict[str, Any]) -> list[dict[str, Any]]:
    issuer_name = _normal_name(issuer.get("name"))
    ticker_names = {_normal_name(t) for t in issuer.get("tickers") or []}
    rows = []
    for ticker, reference in provenance.bond_references().items():
        reference_name = _normal_name(reference.get("issuer"))
        if not reference_name or not (reference_name in issuer_name or issuer_name in reference_name or reference_name in ticker_names):
            continue
        coupons = provenance.bond_coupons().get(ticker, [])
        schedule = bond_math.issue_schedule(reference, coupons)
        rows.append({
            **reference,
            "ticker": ticker,
            "cashflow_schedule": schedule,
            "cashflow_status": "available" if (schedule or {}).get("items") else "unavailable",
        })
    return rows


def _events(issuer: dict[str, Any]) -> list[dict[str, Any]]:
    ticker = issuer["ticker"]
    items: list[dict[str, Any]] = []
    try:
        for row in news_store.get_news_for_ticker(ticker, limit=30, days=730):
            items.append({
                "id": row.get("id"),
                "category": row.get("type") or row.get("category"),
                "title": row.get("title"),
                "event_date": row.get("published_at"),
                "effective_date": row.get("event_date"),
                "materiality": row.get("materiality"),
                "source_tier": row.get("source_tier"),
                "source_url": row.get("url"),
            })
    except Exception:
        pass
    for action in corporate_actions.actions_for(ticker):
        items.append({
            "id": f"share-action:{ticker}:{action.ex_date}",
            "category": "share_count_change",
            "title": "Share split" if action.kind == "split" else "Bonus share issue",
            "event_date": action.ex_date,
            "effective_date": action.ex_date,
            "materiality": "high",
            "factor": action.ratio,
            "source_url": action.source,
        })
    for row in dividends.read_snapshot(ticker):
        items.append({
            "id": f"dividend:{ticker}:{row.get('registry_date') or row.get('decision_date')}",
            "category": "dividend",
            "title": "Dividend disclosure",
            "event_date": row.get("registry_date") or row.get("decision_date"),
            "effective_date": row.get("payment_date"),
            "materiality": "high",
            "amount": row.get("amount"),
            "source_url": row.get("source_url"),
        })
    return sorted(items, key=lambda row: str(row.get("event_date") or ""), reverse=True)


def _entity_metrics(identifier: str, object_type: str, standard: str, period: str | None, scope: str) -> dict[str, Any]:
    if object_type == "sector":
        sector = str(identifier or "").strip().lower()
        candidates = [
            ticker for ticker, row in get_securities_map().items()
            if str(row.get("sector") or "").strip().lower() == sector and row.get("type") != "bond"
        ]
        members: list[dict[str, Any]] = []
        seen_issuers: set[str] = set()
        for ticker in candidates:
            try:
                member = _entity_metrics(ticker, "issuer", standard, period, scope)
            except HTTPException:
                continue
            issuer_key = str(member.get("issuer_id") or member["id"])
            if issuer_key in seen_issuers:
                continue
            seen_issuers.add(issuer_key)
            members.append(member)
        if not members:
            raise HTTPException(status_code=404, detail=f"sector {identifier} not found")
        codes = set().union(*(set(member["metrics"]) for member in members))

        def percentile(values: list[float], fraction: float) -> float:
            position = (len(values) - 1) * fraction
            low, high = math.floor(position), math.ceil(position)
            if low == high:
                return values[low]
            return values[low] + (values[high] - values[low]) * (position - low)

        statistics_by_metric: dict[str, dict[str, Any]] = {}
        metrics: dict[str, float | None] = {}
        for code in codes:
            values = sorted(
                value for member in members
                if (value := _safe_float(member["metrics"].get(code))) is not None
            )
            metrics[code] = statistics.median(values) if values else None
            statistics_by_metric[code] = {
                "median": metrics[code],
                "p25": percentile(values, 0.25) if values else None,
                "p75": percentile(values, 0.75) if values else None,
                "min": values[0] if values else None,
                "max": values[-1] if values else None,
                "count": len(values),
                "member_count": len(members),
                "coverage": round(len(values) / len(members), 4),
                "aggregation": "median",
            }
        member_periods = sorted({str(member.get("period")) for member in members if member.get("period")})
        aggregate_source = {
            "type": "sector_aggregate",
            "member_snapshot_hashes": [member.get("source_snapshot_hash") for member in members],
            "statistics": statistics_by_metric,
        }
        return {
            "id": sector,
            "ticker": None,
            "name": sector,
            "sector": sector,
            "sector_type": "sector",
            "period": member_periods[0] if len(member_periods) == 1 else period,
            "source": aggregate_source,
            "source_snapshot_hash": _snapshot_hash(aggregate_source),
            "metrics": metrics,
            "statistics": statistics_by_metric,
            "warnings": (["sector aggregate contains fewer than three issuers"] if len(members) < 3 else [])
            + (["member periods differ; period-sensitive ranking is blocked unless a common period is requested"] if len(member_periods) > 1 else []),
            "member_count": len(members),
        }
    if object_type == "bond":
        ticker = identifier.upper()
        reference = provenance.bond_references().get(ticker)
        if not reference:
            raise HTTPException(status_code=404, detail=f"bond {identifier} not found")
        isin = str(reference.get("isin") or "").upper()
        quote = get_all_quotes().get(isin) or {}
        trade = get_all_trade_stats().get(isin) or {}
        latest_price = _safe_float(quote.get("close_price") or trade.get("close_price"))
        nominal = _safe_float(reference.get("nominal"))
        maturity = None
        try:
            maturity = date.fromisoformat(str(reference.get("maturity_date")))
        except ValueError:
            pass
        years = max(0.0, (maturity - _now().date()).days / 365.0) if maturity else None
        return {
            "id": ticker,
            "ticker": ticker,
            "name": reference.get("issuer") or ticker,
            "sector_type": "bond",
            "period": str(quote.get("trade_date") or _now().date()),
            "source": reference.get("source_url"),
            "metrics": {
                "latest_price": latest_price,
                "price_pct": latest_price / nominal * 100 if latest_price is not None and nominal else None,
                "coupon_rate_pct": _safe_float(reference.get("coupon_rate")),
                "ytm_pct": None,
                "duration_years": None,
                "years_to_maturity": years,
                "turnover": _safe_float(trade.get("total_value") or quote.get("turnover")),
            },
            "warnings": (["cash-flow schedule or market price is insufficient; YTM and duration are not published"]),
        }

    issuer = _resolve_issuer(identifier)
    snapshot = _financial_snapshot(issuer, standard, period, scope)
    obs = {item["metric"]: item.get("normalized") for item in snapshot["observations"]}
    quote, trade = _quote_and_trade(issuer)
    ratios = get_all_ratios().get(issuer["ticker"]) or {}
    latest_financial = get_all_financials(_standard_form(standard)).get(issuer["ticker"]) or {}
    org_type = str(latest_financial.get("org_type") or "").lower()
    sector_type = "bank" if org_type == "bank" else "nonbank"
    metrics = {
        **obs,
        "latest_price": _safe_float(quote.get("close_price")),
        "price_change_pct": _safe_float(quote.get("change_percent")),
        "turnover": _safe_float(trade.get("total_value") or quote.get("turnover")),
        "trade_count": _safe_float(trade.get("trade_count")),
        "pe": _safe_float(ratios.get("pe")),
        "pb": _safe_float(ratios.get("pb")),
        "ev_ebitda": _safe_float(ratios.get("ev_ebitda")),
        "nim_pct": _safe_float(ratios.get("nim")),
    }
    return {
        "id": issuer["ticker"],
        "issuer_id": issuer["id"],
        "ticker": issuer["ticker"],
        "name": issuer["name"],
        "sector": issuer["sector"],
        "sector_type": sector_type,
        "period": snapshot.get("period"),
        "source": snapshot.get("source"),
        "source_snapshot_hash": snapshot["source_snapshot_hash"],
        "metrics": metrics,
        "warnings": snapshot["quality"]["warnings"],
    }


def _metric_warning(metric: str, entities: list[dict[str, Any]], object_type: str) -> dict[str, Any] | None:
    definition = METRIC_DEFINITIONS[metric]
    sectors = set(definition.get("sectors") or [])
    present = {row.get("sector_type") for row in entities}
    if sectors and object_type != "sector" and not present.issubset(sectors):
        return {
            "code": "metric_not_comparable",
            "metric": metric,
            "phase": "preflight",
            "message": f"{metric} is not valid for every selected sector and was not ranked",
        }
    level = definition.get("level")
    if object_type == "issuer" and level in {"stock", "bond"}:
        return {"code": "wrong_object_level", "metric": metric, "phase": "preflight", "message": f"{metric} belongs to {level}, not issuer"}
    if object_type == "bond" and level not in {"bond", "instrument"}:
        return {"code": "wrong_object_level", "metric": metric, "phase": "preflight", "message": f"{metric} is not a bond metric"}
    return None


def _comparison_run(payload: ComparisonRequest) -> dict[str, Any]:
    object_type = payload.object_type
    standard = payload.standard or "nsbu"
    ids = list(payload.ids or [])
    if payload.peer_rule:
        sector = str(payload.peer_rule.get("sector") or "").strip().lower()
        limit = max(2, min(int(payload.peer_rule.get("limit") or 3), 3))
        ids = [ticker for ticker, row in get_securities_map().items() if str(row.get("sector") or "").lower() == sector and row.get("type") != "bond"][:limit]
        if len(ids) < 2:
            raise HTTPException(status_code=422, detail="peer rule resolved fewer than two objects")
    defaults = DEFAULT_BOND_METRICS if object_type == "bond" else DEFAULT_STOCK_METRICS if object_type == "stock" else DEFAULT_ISSUER_METRICS
    metrics = list(dict.fromkeys(payload.metrics or defaults))
    unknown = [metric for metric in metrics if metric not in METRIC_DEFINITIONS]
    if unknown:
        raise HTTPException(status_code=422, detail={"unknown_metrics": unknown})
    entities = [_entity_metrics(identifier, object_type, standard, payload.period, payload.scope) for identifier in ids]
    warnings: list[dict[str, Any]] = []
    blocked: set[str] = set()
    for entity in entities:
        for message in entity.get("warnings") or []:
            warnings.append({
                "code": "object_data_limitation",
                "object_id": entity["id"],
                "phase": "preflight",
                "message": str(message),
            })
    for metric in metrics:
        warning = _metric_warning(metric, entities, object_type)
        if warning:
            warnings.append(warning)
            blocked.add(metric)
    if len(entities) < 3:
        warnings.append({"code": "percentile_requires_three", "phase": "preflight", "message": "percentile and peer score require at least three objects"})
    if payload.currency != "UZS":
        warnings.append({"code": "currency_conversion_unavailable", "phase": "preflight", "message": "no verified FX snapshot was supplied; monetary values remain in UZS"})

    columns: list[dict[str, Any]] = []
    for metric in metrics:
        definition = METRIC_DEFINITIONS[metric]
        values = [(row["id"], _safe_float(row["metrics"].get(metric))) for row in entities]
        available = [value for _id, value in values if value is not None]
        if not available:
            warnings.append({
                "code": "metric_unavailable",
                "metric": metric,
                "phase": "preflight",
                "message": f"{metric} has no verified values and was not ranked",
            })
        normal: dict[str, float | None] = {key: None for key, _value in values}
        ranks: dict[str, int | None] = {key: None for key, _value in values}
        percentiles: dict[str, float | None] = {key: None for key, _value in values}
        if metric not in blocked and available and definition["direction"] != "neutral":
            low, high = min(available), max(available)
            for key, value in values:
                if value is None:
                    continue
                score = 50.0 if high == low else ((value - low) / (high - low) * 100)
                if definition["direction"] == "lower":
                    score = 100 - score
                normal[key] = round(score, 4)
            ordered = sorted(((key, value) for key, value in values if value is not None), key=lambda pair: pair[1], reverse=definition["direction"] == "higher")
            previous = object()
            rank = 0
            for index, (key, value) in enumerate(ordered, start=1):
                if value != previous:
                    rank = index
                ranks[key] = rank
                previous = value
                if len(entities) >= 3:
                    percentiles[key] = round((len(ordered) - rank) / max(1, len(ordered) - 1) * 100, 2)
        columns.append({**definition, "metric": metric, "blocked": metric in blocked, "values": [
            {
                "object_id": row["id"],
                "raw": row["metrics"].get(metric),
                "normalized": normal[row["id"]],
                "rank": ranks[row["id"]],
                "percentile": percentiles[row["id"]],
                "period": row.get("period"),
                "standard": standard if definition["level"] == "issuer" else None,
                "source": row.get("source"),
            }
            for row in entities
        ]})

    leaders = []
    for column in columns:
        ranked = [item for item in column["values"] if item["rank"] == 1]
        if ranked and not column["blocked"]:
            leaders.append({"metric": column["metric"], "object_ids": [item["object_id"] for item in ranked], "value": ranked[0]["raw"]})
    summary = {
        "text": " ".join(
            [f"{item['metric']}: leader {', '.join(item['object_ids'])} ({item['value']})." for item in leaders[:4]]
            + (["Limitations: " + "; ".join(warning["message"] for warning in warnings) + "."] if warnings else [])
        ),
        "leaders": leaders,
        "warnings": warnings,
        "verified_against_table": True,
    }
    charts = []
    chartable = [column for column in columns if not column["blocked"] and any(item["normalized"] is not None for item in column["values"])]
    if chartable:
        charts.append({"type": "bar", "title": "Normalized metrics", "series": [
            {"metric": column["metric"], "values": [{"object_id": item["object_id"], "value": item["normalized"]} for item in column["values"]]}
            for column in chartable
        ]})
    if len(chartable) >= 3:
        charts.append({"type": "radar", "title": "Comparable profile", "axes": [column["metric"] for column in chartable], "series": [
            {"object_id": row["id"], "values": [next(item["normalized"] for item in column["values"] if item["object_id"] == row["id"]) for column in chartable]}
            for row in entities
        ]})

    request_data = payload.model_dump(mode="json")
    snapshot = {"request": request_data, "entities": entities, "table": columns, "warnings": warnings}
    created = _now().isoformat()
    run = {
        "ok": True,
        "api_version": API_VERSION,
        "run_id": uuid.uuid4().hex,
        "created_at": created,
        "snapshot_hash": _snapshot_hash(snapshot),
        "normalization_version": "min-max-directional-v1",
        "request": request_data,
        "objects": [{key: row.get(key) for key in ("id", "issuer_id", "ticker", "name", "sector", "sector_type", "period", "member_count", "statistics")} for row in entities],
        "warnings": warnings,
        "table": {"columns": columns, "row_count": len(entities), "metric_count": len(columns)},
        "charts": charts[:2],
        "summary": summary,
    }
    _save_run(run)
    return run


def _fmt_number(value: Any, lang: str) -> str:
    number = _safe_float(value)
    if number is None:
        return "—"
    text = f"{number:,.2f}".rstrip("0").rstrip(".")
    return text if lang == "en" else text.replace(",", " ").replace(".", ",")


def _ai_report(issuer: dict[str, Any], standard: str, period: str | None, scope: str, lang: str) -> dict[str, Any]:
    snapshot = _financial_snapshot(issuer, standard, period, scope)
    values = {item["metric"]: item for item in snapshot["observations"]}
    available = {key: item["normalized"] for key, item in values.items() if item["normalized"] is not None}
    required = {"revenue", "net_income", "net_margin_pct", "debt_ratio_pct", "roe_pct"}
    sufficient = len(required & set(available)) >= 4
    refs = [
        {"metric": key, "raw": item["raw"], "value": item["normalized"], "period": item["period"], "source": item["source"]}
        for key, item in values.items() if item["normalized"] is not None
    ]
    if not sufficient:
        text = (
            f"За период {snapshot.get('period') or '—'} доступен сокращённый отчёт по {standard.upper()}: подтверждённых показателей недостаточно для полного заключения. "
            "Отсутствующие значения не заменены нулями и не восстановлены предположениями.\n\n"
            "Сопоставление с другим стандартом в этот текст не включено. Для полного отчёта необходим исходный документ с выручкой, прибылью, балансом и показателями рентабельности."
            if lang == "ru" else
            f"A shortened {standard.upper()} report is available for {snapshot.get('period') or '—'} because too few metrics are traceable. Missing values were not replaced by zero or estimates.\n\n"
            "No other reporting standard is mixed into this text. A complete source document with income, balance-sheet and profitability figures is required for the full report."
        )
        paragraphs = text.split("\n\n")
        reason = "insufficient_traceable_metrics"
    else:
        n = lambda key: _fmt_number(available.get(key), lang)
        if lang == "ru":
            paragraphs = [
                f"Отчёт относится только к {standard.upper()} за {snapshot['period']} и уровню {scope}. Он сформирован из одного воспроизводимого снимка источников; показатели другого стандарта, другого периода или уровня консолидации в расчёты не включены. Данные позволяют оценить доходы, прибыль, баланс, рентабельность и основные ограничения, но не являются персональной инвестиционной рекомендацией.",
                f"Выручка за выбранный период составила {n('revenue')} тыс. сум, чистая прибыль — {n('net_income')} тыс. сум. Изменение выручки относительно сопоставимого периода равно {n('revenue_growth_pct')}%, изменение чистой прибыли — {n('net_income_growth_pct')}%. Сравнение выполнено строго с {snapshot.get('previous_comparable_period') or 'недоступным сопоставимым периодом'}; отсутствие базы не интерпретируется как нулевая динамика.",
                f"Чистая маржа составляет {n('net_margin_pct')}%. Валовая прибыль равна {n('gross_profit')} тыс. сум, операционная прибыль — {n('operating_income')} тыс. сум. Эти величины описывают структуру раскрытого результата, однако без примечаний к отчётности нельзя надёжно отделить устойчивые операции от разовых эффектов, переоценок или изменений учётной политики.",
                f"Обязательства составляют {n('total_liabilities')} тыс. сум при активах {n('total_assets')} тыс. сум и капитале {n('total_equity')} тыс. сум. Доля обязательств в активах равна {n('debt_ratio_pct')}%, коэффициент текущей ликвидности — {n('current_ratio')}. Для банков и других финансовых организаций эти показатели читаются по отраслевой методике и не заменяют анализ регуляторного капитала, фондирования и качества активов.",
                f"Рентабельность капитала равна {n('roe_pct')}%, рентабельность активов — {n('roa_pct')}%. Денежные средства на отчётную дату составляют {n('cash')} тыс. сум. Положительное значение прибыли само по себе не доказывает высокое качество денежного потока: в доступном слое нет полной сверки CFO, CAPEX и свободного денежного потока, поэтому такой вывод здесь не делается.",
                "Сильной стороной набора данных является трассируемость показателей до конкретного периода и документа, а также отдельное хранение исходных и расчётных значений. Положительная динамика отмечается только там, где существует сопоставимая база. Значения рентабельности и маржи показываются вместе с периодом, поэтому более старый коэффициент не выдаётся за характеристику текущего квартала.",
                "Основные риски заключаются в возможной неполноте раскрытия, редких рыночных сделках, разнице между оперативной НСБУ и годовой МСФО, а также в отсутствии части отраслевых KPI. Аномалия является поводом для проверки первичного документа, а не обвинением. Итоговый вывод ограничен фактическим состоянием отчётности: перед сравнением с другими эмитентами необходимо сохранить тот же период, стандарт, scope, валюту и отраслевую методику.",
                "Методика отчёта намеренно консервативна. Каждое число берётся из наблюдения со ссылкой на источник, единицей измерения и собственным периодом; расчётные показатели содержат формулу. Пропуск остаётся пропуском, поэтому недостаточная отчётность не улучшает и не ухудшает результат искусственно. Рыночная цена обновляется отдельно от фундаментального текста и не создаёт новую версию этого заключения. Новость также не меняет финансовый факт без первичного документа. Если эмитент опубликует restatement, новую квартальную НСБУ, годовую МСФО, аудиторское мнение или существенное корпоративное событие, снимок и версия отчёта должны быть пересчитаны. До такого обновления вывод следует читать вместе со статусами свежести обоих стандартов, датой последней сделки и перечисленными ограничениями данных. Рейтинг строится только по сопоставимым значениям, пропуски не получают искусственно низкое место, а percentile рассчитывается минимум для трёх объектов. Это сохраняет воспроизводимость анализа и позволяет проверить любой вывод без обращения к предположениям модели.",
            ]
        elif lang == "uz":
            paragraphs = [
                f"Ushbu hisobot faqat {snapshot['period']} davri uchun {standard.upper()} standarti va {scope} darajasiga tegishli. U bitta qayta tiklanadigan manba suratidan tuzilgan; boshqa standart, davr yoki konsolidatsiya darajasidagi raqamlar hisobga qo‘shilmagan. Mavjud ma’lumot daromad, foyda, balans, rentabellik va asosiy cheklovlarni faktlar asosida ko‘rib chiqishga yetadi, ammo bu shaxsiy investitsiya tavsiyasi emas.",
                f"Tanlangan davrda tushum {n('revenue')} ming so‘m, sof foyda esa {n('net_income')} ming so‘m bo‘lgan. Tushumning solishtirma davrga nisbatan o‘zgarishi {n('revenue_growth_pct')}%, sof foydaning o‘zgarishi {n('net_income_growth_pct')}%ni tashkil etadi. Solishtirish aynan {snapshot.get('previous_comparable_period') or 'mavjud bo‘lmagan solishtirma davr'} bilan bajarilgan; baza yo‘q bo‘lsa, o‘sish nol deb ko‘rsatilmaydi.",
                f"Sof marja {n('net_margin_pct')}%ni tashkil etadi. Yalpi foyda {n('gross_profit')} ming so‘m, operatsion foyda {n('operating_income')} ming so‘m. Bu qiymatlar e’lon qilingan natijaning tuzilishini ko‘rsatadi, biroq to‘liq izohlar bo‘lmasa, barqaror operatsiyalarni bir martalik ta’sirlar, qayta baholash yoki hisob siyosatidagi o‘zgarishlardan ishonchli ajratib bo‘lmaydi.",
                f"Majburiyatlar {n('total_liabilities')} ming so‘m, aktivlar {n('total_assets')} ming so‘m va kapital {n('total_equity')} ming so‘m. Majburiyatlarning aktivlardagi ulushi {n('debt_ratio_pct')}%, joriy likvidlik koeffitsiyenti {n('current_ratio')}. Banklar va boshqa moliyaviy tashkilotlarda bu raqamlar alohida tarmoq usulida talqin qilinadi hamda regulyativ kapital, moliyalashtirish va aktivlar sifatini tahlil qilish o‘rnini bosmaydi.",
                f"Kapital rentabelligi {n('roe_pct')}%, aktivlar rentabelligi {n('roa_pct')}%. Hisobot sanasidagi pul mablag‘lari {n('cash')} ming so‘m. Ijobiy buxgalteriya foydasi pul oqimining yuqori sifatini o‘z-o‘zidan isbotlamaydi: tekshirilgan qatlamda CFO, CAPEX va erkin pul oqimini to‘liq solishtirish uchun barcha kirish ma’lumotlari yo‘q, shu sababli bunday xulosa chiqarilmagan.",
                "Ma’lumotlar to‘plamining kuchli tomoni — ko‘rsatkichlarning aniq davr va hujjatgacha kuzatilishi, shuningdek dastlabki hamda hisoblangan qiymatlarning alohida saqlanishidir. Ijobiy yoki salbiy yo‘nalish faqat solishtirma baza mavjud joyda qayd etiladi. Rentabellik va marja o‘z davri bilan birga beriladi, shuning uchun eski yillik koeffitsiyent joriy chorak holati sifatida taqdim etilmaydi.",
                "Asosiy xavflar oshkor etishning to‘liq bo‘lmasligi, bozordagi bitimlarning kamligi, tezkor NSBU bilan yillik IFRS o‘rtasidagi farq va ayrim tarmoq KPIlarining mavjud emasligidir. Anomaliya birlamchi hujjatni tekshirish uchun signal bo‘lib, avtomatik ayblov emas. Boshqa emitentlar bilan taqqoslashda davr, standart, scope, valyuta va tarmoq metodikasi bir xil saqlanishi kerak.",
                "Hisobot metodikasi ataylab ehtiyotkor tuzilgan. Har bir raqam manba, o‘lchov birligi va o‘z davriga ega kuzatuvdan olinadi; hisoblangan ko‘rsatkich formulani saqlaydi. Yetishmagan qiymat nolga yoki taxminga aylantirilmaydi. Bozor narxi fundamental matndan alohida yangilanadi va o‘zi yangi versiya yaratmaydi. Yangilik ham birlamchi hujjatsiz moliyaviy faktni o‘zgartirmaydi. Restatement, yangi choraklik NSBU, yillik IFRS, auditor fikri yoki muhim korporativ voqea paydo bo‘lsa, manba surati va hisobot versiyasi qayta hisoblanadi. Ungacha xulosa ikkala standartning yangilik holati, oxirgi bitim sanasi va ko‘rsatilgan cheklovlar bilan birga o‘qilishi kerak. Reyting faqat solishtiriladigan qiymatlar uchun hisoblanadi; ma’lumot yetishmasa obyekt past o‘rin bilan jazolanmaydi. Percentil kamida uchta obyekt bo‘lgandagina beriladi, bir xil qiymatlar esa bir xil o‘rinni oladi. Har bir cheklov API javobida alohida ogohlantirish sifatida qoladi va jadvaldan oldin mijozga ham uzatiladi. Shu yondashuv tahlilni qayta tiklash, har bir xulosani model taxminlarisiz tekshirish va mustaqil auditni osonlashtirish imkonini beradi.",
            ]
        else:
            paragraphs = [
                f"This report covers only {standard.upper()} for {snapshot['period']} at {scope} scope. It is generated from one reproducible source snapshot; figures from another standard, period or consolidation level are excluded. The available data supports a factual review of income, profit, balance-sheet structure and profitability, but it is not a personalized investment recommendation.",
                f"Revenue was {n('revenue')} thousand UZS and net income was {n('net_income')} thousand UZS. Revenue changed by {n('revenue_growth_pct')}% and net income changed by {n('net_income_growth_pct')}% against {snapshot.get('previous_comparable_period') or 'an unavailable comparable period'}. A missing comparison base is not shown as zero growth.",
                f"Net margin was {n('net_margin_pct')}%. Gross profit was {n('gross_profit')} thousand UZS and operating income was {n('operating_income')} thousand UZS. These figures describe the disclosed result, but the current layer cannot reliably separate recurring operations from one-off effects or accounting changes without the complete notes.",
                f"Liabilities were {n('total_liabilities')} thousand UZS against assets of {n('total_assets')} thousand UZS and equity of {n('total_equity')} thousand UZS. Liabilities represented {n('debt_ratio_pct')}% of assets and the current ratio was {n('current_ratio')}. Financial institutions require their sector method; these ratios do not replace capital, funding or asset-quality analysis.",
                f"Return on equity was {n('roe_pct')}% and return on assets was {n('roa_pct')}%. Cash at the reporting date was {n('cash')} thousand UZS. Positive accounting profit does not prove cash-flow quality, and no conclusion about CFO, CAPEX or free cash flow is made where the verified layer does not contain those inputs.",
                "A strength of this result is traceability to a stated period and source document, with reported and calculated values kept distinct. Direction is described only when a comparable base exists. Profitability ratios retain their own period, so an older annual ratio is not presented as a current-quarter fact.",
                "The principal limitations are incomplete disclosure, potentially infrequent market trading, differences between quarterly NSBU and annual IFRS, and unavailable sector-specific KPIs. An anomaly is a prompt to inspect the primary document, not an accusation. Any peer comparison should keep period, standard, scope, currency and sector methodology constant.",
                "The report uses a deliberately conservative method. Every number comes from an observation carrying its source, unit and own reporting period, while calculated values retain their formula. A missing value remains missing, so incomplete disclosure cannot improve or weaken the result artificially. Market price updates separately from the fundamental text and does not create a new version by itself. A news item likewise cannot alter a financial fact without a primary document. A restatement, new quarterly NSBU filing, annual IFRS report, audit opinion or material corporate event requires a new source snapshot and report version. Until then, this conclusion should be read together with the freshness state of both standards, the latest trade date and the listed data limitations. This design keeps the analysis reproducible and makes each factual conclusion independently checkable without relying on assumptions made by a language model.",
            ]
        text = "\n\n".join(paragraphs)
        reason = None
    version_key = {
        "issuer": issuer["id"], "standard": standard, "period": snapshot.get("period"),
        "scope": scope, "lang": lang, "template": SECTOR_TEMPLATES["nonbank"]["version"],
        "source_snapshot_hash": snapshot["source_snapshot_hash"], "text": text,
    }
    return {
        "ok": True,
        "issuer": {key: issuer[key] for key in ("id", "ticker", "name")},
        "standard": standard,
        "period": snapshot.get("period"),
        "scope": scope,
        "language": lang,
        "status": "complete" if sufficient else "shortened",
        "shortened_reason": reason,
        "paragraph_count": len(paragraphs),
        "word_count": len(text.split()),
        "paragraphs": paragraphs,
        "text": text,
        "number_references": refs,
        "source_snapshot_hash": snapshot["source_snapshot_hash"],
        "version": _snapshot_hash(version_key),
        "generated_at": _now().isoformat(),
        "disclaimer": "Information only; not a personalized investment recommendation.",
    }


@router.get("/issuers/{issuer_id}/profile")
def issuer_profile(issuer_id: str) -> dict[str, Any]:
    issuer = _resolve_issuer(issuer_id)
    snapshot = _financial_snapshot(issuer, "nsbu", None, "separate")
    quote, trade = _quote_and_trade(issuer)
    events = _events(issuer)
    bond_rows = _issuer_bonds(issuer)
    dividend_rows = dividends.read_snapshot(issuer["ticker"])
    observations = {item["metric"]: item for item in snapshot["observations"]}
    key_metrics = [observations[key] for key in DEFAULT_ISSUER_METRICS if key in observations][:8]
    return {
        "ok": True,
        "api_version": API_VERSION,
        "issuer": {key: issuer[key] for key in ("id", "ticker", "tickers", "isin", "name", "sector")},
        "market": {
            "last_price": quote.get("close_price"),
            "last_trade_date": quote.get("trade_date"),
            "turnover": trade.get("total_value") or quote.get("turnover"),
            "trade_count": trade.get("trade_count"),
            "source": "UZSE catalog",
        },
        "report_freshness": [_freshness_one(issuer, "nsbu"), _freshness_one(issuer, "ifrs")],
        "key_metrics": key_metrics,
        "dividends": {"count": len(dividend_rows), "latest": dividend_rows[0] if dividend_rows else None},
        "events": events[:8],
        "bonds": {"count": len(bond_rows), "items": bond_rows[:5]},
        "risks": _risk_flags(snapshot, quote),
        "source_snapshot_hash": snapshot["source_snapshot_hash"],
    }


@router.get("/issuers/{issuer_id}/report-freshness")
def issuer_report_freshness(issuer_id: str) -> dict[str, Any]:
    issuer = _resolve_issuer(issuer_id)
    return {"ok": True, "issuer_id": issuer["id"], "ticker": issuer["ticker"], "layers": [_freshness_one(issuer, "nsbu"), _freshness_one(issuer, "ifrs")]}


@router.get("/issuers/{issuer_id}/financial-analysis")
def issuer_financial_analysis(
    issuer_id: str,
    standard: Literal["nsbu", "ifrs"] = Query(...),
    period: str | None = Query(default=None, pattern=r"^\d{4}(?:Q[1-4])?$"),
    scope: Literal["separate", "consolidated"] = "separate",
) -> dict[str, Any]:
    return {"ok": True, "api_version": API_VERSION, **_financial_snapshot(_resolve_issuer(issuer_id), standard, period, scope)}


@router.get("/issuers/{issuer_id}/ai-report")
def issuer_ai_report(
    issuer_id: str,
    standard: Literal["nsbu", "ifrs"] = Query(...),
    period: str | None = Query(default=None, pattern=r"^\d{4}(?:Q[1-4])?$"),
    scope: Literal["separate", "consolidated"] = "separate",
    lang: Literal["ru", "uz", "en"] = "ru",
) -> dict[str, Any]:
    return _ai_report(_resolve_issuer(issuer_id), standard, period, scope, lang)


@router.get("/issuers/{issuer_id}/credit-profile")
def issuer_credit_profile(issuer_id: str, standard: Literal["nsbu", "ifrs"] = "nsbu", period: str | None = None) -> dict[str, Any]:
    issuer = _resolve_issuer(issuer_id)
    snapshot = _financial_snapshot(issuer, standard, period, "separate")
    observations = {item["metric"]: item for item in snapshot["observations"]}
    latest = get_all_financials(_standard_form(standard)).get(issuer["ticker"]) or {}
    method = "bank" if str(latest.get("org_type") or "").lower() == "bank" else "corporate"
    selected = ["cash", "total_liabilities", "total_equity", "debt_ratio_pct", "debt_to_equity", "current_ratio", "quick_ratio"]
    return {
        "ok": True,
        "issuer": {key: issuer[key] for key in ("id", "ticker", "name")},
        "method": method,
        "standard": standard,
        "period": snapshot["period"],
        "metrics": [observations[key] for key in selected if key in observations],
        "bonds": _issuer_bonds(issuer),
        "warnings": (["bank metrics require regulatory capital, funding and asset-quality data"] if method == "bank" else ["maturity schedule and covenants are shown only when disclosed"]),
        "source_snapshot_hash": snapshot["source_snapshot_hash"],
    }


@router.get("/issuers/{issuer_id}/events")
def issuer_events(issuer_id: str, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    issuer = _resolve_issuer(issuer_id)
    items = _events(issuer)[:limit]
    return {"ok": True, "issuer_id": issuer["id"], "ticker": issuer["ticker"], "count": len(items), "items": items}


@router.get("/issuers/{issuer_id}/bonds")
def issuer_bonds(issuer_id: str) -> dict[str, Any]:
    issuer = _resolve_issuer(issuer_id)
    items = _issuer_bonds(issuer)
    return {"ok": True, "issuer_id": issuer["id"], "ticker": issuer["ticker"], "count": len(items), "items": items}


@router.post("/comparisons", status_code=201)
def create_comparison(payload: ComparisonRequest) -> dict[str, Any]:
    return _comparison_run(payload)


@router.get("/comparisons/{run_id}")
def get_comparison(run_id: str) -> dict[str, Any]:
    return _load_run(run_id)


@router.get("/comparisons/{run_id}/table")
def get_comparison_table(run_id: str) -> dict[str, Any]:
    run = _load_run(run_id)
    return {"ok": True, "run_id": run_id, "snapshot_hash": run["snapshot_hash"], "warnings": run["warnings"], "table": run["table"]}


@router.get("/comparisons/{run_id}/charts")
def get_comparison_charts(run_id: str) -> dict[str, Any]:
    run = _load_run(run_id)
    return {"ok": True, "run_id": run_id, "snapshot_hash": run["snapshot_hash"], "charts": run["charts"]}


@router.get("/comparisons/{run_id}/summary")
def get_comparison_summary(run_id: str) -> dict[str, Any]:
    run = _load_run(run_id)
    return {"ok": True, "run_id": run_id, "snapshot_hash": run["snapshot_hash"], "summary": run["summary"]}


@router.get("/comparisons/{run_id}/export.csv")
def export_comparison_csv(run_id: str) -> Response:
    run = _load_run(run_id)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["run_id", "snapshot_hash", "object_id", "metric", "raw", "normalized", "rank", "percentile", "unit", "period", "standard", "source"])
    for column in run["table"]["columns"]:
        for item in column["values"]:
            writer.writerow([
                run_id, run["snapshot_hash"], item["object_id"], column["metric"], item["raw"], item["normalized"], item["rank"], item["percentile"], column["unit"], item["period"], item["standard"], _canonical(item["source"]),
            ])
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="comparison-{run_id}.csv"'},
    )


def _comparison_pdf(run: dict[str, Any]) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="PDF renderer is unavailable") from exc
    buffer = io.BytesIO()
    styles = getSampleStyleSheet()
    story = [Paragraph("Issuer comparative analysis", styles["Title"]), Paragraph(f"Run {run['run_id']} · snapshot {run['snapshot_hash']}", styles["Normal"]), Spacer(1, 8)]
    objects = run["objects"]
    header = ["Metric"] + [row.get("ticker") or row["id"] for row in objects]
    data = [header]
    for column in run["table"]["columns"]:
        values = {item["object_id"]: item["raw"] for item in column["values"]}
        data.append([f"{column['label']} ({column['unit']})"] + [values.get(row["id"]) if values.get(row["id"]) is not None else "—" for row in objects])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([table, Spacer(1, 10), Paragraph(run["summary"]["text"] or "No comparable leaders.", styles["BodyText"]), Spacer(1, 8), Paragraph("Information only; not a personalized investment recommendation.", styles["Italic"])])
    SimpleDocTemplate(buffer, pagesize=landscape(A4), title=f"comparison-{run['run_id']}").build(story)
    return buffer.getvalue()


@router.get("/comparisons/{run_id}/report.pdf")
def export_comparison_pdf(run_id: str) -> Response:
    run = _load_run(run_id)
    return Response(
        content=_comparison_pdf(run),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="comparison-{run_id}.pdf"'},
    )
