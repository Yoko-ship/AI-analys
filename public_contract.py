"""Public data contracts for financial reports and issuer multipliers.

The calculation engine intentionally keeps its established internal status
vocabulary because the current UI already renders it.  This module adds the
stable, explicit contract required by the public API: a deterministic snapshot,
formula and input disclosure, one of the documented public statuses, and a
freshness decision for every quote used in market capitalisation.

It contains no I/O.  Dates and data rows go in; serialisable dictionaries come
out, which keeps the boundary independently testable.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Sequence

import fundamentals
from formulas import thresholds


CONTRACT_VERSION = "financial-public-v2"
NEW_REPORT_HOURS = 168

CALCULATED = "CALCULATED"
NO_DATA = "NO_DATA"
NOT_MEANINGFUL = "NOT_MEANINGFUL"
NOT_APPLICABLE = "NOT_APPLICABLE"
STALE_PRICE = "STALE_PRICE"
INCOMPLETE_MARKET_CAP = "INCOMPLETE_MARKET_CAP"
DATA_CONFLICT = "DATA_CONFLICT"
CALCULATION_ERROR = "CALCULATION_ERROR"
RECALCULATING = "RECALCULATING"

PUBLIC_CALCULATION_STATUSES = frozenset({
    CALCULATED, NO_DATA, NOT_MEANINGFUL, NOT_APPLICABLE, STALE_PRICE,
    INCOMPLETE_MARKET_CAP, DATA_CONFLICT, CALCULATION_ERROR, RECALCULATING,
})

_CAP_METRICS = frozenset({"pe", "pb", "ps"})
_METRIC_FORMULAS = {
    # These names reflect the inputs the current NSBU store can actually prove.
    # When parent-attributable values and consolidation scope are added to that
    # store, the contract can tighten the basis without mislabelling today's data.
    "pe": "issuer_market_cap / ttm_net_income",
    "pb": "issuer_market_cap / ending_equity",
    "ps": "issuer_market_cap / ttm_revenue",
    "roe": "ttm_net_income / average_equity * 100",
    "roa": "ttm_net_income / average_assets * 100",
    "net_margin": "ttm_net_income / ttm_revenue * 100",
    "equity_assets": "ending_equity / ending_assets * 100",
    "bvps": "ending_equity / total_issuer_shares_outstanding",
}


def _display_value(metric_name: str, metric: dict[str, Any],
                   inputs: dict[str, Any], status: str) -> float | None:
    """Return the numeric candidate the UI may show beside a warning.

    ``value`` remains the calculation-safe field used by rankings and exports.
    A conflicted, stale, loss-making or out-of-range result can still be useful
    to a reader as a number, provided the UI marks it and never promotes it as
    verified. Structurally inapplicable metrics remain blank.
    """
    if status == NOT_APPLICABLE:
        return None
    for candidate in (metric.get("value"), metric.get("computed")):
        number = _number(candidate)
        if number is not None:
            return number
    keys = {
        "pe": ("issuer_market_cap", "ttm_net_income", False),
        "pb": ("issuer_market_cap", "ending_equity", False),
        "ps": ("issuer_market_cap", "ttm_revenue", False),
        "roe": ("ttm_net_income", "average_equity", True),
        "roa": ("ttm_net_income", "average_assets", True),
        "net_margin": ("ttm_net_income", "ttm_revenue", True),
        "equity_assets": ("ending_equity", "ending_assets", True),
        "bvps": ("ending_equity", "total_issuer_shares_outstanding", False),
    }.get(metric_name)
    if not keys:
        return None
    numerator = _number(inputs.get(keys[0]))
    denominator = _number(inputs.get(keys[1]))
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator * (100.0 if keys[2] else 1.0)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw[:10]
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%Y%m%d"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    return None


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, date):
        stamp = datetime.combine(value, time.min)
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _reason(metric: dict[str, Any]) -> str | None:
    if metric.get("note"):
        return str(metric["note"])
    reasons = metric.get("reasons")
    if isinstance(reasons, list) and reasons:
        return "; ".join(str(item) for item in reasons)
    if metric.get("status") and metric.get("status") != fundamentals.STATUS_OK:
        return str(metric["status"])
    return None


def market_class_input(row: dict[str, Any], *, shares_outstanding: Any = None,
                       reference_date: date | None = None) -> dict[str, Any]:
    """Validate one class's quote/share inputs and calculate its usable cap.

    A registry/reference price with no trade date is deliberately rejected.  A
    stale quote is distinct from a missing quote, and a missing share count makes
    the issuer cap incomplete even when the source happens to publish a cap.
    """
    ref = reference_date or date.today()
    limit = int(thresholds()["catalog"].get("inactive_after_days", 90))
    traded = _day(row.get("last_trade_date"))
    price = _number(row.get("last_price"))
    shares = _number(shares_outstanding if shares_outstanding is not None
                     else row.get("shares_outstanding"))
    reported_cap = _number(row.get("market_cap"))

    age = (ref - traded).days if traded else None
    if row.get("last_trade_date") and traded is None:
        status, reason = DATA_CONFLICT, "unreadable last trade date"
    elif traded and traded > ref:
        status, reason = DATA_CONFLICT, "last trade date is in the future"
    elif price is None or price <= 0 or traded is None:
        status, reason = INCOMPLETE_MARKET_CAP, "verified class price is unavailable"
    elif age is not None and age > limit:
        status, reason = STALE_PRICE, f"class price is older than {limit} days"
    elif shares is None or shares <= 0:
        status, reason = INCOMPLETE_MARKET_CAP, "verified outstanding share count is unavailable"
    else:
        status, reason = CALCULATED, None

    # Keep a source cap when one exists so the independent price×shares control
    # can detect a unit mismatch.  Otherwise compute the class cap explicitly.
    cap = (reported_cap if reported_cap is not None and reported_cap > 0
           else price * shares if price and shares else None)
    if status != CALCULATED:
        cap = None

    return {
        "ticker": str(row.get("ticker") or "").upper(),
        "price": price,
        "price_as_of": traded.isoformat() if traded else None,
        "price_source": row.get("source_url") or row.get("price_source"),
        "currency": row.get("currency") or "UZS",
        "price_age_days": age,
        "max_price_age_days": limit,
        "shares_outstanding": shares,
        "shares_as_of": row.get("shares_as_of"),
        "shares_source": row.get("shares_source"),
        "reported_market_cap": reported_cap,
        "market_cap": cap,
        "calculation_status": status,
        "limitation_reason": reason,
        "usable_for_issuer_cap": status == CALCULATED,
    }


def _market_cap_status(classes: Sequence[dict[str, Any]],
                       multiples: dict[str, Any]) -> str:
    statuses = {
        str((item.get("market_input") or {}).get("calculation_status") or "")
        for item in classes
    }
    if STALE_PRICE in statuses:
        return STALE_PRICE
    if DATA_CONFLICT in statuses:
        return DATA_CONFLICT
    if statuses - {CALCULATED} or not classes:
        return INCOMPLETE_MARKET_CAP
    if (multiples.get("market_cap_issuer") or {}).get("value") is None:
        return INCOMPLETE_MARKET_CAP
    return CALCULATED


def _public_status(metric_name: str, metric: dict[str, Any], cap_status: str) -> str:
    if metric_name in _CAP_METRICS and cap_status != CALCULATED:
        return cap_status
    legacy = str(metric.get("status") or "")
    value = metric.get("value")
    if legacy in {fundamentals.STATUS_OK, fundamentals.STATUS_OUT_OF_RANGE}:
        return CALCULATED if value is not None else NO_DATA
    if legacy in {fundamentals.STATUS_LOSS, fundamentals.STATUS_NEGATIVE_EQUITY}:
        return NOT_MEANINGFUL
    if legacy == fundamentals.STATUS_NOT_APPLICABLE:
        return NOT_APPLICABLE
    if legacy in {fundamentals.STATUS_UNVERIFIED, fundamentals.STATUS_INCONSISTENT,
                  "blocked_unit_mismatch", "audit_blocked"}:
        return DATA_CONFLICT
    if legacy == "recalculating":
        return RECALCULATING
    if legacy in {"incomplete", "no_market_cap", "no_share_count"}:
        return INCOMPLETE_MARKET_CAP if metric_name in _CAP_METRICS else NO_DATA
    return NO_DATA


def _snapshot_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def market_inputs_version(inputs: dict[str, Any]) -> str:
    """Content version for the multiples cache, not merely row counts.

    A corrected statement or share count can arrive during the same trading
    session without changing any collection length.  Keying only by date and
    counts therefore served the old result until the next session.  Hash the
    actual dependencies so any material input change creates a new cache entry.
    """
    board = sorted(({
        key: row.get(key) for key in (
            "ticker", "isin", "last_price", "last_trade_date", "market_cap",
            "shares_outstanding", "shares_as_of", "currency",
        )
    } for row in (inputs.get("board") or [])), key=lambda row: str(row.get("ticker") or ""))
    securities = {
        str(ticker): {key: row.get(key) for key in (
            "issuer_id", "org_id", "isin", "type", "is_preferred",
            "shares_outstanding",
        )}
        for ticker, row in sorted((inputs.get("securities") or {}).items(),
                                  key=lambda item: str(item[0]))
    }
    payload = {
        "contract_version": CONTRACT_VERSION,
        "trade_date": inputs.get("trade_date"),
        "board": board,
        "securities": securities,
        "financials": inputs.get("financials") or {},
        "ratios": inputs.get("ratios") or {},
    }
    return _snapshot_id(payload)


def multiplier_contract(multiples: dict[str, Any], classes: Sequence[dict[str, Any]],
                        fin: dict[str, Any] | None, ratio: dict[str, Any] | None,
                        *, market_as_of: Any = None) -> dict[str, Any]:
    """Attach the documented public envelope to an issuer calculation result."""
    result = copy.deepcopy(multiples)
    flows = fundamentals.twelve_month_flows(fin)
    balance = fundamentals.balance_snapshot(fin, ratio)
    cap_status = _market_cap_status(classes, result)
    class_inputs = [copy.deepcopy(item.get("market_input") or {}) for item in classes]
    financial_period = result.get("base_period") or fundamentals.period_label(fin)
    financial_standard = (fin or {}).get("standard") or (fin or {}).get("form") or "NSBU"
    financial_scope = ((fin or {}).get("consolidation_scope")
                       or (fin or {}).get("scope") or "UNKNOWN")
    market_date = str(market_as_of or "") or max(
        (str(item.get("price_as_of")) for item in class_inputs if item.get("price_as_of")),
        default=None,
    )

    flow_values = flows.get("values") or {}
    issuer_cap = (result.get("market_cap_issuer") or {}).get("value")
    total_shares = sum((_number(item.get("shares_outstanding")) or 0.0)
                       for item in class_inputs)
    inputs = {
        "issuer_market_cap": issuer_cap,
        "ttm_net_income": flow_values.get("net_income"),
        "ttm_revenue": flow_values.get("revenue"),
        "ending_equity": balance.get("equity"),
        "average_equity": balance.get("equity_avg"),
        "ending_assets": balance.get("assets"),
        "average_assets": balance.get("assets_avg"),
        "total_issuer_shares_outstanding": total_shares or None,
    }
    metric_inputs = {
        "pe": ("issuer_market_cap", "ttm_net_income"),
        "pb": ("issuer_market_cap", "ending_equity"),
        "ps": ("issuer_market_cap", "ttm_revenue"),
        "roe": ("ttm_net_income", "average_equity"),
        "roa": ("ttm_net_income", "average_assets"),
        "net_margin": ("ttm_net_income", "ttm_revenue"),
        "equity_assets": ("ending_equity", "ending_assets"),
        "bvps": ("ending_equity", "total_issuer_shares_outstanding"),
    }
    snapshot_payload = {
        "contract_version": CONTRACT_VERSION,
        "financial_period": financial_period,
        "financial_standard": financial_standard,
        "financial_scope": financial_scope,
        "market_date": market_date,
        "financial_inputs": inputs,
        "market_inputs": class_inputs,
        "formula_version": CONTRACT_VERSION,
    }
    snapshot_id = _snapshot_id(snapshot_payload)

    for name, keys in metric_inputs.items():
        metric = result.get(name)
        if not isinstance(metric, dict):
            continue
        status = _public_status(name, metric, cap_status)
        metric.update({
            "calculation_status": status,
            "financial_period": metric.get("base_period") or financial_period,
            "financial_standard": financial_standard,
            "financial_scope": financial_scope,
            "market_date": market_date,
            "basis": "issuer",
            "formula": _METRIC_FORMULAS[name],
            "inputs": {key: inputs.get(key) for key in keys},
            "calculation_snapshot": snapshot_id,
        })
        display_value = _display_value(name, metric, inputs, status)
        metric["display_value"] = display_value
        metric["display_warning"] = bool(
            display_value is not None
            and (status != CALCULATED or metric.get("status") == fundamentals.STATUS_OUT_OF_RANGE)
        )
        limitation = _reason(metric)
        if status != CALCULATED and limitation:
            metric["limitation_reason"] = limitation

    result["market_cap_issuer"] = {
        **(result.get("market_cap_issuer") or {}),
        "calculation_status": cap_status,
        "formula": "sum(class_price * class_shares_outstanding)",
        "market_date": market_date,
        "basis": "issuer",
        "class_inputs": class_inputs,
        "calculation_snapshot": snapshot_id,
    }
    result["calculation_snapshot"] = {
        "id": snapshot_id,
        "version": CONTRACT_VERSION,
        "financial_period": financial_period,
        "financial_standard": financial_standard,
        "financial_scope": financial_scope,
        "market_date": market_date,
        "basis": "issuer",
        "dependency_status": {
            "market_cap": cap_status,
            "financial_statement": ("DATA_CONFLICT" if not (result.get("validation") or {}).get("valid", True)
                                    else "AVAILABLE" if fin else "NO_DATA"),
        },
    }
    return result


_PIPELINE_ACTIVE = frozenset({
    "DETECTED", "DISCOVERED", "DOWNLOADING", "DOWNLOADED", "PARSING", "PARSED",
    "VALIDATING", "READY_IN_LIBRARY", "RECALCULATING",
})
_PIPELINE_REVIEW = frozenset({
    "SOURCE_UNAVAILABLE", "PARSER_ERROR", "PARSE_FAILED", "DATA_CONFLICT",
    "NEEDS_REVIEW", "QUALITY_BLOCKED", "PUBLISH_ERROR", "REJECTED",
})


def catalog_report_contract(reports: Iterable[dict[str, Any]], *,
                            now: datetime | None = None) -> list[dict[str, Any]]:
    """Annotate report-library rows without upgrading unknown proof to verified.

    The 168-hour badge is half-open: it is present before the boundary and gone
    at exactly 168 hours.  ``latest_verified`` is emitted only when the input
    explicitly proves verification; legacy catalog rows therefore say
    ``latest_available`` instead of making a stronger claim than the database.
    """
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    rows = [copy.deepcopy(row) for row in reports]
    latest: dict[tuple[Any, ...], int] = {}
    for index, row in enumerate(rows):
        key = (row.get("report_form"), row.get("period_type"), row.get("scope"))
        rank = (int(_number(row.get("year")) or 0),
                int(_number(row.get("quarter")) or 0),
                _timestamp(row.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc))
        previous = latest.get(key)
        if previous is None:
            latest[key] = index
            row["_latest_rank"] = rank
        elif rank > rows[previous]["_latest_rank"]:
            latest[key] = index
            row["_latest_rank"] = rank
    for row in rows:
        row.pop("_latest_rank", None)
    for index in latest.values():
        rows[index]["_is_latest"] = True

    for row in rows:
        is_latest = bool(row.pop("_is_latest", False))
        workflow = str(row.get("pipeline_stage") or row.get("workflow_status")
                       or row.get("state") or "").upper()
        published = _timestamp(row.get("published_at"))
        age = moment - published if published else None
        in_badge_window = bool(age is not None and timedelta(0) <= age < timedelta(hours=NEW_REPORT_HOURS))
        corrected = bool(row.get("corrected") or (_number(row.get("version")) or 0) > 1)
        verified = bool(row.get("verified") or workflow in {"VALIDATED", "PUBLISHED"})

        if workflow in _PIPELINE_REVIEW:
            library_status = "requires_review"
        elif workflow in _PIPELINE_ACTIVE:
            library_status = "processing"
        elif corrected and in_badge_window:
            library_status = "corrected"
        elif in_badge_window:
            library_status = "new"
        elif is_latest:
            library_status = "latest_verified" if verified else "latest_available"
        else:
            library_status = "archive"

        badge_until = (published + timedelta(hours=NEW_REPORT_HOURS)
                       if published and in_badge_window else None)
        row.update({
            "library_status": library_status,
            "is_current": is_latest,
            "verification_status": "VERIFIED" if verified else "UNKNOWN",
            "calculation_eligible": verified,
            "badge": ({"kind": "corrected" if corrected else "new",
                       "window_hours": NEW_REPORT_HOURS,
                       "until": badge_until.isoformat()}
                      if badge_until else None),
        })
    return rows
